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
                    if row is None:
                        st.markdown("<div style='font-size:22px;font-weight:900'>Não encontrado</div>", unsafe_allow_html=True)
                        st.caption("Nenhum Pit Stop registrado na base sincronizada.")
                        return
                    st.caption(f"OS/ID: {texto(row['os_id'])}")
                    entrada, lib = row["_entrada"], row["_lib"]
                    referencia = lib if pd.notna(lib) else entrada
                    data = referencia.strftime("%d/%m/%Y") if pd.notna(referencia) else "Data não informada"
                    st.markdown(f"<div style='font-size:27px;font-weight:900'>{data}</div>", unsafe_allow_html=True)
                    if pd.notna(lib):
                        dias = max(0, (agora.normalize() - lib.normalize()).days)
                        st.markdown(f"Há **{dias} dia(s)** • Liberação às **{lib.strftime('%H:%M')}**")
                    else:
                        st.caption("Liberação da OS ainda não confirmada.")
                    with st.expander("Ver atendimento"):
                        st.write(f"**OS/ID:** {texto(row['os_id'])}")
                        st.write(f"**Evento:** {texto(row['evento'])}")
                        st.write(f"**Descrição:** {texto(row['descricao'])}")
                        st.write(f"**Início:** {entrada.strftime('%d/%m/%Y %H:%M') if pd.notna(entrada) else 'Não informado'}")
                        st.write(f"**Liberação:** {lib.strftime('%d/%m/%Y %H:%M') if pd.notna(lib) else 'Não confirmada'}")
                        st.write(f"**Status:** {texto(row.get('status'))}")

        c1, c2, c3 = st.columns(3)
        preventiva_card(c1, "ÚLTIMA ITR", r_itr, "🔵", 20)
        preventiva_card(c2, "ÚLTIMA REVISÃO", r_rev, "🟣", 120)
        pitstop_card(c3, r_pit)

        st.markdown("#### Histórico de atendimentos")
        show = hist[["os_id", "evento", "descricao", "parada", "inicio", "fim", "status"]].copy()
        show.columns = ["OS/ID", "EVENTO", "DESCRIÇÃO", "PARADA", "INÍCIO", "FIM", "STATUS"]
        show.loc[hist["excluida_asn"], "STATUS"] = "Excluída na Lista ASN"
        estilos = show.style.apply(lambda row: ["text-decoration:line-through;color:#6b7280" if hist.loc[row.name, "excluida_asn"] else "" for _ in row], axis=1)
        st.dataframe(estilos, use_container_width=True, hide_index=True)

    @st.fragment
    def render_consulta_rapida():
        q1, q2 = st.columns([5, 1])
        with q1:
            frota_q = st.text_input("Frota", placeholder="Ex.: 13725", label_visibility="collapsed")
        with q2:
            pesquisar = st.button("🔎 Pesquisar", use_container_width=True)
        if pesquisar and frota_q.strip():
            modal_historico_frota(norm_frota(frota_q))

    render_consulta_rapida()
    st.stop()
