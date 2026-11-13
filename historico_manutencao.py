"""Acesso independente à mesma consulta rápida de frota do Monitor Web."""
import pandas as pd
import streamlit as st


def render_consulta(carregar, converter_hora, norm_frota, _inconsistencias_asn):
    st.markdown("<div class='mon-title'>🔎 Consulta rápida de frota</div>", unsafe_allow_html=True)
    st.markdown("<div class='mon-sub'>Desenvolvido por Evandro Junior</div>", unsafe_allow_html=True)
    try:
        df = carregar().copy()
    except Exception:
        st.error("Não foi possível carregar o histórico. Tente novamente.")
        st.stop()
    if df.empty:
        st.warning("A base do monitor está vazia. Confira a sincronização da Lista ASN no Power Automate.")
        st.stop()
    for c in ["parada", "inicio", "fim", "fim_asn", "fim_liberacao_10sul", "previsao_liberacao_10sul"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c].map(converter_hora), errors="coerce")
    for c in ["os_id", "frota", "evento", "status", "descricao", "modal", "unidade"]:
        if c not in df.columns:
            df[c] = ""
    df["frota"] = df["frota"].apply(norm_frota)
    mascara_excluidas = df.get("excluida_asn_em", pd.Series(None, index=df.index, dtype=object)).notna()
    os_excluidas = df.loc[mascara_excluidas].copy()
    df = df.loc[~mascara_excluidas].copy()
    inconsistencias_asn = _inconsistencias_asn(df)
    agora = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None)

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
    st.stop()
