import os
import re
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from monitor_delta import MonitorDeltaCache

MOBILE_READ_ONLY = bool(globals().get("MOBILE_READ_ONLY", False)) or st.query_params.get("mobile", "0") == "1"
st.set_page_config(page_title="10 Sul • Consulta Mobile" if MOBILE_READ_ONLY else "Monitor Gerencial 10 Sul", page_icon="📊", layout="wide")

_registrar_baixa_whatsapp = components.declare_component(
    "registrar_baixa_whatsapp", path=str(Path(__file__).parent / "whatsapp_liberacao")
)

def _secret(nome):
    try:
        return str(st.secrets[nome]).strip()
    except Exception:
        return os.getenv(nome, "").strip()

SUPABASE_URL = _secret("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _secret("SUPABASE_KEY")

ESPECIAIS = {"13169","13241","11003","11001","11007","11009"}

st.markdown("""
<style>
.block-container{max-width:1600px;padding-top:1.2rem;padding-bottom:2rem}
#MainMenu,footer,header{visibility:hidden}
.mon-title{font-size:27px;font-weight:900;color:#10284a;margin-bottom:2px}
.mon-sub{font-size:12px;color:#667085;margin-bottom:14px}
.mon-section{background:#f4f9ff;border-left:5px solid #2583f7;border-radius:12px;padding:14px 18px;margin:16px 0 12px}
.mon-section-title{font-size:19px;font-weight:900;color:#10284a}
.mon-section-sub{font-size:12px;color:#667085;margin-top:4px}
.kpi{border:1px solid #dbe3ec;background:#f4f9ff;border-radius:11px;min-height:90px;padding:13px 8px;text-align:center}
.kpi-red{background:#fff2f4;border-color:#f7d8dd;color:#7f1d1d}
.kpi-orange{background:#fff8ef;border-color:#f3e4cf}
.kpi-n{font-size:24px;font-weight:900;line-height:1.05}
.kpi-l{font-size:12px;font-weight:800;margin-top:10px}
div[data-testid="stButton"] > button[kind="secondary"]{min-height:90px;border-radius:11px;font-weight:850;white-space:pre-line;font-size:14px}
.card{border:1px solid #dbe3ec;border-radius:12px;padding:14px;background:white}
.card-title{text-align:center;font-size:16px;font-weight:850;color:#10284a;margin-bottom:6px}
.card-center{text-align:center;font-size:13px}
.caption{font-size:12px;color:#667085;margin-top:5px}
.hunt-title{font-size:16px;font-weight:850;color:#10284a;margin-bottom:9px}
.hunt-kpi{font-size:30px;font-weight:900}
.hunt-compare{font-size:12px;color:#667085;margin-top:2px}
.up{color:#dc2626;font-weight:800}.down{color:#16a34a;font-weight:800}.flat{color:#667085;font-weight:800}
.top-card{border:1px solid #f0cfd4;border-radius:12px;padding:13px;background:#fff8f9;min-height:145px}
.top-title{font-size:13px;font-weight:850;color:#7f1d1d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top-row{display:flex;justify-content:space-between;border-top:1px solid #f1dfe2;padding:7px 2px;font-size:13px}
.reinc-head,.reinc-row{display:grid;grid-template-columns:1fr 90px 125px;gap:8px;padding:7px 8px}
.reinc-head{background:#eef1f5;font-size:12px;font-weight:700;color:#667085}
.reinc-row{border-bottom:1px solid #e8edf2;font-size:13px}

@media (max-width: 768px) {
  .block-container{padding-left:.65rem!important;padding-right:.65rem!important;padding-top:.65rem!important;max-width:100%!important}
  .mon-title{font-size:1.35rem!important}.mon-sub{font-size:.78rem!important}
  .mon-section{padding:12px!important;margin-top:12px!important}.mon-section-title{font-size:.95rem!important}
  div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
  div[data-testid="column"]{min-width:100%!important;width:100%!important;flex:1 1 100%!important}
  div[data-testid="stDataFrame"]{max-width:100%!important;overflow-x:auto!important}
  div[role="dialog"]{width:calc(100vw - 18px)!important;max-width:calc(100vw - 18px)!important;margin:9px!important}
}

/* Painel de desempenho do supervisor: compacto no topo */
div[data-testid="stVegaLiteChart"]{margin-top:-4px;margin-bottom:-8px}
@media (max-width: 768px) {
  div[data-testid="stVegaLiteChart"]{width:100%!important;max-width:100%!important}
}
</style>
""", unsafe_allow_html=True)

def api_get(table, params=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados nos Secrets.")
    url=f"{SUPABASE_URL}/rest/v1/{table}"
    headers={"apikey":SUPABASE_KEY, "Authorization":f"Bearer {SUPABASE_KEY}"}
    r=requests.get(url,headers=headers,params=params or {},timeout=45)
    if not r.ok:
        raise RuntimeError(f"Supabase HTTP {r.status_code}: {r.text[:800]}")
    return r.json()

def api_post(path, payload):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados nos Secrets.")
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                      headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                      json=payload, timeout=45)
    if not r.ok:
        raise RuntimeError(f"Supabase HTTP {r.status_code}: {r.text[:800]}")
    return r.json()


@st.cache_resource
def _cache_incremental_monitor():
    return MonitorDeltaCache()


def _ler_atendimentos(table, filtros=None):
    """Carrega somente paradas desde 01/01/2026, filtradas no servidor."""
    todos = []
    offset = 0
    while True:
        lote = api_get(table, {"select": "*", "order": "os_id.asc,frota.asc",
                              "limit": 1000, "offset": offset, "unidade": "eq.ARA",
                              "or": "(parada.gte.2026-01-01,and(parada.is.null,inicio.gte.2026-01-01))",
                              **(filtros or {})})
        todos.extend(lote)
        if len(lote) < 1000:
            break
        offset += 1000
    return pd.DataFrame(todos)


def _hora_brasilia(valor):
    """Preserva horários locais sem fuso e converte valores com fuso para Brasília."""
    try:
        ts = pd.Timestamp(valor)
        if pd.isna(ts):
            return pd.NaT
        return ts.tz_convert("America/Sao_Paulo").tz_localize(None) if ts.tzinfo else ts
    except (ValueError, TypeError):
        return pd.NaT


def _evento_resumido_whatsapp(evento):
    import unicodedata
    texto = str(evento or "").strip()
    normalizado = unicodedata.normalize("NFKD", texto.upper()).encode("ascii", "ignore").decode()
    if re.search(r"\bCNP\b", normalizado) or ("CORRETIV" in normalizado and re.search(r"\b(?:N|NAO)\s+PROG", normalizado)):
        return "CNP"
    if re.search(r"\bREV(?:ISAO|ISOES)?\b", normalizado):
        return "REV"
    if re.search(r"\bITR\b", normalizado):
        return "ITR"
    return texto


def _mensagem_liberacao(frota, evento, quando):
    hora = _hora_brasilia(quando)
    return (
        f"Frota: {norm_frota(frota)}\nEvento: {_evento_resumido_whatsapp(evento)}\n"
        f"Data/hora baixa: {hora.strftime('%d/%m/%Y %H:%M')}\n"
        "Status: Liberado pela 10 Sul\n"
        "Aguardando baixa do cliente."
    )


def _nome_coluna_fim_10sul(colunas):
    """Reconhece a coluna existente sem confundir fim ASN ou fim do laudo."""
    import unicodedata
    def normalizar(nome):
        texto = unicodedata.normalize("NFKD", str(nome).lower())
        return re.sub(r"[^a-z0-9]", "", texto)
    normalizados = {normalizar(c): c for c in colunas}
    for nome in ["liberacao_10sul", "liberacao_10_sul", "fim_10sul", "fim_10_sul", "fim_liberacao_10sul"]:
        encontrado = normalizados.get(normalizar(nome))
        if encontrado:
            return encontrado
    return None


@st.cache_data(ttl=60, show_spinner=False)
def _coluna_fim_10sul_banco():
    registros = api_get("monitor_atendimentos", {"select": "*", "limit": 1})
    coluna = _nome_coluna_fim_10sul(registros[0].keys()) if registros else None
    if coluna is None:
        raise RuntimeError(
            "Não localizei a coluna Fim 10 Sul em monitor_atendimentos. "
            "Precisamos confirmar o nome técnico e a tabela da coluna já usada pelo sistema. "
            "Nenhuma nova coluna foi criada."
        )
    return coluna


def _erro_gravacao_liberacao(resposta):
    """Diagnóstico do banco sem exibir credenciais nem dados da requisição."""
    try:
        erro = resposta.json()
        codigo = str(erro.get("code") or "") if isinstance(erro, dict) else ""
        mensagem = str(erro.get("message") or "") if isinstance(erro, dict) else ""
    except (ValueError, TypeError):
        codigo, mensagem = "", ""
    codigo = re.sub(r"[^A-Za-z0-9_]", "", codigo)[:30]
    detalhe = f"HTTP {resposta.status_code}" + (f" · {codigo}" if codigo else "")
    if codigo in {"PGRST204", "42703"}:
        _coluna_fim_10sul_banco.clear()
        return (
            "O banco não reconheceu a coluna de liberação selecionada. "
            "Atualize o monitor para conferir novamente o nome da coluna Fim 10 Sul existente. "
            f"Nenhuma nova coluna foi criada. ({detalhe})"
        )
    if resposta.status_code in {401, 403} or codigo == "42501":
        return (
            "O banco recusou a permissão de gravação. A chave de leitura não permite "
            "registrar esta informação. Confira as permissões da conta usada pelo monitor "
            "ou configure SUPABASE_WRITE_KEY nos Secrets com uma chave autorizada de servidor. "
            f"Não cole a chave no chat. ({detalhe})"
        )
    return f"O banco recusou a liberação 10 Sul. Código de diagnóstico: {detalhe}."


def _salvar_liberacao_10sul(registro, quando):
    """Grava somente o fim da 10 Sul; não altera status nem baixa ASN."""
    quando = _hora_brasilia(quando)
    agora_local = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)
    inicio = _hora_brasilia(registro.get("inicio_mon", registro.get("inicio")))
    if pd.isna(quando) or quando > agora_local:
        raise ValueError("Informe uma data/hora válida, até o horário atual.")
    if pd.notna(inicio) and quando < inicio:
        raise ValueError("A liberação não pode ser anterior ao início do atendimento.")
    os_id, frota = str(registro["os_id"]), norm_frota(registro["frota"])
    filtros = {"os_id": f"eq.{os_id}", "frota": f"eq.{frota}"}
    origem = api_get("monitor_asn", {**filtros, "select": "os_id,frota,status,fim,excluida_asn_em"})
    if len(origem) != 1:
        raise RuntimeError("Não foi possível identificar uma única OS na ASN. Atualize o monitor.")
    if origem[0].get("excluida_asn_em"):
        raise ValueError("Esta OS foi excluída na Lista ASN. Apenas consulta ao histórico disponível.")
    if pd.notna(_hora_brasilia(origem[0].get("fim"))) or "MANUT" not in str(origem[0].get("status", "")).upper():
        raise ValueError("A cliente já deu baixa ou alterou esta OS. Atualize o monitor.")
    valor = quando.tz_localize("America/Sao_Paulo").isoformat()
    chave_gravacao = _secret("SUPABASE_WRITE_KEY") or SUPABASE_KEY
    headers = {"apikey": chave_gravacao, "Prefer": "return=representation"}
    # As novas chaves sb_secret_* usam somente apikey; JWT legado usa Bearer.
    if not str(chave_gravacao).startswith(("sb_secret_", "sb_publishable_")):
        headers["Authorization"] = f"Bearer {chave_gravacao}"
    url = f"{SUPABASE_URL}/rest/v1/monitor_atendimentos"
    coluna_fim = _coluna_fim_10sul_banco()
    payload = {coluna_fim: valor}
    resposta = requests.patch(url, headers=headers, params=filtros, json=payload, timeout=45)
    if not resposta.ok:
        raise RuntimeError(_erro_gravacao_liberacao(resposta))
    salvos = resposta.json()
    if not salvos:
        # A ASN pode conter uma OS nova ainda não importada para o histórico.
        campos = ["os_id", "frota", "evento", "status", "descricao", "modal", "unidade"]
        novo = {c: str(registro.get(c) or "") for c in campos}
        for c in ["parada", "inicio"]:
            hora = _hora_brasilia(registro.get(c))
            novo[c] = hora.tz_localize("America/Sao_Paulo").isoformat() if pd.notna(hora) else None
        novo.update(payload)
        resposta = requests.post(url, headers=headers, json=novo, timeout=45)
        if resposta.status_code == 409:
            resposta = requests.patch(url, headers=headers, params=filtros, json=payload, timeout=45)
        if not resposta.ok:
            raise RuntimeError(_erro_gravacao_liberacao(resposta))
        salvos = resposta.json()
    if len(salvos) != 1:
        raise RuntimeError("A gravação não confirmou uma única OS. Atualize o monitor antes de tentar novamente.")
    confirmado = _hora_brasilia(salvos[0].get(coluna_fim))
    if pd.isna(confirmado) or confirmado != quando:
        raise RuntimeError("A data/hora gravada não foi confirmada. Atualize o monitor.")
    carregar.clear()
    return _mensagem_liberacao(frota, registro["evento"], confirmado)


def _desfazer_liberacao_10sul(registro):
    """Retira somente a liberação manual da OS selecionada, mantendo a ASN intacta."""
    os_id, frota = str(registro["os_id"]), norm_frota(registro["frota"])
    filtros = {"os_id": f"eq.{os_id}", "frota": f"eq.{frota}"}
    origem = api_get("monitor_asn", {**filtros, "select": "os_id,frota,status,fim,excluida_asn_em"})
    if len(origem) != 1:
        raise RuntimeError("Não foi possível identificar uma única OS na ASN. Atualize o monitor.")
    if origem[0].get("excluida_asn_em"):
        raise ValueError("Esta OS foi excluída na Lista ASN. Apenas consulta ao histórico disponível.")
    if pd.notna(_hora_brasilia(origem[0].get("fim"))) or "MANUT" not in str(origem[0].get("status", "")).upper():
        raise ValueError("O cliente já deu baixa ou alterou esta OS. A baixa ASN não pode ser desfeita aqui.")
    coluna_fim = _coluna_fim_10sul_banco()
    atuais = api_get("monitor_atendimentos", {**filtros, "select": "*"})
    if len(atuais) != 1:
        raise RuntimeError("Não foi possível identificar uma única liberação 10 Sul. Atualize o monitor.")
    valor_atual = atuais[0].get(coluna_fim)
    hora_atual = _hora_brasilia(valor_atual)
    if pd.isna(hora_atual):
        raise ValueError("Esta OS já está sem liberação 10 Sul. Atualize o monitor.")
    exibida = _hora_brasilia(registro.get("fim_liberacao_10sul"))
    if pd.isna(exibida) or exibida != hora_atual:
        raise ValueError("A liberação mudou desde que a janela foi aberta. Atualize antes de desfazer.")
    chave_gravacao = _secret("SUPABASE_WRITE_KEY") or SUPABASE_KEY
    headers = {"apikey": chave_gravacao, "Prefer": "return=representation"}
    if not str(chave_gravacao).startswith(("sb_secret_", "sb_publishable_")):
        headers["Authorization"] = f"Bearer {chave_gravacao}"
    # Só altera a versão da baixa que foi conferida; não desfaz uma atualização concorrente.
    filtros[coluna_fim] = f"eq.{valor_atual}"
    resposta = requests.patch(
        f"{SUPABASE_URL}/rest/v1/monitor_atendimentos",
        headers=headers, params=filtros, json={coluna_fim: None}, timeout=45,
    )
    if not resposta.ok:
        raise RuntimeError(_erro_gravacao_liberacao(resposta))
    salvos = resposta.json()
    if len(salvos) != 1 or salvos[0].get(coluna_fim) is not None:
        raise RuntimeError("Não foi possível confirmar o desfazimento. Atualize o monitor.")
    carregar.clear()
    return frota


def _mensagem_previsao(frota, evento, quando):
    return (
        "FROTA | EVENTO | PREVISÃO\n"
        f"{frota} | {_evento_resumido_whatsapp(evento)} | {pd.Timestamp(quando).strftime('%d/%m %H:%M')}"
    )


def _erro_gravacao_previsao(resposta):
    try:
        erro = resposta.json()
        codigo = erro.get("code") if isinstance(erro, dict) else None
    except (ValueError, TypeError):
        codigo = None
    if codigo in {"PGRST204", "42703"}:
        return (
             "Falta disponibilizar os campos de previsão e observação no banco da nuvem. "
            "A previsão não foi salva nem encaminhada ao WhatsApp."
        )
    return _erro_gravacao_liberacao(resposta)


def _salvar_previsao_10sul(registro, quando, observacao=""):
    """Grava somente a previsão; não altera fim, status nem cálculo de tempo."""
    sem_previsao = quando is None
    quando = _hora_brasilia(quando)
    observacao = " ".join(str(observacao or "").split())
    if len(observacao) > 300:
        raise ValueError("Use até 300 caracteres na observação.")
    if not sem_previsao:
        observacao = ""
    agora_local = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)
    inicio = _hora_brasilia(registro.get("inicio_mon", registro.get("inicio")))
    if not sem_previsao and (pd.isna(quando) or quando < agora_local.floor("min")):
        raise ValueError("Informe uma previsão válida, a partir do horário atual.")
    if not sem_previsao and pd.notna(inicio) and quando < inicio:
        raise ValueError("A previsão não pode ser anterior ao início do atendimento.")
    os_id, frota = str(registro["os_id"]), norm_frota(registro["frota"])
    filtros = {"os_id": f"eq.{os_id}", "frota": f"eq.{frota}"}
    origem = api_get("monitor_asn", {**filtros, "select": "os_id,frota,status,fim,excluida_asn_em"})
    if len(origem) != 1:
        raise RuntimeError("Não foi possível identificar uma única OS na ASN. Atualize o monitor.")
    if origem[0].get("excluida_asn_em"):
        raise ValueError("Esta OS foi excluída na Lista ASN. Apenas consulta ao histórico disponível.")
    if pd.notna(_hora_brasilia(origem[0].get("fim"))) or "MANUT" not in str(origem[0].get("status", "")).upper():
        raise ValueError("A cliente já deu baixa ou alterou esta OS. Atualize o monitor.")
    atuais = api_get("monitor_atendimentos", {**filtros, "select": "*"})
    for atual in atuais:
        coluna_baixa = _nome_coluna_fim_10sul(atual.keys())
        if coluna_baixa and pd.notna(_hora_brasilia(atual.get(coluna_baixa))):
            raise ValueError("Esta frota já foi liberada pela 10 Sul. Atualize o monitor.")
    valor = None if sem_previsao else quando.tz_localize("America/Sao_Paulo").isoformat()
    chave_gravacao = _secret("SUPABASE_WRITE_KEY") or SUPABASE_KEY
    headers = {"apikey": chave_gravacao, "Prefer": "return=representation"}
    # As novas chaves sb_secret_* usam somente apikey; JWT legado usa Bearer.
    if not str(chave_gravacao).startswith(("sb_secret_", "sb_publishable_")):
        headers["Authorization"] = f"Bearer {chave_gravacao}"
    url = f"{SUPABASE_URL}/rest/v1/monitor_atendimentos"
    coluna_fim = "previsao_liberacao_10sul"
    payload = {coluna_fim: valor, "observacao_previsao_10sul": observacao}
    resposta = requests.patch(url, headers=headers, params=filtros, json=payload, timeout=45)
    if not resposta.ok:
        raise RuntimeError(_erro_gravacao_previsao(resposta))
    salvos = resposta.json()
    if not salvos:
        # A ASN pode conter uma OS nova ainda não importada para o histórico.
        campos = ["os_id", "frota", "evento", "status", "descricao", "modal", "unidade"]
        novo = {c: str(registro.get(c) or "") for c in campos}
        for c in ["parada", "inicio"]:
            hora = _hora_brasilia(registro.get(c))
            novo[c] = hora.tz_localize("America/Sao_Paulo").isoformat() if pd.notna(hora) else None
        novo.update(payload)
        resposta = requests.post(url, headers=headers, json=novo, timeout=45)
        if resposta.status_code == 409:
            resposta = requests.patch(url, headers=headers, params=filtros, json=payload, timeout=45)
        if not resposta.ok:
            raise RuntimeError(_erro_gravacao_previsao(resposta))
        salvos = resposta.json()
    if len(salvos) != 1:
        raise RuntimeError("A gravação não confirmou uma única OS. Atualize o monitor antes de tentar novamente.")
    confirmado = _hora_brasilia(salvos[0].get(coluna_fim))
    if (sem_previsao and pd.notna(confirmado)) or (not sem_previsao and (pd.isna(confirmado) or confirmado != quando)):
        raise RuntimeError("A data/hora gravada não foi confirmada. Atualize o monitor.")
    nota_confirmada = str(salvos[0].get("observacao_previsao_10sul") or "")
    if nota_confirmada != observacao:
        raise RuntimeError("A observação gravada não foi confirmada. Atualize o monitor.")
    carregar.clear()
    return _mensagem_previsoes_card(pd.DataFrame([{
        "frota": frota, "evento": registro["evento"], "previsao": confirmado, "observacao": nota_confirmada,
    }]))

def _previsoes_do_card(dados, base):
    """Inclui todas as OS exibidas no card, sem descartar linhas sem previsão."""
    atuais = {
        (str(row["os_id"]), norm_frota(row["frota"])): row
        for _, row in base.iterrows()
    }
    linhas = []
    for _, exibida in dados.drop_duplicates(["os_id", "frota"]).iterrows():
        chave = (str(exibida["os_id"]), norm_frota(exibida["frota"]))
        row = atuais.get(chave)
        if row is None:
            raise ValueError("Não foi possível consultar todas as frotas do card. Atualize o monitor antes de enviar.")
        linhas.append({
            "os_id": chave[0], "frota": chave[1], "evento": str(exibida.get("evento", "")),
            "previsao": _hora_brasilia(row.get("previsao_liberacao_10sul")),
            "observacao": "" if pd.isna(row.get("observacao_previsao_10sul")) else " ".join(str(row.get("observacao_previsao_10sul")).split()),
        })
    return pd.DataFrame(linhas, columns=["os_id", "frota", "evento", "previsao", "observacao"])


def _mensagem_previsoes_card(previsoes):
    if previsoes.empty:
        raise ValueError("Não há frotas em atendimento neste card.")
    linhas = ["FROTA | EVENTO | PREVISÃO"]
    for _, row in previsoes.sort_values(["frota", "evento"]).iterrows():
        if pd.notna(row["previsao"]):
            texto_previsao = pd.Timestamp(row["previsao"]).strftime("%d/%m %H:%M")
        else:
            observacao = row.get("observacao")
            texto_previsao = " ".join(str(observacao).split()) if pd.notna(observacao) and str(observacao).strip() else "—"
        evento = _evento_resumido_whatsapp(row["evento"])
        linhas.append(f"{row['frota']} | {evento} | {texto_previsao}")
    return "\n".join(linhas)


def _combinar_base_asn(historico, asn):
    """ASN prevalece nos dados da cliente; início salvo continua preservado."""
    def preparar(d):
        d = d.copy()
        for c in ["os_id", "frota"]:
            d[c] = d[c].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        return d.drop_duplicates(["os_id", "frota"], keep="last").set_index(["os_id", "frota"])
    if asn.empty:
        raise RuntimeError("monitor_asn não retornou registros. Confira a permissão de leitura dessa tabela.")
    a = preparar(asn)
    if "local_manutencao" not in a.columns:
        a["local_manutencao"] = None
    if "excluida_asn_em" not in a.columns:
        a["excluida_asn_em"] = None
    if "ausente_abertas_asn_em" not in a.columns:
        a["ausente_abertas_asn_em"] = None
    a["inicio_asn"] = a["inicio"]
    a["inicio_suzano"] = a["parada"]
    a["fim_asn"] = a["fim"]
    a["fim"] = pd.to_datetime(a["fim_asn"], errors="coerce")
    if historico.empty:
        return a.reset_index()
    h = preparar(historico)
    coluna_fim_existente = _nome_coluna_fim_10sul(h.columns)
    if coluna_fim_existente and coluna_fim_existente != "fim_liberacao_10sul":
        # Nome interno padronizado; gravação na coluna original do banco.
        h["fim_liberacao_10sul"] = h[coluna_fim_existente]
    # Fim histórico combinado não comprova a origem ASN ou liberação manual.
    for c in ["fim_asn", "fim_liberacao_10sul"]:
        if c not in h.columns:
            h[c] = pd.NaT
    h["fim"] = pd.to_datetime(h["fim_asn"], errors="coerce").fillna(pd.to_datetime(h["fim_liberacao_10sul"].map(_hora_brasilia), errors="coerce"))
    resultado = h.reindex(h.index.union(a.index)).copy()
    # Os valores nulos da ASN também prevalecem: uma OS reaberta perde o fim.
    for c in ["evento", "status", "parada", "fim", "descricao", "modal", "unidade", "inicio_suzano", "inicio_asn", "fim_asn", "sincronizado_em", "excluida_asn_em", "local_manutencao", "ausente_abertas_asn_em"]:
        if c not in resultado.columns:
            resultado[c] = None
        resultado.loc[a.index, c] = a[c]
    # Não substitui possíveis ajustes de início já gravados pelo sistema principal.
    salvo = pd.to_datetime(resultado["inicio"], errors="coerce")
    novos = a.index[~a.index.isin(h.index)]
    resultado.loc[novos, "inicio"] = a.loc[novos, "inicio"]
    sem_inicio = a.index[salvo.reindex(a.index).isna()]
    resultado.loc[sem_inicio, "inicio"] = a.loc[sem_inicio, "inicio"]
    resultado["fim"] = pd.to_datetime(resultado["fim_asn"], errors="coerce").fillna(pd.to_datetime(resultado["fim_liberacao_10sul"].map(_hora_brasilia), errors="coerce"))
    return resultado.reset_index()


def _inconsistencias_asn(base):
    """Sinais de conferência na origem; não conclui atendimento nem altera OS."""
    colunas = ["FROTA","OS/ID","EVENTO","PARADA ASN","FIM ASN","STATUS ASN","OS RELACIONADA","EVENTO RELACIONADO","PARADA RELACIONADA","FIM RELACIONADO","SITUAÇÃO"]
    if base.empty:
        return pd.DataFrame(columns=colunas)
    b = base.copy()
    # Histórico sem registro na cópia ASN não confirma a situação da origem.
    b = b.loc[b.get("sincronizado_em", pd.Series(None, index=b.index, dtype=object)).notna()]
    b = b.loc[b.get("excluida_asn_em", pd.Series(None, index=b.index, dtype=object)).isna()]
    if b.empty:
        return pd.DataFrame(columns=colunas)
    b = b.drop_duplicates(["os_id","frota"], keep="last")
    b["_parada"] = b["parada"].map(_hora_brasilia)
    b["_fim"] = b["fim_asn"].map(_hora_brasilia)
    registros = []
    def incluir(r, situacao, outro=None):
        registros.append({"FROTA":str(r["frota"]), "OS/ID":str(r["os_id"]), "EVENTO":r["evento"],
            "PARADA ASN":r["_parada"], "FIM ASN":r["_fim"], "STATUS ASN":r["status"],
            "OS RELACIONADA":str(outro["os_id"]) if outro is not None else "",
            "EVENTO RELACIONADO":outro["evento"] if outro is not None else "",
            "PARADA RELACIONADA":outro["_parada"] if outro is not None else pd.NaT,
            "FIM RELACIONADO":outro["_fim"] if outro is not None else pd.NaT, "SITUAÇÃO":situacao})
    for _, r in b.iterrows():
        if pd.notna(r["_parada"]) and pd.notna(r["_fim"]) and r["_fim"] < r["_parada"]:
            incluir(r, "Fim ASN anterior à parada — conferir horário na origem")
        elif "MANUT" in str(r["status"]).upper() and pd.notna(r["_fim"]):
            incluir(r, "Status em manutenção com fim preenchido — conferir na origem")
        elif "LIBER" in str(r["status"]).upper() and pd.isna(r["_fim"]):
            incluir(r, "Status liberado sem data de fim — conferir na origem")
    for _, grupo in b.loc[b["_parada"].notna()].groupby("frota", sort=False):
        linhas = [r for _, r in grupo.sort_values(["_parada","os_id"]).iterrows()]
        for anterior, posterior in zip(linhas, linhas[1:]):
            fim = anterior["_fim"]
            aberto = "MANUT" in str(anterior["status"]).upper() and pd.isna(fim)
            if aberto:
                incluir(anterior, "OS sem baixa com outro atendimento da mesma frota — conferir pendência na ASN", posterior)
            elif pd.notna(fim) and fim >= anterior["_parada"] and fim > posterior["_parada"]:
                incluir(anterior, "Períodos de OS sobrepostos na ASN — conferir horários", posterior)
    return pd.DataFrame(registros, columns=colunas)


def _inicio_tres_meses(agora=None):
    """Mês atual e dois anteriores, respeitando o início do histórico em 2026."""
    hoje = pd.Timestamp(agora) if agora is not None else pd.Timestamp.now(tz="America/Sao_Paulo")
    inicio = hoje.replace(day=1) - pd.DateOffset(months=2)
    return max("2026-01-01", inicio.date().isoformat())


@st.cache_data(show_spinner=False, max_entries=6)
def _historico_fixo(table, inicio_recentes):
    """Dados anteriores à janela: uma carga por tabela e janela mensal."""
    return _ler_atendimentos(table, {
        "and": f"(or(parada.lt.{inicio_recentes},and(parada.is.null,inicio.lt.{inicio_recentes})))"
    })


def _filtro_recentes(inicio, arquivo):
    partes = [f"parada.gte.{inicio}", f"and(parada.is.null,inicio.gte.{inicio})",
              "status.ilike.*MANUT*"]
    # Keep querying old open OS from the snapshot even after they close.
    # This prevents the cached open status from reappearing on the next refresh.
    if not arquivo.empty and "status" in arquivo.columns:
        abertas = arquivo.loc[arquivo["status"].fillna("").astype(str).str.contains("MANUT", case=False), "os_id"]
        ids = sorted(set(str(x).strip() for x in abertas if pd.notna(x)))
        if ids:
            citados = ",".join('"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"' for x in ids)
            partes.append(f"os_id.in.({citados})")
    return {"and": "(or(" + ",".join(partes) + "))"}


def _atendimentos_com_historico(table, inicio_recentes):
    arquivo = _historico_fixo(table, inicio_recentes)
    abertas = []
    if not arquivo.empty and "status" in arquivo.columns:
        abertas = sorted(set(arquivo.loc[arquivo["status"].fillna("").astype(str).str.contains("MANUT", case=False), "os_id"].dropna().astype(str)))
    recentes = _cache_incremental_monitor().read(api_post, table, inicio_recentes, abertas)
    if arquivo.empty:
        return recentes
    # Old open rows belong to the live feed, including closures and removals.
    arquivo = arquivo.loc[~arquivo["status"].fillna("").astype(str).str.contains("MANUT", case=False)]
    resultado = pd.concat([arquivo, recentes], ignore_index=True).drop_duplicates(
        ["os_id", "frota"], keep="last").reset_index(drop=True)
    resultado.attrs["sincronizado_em"] = recentes.attrs.get("sincronizado_em")
    return resultado


@st.cache_data(ttl=60, show_spinner=False)
def carregar():
    """Base ASN v5: histórico fixo e transferência somente de alterações recentes."""
    inicio = _inicio_tres_meses()
    historico = _atendimentos_com_historico("monitor_atendimentos", inicio)
    asn = _atendimentos_com_historico("monitor_asn", inicio)
    base = _combinar_base_asn(historico, asn)
    base.attrs["sincronizado_em"] = asn.attrs.get("sincronizado_em")
    unidade = base["unidade"].fillna("").astype(str).str.strip().str.upper()
    return base.loc[unidade.eq("ARA")].copy().reset_index(drop=True)

def norm_frota(v):
    s=str(v or "").strip()
    return re.sub(r"\.0$","",s)

def hhmm(h):
    if h is None or pd.isna(h): return "--:--"
    m=max(0,int(round(float(h)*60)))
    return f"{m//60:02d}:{m%60:02d}"


@st.cache_data(ttl=60, show_spinner=False)
def carregar_laudos_manuais_web():
    """Lê os laudos conferidos diretamente da tabela public.laudos_monitor."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return pd.DataFrame()
    try:
        url=f"{SUPABASE_URL}/rest/v1/laudos_monitor"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
        todos=[]; inicio=0; pagina=1000
        while True:
            hh=dict(h); hh["Range"]=f"{inicio}-{inicio+pagina-1}"; hh["Prefer"]="count=none"
            r=requests.get(url,headers=hh,params={"select":"*","order":"id.asc"},timeout=45)
            if not r.ok:
                st.session_state["_erro_laudos_web"] = f"HTTP {r.status_code}: {r.text[:500]}"
                return pd.DataFrame()
            lote=r.json()
            if not lote: break
            todos.extend(lote)
            if len(lote)<pagina: break
            inicio += pagina
        if not todos:
            st.session_state.pop("_erro_laudos_web",None)
            return pd.DataFrame()
        d=pd.DataFrame(todos)
        # Mantém o restante do Monitor compatível com os nomes históricos.
        ren={
            "registro":"REGISTRO","os_id":"OS_ID","frota":"FROTA","compartimento":"COMPARTIMENTO",
            "status":"STATUS","inicio_manutencao":"INICIO_MANUTENCAO","fim_manutencao":"FIM_MANUTENCAO",
            "atividade_id":"ATIVIDADE_ID","atividade":"ATIVIDADE","executante":"EXECUTANTE",
            "classificacao":"CLASSIFICACAO","inicio_atividade":"INICIO_ATIVIDADE","fim_atividade":"FIM_ATIVIDADE",
            "horas":"HORAS","evidencias":"EVIDENCIAS"
        }
        d=d.rename(columns={k:v for k,v in ren.items() if k in d.columns})
        # FIM_MANUTENCAO preserva a liberação informada no laudo (10 Sul).
        # A liberação da cliente vem da base sincronizada e não sobrescreve o laudo.
        d["FIM_CLIENTE"]=""
        try:
            atend=carregar()
            if not atend.empty and all(c in atend.columns for c in ["os_id","frota","fim_asn"]):
                def chave_os(v):
                    return re.sub(r"\\.0$","",str(v).strip())
                atend=atend.copy()
                chaves_ara = set(zip(atend["os_id"].apply(chave_os), atend["frota"].apply(norm_frota)))
                d = d.loc[[(chave_os(o), norm_frota(f)) in chaves_ara for o, f in zip(d["OS_ID"], d["FROTA"])]].copy()
                atend["_OS"]=atend["os_id"].apply(chave_os)
                atend["_FROTA"]=atend["frota"].apply(norm_frota)
                atend["_FIM"]=pd.to_datetime(atend["fim_asn"],errors="coerce")
                finais=atend.groupby(["_OS","_FROTA"])["_FIM"].max()
                d["FIM_CLIENTE"]=[
                    finais.get((chave_os(osid),norm_frota(fr)),pd.NaT)
                    for osid,fr in zip(d["OS_ID"],d["FROTA"])
                ]
        except Exception as e:
            st.session_state["_erro_fim_cliente"]=str(e)
        st.session_state.pop("_erro_laudos_web",None)
        return d
    except Exception as e:
        st.session_state["_erro_laudos_web"] = str(e)
        return pd.DataFrame()

def baixar_evidencia_laudo_web(path):
    try:
        url=f"{SUPABASE_URL}/storage/v1/object/authenticated/evidencias-desvios/{path}"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
        r=requests.get(url,headers=h,timeout=45)
        return (r.content,r.headers.get("content-type","")) if r.ok else (None,"")
    except Exception:return None,""

def atualizar_atividade_laudo_web(atividade_id, dados):
    """Atualiza uma atividade já conferida na tabela public.laudos_monitor."""
    if MOBILE_READ_ONLY:
        return False, "Esta versão permite somente consulta."
    chave_escrita=_secret("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not chave_escrita:
        return False,"O Monitor está somente para leitura. Configure a credencial de escrita nos Secrets do servidor."
    aid=str(atividade_id or "").strip()
    if not aid:
        return False,"Atividade sem identificador; não é seguro editar."
    try:
        url=f"{SUPABASE_URL}/rest/v1/laudos_monitor"
        h={"apikey":chave_escrita,"Authorization":f"Bearer {chave_escrita}","Content-Type":"application/json","Prefer":"return=representation"}
        r=requests.patch(url,headers=h,params={"atividade_id":f"eq.{aid}","select":"atividade_id"},json=dados,timeout=45)
        if not r.ok:return False,f"Supabase HTTP {r.status_code}: {r.text[:500]}"
        if not r.json() or any(str(x.get("atividade_id"))!=aid for x in r.json()):
            return False,"A atividade não foi gravada. Recarregue e confira as permissões de escrita."
        carregar_laudos_manuais_web.clear()
        return True,"Alteração salva."
    except Exception as e:return False,str(e)

def atualizar_datas_laudo_web(ids, inicio, fim):
    """Atualiza somente o período 10 Sul das linhas do laudo selecionado."""
    if MOBILE_READ_ONLY:
        return False, "Esta versão permite somente consulta."
    chave_escrita=_secret("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not chave_escrita:
        return False, "O Monitor está configurado somente para leitura. Configure SUPABASE_SERVICE_KEY nos Secrets do servidor para salvar datas."
    try:
        ids=sorted({int(i) for i in ids})
        ini=pd.Timestamp(inicio); final=pd.Timestamp(fim)
        if not ids or pd.isna(ini) or pd.isna(final) or final<ini:
            return False, "Informe início e fim válidos; o fim não pode ser anterior ao início."
        h={"apikey":chave_escrita,"Authorization":f"Bearer {chave_escrita}","Content-Type":"application/json","Prefer":"return=representation"}
        r=requests.patch(f"{SUPABASE_URL}/rest/v1/laudos_monitor",headers=h,
            params={"id":"in.("+",".join(map(str,ids))+")","select":"id"},
            json={"inicio_manutencao":ini.strftime("%Y-%m-%dT%H:%M:%S"),"fim_manutencao":final.strftime("%Y-%m-%dT%H:%M:%S")},timeout=45)
        if not r.ok: return False,f"Supabase HTTP {r.status_code}: {r.text[:500]}"
        if {int(x["id"]) for x in r.json()}!=set(ids):
            carregar_laudos_manuais_web.clear()
            return False, "Nem todas as linhas foram atualizadas. Recarregue e confira o laudo."
        carregar_laudos_manuais_web.clear()
        return True, "Datas do laudo salvas."
    except Exception as e:
        return False,str(e)

@st.cache_data(ttl=60,show_spinner=False)
def carregar_importacoes_evidencias_pendentes():
    import json
    import urllib.parse
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"registros":[],"erro":"Acesso às evidências não configurado."}
    headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
    storage=f"{SUPABASE_URL}/storage/v1"
    registros=[]; offset=0
    try:
        while True:
            response=requests.post(f"{storage}/object/list/evidencias-desvios",headers=headers,
                json={"prefix":"avarias-itr/importacoes","limit":100,"offset":offset,
                      "sortBy":{"column":"updated_at","order":"desc"}},timeout=30)
            response.raise_for_status(); page=response.json()
            for obj in page:
                name=obj.get("name","")
                if not name.endswith(".json"): continue
                path=urllib.parse.quote("avarias-itr/importacoes/"+name,safe="/")
                data=requests.get(f"{storage}/object/authenticated/evidencias-desvios/{path}",headers=headers,timeout=30)
                data.raise_for_status(); registros.extend(data.json().get("evidencias",[]))
            if len(page)<100: break
            offset+=len(page)
        return {"registros":registros,"erro":""}
    except Exception as exc:
        return {"registros":[],"erro":str(exc)}


def contar_evidencias_pendentes(registros, laudos):
    """Só conta arquivos armazenados ainda sem vínculo; não mistura ausência de foto com pendência."""
    import json
    vinculadas=set()
    for value in laudos.get("EVIDENCIAS",pd.Series(dtype=str)):
        try:
            paths=value if isinstance(value,list) else json.loads(value or "[]")
            if isinstance(paths,list): vinculadas.update(p for p in paths if isinstance(p,str))
        except (TypeError,ValueError): pass
    contagem={}; vistos=set(); sem_frota=0
    for item in registros:
        path=item.get("path",""); identity=item.get("sha256") or path
        if not identity or identity in vistos: continue
        vistos.add(identity)
        if not item.get("armazenado") or path in vinculadas: continue
        frota=norm_frota(item.get("frota",""))
        if not frota or frota.lower() in ("nan","none","null","<na>"):
            sem_frota+=1; continue
        contagem[frota]=contagem.get(frota,0)+1
    return contagem,sem_frota


def status_evidencias_pendentes(laudos):
    imported=carregar_importacoes_evidencias_pendentes()
    if imported["erro"]:
        st.warning("Não foi possível consultar as evidências pendentes. Clique em Atualizar para tentar novamente.")
        return None,0
    return contar_evidencias_pendentes(imported["registros"],laudos)


def destacar_frotas_pendentes(tabela, contagem):
    tabela=tabela.copy()
    tabela["EVIDÊNCIAS PENDENTES"]=tabela["FROTA"].apply(
        lambda frota: "Indisponível" if contagem is None else
        (f"⚠️ {contagem[norm_frota(frota)]} pendentes" if contagem.get(norm_frota(frota),0) else "—"))
    return tabela.style.apply(lambda row:
        ["background-color: #fff3cd; color: #713f12; font-weight: 600" if
         contagem is not None and contagem.get(norm_frota(row["FROTA"]),0)>0 else ""]*len(row),axis=1)


@st.fragment
def render_laudos_web():
    import json
    d=carregar_laudos_manuais_web()
    if d.empty:
        err=st.session_state.get("_erro_laudos_web")
        if err:
            st.warning(f"Laudos ainda não chegaram ao Monitor Web. Detalhe da leitura: {err}")
        else:
            st.caption("Ainda não há laudos manuais publicados.")
        return

    for c in ["REGISTRO","OS_ID","FROTA","CLASSIFICACAO","ATIVIDADE","EXECUTANTE",
              "INICIO_ATIVIDADE","FIM_ATIVIDADE","INICIO_MANUTENCAO","FIM_MANUTENCAO",
              "EVIDENCIAS","ATIVIDADE_ID","HORAS","INICIO 10 SUL","INICIO_10_SUL","INICIO 10SUL","INICIO SUZANO","INICIO_SUZANO"]:
        if c not in d.columns:
            d[c]=""

    d["HORAS"]=pd.to_numeric(d["HORAS"],errors="coerce").fillna(0.0)
    d["CLASSIFICACAO"]=d["CLASSIFICACAO"].fillna("OUTROS").astype(str).str.upper().str.strip()
    d["FROTA"]=d["FROTA"].apply(norm_frota)
    d["INICIO_ATIVIDADE_DT"]=pd.to_datetime(d["INICIO_ATIVIDADE"],errors="coerce")
    d["FIM_ATIVIDADE_DT"]=pd.to_datetime(d["FIM_ATIVIDADE"],errors="coerce")

    # 1) RESUMO COMPACTO — uma linha por MANUTENÇÃO (OS/ID + FROTA).
    # Vários laudos/compartimentos da mesma OS pertencem à mesma manutenção e
    # precisam ser consolidados em uma única linha. Se a OS estiver vazia,
    # usamos REGISTRO apenas como fallback para não juntar atendimentos distintos.
    _os=d["OS_ID"].fillna("").astype(str).str.strip()
    _reg=d["REGISTRO"].fillna("").astype(str).str.strip()
    d["_CHAVE_OS"]=_os.where(_os.ne("") & _os.str.lower().ne("nan"), _reg)
    d["_CHAVE_OS"]=d["_CHAVE_OS"].where(d["_CHAVE_OS"].ne(""), d.index.astype(str))
    pv=d.pivot_table(index=["_CHAVE_OS","FROTA"],columns="CLASSIFICACAO",values="HORAS",aggfunc="sum",fill_value=0).reset_index()
    for c in ["ITR","CNP","GM","OUTROS"]:
        if c not in pv.columns: pv[c]=0.0
    pv["TEMPO_TOTAL"]=pv[["ITR","CNP","GM","OUTROS"]].sum(axis=1)
    # Laudos sem qualquer tempo apontado não poluem o resumo.
    pv=pv[pv["TEMPO_TOTAL"] > 0].copy()
    pv=pv.iloc[::-1].reset_index(drop=True)

    # Pesquisa instantânea por frota. O filtro é aplicado no próprio resumo,
    # preservando o vínculo posicional entre a tabela e o REGISTRO selecionado.
    _busca_frota=st.text_input(
        "🔎 Pesquisar frota",
        placeholder="Digite o número da frota...",
        key="laudos_busca_frota",
    ).strip()
    if _busca_frota:
        _bf=_busca_frota.replace(".0","").strip()
        pv=pv[pv["FROTA"].astype(str).str.contains(_bf,case=False,na=False,regex=False)].reset_index(drop=True)

    resumo=pd.DataFrame({
        "FROTA":pv["FROTA"].astype(str)+"  ›",
        "ITR":pv["ITR"].apply(hhmm),
        "CNP":pv["CNP"].apply(hhmm),
        "GM":pv["GM"].apply(hhmm),
        "OUTROS":pv["OUTROS"].apply(hhmm),
        "TEMPO TOTAL":pv["TEMPO_TOTAL"].apply(hhmm),
    })
    if _busca_frota and resumo.empty:
        st.info("Nenhuma frota encontrada para essa pesquisa.")
    st.caption("Selecione uma frota para abrir o detalhamento.")
    pendencias,_=status_evidencias_pendentes(d)
    st.caption("⚠️ Amarelo: a frota tem evidências importadas ainda pendentes de vínculo ou conferência.")
    ev=st.dataframe(
        destacar_frotas_pendentes(resumo,pendencias),
        use_container_width=True,
        hide_index=True,
        height=min(310, 38+35*max(1,len(resumo))),
        on_select="rerun",
        selection_mode="single-row",
        key="laudos_resumo_tabela",
    )
    rows=list(ev.selection.rows) if hasattr(ev,"selection") else []
    if rows:
        try:
            pos=int(rows[0])
        except Exception:
            pos=-1
        # O Streamlit pode manter a seleção da tabela anterior após uma busca/filtro.
        # Nunca tente acessar uma posição que já não existe no DataFrame filtrado.
        if 0 <= pos < len(pv):
            st.session_state["wos_chave"]=str(pv.iloc[pos]["_CHAVE_OS"])
            st.session_state["wfrota_chave"]=str(pv.iloc[pos]["FROTA"])
            st.session_state["waid"]=None
        else:
            st.session_state["wos_chave"]=None
            st.session_state["wfrota_chave"]=None
            st.session_state["waid"]=None
    elif resumo.empty:
        st.session_state["wos_chave"]=None
        st.session_state["wfrota_chave"]=None
        st.session_state["waid"]=None

    # 2) MANUTENÇÃO SELECIONADA — todas as atividades/compartimentos da mesma OS + frota.
    os_chave=st.session_state.get("wos_chave")
    frota_chave=st.session_state.get("wfrota_chave")
    if not os_chave or not frota_chave: return
    det=d[d["_CHAVE_OS"].astype(str).eq(str(os_chave)) & d["FROTA"].astype(str).eq(str(frota_chave))].copy()
    if det.empty: return
    reg=str(os_chave)
    det["_AID_SEL"]=[str(v).strip() if str(v).strip() and str(v).strip().lower()!="nan" else f"{reg}_{idx}" for idx,v in zip(det.index,det["ATIVIDADE_ID"])]

    st.markdown(f"**Frota {det.iloc[0]['FROTA']} — detalhamento**")
    if MOBILE_READ_ONLY:
        liberacoes=pd.DataFrame({
            "FIM INFORMADO — 10 SUL":pd.to_datetime(det["FIM_MANUTENCAO"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("Não informado"),
            "FIM CLIENTE":pd.to_datetime(det["FIM_CLIENTE"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("OS ainda sem baixa"),
        }).drop_duplicates()
        st.dataframe(liberacoes,hide_index=True,use_container_width=True)
    else:
        periodos=[]; ids_periodos=[]
        # Um período por laudo, mantendo separados os compartimentos da mesma OS.
        for (registro,comp,ini,fim), grupo in det.groupby(
            ["REGISTRO","COMPARTIMENTO","INICIO_MANUTENCAO","FIM_MANUTENCAO"],dropna=False,sort=False):
            periodos.append({
                "LAUDO":str(registro), "COMPARTIMENTO":str(comp),
                "INÍCIO INFORMADO — 10 SUL":pd.to_datetime(ini,errors="coerce"),
                "FIM INFORMADO — 10 SUL":pd.to_datetime(fim,errors="coerce"),
                "FIM CLIENTE":pd.to_datetime(grupo["FIM_CLIENTE"],errors="coerce").max(),
            })
            ids_periodos.append(grupo["id"].tolist())
        datas_base=pd.DataFrame(periodos)
        st.caption("Edite a data e hora de início ou fim do laudo nesta tabela e salve abaixo.")
        datas_editadas=st.data_editor(datas_base,hide_index=True,use_container_width=True,num_rows="fixed",
            disabled=["LAUDO","COMPARTIMENTO","FIM CLIENTE"],
            column_config={
                "LAUDO":st.column_config.TextColumn("Laudo",width="medium"),
                "INÍCIO INFORMADO — 10 SUL":st.column_config.DatetimeColumn("INÍCIO INFORMADO — 10 SUL",format="DD/MM/YYYY HH:mm",required=True),
                "FIM INFORMADO — 10 SUL":st.column_config.DatetimeColumn("FIM INFORMADO — 10 SUL",format="DD/MM/YYYY HH:mm",required=True),
                "FIM CLIENTE":st.column_config.DatetimeColumn("FIM CLIENTE",format="DD/MM/YYYY HH:mm"),
            },key=f"datas_laudo_{reg}_{frota_chave}")
        if st.button("💾 SALVAR DATAS DO LAUDO",type="primary",key=f"salvar_datas_laudo_{reg}_{frota_chave}"):
            planos=[]; erros_datas=[]
            for i,linha in datas_editadas.iterrows():
                ini=linha["INÍCIO INFORMADO — 10 SUL"]; fim=linha["FIM INFORMADO — 10 SUL"]
                if pd.isna(ini) or pd.isna(fim) or fim<ini:
                    erros_datas.append(f"Laudo {linha['LAUDO']}: informe datas válidas e fim igual ou posterior ao início.")
                elif ini!=datas_base.iloc[i]["INÍCIO INFORMADO — 10 SUL"] or fim!=datas_base.iloc[i]["FIM INFORMADO — 10 SUL"]:
                    planos.append((ids_periodos[i],ini,fim))
            if erros_datas:
                st.error(" | ".join(erros_datas))
            else:
                for ids,ini,fim in planos:
                    ok,msg=atualizar_datas_laudo_web(ids,ini,fim)
                    if not ok:
                        erros_datas.append(msg);break
                if erros_datas: st.error(" | ".join(erros_datas))
                elif planos:
                    st.session_state["datas_laudo_salvas"]=True
                    st.rerun()
                else: st.info("Nenhuma data foi alterada.")
        if st.session_state.pop("datas_laudo_salvas",False):
            st.success("Datas do laudo atualizadas. Os indicadores foram recalculados.")

    def _tem_evidencia_atual(v):
        try:
            if v is None or (isinstance(v,float) and pd.isna(v)): return False
            txt=str(v).strip()
            if not txt or txt.lower() in ("nan","none","null","[]","{}"): return False
            obj=json.loads(txt)
            return isinstance(obj,list) and any(str(x).strip() for x in obj if x is not None)
        except Exception:
            return False

    det["_TEM_EVIDENCIA"]=det["EVIDENCIAS"].apply(_tem_evidencia_atual)
    detalhes=pd.DataFrame({
        "ATIVIDADE":[("📎 "+str(a)+"  ›") if tem else (str(a)+"  ›")
                     for a,tem in zip(det["ATIVIDADE"].fillna("Atividade"),det["_TEM_EVIDENCIA"])],
        "TIPO":det["CLASSIFICACAO"].fillna("OUTROS").astype(str),
        "INÍCIO":det["INICIO_ATIVIDADE_DT"].apply(lambda x:"--:--" if pd.isna(x) else x.strftime("%H:%M")),
        "FIM":det["FIM_ATIVIDADE_DT"].apply(lambda x:"--:--" if pd.isna(x) else x.strftime("%H:%M")),
        "TEMPO TOTAL":det["HORAS"].apply(hhmm),
    }).reset_index(drop=True)
    _styler=detalhes.style.apply(
        lambda row: ["background-color:#e8f5e9;color:#174d2a;font-weight:600;"]*len(row)
        if bool(det.reset_index(drop=True).loc[row.name,"_TEM_EVIDENCIA"]) else [""]*len(row),
        axis=1,
    )
    ev2=st.dataframe(
        _styler,
        use_container_width=True,
        hide_index=True,
        height=min(260, 38+35*max(1,len(detalhes))),
        on_select="rerun",
        selection_mode="single-row",
        key=f"laudos_detalhe_{reg}",
    )
    rows2=list(ev2.selection.rows) if hasattr(ev2,"selection") else []
    if rows2:
        st.session_state["waid"]=str(det.reset_index(drop=True).iloc[int(rows2[0])]["_AID_SEL"])

    # Edição controlada do laudo já publicado.
    if not MOBILE_READ_ONLY:
        with st.expander("✏️ Editar laudo", expanded=False):
            edit_base=det.reset_index(drop=True).copy()
            edit_view=pd.DataFrame({
                "ATIVIDADE":edit_base["ATIVIDADE"].fillna("").astype(str),
                "EXECUTANTE":edit_base["EXECUTANTE"].fillna("").astype(str),
                "TIPO":edit_base["CLASSIFICACAO"].fillna("OUTROS").astype(str),
                "INÍCIO":edit_base["INICIO_ATIVIDADE_DT"].apply(lambda x:"" if pd.isna(x) else x.strftime("%H:%M")),
                "FIM":edit_base["FIM_ATIVIDADE_DT"].apply(lambda x:"" if pd.isna(x) else x.strftime("%H:%M")),
            })
            editado=st.data_editor(
                edit_view,hide_index=True,use_container_width=True,num_rows="fixed",
                key=f"editar_laudo_{reg}_{frota_chave}",
                column_config={"TIPO":st.column_config.SelectboxColumn("TIPO",options=["ITR","CNP","GM","OUTROS"],required=True)}
            )
            if st.button("💾 SALVAR ALTERAÇÕES",type="primary",key=f"salvar_edicao_{reg}_{frota_chave}"):
                erros=[]; alteradas=0
                for i,r in editado.iterrows():
                    orig=edit_base.iloc[i]
                    aid_real=str(orig.get("ATIVIDADE_ID","") or "").strip()
                    if not aid_real or aid_real.lower()=="nan":
                        erros.append(f"Linha {i+1}: atividade sem ID interno."); continue
                    try:
                        base_ini=pd.to_datetime(orig.get("INICIO_ATIVIDADE"),errors="coerce")
                        base_fim=pd.to_datetime(orig.get("FIM_ATIVIDADE"),errors="coerce")
                        h1=datetime.strptime(str(r["INÍCIO"]).strip(),"%H:%M").time()
                        h2=datetime.strptime(str(r["FIM"]).strip(),"%H:%M").time()
                        dia=(base_ini.date() if not pd.isna(base_ini) else pd.Timestamp.today().date())
                        dt1=pd.Timestamp(datetime.combine(dia,h1)); dt2=pd.Timestamp(datetime.combine(dia,h2))
                        if dt2<dt1:dt2+=pd.Timedelta(days=1)
                        payload={
                            "atividade":str(r["ATIVIDADE"]).strip(),
                            "executante":str(r["EXECUTANTE"]).strip(),
                            "classificacao":str(r["TIPO"]).strip().upper(),
                            "inicio_atividade":dt1.strftime("%Y-%m-%dT%H:%M:%S"),
                            "fim_atividade":dt2.strftime("%Y-%m-%dT%H:%M:%S"),
                            "horas":max(0,(dt2-dt1).total_seconds()/3600),
                        }
                        mudou=(payload["atividade"]!=str(orig.get("ATIVIDADE","") or "").strip()
                               or payload["executante"]!=str(orig.get("EXECUTANTE","") or "").strip()
                               or payload["classificacao"]!=str(orig.get("CLASSIFICACAO","") or "").strip().upper()
                               or payload["inicio_atividade"]!=(base_ini.strftime("%Y-%m-%dT%H:%M:%S") if not pd.isna(base_ini) else "")
                               or payload["fim_atividade"]!=(base_fim.strftime("%Y-%m-%dT%H:%M:%S") if not pd.isna(base_fim) else ""))
                        if mudou:
                            ok,msg=atualizar_atividade_laudo_web(aid_real,payload)
                            if ok:alteradas+=1
                            else:erros.append(f"Linha {i+1}: {msg}")
                    except Exception:
                        erros.append(f"Linha {i+1}: confira INÍCIO e FIM no formato HH:MM.")
                if erros:
                    st.error(" | ".join(erros[:6]))
                else:
                    st.success(f"✅ {alteradas} atividade(s) atualizada(s).")
                    st.rerun()

    # 3) ATIVIDADE SELECIONADA — evidencia somente desta atividade.
    aid=st.session_state.get("waid")
    if not aid: return
    rr=det[det["_AID_SEL"].astype(str).eq(str(aid))]
    if rr.empty: return
    row=rr.iloc[0]
    st.markdown(f"**Evidência — {row.get('ATIVIDADE','Atividade')}**")
    try: evs=json.loads(row.get("EVIDENCIAS") or "[]")
    except Exception: evs=[]
    if not evs:
        st.info("Nenhuma evidência anexada a esta atividade.")
        return
    for j,ep in enumerate(evs):
        b,ct=baixar_evidencia_laudo_web(ep)
        if not b: continue
        if ct.startswith("image/"): st.image(b,use_container_width=True)
        elif ct.startswith("video/"): st.video(b)
        else: st.download_button("📄 Abrir/baixar evidência",b,file_name=ep.split("/")[-1],key=f"wdl_{reg}_{aid}_{j}")

def evento_flags(s):
    e=s.fillna("").astype(str).str.upper().str.strip()
    itr=e.eq("ITR")
    rev=e.str.contains("REVIS",na=False)
    sos=e.str.startswith("SOS",na=False)
    cnp=e.str.contains("CORRETIVA",na=False)&(
        e.str.contains("Ñ PROG",na=False)|e.str.contains("NÃO PROG",na=False)|e.str.contains("NAO PROG",na=False)
    )
    return e,itr,rev,sos,cnp

# Consulta de leitura por GO para o aplicativo do socorro, usando os Secrets existentes.
if st.query_params.get("socorro_historico", "0") == "1":
    from socorro_history import render_consulta
    render_consulta(carregar, _hora_brasilia)

if st.button("↻ Atualizar", key="monitor_refresh_top", type="primary", use_container_width=True):
    # Preserve archived months when manually refreshing the current data.
    for nome in ("carregar", "carregar_laudos_manuais_web",
                 "carregar_importacoes_evidencias_pendentes", "carregar_justificativas_laudos"):
        funcao = globals().get(nome)
        if funcao is not None and hasattr(funcao, "clear"):
            funcao.clear()
    st.rerun()

atualizacao_automatica = st.toggle(
    "Atualização automática a cada 1 minuto",
    value=True,
    key="monitor_auto_refresh",
    help="Desative para pausar a atualização enquanto consulta ou preenche informações.",
)

# A primeira execução acompanha o carregamento normal da página. Só o
# próximo disparo do fragmento limpa a consulta e atualiza o monitor inteiro.
st.session_state["_monitor_auto_refresh_armed"] = False


@st.fragment(run_every=60 if atualizacao_automatica else None)
def _atualizar_monitor_automaticamente():
    if st.session_state["_monitor_auto_refresh_armed"]:
        # Rerun updates elapsed times; the shared 60-second cache governs reads.
        st.rerun()
    st.session_state["_monitor_auto_refresh_armed"] = True


_atualizar_monitor_automaticamente()

try:
    df=carregar()
except Exception as e:
    st.error(f"Não foi possível carregar o monitor: {e}")
    st.stop()

if df.empty:
    st.warning("A base do monitor está vazia. Confira a sincronização da Lista ASN no Power Automate.")
    st.stop()

for c in ["parada","inicio","fim","fim_asn","fim_liberacao_10sul","previsao_liberacao_10sul"]:
    if c in df.columns:
        df[c]=pd.to_datetime(df[c].map(_hora_brasilia),errors="coerce")
for c in ["os_id","frota","evento","status","descricao","modal","unidade"]:
    if c not in df.columns: df[c]=""
df["frota"]=df["frota"].apply(norm_frota)

# Exclusões confirmadas permanecem no histórico, fora de toda apuração operacional.
mascara_excluidas = df.get("excluida_asn_em", pd.Series(None, index=df.index, dtype=object)).notna()
os_excluidas = df.loc[mascara_excluidas].copy()
df = df.loc[~mascara_excluidas].copy()

inconsistencias_asn = _inconsistencias_asn(df)

agora=pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)
ev, is_itr_all,is_rev_all,is_sos_all,is_cnp_all=evento_flags(df["evento"])

# MÉDIAS DO SUPERVISOR — ITR e REVISÃO separadas
def _base_evento(tipo):
    b=df.copy()
    e=b["evento"].fillna("").astype(str).str.upper().str.strip()
    mask=e.eq("ITR") if tipo=="ITR" else e.str.contains("REVIS",na=False)
    b=b[mask & ~b["frota"].isin(ESPECIAIS)].copy()
    b["ini_calc"]=b["inicio"].fillna(b["parada"])
    b["fim_calc"]=b["fim"].fillna(agora)
    b=b[b["ini_calc"].notna() & (b["fim_calc"]>=b["ini_calc"])].copy()
    # Em manutenção só entra após atingir o SLA; liberadas entram normalmente.
    aberto=b["fim"].isna() | b["status"].fillna("").astype(str).str.upper().str.contains("MANUT",na=False)
    total=(b["fim_calc"]-b["ini_calc"]).dt.total_seconds()/3600
    sla=12 if tipo=="ITR" else 24
    return b[(~aberto)|(total>=sla)].copy(), sla

def _quebrar_por_dia(tipo, dias=7):
    b,sla=_base_evento(tipo)
    ini_janela=agora.normalize()-pd.Timedelta(days=dias-1)
    rows=[]
    for _,r in b.iterrows():
        ini=pd.Timestamp(r["ini_calc"]); fim=min(pd.Timestamp(r["fim_calc"]),agora)
        d=max(ini.normalize(),ini_janela)
        while d<=fim.normalize():
            a=max(ini,d)
            z=min(fim,d+pd.Timedelta(days=1))
            h=max(0,(z-a).total_seconds()/3600)
            if h>0: rows.append({"DIA_DT":d,"HORAS":h})
            d+=pd.Timedelta(days=1)
    if not rows:return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA"]),None,sla
    q=pd.DataFrame(rows)
    g=q.groupby("DIA_DT",as_index=False)["HORAS"].mean().rename(columns={"HORAS":"MEDIA_H"})
    g["DIA"]=g["DIA_DT"].dt.strftime("%d/%m")
    hoje=g.loc[g["DIA_DT"].eq(agora.normalize()),"MEDIA_H"]
    return g,(float(hoje.iloc[0]) if len(hoje) else None),sla

def _grafico_media_diaria(g,sla):
    if g.empty:
        st.info("Sem dados para o período."); return
    gg=g.copy()
    gg["COR"] = gg["MEDIA_H"].apply(lambda v: "#dc2626" if float(v) >= float(sla) else "#0874d1")
    base=alt.Chart(gg).encode(
        x=alt.X("DIA:N",title=None,sort=None,axis=alt.Axis(labelAngle=0,labelFontSize=10)),
        y=alt.Y("MEDIA_H:Q",title="Horas")
    )
    linha=base.mark_line(color="#0874d1",strokeWidth=3).encode(tooltip=["DIA",alt.Tooltip("MEDIA_H:Q",format=".2f")])
    pts=base.mark_point(filled=True,size=80).encode(color=alt.Color("COR:N",scale=None,legend=None))
    rot=base.mark_text(dy=-12,fontSize=11,fontWeight="bold").encode(
        text=alt.Text("ROTULO:N"), color=alt.Color("COR:N",scale=None,legend=None))
    rule=alt.Chart(pd.DataFrame({"SLA":[sla]})).mark_rule(color="#dc2626",strokeDash=[5,4],strokeWidth=2).encode(y="SLA:Q")
    lab=alt.Chart(pd.DataFrame({"SLA":[sla],"TXT":[f"SLA {int(sla):02d}:00"]})).mark_text(
        align="right",dx=-4,dy=-7,color="#dc2626",fontSize=10,fontWeight="bold").encode(
        x=alt.value("width"),y="SLA:Q",text="TXT:N")
    st.altair_chart((linha+pts+rot+rule+lab).properties(height=135),use_container_width=True)

def _base_medias_origem(tipo,origem):
    """Médias das OS: datas de laudos não participam deste cálculo."""
    e=df["evento"].fillna("").astype(str).str.strip().str.upper()
    mask=e.eq("ITR") if tipo=="ITR" else e.str.contains("REVIS",na=False)
    b=df[mask & ~df["frota"].isin(ESPECIAIS)].copy()
    b["OS/ID"]=b["os_id"].apply(_chave_vinculo_laudo)
    b["FROTA"]=b["frota"].apply(_chave_vinculo_laudo)
    inicio_col = "parada" if origem == "Suzano" else "inicio"
    fim_col = "fim_asn" if origem == "Suzano" else "fim"
    b["INICIO_CALC"] = pd.to_datetime(b[inicio_col], errors="coerce")
    b["FIM_CALC"] = pd.to_datetime(b[fim_col], errors="coerce")
    base = b[["OS/ID", "FROTA", "INICIO_CALC", "FIM_CALC"]].copy()
    base = base.sort_values("FIM_CALC", na_position="first").drop_duplicates(["OS/ID", "FROTA"], keep="last")
    base=base[base["OS/ID"].ne("") & base["FROTA"].ne("") & base["INICIO_CALC"].notna() & base["FIM_CALC"].notna() & (base["FIM_CALC"]>=base["INICIO_CALC"]) & (base["FIM_CALC"]<=agora)].copy()
    base["HORAS"]=(base["FIM_CALC"]-base["INICIO_CALC"]).dt.total_seconds()/3600
    return base.sort_values("FIM_CALC",ascending=False).reset_index(drop=True)


def _recorte_media_origem(base,periodo):
    if periodo=="Mês acumulado":
        inicio=agora.normalize().replace(day=1); fim=agora
        return base[base["FIM_CALC"].between(inicio,fim)].copy()
    dia=agora.normalize()-pd.Timedelta(days=1)
    return base[(base["FIM_CALC"]>=dia)&(base["FIM_CALC"]<dia+pd.Timedelta(days=1))].copy()


@st.dialog("Ordens computadas na média",width="large")
def modal_ordens_media(tipo,origem,periodo,base):
    st.markdown(f"### {tipo} · {origem} · {periodo}")
    if base.empty:
        st.info("Nenhuma OS com início e fim válidos nessa origem e nesse período.")
        return
    total=base["HORAS"].sum(); quantidade=len(base)
    st.metric("Média — FIM − INÍCIO",hhmm(total/quantidade))
    st.caption(f"Tempo total {hhmm(total)} ÷ {quantidade} OS. Referência do período: FIM {origem}.")
    show=base.copy()
    show[f"INÍCIO {origem.upper()}"]=show["INICIO_CALC"].dt.strftime("%d/%m/%Y %H:%M")
    show[f"FIM {origem.upper()}"]=show["FIM_CALC"].dt.strftime("%d/%m/%Y %H:%M")
    show["TEMPO TOTAL"]=show["HORAS"].apply(hhmm)
    st.dataframe(show[["OS/ID","FROTA",f"INÍCIO {origem.upper()}",f"FIM {origem.upper()}","TEMPO TOTAL"]],hide_index=True,use_container_width=True)


@st.fragment
def _botoes_medias_origens(tipo):
    cols=st.columns(2,gap="small")
    for col,origem in zip(cols,["Suzano","10 Sul"]):
        with col:
            base=_base_medias_origem(tipo,origem)
            for periodo in ["Mês acumulado"]:
                recorte=_recorte_media_origem(base,periodo)
                media=recorte["HORAS"].mean() if len(recorte) else None
                if st.button(f"{origem} · {periodo}\n\n{hhmm(media)}\n\nVer {len(recorte)} OS ›",key=f"media_origem_{tipo}_{origem}_{periodo}",use_container_width=True):
                    modal_ordens_media(tipo,origem,periodo,recorte)
    st.caption("Suzano: parada até fim ASN. 10 Sul: início ajustado da OS até fim ASN; sem baixa ASN, usa a liberação manual identificada. Datas do laudo ficam apenas nas médias dos laudos.")



def _media_acumulada_mes(tipo):
    b,sla=_base_evento(tipo)
    inicio_mes=agora.normalize().replace(day=1)
    # Liberadas no mês e OS abertas elegíveis pelo SLA até o momento.
    b=b[b["fim_calc"].between(inicio_mes,agora)].copy()
    b=b.sort_values("ini_calc").drop_duplicates(["os_id","frota"],keep="last")
    horas=(b["fim_calc"]-b["ini_calc"]).dt.total_seconds()/3600
    return horas.mean() if not horas.empty else None


def _quadro_supervisor(tipo,icone):
    g,hoje,sla=_quebrar_por_dia(tipo,7)
    if not g.empty:g["ROTULO"]=g["MEDIA_H"].apply(hhmm)
    situacao = "SEM DADOS" if hoje is None else ("DENTRO DO SLA" if hoje < sla else "ACIMA DO SLA")
    cor = "#667085" if hoje is None else ("#15803d" if hoje < sla else "#dc2626")
    fundo = "#f8fafc" if hoje is None else ("#f0fdf4" if hoje < sla else "#fff1f2")
    st.markdown(
        f"<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:2px'>"
        f"<div style='font-size:20px;font-weight:900;color:#10284a'>{icone} {tipo}</div>"
        f"<div style='font-size:11px;font-weight:900;color:{cor};background:{fundo};padding:4px 8px;border-radius:999px'>{situacao}</div>"
        f"</div>", unsafe_allow_html=True)
    _botoes_medias_origens(tipo)
    st.markdown("<div style='font-size:11px;font-weight:850;color:#344054;margin:10px 0 4px'>MÉDIA DIÁRIA SUZANO • TEMPO DISTRIBUÍDO POR DIA • ÚLTIMOS 7 DIAS</div>",unsafe_allow_html=True)
    _grafico_media_diaria(g,sla)

def render_medias_supervisor():
    c1,c2=st.columns(2,gap="small")
    with c1:
        with st.container(border=True): _quadro_supervisor("ITR","🔧")
    with c2:
        with st.container(border=True): _quadro_supervisor("REVISÃO","🛠️")

@st.dialog("📑 Embasamento contratual", width="large")
def modal_embasamento_contratual(tema):
    # Conteúdo operacional sanitizado: não publica preços, contatos ou o PDF integral.
    dados = {
        "ITR": {
            "titulo": "ITR — Tempo médio contratual",
            "destaque": "12:00 horas",
            "texto": "A referência contratual utilizada no monitor é de 12 horas para ITR, composta por 6 horas de inspeção técnica de rotina e 6 horas para correção dos itens provenientes da ITR.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • referência operacional de ITR / nível de serviço",
        },
        "REVISÃO": {
            "titulo": "Revisão — Tempo médio contratual",
            "destaque": "24:00 horas",
            "texto": "A referência contratual utilizada no monitor é de 24 horas de tempo médio de atendimento por veículo para Revisão.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • referência operacional de Revisão / nível de serviço",
        },
        "GM": {
            "titulo": "GM — Tratamento contratual",
            "destaque": "Ocorrência operacional",
            "texto": "O documento prevê a exclusão, no cálculo dos indicadores, de avarias com GM por ocorrência operacional. A proposta utilizada como base não apresenta, nesse trecho, uma definição formal da sigla GM; por isso o monitor não amplia essa definição por conta própria.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • regras de mensuração / exclusões",
        },
        "FORA DO ESCOPO": {
            "titulo": "Atividades fora do escopo normal",
            "destaque": "Tratamento separado",
            "texto": "O documento separa alterações das características originais e intervenções maiores, usando como referência intervenções superiores a 10 HH. Também relaciona fabricação, usinagem, recondicionamento de peças, adequação/modificação de estrutura e veículos sinistrados como atividades não incluídas na proposta, observadas as ressalvas do próprio documento.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • escopo e exclusões",
        },
        "EXPURGOS": {
            "titulo": "Expurgos — Tempos desconsideráveis",
            "destaque": "Conforme condição contratual",
            "texto": "Podem ser tratados como expurgo, conforme as condições do documento, tempos atribuíveis à contratante e situações previstas, como aguardando peças, peças de má qualidade comprovada, serviços estruturais, garantias executadas por terceiros e documentação de responsabilidade da contratante.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • condições de abatimento do tempo médio",
        },
        "RESPONSABILIDADES": {
            "titulo": "Responsabilidades operacionais",
            "destaque": "Consulta gerencial",
            "texto": "Esta seção resume apenas responsabilidades operacionais necessárias à interpretação dos indicadores. Informações comerciais, valores, contatos e demais dados sensíveis não são exibidos no Monitor Web.",
            "ref": "Proposta Comercial nº 27052024 — Revisão 10 • responsabilidades da contratante e da contratada",
        },
    }
    d=dados.get(tema,dados["ITR"])
    st.markdown(f"### {d['titulo']}")
    st.markdown(f"<div style='background:#eef6ff;border:1px solid #cfe2ff;border-radius:12px;padding:14px;margin:8px 0 14px'><div style='font-size:12px;font-weight:800;color:#667085'>REFERÊNCIA</div><div style='font-size:25px;font-weight:900;color:#10284a'>{d['destaque']}</div></div>",unsafe_allow_html=True)
    st.write(d["texto"])
    st.caption(d["ref"])
    st.info("🔒 Visualização sanitizada: o contrato integral, preços, contatos e demais dados sensíveis não são disponibilizados neste monitor.")

@st.fragment
def render_embasamento_contratual():
    st.markdown("<div class='mon-section'><div class='mon-section-title'>📑 EMBASAMENTO CONTRATUAL</div><div class='mon-section-sub'>Consulta operacional sanitizada dos critérios utilizados no monitor — sem valores ou dados comerciais sensíveis</div></div>",unsafe_allow_html=True)
    temas=[("ITR","ITR • 12h"),("REVISÃO","REVISÃO • 24h"),("GM","GM"),("FORA DO ESCOPO","FORA DO ESCOPO"),("EXPURGOS","EXPURGOS"),("RESPONSABILIDADES","RESPONSABILIDADES")]
    cols=st.columns(6,gap="small")
    for i,(tema,rotulo) in enumerate(temas):
        with cols[i]:
            if st.button(f"📑\n{rotulo}",key=f"emb_{i}",use_container_width=True):
                modal_embasamento_contratual(tema)


def _coluna_laudo(d, nomes):
    """Localiza coluna mesmo que o importador use espaço ou underscore."""
    mapa={re.sub(r"[^A-Z0-9]","",str(c).upper()):c for c in d.columns}
    for nome in nomes:
        k=re.sub(r"[^A-Z0-9]","",str(nome).upper())
        if k in mapa: return mapa[k]
    return None

def _medias_laudos_por_dia(classificacao, dias=7):
    d=carregar_laudos_manuais_web().copy()
    if d.empty:
        return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA","ROTULO"]), None
    for c in ["REGISTRO","OS_ID","FROTA","CLASSIFICACAO","HORAS"]:
        if c not in d.columns: d[c]=""
    col_ini=_coluna_laudo(d,["INICIO_MANUTENCAO","INICIO MANUTENCAO","INÍCIO MANUTENÇÃO","INICIO 10 SUL","INICIO_10_SUL","INICIO10SUL"])
    if not col_ini:
        return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA","ROTULO"]), None
    d["_INI10"]=pd.to_datetime(d[col_ini],errors="coerce",dayfirst=True)
    d["HORAS"]=pd.to_numeric(d["HORAS"],errors="coerce").fillna(0.0)
    d["CLASSIFICACAO"]=d["CLASSIFICACAO"].fillna("OUTROS").astype(str).str.upper().str.strip()
    d=d[d["_INI10"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA","ROTULO"]), None
    # Primeiro soma todas as atividades da mesma OS/frota; só depois calcula a média das OS do dia.
    # Alguns registros publicados têm OS_ID vazio. O pandas descarta chaves vazias/NaN no groupby,
    # o que fazia ITR/CNP desaparecerem apesar de existirem no JSON.
    os_id=d["OS_ID"].fillna("").astype(str).str.strip()
    registro=d["REGISTRO"].fillna("").astype(str).str.strip()
    d["_CHAVE_OS"]=os_id.where(os_id.ne("") & os_id.str.lower().ne("nan"), registro)
    d["_CHAVE_OS"]=d["_CHAVE_OS"].where(d["_CHAVE_OS"].ne(""), d.index.astype(str))
    osd=(d[d["CLASSIFICACAO"].eq(classificacao)]
         .groupby(["_CHAVE_OS","FROTA"],as_index=False,dropna=False)
         .agg(HORAS=("HORAS","sum"), INICIO_10_SUL=("_INI10","first")))
    osd=osd[osd["HORAS"]>0].copy()  # 00:00 não derruba a média
    if osd.empty:
        return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA","ROTULO"]), None
    osd["DIA_DT"]=osd["INICIO_10_SUL"].dt.normalize()
    ini=agora.normalize()-pd.Timedelta(days=dias-1)
    osd=osd[(osd["DIA_DT"]>=ini)&(osd["DIA_DT"]<=agora.normalize())]
    g=osd.groupby("DIA_DT",as_index=False)["HORAS"].mean().rename(columns={"HORAS":"MEDIA_H"})
    g["DIA"]=g["DIA_DT"].dt.strftime("%d/%m")
    g["ROTULO"]=g["MEDIA_H"].apply(hhmm)
    # KPI dos laudos usa sempre o dia anterior, pois os laudos chegam fechados D-1.
    dia_anterior=agora.normalize()-pd.Timedelta(days=1)
    hj=g.loc[g["DIA_DT"].eq(dia_anterior),"MEDIA_H"]
    return g,(float(hj.iloc[0]) if len(hj) else None)

def _grafico_laudos(g, classificacao):
    if g.empty:
        st.info("Sem dados de laudos para o período."); return
    cor="#0874d1" if classificacao=="ITR" else "#b42318"
    base=alt.Chart(g).encode(
        x=alt.X("DIA:N",title=None,sort=None,axis=alt.Axis(labelAngle=0,labelFontSize=10)),
        y=alt.Y("MEDIA_H:Q",title="Horas")
    )
    linha=base.mark_line(point=alt.OverlayMarkDef(size=65),color=cor,strokeWidth=3)
    rot=base.mark_text(dy=-12,fontSize=11,fontWeight="bold",color=cor).encode(text=alt.Text("ROTULO:N"))
    st.altair_chart((linha+rot).properties(height=135),use_container_width=True)

def _quadro_media_laudo(classificacao, icone):
    g,hoje=_medias_laudos_por_dia(classificacao,7)
    st.markdown(f"<div style='font-size:20px;font-weight:900;color:#10284a'>{icone} {classificacao} — LAUDOS</div>",unsafe_allow_html=True)
    st.markdown(
        f"<div style='display:flex;align-items:end;gap:10px;margin:6px 0 6px'>"
        f"<span style='font-size:11px;font-weight:800;color:#667085'>MÉDIA DO DIA</span>"
        f"<span style='font-size:28px;line-height:1;font-weight:900;color:#10284a'>{hhmm(hoje)}</span></div>",unsafe_allow_html=True)
    st.markdown("<div style='font-size:11px;font-weight:850;color:#344054;margin:4px 0 2px'>MÉDIA DIÁRIA • ÚLTIMOS 7 DIAS • DATA = INÍCIO 10 SUL</div>",unsafe_allow_html=True)
    _grafico_laudos(g,classificacao)

@st.fragment
def render_medias_laudos():
    c1,c2=st.columns(2,gap="small")
    with c1:
        with st.container(border=True): _quadro_media_laudo("ITR","🔧")
    with c2:
        with st.container(border=True): _quadro_media_laudo("CNP","🚨")


def _normalizar_atividade_gerencial(txt):
    """Normaliza a atividade para o relatório, preservando componentes distintos."""
    if txt is None or pd.isna(txt):
        return "Outras atividades"

    import unicodedata
    s = str(txt).upper().strip()
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "Outras atividades"

    # Leituras evidentemente suspeitas da IA: não inventar classificação.
    if any(t in s for t in ["VAZAROLA", "VAZARROLA", "VASAROLA", "VASARROLA"]):
        return "⚠️ Descrição a revisar"

    # FREIO x AMARRAÇÃO: regras específicas e prioritárias.
    # Nunca classificar CATRACA isoladamente.
    if "CATRACA" in s and "FREIO" in s:
        return "Catraca de freio"
    if "CATRACA" in s and "AMARR" in s:
        return "Catraca de amarração"
    if "GANCHO" in s and "AMARR" in s:
        return "Gancho de amarração"
    if any(t in s for t in ["REGULAR CATRACA", "REGULAGEM CATRACA", "REGULAR FREIO", "REGULAGEM FREIO", "REGULA FREIO", "REGUL FREIO", "REGULAR S RODAS"]):
        return "Regulagem de freio"
    if "TAMBOR" in s and "FREIO" in s:
        return "Tambor de freio"
    if any(t in s for t in ["CUICA", "CAMARA DE FREIO"]):
        return "Cuíca de freio"
    if any(t in s for t in ["LONA DE FREIO", "LONA FREIO", "LONAS DE FREIO", "LONAS FREIO"]):
        return "Lona de freio"
    if "BRUCUTU" in s:
        return "Sistema de freio"
    if "PINCA" in s:
        return "Sistema de freio"

    # Quinta roda é componente próprio; 'sapata' aqui não significa freio.
    if any(t in s for t in ["5 RODA", "5A RODA", "QUINTA RODA"]):
        return "Quinta roda"

    if "PINO REI" in s:
        return "Pino rei"

    # Lona estrutural do implemento, separada de lona de freio.
    if any(t in s for t in ["PONTA DE LONA", "PONTA LONA", "PONTA DA LONA", "PORTA DE LONA", "PORTA LONA", "PORTAS DE LONA", "PORTAS LONA"]):
        return "Ponta de lona"
    if ("LONA" in s or "LONAS" in s) and "FREIO" not in s:
        return "Ponta de lona"

    if any(t in s for t in ["PROTETOR LATERAL", "PROTECAO LATERAL", "PROTECAO LATER", "PROT LATERAL"]):
        return "Protetor lateral"

    # Solda/fabricação estrutural.
    if any(t in s for t in ["CHAPA DE ASSOALHO", "CHAPA ASSOALHO", "ASSOALHO", "SOLDAR", "SOLDA", "TRINCA"]):
        return "SOLDA"
    if "PARALAMA" in s and "SUPORTE" in s and any(t in s for t in ["FABRICAR", "FABRICACAO", "SOLDAR", "SOLDA", "REPARAR"]):
        return "SOLDA"
    if "PARALAMA" in s:
        return "Paralama"

    # Suspensão / rodeiro.
    if any(t in s for t in ["BUCHA", "BUCHAS", "MANCAL", "BALANCA"]):
        return "Bucha / Mancal / Balança"
    if any(t in s for t in ["AMORTECEDOR", "PONTA DE EIXO", "PONTAS DE EIXO", "MOLA AZUL", "LAMINA", "SUSPENSAO", "TIRANTE", "TIRANTES"]):
        return "Suspensão"
    if any(t in s for t in ["FOLGA DE CUBO", "CUBO", "RODEIRO TRAVADO", "RODEIRO PRESO", "DESTRAVAR RODEIRO", "DESTRAVAMENTO RODEIRO"]):
        return "Cubo / Rodeiro"
    if any(t in s for t in ["BOLSA DE SUSPENSAO", "BOLSA SUSPENSAO", "BOLSA DE AR", "VALVULA NIVELADORA", "NIVELADORA", "DRENO DO BALAO", "DRENO BALAO"]):
        return "Suspensão pneumática"

    # Sistema pneumático geral, depois das regras específicas de suspensão.
    if any(t in s for t in ["GATILHO PNEUMATICO", "PNEUMATICO", "PNEUMATICA", "VAZAMENTO DE AR", "MANGUEIRA DE AR", "CONEXAO DE AR"]):
        return "Pneumático / Sistema de ar"

    if "CALCO" in s and "CAVALO" in s:
        return "Calço de cavalo"

    if any(t in s for t in ["TROCA DE PNEU", "TROCAR PNEU", "SUBSTITUIR PNEU", "SUBSTITUICAO PNEU"]):
        return "Troca de pneu"
    if any(t in s for t in ["CORUJINHA", "ILUMINACAO", "LANTERNA", "LANTERNAS", "LUZ LATERAL", "LUZ DE POSICAO"]):
        return "Iluminação / Corujinha"

    return "Outras atividades"


def _chave_vinculo_laudo(valor):
    if valor is None or pd.isna(valor):
        return ""
    texto=str(valor).strip()
    if texto.lower() in ("nan","none","null","<na>"):
        return ""
    return re.sub(r"\.0$","",texto)


def listar_itr_sem_laudo(atendimentos, laudos):
    """O vínculo exige a mesma OS e frota, independentemente da baixa."""
    itr=atendimentos[atendimentos["evento"].fillna("").astype(str).str.strip().str.upper().eq("ITR")].copy()
    itr["_OS"]=itr["os_id"].apply(_chave_vinculo_laudo)
    itr["_FROTA"]=itr["frota"].apply(_chave_vinculo_laudo)
    vinculados=set()
    if not laudos.empty:
        if not {"OS_ID","FROTA"}.issubset(laudos.columns):
            raise ValueError("A base de laudos não possui OS/ID e FROTA para verificar o vínculo.")
        vinculados={(osid,frota) for osid,frota in zip(
            laudos["OS_ID"].apply(_chave_vinculo_laudo),
            laudos["FROTA"].apply(_chave_vinculo_laudo)) if osid and frota}
    pendentes=itr[[not (osid and frota and (osid,frota) in vinculados)
                   for osid,frota in zip(itr["_OS"],itr["_FROTA"])]].copy() if len(itr) else itr.copy()
    # Duplicatas da sincronização não devem aumentar o contador.
    pendentes=pendentes.drop_duplicates(["_OS","_FROTA","inicio","parada"],keep="last")
    com_id=pendentes[pendentes["_OS"].ne("")].drop_duplicates(["_OS","_FROTA"],keep="last")
    sem_id=pendentes[pendentes["_OS"].eq("")]
    return pd.concat([com_id,sem_id],ignore_index=True)


def render_itr_sem_laudo():
    st.markdown("#### 📋 ITR sem vínculo com laudo")
    st.caption("Vínculo conferido por OS/ID + FROTA na base de laudos publicados. Inclui OS abertas e liberadas; laudo de outra ITR da mesma frota não elimina a pendência.")
    laudos=carregar_laudos_manuais_web()
    if st.session_state.get("_erro_laudos_web"):
        st.warning("Não foi possível consultar os laudos. A lista de pendências estará disponível quando a leitura for restabelecida.")
        return
    try:
        pendentes=listar_itr_sem_laudo(df,laudos)
    except ValueError as erro:
        st.warning(str(erro))
        return
    a,b,c=st.columns(3)
    with a:
        periodo=st.selectbox("Período da ITR",["Últimos 30 dias","Mês atual","Últimos 7 dias","Todo o histórico","Personalizado"],key="itr_sem_laudo_periodo")
    with b:
        situacao=st.selectbox("Situação da OS",["Todas","Em manutenção","Liberadas"],key="itr_sem_laudo_status")
    with c:
        busca=st.text_input("Pesquisar frota",key="itr_sem_laudo_frota",placeholder="Ex.: 13725").strip()
    ref=pendentes["inicio"].fillna(pendentes["parada"])
    if periodo!="Todo o histórico":
        fim=agora
        if periodo=="Mês atual": inicio=agora.normalize().replace(day=1)
        elif periodo=="Últimos 7 dias": inicio=agora.normalize()-pd.Timedelta(days=6)
        elif periodo=="Últimos 30 dias": inicio=agora.normalize()-pd.Timedelta(days=29)
        else:
            a,b=st.columns(2)
            with a: inicio=pd.Timestamp(st.date_input("De",value=agora.date().replace(day=1),key="itr_sem_laudo_de"))
            with b: fim=pd.Timestamp(st.date_input("Até",value=agora.date(),key="itr_sem_laudo_ate"))+pd.Timedelta(days=1)-pd.Timedelta(seconds=1)
        pendentes=pendentes[ref.between(inicio,fim)].copy()
    if situacao=="Em manutenção": pendentes=pendentes[pendentes["fim"].isna()].copy()
    elif situacao=="Liberadas": pendentes=pendentes[pendentes["fim"].notna()].copy()
    if busca:
        pendentes=pendentes[pendentes["_FROTA"].str.contains(busca,regex=False,na=False)].copy()
    a,b=st.columns(2)
    with a: st.metric("Frotas sem vínculo",pendentes.loc[pendentes["_FROTA"].ne(""),"_FROTA"].nunique())
    with b: st.metric("ITR sem vínculo",len(pendentes))
    if pendentes.empty:
        st.success("Nenhuma ITR sem vínculo com laudo nos filtros selecionados.")
        return
    pendentes["_INICIO"]=pendentes["inicio"].fillna(pendentes["parada"])
    pendentes=pendentes.sort_values("_INICIO",ascending=False,na_position="last")
    show=pd.DataFrame({
        "OS/ID":pendentes["_OS"].replace("","Não informado"),
        "FROTA":pendentes["_FROTA"].replace("","Não informada"),
        "INÍCIO":pendentes["_INICIO"].dt.strftime("%d/%m/%Y %H:%M").fillna("Não informado"),
        "FIM CLIENTE":pendentes["fim"].dt.strftime("%d/%m/%Y %H:%M").fillna("Sem baixa"),
        "SITUAÇÃO":pendentes["fim"].notna().map({True:"Liberada",False:"Em manutenção"}),
        "PENDÊNCIA":pendentes["_OS"].eq("").map({True:"OS/ID ausente — vínculo não verificável",False:"Sem laudo vinculado"}),
    })
    st.dataframe(show,hide_index=True,use_container_width=True)


@st.cache_data(ttl=60, show_spinner=False)
def carregar_justificativas_laudos():
    """Registros independentes no Storage; não altera atividades do laudo."""
    import json
    h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
    base=f"{SUPABASE_URL}/storage/v1"
    registros=[]; offset=0
    while True:
        r=requests.post(f"{base}/object/list/evidencias-desvios",headers=h,
                        json={"prefix":"justificativas-laudos","limit":100,"offset":offset,"sortBy":{"column":"name","order":"asc"}},timeout=45)
        r.raise_for_status()
        objetos=r.json()
        for obj in objetos:
            nome=obj.get("name","")
            if not nome.endswith(".json"): continue
            rr=requests.get(f"{base}/object/evidencias-desvios/justificativas-laudos/{nome}",headers=h,timeout=45)
            rr.raise_for_status()
            item=rr.json()
            if not isinstance(item,dict) or item.get("versao")!=1:
                raise ValueError("Registro de justificativa inválido.")
            registros.append(item)
        if len(objetos)<100: break
        offset+=100
    return pd.DataFrame(registros)


def horas_sem_sobreposicao_laudo(atividades):
    """União de intervalos: simultaneidade não aumenta o tempo decorrido."""
    intervalos=[]
    sem_horario=0.0
    for _,r in atividades.iterrows():
        inicio=_hora_brasilia(r.get("INICIO_ATIVIDADE"))
        fim=_hora_brasilia(r.get("FIM_ATIVIDADE"))
        if pd.notna(inicio) and pd.notna(fim) and fim>=inicio:
            intervalos.append((inicio,fim))
        else:
            horas=pd.to_numeric(r.get("HORAS"),errors="coerce")
            if pd.notna(horas):
                sem_horario+=max(0,float(horas))
    total=0.0
    ini_atual=fim_atual=None
    for inicio,fim in sorted(intervalos):
        if ini_atual is None:
            ini_atual,fim_atual=inicio,fim
        elif inicio<=fim_atual:
            fim_atual=max(fim_atual,fim)
        else:
            total+=(fim_atual-ini_atual).total_seconds()/3600
            ini_atual,fim_atual=inicio,fim
    if ini_atual is not None:
        total+=(fim_atual-ini_atual).total_seconds()/3600
    return total+sem_horario


def consolidar_tempos_laudos(atividades):
    linhas=[]
    for (osid,frota),grupo in atividades.groupby(["CHAVE_OS","FROTA"],sort=False):
        linha={"CHAVE_OS":osid,"FROTA":frota,"APONTADO_REAL":horas_sem_sobreposicao_laudo(grupo)}
        for tipo in ["ITR","CNP","GM","OUTROS"]:
            linha[tipo]=horas_sem_sobreposicao_laudo(grupo[grupo["CLASSIFICACAO"].eq(tipo)])
        linhas.append(linha)
    return pd.DataFrame(linhas,columns=["CHAVE_OS","FROTA","APONTADO_REAL","ITR","CNP","GM","OUTROS"])


def apurar_tempos_justificados(manut,piv,justificativas):
    base=manut.merge(piv,on=["CHAVE_OS","FROTA"],how="left").copy()
    base["APONTADO"]=base["APONTADO_REAL"].fillna(0) if "APONTADO_REAL" in base else base[["ITR","CNP","GM","OUTROS"]].fillna(0).sum(axis=1)
    # O saldo é calculado em cada OS; excesso de outra OS não compensa lacunas.
    base["SEM_APONTAMENTO"]=(base["H_MANUT"]-base["APONTADO"]).clip(lower=0).fillna(0)
    totais={}
    if not justificativas.empty:
        for _,r in justificativas.iterrows():
            chave=(_chave_vinculo_laudo(r.get("os_id")),_chave_vinculo_laudo(r.get("frota")))
            minutos=pd.to_numeric(r.get("minutos"),errors="coerce")
            if chave[0] and chave[1] and pd.notna(minutos) and minutos>0:
                totais[chave]=totais.get(chave,0)+float(minutos)/60
    base["JUSTIFICADO_REGISTRADO"]=[totais.get((_chave_vinculo_laudo(o),_chave_vinculo_laudo(f)),0) for o,f in zip(base["CHAVE_OS"],base["FROTA"])]
    base["JUSTIFICADO"]=base[["SEM_APONTAMENTO","JUSTIFICADO_REGISTRADO"]].min(axis=1)
    base["PENDENTE"]=(base["SEM_APONTAMENTO"]-base["JUSTIFICADO"]).clip(lower=0)
    return base


def salvar_justificativa_laudo(osid,frota,minutos,motivo,observacao,responsavel,inicio=None,fim=None):
    if MOBILE_READ_ONLY:
        raise PermissionError("Esta versão permite somente consulta.")
    import uuid
    registro={"versao":1,"id":uuid.uuid4().hex,"os_id":_chave_vinculo_laudo(osid),
              "frota":_chave_vinculo_laudo(frota),"minutos":int(minutos),"motivo":motivo,
              "observacao":observacao.strip(),"responsavel":responsavel.strip(),
              "inicio":inicio.isoformat() if inicio is not None else None,
              "fim":fim.isoformat() if fim is not None else None,
              "registrado_em":pd.Timestamp.now(tz="America/Sao_Paulo").isoformat()}
    h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}","Content-Type":"application/json","x-upsert":"false"}
    r=requests.post(f"{SUPABASE_URL}/storage/v1/object/evidencias-desvios/justificativas-laudos/{registro['id']}.json",headers=h,json=registro,timeout=45)
    r.raise_for_status()
    carregar_justificativas_laudos.clear()


@st.dialog("Justificativas do tempo sem apontamento",width="large")
def modal_justificativas_laudos(manut,piv,os_validas,consulta=False):
    try:
        js=carregar_justificativas_laudos()
        base=apurar_tempos_justificados(manut,piv,js)
    except Exception:
        st.error("Não foi possível consultar as justificativas salvas. Verifique o acesso ao armazenamento de evidências.")
        return
    view=base.copy()
    for c in ["SEM_APONTAMENTO","JUSTIFICADO","PENDENTE"]: view[c]=view[c].apply(hhmm)
    st.dataframe(view[["CHAVE_OS","FROTA","SEM_APONTAMENTO","JUSTIFICADO","PENDENTE"]].rename(columns={"CHAVE_OS":"OS/ID","SEM_APONTAMENTO":"SEM APONTAMENTO","JUSTIFICADO":"JUSTIFICADO","PENDENTE":"A JUSTIFICAR"}),hide_index=True,use_container_width=True)
    if not js.empty:
        chaves={(_chave_vinculo_laudo(o),_chave_vinculo_laudo(f)) for o,f in zip(base.CHAVE_OS,base.FROTA)}
        hist=js[[(_chave_vinculo_laudo(r.os_id),_chave_vinculo_laudo(r.frota)) in chaves for _,r in js.iterrows()]].copy()
        if not hist.empty:
            hist["TEMPO"]=hist["minutos"].apply(lambda v:hhmm(float(v)/60))
            for _c in ("inicio","fim"):
                if _c not in hist.columns: hist[_c]=None
            st.markdown("**Justificativas registradas**")
            st.dataframe(hist[["os_id","frota","inicio","fim","TEMPO","motivo","observacao","responsavel","registrado_em"]].rename(columns={"os_id":"OS/ID","frota":"FROTA","inicio":"INÍCIO","fim":"FIM","motivo":"MOTIVO","observacao":"OBSERVAÇÃO","responsavel":"RESPONSÁVEL INFORMADO","registrado_em":"REGISTRO"}),hide_index=True,use_container_width=True)
    if consulta or MOBILE_READ_ONLY: return
    op=base[base["PENDENTE"]>0].copy()
    op=op[[(_chave_vinculo_laudo(o),_chave_vinculo_laudo(f)) in os_validas for o,f in zip(op.CHAVE_OS,op.FROTA)]] if len(op) else op
    if op.empty:
        st.info("Nenhuma OS com saldo e identificador válido para justificar.")
        return
    pos=st.selectbox("Manutenção",range(len(op)),format_func=lambda i:f"Frota {op.iloc[i]['FROTA']} · OS {op.iloc[i]['CHAVE_OS']} · Saldo {hhmm(op.iloc[i]['PENDENTE'])}")
    row=op.iloc[pos]
    with st.form("registrar_justificativa_tempo"):
        st.caption("Adicione quantos intervalos forem necessários. Cada justificativa é salva separadamente.")
        motivo=st.selectbox("Motivo",["Inspeção da Mega","Aguardando box","Aguardando peça","Aguardando liberação do cliente","Intervalo","Falta de equipe","Outros"])
        c_ini,c_fim=st.columns(2)
        inicio=c_ini.time_input("Início",value=None,step=60)
        fim=c_fim.time_input("Fim",value=None,step=60)
        obs=st.text_area("Observação")
        nome=st.text_input("Responsável pelo registro")
        gravar=st.form_submit_button("Adicionar justificativa",type="primary")
    if gravar:
        if inicio is None or fim is None or not nome.strip() or (motivo=="Outros" and not obs.strip()):
            st.error("Informe início, fim, responsável e observação quando o motivo for Outros.")
            return
        from datetime import datetime as _datetime
        dia_base=pd.to_datetime(row.get("INICIO"),errors="coerce")
        if pd.isna(dia_base):
            st.error("A manutenção está sem data de início válida.")
            return
        inicio_dt=_datetime.combine(dia_base.date(),inicio)
        fim_dt=_datetime.combine(dia_base.date(),fim)
        if fim_dt<=inicio_dt:
            st.error("O horário final deve ser posterior ao inicial. Para intervalos que atravessam a meia-noite, registre em dias separados.")
            return
        minutos=int((fim_dt-inicio_dt).total_seconds()//60)
        try:
            carregar_justificativas_laudos.clear()
            js_atual=carregar_justificativas_laudos()
            atual=apurar_tempos_justificados(manut,piv,js_atual)
            saldo=atual.loc[atual.CHAVE_OS.eq(row.CHAVE_OS)&atual.FROTA.eq(row.FROTA),"PENDENTE"].iloc[0]
            if minutos<=0 or minutos>int(round(saldo*60)):
                st.error("O intervalo deve ter duração positiva e não pode ultrapassar o saldo da OS.")
                return
            if not js_atual.empty:
                for _,reg in js_atual.iterrows():
                    if (_chave_vinculo_laudo(reg.get("os_id"))!=_chave_vinculo_laudo(row.CHAVE_OS)
                        or _chave_vinculo_laudo(reg.get("frota"))!=_chave_vinculo_laudo(row.FROTA)):
                        continue
                    ant_ini=pd.to_datetime(reg.get("inicio"),errors="coerce")
                    ant_fim=pd.to_datetime(reg.get("fim"),errors="coerce")
                    if pd.notna(ant_ini) and pd.notna(ant_fim) and inicio_dt<ant_fim.to_pydatetime() and fim_dt>ant_ini.to_pydatetime():
                        st.error("Este intervalo se sobrepõe a uma justificativa já registrada.")
                        return
            salvar_justificativa_laudo(row.CHAVE_OS,row.FROTA,minutos,motivo,obs,nome,inicio_dt,fim_dt)
            st.session_state["justificativa_salva"]=True
            st.rerun()
        except Exception as e:
            st.error(f"Não foi possível salvar a justificativa: {e}")



def calcular_medias_periodicas_laudos(manut, piv):
    """Uma manutenção por OS/frota; semana de segunda a domingo."""
    base=manut.merge(piv, on=["CHAVE_OS","FROTA"], how="left").copy()
    base=base[base["FIM"].notna() & base["H_MANUT"].notna()].copy()
    base["DIA"]=base["FIM"].dt.normalize()
    base["SEMANA"]=base["DIA"]-pd.to_timedelta(base["DIA"].dt.weekday,unit="D")
    for tipo in ["ITR","CNP"]:
        base[tipo]=base[tipo].where(base[tipo]>0)
    def agrupar(coluna):
        return (base.groupby(coluna,as_index=False)
                .agg(MANUTENCOES=("H_MANUT","size"),MEDIA_MANUT=("H_MANUT","mean"),
                     MEDIA_ITR=("ITR","mean"),MEDIA_CNP=("CNP","mean"))
                .sort_values(coluna))
    return agrupar("DIA"),agrupar("SEMANA")


def atividades_da_manutencao_laudo(base, chave_os, frota):
    """Mantém OS e frota juntas, inclusive quando a frota tem vários atendimentos."""
    return base.loc[
        base["CHAVE_OS"].astype(str).eq(str(chave_os)) &
        base["FROTA"].astype(str).eq(str(frota))
    ].copy().reset_index(drop=True)


def pendentes_da_frota_monitor(registros, laudos, frota):
    import json
    vinculadas=set()
    for value in laudos.get("EVIDENCIAS",pd.Series(dtype=str)):
        try:
            paths=value if isinstance(value,list) else json.loads(value or "[]")
            if isinstance(paths,list): vinculadas.update(p for p in paths if isinstance(p,str))
        except (TypeError,ValueError): pass
    vistos=set(); pendentes=[]
    for item in registros:
        path=item.get("path",""); identity=item.get("sha256") or path
        if not identity or identity in vistos: continue
        vistos.add(identity)
        if item.get("armazenado") and path not in vinculadas and norm_frota(item.get("frota",""))==norm_frota(frota):
            pendentes.append(item)
    return pendentes


def vincular_evidencia_no_monitor(atividade, path):
    if MOBILE_READ_ONLY:
        return False,"Esta versão permite somente consulta."
    key=_secret("SUPABASE_WRITE_KEY") or _secret("SUPABASE_SERVICE_KEY") or SUPABASE_KEY
    if not SUPABASE_URL or not key:
        return False,"Acesso à gravação não configurado no monitor."
    try:
        payload={"p_id":int(atividade["id"]),"p_atividade_id":str(atividade["ATIVIDADE_ID"]),
                 "p_os_id":str(atividade["OS_ID"]),"p_frota":norm_frota(atividade["FROTA"]),"p_path":path}
        headers={"apikey":key,"Content-Type":"application/json"}
        if not key.startswith(("sb_secret_","sb_publishable_")):
            headers["Authorization"]=f"Bearer {key}"
        response=requests.post(f"{SUPABASE_URL}/rest/v1/rpc/anexar_evidencia_itr",headers=headers,json=payload,timeout=45)
        if response.status_code in (401,403):
            return False,"O monitor está com acesso de leitura à base. É necessário configurar uma chave de servidor autorizada em SUPABASE_WRITE_KEY nos Secrets para confirmar vínculos."
        if not response.ok:
            try:message=response.json().get("message","")
            except ValueError:message=""
            return False,message or f"Não foi possível salvar o vínculo (HTTP {response.status_code})."
        result=response.json()
        if not isinstance(result,dict) or result.get("id")!=payload["p_id"] or path not in result.get("evidencias",[]):
            return False,"O vínculo não foi confirmado pela base. Atualize o monitor e confira a atividade."
        carregar_laudos_manuais_web.clear()
        return True,"Evidência vinculada à atividade."
    except (KeyError,TypeError,ValueError):
        return False,"Atividade sem identificação válida. Atualize o monitor antes de vincular."
    except Exception:
        return False,"Não foi possível comunicar com a base. Tente novamente."


def render_vinculo_pendente_monitor(atividades, frota, contexto, atividade_selecionada=None):
    if st.session_state.pop("evidencia_vinculada_monitor",False):
        st.success("✅ Evidência vinculada. A quantidade de pendências foi atualizada.")
    imported=carregar_importacoes_evidencias_pendentes()
    if imported["erro"]: return
    pendentes=pendentes_da_frota_monitor(imported["registros"],carregar_laudos_manuais_web(),frota)
    if not pendentes: return
    with st.expander(f"📷 Resolver {len(pendentes)} evidência(s) pendente(s) aqui",expanded=True):
        by_path={item["path"]:item for item in pendentes}
        path=st.selectbox("Evidência pendente",list(by_path),
            format_func=lambda p:f"{str(by_path[p].get('data',''))[:10]} · {by_path[p].get('arquivo',p.split('/')[-1])}",
            key=f"rg_pendente_foto_{contexto}")
        item=by_path[path]
        data,content_type=baixar_evidencia_laudo_web(path)
        if not data:
            st.warning("Não foi possível abrir a evidência. Atualize o monitor e tente novamente.")
            return
        if content_type.startswith("image/"): st.image(data,use_container_width=True)
        elif content_type.startswith("video/"): st.video(data)
        else: st.download_button("Abrir evidência",data,file_name=item.get("arquivo","evidencia"),key=f"rg_pendente_arquivo_{contexto}")
        st.write(item.get("legenda") or "Sem descrição na conversa.")
        st.caption(f"Registro: {item.get('data','')} · Frota {frota}. Confira a data, o compartimento e a atividade antes de confirmar.")
        if MOBILE_READ_ONLY:
            st.info("Esta versão permite somente consultar as evidências."); return
        choices=[None]+list(range(len(atividades)))
        initial=atividade_selecionada+1 if atividade_selecionada is not None else 0
        chosen=st.selectbox("Vincular à atividade deste laudo",choices,index=initial,
            format_func=lambda pos:"Selecione a atividade" if pos is None else
                f"{atividades.iloc[pos].get('COMPARTIMENTO','')} · {atividades.iloc[pos]['ATIVIDADE']} · {atividades.iloc[pos].get('CLASSIFICACAO','')}",
            key=f"rg_pendente_atividade_{contexto}_{item.get('sha256','')}")
        if st.button("✅ Confirmar vínculo nesta atividade",type="primary",disabled=chosen is None,
            key=f"rg_pendente_confirmar_{contexto}_{item.get('sha256','')}"):
            ok,message=vincular_evidencia_no_monitor(atividades.iloc[int(chosen)],path)
            if ok:
                st.session_state["evidencia_vinculada_monitor"]=True
                st.rerun()
            else:st.error(message)


def render_atividades_evidencias_gerencial(base, chave_os, frota):
    import json
    import hashlib
    atividades=atividades_da_manutencao_laudo(base,chave_os,frota)
    if atividades.empty:
        st.info("Nenhuma atividade de laudo encontrada para este atendimento.")
        return
    def arquivos(value):
        try:
            parsed=value if isinstance(value,list) else json.loads(value or "[]")
            return [p for p in parsed if isinstance(p,str) and p.strip()] if isinstance(parsed,list) else []
        except (TypeError,ValueError):
            return []
    for col in ["EVIDENCIAS","ATIVIDADE_ID","INICIO_ATIVIDADE","FIM_ATIVIDADE"]:
        if col not in atividades: atividades[col]=""
    contexto=hashlib.sha256(json.dumps([str(chave_os),str(frota),
        atividades["ATIVIDADE_ID"].fillna("").astype(str).tolist(),
        atividades["ATIVIDADE"].fillna("").astype(str).tolist()],ensure_ascii=False).encode()).hexdigest()[:20]
    st.markdown(f"**Atividades — Frota {frota} · OS/ID {chave_os}**")
    totais=atividades.groupby("CLASSIFICACAO")["HORAS"].sum()
    st.caption(" · ".join(f"{tipo}: {hhmm(totais.get(tipo,0))}" for tipo in ["ITR","CNP","GM","OUTROS"]))
    mostrar=atividades[["COMPARTIMENTO","ATIVIDADE","CLASSIFICACAO","EXECUTANTE"]].copy()
    mostrar=mostrar.rename(columns={"COMPARTIMENTO":"COMP.","CLASSIFICACAO":"TIPO"})
    for original,label in [("INICIO_ATIVIDADE","INÍCIO"),("FIM_ATIVIDADE","FIM")]:
        mostrar[label]=pd.to_datetime(atividades[original],errors="coerce").dt.strftime("%d/%m %H:%M").fillna("")
    mostrar["TEMPO"]=atividades["HORAS"].apply(hhmm)
    mostrar["EVIDÊNCIAS"]=atividades["EVIDENCIAS"].apply(lambda value:len(arquivos(value)))
    st.caption("Clique em uma atividade para abrir suas fotos, vídeos ou documentos.")
    event=st.dataframe(mostrar,hide_index=True,use_container_width=True,
        height=min(440,38+35*max(1,len(mostrar))),
        on_select="rerun",selection_mode="single-row",key=f"rg_atividades_{contexto}")
    selected=list(event.selection.rows) if hasattr(event,"selection") else []
    selected_pos=int(selected[0]) if selected and 0 <= int(selected[0]) < len(atividades) else None
    render_vinculo_pendente_monitor(atividades,frota,contexto,selected_pos)
    if not selected or not 0 <= int(selected[0]) < len(atividades): return
    row=atividades.iloc[int(selected[0])]
    evidencias=arquivos(row.get("EVIDENCIAS"))
    st.markdown(f"**Evidências — {row['ATIVIDADE']}**")
    if not evidencias:
        st.info("Nenhuma evidência anexada a esta atividade.")
        return
    for i,path in enumerate(evidencias):
        data,content_type=baixar_evidencia_laudo_web(path)
        if not data:
            st.warning("Não foi possível abrir esta evidência. Clique em Atualizar para tentar novamente.")
        elif content_type.startswith("image/"):
            st.image(data,use_container_width=True)
        elif content_type.startswith("video/"):
            st.video(data)
        else:
            st.download_button("📄 Abrir/baixar evidência",data,file_name=path.split("/")[-1],
                key=f"rg_evidencia_{contexto}_{int(selected[0])}_{i}")


@st.fragment
def render_relatorio_gerencial_laudos():
    d=carregar_laudos_manuais_web().copy()
    st.markdown("<div class='mon-section'><div class='mon-section-title'>📊 RELATÓRIO GERENCIAL — LAUDOS DE MANUTENÇÃO</div><div class='mon-section-sub'>Análise gerencial baseada exclusivamente nos laudos conferidos e publicados</div></div>",unsafe_allow_html=True)
    if d.empty:
        st.info("Ainda não há laudos conferidos publicados para montar o relatório gerencial.")
        return
    for c in ["REGISTRO","OS_ID","FROTA","COMPARTIMENTO","CLASSIFICACAO","ATIVIDADE","EXECUTANTE","HORAS","INICIO_MANUTENCAO","FIM_MANUTENCAO"]:
        if c not in d.columns: d[c]=""
    d["FROTA"]=d["FROTA"].apply(norm_frota)
    d["HORAS"]=pd.to_numeric(d["HORAS"],errors="coerce").fillna(0.0)
    d["CLASSIFICACAO"]=d["CLASSIFICACAO"].fillna("OUTROS").astype(str).str.upper().str.strip()
    d["INI_DT"]=pd.to_datetime(d["INICIO_MANUTENCAO"],errors="coerce",dayfirst=True)
    d["FIM_DT"]=pd.to_datetime(d["FIM_MANUTENCAO"],errors="coerce",dayfirst=True)
    d=d[d["INI_DT"].notna()].copy()
    if d.empty:
        st.info("Os laudos publicados ainda não possuem data de início válida."); return
    hoje_rg=agora.normalize(); mes_ini_rg=hoje_rg.replace(day=1)
    a,b,c=st.columns([1.25,1,1])
    with a:
        periodo=st.selectbox("Período",["Mês atual","Últimos 7 dias","Últimos 30 dias","Personalizado"],key="rg_periodo")
    if periodo=="Mês atual": di,dfim=mes_ini_rg,agora
    elif periodo=="Últimos 7 dias": di,dfim=hoje_rg-pd.Timedelta(days=6),agora
    elif periodo=="Últimos 30 dias": di,dfim=hoje_rg-pd.Timedelta(days=29),agora
    else:
        with b: di0=st.date_input("De",value=mes_ini_rg.date(),key="rg_de")
        with c: df0=st.date_input("Até",value=hoje_rg.date(),key="rg_ate")
        di=pd.Timestamp(di0); dfim=pd.Timestamp(df0)+pd.Timedelta(days=1)-pd.Timedelta(seconds=1)
    frotas_rg=sorted(
        frota for frota in d["FROTA"].unique()
        if frota and frota.lower() not in ("nan","none","null","<na>")
    )
    frota_rg=st.selectbox(
        "🔎 Filtrar por frota",
        ["Todas as frotas"]+frotas_rg,
        key="rg_frota",
        help="Digite o número para localizar uma frota. O filtro atualiza todos os indicadores, gráficos e detalhes deste relatório.",
    )
    # Usa a liberação consolidada da OS, mantendo todos os compartimentos.
    os_base=d["OS_ID"].fillna("").astype(str).str.strip()
    reg_base=d["REGISTRO"].fillna("").astype(str).str.strip()
    d["CHAVE_OS"]=os_base.where(os_base.ne("")&os_base.str.lower().ne("nan"),reg_base)
    d["CHAVE_OS"]=d["CHAVE_OS"].where(d["CHAVE_OS"].ne(""),d.index.astype(str))
    fim_os=d.groupby(["CHAVE_OS","FROTA"])["FIM_DT"].transform("max")
    x=d[(fim_os>=di)&(fim_os<=dfim)].copy()
    if frota_rg!="Todas as frotas":
        x=x[x["FROTA"].eq(frota_rg)].copy()
    if x.empty:
        st.info("Sem laudos conferidos para a frota e o período selecionados." if frota_rg!="Todas as frotas" else "Sem laudos conferidos no período selecionado.")
        return
    osid=x["OS_ID"].fillna("").astype(str).str.strip(); reg=x["REGISTRO"].fillna("").astype(str).str.strip()
    x["CHAVE_OS"]=osid.where(osid.ne("")&osid.str.lower().ne("nan"),reg)
    x["CHAVE_OS"]=x["CHAVE_OS"].where(x["CHAVE_OS"].ne(""),x.index.astype(str))
    manut=(x.groupby(["CHAVE_OS","FROTA"],as_index=False).agg(INICIO=("INI_DT","min"),FIM=("FIM_DT","max")))
    manut["H_MANUT"]=((manut["FIM"]-manut["INICIO"]).dt.total_seconds()/3600).clip(lower=0)
    total_laudos=x["REGISTRO"].replace("",pd.NA).nunique() or x["CHAVE_OS"].nunique()
    frotas=x["FROTA"].nunique(); med_man=manut.loc[manut["H_MANUT"]>0,"H_MANUT"].mean()
    piv=consolidar_tempos_laudos(x)
    for cc in ["ITR","CNP","GM","OUTROS"]:
        if cc not in piv.columns:piv[cc]=0.0
    med_itr=piv.loc[piv["ITR"]>0,"ITR"].mean(); med_cnp=piv.loc[piv["CNP"]>0,"CNP"].mean()
    apont=piv["APONTADO_REAL"].sum(); hman=manut["H_MANUT"].sum()
    erro_justificativas=False
    try:
        justificativas=carregar_justificativas_laudos()
    except Exception:
        justificativas=pd.DataFrame()
        erro_justificativas=True
    tempos=apurar_tempos_justificados(manut,piv,justificativas)
    sem=tempos["SEM_APONTAMENTO"].sum()
    pendente=tempos["PENDENTE"].mean()
    justificado=tempos["JUSTIFICADO"].mean()
    os_validas={(_chave_vinculo_laudo(o),_chave_vinculo_laudo(f)) for o,f in zip(x["OS_ID"],x["FROTA"]) if _chave_vinculo_laudo(o) and _chave_vinculo_laudo(f)}

    cards=[("📄","Total de Laudos",str(int(total_laudos)),"#eef6ff"),("🚛","Carretas Atendidas",str(int(frotas)),"#eef6ff"),("⏱️","Tempo Médio de Manutenção",hhmm(med_man),"#ecfdf5"),("🔧","Tempo Médio ITR",hhmm(med_itr),"#fff7ed"),("🛠️","Tempo Médio CNP",hhmm(med_cnp),"#fff1f2")]
    cs=st.columns(3,gap="small")+st.columns(2,gap="small")
    for col,(ico,lab,val,bg) in zip(cs,cards):
        with col: st.markdown(f"<div style='background:{bg};border:1px solid #dbe3ec;border-radius:12px;padding:13px 8px;text-align:center;min-height:105px'><div style='font-size:12px;font-weight:850;color:#344054'>{ico} {lab}</div><div style='font-size:27px;font-weight:900;color:#10284a;margin-top:10px'>{val}</div></div>",unsafe_allow_html=True)
    st.markdown("<br>",unsafe_allow_html=True)
    if st.session_state.pop("justificativa_salva",False):
        st.success("Justificativa salva.")
    if erro_justificativas:
        st.warning("As justificativas não puderam ser consultadas. Os saldos estão indisponíveis até restabelecer a leitura.")
    cpend,cjust=st.columns(2,gap="small")
    with cpend:
        if st.button(f"🔴 Tempo sem justificativa\n\n{hhmm(pendente) if not erro_justificativas else '--:--'}\n\n{"Consultar saldo ›" if MOBILE_READ_ONLY else "Justificar tempo ›"}",key="rg_justificar_tempo",use_container_width=True,disabled=erro_justificativas):
            modal_justificativas_laudos(manut,piv,os_validas,consulta=MOBILE_READ_ONLY)
    with cjust:
        if st.button(f"🔵 Tempo justificado\n\n{hhmm(justificado) if not erro_justificativas else '--:--'}\n\nConsultar justificativas ›",key="rg_consultar_justificativas",use_container_width=True,disabled=erro_justificativas):
            modal_justificativas_laudos(manut,piv,os_validas,consulta=True)
    st.caption("Cards de tempo: média por manutenção. Justificativas não alteram o tempo total nem os apontamentos de ITR/CNP.")
    st.markdown("<br>",unsafe_allow_html=True)

    st.markdown("**Confronto ASN × laudos — por OS e frota**")
    st.caption("Tempo ASN = início até liberação da Lista ASN. Apontado = tempo dos intervalos das atividades da mesma OS/frota, contando sobreposições uma única vez. Diferença positiva é tempo a esclarecer; não comprova o motivo da espera.")
    st.caption("Atividades sem início/fim válidos mantêm as horas informadas, pois não é possível identificar paralelismo nesses registros. Médias ITR/CNP também descontam sobreposições dentro da categoria; categorias diferentes podem ocorrer em paralelo.")
    confronto=manut.merge(piv[["CHAVE_OS","FROTA","APONTADO_REAL","ITR","CNP","GM","OUTROS"]],on=["CHAVE_OS","FROTA"],how="left")
    confronto["APONTADO"]=confronto["APONTADO_REAL"].fillna(0)
    origem=df.copy()
    origem["CHAVE_OS"]=origem["os_id"].apply(_chave_vinculo_laudo)
    origem["FROTA"]=origem["frota"].apply(norm_frota)
    origem["INICIO_ASN"]=pd.to_datetime(origem.get("inicio_asn",pd.Series(pd.NaT,index=origem.index)).map(_hora_brasilia),errors="coerce")
    origem["FIM_ASN"]=pd.to_datetime(origem.get("fim_asn",pd.Series(pd.NaT,index=origem.index)).map(_hora_brasilia),errors="coerce")
    origem=origem.drop_duplicates(["CHAVE_OS","FROTA"],keep="last")
    confronto["CHAVE_OS"]=confronto["CHAVE_OS"].apply(_chave_vinculo_laudo)
    confronto=confronto.merge(origem[["CHAVE_OS","FROTA","INICIO_ASN","FIM_ASN"]],on=["CHAVE_OS","FROTA"],how="left",validate="one_to_one")
    confronto["H_ASN"]=(confronto["FIM_ASN"]-confronto["INICIO_ASN"]).dt.total_seconds()/3600
    confronto.loc[confronto["H_ASN"].lt(0),"H_ASN"]=float("nan")
    confronto["DIFERENCA"]=confronto["H_ASN"]-confronto["APONTADO"]
    for col,label in zip(st.columns(3),["Tempo total ASN","Tempo total apontado nos laudos","Diferença ASN − apontado"]):
        with col:
            if label=="Tempo total ASN":
                valor=hhmm(confronto["H_ASN"].sum(min_count=1))
            elif label=="Tempo total apontado nos laudos":
                valor=hhmm(confronto["APONTADO"].sum())
            else:
                validos=confronto[confronto["H_ASN"].notna()]
                saldo=validos["DIFERENCA"].sum(min_count=1)
                valor=("--:--" if pd.isna(saldo) else ("−" if saldo<0 else "")+hhmm(abs(saldo)))
            st.metric(label,valor)
    exib=confronto[["CHAVE_OS","FROTA"]].rename(columns={"CHAVE_OS":"OS/ID"}).copy()
    for campo,label in [("INICIO_ASN","INÍCIO ASN"),("FIM_ASN","LIBERAÇÃO ASN")]:
        exib[label]=confronto[campo].dt.strftime("%d/%m/%Y %H:%M").fillna("Não informado")
    exib["TEMPO ASN"]=confronto["H_ASN"].apply(hhmm)
    exib["APONTADO NO LAUDO"]=confronto["APONTADO"].apply(hhmm)
    exib["DIFERENÇA"]=confronto["DIFERENCA"].apply(lambda h:"--:--" if pd.isna(h) else ("−" if h<0 else "")+hhmm(abs(h)))
    exib["CONFERÊNCIA"]=confronto.apply(lambda r:"ASN sem início/liberação válida" if pd.isna(r.H_ASN) else ("Tempo a esclarecer" if r.DIFERENCA>1/120 else ("Apontamento superior à ASN" if r.DIFERENCA< -1/120 else "Tempos conferem")),axis=1)
    st.dataframe(exib.style.apply(lambda r:["background-color: #fff1f2" if r["CONFERÊNCIA"]=="Tempo a esclarecer" else "" for _ in r],axis=1),hide_index=True,use_container_width=True)
    if confronto["H_ASN"].isna().any():
        st.caption("OS sem datas válidas da ASN ficam fora do total ASN e da diferença. Não se substituem datas ASN por datas do laudo ou liberação 10 Sul.")
    st.markdown("<br>",unsafe_allow_html=True)

    st.markdown("**Médias diárias e semanais — manutenção, ITR e CNP**")
    st.caption("Referência: FIM informado pela 10 Sul. Uma manutenção por OS/frota. Semana: segunda a domingo. ITR e CNP consideram apenas manutenções com tempo na categoria. Os filtros de período e frota se aplicam às médias.")
    medias_dia,medias_semana=calcular_medias_periodicas_laudos(manut,piv)
    tab_dia,tab_semana=st.tabs(["Média por dia","Média por semana"])
    for tab,tabela,coluna in [(tab_dia,medias_dia,"DIA"),(tab_semana,medias_semana,"SEMANA")]:
        with tab:
            if tabela.empty:
                st.caption("Sem manutenções liberadas para calcular as médias.")
                continue
            ultimo=tabela.iloc[-1]
            rotulo=(ultimo[coluna].strftime("%d/%m/%Y") if coluna=="DIA"
                    else f"{ultimo[coluna].strftime('%d/%m/%Y')} a {(ultimo[coluna]+pd.Timedelta(days=6)).strftime('%d/%m/%Y')}")
            st.caption(f"{'Último dia com liberação' if coluna=='DIA' else 'Última semana com liberação'} no período: {rotulo}")
            for col,(label,campo) in zip(st.columns(3),[("Média manutenção","MEDIA_MANUT"),("Média ITR","MEDIA_ITR"),("Média CNP","MEDIA_CNP")]):
                with col: st.metric(label,hhmm(ultimo[campo]))
            exib=tabela.copy()
            exib[coluna]=exib[coluna].apply(lambda v: v.strftime("%d/%m/%Y") if coluna=="DIA" else f"{v.strftime('%d/%m/%Y')} a {(v+pd.Timedelta(days=6)).strftime('%d/%m/%Y')}")
            for campo in ["MEDIA_MANUT","MEDIA_ITR","MEDIA_CNP"]:
                exib[campo]=exib[campo].apply(hhmm)
            st.dataframe(exib.rename(columns={coluna:"DIA" if coluna=="DIA" else "SEMANA (SEG–DOM)","MANUTENCOES":"MANUTENÇÕES","MEDIA_MANUT":"MÉDIA MANUTENÇÃO","MEDIA_ITR":"MÉDIA ITR","MEDIA_CNP":"MÉDIA CNP"}),hide_index=True,use_container_width=True)
    st.markdown("<br>",unsafe_allow_html=True)
    g1,g2,g3=st.columns([1.5,1,1],gap="small")
    diario=x.assign(DIA=x.groupby(["CHAVE_OS","FROTA"])["FIM_DT"].transform("max").dt.normalize()).groupby(["DIA","CLASSIFICACAO"],as_index=False)["HORAS"].sum()
    with g1:
        with st.container(border=True):
            st.markdown("**Evolução dos tempos apontados por dia**")
            if not diario.empty:
                ch=alt.Chart(diario).mark_bar().encode(x=alt.X("DIA:T",title=None),y=alt.Y("HORAS:Q",title="Horas"),color=alt.Color("CLASSIFICACAO:N",title=None),tooltip=["DIA:T","CLASSIFICACAO:N",alt.Tooltip("HORAS:Q",format=".2f")]).properties(height=260)
                st.altair_chart(ch,use_container_width=True)
    comp=pd.DataFrame({"TIPO":["ITR","CNP","GM","OUTROS","SEM APONTAMENTO"],"HORAS":[x.loc[x.CLASSIFICACAO.eq("ITR"),"HORAS"].sum(),x.loc[x.CLASSIFICACAO.eq("CNP"),"HORAS"].sum(),x.loc[x.CLASSIFICACAO.eq("GM"),"HORAS"].sum(),x.loc[x.CLASSIFICACAO.eq("OUTROS"),"HORAS"].sum(),sem]})
    with g2:
        with st.container(border=True):
            st.markdown("**Composição do tempo**")
            _sel_tipo=alt.selection_point(fields=["TIPO"],name="tipo_rg",on="click",clear="dblclick")
            ch=(alt.Chart(comp[comp.HORAS>0]).mark_arc(innerRadius=55)
                .encode(theta="HORAS:Q",color=alt.Color("TIPO:N",title=None),
                        opacity=alt.condition(_sel_tipo,alt.value(1.0),alt.value(0.35)),
                        tooltip=["TIPO",alt.Tooltip("HORAS:Q",format=".2f")])
                .add_params(_sel_tipo).properties(height=260))
            _ev_tipo=st.altair_chart(ch,use_container_width=True,on_select="rerun",key="rg_composicao_tipo")
            _tipo_click=None
            try:
                _raw=_ev_tipo.selection.get("tipo_rg",[])
                if isinstance(_raw,list) and _raw:
                    _tipo_click=str(_raw[0].get("TIPO","") or "").upper().strip()
            except Exception:
                _tipo_click=None
            if _tipo_click:
                st.session_state["rg_tipo_atividade"]=_tipo_click
            _tipo_filtro=st.session_state.get("rg_tipo_atividade")
            if _tipo_filtro:
                st.caption(f"Filtro ativo: {_tipo_filtro} · dê duplo clique no gráfico ou use Limpar.")
                if st.button("✖ Limpar filtro",key="rg_limpar_tipo",use_container_width=True):
                    st.session_state.pop("rg_tipo_atividade",None); st.rerun()
    with g3:
        with st.container(border=True):
            st.markdown("**Tempo por compartimento**")
            cp=x.groupby("COMPARTIMENTO",as_index=False)["HORAS"].mean(); cp=cp[cp["COMPARTIMENTO"].astype(str).str.strip().ne("")]
            if cp.empty: st.caption("Sem compartimento informado.")
            else:
                ch=alt.Chart(cp).mark_bar().encode(y=alt.Y("COMPARTIMENTO:N",title=None,sort="-x"),x=alt.X("HORAS:Q",title="Horas"),tooltip=["COMPARTIMENTO",alt.Tooltip("HORAS:Q",format=".2f")]).properties(height=260)
                st.altair_chart(ch,use_container_width=True)
    t1,t2=st.columns(2,gap="small")
    with t1:
        with st.container(border=True):
            st.markdown("**🔧 Principais intervenções identificadas nos laudos**")
            st.caption("Conta cada frota uma única vez por família de serviço, mesmo que a atividade apareça em vários compartimentos. Clique em uma linha para conferir as descrições originais.")
            _tipo_ativo=st.session_state.get("rg_tipo_atividade")
            if _tipo_ativo=="SEM APONTAMENTO":
                tc=x.iloc[0:0].copy()
                st.info("SEM APONTAMENTO é o intervalo da manutenção sem atividade registrada; por isso não há atividades para listar.")
            elif _tipo_ativo in ("ITR","CNP","GM","OUTROS"):
                tc=x[x.CLASSIFICACAO.eq(_tipo_ativo)].copy()
            else:
                tc=x.copy()
            if tc.empty and _tipo_ativo!="SEM APONTAMENTO":
                st.caption(f"Sem atividades {_tipo_ativo or ''} no período.".replace("  "," "))
            elif _tipo_ativo!="SEM APONTAMENTO":
                tc["FAMILIA"] = tc["ATIVIDADE"].apply(_normalizar_atividade_gerencial)
                tc["_OS_FROTA"] = tc["CHAVE_OS"].astype(str)+"|"+tc["FROTA"].astype(str)
                fam=(tc.groupby("FAMILIA",as_index=False)
                     .agg(CARRETAS=("FROTA","nunique"), INTERVENCOES=("_OS_FROTA","nunique"), HORAS=("HORAS","sum")))
                fam["% DAS CARRETAS"]=(fam["CARRETAS"]/max(1,frotas)*100).round(1)
                fam=fam.sort_values(["CARRETAS","INTERVENCOES","HORAS"],ascending=False).reset_index(drop=True)
                fam_show=fam.copy()
                fam_show["TEMPO TOTAL"]=fam_show["HORAS"].apply(hhmm)
                fam_show["% DAS CARRETAS"]=fam_show["% DAS CARRETAS"].apply(lambda v:f"{v:.1f}%".replace(".",","))
                evfam=st.dataframe(fam_show[["FAMILIA","CARRETAS","% DAS CARRETAS","INTERVENCOES","TEMPO TOTAL"]].rename(columns={"FAMILIA":"ATIVIDADE NORMALIZADA","INTERVENCOES":"OS/ATENDIMENTOS"}),hide_index=True,use_container_width=True,on_select="rerun",selection_mode="single-row",key="rg_familias_servicos")
                sel=list(evfam.selection.rows) if hasattr(evfam,"selection") else []
                if sel and 0 <= int(sel[0]) < len(fam):
                    familia_sel=str(fam.iloc[int(sel[0])]["FAMILIA"])
                    rel=tc[tc["FAMILIA"].eq(familia_sel)].copy()
                    rel["TEMPO"]=rel["HORAS"].apply(hhmm)
                    rel=rel.rename(columns={"OS_ID":"OS/ID","COMPARTIMENTO":"COMP.","ATIVIDADE":"DESCRIÇÃO ORIGINAL"})
                    st.markdown(f"**{familia_sel} — {rel['FROTA'].nunique()} de {frotas} carretas atendidas**")
                    st.dataframe(rel[["FROTA","OS/ID","COMP.","DESCRIÇÃO ORIGINAL","TEMPO"]].drop_duplicates(),hide_index=True,use_container_width=True,height=min(260,38+35*max(1,len(rel))))
    with t2:
        with st.container(border=True):
            st.markdown("**Carretas com maior tempo de manutenção**")
            pendencias,sem_frota=status_evidencias_pendentes(d)
            if pendencias is not None:
                st.caption("⚠️ Amarelo: evidências pendentes de conferência/vínculo para a frota. A quantidade considera todas as importações.")
                if pendencias or sem_frota:
                    with st.expander(f"⚠️ Frotas com evidências pendentes ({len(pendencias)})",expanded=False):
                        lista=pd.DataFrame([{"FROTA":f,"ARQUIVOS PENDENTES":q} for f,q in sorted(pendencias.items())],
                            columns=["FROTA","ARQUIVOS PENDENTES"])
                        st.dataframe(lista,hide_index=True,use_container_width=True)
                        if sem_frota: st.caption(f"Outros {sem_frota} arquivos aguardam identificação da frota.")
            top=manut.sort_values("H_MANUT",ascending=False).head(10).copy().reset_index(drop=True); top["TEMPO TOTAL"]=top["H_MANUT"].apply(hhmm); top["INÍCIO"]=top["INICIO"].dt.strftime("%d/%m %H:%M"); top["FIM"]=top["FIM"].dt.strftime("%d/%m %H:%M")
            import hashlib
            ranking_key=hashlib.sha256(top[["CHAVE_OS","FROTA","INÍCIO","FIM"]].to_json(orient="values").encode()).hexdigest()[:20]
            st.caption("Clique na frota para ver as atividades e suas evidências.")
            evento_top=st.dataframe(destacar_frotas_pendentes(top[["FROTA","INÍCIO","FIM","TEMPO TOTAL"]],pendencias),hide_index=True,use_container_width=True,
                on_select="rerun",selection_mode="single-row",key=f"rg_maior_tempo_{ranking_key}")
            selecionadas_top=list(evento_top.selection.rows) if hasattr(evento_top,"selection") else []
            if selecionadas_top and 0 <= int(selecionadas_top[0]) < len(top):
                manutencao=top.iloc[int(selecionadas_top[0])]
                if pendencias and pendencias.get(str(manutencao["FROTA"]),0):
                    st.warning(f"Frota {manutencao['FROTA']}: {pendencias[str(manutencao['FROTA'])]} evidência(s) pendente(s). Confira e vincule abaixo, nesta mesma tela.")
                render_atividades_evidencias_gerencial(x,manutencao["CHAVE_OS"],manutencao["FROTA"])
    st.markdown("**Detalhamento dos laudos do período**")
    det=x[["FROTA","OS_ID","COMPARTIMENTO","ATIVIDADE","CLASSIFICACAO","EXECUTANTE","HORAS"]].copy(); det["TEMPO"]=det["HORAS"].apply(hhmm); det=det.rename(columns={"OS_ID":"OS/ID","COMPARTIMENTO":"COMP.","CLASSIFICACAO":"TIPO"})
    st.dataframe(det[["FROTA","OS/ID","COMP.","ATIVIDADE","TIPO","EXECUTANTE","TEMPO"]],hide_index=True,use_container_width=True,height=330)


def _retornos_pos_itr(base, agora):
    """Última ITR concluída por frota; conta OS distintas até 120h após a liberação."""
    cols = ["Frota", "Última ITR", "Qtd. paradas após ITR"]
    b = base.copy()
    if b.empty:
        return pd.DataFrame(columns=cols), b
    b = b.loc[b.get("excluida_asn_em", pd.Series(None, index=b.index, dtype=object)).isna()]
    b = b.drop_duplicates(["os_id", "frota"], keep="last").copy()
    ev = b["evento"].fillna("").astype(str).str.upper().str.strip()
    # A liberação operacional 10 Sul prevalece para o intervalo de retorno.
    lib = pd.to_datetime(b.get("fim_liberacao_10sul", pd.Series(pd.NaT, index=b.index)), errors="coerce")
    b["_lib_itr"] = lib.fillna(pd.to_datetime(b["fim"], errors="coerce"))
    itrs = b.loc[ev.eq("ITR") & b["_lib_itr"].notna() & b["_lib_itr"].le(agora)]
    itrs = itrs.sort_values(["_lib_itr", "os_id"]).drop_duplicates("frota", keep="last")
    ret = b.loc[ev.str.contains("CORRETIVA", regex=False) | ev.str.match(r"^(?:SOS\b|CNP\b)")].copy()
    ret["_parada_retorno"] = pd.to_datetime(ret["parada"], errors="coerce").fillna(pd.to_datetime(ret["inicio"], errors="coerce"))
    itrs = itrs[["frota", "os_id", "_lib_itr"]].rename(columns={"os_id":"OS ITR", "_lib_itr":"Última ITR"})
    ret = ret.drop(columns=["_lib_itr"]).merge(itrs, on="frota", how="inner")
    delta = ret["_parada_retorno"] - ret["Última ITR"]
    ret = ret.loc[delta.ge(pd.Timedelta(0)) & delta.le(pd.Timedelta(days=5)) & ret["_parada_retorno"].le(agora) & ret["os_id"].ne(ret["OS ITR"])].copy()
    resumo = ret.groupby(["frota", "Última ITR"], as_index=False).agg(**{"Qtd. paradas após ITR":("os_id", "nunique")})
    resumo = resumo.rename(columns={"frota":"Frota"}).sort_values(["Qtd. paradas após ITR", "Frota"], ascending=[False,True])
    return resumo[cols], ret


# Oficina agora segue a baixa ASN: conclusão 10 Sul mantém a OS na relação.
status=df["status"].fillna("").astype(str).str.upper()
fim_cliente = pd.to_datetime(df.get("fim_asn", df["fim"]), errors="coerce")
_, itr_oficina, revisao_oficina, sos_oficina, cnp_oficina = evento_flags(df["evento"])
eventos_oficina = itr_oficina | revisao_oficina | sos_oficina | cnp_oficina
presente_abertas_asn = df.get("ausente_abertas_asn_em", pd.Series(None, index=df.index, dtype=object)).isna()
mon=df[status.str.contains("MANUT",na=False)&fim_cliente.isna()&eventos_oficina&presente_abertas_asn].copy()
mon["fim_liberacao_10sul"]=pd.to_datetime(
    mon.get("fim_liberacao_10sul", pd.Series(pd.NaT, index=mon.index)), errors="coerce")
mon["finalizada_10sul"]=mon["fim_liberacao_10sul"].notna()
mon["inicio_mon"]=mon["inicio"].fillna(mon["parada"])
mon["horas_aberto"]=((mon["fim_liberacao_10sul"].fillna(agora)-mon["inicio_mon"]).dt.total_seconds()/3600).clip(lower=0)
mon=mon.sort_values("inicio_mon",ascending=False).drop_duplicates("os_id",keep="first")
mev,mitr,mrev,msos,mcnp=evento_flags(mon["evento"])
mon["sla_h"]=pd.NA
mon.loc[mitr,"sla_h"]=12.0
mon.loc[mrev,"sla_h"]=24.0
mon["sla_h"]=pd.to_numeric(mon["sla_h"],errors="coerce")
mon["acima_sla"]=~mon["finalizada_10sul"]&mon["sla_h"].notna()&(mon["horas_aberto"]>=mon["sla_h"])

def _motivos_parada_alerta(descricao):
    """Agrupa termos da descrição; não infere diagnóstico ausente na ASN."""
    import unicodedata
    texto = "" if pd.isna(descricao) else str(descricao)
    texto = unicodedata.normalize("NFKD", texto.upper()).encode("ascii", "ignore").decode()
    regras = {
        "travamento de rodeiro": r"\b(?:RODEIR\w*|RODAS?|CUBOS?)\b.{0,45}\b(?:TRAV\w*|BLOQUE\w*)\b|\b(?:TRAV\w*|BLOQUE\w*)\b.{0,45}\b(?:RODEIR\w*|RODAS?|CUBOS?)\b",
        "problemas no sistema de freio": r"\b(?:FREI\w*|CATRACA\w*|CUICA\w*|LONAS?\b.{0,15}\bFREIO)\b",
        "problemas no rodeiro / cubo / rolamento": r"\b(?:RODEIR\w*|CUBOS?|ROLAMENT\w*)\b",
        "problemas na suspensão / bolsas": r"\b(?:SUSPENS\w*|BOLSAS?|AMORTECED\w*|MOLAS?)\b",
        "problemas no sistema pneumático / ar": r"\b(?:PNEUMATIC\w*|COMPRESSOR\w*)\b|\bVAZ\w*\b.{0,25}\bAR\b|\b(?:MANGUEIR\w*|CONEX\w*|VALVUL\w*)\b.{0,25}\bAR\b",
        "problemas elétricos / iluminação": r"\b(?:ELETR\w*|ILUMIN\w*|LANTERN\w*|LUZ\w*|FAROL\w*|CHICOTE\w*|CORUJA\w*)\b",
        "problemas na estrutura / solda": r"\b(?:SOLD\w*|TRINC\w*|ESTRUT\w*|CHASSI\w*|SUPORTE\w*)\b",
        "problemas nos pneus": r"\b(?:PNEUS?|BORRACH\w*)\b",
    }
    motivos = [nome for nome, padrao in regras.items() if re.search(padrao, texto)]
    if "travamento de rodeiro" in motivos and "problemas no rodeiro / cubo / rolamento" in motivos:
        motivos.remove("problemas no rodeiro / cubo / rolamento")
    return motivos or ["outros motivos / descrição a conferir"]


def _paradas_alerta_sete_dias(base, agora_local):
    """Janela móvel de 7 dias pela parada; cada OS/frota é contada uma vez."""
    b = base.copy()
    for coluna in ["os_id", "frota", "evento", "modal", "descricao", "status"]:
        if coluna not in b:
            b[coluna] = ""
    for coluna in ["parada", "inicio"]:
        b[coluna] = pd.to_datetime(b.get(coluna, pd.Series(pd.NaT, index=b.index)).map(_hora_brasilia), errors="coerce")
    b["frota"] = b["frota"].fillna("").map(norm_frota)
    b["os_id"] = b["os_id"].fillna("").astype(str).str.strip()
    evento = b["evento"].fillna("").astype(str).str.upper()
    import unicodedata
    evento = evento.map(lambda v: unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode())
    elegivel = evento.str.match(r"^\s*(?:SOS|CNP)\b") | (
        evento.str.contains("CORRETIV", regex=False) & evento.str.contains(r"\b(?:NAO|N)\s*PROG"))
    b["data_parada_alerta"] = b["parada"].fillna(b["inicio"])
    excluida = b.get("excluida_asn_em", pd.Series(None, index=b.index, dtype=object)).notna()
    b = b.loc[elegivel & ~excluida & b["frota"].ne("") & ~b["frota"].isin(ESPECIAIS)
              & ~b["modal"].fillna("").astype(str).str.contains("CAVALO", case=False)
              & b["data_parada_alerta"].ge(agora_local - pd.Timedelta(days=7))
              & b["data_parada_alerta"].le(agora_local)].copy()
    # Sem OS identificada, preservar paradas diferentes da mesma frota.
    b["_chave_os_alerta"] = b["os_id"].where(b["os_id"].ne(""), b["data_parada_alerta"].astype(str))
    b = b.drop_duplicates(["_chave_os_alerta", "frota"], keep="last")
    b["motivo_alerta"] = b["descricao"].map(_motivos_parada_alerta)
    return b.explode("motivo_alerta")


@st.dialog("🚨 Carretas do alerta — últimos 7 dias", width="large")
def modal_carretas_alerta_sete_dias(motivo, relacao):
    st.markdown(f"**{motivo.capitalize()}**")
    st.caption(f"{relacao['frota'].nunique()} carretas distintas • {len(relacao)} paradas / OS")
    relacao = relacao.sort_values("data_parada_alerta", ascending=False)
    tabela = relacao[["os_id", "frota", "data_parada_alerta", "descricao"]].copy()
    tabela["data_parada_alerta"] = tabela["data_parada_alerta"].dt.strftime("%d/%m/%Y %H:%M")
    tabela = tabela.rename(columns={"os_id":"ID", "frota":"FROTA",
                                   "data_parada_alerta":"DATA DA PARADA", "descricao":"DESCRIÇÃO"})
    st.dataframe(tabela, hide_index=True, use_container_width=True,
                 column_config={"DESCRIÇÃO": st.column_config.TextColumn("DESCRIÇÃO", width="large")})
    st.caption("Toque ou dê dois cliques na descrição para consultar o texto completo.")


def render_alertas_paradas_sete_dias(base, agora_local):
    detalhes = _paradas_alerta_sete_dias(base, agora_local)
    inicio_janela = agora_local - pd.Timedelta(days=7)
    periodo = f"{inicio_janela:%d/%m/%Y %H:%M} a {agora_local:%d/%m/%Y %H:%M}"
    if detalhes.empty:
        st.caption("Alertas CNP / SOS • últimos 7 dias: nenhuma parada de carreta registrada no período.")
        return
    resumo = detalhes.groupby("motivo_alerta")["frota"].nunique().sort_values(ascending=False)
    st.markdown("""
    <style>
    .st-key-alertas_paradas_7d div[data-testid="stButton"] > button {
        background:#ffebee!important;color:#a52a35!important;
        border:1px solid #f7cbd1!important;border-radius:12px!important;
        padding:20px 24px!important;text-align:left!important;
        justify-content:flex-start!important;min-height:90px!important;
        height:auto!important;white-space:normal!important;
    }
    .st-key-alertas_paradas_7d div[data-testid="stButton"] > button p {
        font-size:18px!important;font-weight:600!important;text-align:left!important;
    }
    .st-key-alertas_paradas_7d div[data-testid="stButton"] > button:hover {
        background:#ffdce1!important;border-color:#b42332!important;
    }
    .st-key-alertas_paradas_7d div[data-testid="stButton"] > button:focus-visible {
        outline:3px solid #b42332!important;outline-offset:2px!important;
    }
    </style>
    """, unsafe_allow_html=True)
    st.markdown("### 🚨 ATENÇÃO, LIDERANÇA — PARADAS NOS ÚLTIMOS 7 DIAS")
    st.caption("Clique em um alerta para ver as carretas e as descrições das paradas.")
    with st.container(key="alertas_paradas_7d"):
        for motivo, quantidade in resumo.items():
            verbo = "parou" if quantidade == 1 else "pararam"
            carreta = "carreta" if quantidade == 1 else "carretas"
            if st.button(
                f"🚨 ATENÇÃO: {quantidade} {carreta} {verbo} por {motivo} nos últimos sete dias.  ›",
                key=f"alerta_paradas_7d_{motivo}", use_container_width=True,
                help="Abrir ID, frota, data da parada e descrição",
            ):
                relacao = detalhes.loc[detalhes["motivo_alerta"].eq(motivo)].copy()
                modal_carretas_alerta_sete_dias(motivo, relacao)
    st.caption(f"CNP e SOS • Unidade ARA • {periodo} (Brasília). Inclui liberadas e em manutenção. "
               "Carretas distintas por motivo; uma frota pode aparecer em mais de um grupo. "
               "Agrupamento pelas descrições registradas; conferir as OS para definir a ação.")


st.markdown(f"<div class='mon-title'>{"📊 10 SUL • CONSULTA MOBILE" if MOBILE_READ_ONLY else "📺 MONITOR DA OFICINA"}</div>",unsafe_allow_html=True)
st.markdown("<div class='mon-sub'>Desenvolvido por Evandro Junior</div>", unsafe_allow_html=True)

if not MOBILE_READ_ONLY:
    render_alertas_paradas_sete_dias(df, agora)

if not MOBILE_READ_ONLY:
    st.link_button(
        "📊 Três Lagoas — Power BI",
        "https://app.powerbi.com/groups/me/apps/beec19e1-2ee7-4136-8f98-7b1536aef32c/"
        "reports/79b57ecb-df91-4336-8423-91d2ac213448/dbb8f200b34048170dd3"
        "?ctid=a7109315-9727-4adf-97ad-4849bb63edcb&experience=power-bi",
        help="Abre o relatório de Três Lagoas em outra aba, com acesso pela conta Microsoft.",
    )
st.markdown(f"<div class='mon-sub'>Monitor Gerencial Web • Atualizado em {agora.strftime('%d/%m/%Y %H:%M')}</div>",unsafe_allow_html=True)

if MOBILE_READ_ONLY:
    st.caption("Somente consulta • Unidade ARA")
    sync = pd.to_datetime(df.attrs.get("sincronizado_em"), errors="coerce", utc=True)
    if pd.isna(sync):
        sync = pd.to_datetime(df.get("sincronizado_em", pd.Series(dtype=str)), errors="coerce", utc=True).max()
    st.caption("Última sincronização da base: " + (sync.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M") if pd.notna(sync) else "não informada pela origem"))
    st.markdown("""<style>
    @media(max-width:768px){
      div[class*="st-key-card_oficina_"],.st-key-card_sos{height:100%}
      div[data-testid="stHorizontalBlock"]:has(.st-key-card_sos)>div{min-width:calc(50% - .5rem)!important;width:calc(50% - .5rem)!important;flex:1 1 calc(50% - .5rem)!important}
      button{touch-action:manipulation}
    }
    @media(prefers-reduced-motion:reduce){.st-key-card_sos button{animation:none!important}}
    </style>""", unsafe_allow_html=True)

if st.session_state.get("liberacao_10sul_desfeita"):
    frota_desfeita = st.session_state.pop("liberacao_10sul_desfeita")
    st.success(f"Pedido de baixa 10 Sul da frota {frota_desfeita} desfeito. A contagem do tempo foi retomada.")

st.markdown("#### 🔎 Consulta rápida de frota")

@st.dialog("🔎 Histórico da frota", width="large")
def modal_historico_frota(fq):
    hist=pd.concat([df[df["frota"].eq(fq)], os_excluidas[os_excluidas["frota"].eq(fq)]], ignore_index=True).sort_values("inicio",ascending=False)
    hist["excluida_asn"] = hist.get("excluida_asn_em", pd.Series(None, index=hist.index, dtype=object)).notna()
    st.markdown(f"### Frota {fq}")
    conferir = inconsistencias_asn.loc[inconsistencias_asn["FROTA"].eq(fq)]
    if not conferir.empty:
        st.warning("Há registros desta frota que precisam de conferência na ASN. OS pendente não confirma atendimento ainda em andamento.")
        st.dataframe(conferir, hide_index=True, use_container_width=True)
    if hist.empty:
        st.warning("Frota não encontrada na base sincronizada.")
        return

    hev=hist["evento"].fillna("").astype(str).str.upper().str.strip()
    # No monitor original, a preventiva é referenciada pela liberação.
    itr=hist[hev.eq("ITR") & ~hist["excluida_asn"]].copy()
    rev=hist[hev.str.contains("REVIS",na=False) & ~hist["excluida_asn"]].copy()

    def ultima_preventiva(x):
        if x.empty:
            return None
        x=x.copy()
        x["_lib"]=pd.to_datetime(x["fim"],errors="coerce")
        x["_entrada"]=pd.to_datetime(x["inicio"],errors="coerce").fillna(
            pd.to_datetime(x["parada"],errors="coerce"))
        # A última entrada identifica o atendimento mais recente, inclusive aberto.
        # O fim só é usado como referência quando a entrada não foi informada.
        x["_ref"]=x["_entrada"].fillna(x["_lib"])
        x=x.sort_values(["_ref","_lib"],ascending=False,na_position="last")
        return x.iloc[0]

    r_itr=ultima_preventiva(itr)
    r_rev=ultima_preventiva(rev)

    c1,c2=st.columns(2)
    def preventiva_card(col, titulo, row, cor, intervalo):
        with col:
            with st.container(border=True):
                st.markdown(f"<div style='font-size:13px;font-weight:800;color:#667085'>{cor} {titulo}</div>",unsafe_allow_html=True)
                if row is None:
                    st.markdown("<div style='font-size:24px;font-weight:900'>Não encontrada</div>",unsafe_allow_html=True)
                    st.caption("Nenhum atendimento desse evento no histórico ARA sincronizado.")
                    return
                st.caption(f"OS/ID: {row['os_id']}")
                lib=row["_lib"]
                entrada=row["_entrada"]
                if pd.isna(lib):
                    data=entrada.strftime("%d/%m/%Y") if pd.notna(entrada) else "Data não informada"
                    st.markdown(f"<div style='font-size:27px;font-weight:900'>{data}</div>",unsafe_allow_html=True)
                    st.caption("Último atendimento • liberação da OS ainda não confirmada.")
                    if pd.notna(entrada):
                        st.caption(f"Início: {entrada.strftime('%d/%m/%Y %H:%M')}")
                    st.caption(f"Status: {row.get('status','Não informado')}")
                    return
                dias=max(0,(agora.normalize()-lib.normalize()).days)
                prox=lib.normalize()+pd.Timedelta(days=intervalo)
                st.markdown(f"<div style='font-size:27px;font-weight:900'>{lib.strftime('%d/%m/%Y')}</div>",unsafe_allow_html=True)
                st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **{prox.strftime('%d/%m/%Y')}**")
                st.caption(f"Liberação da OS: {lib.strftime('%d/%m/%Y %H:%M')}")

    preventiva_card(c1,"ÚLTIMA ITR",r_itr,"🔵",20)
    preventiva_card(c2,"ÚLTIMA REVISÃO",r_rev,"🟣",120)

    st.markdown("#### Histórico de atendimentos")
    show=hist[["os_id","evento","descricao","parada","inicio","fim","status"]].copy()
    show.columns=["OS/ID","EVENTO","DESCRIÇÃO","PARADA","INÍCIO","FIM","STATUS"]
    show.loc[hist["excluida_asn"], "STATUS"] = "Excluída na Lista ASN"
    estilos = show.style.apply(lambda row: ["text-decoration:line-through;color:#6b7280" if hist.loc[row.name, "excluida_asn"] else "" for _ in row], axis=1)
    st.dataframe(estilos,use_container_width=True,hide_index=True)

@st.fragment
def render_consulta_rapida():
    q1,q2=st.columns([5,1])
    with q1:
        frota_q=st.text_input("Frota",placeholder="Ex.: 13725",label_visibility="collapsed")
    with q2:
        pesquisar=st.button("🔎 Pesquisar",use_container_width=True)
    if pesquisar and frota_q.strip():
        modal_historico_frota(norm_frota(frota_q))

render_consulta_rapida()

st.markdown("<div class='mon-section'><div class='mon-section-title'>OFICINA AGORA</div><div class='mon-section-sub'>Situação em tempo real e pontos que exigem atenção</div></div>",unsafe_allow_html=True)

def _frotas_em_varios_tipos(base, grupos):
    """Compara só cards de evento; totais e SLA não são outros tipos."""
    tipos = {}
    for nome, mascara in grupos:
        for valor in base.loc[mascara, "frota"].dropna():
            frota = norm_frota(valor)
            if frota:
                tipos.setdefault(frota, set()).add(nome)
    return {frota: " · ".join(sorted(nomes)) for frota, nomes in tipos.items() if len(nomes) > 1}


frotas_varios_tipos = _frotas_em_varios_tipos(mon, [
    ("CNP", mcnp), ("SOS", msos), ("ITR", mitr), ("REVISÃO", mrev),
])


def _estilo_relacao_os(linha):
    finalizada = "FINALIZADA 10 SUL" in str(linha["SITUAÇÃO"])
    varios = str(linha.get("CARDS COM OS ABERTA", "—")) != "—"
    return [
        "background-color:#fff3cd;color:#854d0e;font-weight:700" if varios and c in {"FROTA", "CARDS COM OS ABERTA"}
        else "background-color:#e7f5ed;color:#145c3b" if finalizada else ""
        for c in linha.index
    ]


def tabela_relacao_os(dados, incluir_local=False):
    if dados is None or dados.empty:
        colunas=["OS/ID","FROTA","EVENTO","DESCRIÇÃO DO EVENTO","PARADA","INÍCIO","TEMPO ABERTO","PREVISÃO","LIBERAÇÃO 10 SUL","SITUAÇÃO"]
        if incluir_local:
            colunas.insert(3, "LOCAL DA MANUTENÇÃO")
        return pd.DataFrame(columns=colunas)
    x=dados.copy()
    x["TEMPO ABERTO"]=x["horas_aberto"].apply(hhmm)
    x["PARADA"]=pd.to_datetime(x["parada"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("Não informada")
    x["INÍCIO"]=pd.to_datetime(x["inicio_mon"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    x["SITUAÇÃO"]=x["acima_sla"].map({True:"🔴 SLA ULTRAPASSADO",False:"EM ATENDIMENTO"})
    x.loc[x["finalizada_10sul"], "SITUAÇÃO"]="🟢 FINALIZADA 10 SUL · AGUARDANDO BAIXA CLIENTE"
    x["LIBERAÇÃO 10 SUL"]=x["fim_liberacao_10sul"].dt.strftime("%d/%m/%Y %H:%M").fillna("—")
    x["PREVISÃO"]=pd.to_datetime(x.get("previsao_liberacao_10sul", pd.Series(pd.NaT, index=x.index)),errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("—")
    x=x.rename(columns={"os_id":"OS/ID","frota":"FROTA","evento":"EVENTO","descricao":"DESCRIÇÃO DO EVENTO"})
    cols_show=["OS/ID","FROTA","EVENTO","DESCRIÇÃO DO EVENTO","PARADA","INÍCIO","TEMPO ABERTO","PREVISÃO","LIBERAÇÃO 10 SUL","SITUAÇÃO"]
    if incluir_local:
        local=x.get("local_manutencao", pd.Series(None, index=x.index, dtype=object))
        x["LOCAL DA MANUTENÇÃO"]=local.fillna("").astype(str).str.strip().replace("", "Não informado")
        cols_show.insert(3, "LOCAL DA MANUTENÇÃO")

    x["CARDS COM OS ABERTA"] = x["FROTA"].apply(norm_frota).map(frotas_varios_tipos).fillna("—")
    cols_show.insert(2, "CARDS COM OS ABERTA")
    return x[cols_show]


def html_impressao_relacao(titulo, tabela, emitido_em):
    from html import escape
    total_frotas = tabela["FROTA"].nunique() if "FROTA" in tabela else 0
    cabecalho = "".join("<th>" + escape(str(c)) + "</th>" for c in tabela.columns)
    linhas = []
    for _, linha in tabela.fillna("—").iterrows():
        classe = "finalizada" if "FINALIZADA 10 SUL" in str(linha.get("SITUAÇÃO", "")) else ""
        celulas = "".join("<td>" + escape(str(v)) + "</td>" for v in linha)
        linhas.append('<tr class="' + classe + '">' + celulas + "</tr>")
    bloqueado = " disabled" if tabela.empty else ""
    return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Relação de frotas</title><style>
body{margin:0;font-family:Arial,sans-serif;color:#243746}button{box-sizing:border-box;width:100%;padding:10px 8px;border:1px solid #ccd6de;border-radius:8px;background:#fff;color:#15364b;font-size:13px;font-weight:600;cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible{outline:3px solid #208991;outline-offset:2px}.relatorio{display:none}h1{font-size:20pt;margin:0 0 8px}h2{font-size:15pt;margin:8px 0}p{font-size:10pt;margin:8px 0}table{width:100%;border-collapse:collapse;table-layout:auto;font-size:11pt}th,td{padding:6px 4px;border:1px solid #ccd6de;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf0f4;text-align:left;color:#15364b}tr:nth-child(even){background:#f5f7f9}tr.finalizada{background:#e7f5ed;color:#145c3b}thead{display:table-header-group}tr{break-inside:avoid}
.pagina-impressao .relatorio{display:block}.pagina-impressao{padding:16px}.orientacao{font:14px Arial,sans-serif;color:#52616b;margin:12px 0}
@media print{button,.orientacao{display:none!important}.pagina-impressao{padding:0}.relatorio{display:block;width:100%}th,tr{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@page{size:A4 landscape;margin:8mm}
</style></head><body><button id="imprimir" """ + bloqueado + """>🖨️ Imprimir relação</button><section class="relatorio">
<h1>10 SUL · OFICINA ARACRUZ</h1><h2>""" + escape(str(titulo)) + """</h2>
<p>Unidade: ARA | Emitido em """ + escape(str(emitido_em)) + """ (Brasília)</p>
<p>""" + str(len(tabela)) + """ atendimento(s) · """ + str(total_frotas) + """ frota(s)</p>
<table><thead><tr>""" + cabecalho + """</tr></thead><tbody>""" + "".join(linhas) + """</tbody></table>
<p>Verde: finalizada pela 10 Sul, aguardando baixa do cliente. Relação conforme o card consultado.</p>
<p>Desenvolvido por Evandro Junior</p></section><p id="aviso-impressao" role="status" style="font:13px Arial,sans-serif"></p><script>
document.getElementById('imprimir').onclick=()=>{
    const pagina=window.open('', '_blank', 'width=1200,height=850');
    if(!pagina){document.getElementById('aviso-impressao').textContent='Permita abrir uma nova janela para imprimir a relação em A4 deitado.';return;}
    document.getElementById('aviso-impressao').textContent='';
    pagina.document.open();
    pagina.document.write('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>10 Sul · Relação de frotas</title><style>'+document.querySelector('style').textContent+'</style></head><body class="pagina-impressao"><button id="imprimir-pagina">🖨️ Imprimir / Salvar PDF</button><p class="orientacao">A4 · Paisagem (deitado) · Escala 100%. Se o navegador mantiver a orientação anterior, selecione Paisagem na impressão.</p>'+document.querySelector('.relatorio').outerHTML+'</body></html>');
    pagina.document.close();
    const imprimir=()=>{pagina.focus();pagina.print();};
    pagina.document.getElementById('imprimir-pagina').onclick=imprimir;
    pagina.document.fonts.ready.then(()=>pagina.requestAnimationFrame(()=>pagina.requestAnimationFrame(imprimir)));
};
</script></body></html>"""


def imprimir_relacao_card(titulo, dados):
    tabela = tabela_relacao_os(dados, incluir_local="SOS" in str(titulo).upper())
    emitido = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    components.html(html_impressao_relacao(titulo, tabela, emitido), height=48, scrolling=False)


@st.dialog("Relação de carretas", width="large")
def modal_os_abertas(titulo, dados, card_id):
    chave_modal = f"lib_10sul_card_{card_id}"
    st.markdown(f"### {titulo}")
    if dados is None or dados.empty:
        st.info("Nenhuma OS aberta neste card.")
        return
    x=tabela_relacao_os(dados, incluir_local=card_id == 2)
    destaque = x.style.apply(_estilo_relacao_os, axis=1)
    st.dataframe(destaque,use_container_width=True,hide_index=True,key=f"{chave_modal}_tabela")
    imprimir_relacao_card(titulo, dados)
    st.caption("Verde: concluída pela 10 Sul, aguardando baixa ASN. O tempo considera a conclusão informada.")
    st.caption("🟡 Frota em mais de um tipo: a coluna CARDS COM OS ABERTA mostra todos os tipos envolvidos.")
    if not MOBILE_READ_ONLY:
        st.markdown("#### Previsão e liberação 10 Sul")
        opcoes = list(range(len(dados)))
        pos = st.selectbox("Frota / atendimento", opcoes,
            format_func=lambda i: f"{dados.iloc[i]['frota']} · {dados.iloc[i]['evento']} · OS {dados.iloc[i]['os_id']}",
            key=f"{chave_modal}_atendimento")
        registro = dados.iloc[pos].copy()
        base_registro_atual = carregar()
        atual_selecionado = base_registro_atual.loc[
            base_registro_atual["os_id"].astype(str).eq(str(registro["os_id"])) &
            base_registro_atual["frota"].apply(norm_frota).eq(norm_frota(registro["frota"]))
        ]
        if len(atual_selecionado) == 1:
            registro["fim_liberacao_10sul"] = atual_selecionado.iloc[0].get("fim_liberacao_10sul")
        existente = _hora_brasilia(registro.get("fim_liberacao_10sul"))
        inicial = existente if pd.notna(existente) else agora.floor("min")
        chave_registro = f"{chave_modal}_{registro['os_id']}_{registro['frota']}"
        with st.expander("📅 Informar previsão de liberação", expanded=False):
            if pd.notna(existente):
                st.info("A frota já foi liberada pela 10 Sul e aguarda a baixa do cliente.")
            else:
                atual_prev = carregar()
                atual_prev = atual_prev.loc[
                    atual_prev["os_id"].astype(str).eq(str(registro["os_id"])) &
                    atual_prev["frota"].apply(norm_frota).eq(norm_frota(registro["frota"]))
                ]
                registro_prev = atual_prev.iloc[0] if not atual_prev.empty else registro
                previsao_atual = _hora_brasilia(registro_prev.get("previsao_liberacao_10sul"))
                nota_atual = registro_prev.get("observacao_previsao_10sul")
                nota_atual = "" if pd.isna(nota_atual) else str(nota_atual)
                if pd.notna(previsao_atual):
                    st.caption(f"Previsão registrada: {previsao_atual.strftime('%d/%m/%Y %H:%M')}")
                situacao_prev = st.radio(
                    "Situação da previsão", ["Com data/hora", "Ainda sem previsão"],
                    index=0 if pd.notna(previsao_atual) else 1,
                    key=f"{chave_registro}_previsao_situacao",
                )
                quando_prev, observacao_prev = None, ""
                if situacao_prev == "Com data/hora":
                    inicial_prev = previsao_atual if pd.notna(previsao_atual) and previsao_atual >= agora.floor("min") else agora.ceil("min") + pd.Timedelta(hours=1)
                    p_data, p_hora = st.columns(2)
                    data_prev = p_data.date_input("Data prevista", value=inicial_prev.date(), min_value=agora.date(), key=f"{chave_registro}_previsao_data")
                    hora_prev = p_hora.time_input("Hora prevista", value=inicial_prev.time(), step=60, key=f"{chave_registro}_previsao_hora")
                    quando_prev = datetime.combine(data_prev, hora_prev)
                else:
                    observacao_prev = st.text_area(
                        "Por que ainda não há previsão? (opcional)",
                        value=nota_atual, max_chars=300,
                        placeholder="Ex.: aguardando peça ou avaliação técnica.",
                        key=f"{chave_registro}_previsao_observacao",
                    )
                if st.button("Salvar previsão / observação", key=f"{chave_registro}_previsao_salvar", type="primary"):
                    try:
                        _salvar_previsao_10sul(registro, quando_prev, observacao_prev)
                        st.session_state[f"{chave_modal}_previsao_salva"] = str(registro["frota"])
                        st.rerun(scope="fragment")
                    except Exception as exc:
                        st.error(str(exc))
                st.caption("Salve e envie o resumo completo. Sem previsão, será enviada apenas a observação.")

            base_previsoes = carregar()
            previsoes_card = _previsoes_do_card(dados, base_previsoes)
            total_prev = len(previsoes_card)
            informadas_prev = int(previsoes_card["previsao"].notna().sum())
            frota_salva_prev = st.session_state.pop(f"{chave_modal}_previsao_salva", None)
            if frota_salva_prev:
                st.success(f"Previsão da frota {frota_salva_prev} salva.")
            st.markdown(f"**Previsões registradas: {informadas_prev} de {total_prev}**")
            if informadas_prev < total_prev:
                faltam_prev = previsoes_card.loc[previsoes_card["previsao"].isna(), "frota"].astype(str).tolist()
                st.caption("Ainda sem previsão: " + ", ".join(faltam_prev))
            if total_prev:
                import importlib
                import previsao_share
                import monitor_share
                importlib.reload(previsao_share)
                imagem_previsoes = previsao_share.gerar_imagem_previsoes(
                    previsoes_card,
                    pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None),
                    _evento_resumido_whatsapp,
                )
                st.image(imagem_previsoes, use_container_width=True)
                monitor_share.botao_compartilhar_imagem(imagem_previsoes)
                st.download_button(
                    "Baixar imagem PNG", imagem_previsoes,
                    file_name="previsoes_frotas_10sul.png", mime="image/png",
                    key=f"{chave_modal}_baixar_previsoes_png",
                )
            else:
                st.caption("Não há frotas pendentes de liberação da 10 Sul neste card.")
            st.caption("O resumo inclui todas as frotas do card. Sem data/hora, mostra a observação; sem observação, mostra —.")

        if pd.notna(existente):
            st.caption(f"Liberação 10 Sul: {existente.strftime('%d/%m/%Y %H:%M')}")
            if st.button("Desfazer pedido de baixa 10 Sul", key=f"{chave_registro}_desfazer"):
                try:
                    frota_desfeita = _desfazer_liberacao_10sul(registro)
                    st.session_state.pop(f"{chave_registro}_resultado_whatsapp", None)
                    st.session_state["liberacao_10sul_desfeita"] = frota_desfeita
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        st.markdown("##### Registrar baixa 10 Sul")
        c_data, c_hora = st.columns(2)
        data_lib = c_data.date_input("Data", value=inicial.date(), max_value=agora.date(), key=f"{chave_registro}_data")
        hora_lib = c_hora.time_input("Hora", value=inicial.time(), step=60, key=f"{chave_registro}_hora")
        # O componente mantém a janela reservada no clique e recebe a confirmação do servidor.
        chave_resultado = f"{chave_registro}_resultado_whatsapp"
        resultado = st.session_state.get(chave_resultado)
        pedido = _registrar_baixa_whatsapp(
            result=resultado,
            key=f"{chave_registro}_registrar_whatsapp",
            default=None,
        )
        st.caption("A OS permanece aberta até a baixa do cliente. Ao registrar, escolha o grupo no WhatsApp.")
        nonce = pedido.get("nonce") if isinstance(pedido, dict) else None
        processados = st.session_state.setdefault("lib_10sul_pedidos_processados", set())
        if isinstance(nonce, str) and nonce and nonce not in processados:
            processados.add(nonce)
            try:
                aviso = _salvar_liberacao_10sul(registro, datetime.combine(data_lib, hora_lib))
                st.session_state[chave_resultado] = {
                    "nonce": nonce,
                    "url": "https://wa.me/?text=" + quote(aviso),
                }
            except Exception as exc:
                st.session_state[chave_resultado] = {"nonce": nonce, "error": str(exc)}
            # A janela de registro permanece aberta; não retorna para o dashboard.
            st.rerun(scope="fragment")
        if resultado and resultado.get("error"):
            st.error(resultado["error"])
        elif resultado and resultado.get("url"):
            st.success("Baixa registrada pela 10 Sul. A OS aguarda a baixa do cliente.")
        elif pd.notna(existente):
            texto_aviso = _mensagem_liberacao(registro["frota"], registro["evento"], existente)
            st.link_button("Avisar cliente no WhatsApp", "https://wa.me/?text=" + quote(texto_aviso))

cards=[
    (len(mon),"🔧 EM MANUTENÇÃO","",mon),
    (int(mcnp.sum()),"🚨 CNP ABERTAS","red",mon[mcnp]),
    (int(msos.sum()),"🆘 SOS ABERTOS","red",mon[msos]),
    (int(mitr.sum()),"🔧 ITR ABERTAS","",mon[mitr]),
    (int(mrev.sum()),"🛠️ REVISÕES","",mon[mrev]),
    (0,"📦 AG. PEÇA","orange",mon.iloc[0:0]),
    (int(mon["acima_sla"].sum()),"⏱️ ACIMA SLA","red",mon[mon["acima_sla"]]),
]
# Alerta SOS: somente atendimentos ainda abertos, estritamente acima de 3 horas.
sos_acima_3h = (
    mon.loc[msos & ~mon["finalizada_10sul"] & mon["horas_aberto"].gt(3), ["frota", "horas_aberto"]]
    .groupby("frota", as_index=False)["horas_aberto"].max()
    .sort_values(["horas_aberto", "frota"], ascending=[False, True])
)
sos_em_alerta = not sos_acima_3h.empty
import html as _html_sos
sos_detalhes_card = (
    "<div class='sos-mini-table' role='table' aria-label='SOS acima de 3 horas'>"
    "<div class='sos-mini-row sos-mini-head' role='row'>"
    "<span role='columnheader'>FROTA</span><span role='columnheader'>TEMPO</span></div>"
    + "".join(
        "<div class='sos-mini-row' role='row'>"
        f"<span role='cell'>{_html_sos.escape(str(r['frota']))}</span>"
        f"<strong role='cell'>{hhmm(r['horas_aberto'])}</strong></div>"
        for _, r in sos_acima_3h.head(3).iterrows()
    ) + "</div>"
) if sos_em_alerta else ""
if len(sos_acima_3h) > 3:
    sos_detalhes_card += f"<div class='sos-mini-more'>+ {len(sos_acima_3h) - 3} frotas</div>"
if sos_em_alerta:
    st.markdown("""
    <style>
    @keyframes sos_card_piscar {
        0%, 100% {background-color:#dc2626; border-color:#dc2626;}
        50% {background-color:#991b1b; border-color:#991b1b;}
    }
    .st-key-card_sos {
        background-color:#dc2626;
        border:1px solid #dc2626;
        border-radius:11px;
        padding:4px 8px 10px;
        gap:0!important;
        animation:sos_card_piscar 1.4s ease-in-out infinite;
    }
    .st-key-card_sos div[data-testid="stButton"] > button {
        background:transparent!important;
        border:0!important;
        box-shadow:none!important;
        color:#ffffff!important;
        min-height:76px!important;
        padding:6px!important;
    }
    .sos-mini-table {
        width:min(100%,220px);
        margin:0 auto;
        color:#ffffff;
        font-size:12px;
        line-height:1.5;
        text-align:center;
    }
    .sos-mini-row {
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:8px;
        padding:2px 0;
        border-bottom:1px solid rgba(255,255,255,.22);
    }
    .sos-mini-head {font-size:10px;font-weight:600;letter-spacing:.4px;}
    .sos-mini-more {color:#ffffff;font-size:11px;text-align:center;margin-top:4px;}

    .st-key-card_sos div[data-testid="stButton"] > button * {
        color:#ffffff!important;
    }
    </style>
    """, unsafe_allow_html=True)
@st.fragment
def render_cards_oficina():
    cols=st.columns(7,gap="small")
    for i,(col,(n,lab,kind,dados_card)) in enumerate(zip(cols,cards)):
        with col:
            # O alerta colore o card inteiro, incluindo a tabela compacta de frotas.
            with st.container(key="card_sos" if i == 2 else f"card_oficina_{i}"):
                if st.button(f"{n}\n\n{lab}",key=f"kpi_abertas_{i}",use_container_width=True):
                    modal_os_abertas(lab,dados_card,i)
                finalizadas_card = int(dados_card["finalizada_10sul"].sum())
                if finalizadas_card:
                    st.markdown(
                        "<div style='background:#e7f5ed;color:#145c3b;border-radius:8px;"
                        "padding:5px 8px;font-size:11px;text-align:center'>"
                        f"🟢 {finalizadas_card} finalizada(s) 10 Sul · aguardando cliente</div>",
                        unsafe_allow_html=True,
                    )
                repetidas_card = sorted({norm_frota(f) for f in dados_card["frota"].dropna()} & frotas_varios_tipos.keys())
                if repetidas_card:
                    avisos = "<br>".join(
                        f"<b>Frota {_html_sos.escape(f)}</b><br>{_html_sos.escape(frotas_varios_tipos[f])}"
                        for f in repetidas_card
                    )
                    st.markdown(
                        "<div style='background:#fff3cd;color:#854d0e;border:1px solid #eab308;"
                        "border-radius:8px;padding:7px;font-size:11px;text-align:center'>"
                        "<b>⚠️ EM MAIS DE UM TIPO</b><br>" + avisos + "</div>",
                        unsafe_allow_html=True,
                    )
                if i == 2 and sos_detalhes_card:
                    st.markdown(sos_detalhes_card, unsafe_allow_html=True)

render_cards_oficina()

# Médias ITR e Revisão imediatamente abaixo dos cards Oficina Agora.
render_medias_supervisor()

# MAIORES TEMPOS
st.markdown("### 🚨 Maiores tempos em manutenção por evento")
def topcard(mask,titulo):
    d=mon[mask].sort_values("horas_aberto",ascending=False).head(3)
    rows=""
    for pos,(_,r) in enumerate(d.iterrows(),1):
        rows+=f"<div class='top-row'><span>{pos}º&nbsp;&nbsp;FROTA {r['frota']}</span><strong>{hhmm(r['horas_aberto'])}</strong></div>"
    if not rows: rows="<div class='top-row'><span>Nenhuma ocorrência aberta</span></div>"
    st.markdown(f"<div class='top-card'><div class='top-title'>🚨 {titulo} — MAIORES TEMPOS</div>{rows}</div>",unsafe_allow_html=True)
for col,(mask,t) in zip(st.columns(4),[(mcnp,"CORRETIVA Ñ PROG."),(mitr,"ITR"),(mrev,"REVISÃO"),(msos,"SOS")]):
    with col: topcard(mask,t)

# ALERTAS & HUNT
hunt=df[is_cnp_all].copy()
hunt["ref"]=hunt["inicio"].fillna(hunt["parada"])
hunt=hunt[hunt["ref"].notna()].copy()
hunt["desc_norm"]=hunt["descricao"].fillna("").astype(str).str.upper()
hoje=agora.normalize()
mes_ini=hoje.replace(day=1)
mes_ant_fim=mes_ini
mes_ant_ini=(mes_ini-pd.offsets.MonthBegin(1)).normalize()
sem_ini=hoje-pd.Timedelta(days=hoje.weekday())
sem_ant_ini=sem_ini-pd.Timedelta(days=7)
sem_ant_fim=sem_ini
q_mes=int(((hunt["ref"]>=mes_ini)&(hunt["ref"]<=agora)).sum())
q_mes_ant=int(((hunt["ref"]>=mes_ant_ini)&(hunt["ref"]<mes_ant_fim)).sum())
q_sem=int(((hunt["ref"]>=sem_ini)&(hunt["ref"]<=agora)).sum())
q_sem_ant=int(((hunt["ref"]>=sem_ant_ini)&(hunt["ref"]<sem_ant_fim)).sum())
def delta(a,b): return None if b==0 else (a-b)/b*100
dm,ds=delta(q_mes,q_mes_ant),delta(q_sem,q_sem_ant)
def dhtml(v):
    if v is None:return "<span class='flat'>→ sem base</span>"
    if v>0:return f"<span class='up'>↑ {abs(v):.1f}%</span>".replace(".",",")
    if v<0:return f"<span class='down'>↓ {abs(v):.1f}%</span>".replace(".",",")
    return "<span class='flat'>→ 0,0%</span>"

familias={
"Elétrica / Iluminação":["ELÉTR","ELETR","LUZ","LANTER","CORUJ","ILUM"],
"Bolsa / Suspensão":["BOLSA","SUSPENS"],
"Pneumático / Ar":["PNEUM","VAZAMENTO DE AR","MANGUEIRA","CONEXÃO","CONEXAO","AR "],
"Freio / Regulagem":["FREIO","REGUL","CATRACA","CUÍCA","CUICA","LONA"],
"Estrutura / Solda":["SOLDA","TRINCA","ESTRUT","CHASSI","SUPORTE"],
"Pneu / Borracharia":["PNEU","BORRACH"],
}
atual=hunt[(hunt["ref"]>=sem_ini)&(hunt["ref"]<=agora)].copy()
anterior=hunt[(hunt["ref"]>=sem_ant_ini)&(hunt["ref"]<sem_ant_fim)].copy()
def _descricao_contem_termo(valor, termos):
    # Evita pd.NA/NaN gerar "boolean value of NA is ambiguous" no Streamlit Cloud.
    if valor is None or pd.isna(valor):
        texto = ""
    else:
        texto = str(valor).upper()
    return any(str(t).upper() in texto for t in termos if t is not None)

mot=[]
for cat,termos in familias.items():
    qa=int(atual["desc_norm"].apply(lambda z: _descricao_contem_termo(z, termos)).sum())
    qb=int(anterior["desc_norm"].apply(lambda z: _descricao_contem_termo(z, termos)).sum())
    mot.append((cat,qa,qa-qb))
mot=sorted(mot,key=lambda x:(x[1],x[2]),reverse=True)

st.markdown("<div class='mon-section'><div class='mon-section-title'>4. ALERTAS & HUNT</div><div class='mon-section-sub'>Corretivas não programadas e inteligência da operação</div></div>",unsafe_allow_html=True)
acoes_compartilhar_cnp = st.empty()
h1,h2,h3=st.columns([1,1.08,1])
with h1:
    with st.container(border=True):
        st.markdown("<div class='hunt-title'>📊 Tendência das CNP</div>",unsafe_allow_html=True)
        a,b=st.columns(2)
        with a: st.markdown(f"<div class='hunt-kpi'>{q_mes}</div><b>CNP no mês</b><div class='hunt-compare'>vs. {q_mes_ant} no mês anterior</div>{dhtml(dm)}",unsafe_allow_html=True)
        with b: st.markdown(f"<div class='hunt-kpi'>{q_sem}</div><b>CNP na semana</b><div class='hunt-compare'>vs. {q_sem_ant} na semana anterior</div>{dhtml(ds)}",unsafe_allow_html=True)
        st.markdown("<div style='margin-top:14px;font-size:12px;font-weight:700'>CNP por semana • últimas 8 semanas</div>",unsafe_allow_html=True)
        if not hunt.empty:
            tw=hunt.copy(); tw["SEMANA"]=tw["ref"].dt.to_period("W-MON").apply(lambda x:x.start_time)
            wk=tw.groupby("SEMANA").size().sort_index().tail(8).reset_index(name="QTD")
            wk["LAB"]=wk["SEMANA"].apply(lambda d:f"S{d.isocalendar().week:02d}")
            st.line_chart(wk.set_index("LAB")["QTD"],height=150,use_container_width=True)
with h2:
    with st.container(border=True):
        st.markdown("<div class='hunt-title'>📋 Principais motivos das CNP — semana ⓘ</div>",unsafe_allow_html=True)
        if "motivo_cnp_aberto" not in st.session_state:
            st.session_state["motivo_cnp_aberto"] = None

        for cat,qa,dif in mot[:4]:
            seta="↑" if dif>0 else "↓" if dif<0 else "→"
            aberto = st.session_state["motivo_cnp_aberto"] == cat
            indicador = "⌃" if aberto else "›"

            if st.button(
                f"{cat}     {qa}     {seta} {abs(dif)}  {indicador}",
                key=f"m_{cat}",
                use_container_width=True
            ):
                # Mesmo motivo: recolhe. Outro motivo: fecha o anterior e abre este.
                st.session_state["motivo_cnp_aberto"] = None if aberto else cat
                st.rerun()

            if st.session_state["motivo_cnp_aberto"] == cat:
                termos=familias[cat]
                rel=atual[
                    atual["desc_norm"].apply(lambda z: _descricao_contem_termo(z, termos))
                ][["frota","os_id","evento","descricao","ref","status"]].copy()
                st.dataframe(rel,use_container_width=True,hide_index=True)

        st.info("Clique em um motivo para abrir ou recolher as OS relacionadas, com frotas, datas, tempos e descrições.")
with h3:
    with st.container(border=True):
        crescem=[x for x in mot if x[2]>0 and x[1]>0]
        if crescem:
            txt=", ".join(f"{x[0]} (+{x[2]})" for x in crescem[:3])
            leitura=f"O crescimento da semana está concentrado principalmente em {txt}. A leitura usa termos encontrados nas descrições das CNP e indica concentração de ocorrências, não causa definitiva."
        elif ds is not None and ds<0:
            top=next((x[0] for x in mot if x[1]>0),"nenhuma família específica")
            leitura=f"As CNP reduziram {abs(ds):.1f}% na comparação semanal. No período atual, {top} aparece entre os grupos mais frequentes.".replace(".",",")
        else:
            leitura="Não há crescimento relevante identificado na comparação semanal ou ainda não existe base anterior suficiente para concluir tendência."
        st.markdown(f"<div class='hunt-title'>🧠 Leitura do período</div><div style='font-size:13px;line-height:1.5'>{leitura}</div>",unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<div class='hunt-title'>👥 Frotas reincidentes <span style='font-size:11px;font-weight:500;color:#667085'>(últimos 30 dias)</span></div>",unsafe_allow_html=True)
        r30=hunt[(hunt["ref"]>=hoje-pd.Timedelta(days=30))&(hunt["ref"]<=agora)]
        if not r30.empty:
            rr=r30.groupby("frota").agg(QTDE=("ref","size"),ULTIMA=("ref","max")).sort_values(["QTDE","ULTIMA"],ascending=[False,False]).head(3)
            st.markdown("<div class='reinc-head'><span>Frota</span><span>Qtde. CNP</span><span>Última ocorrência</span></div>",unsafe_allow_html=True)
            for fr,r in rr.iterrows():
                st.markdown(f"<div class='reinc-row'><b>{fr}</b><span>{int(r['QTDE'])}</span><span>{r['ULTIMA'].strftime('%d/%m/%Y')}</span></div>",unsafe_allow_html=True)
        else: st.caption("Sem dados suficientes para identificar reincidências.")



# SOS: evolução no mesmo formato da tendência de CNP.
import importlib as _importlib_sos
_relatorio_sos = _importlib_sos.reload(_importlib_sos.import_module("monitor_share"))
_tendencia_sos = _relatorio_sos.calcular_tendencia_sos(df, agora)
with st.container(border=True):
    st.markdown("<div class='hunt-title'>🆘 Tendência dos SOS</div>", unsafe_allow_html=True)
    _sos_mes, _sos_semana = st.columns(2)
    with _sos_mes:
        st.markdown(f"<div class='hunt-kpi'>{_tendencia_sos['q_mes']}</div><b>SOS no mês</b><div class='hunt-compare'>vs. {_tendencia_sos['q_mes_ant']} no mês anterior</div>{dhtml(_tendencia_sos['dm'])}", unsafe_allow_html=True)
    with _sos_semana:
        st.markdown(f"<div class='hunt-kpi'>{_tendencia_sos['q_sem']}</div><b>SOS na semana</b><div class='hunt-compare'>vs. {_tendencia_sos['q_sem_ant']} na semana anterior</div>{dhtml(_tendencia_sos['ds'])}", unsafe_allow_html=True)
    st.markdown("**SOS por semana • últimas 8 semanas com registros**")
    if not _tendencia_sos["semanas"].empty:
        st.line_chart(_tendencia_sos["semanas"].set_index("LAB")["QTD"], height=150, use_container_width=True)
    else:
        st.caption("Sem dados de SOS no período.")

@st.dialog("Resumo do Monitor Gerencial", width="large")
def abrir_resumo_compartilhavel():
    import importlib
    # O Streamlit reexecuta a página, mas mantém módulos importados na sessão.
    # Recarrega o relatório para usar também as funções novas após uma publicação.
    relatorio = importlib.reload(importlib.import_module("monitor_share"))
    png = relatorio.gerar_imagem_resumo(hunt, agora, q_mes, q_mes_ant, q_sem, q_sem_ant,
                                      dm, ds, mot, leitura,
                                      relatorio.calcular_medias_monitor(df, agora),
                                      relatorio.calcular_oficina_agora(df),
                                      relatorio.calcular_tendencia_sos(df, agora))
    st.image(png, use_container_width=True)
    relatorio.botao_compartilhar_imagem(png)
    st.download_button("Baixar imagem PNG", png, "resumo_monitor_10sul.png", mime="image/png",
                       key="download_resumo_cnp")

@st.fragment
def render_acao_compartilhar_resumo():
    with acoes_compartilhar_cnp.container():
        if st.button("📲 Compartilhar resumo no WhatsApp", use_container_width=True,
                     key="compartilhar_resumo_cnp"):
            abrir_resumo_compartilhavel()

render_acao_compartilhar_resumo()



@st.dialog("OS excluídas na Lista ASN", width="large")
def modal_os_excluidas():
    st.caption("Histórico preservado • exclusão confirmada na origem • sem notificações ou indicadores de manutenção.")
    if os_excluidas.empty:
        st.info("Nenhuma OS com exclusão confirmada na Lista ASN.")
        return
    show = os_excluidas.sort_values("excluida_asn_em", ascending=False)[["os_id","frota","evento","descricao","parada","inicio","excluida_asn_em"]].copy()
    show["excluida_asn_em"] = show["excluida_asn_em"].map(_hora_brasilia)
    show.columns = ["OS/ID","FROTA","EVENTO","DESCRIÇÃO","PARADA","INÍCIO","EXCLUSÃO CONFIRMADA EM"]
    tabela = show.style.format(escape="html", na_rep="—").set_properties(**{"text-decoration":"line-through","color":"#6b7280","padding":"8px","border-bottom":"1px solid #e5e7eb"}).hide(axis="index").to_html()
    st.markdown("<div style='overflow-x:auto;max-width:100%'>" + tabela + "</div>", unsafe_allow_html=True)

@st.dialog("⚠️ OS para conferir na ASN", width="large")
def modal_inconsistencias_asn():
    st.warning("Dados da origem que precisam de conferência. Uma OS sem baixa pode ser pendência de registro; a sobreposição não comprova dois atendimentos em andamento.")
    st.caption("Somente consulta • os registros e horários da Lista ASN permanecem intactos.")
    if inconsistencias_asn.empty:
        st.info("Nenhuma inconsistência identificada nos registros ASN disponíveis.")
    else:
        st.dataframe(inconsistencias_asn, hide_index=True, use_container_width=True)

ids_conferir = set(inconsistencias_asn["OS/ID"]) | {v for v in inconsistencias_asn["OS RELACIONADA"] if v}
@st.fragment
def render_card_inconsistencias_asn():
    with st.container(key="card_inconsistencias_asn"):
        if st.button(f"{len(ids_conferir)}\n\n⚠️ OS PARA CONFERIR NA ASN", key="kpi_inconsistencias_asn", use_container_width=True):
            modal_inconsistencias_asn()
        if ids_conferir:
            st.caption("OS sem baixa com outro atendimento • horários sobrepostos ou incoerentes. Abra para comparar as OS.")

render_card_inconsistencias_asn()

@st.dialog("Atividades das paradas após ITR", width="large")
def modal_atividades_retornos_itr(frota, paradas):
    st.markdown(f"### 🚛 Frota {frota}")
    paradas = paradas.loc[paradas["frota"].eq(frota)].sort_values("_parada_retorno").copy()
    if paradas.empty:
        st.info("Nenhuma parada contabilizada para esta frota.")
        return
    st.caption(f"Última ITR: {paradas['Última ITR'].iloc[0].strftime('%d/%m/%Y %H:%M')} • {paradas['os_id'].nunique()} parada(s) em até 5 dias")
    laudos = carregar_laudos_manuais_web().copy()
    if st.session_state.get("_erro_laudos_web"):
        st.warning("Não foi possível consultar os laudos agora. As descrições das OS continuam disponíveis abaixo.")
    for numero, (_, parada) in enumerate(paradas.iterrows(), 1):
        with st.container(border=True):
            data = parada["_parada_retorno"].strftime("%d/%m/%Y %H:%M")
            st.markdown(f"**{numero}ª parada • OS {parada['os_id']} • {parada['evento']}**")
            st.caption(f"Parada: {data} • Status: {parada.get('status', '')}")
            valor_descricao = parada.get("descricao", "")
            descricao = "" if pd.isna(valor_descricao) else str(valor_descricao).strip()
            st.markdown("**Descrição do serviço na OS**")
            st.write(descricao or "Descrição não informada.")
            if laudos.empty or not {"FROTA", "OS_ID"}.issubset(laudos.columns):
                atividades = pd.DataFrame()
            else:
                atividades = laudos.loc[
                    laudos["FROTA"].apply(norm_frota).eq(norm_frota(frota)) &
                    laudos["OS_ID"].map(_chave_vinculo_laudo).eq(_chave_vinculo_laudo(parada["os_id"]))
                ].copy()
            st.markdown("**Atividades realizadas — laudos vinculados**")
            if atividades.empty:
                st.caption("Nenhuma atividade de laudo vinculada a esta OS e frota.")
            else:
                nomes = {"ATIVIDADE":"Atividade", "COMPARTIMENTO":"Compartimento", "CLASSIFICACAO":"Tipo", "EXECUTANTE":"Executante", "INICIO_ATIVIDADE":"Início", "FIM_ATIVIDADE":"Fim", "HORAS":"Horas"}
                campos = [c for c in nomes if c in atividades.columns]
                st.dataframe(atividades[campos].rename(columns=nomes), hide_index=True, use_container_width=True)


# Retornos pós-ITR: mantém também as paradas já liberadas na contagem.
retornos_itr, detalhes_retornos_itr = _retornos_pos_itr(df, agora)
@st.fragment
def render_card_retornos_itr():
    with st.container(key="card_retornos_itr", border=True):
        with st.expander("🚨 Retornos após ITR — até 5 dias", expanded=False):
            st.caption("CORRETIVA + SOS • última ITR concluída • intervalo da liberação até a parada • uma contagem por OS")
            if retornos_itr.empty:
                st.caption("Nenhuma carreta com retorno em até 5 dias após a última ITR.")
            else:
                st.markdown("""<style>
                @keyframes retorno_itr_piscar {0%,100%{background:#fff1f2;border-color:#ef4444}50%{background:#fecaca;border-color:#991b1b}}
                .st-key-card_retornos_itr{animation:retorno_itr_piscar 1.6s ease-in-out infinite;border:2px solid #ef4444!important;border-radius:12px}
                @media(prefers-reduced-motion:reduce){.st-key-card_retornos_itr{animation:none!important}}
                </style>""", unsafe_allow_html=True)
                selecao_retorno_itr = st.dataframe(
                    retornos_itr.reset_index(drop=True), hide_index=True, use_container_width=True,
                    on_select="rerun", selection_mode="single-row", key="retornos_itr_selecao",
                    column_config={"Última ITR":st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")})
                st.caption("Toque na linha da frota para abrir as atividades das paradas.")
                linhas_retorno_itr = list(selecao_retorno_itr.selection.rows)
                if linhas_retorno_itr and linhas_retorno_itr[0] < len(retornos_itr):
                    selecionada_itr = retornos_itr.iloc[linhas_retorno_itr[0]]
                    chave_selecao_itr = (selecionada_itr["Frota"], str(selecionada_itr["Última ITR"]))
                    if st.session_state.get("retorno_itr_modal_aberto") != chave_selecao_itr:
                        st.session_state["retorno_itr_modal_aberto"] = chave_selecao_itr
                        modal_atividades_retornos_itr(selecionada_itr["Frota"], detalhes_retornos_itr)
                else:
                    st.session_state.pop("retorno_itr_modal_aberto", None)
                st.markdown("#### Ranking de paradas por descrição do serviço")
                ranking_servicos = detalhes_retornos_itr.drop_duplicates(["frota", "os_id"]).copy()
                ranking_servicos["Descrição do serviço"] = (
                    ranking_servicos["descricao"].fillna("").astype(str)
                    .str.replace(r"\s+", " ", regex=True).str.strip().str.upper()
                    .replace("", "SEM DESCRIÇÃO INFORMADA")
                )
                ranking_servicos = (
                    ranking_servicos.groupby("Descrição do serviço", as_index=False)
                    .size().rename(columns={"size": "Qtd. paradas"})
                    .sort_values(["Qtd. paradas", "Descrição do serviço"], ascending=[False, True])
                )
                limite_ranking_itr = st.selectbox("Serviços no gráfico", [5, 10, 20], index=0, key="limite_ranking_itr", format_func=lambda n:f"{n} serviços com mais paradas")
                grafico_ranking_itr = ranking_servicos.head(limite_ranking_itr).copy()
                grafico_ranking_itr["Posição"] = [f"{n}º" for n in range(1, len(grafico_ranking_itr)+1)]
                barras_servicos = alt.Chart(grafico_ranking_itr).encode(
                    x=alt.X("Posição:O", sort=grafico_ranking_itr["Posição"].tolist(),
                            axis=alt.Axis(title="Serviços — veja as descrições abaixo", labelAngle=0, labelFontSize=13)),
                    y=alt.Y("Qtd. paradas:Q", axis=alt.Axis(title="Quantidade de paradas", tickMinStep=1),
                            scale=alt.Scale(domainMin=0, padding=30)),
                    tooltip=[alt.Tooltip("Posição:O"), alt.Tooltip("Descrição do serviço:N"), alt.Tooltip("Qtd. paradas:Q", format="d")],
                )
                grafico_servicos = (
                    barras_servicos.mark_bar(color="#e53935", cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
                    + barras_servicos.mark_text(dy=-12, fontSize=17, fontWeight="bold", color="#10284a").encode(
                        text=alt.Text("Qtd. paradas:Q", format="d"))
                ).properties(height=360, background="white").configure_view(strokeWidth=0).configure_axis(gridColor="#edf0f4", titleFontSize=12)
                st.altair_chart(grafico_servicos, use_container_width=True)
                st.dataframe(grafico_ranking_itr[["Posição", "Descrição do serviço", "Qtd. paradas"]], hide_index=True, use_container_width=True,
                             column_config={"Descrição do serviço":st.column_config.TextColumn(width="large")})
                st.caption("Cada coluna representa um serviço. O número acima é a quantidade de paradas. Cada OS conta uma vez; maiúsculas e espaços não separam descrições iguais.")
                with st.expander("Ver as paradas contabilizadas"):
                    det = detalhes_retornos_itr.rename(columns={"frota":"Frota", "os_id":"OS retorno", "evento":"Evento", "_parada_retorno":"Parada", "descricao":"Descrição", "status":"Status"})
                    st.dataframe(det[["Frota","OS ITR","Última ITR","OS retorno","Evento","Parada","Descrição","Status"]].sort_values(["Frota","Parada"]), hide_index=True, use_container_width=True)

render_card_retornos_itr()

@st.fragment
def render_card_os_excluidas_asn():
    # O clique executa somente este card, sem recarregar e recalcular o monitor.
    with st.container(key="card_os_excluidas_asn"):
        if st.button(f"{len(os_excluidas)}\n\n🗑️ OS EXCLUÍDAS NA LISTA ASN", key="kpi_os_excluidas_asn", use_container_width=True):
            modal_os_excluidas()

render_card_os_excluidas_asn()

@st.fragment
def render_reprovacoes_mega():
    from reprovacoes_whatsapp import render_relatorio
    with st.expander("🚫 RELATÓRIO DE REPROVAÇÕES — MEGA", expanded=False):
        if st.checkbox("Abrir relatório de reprovações", key="abrir_reprovacoes_mega"):
            render_relatorio(SUPABASE_URL, SUPABASE_KEY, MOBILE_READ_ONLY)

render_reprovacoes_mega()

with st.expander("📑 EMBASAMENTO CONTRATUAL", expanded=False):
    render_embasamento_contratual()

with st.expander("📊 RELATÓRIO GERENCIAL — LAUDOS", expanded=False):
    render_relatorio_gerencial_laudos()

with st.expander("📊 MÉDIAS DOS LAUDOS", expanded=False):
    st.caption("Médias calculadas pelos tempos apontados nos laudos, agrupadas pela data de INÍCIO 10 SUL.")
    render_medias_laudos()

with st.expander("📋 APURAÇÃO DOS LAUDOS", expanded=False):
    st.caption("Resumo dos tempos apontados por frota e evidências das atividades.")
    render_laudos_web()

with st.expander("📋 ITR SEM VÍNCULO COM LAUDO", expanded=not MOBILE_READ_ONLY):
    render_itr_sem_laudo()

# Consulta histórica de carretas atendidas — leitura da mesma base consolidada ASN.
@st.fragment
def render_carretas_atendidas_periodo():
    with st.expander("🚛 CARRETAS ATENDIDAS POR PERÍODO", expanded=False):
        st.caption("Consulte atendimentos pela data de início, incluindo OS abertas. Cada OS conta uma vez; uma frota pode ter vários atendimentos.")
        from programacao_semanal import render_programacao_semanal
        with st.expander("📅 Importar programação semanal (somente cadastro)", expanded=False):
            render_programacao_semanal(df, integrado=True)
        hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        c1, c2 = st.columns(2)
        with c1:
            data_ini = st.date_input("Data inicial", value=hoje.replace(day=1), key="atend_periodo_inicio")
        with c2:
            data_fim = st.date_input("Data final", value=hoje, key="atend_periodo_fim")
        if data_ini > data_fim:
            st.warning("A data inicial não pode ser posterior à data final.")
            return
        base = df.copy()
        if base.empty:
            st.info("Não há atendimentos na base para consulta.")
            return
        base["_evento_consulta"] = base["evento"].fillna("").astype(str).str.strip()
        opcoes = sorted(v for v in base["_evento_consulta"].unique() if v)
        eventos = st.multiselect("Filtrar evento (vazio = todos)", opcoes, key="atend_periodo_eventos")
        if eventos:
            base = base.loc[base["_evento_consulta"].isin(eventos)].copy()
        base["_inicio_consulta"] = pd.to_datetime(base["inicio"], errors="coerce")
        # Datas sem timezone são apresentadas como horário local da operação.
        if getattr(base["_inicio_consulta"].dt, "tz", None) is not None:
            base["_inicio_consulta"] = base["_inicio_consulta"].dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
        base = base.loc[
            base["_inicio_consulta"].notna()
            & (base["_inicio_consulta"].dt.date >= data_ini)
            & (base["_inicio_consulta"].dt.date <= data_fim)
        ].copy()
        if "os_id" in base.columns:
            base = base.drop_duplicates(subset=["os_id"], keep="last")
        frotas = base["frota"].dropna().astype(str).str.strip()
        frotas = frotas.loc[~frotas.isin(["", "nan", "None"])]
        k1, k2 = st.columns(2)
        k1.metric("Carretas distintas", frotas.nunique())
        k2.metric("Total de atendimentos", len(base))
        if base.empty:
            st.info("Nenhum atendimento encontrado com os filtros informados.")
            return
        base["_fim_consulta"] = pd.to_datetime(base["fim"], errors="coerce")
        if getattr(base["_fim_consulta"].dt, "tz", None) is not None:
            base["_fim_consulta"] = base["_fim_consulta"].dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
        tempo = (base["_fim_consulta"] - base["_inicio_consulta"]).dt.total_seconds().div(60)
        def fmt_tempo(v):
            if pd.isna(v) or v < 0:
                return ""
            minutos = int(v)
            return f"{minutos // 60:02d}:{minutos % 60:02d}"
        relacao = pd.DataFrame({
            "OS/ID": base["os_id"].astype(str),
            "FROTA": base["frota"].astype(str),
            "EVENTO": base["_evento_consulta"],
            "INÍCIO": base["_inicio_consulta"].dt.strftime("%d/%m/%Y %H:%M"),
            "LIBERAÇÃO": base["_fim_consulta"].dt.strftime("%d/%m/%Y %H:%M").fillna("Em aberto"),
            "TEMPO": tempo.map(fmt_tempo),
        }).sort_values(["INÍCIO", "FROTA"], ascending=[False, True])
        # Cruzamento opcional com a programação oficial persistida.
        try:
            from programacao_semanal import _frota, _tipo
            chave_programacao = _secret("SUPABASE_WRITE_KEY") or SUPABASE_KEY
            api_headers = {"apikey": chave_programacao}
            if not chave_programacao.startswith(("sb_secret_", "sb_publishable_")):
                api_headers["Authorization"] = f"Bearer {chave_programacao}"
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/monitor_programacoes_semanais",
                headers=api_headers,
                params={"select": "id,semana_inicio,nome_arquivo,dados", "order": "semana_inicio.desc"},
                timeout=20,
            )
            resp.raise_for_status()
            historico = resp.json()
            oficiais = [p for p in historico if p.get("dados") and all(k in p["dados"][0] for k in ("GO", "DATA", "TIPO"))]
            if oficiais:
                escolhas = {str(p["id"]): p["nome_arquivo"] for p in oficiais}
                escolhas[""] = "Sem programação (somente atendimentos)"
                escolha = st.selectbox("Confrontar com programação semanal salva",
                                      list(escolhas), format_func=lambda k: escolhas[k],
                                      key="atend_periodo_programacao")
                if escolha:
                    programacao = next(p for p in oficiais if str(p["id"]) == escolha)
                    linhas = pd.DataFrame(programacao["dados"])
                    linhas["FROTA"] = linhas["GO"].map(_frota)
                    linhas["EVENTO"] = linhas["TIPO"].map(_tipo)
                    linhas["DATA PROGRAMADA"] = pd.to_datetime(linhas["DATA"], errors="coerce")
                    linhas = linhas.loc[linhas["FROTA"].ne("") & linhas["DATA PROGRAMADA"].notna()]
                    if eventos:
                        linhas = linhas.loc[linhas["EVENTO"].isin([_tipo(e) for e in eventos])]
                    relacao["DATA PROGRAMADA"] = ""
                    relacao["ATENDIDA EM"] = relacao["INÍCIO"].str[:10]
                    relacao["SITUAÇÃO"] = "SEM PROGRAMAÇÃO"
                    relacao["_frota"] = relacao["FROTA"].map(_frota)
                    relacao["_evento"] = relacao["EVENTO"].map(_tipo)
                    pendentes = []
                    # Todas as OS da mesma frota/evento devem herdar a programação,
                    # inclusive quando a ASN contém mais de uma OS no mesmo período.
                    for _, p in linhas.iterrows():
                        candidatos = relacao.loc[
                            relacao["_frota"].eq(p["FROTA"]) &
                            relacao["_evento"].eq(p["EVENTO"])
                        ].copy()
                        if not candidatos.empty:
                            for idx in candidatos.index:
                                real = pd.to_datetime(relacao.at[idx, "INÍCIO"], dayfirst=True, errors="coerce")
                                prevista = p["DATA PROGRAMADA"].normalize()
                                if pd.isna(real):
                                    continue
                                # Havendo mais de uma programação da mesma frota,
                                # prevalece a data programada mais próxima da OS.
                                anterior = relacao.at[idx, "DATA PROGRAMADA"]
                                if anterior:
                                    data_anterior = pd.to_datetime(anterior, dayfirst=True, errors="coerce")
                                    if pd.notna(data_anterior) and abs((real.normalize() - data_anterior).days) <= abs((real.normalize() - prevista).days):
                                        continue
                                relacao.at[idx, "DATA PROGRAMADA"] = prevista.strftime("%d/%m/%Y")
                                relacao.at[idx, "SITUAÇÃO"] = (
                                    "NO DIA" if real.normalize() == prevista
                                    else "ANTECIPADA" if real.normalize() < prevista else "ATRASADA"
                                )
                        else:
                            pendentes.append({
                                "OS/ID": "", "FROTA": p["FROTA"], "EVENTO": p["EVENTO"],
                                "INÍCIO": "", "LIBERAÇÃO": "", "TEMPO": "",
                                "DATA PROGRAMADA": p["DATA PROGRAMADA"].strftime("%d/%m/%Y"),
                                "ATENDIDA EM": "NÃO ATENDIDA",
                                "SITUAÇÃO": "AGUARDANDO" if p["DATA PROGRAMADA"].date() > hoje else "NÃO ATENDIDA",
                                "_frota": p["FROTA"], "_evento": p["EVENTO"]
                            })
                    if pendentes:
                        relacao = pd.concat([relacao, pd.DataFrame(pendentes)], ignore_index=True)
                    relacao = relacao.drop(columns=["_frota", "_evento"])
                    ordem = ["OS/ID", "FROTA", "EVENTO", "DATA PROGRAMADA", "ATENDIDA EM", "SITUAÇÃO", "INÍCIO", "LIBERAÇÃO", "TEMPO"]
                    relacao = relacao[ordem]
                    st.caption("A conferência considera o evento e a frota na semana selecionada; atendimentos fora da programação permanecem identificados.")
            else:
                st.caption("Importe e salve uma programação para exibir DATA PROGRAMADA e ATENDIDA EM.")
        except Exception as exc:
            st.warning(f"Não foi possível consultar a programação salva: {exc}")
        # Painel de exceções: somente quando existe programação selecionada.
        possui_programacao = "DATA PROGRAMADA" in relacao.columns and "SITUAÇÃO" in relacao.columns
        if possui_programacao:
            fora_programacao = relacao.loc[relacao["SITUAÇÃO"].eq("SEM PROGRAMAÇÃO")].copy()
            nao_atendidas = relacao.loc[relacao["SITUAÇÃO"].eq("NÃO ATENDIDA")].copy()
            st.markdown("#### 📋 Resumo das divergências da programação")
            quadro_esq, quadro_dir = st.columns(2)
            with quadro_esq:
                st.error(f"🚨 Atendidas fora da programação — {fora_programacao['FROTA'].nunique()} carreta(s)")
                if fora_programacao.empty:
                    st.success("Nenhuma carreta atendida fora da programação.")
                else:
                    st.dataframe(fora_programacao[["FROTA", "OS/ID", "EVENTO", "ATENDIDA EM"]].drop_duplicates(),
                        use_container_width=True, hide_index=True)
            with quadro_dir:
                st.warning(f"⚠️ Programadas e não atendidas — {nao_atendidas['FROTA'].nunique()} carreta(s)")
                if nao_atendidas.empty:
                    st.success("Nenhuma carreta programada ficou sem atendimento.")
                else:
                    st.dataframe(nao_atendidas[["FROTA", "EVENTO", "DATA PROGRAMADA"]].drop_duplicates(),
                        use_container_width=True, hide_index=True)
        st.dataframe(relacao, hide_index=True, use_container_width=True, height=min(550, 40 + 35 * len(relacao)))
        # PDF para impressão da mesma conferência exibida na tela.
        try:
            from reportlab.lib import colors as pdf_colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT
            from reportlab.lib.units import mm
            from xml.sax.saxutils import escape
            from io import BytesIO as PdfBytesIO

            nome_programacao_pdf = str(escolhas.get(escolha, "Sem programação")) if "escolhas" in locals() and "escolha" in locals() else "Não selecionada"

            def gerar_resumo_pdf():
                memoria = PdfBytesIO()
                documento = SimpleDocTemplate(memoria, pagesize=landscape(A4),
                    leftMargin=12*mm, rightMargin=12*mm,
                    topMargin=14*mm, bottomMargin=15*mm)
                estilos = getSampleStyleSheet()
                titulo_pdf = ParagraphStyle("titulo_conf", parent=estilos["Heading1"],
                    fontSize=16, leading=19, textColor=pdf_colors.HexColor("#183C34"))
                normal_pdf = ParagraphStyle("normal_conf", parent=estilos["Normal"],
                    fontSize=8, leading=11)
                celula_pdf = ParagraphStyle("celula_conf", parent=normal_pdf,
                    fontSize=6.8, leading=9)
                cab_pdf = ParagraphStyle("cab_conf", parent=celula_pdf,
                    fontName="Helvetica-Bold", textColor=pdf_colors.white)
                itens = [Paragraph("10 SUL | RESUMO DE ATENDIMENTOS", titulo_pdf),
                    Spacer(1, 3*mm),
                    Paragraph(f"Período: {data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}", normal_pdf),
                    Paragraph("Eventos: " + escape(", ".join(str(e) for e in eventos) if eventos else "Todos"), normal_pdf),
                    Paragraph("Programação: " + escape(nome_programacao_pdf), normal_pdf),
                    Spacer(1, 5*mm)]
                situacoes = relacao["SITUAÇÃO"].fillna("").astype(str).value_counts() if "SITUAÇÃO" in relacao.columns else pd.Series(dtype=int)
                total_distintas = relacao.loc[relacao["OS/ID"].astype(str).str.strip().ne(""), "FROTA"].nunique()
                resumo_linhas = [
                    ["CARRETAS ATENDIDAS", "TOTAL DE ATENDIMENTOS", "NO DIA", "ATRASADAS", "ANTECIPADAS", "NÃO ATENDIDAS", "SEM PROGRAMAÇÃO"],
                    [str(total_distintas), str(len(base)), str(situacoes.get("NO DIA", 0)),
                     str(situacoes.get("ATRASADA", 0)), str(situacoes.get("ANTECIPADA", 0)),
                     str(situacoes.get("NÃO ATENDIDA", 0)), str(situacoes.get("SEM PROGRAMAÇÃO", 0))],
                ]
                resumo_tabela = Table(resumo_linhas, colWidths=[39*mm]*7)
                resumo_tabela.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), pdf_colors.HexColor("#E8F0ED")),
                    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                    ("FONTSIZE", (0,0), (-1,0), 7),
                    ("FONTSIZE", (0,1), (-1,1), 12),
                    ("ALIGN", (0,0), (-1,-1), "CENTER"),
                    ("TOPPADDING", (0,0), (-1,-1), 7),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 7),
                    ("BOX", (0,0), (-1,-1), 0.5, pdf_colors.HexColor("#B6CAC2")),
                ]))
                itens.extend([resumo_tabela, Spacer(1, 7*mm)])
                if possui_programacao:
                    for titulo_quadro, dados_quadro, campos_quadro in [
                        ("ATENDIDAS FORA DA PROGRAMAÇÃO", fora_programacao,
                         ["FROTA", "OS/ID", "EVENTO", "ATENDIDA EM"]),
                        ("PROGRAMADAS E NÃO ATENDIDAS", nao_atendidas,
                         ["FROTA", "EVENTO", "DATA PROGRAMADA"])]:
                        itens.append(Paragraph(
                            escape(titulo_quadro) + f" — {dados_quadro['FROTA'].nunique()} carreta(s)",
                            estilos["Heading3"]))
                        if dados_quadro.empty:
                            itens.append(Paragraph("Nenhuma ocorrência.", normal_pdf))
                        else:
                            campos_quadro = [col for col in campos_quadro if col in dados_quadro.columns]
                            linhas_quadro = [[Paragraph(escape(col), cab_pdf) for col in campos_quadro]]
                            for _, linha_quadro in dados_quadro[campos_quadro].drop_duplicates().iterrows():
                                linhas_quadro.append([
                                    Paragraph(escape(str(linha_quadro[col])) if pd.notna(linha_quadro[col]) else "", celula_pdf)
                                    for col in campos_quadro])
                            larg_quadro = [min(48, 250 / len(campos_quadro)) * mm] * len(campos_quadro)
                            tabela_quadro = Table(linhas_quadro, colWidths=larg_quadro,
                                repeatRows=1, hAlign="LEFT")
                            tabela_quadro.setStyle(TableStyle([
                                ("BACKGROUND", (0,0), (-1,0), pdf_colors.HexColor("#183C34")),
                                ("ROWBACKGROUNDS", (0,1), (-1,-1),
                                 [pdf_colors.white, pdf_colors.HexColor("#F5F8F6")]),
                                ("VALIGN", (0,0), (-1,-1), "TOP"),
                                ("TOPPADDING", (0,0), (-1,-1), 5),
                                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                            ]))
                            itens.append(tabela_quadro)
                        itens.append(Spacer(1, 4*mm))
                itens.append(Paragraph("Relação de atendimentos e programação", estilos["Heading3"]))
                colunas = ["OS/ID", "FROTA", "EVENTO", "DATA PROGRAMADA", "ATENDIDA EM",
                           "SITUAÇÃO", "INÍCIO", "LIBERAÇÃO", "TEMPO"]
                disponiveis = [col for col in colunas if col in relacao.columns]
                larguras = {"OS/ID": 19, "FROTA": 19, "EVENTO": 22,
                    "DATA PROGRAMADA": 30, "ATENDIDA EM": 28, "SITUAÇÃO": 31,
                    "INÍCIO": 34, "LIBERAÇÃO": 34, "TEMPO": 18}
                linhas_pdf = [[Paragraph(escape(col), cab_pdf) for col in disponiveis]]
                for _, registro in relacao.iterrows():
                    linhas_pdf.append([Paragraph(escape(str(registro[col])) if pd.notna(registro[col]) else "", celula_pdf)
                                      for col in disponiveis])
                detalhe = Table(linhas_pdf, colWidths=[larguras[col]*mm for col in disponiveis],
                                repeatRows=1, hAlign="LEFT")
                detalhe.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), pdf_colors.HexColor("#183C34")),
                    ("ROWBACKGROUNDS", (0,1), (-1,-1), [pdf_colors.white, pdf_colors.HexColor("#F5F8F6")]),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING", (0,0), (-1,-1), 5),
                    ("RIGHTPADDING", (0,0), (-1,-1), 5),
                    ("TOPPADDING", (0,0), (-1,-1), 6),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                    ("LINEBELOW", (0,1), (-1,-1), 0.2, pdf_colors.HexColor("#DDE6E1")),
                ]))
                itens.append(detalhe)
                def rodape(canvas, doc):
                    canvas.saveState()
                    canvas.setFont("Helvetica", 8)
                    canvas.setFillColor(pdf_colors.HexColor("#64746D"))
                    canvas.drawString(12*mm, 9*mm, "10 Sul | Monitor Web | Conferência de programação")
                    canvas.drawRightString(285*mm, 9*mm, f"Página {doc.page}")
                    canvas.restoreState()
                documento.build(itens, onFirstPage=rodape, onLaterPages=rodape)
                return memoria.getvalue()

            st.download_button("🖨️ Imprimir resumo em PDF", data=gerar_resumo_pdf(),
                file_name=f"RESUMO_ATENDIMENTOS_{data_ini}_{data_fim}.pdf",
                mime="application/pdf", key="imprimir_resumo_atendimentos")
        except Exception as exc:
            st.warning(f"Não foi possível preparar o PDF para impressão: {exc}")

        from io import BytesIO
        try:
            arquivo = BytesIO()
            with pd.ExcelWriter(arquivo, engine="openpyxl") as writer:
                relacao.to_excel(writer, index=False, sheet_name="Atendimentos")
            st.download_button("📥 Exportar Excel", arquivo.getvalue(),
                               file_name=f"carretas_atendidas_{data_ini}_{data_fim}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="baixar_carretas_atendidas")
        except ImportError:
            st.download_button("📥 Exportar CSV (Excel)",
                               relacao.to_csv(index=False, sep=";").encode("utf-8-sig"),
                               file_name=f"carretas_atendidas_{data_ini}_{data_fim}.csv",
                               mime="text/csv", key="baixar_carretas_atendidas_csv")

render_carretas_atendidas_periodo()

st.caption("Atualização automática a cada 60 segundos.")

# Crédito discreto no rodapé
st.markdown(
    """
    <div style="
        margin-top: 26px;
        padding: 14px 0 8px 0;
        text-align: center;
        color: #98A2B3;
        font-size: 11px;
        font-weight: 400;
        letter-spacing: 0.1px;
    ">
        Desenvolvido por Evandro dos Santos Oliveira Junior
    </div>
    """,
    unsafe_allow_html=True,
)















