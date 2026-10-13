"""Fila durável de relatórios; usada pelo Streamlit e GitHub Actions."""
import base64
import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = 'dados/envios_socorro'
CONFIG = ROOT + '/config.json'
DEFAULT_TO = ['evandrojunior.10sul@suzano.com.br']


def destinatarios(valor):
    partes = re.split(r'[;,\s]+', valor) if isinstance(valor, str) else valor
    if not isinstance(partes, (list, tuple)):
        raise ValueError('Informe os e-mails dos destinatários.')
    emails = []
    for parte in partes:
        email = str(parte).strip()
        if not email:
            continue
        if len(email) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", email):
            raise ValueError('E-mail inválido: ' + email)
        if email.lower() not in [e.lower() for e in emails]:
            emails.append(email)
    if not 1 <= len(emails) <= 50:
        raise ValueError('Informe de 1 a 50 destinatários.')
    return emails


class ArquivosEmail:
    def __init__(self, requisitar, branch='main'):
        self.requisitar = requisitar
        self.branch = branch

    def ler(self, path):
        from urllib.parse import quote
        item = self.requisitar('/contents/' + path + '?ref=' + quote(self.branch, safe=''))
        if item is None:
            return None, None
        return json.loads(base64.b64decode(item['content'])), item['sha']

    def salvar(self, path, data, sha=None):
        body = {'message': 'Estoque Socorro: atualizar envio por e-mail', 'branch': self.branch,
                'content': base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()}
        if sha:
            body['sha'] = sha
        return self.requisitar('/contents/' + path, 'PUT', body)

    def listar(self, pasta):
        from urllib.parse import quote
        items = self.requisitar('/contents/' + ROOT + '/' + pasta + '?ref=' + quote(self.branch, safe='')) or []
        return [x for x in items if x.get('type') == 'file' and x['name'].endswith('.json')]

    def configuracao(self):
        data, sha = self.ler(CONFIG)
        return data or {'destinatarios': DEFAULT_TO, 'automatico': True}, sha

    def solicitar(self, emails):
        import uuid
        ident = str(uuid.uuid4())
        data = {'id': ident, 'tipo': 'manual', 'destinatarios': destinatarios(emails),
                'solicitado_em': datetime.now(timezone.utc).isoformat()}
        self.salvar(ROOT + '/solicitacoes/' + ident + '.json', data)
        return ident

    def historico(self, limite=30):
        # GitHub returns these UUID files by name, so timestamps decide ordering.
        arquivos = self.listar('historico')
        registros = [self.ler(x['path'])[0] for x in arquivos]
        return sorted(registros, key=lambda x: x.get('solicitado_em', ''), reverse=True)[:limite]


def enviar_resend(payload, key, ident):
    req = Request('https://api.resend.com/emails', data=json.dumps(payload).encode(),
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                           'User-Agent': '10Sul-Estoque/2.0', 'Idempotency-Key': 'socorro/' + ident}, method='POST')
    try:
        with urlopen(req, timeout=30) as response:
            result = json.load(response)
            if not result.get('id'):
                return {'status': 'incerto', 'erro': 'Resposta sem ID. Verifique no Resend antes de reenviar.'}
            return {'status': 'aceito', 'resend_id': result['id'], 'aceito_em': datetime.now(timezone.utc).isoformat()}
    except HTTPError as exc:
        return {'status': 'falha', 'erro': f'Resend recusou o envio (HTTP {exc.code}). Confira a chave, o domínio do remetente e os destinatários.'}
    except (URLError, OSError, ValueError):
        return {'status': 'incerto', 'erro': 'Sem confirmação do Resend. Confira no Resend antes de reenviar.'}
