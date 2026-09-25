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

st.markdown("<div class='mon-section'><div class='mon-section-title'>1. OFICINA AGORA</div><div class='mon-section-sub'>Situação em tempo real e pontos que exigem atenção</div></div>",unsafe_allow_html=True)
cards=[
    (len(mon),"🔧 EM<br>MANUTENÇÃO",""),
    (int(mcnp.sum()),"🚨 CNP<br>ABERTAS","red"),
    (int(msos.sum()),"🆘 SOS<br>ABERTOS","red"),
    (int(mitr.sum()),"🔧 ITR ABERTAS",""),
    (int(mrev.sum()),"🛠️ REVISÕES",""),
    (0,"📦 AG. PEÇA","orange"),
    (int(mon["acima_sla"].sum()),"⏱️ ACIMA SLA","red"),
]
cols=st.columns(7,gap="small")
for col,(n,lab,kind) in zip(cols,cards):
    cls="kpi "+("kpi-red" if kind=="red" else "kpi-orange" if kind=="orange" else "")
    with col:
        st.markdown(f"<div class='{cls}'><div class='kpi-n'>{n}</div><div class='kpi-l'>{lab}</div></div>",unsafe_allow_html=True)

# MÉDIAS
def base_media(tipo):
    b=df.copy()
    e=b["evento"].fillna("").astype(str).str.upper().str.strip()
    mask=e.eq("ITR") if tipo=="ITR" else e.str.contains("REVIS",na=False)
    b=b[mask].copy()
    b=b[~b["frota"].isin(ESPECIAIS)].copy()
    ini=b["inicio"]
    fim=b["fim"]
    stt=b["status"].fillna("").astype(str).str.upper()
    aberto=stt.str.contains("MANUT",na=False)|fim.isna()
    # Compatibilidade com pandas/Streamlit Cloud: preserva o mesmo dtype datetime64[ns]
    # ao preencher atendimentos ainda abertos com o horário atual.
    fimcalc=fim.copy()
    agora_dt=pd.Timestamp(agora).to_datetime64()
    fimcalc=fimcalc.mask(aberto, agora_dt)
    horas=(fimcalc-ini).dt.total_seconds()/3600
    sla=12 if tipo=="ITR" else 24
    valid=(~aberto)|(horas>=sla)
    out=pd.DataFrame({"inicio":ini,"fim":fim,"horas":horas,"aberto":aberto})
    return out[valid & ini.notna() & horas.notna() & (horas>=0)].copy()

def media_periodo(tipo, periodo):
    b=base_media(tipo)
    if b.empty:return None
    ini=b["inicio"]; hoje=agora.normalize()
    if periodo=="DIA": m=ini.dt.normalize().eq(hoje)
    elif periodo=="MES": m=(ini.dt.year==agora.year)&(ini.dt.month==agora.month)
    else:
        iso=ini.dt.isocalendar(); ino=agora.isocalendar()
        m=(iso.week==ino.week)&(iso.year==ino.year)
    x=b.loc[m,"horas"]
    return float(x.mean()) if len(x) else None

def resumo(tipo):
    b=base_media(tipo)
    sla=12 if tipo=="ITR" else 24
    hoje=agora.normalize()
    seg=hoje-pd.Timedelta(days=hoje.weekday())
    sems=[]
    semanal=[]
    for k in [2,1,0]:
        s=seg-pd.Timedelta(days=7*k); f=s+pd.Timedelta(days=7)
        x=b[(b["inicio"]>=s)&(b["inicio"]<f)]["horas"]
        v=float(x.mean()) if len(x) else None
        lab=f"S{s.isocalendar().week:02d}"
        sems.append((lab,hhmm(v))); semanal.append({"SEMANA":lab,"MEDIA_H":v})
    meses=[]; cur=pd.Period(agora,freq="M")
    for k in [2,1,0]:
        p=cur-k
        x=b[b["inicio"].dt.to_period("M").eq(p)]["horas"]
        v=float(x.mean()) if len(x) else None
        meses.append((p.strftime("%b/%y").replace("Sep","Set").replace("Aug","Ago").replace("Jul","Jul"),hhmm(v)))
    bm=b[(b["inicio"].dt.year==agora.year)&(b["inicio"].dt.month==agora.month)].copy()
    if not bm.empty:
        bm["DIA_DT"]=bm["inicio"].dt.normalize()
        diaria=bm.groupby("DIA_DT")["horas"].mean().reset_index(name="MEDIA_H")
        diaria["DIA"]=diaria["DIA_DT"].dt.strftime("%d/%m")
    else: diaria=pd.DataFrame(columns=["DIA","MEDIA_H"])
    return sems,meses,pd.DataFrame(semanal),diaria,sla

def card_media(tipo):
    md=media_periodo(tipo,"DIA"); mm=media_periodo(tipo,"MES")
    sems,meses,semanal,diaria,sla=resumo(tipo)
    st.markdown(f"<div class='card-title'>⏱️ MÉDIA {tipo}</div>",unsafe_allow_html=True)
    st.markdown(f"<div class='card-center'>Hoje: <b>{hhmm(md)}</b> &nbsp;•&nbsp; Mês até hoje: <b>{hhmm(mm)}</b> &nbsp;•&nbsp; SLA: <b>{sla:02d}:00</b></div>",unsafe_allow_html=True)
    st.markdown("<div class='card-center' style='margin-top:8px'><b>Últimas 3 semanas</b><br>"+" &nbsp; | &nbsp; ".join(f"{a}: <b>{b}</b>" for a,b in sems)+"</div>",unsafe_allow_html=True)
    p=semanal.dropna()
    if not p.empty:
        ch=alt.Chart(p).mark_line(point=True).encode(x=alt.X("SEMANA:N",title=None,axis=alt.Axis(labelAngle=0)),y=alt.Y("MEDIA_H:Q",title=None,axis=None),tooltip=["SEMANA",alt.Tooltip("MEDIA_H:Q",format=".2f")]).properties(height=65)
        rule=alt.Chart(pd.DataFrame({"SLA":[sla]})).mark_rule(strokeDash=[4,3]).encode(y="SLA:Q")
        st.altair_chart(ch+rule,use_container_width=True)
    st.markdown("<div class='caption'>Média semanal por INÍCIO • abertas entram ao atingir o SLA</div>",unsafe_allow_html=True)
    st.markdown("<div class='card-center' style='margin-top:14px'><b>Últimos 3 meses</b><br>"+" &nbsp; | &nbsp; ".join(f"{a}: <b>{b}</b>" for a,b in meses)+"</div>",unsafe_allow_html=True)
    if not diaria.empty:
        ch=alt.Chart(diaria).mark_line(point=True).encode(x=alt.X("DIA:N",title=None,axis=alt.Axis(labelAngle=0,labelFontSize=9)),y=alt.Y("MEDIA_H:Q",title=None,axis=None),tooltip=["DIA",alt.Tooltip("MEDIA_H:Q",format=".2f")]).properties(height=75)
        rule=alt.Chart(pd.DataFrame({"SLA":[sla]})).mark_rule(strokeDash=[4,3]).encode(y="SLA:Q")
        st.altair_chart(ch+rule,use_container_width=True)
    st.markdown("<div class='caption'>Média diária do mês corrente • linha tracejada = SLA</div>",unsafe_allow_html=True)

st.markdown("<div class='mon-section'><div class='mon-section-title'>2. DESEMPENHO</div><div class='mon-section-sub'>Indicadores principais da oficina e evolução do SLA</div></div>",unsafe_allow_html=True)
c1,c2,c3=st.columns(3)
with c1:
    with st.container(border=True): card_media("ITR")
with c2:
    with st.container(border=True): card_media("REVISÃO")
with c3:
    with st.container(border=True):
        st.markdown("<div class='card-title'>📈 MTBF</div><div class='card-center'>Aguardando definição das regras</div>",unsafe_allow_html=True)

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
    qa=int(atual["desc_norm"].apply(lambda z:any(t in z for t in termos)).sum())
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
