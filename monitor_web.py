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
            if not atend.empty and all(c in atend.columns for c in ["os_id","frota","fim"]):
                def chave_os(v):
                    return re.sub(r"\\.0$","",str(v).strip())
                atend=atend.copy()
                atend["_OS"]=atend["os_id"].apply(chave_os)
                atend["_FROTA"]=atend["frota"].apply(norm_frota)
                atend["_FIM"]=pd.to_datetime(atend["fim"],errors="coerce")
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
        url=f"{SUPABASE_URL}/storage/v1/object/evidencias-desvios/{path}"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}
        r=requests.get(url,headers=h,timeout=45)
        return (r.content,r.headers.get("content-type","")) if r.ok else (None,"")
    except Exception:return None,""

def atualizar_atividade_laudo_web(atividade_id, dados):
    """Atualiza uma atividade já conferida na tabela public.laudos_monitor."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False,"Supabase não configurado."
    aid=str(atividade_id or "").strip()
    if not aid:
        return False,"Atividade sem identificador; não é seguro editar."
    try:
        url=f"{SUPABASE_URL}/rest/v1/laudos_monitor"
        h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}","Content-Type":"application/json","Prefer":"return=minimal"}
        r=requests.patch(url,headers=h,params={"atividade_id":f"eq.{aid}"},json=dados,timeout=45)
        if not r.ok:return False,f"Supabase HTTP {r.status_code}: {r.text[:500]}"
        carregar_laudos_manuais_web.clear()
        return True,"Alteração salva."
    except Exception as e:return False,str(e)

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
    liberacoes=pd.DataFrame({
        "FIM INFORMADO — 10 SUL":pd.to_datetime(det["FIM_MANUTENCAO"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("Não informado"),
        "FIM CLIENTE":pd.to_datetime(det["FIM_CLIENTE"],errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("OS ainda sem baixa"),
    }).drop_duplicates()
    st.dataframe(liberacoes,hide_index=True,use_container_width=True)


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
        f"<span style='font-size:11px;font-weight:800;color:#667085'>MÉDIA DO DIA ANTERIOR</span>"
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


def apurar_tempos_justificados(manut,piv,justificativas):
    base=manut.merge(piv,on=["CHAVE_OS","FROTA"],how="left").copy()
    base["APONTADO"]=base[["ITR","CNP","GM","OUTROS"]].fillna(0).sum(axis=1)
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


def salvar_justificativa_laudo(osid,frota,minutos,motivo,observacao,responsavel):
    import uuid
    registro={"versao":1,"id":uuid.uuid4().hex,"os_id":_chave_vinculo_laudo(osid),
              "frota":_chave_vinculo_laudo(frota),"minutos":int(minutos),"motivo":motivo,
              "observacao":observacao.strip(),"responsavel":responsavel.strip(),
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
            st.markdown("**Justificativas registradas**")
            st.dataframe(hist[["os_id","frota","TEMPO","motivo","observacao","responsavel","registrado_em"]].rename(columns={"os_id":"OS/ID","frota":"FROTA","motivo":"MOTIVO","observacao":"OBSERVAÇÃO","responsavel":"RESPONSÁVEL INFORMADO","registrado_em":"REGISTRO"}),hide_index=True,use_container_width=True)
    if consulta: return
    op=base[base["PENDENTE"]>0].copy()
    op=op[[(_chave_vinculo_laudo(o),_chave_vinculo_laudo(f)) in os_validas for o,f in zip(op.CHAVE_OS,op.FROTA)]] if len(op) else op
    if op.empty:
        st.info("Nenhuma OS com saldo e identificador válido para justificar.")
        return
    pos=st.selectbox("Manutenção",range(len(op)),format_func=lambda i:f"Frota {op.iloc[i]['FROTA']} · OS {op.iloc[i]['CHAVE_OS']} · Saldo {hhmm(op.iloc[i]['PENDENTE'])}")
    row=op.iloc[pos]
    with st.form("registrar_justificativa_tempo"):
        tempo=st.text_input("Tempo a justificar (HH:MM)",value=hhmm(row["PENDENTE"]))
        motivo=st.selectbox("Motivo",["Aguardando peça","Aguardando liberação do cliente","Intervalo","Falta de equipe","Outros"])
        obs=st.text_area("Observação")
        nome=st.text_input("Responsável pelo registro")
        gravar=st.form_submit_button("Salvar justificativa",type="primary")
    if gravar:
        match=re.fullmatch(r"(\d+):([0-5]\d)",tempo.strip())
        if not match or not nome.strip() or (motivo=="Outros" and not obs.strip()):
            st.error("Informe o tempo em HH:MM, o responsável e a observação quando o motivo for Outros.")
            return
        minutos=int(match[1])*60+int(match[2])
        try:
            carregar_justificativas_laudos.clear()
            atual=apurar_tempos_justificados(manut,piv,carregar_justificativas_laudos())
            saldo=atual.loc[atual.CHAVE_OS.eq(row.CHAVE_OS)&atual.FROTA.eq(row.FROTA),"PENDENTE"].iloc[0]
            if minutos<=0 or minutos>int(round(saldo*60)):
                st.error("O tempo deve ser maior que zero e não pode ultrapassar o saldo da OS.")
                return
            salvar_justificativa_laudo(row.CHAVE_OS,row.FROTA,minutos,motivo,obs,nome)
            st.session_state["justificativa_salva"]=True
            st.rerun()
        except Exception:
            st.error("Não foi possível salvar. Confira o acesso de gravação ao armazenamento e consulte o histórico antes de tentar novamente.")



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
    piv=x.pivot_table(index=["CHAVE_OS","FROTA"],columns="CLASSIFICACAO",values="HORAS",aggfunc="sum",fill_value=0).reset_index()
    for cc in ["ITR","CNP","GM","OUTROS"]:
        if cc not in piv.columns:piv[cc]=0.0
    med_itr=piv.loc[piv["ITR"]>0,"ITR"].mean(); med_cnp=piv.loc[piv["CNP"]>0,"CNP"].mean()
    apont=piv[["ITR","CNP","GM","OUTROS"]].sum(axis=1).sum(); hman=manut["H_MANUT"].sum()
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
        if st.button(f"🔴 Tempo sem justificativa\n\n{hhmm(pendente) if not erro_justificativas else '--:--'}\n\nJustificar tempo ›",key="rg_justificar_tempo",use_container_width=True,disabled=erro_justificativas):
            modal_justificativas_laudos(manut,piv,os_validas)
    with cjust:
        if st.button(f"🔵 Tempo justificado\n\n{hhmm(justificado) if not erro_justificativas else '--:--'}\n\nConsultar justificativas ›",key="rg_consultar_justificativas",use_container_width=True,disabled=erro_justificativas):
            modal_justificativas_laudos(manut,piv,os_validas,consulta=True)
    st.caption("Cards de tempo: média por manutenção. Justificativas não alteram o tempo total nem os apontamentos de ITR/CNP.")
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
            top=manut.sort_values("H_MANUT",ascending=False).head(10).copy(); top["TEMPO TOTAL"]=top["H_MANUT"].apply(hhmm); top["INÍCIO"]=top["INICIO"].dt.strftime("%d/%m %H:%M"); top["FIM"]=top["FIM"].dt.strftime("%d/%m %H:%M")
            st.dataframe(top[["FROTA","INÍCIO","FIM","TEMPO TOTAL"]],hide_index=True,use_container_width=True)
    st.markdown("**Detalhamento dos laudos do período**")
    det=x[["FROTA","OS_ID","COMPARTIMENTO","ATIVIDADE","CLASSIFICACAO","EXECUTANTE","HORAS"]].copy(); det["TEMPO"]=det["HORAS"].apply(hhmm); det=det.rename(columns={"OS_ID":"OS/ID","COMPARTIMENTO":"COMP.","CLASSIFICACAO":"TIPO"})
    st.dataframe(det[["FROTA","OS/ID","COMP.","ATIVIDADE","TIPO","EXECUTANTE","TEMPO"]],hide_index=True,use_container_width=True,height=330)


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

render_embasamento_contratual()

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

with st.expander("📋 ITR SEM VÍNCULO COM LAUDO", expanded=True):
    render_itr_sem_laudo()

with st.expander("📊 RELATÓRIO GERENCIAL — LAUDOS", expanded=False):
    render_relatorio_gerencial_laudos()

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


