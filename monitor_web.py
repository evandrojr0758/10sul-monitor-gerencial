import os
import re
from datetime import timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Monitor Gerencial 10 Sul", page_icon="📺", layout="wide")

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

@st.cache_data(ttl=60, show_spinner=False)
def carregar():
    # O Supabase/PostgREST limita cada resposta a ~1000 linhas.
    # Portanto buscamos em páginas para trazer TODO o histórico,
    # inclusive revisões antigas usadas na Consulta Rápida.
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados nos Secrets.")

    url=f"{SUPABASE_URL}/rest/v1/monitor_atendimentos"
    base_headers={
        "apikey":SUPABASE_KEY,
        "Authorization":f"Bearer {SUPABASE_KEY}",
    }

    todos=[]
    pagina=1000
    inicio_range=0

    while True:
        fim_range=inicio_range + pagina - 1
        headers=dict(base_headers)
        headers["Range"]=f"{inicio_range}-{fim_range}"
        headers["Prefer"]="count=none"

        r=requests.get(
            url,
            headers=headers,
            params={"select":"*","order":"inicio.desc"},
            timeout=60
        )
        if not r.ok:
            raise RuntimeError(f"Supabase HTTP {r.status_code}: {r.text[:800]}")

        lote=r.json()
        if not lote:
            break

        todos.extend(lote)

        if len(lote) < pagina:
            break

        inicio_range += pagina

    return pd.DataFrame(todos)

def norm_frota(v):
    s=str(v or "").strip()
    return re.sub(r"\.0$","",s)

def hhmm(h):
    if h is None or pd.isna(h): return "--:--"
    m=max(0,int(round(float(h)*60)))
    return f"{m//60:02d}:{m%60:02d}"


@st.cache_data(ttl=60, show_spinner=False)
def carregar_laudos_manuais_web():
    import json
    if not SUPABASE_URL or not SUPABASE_KEY: return pd.DataFrame()
    try:
        url=f"{SUPABASE_URL}/storage/v1/object/authenticated/evidencias-desvios/monitor/laudos_manuais.json"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
        r=requests.get(url,headers=h,timeout=45)
        if not r.ok:return pd.DataFrame()
        return pd.DataFrame(json.loads(r.content.decode("utf-8")))
    except Exception:return pd.DataFrame()

def baixar_evidencia_laudo_web(path):
    try:
        url=f"{SUPABASE_URL}/storage/v1/object/authenticated/evidencias-desvios/{path}"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
        r=requests.get(url,headers=h,timeout=45)
        return (r.content,r.headers.get("content-type","")) if r.ok else (None,"")
    except Exception:return None,""

def render_laudos_web():
    import json
    d=carregar_laudos_manuais_web()
    if d.empty:
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

    # 1) RESUMO COMPACTO — uma linha por frota. Nada de botões gigantes.
    pv=d.pivot_table(index=["REGISTRO","FROTA"],columns="CLASSIFICACAO",values="HORAS",aggfunc="sum",fill_value=0).reset_index()
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
    ev=st.dataframe(
        resumo,
        use_container_width=True,
        hide_index=True,
        height=min(310, 38+35*max(1,len(resumo))),
        on_select="rerun",
        selection_mode="single-row",
        key="laudos_resumo_tabela",
    )
    rows=list(ev.selection.rows) if hasattr(ev,"selection") else []
    if rows:
        pos=int(rows[0])
        st.session_state["wreg"]=str(pv.iloc[pos]["REGISTRO"])
        st.session_state["waid"]=None

    # 2) FROTA SELECIONADA — somente atividades daquela frota.
    reg=st.session_state.get("wreg")
    if not reg: return
    det=d[d["REGISTRO"].astype(str).eq(str(reg))].copy()
    if det.empty: return
    det["_AID_SEL"]=[str(v).strip() if str(v).strip() and str(v).strip().lower()!="nan" else f"{reg}_{idx}" for idx,v in zip(det.index,det["ATIVIDADE_ID"])]

    st.markdown(f"**Frota {det.iloc[0]['FROTA']} — detalhamento**")
    detalhes=pd.DataFrame({
        "ATIVIDADE":det["ATIVIDADE"].fillna("Atividade").astype(str)+"  ›",
        "INÍCIO":det["INICIO_ATIVIDADE_DT"].apply(lambda x:"--:--" if pd.isna(x) else x.strftime("%H:%M")),
        "FIM":det["FIM_ATIVIDADE_DT"].apply(lambda x:"--:--" if pd.isna(x) else x.strftime("%H:%M")),
        "TEMPO TOTAL":det["HORAS"].apply(hhmm),
    }).reset_index(drop=True)
    ev2=st.dataframe(
        detalhes,
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

try:
    df=carregar()
except Exception as e:
    st.error(f"Não foi possível carregar o monitor: {e}")
    st.stop()

if df.empty:
    st.warning("A tabela monitor_atendimentos está vazia. Abra o sistema principal para sincronizar a base.")
    st.stop()

for c in ["parada","inicio","fim"]:
    if c in df.columns:
        df[c]=pd.to_datetime(df[c],errors="coerce")
for c in ["os_id","frota","evento","status","descricao","modal","unidade"]:
    if c not in df.columns: df[c]=""
df["frota"]=df["frota"].apply(norm_frota)

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
    st.markdown(
        f"<div style='display:flex;align-items:end;gap:10px;margin:0 0 3px'>"
        f"<span style='font-size:11px;font-weight:800;color:#667085'>MÉDIA DO DIA</span>"
        f"<span style='font-size:28px;line-height:1;font-weight:900;color:#10284a'>{hhmm(hoje)}</span>"
        f"<span style='font-size:11px;color:#98a2b3'>SLA {sla:02d}:00</span></div>", unsafe_allow_html=True)
    st.markdown("<div style='font-size:11px;font-weight:850;color:#344054;margin:10px 0 4px'>MÉDIA DIÁRIA • ÚLTIMOS 7 DIAS</div>",unsafe_allow_html=True)
    _grafico_media_diaria(g,sla)

def render_medias_supervisor():
    c1,c2=st.columns(2,gap="small")
    with c1:
        with st.container(border=True): _quadro_supervisor("ITR","🔧")
    with c2:
        with st.container(border=True): _quadro_supervisor("REVISÃO","🛠️")


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
    col_ini=_coluna_laudo(d,["INICIO 10 SUL","INICIO_10_SUL","INICIO10SUL"])
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
    hj=g.loc[g["DIA_DT"].eq(agora.normalize()),"MEDIA_H"]
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

def render_medias_laudos():
    c1,c2=st.columns(2,gap="small")
    with c1:
        with st.container(border=True): _quadro_media_laudo("ITR","🔧")
    with c2:
        with st.container(border=True): _quadro_media_laudo("CNP","🚨")


# OFICINA AGORA: mesma lógica-base do app principal: status manutenção + sem fim.
status=df["status"].fillna("").astype(str).str.upper()
mon=df[status.str.contains("MANUT",na=False)&df["fim"].isna()].copy()
mon["inicio_mon"]=mon["inicio"].fillna(mon["parada"])
mon["horas_aberto"]=((agora-mon["inicio_mon"]).dt.total_seconds()/3600).clip(lower=0)
mon=mon.sort_values("inicio_mon",ascending=False).drop_duplicates("os_id",keep="first")
mev,mitr,mrev,msos,mcnp=evento_flags(mon["evento"])
mon["sla_h"]=pd.NA
mon.loc[mitr,"sla_h"]=12.0
mon.loc[mrev,"sla_h"]=24.0
mon["sla_h"]=pd.to_numeric(mon["sla_h"],errors="coerce")
mon["acima_sla"]=mon["sla_h"].notna()&(mon["horas_aberto"]>=mon["sla_h"])

st.markdown("<div class='mon-title'>📺 MONITOR DA OFICINA</div>",unsafe_allow_html=True)
st.markdown(f"<div class='mon-sub'>Monitor Gerencial Web • Atualizado em {agora.strftime('%d/%m/%Y %H:%M')}</div>",unsafe_allow_html=True)

render_medias_supervisor()

st.markdown("<div class='mon-section'><div class='mon-section-title'>OFICINA AGORA</div><div class='mon-section-sub'>Situação em tempo real e pontos que exigem atenção</div></div>",unsafe_allow_html=True)
@st.dialog("Relação de carretas", width="large")
def modal_os_abertas(titulo, dados):
    st.markdown(f"### {titulo}")
    if dados is None or dados.empty:
        st.info("Nenhuma OS aberta neste card.")
        return
    x=dados.copy()
    x["TEMPO ABERTO"]=x["horas_aberto"].apply(hhmm)
    x["INÍCIO"]=pd.to_datetime(x["inicio_mon"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    x["SITUAÇÃO"]=x["acima_sla"].map({True:"🔴 SLA ULTRAPASSADO",False:"🟢 EM MANUTENÇÃO"})
    x=x.rename(columns={"os_id":"OS/ID","frota":"FROTA","evento":"EVENTO","descricao":"DESCRIÇÃO DO EVENTO"})
    cols_show=["OS/ID","FROTA","EVENTO","DESCRIÇÃO DO EVENTO","INÍCIO","TEMPO ABERTO","SITUAÇÃO"]
    st.dataframe(x[cols_show],use_container_width=True,hide_index=True)

cards=[
    (len(mon),"🔧 EM MANUTENÇÃO","",mon),
    (int(mcnp.sum()),"🚨 CNP ABERTAS","red",mon[mcnp]),
    (int(msos.sum()),"🆘 SOS ABERTOS","red",mon[msos]),
    (int(mitr.sum()),"🔧 ITR ABERTAS","",mon[mitr]),
    (int(mrev.sum()),"🛠️ REVISÕES","",mon[mrev]),
    (0,"📦 AG. PEÇA","orange",mon.iloc[0:0]),
    (int(mon["acima_sla"].sum()),"⏱️ ACIMA SLA","red",mon[mon["acima_sla"]]),
]
cols=st.columns(7,gap="small")
for i,(col,(n,lab,kind,dados_card)) in enumerate(zip(cols,cards)):
    with col:
        # Botão real: funciona por toque no celular e clique no computador.
        if st.button(f"{n}\n\n{lab}",key=f"kpi_abertas_{i}",use_container_width=True):
            modal_os_abertas(lab,dados_card)

with st.expander("📊 MÉDIAS DOS LAUDOS", expanded=False):
    st.caption("Médias calculadas pelos tempos apontados nos laudos, agrupadas pela data de INÍCIO 10 SUL.")
    render_medias_laudos()

st.markdown("<div class='mon-section'><div class='mon-section-title'>APURAÇÃO DOS LAUDOS</div><div class='mon-section-sub'>Resumo dos tempos apontados por frota e evidências das atividades</div></div>",unsafe_allow_html=True)
render_laudos_web()

st.markdown("#### 🔎 Consulta rápida de frota")

@st.dialog("🔎 Histórico da frota", width="large")
def modal_historico_frota(fq):
    hist=df[df["frota"].eq(fq)].copy().sort_values("inicio",ascending=False)
    st.markdown(f"### Frota {fq}")
    if hist.empty:
        st.warning("Frota não encontrada na base sincronizada.")
        return

    hev=hist["evento"].fillna("").astype(str).str.upper().str.strip()
    # No monitor original, a preventiva é referenciada pela liberação.
    itr=hist[hev.eq("ITR")].copy()
    rev=hist[hev.str.contains("REVIS",na=False)].copy()

    def ultima_liberada(x):
        if x.empty: return None
        x=x.copy()
        x["_lib"]=x["fim"]
        x=x[x["_lib"].notna()].sort_values("_lib",ascending=False)
        return None if x.empty else x.iloc[0]

    r_itr=ultima_liberada(itr)
    r_rev=ultima_liberada(rev)

    c1,c2=st.columns(2)
    def preventiva_card(col, titulo, row, cor, intervalo):
        with col:
            with st.container(border=True):
                st.markdown(f"<div style='font-size:13px;font-weight:800;color:#667085'>{cor} {titulo}</div>",unsafe_allow_html=True)
                if row is None:
                    st.markdown("<div style='font-size:24px;font-weight:900'>Não encontrada</div>",unsafe_allow_html=True)
                    st.caption("Sem preventiva liberada na base sincronizada.")
                    return
                lib=pd.Timestamp(row["_lib"])
                dias=max(0,(agora.normalize()-lib.normalize()).days)
                prox=lib.normalize()+pd.Timedelta(days=intervalo)
                st.markdown(f"<div style='font-size:27px;font-weight:900'>{lib.strftime('%d/%m/%Y')}</div>",unsafe_allow_html=True)
                st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **{prox.strftime('%d/%m/%Y')}**")
                st.caption(f"Liberação: {lib.strftime('%d/%m/%Y %H:%M')}")

    preventiva_card(c1,"ÚLTIMA ITR",r_itr,"🔵",30)
    preventiva_card(c2,"ÚLTIMA REVISÃO",r_rev,"🟣",120)

    st.markdown("#### Histórico de atendimentos")
    show=hist[["os_id","evento","descricao","parada","inicio","fim","status"]].copy()
    show.columns=["OS/ID","EVENTO","DESCRIÇÃO","PARADA","INÍCIO","FIM","STATUS"]
    st.dataframe(show,use_container_width=True,hide_index=True)

q1,q2=st.columns([5,1])
with q1:
    frota_q=st.text_input("Frota",placeholder="Ex.: 13725",label_visibility="collapsed")
with q2:
    pesquisar=st.button("🔎 Pesquisar",use_container_width=True)
if pesquisar and frota_q.strip():
    modal_historico_frota(norm_frota(frota_q))

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
mot=[]
for cat,termos in familias.items():
    qa=int(atual["desc_norm"].fillna("").astype(str).apply(lambda z:any(str(t) in z for t in termos)).sum())
    qb=int(anterior["desc_norm"].apply(lambda z:any(t in z for t in termos)).sum())
    mot.append((cat,qa,qa-qb))
mot=sorted(mot,key=lambda x:(x[1],x[2]),reverse=True)

st.markdown("<div class='mon-section'><div class='mon-section-title'>4. ALERTAS & HUNT</div><div class='mon-section-sub'>Corretivas não programadas e inteligência da operação</div></div>",unsafe_allow_html=True)
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
                    atual["desc_norm"].apply(lambda z:any(t in z for t in termos))
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
