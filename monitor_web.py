import os, requests, pandas as pd, streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title='Monitor Gerencial 10 Sul', page_icon='📺', layout='wide')

def sec(n):
    try:return str(st.secrets[n]).strip()
    except:return os.getenv(n,'').strip()
URL=sec('SUPABASE_URL').rstrip('/'); KEY=sec('SUPABASE_KEY')
HEAD={'apikey':KEY,'Authorization':f'Bearer {KEY}'}
@st.cache_data(ttl=60)
def carregar():
    r=requests.get(f'{URL}/rest/v1/monitor_atendimentos?select=*&order=inicio.desc',headers=HEAD,timeout=30); r.raise_for_status(); return pd.DataFrame(r.json())

def hhmm(h):
    if pd.isna(h): return '—'
    h=max(0,float(h)); return f'{int(h):02d}:{int(round((h-int(h))*60))%60:02d}'
def norm_ev(x):
    s=str(x).upper()
    if 'ITR' in s:return 'ITR'
    if 'REVIS' in s:return 'REVISÃO'
    if 'SOS' in s:return 'SOS'
    if 'CORRET' in s or 'CNP' in s:return 'CNP'
    return s.strip()

st.markdown('''<style>
.block-container{padding-top:1.2rem;max-width:1500px}.box{border:1px solid #dce3ea;border-radius:12px;padding:16px;background:white}.title{font-size:26px;font-weight:800}.section{border-left:5px solid #2589ff;background:#f1f7ff;border-radius:10px;padding:12px 16px;margin:18px 0 12px}.section b{font-size:18px}.small{color:#6b7280;font-size:12px}
</style>''',unsafe_allow_html=True)
st.markdown("<div class='title'>📺 Monitor Gerencial — 10 Sul</div>",unsafe_allow_html=True)
try: df=carregar()
except Exception as e: st.error(f'Não foi possível carregar o monitor: {e}'); st.stop()
if df.empty: st.warning('A base do Monitor Web ainda está vazia. Abra o sistema principal para realizar a primeira sincronização.'); st.stop()
for c in ['inicio','fim','parada']: df[c]=pd.to_datetime(df.get(c),errors='coerce')
df['EV']=df['evento'].map(norm_ev)
agora=pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None)
df['HORAS']=((df['fim'].fillna(agora)-df['inicio']).dt.total_seconds()/3600).clip(lower=0)
df['ABERTA']=df['fim'].isna() | ~df['status'].astype(str).str.upper().str.contains('LIBER')
df['SLA']=df['EV'].map({'ITR':12,'REVISÃO':24})
df['ACIMA']=df['ABERTA'] & df['SLA'].notna() & (df['HORAS']>=df['SLA'])
st.caption(f'Tudo que está publicado pelo sistema principal • Atualizado em {agora:%d/%m/%Y %H:%M}')

st.markdown("<div class='section'><b>1. OFICINA AGORA</b><div class='small'>Situação em tempo real e pontos que exigem atenção</div></div>",unsafe_allow_html=True)
a=df[df.ABERTA]
vals=[('🔧 EM MANUTENÇÃO',len(a)),('🚨 CNP ABERTAS',len(a[a.EV=='CNP'])),('🆘 SOS ABERTOS',len(a[a.EV=='SOS'])),('🔧 ITR ABERTAS',len(a[a.EV=='ITR'])),('🛠️ REVISÕES',len(a[a.EV=='REVISÃO'])),('⏱️ ACIMA SLA',int(a.ACIMA.sum()))]
cols=st.columns(len(vals))
for c,(lab,v) in zip(cols,vals): c.metric(lab,v)

st.markdown("<div class='section'><b>2. DESEMPENHO</b><div class='small'>Indicadores de ITR e Revisão</div></div>",unsafe_allow_html=True)
cols=st.columns(2)
for col,ev,sla in zip(cols,['ITR','REVISÃO'],[12,24]):
    x=df[df.EV==ev].copy(); mes=x[x.inicio.dt.to_period('M')==agora.to_period('M')]
    media=mes.HORAS.mean()
    with col:
        st.markdown(f'### ⏱️ MÉDIA {ev}')
        st.metric('Mês até hoje',hhmm(media),f'SLA {sla:02d}:00',delta_color='off')
        y=x.copy(); y['SEMANA']=y.inicio.dt.isocalendar().week.astype('Int64'); y=y[y.inicio>=agora-pd.Timedelta(days=35)].groupby('SEMANA',as_index=False).HORAS.mean()
        if not y.empty: st.line_chart(y.set_index('SEMANA')['HORAS'],height=180)

st.markdown("<div class='section'><b>3. MAIORES TEMPOS EM MANUTENÇÃO</b><div class='small'>Top 3 por evento entre as OS abertas</div></div>",unsafe_allow_html=True)
cols=st.columns(4)
for col,ev in zip(cols,['CNP','ITR','REVISÃO','SOS']):
    with col:
        st.markdown(f'**🚨 {ev} — MAIORES TEMPOS**')
        top=a[a.EV==ev].nlargest(3,'HORAS')
        if top.empty: st.caption('Sem OS abertas.')
        for i,(_,r) in enumerate(top.iterrows(),1): st.write(f"**{i}º FROTA {r['frota']}** — {hhmm(r.HORAS)}")

st.markdown("<div class='section'><b>4. ALERTAS & HUNT</b><div class='small'>Corretivas não programadas e inteligência da operação</div></div>",unsafe_allow_html=True)
cnp=df[df.EV=='CNP'].copy(); mes0=agora.to_period('M'); mes1=(agora-pd.offsets.MonthBegin()).to_period('M')
cm=cnp[cnp.inicio.dt.to_period('M')==mes0]; ca=cnp[cnp.inicio.dt.to_period('M')==mes1]
c1,c2,c3=st.columns([1,1,2]); c1.metric('CNP no mês',len(cm)); c2.metric('Mês anterior',len(ca))
with c3:
    tmp=cnp[cnp.inicio>=agora-pd.Timedelta(days=56)].copy(); tmp['SEMANA']=tmp.inicio.dt.isocalendar().week.astype('Int64'); g=tmp.groupby('SEMANA').size()
    if not g.empty: st.line_chart(g,height=180)

st.markdown('### 👥 Frotas reincidentes — últimos 30 dias')
r=cnp[cnp.inicio>=agora-pd.Timedelta(days=30)].groupby('frota').agg(**{'Qtde. CNP':('os_id','count'),'Última ocorrência':('inicio','max')}).sort_values('Qtde. CNP',ascending=False).head(10).reset_index()
if not r.empty: st.dataframe(r,use_container_width=True,hide_index=True)

st.markdown('### 🔎 Consulta rápida de frota')
q=st.text_input('Frota',placeholder='Ex.: 13725',label_visibility='collapsed')
if q:
    z=df[df.frota.astype(str).str.contains(q.strip(),case=False,na=False)].copy()
    st.dataframe(z[['frota','os_id','evento','inicio','fim','status','descricao','HORAS']].rename(columns={'HORAS':'Tempo (h)'}),use_container_width=True,hide_index=True)
