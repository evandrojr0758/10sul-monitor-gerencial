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
        elif c in ("parada", "inicio", "fim"):
            df[c] = pd.NaT
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
        hist = pd.concat([df[df["frota"].eq(fq)], os_excluidas[os_excluidas["frota"].eq(fq)]], ignore_index=True).sort_values("inicio", ascending=False)
        hist["excluida_asn"] = hist.get("excluida_asn_em", pd.Series(None, index=hist.index, dtype=object)).notna()
        st.markdown(f"### Frota {fq}")
        conferir = inconsistencias_asn.loc[inconsistencias_asn["FROTA"].eq(fq)]
        if not conferir.empty:
            st.warning("Há registros desta frota que precisam de conferência na ASN. OS pendente não confirma atendimento ainda em andamento.")
            st.dataframe(conferir, hide_index=True, use_container_width=True)
        if hist.empty:
            st.warning("Frota não encontrada na base sincronizada.")
            return

        hev = hist["evento"].fillna("").astype(str).str.upper().str.strip()
        ativos = ~hist["excluida_asn"]
        itr = hist[hev.eq("ITR") & ativos].copy()
        rev = hist[hev.str.contains("REVIS", na=False) & ativos].copy()
        pit = hist[hev.str.replace(r"[\s_-]+", "", regex=True).str.contains("PITSTOP", regex=False) & ativos].copy()

        def ultimo_atendimento(x):
            if x.empty:
                return None
            x = x.copy()
            x["_lib"] = pd.to_datetime(x["fim"], errors="coerce")
            x["_entrada"] = pd.to_datetime(x["inicio"], errors="coerce").fillna(pd.to_datetime(x["parada"], errors="coerce"))
            x["_ref"] = x["_entrada"].fillna(x["_lib"])
            x = x.sort_values(["_ref", "_lib"], ascending=False, na_position="last")
            return x.iloc[0]

        r_itr = ultimo_atendimento(itr)
        r_rev = ultimo_atendimento(rev)
        r_pit = ultimo_atendimento(pit)

        def texto(valor):
            return "Não informado" if pd.isna(valor) or not str(valor).strip() else str(valor)

        def preventiva_card(col, titulo, row, cor, intervalo):
            with col:
                with st.container(border=True):
                    st.markdown(f"<div style='font-size:13px;font-weight:800;color:#667085'>{cor} {titulo}</div>", unsafe_allow_html=True)
                    if row is None:
                        st.markdown("<div style='font-size:24px;font-weight:900'>Não encontrada</div>", unsafe_allow_html=True)
                        st.caption("Nenhum atendimento desse evento na base sincronizada.")
                        return
                    st.caption(f"OS/ID: {texto(row['os_id'])}")
                    lib = row["_lib"]
                    entrada = row["_entrada"]
                    if pd.isna(lib):
                        data = entrada.strftime("%d/%m/%Y") if pd.notna(entrada) else "Data não informada"
                        st.markdown(f"<div style='font-size:27px;font-weight:900'>{data}</div>", unsafe_allow_html=True)
                        st.caption("Último atendimento • liberação da OS ainda não confirmada.")
                        if pd.notna(entrada):
                            st.caption(f"Início: {entrada.strftime('%d/%m/%Y %H:%M')}")
                        st.caption(f"Status: {texto(row.get('status'))}")
                        return
                    dias = max(0, (agora.normalize() - lib.normalize()).days)
                    prox = lib.normalize() + pd.Timedelta(days=intervalo)
                    st.markdown(f"<div style='font-size:27px;font-weight:900'>{lib.strftime('%d/%m/%Y')}</div>", unsafe_allow_html=True)
                    st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **{prox.strftime('%d/%m/%Y')}**")
                    st.caption(f"Liberação da OS: {lib.strftime('%d/%m/%Y %H:%M')}")

        def pitstop_card(col, row):
            with col:
                with st.container(border=True):
                    st.markdown("<div style='font-size:13px;font-weight:800;color:#667085'>🟢 ÚLTIMO PIT STOP</div>", unsafe_allow_html=True)
