"""Envio diário sem depender de uma página aberta."""
import base64
import json
import os
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote
from zoneinfo import ZoneInfo
from pneus_core import enviar_email


def main():
    required = ("PNEUS_GITHUB_TOKEN", "PNEUS_DATA_REPOSITORY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
    if any(not os.environ.get(x) for x in required):
        print("Envio não configurado: complete os secrets do serviço.")
        return
    repo = os.environ["PNEUS_DATA_REPOSITORY"]
    branch = os.environ.get("PNEUS_DATA_BRANCH") or "main"
    url = "https://api.github.com/repos/" + repo + "/contents/dados/estoque_pneus.json"
    headers = {"Authorization": "Bearer " + os.environ["PNEUS_GITHUB_TOKEN"], "Accept": "application/vnd.github+json", "User-Agent": "10Sul-Pneus", "Content-Type": "application/json"}
    def ler():
        with urlopen(Request(url + "?ref=" + quote(branch, safe=""), headers=headers), timeout=30) as resposta:
            arquivo = json.load(resposta)
        return json.loads(base64.b64decode(arquivo["content"])), arquivo["sha"]
    def salvar(dados, sha):
        payload = {"message": "Registrar envio diário do estoque de pneus", "branch": branch, "sha": sha, "content": base64.b64encode(json.dumps(dados, ensure_ascii=False, indent=2).encode()).decode()}
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers, method="PUT"), timeout=30) as resposta:
            json.load(resposta)
    # Antes de tocar na base, confirmar que ela permanece privada.
    with urlopen(Request("https://api.github.com/repos/" + repo, headers=headers), timeout=30) as resposta:
        if not json.load(resposta).get("private"):
            raise RuntimeError("A base de pneus deve ser privada.")
    dados, sha = ler()
    cfg = dados.get("email", {})
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    dia = agora.date().isoformat()
    if not cfg.get("ativo") or not cfg.get("destinatarios") or agora.strftime("%H:%M") < cfg.get("horario", "18:00"):
        print("Fora do horário ou envio desativado.")
        return
    if any(x.get("dia") == dia for x in dados.get("envios", [])):
        print("Dia já processado. Conferir o histórico de envio antes de repetir.")
        return
    registros = [x for x in dados["conferencias"] if x["data_hora"][:10] == dia and datetime.fromisoformat(x["data_hora"]) <= agora]
    if not registros:
        print("Sem conferência hoje; nenhum estoque antigo foi enviado.")
        return
    registro = max(registros, key=lambda x: x["data_hora"])
    envio = {"dia": dia, "conferencia_id": registro["id"], "estado": "processando", "iniciado_em": agora.isoformat(), "destinatarios": cfg["destinatarios"]}
    dados.setdefault("envios", []).append(envio)
    salvar(dados, sha)  # Reservar o dia antes de enviar impede disparos duplicados.
    estado = "enviado"
    try:
        enviar_email(registro, cfg["destinatarios"], dict(os.environ))
    except Exception:
        estado = "verificar_falha"
    for tentativa in range(3):
        dados, sha = ler()
        for item in dados["envios"]:
            if item["dia"] == dia:
                item["estado"] = estado
                item["concluido_em"] = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        try:
            salvar(dados, sha)
            break
        except Exception:
            if tentativa == 2:
                raise
    if estado != "enviado":
        raise RuntimeError("Falha de envio. Confira o servidor e o histórico antes de reenviar manualmente.")
    print("Relatório aceito pelo servidor de e-mail.")


if __name__ == "__main__":
    main()
