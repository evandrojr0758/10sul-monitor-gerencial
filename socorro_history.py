"""Consulta somente de leitura para o aplicativo de atendimento do socorro."""
import json
import re
from datetime import timedelta
import pandas as pd

SOCORRO_ORIGIN = "https://socorro-atendimentos-10sul.peachycrown16.chatgpt.site"


def normalizar_go(valor):
    texto = str(valor or "").strip().upper()
    texto = re.sub(r"^GO[\s\-:]*", "", texto)
    return re.sub(r"\.0$", "", texto).strip()


def historico_frota(base, go, agora, converter_hora):
    go = normalizar_go(go)
    if go != "ALL" and not re.fullmatch(r"[0-9]{3,10}", go):
        raise ValueError("Informe o GO da frota, usando apenas números.")
    dados = base.copy()
    if dados.empty:
        return {"go": go, "records": [], "total": 0}
    if go != "ALL":
        dados = dados.loc[dados["frota"].map(normalizar_go).eq(go)].copy()
    for coluna in ["parada", "inicio", "fim", "fim_asn", "fim_liberacao_10sul"]:
        if coluna not in dados:
            dados[coluna] = pd.NaT
        dados[coluna] = pd.to_datetime(dados[coluna].map(converter_hora), errors="coerce")
    dados["referencia"] = dados["fim"].fillna(dados["inicio"]).fillna(dados["parada"])
    dados = dados.loc[dados["referencia"].between(agora - timedelta(days=15), agora)].copy()
    dados = dados.sort_values("referencia", ascending=False).drop_duplicates(["os_id", "frota"])
    total = len(dados)

    def texto(valor):
        return "" if pd.isna(valor) else str(valor).strip()

    def millis(valor):
        if pd.isna(valor):
            return None
        return int(pd.Timestamp(valor).tz_localize("America/Sao_Paulo").timestamp() * 1000)

    rows = []
    for _, row in dados.head(5000 if go == "ALL" else 200).iterrows():
        cliente_fim = pd.notna(row["fim_asn"])
        manual_fim = pd.notna(row["fim_liberacao_10sul"])
        status = "Liberado" if cliente_fim else "Liberado 10 Sul · aguardando cliente" if manual_fim else texto(row.get("status", "")) or "Em manutenção"
        rows.append({"id": texto(row.get("os_id", "")), "fleet": normalizar_go(row["frota"]),
                     "event": texto(row.get("evento", "")), "description": texto(row.get("descricao", ""))[:4000],
                     "status": status, "reference": millis(row["referencia"]),
                     "departure": millis(row["parada"]), "start": millis(row["inicio"]), "end": millis(row["fim"])})
    return {"go": go, "records": rows, "total": total}


def render_consulta(carregar, converter_hora):
    import streamlit as st
    import streamlit.components.v1 as components
    go = normalizar_go(st.query_params.get("go", ""))
    nonce = str(st.query_params.get("consulta_nonce", ""))
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        nonce = ""
    agora = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)
    payload = {"type": "10sul-socorro-historico", "nonce": nonce, "go": go,
               "loadedAt": int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)}
    try:
        payload.update(historico_frota(carregar(), go, agora, converter_hora))
    except Exception:
        payload.update(error="Não foi possível consultar o sistema principal. Tente novamente com conexão.", records=[])
    # Escaping '<' prevents descriptions from terminating the inline JSON script.
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    html = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
    body{font:15px system-ui;color:#15364b;margin:12px}h2{font-size:21px}article{border:1px solid #dce4eb;border-radius:12px;padding:16px;margin:10px 0}p{white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:#667889;font-size:13px}
    </style></head><body><h2 id="title"></h2><div id="result"></div><script>
    const data=PAYLOAD;
    document.getElementById('title').textContent=(data.go==='ALL'?'Atendimentos recentes':'GO '+data.go)+' · últimos 15 dias';
    const result=document.getElementById('result');
    const time=v=>v?new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(v):'—';
    if(data.error||!data.records.length){result.textContent=data.error||'Nenhum atendimento encontrado nos últimos 15 dias.';}
    for(const r of (data.go==='ALL'?[]:data.records)){const a=document.createElement('article');const h=document.createElement('strong');h.textContent=r.event+' · OS '+r.id;a.append(h);for(const text of [r.status,'Parada: '+time(r.departure),'Início: '+time(r.start)+' · Fim: '+time(r.end),r.description]){const p=document.createElement('p');p.textContent=text;a.append(p);}result.append(a);}
    if(data.nonce){const send=()=>window.top.postMessage(data,ORIGIN);send();setTimeout(send,800);setTimeout(send,2500);}
    </script></body></html>""".replace("PAYLOAD", encoded).replace("ORIGIN", json.dumps(SOCORRO_ORIGIN))
    components.html(html, height=min(1200, 120 + 240 * len(payload.get("records", []))), scrolling=True)
    st.stop()
