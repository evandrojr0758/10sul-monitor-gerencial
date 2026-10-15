"""Importação de inspeções Mega: histórico imutável, independente da base ASN."""
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime

BUCKET = 'evidencias-desvios'
PREFIX = 'reprovacoes-mega-v1'
MAX_TOTAL = 350 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', texto) if not unicodedata.combining(c)).upper()


def data_campo(texto, campo):
    m = re.search(campo + r'\s*:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})', texto, re.I)
    return datetime.strptime(m[1], '%d/%m/%Y %H:%M').isoformat(timespec='minutes') if m else ''


def ler_pdf(conteudo, nome):
    import pymupdf
    with pymupdf.open(stream=conteudo, filetype='pdf') as doc:
        if len(doc) > 100:
            raise ValueError('PDF com mais de 100 páginas')
        texto = '\n'.join(p.get_text() for p in doc)
    n = normalizar(texto)
    status = re.search(r'\b(REPROVADO|APROVADO(?: NA REINSPECAO)?)\b', n[:500])
    frota = re.search(r'NR\s*CHASSI/GO\s*:\s*(\d{5})\b', n)
    placa = re.search(r'PLACA\s*:\s*([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\b', n)
    numero = re.search(r'NUMERACAO\s*:\s*(\d+)', n)
    vistoria = data_campo(n, 'DATA VISTORIA')
    impressao = data_campo(n, 'DATA IMPRESSAO')
    if not all([status, frota, placa, numero, vistoria, impressao]):
        raise ValueError('Não foi possível identificar resultado, frota, placa, número e datas no PDF; conferir manualmente')
    resultado = 'REPROVADO' if status[1] == 'REPROVADO' else 'APROVADO'
    identidade = '|'.join([frota[1], placa[1], numero[1], vistoria, impressao, resultado])
    observacoes = []
    # Os blocos preservam as observações sem misturar as duas colunas do checklist.
    with pymupdf.open(stream=conteudo, filetype='pdf') as doc:
        for pagina in doc:
            for bloco in pagina.get_text('blocks'):
                for obs in re.findall(r'Observa[çc][ãa]o\s*:\s*(.*)', bloco[4], re.I | re.S):
                    obs = re.split(r'\n(?:NÃO CONFORME|CONFORME|N/A)\b', obs)[0]
                    obs = ' '.join(obs.split())
                    if obs and normalizar(obs) not in {normalizar(x) for x in observacoes}:
                        observacoes.append(obs)
    return dict(id=hashlib.sha256(identidade.encode()).hexdigest(), frota=frota[1],
                placa=placa[1], numero=numero[1], vistoria=vistoria, impressao=impressao,
                resultado=resultado, arquivo=nome, sha_pdf=hashlib.sha256(conteudo).hexdigest(),
                observacoes=observacoes, evento='Não informado', texto=texto)


def importar_zip(conteudo):
    registros, arquivos, avisos = [], {}, []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        itens = z.infolist()
        if len(itens) > 5000 or sum(x.file_size for x in itens) > MAX_TOTAL:
            raise ValueError('Exportação muito grande. Envie um período menor (até 350 MB descompactados).')
        for item in itens:
            if item.is_dir() or not item.filename.lower().endswith('.pdf'):
                continue
            if item.file_size > MAX_FILE:
                avisos.append(f'{item.filename}: PDF acima de 25 MB, não importado.'); continue
            try:
                pdf = z.read(item)
                r = ler_pdf(pdf, item.filename.rsplit('/', 1)[-1])
                registros.append(r); arquivos[r['sha_pdf']] = pdf
            except Exception as exc:
                avisos.append(f'{item.filename}: {exc}')
        textos = [z.read(i).decode('utf-8-sig', errors='replace') for i in itens
                  if i.filename.lower().endswith('.txt') and i.file_size < MAX_FILE]
    if not textos:
        avisos.append('Sem histórico TXT; registros extraídos somente dos PDFs.')
    # O TXT é preservado como fonte; datas e identificadores vêm dos documentos.
    # Mensagens sem laudo são explicitadas e nunca viram aprovações automáticas.
    mensagens = '\n'.join(textos)
    if re.search(r'\b(?:REPROVAD|APROVAD)', normalizar(mensagens)):
        avisos.append('Mensagens são mantidas para conferência. Apenas resultados confirmados nos PDFs entram nos indicadores. Exporte COM MÍDIA.')
    return list({r['id']: r for r in registros}.values()), arquivos, avisos, mensagens


def consolidar(registros):
    """Uma ocorrência por frota/dia de vistoria, mantendo cada placa e laudo."""
    grupos = defaultdict(list)
    for r in {r['id']: r for r in registros}.values():
        grupos[(r['frota'], r['vistoria'][:10])].append(r)
    linhas = []
    for (frota, dia), docs in grupos.items():
        reprovados = [r for r in docs if r['resultado'] == 'REPROVADO']
        if not reprovados:
            continue
        # Último resultado por placa/laudo: uma nova reprovação reabre a pendência.
        ultimos = {}
        for r in sorted(docs, key=lambda x: (x['impressao'], x['resultado'] == 'APROVADO')):
            ultimos[(r['placa'], r['numero'], r['vistoria'])] = r
        pendentes = sorted({r['placa'] for r in ultimos.values() if r['resultado'] == 'REPROVADO'})
        placas_r = {r['placa'] for r in reprovados}
        divergentes = sorted({r['placa'] for r in docs if r['resultado'] == 'APROVADO'} - placas_r)
        linhas.append({'Frota': frota, 'Data da vistoria': dia,
                       'Evento': ', '.join(sorted({r.get('evento', 'Não informado') for r in docs})),
                       'Situação': 'Pendente' if pendentes else 'Aprovada na reinspeção',
                       'Placas reprovadas': ', '.join(sorted(placas_r)),
                       'Placas pendentes': ', '.join(pendentes),
                       'Conferência': ('Aprovação em outra placa: ' + ', '.join(divergentes)) if divergentes else '',
                       'Primeira reprovação': min(r['impressao'] for r in reprovados),
                       'Último documento': max(r['impressao'] for r in docs),
                       'Laudos reprovados': len({(r['placa'], r['numero'], r['vistoria']) for r in reprovados}),
                       '_docs': docs})
    return sorted(linhas, key=lambda r: (r['Data da vistoria'], r['Frota']), reverse=True)


class Repositorio:
    def __init__(self, url, chave):
        import requests
        self.http = requests.Session()
        self.http.headers.update({'apikey': chave, 'Authorization': f'Bearer {chave}'})
        self.base = url.rstrip('/') + '/storage/v1'

    def ler(self, caminho):
        r = self.http.get(f'{self.base}/object/authenticated/{BUCKET}/{PREFIX}/{caminho}', timeout=45)
        r.raise_for_status()
        return r.content

    def gravar(self, caminho, dados, tipo):
        r = self.http.post(f'{self.base}/object/{BUCKET}/{PREFIX}/{caminho}', data=dados,
                           headers={'Content-Type': tipo, 'x-upsert': 'false'}, timeout=60)
        if r.ok:
            return
        # Conflito de objeto já existente é esperado nas reimportações.
        try:
            erro = r.json()
        except ValueError:
            erro = {}
        if str(erro.get('statusCode')) == '409' or erro.get('error') == 'Duplicate':
            return
        r.raise_for_status()

    def carregar(self):
        registros = {}; offset = 0
        while True:
            r = self.http.post(f'{self.base}/object/list/{BUCKET}',
                               json={'prefix': PREFIX + '/importacoes', 'limit': 100, 'offset': offset,
                                     'sortBy': {'column': 'name', 'order': 'asc'}}, timeout=45)
            r.raise_for_status(); objetos = r.json()
            for obj in objetos:
                if obj.get('name', '').endswith('.json'):
                    manifesto = json.loads(self.ler('importacoes/' + obj['name']))
                    if manifesto.get('versao') != 1:
                        raise ValueError('Versão de importação não reconhecida')
                    for registro in manifesto['registros']:
                        registros[registro['id']] = registro
            if len(objetos) < 100:
                break
            offset += 100
        return list(registros.values())

    def salvar(self, registros, arquivos, mensagens):
        for sha in {r['sha_pdf'] for r in registros}:
            self.gravar('pdfs/' + sha + '.pdf', arquivos[sha], 'application/pdf')
        manifesto = json.dumps({'versao': 1, 'registros': registros, 'mensagens': mensagens},
                               ensure_ascii=False, sort_keys=True).encode()
        # Só publica o manifesto depois de todos os PDFs estarem disponíveis.
        sha = hashlib.sha256(manifesto).hexdigest()
        self.gravar('importacoes/' + sha + '.json', manifesto, 'application/json')


def render_relatorio(url, chave, somente_leitura=False):
    import pandas as pd
    import streamlit as st
    st.caption('Importe diariamente a conversa exportada COM MÍDIA. O histórico é acumulado; reimportações não aumentam as contagens. Datas vêm dos PDFs, não do encaminhamento no WhatsApp.')
    if not url or not chave:
        st.info('Configure o acesso do monitor para consultar as reprovações.'); return
    repo = Repositorio(url, chave)

    @st.cache_data(ttl=60, show_spinner=False)
    def carregar(url_projeto, _chave):
        return Repositorio(url_projeto, _chave).carregar()

    try:
        historico = carregar(url, chave)
    except Exception:
        st.error('Não foi possível consultar o histórico de reprovações. Tente atualizar.'); return
    if st.button('Atualizar reprovações', key='reprov_atualizar'):
        carregar.clear(); st.rerun()
    if not somente_leitura:
        upload = st.file_uploader('Importar exportação do WhatsApp (.zip)', type=['zip'], key='reprov_zip')
        if upload:
            dados = upload.getvalue(); digest = hashlib.sha256(dados).hexdigest()
            if st.button('Analisar exportação', key='reprov_analisar'):
                try:
                    with st.spinner('Conferindo os PDFs da exportação…'):
                        regs, pdfs, avisos, mensagens = importar_zip(dados)
                    st.session_state['reprov_previa'] = (digest, regs, pdfs, avisos, mensagens)
                except Exception as exc:
                    st.error(f'Não foi possível analisar a exportação: {exc}')
            previa = st.session_state.get('reprov_previa')
            if previa and previa[0] == digest:
                _, regs, pdfs, avisos, mensagens = previa
                existentes = {r['id'] for r in historico}
                novos = [r for r in regs if r['id'] not in existentes]
                st.info(f'{len(regs)} resultados nos PDFs • {len(novos)} novos • {len(regs)-len(novos)} já importados')
                for aviso in avisos:
                    st.warning(aviso)
                if regs:
                    resumo_previa = consolidar(regs)
                    st.dataframe(pd.DataFrame([{k:v for k,v in r.items() if k != '_docs'} for r in resumo_previa]), hide_index=True, use_container_width=True)
                    tabela = pd.DataFrame([{k: r[k] for k in ['id','frota','placa','resultado','vistoria','impressao','evento']} for r in regs])
                    editada = st.data_editor(tabela, hide_index=True, use_container_width=True,
                                            disabled=['id','frota','placa','resultado','vistoria','impressao'],
                                            column_config={'id': None, 'evento': st.column_config.SelectboxColumn('Evento', options=['Não informado','ITR','REVISÃO','REVISÃO 60 DIAS','REVISÃO 90 DIAS','REVISÃO 120 DIAS'])},
                                            key='reprov_eventos_' + digest)
                    st.caption('Confira o evento antes de salvar. Frota, placa, resultado e datas são os informados no PDF.')
                    if st.button('Salvar novos registros', key='reprov_salvar', disabled=not novos):
                        eventos = dict(zip(editada['id'], editada['evento']))
                        novos = [dict(r, evento=eventos[r['id']]) for r in novos]
                        try:
                            with st.spinner('Salvando histórico e PDFs…'):
                                repo.salvar(novos, pdfs, mensagens)
                                verificados = repo.carregar()
                                if not {r['id'] for r in novos} <= {r['id'] for r in verificados}:
                                    raise RuntimeError('Gravação não confirmada')
                            carregar.clear()
                            st.success(f'{len(novos)} registros salvos e conferidos.')
                            historico = verificados
                        except Exception:
                            st.error('A gravação não foi confirmada. Você pode tentar novamente sem duplicar o histórico.')
                if mensagens:
                    with st.expander('Conferir mensagens originais'):
                        st.text(mensagens)
    linhas = consolidar(historico)
    if not linhas:
        st.info('Nenhuma reprovação importada.'); return
    tabela = pd.DataFrame([{k:v for k,v in r.items() if k != '_docs'} for r in linhas])
    c1,c2,c3 = st.columns(3)
    frota = c1.multiselect('Frota', sorted(tabela['Frota'].unique()), key='reprov_frota')
    situacao = c2.multiselect('Situação', ['Pendente','Aprovada na reinspeção'], key='reprov_situacao')
    datas = pd.to_datetime(tabela['Data da vistoria'])
    periodo = c3.date_input('Período da vistoria', (datas.min().date(), datas.max().date()), key='reprov_periodo')
    if frota: tabela = tabela[tabela['Frota'].isin(frota)]
    if situacao: tabela = tabela[tabela['Situação'].isin(situacao)]
    if len(periodo) == 2:
        tabela = tabela[(tabela['Data da vistoria'] >= periodo[0].isoformat()) & (tabela['Data da vistoria'] <= periodo[1].isoformat())]
    a,b,c = st.columns(3)
    a.metric('Ocorrências de reprovação', len(tabela))
    b.metric('Pendentes', int((tabela['Situação'] == 'Pendente').sum()))
    c.metric('Aprovadas na reinspeção', int((tabela['Situação'] == 'Aprovada na reinspeção').sum()))
    st.caption('Uma ocorrência por frota e dia de vistoria. Cada placa precisa de aprovação no mesmo laudo. A data de impressão da aprovação é documental e não representa, necessariamente, o horário da liberação.')
    st.dataframe(tabela, hide_index=True, use_container_width=True)
    st.download_button('Exportar relatório CSV', tabela.to_csv(index=False, sep=';').encode('utf-8-sig'),
                       'reprovacoes-mega.csv', 'text/csv', key='reprov_exportar')
    if tabela.empty: return
    ranking = tabela.groupby('Frota').size().rename('Reprovações').reset_index()
    st.bar_chart(ranking, x='Frota', y='Reprovações', color='#dc2626')
    opcoes = [(r['Frota'], r['Data da vistoria']) for _,r in tabela.iterrows()]
    selecionada = st.selectbox('Consultar documentos da ocorrência', opcoes,
                              format_func=lambda x:f'Frota {x[0]} • {x[1]}', key='reprov_detalhe')
    linha = next(r for r in linhas if (r['Frota'],r['Data da vistoria']) == selecionada)
    if linha['Conferência']: st.warning(linha['Conferência'])
    for doc in sorted(linha['_docs'], key=lambda r:(r['placa'],r['impressao'])):
        with st.expander(f"{doc['placa']} • {doc['resultado']} • {doc['impressao'].replace('T',' ')} • Laudo {doc['numero']}"):
            for obs in doc['observacoes']:
                st.write('• ' + obs)
            st.caption('Observações extraídas automaticamente. Confira a redação completa no PDF.')
            if st.button('Preparar PDF', key='reprov_pdf_' + doc['id']):
                try:
                    pdf = repo.ler('pdfs/' + doc['sha_pdf'] + '.pdf')
                    st.download_button('Abrir / baixar PDF original', pdf, doc['arquivo'], 'application/pdf', key='reprov_download_' + doc['id'])
                except Exception:
                    st.error('Não foi possível abrir este PDF. Tente novamente.')
