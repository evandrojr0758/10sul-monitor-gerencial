"""Consulta independente do historico de manutencao da frota."""
import pandas as pd
import streamlit as st


def render_consulta(carregar, converter_hora, norm_frota, _inconsistencias_asn):
    try:
        df = carregar().copy()
    except Exception:
        st.error('Não foi possível carregar o histórico. Tente novamente.')
        st.stop()
    if df.empty:
        st.warning('A base do monitor está vazia. Confira a sincronização da Lista ASN.')
        st.stop()
    for c in ['parada', 'inicio', 'fim', 'fim_asn', 'fim_liberacao_10sul', 'previsao_liberacao_10sul']:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c].map(converter_hora), errors='coerce')
        else:
            df[c] = pd.NaT
    for c in ['os_id', 'frota', 'evento', 'status', 'descricao', 'modal', 'unidade']:
        if c not in df.columns:
            df[c] = ''
    df['frota'] = df['frota'].apply(norm_frota)
    mascara_excluidas = df.get('excluida_asn_em', pd.Series(None, index=df.index)).notna()
    os_excluidas = df.loc[mascara_excluidas].copy()
    df = df.loc[~mascara_excluidas].copy()
    inconsistencias_asn = _inconsistencias_asn(df)
    agora = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None)

    @st.dialog('🔎 Histórico da frota', width='large')
    def modal_historico_frota(fq):
        hist = pd.concat([df[df['frota'].eq(fq)], os_excluidas[os_excluidas['frota'].eq(fq)]], ignore_index=True)
        hist = hist.sort_values('inicio', ascending=False).reset_index(drop=True)
        hist['excluida_asn'] = hist.get('excluida_asn_em', pd.Series(None, index=hist.index)).notna()
        st.markdown(f'### Frota {fq}')
        if hist.empty:
            st.warning('Frota não encontrada na base sincronizada.')
            return
        hev = hist['evento'].fillna('').astype(str).str.upper().str.strip()
        validos = ~hist['excluida_asn']
        itr = hist[hev.eq('ITR') & validos].copy()
        rev = hist[hev.str.contains('REVIS', na=False) & validos].copy()
        pit = hist[hev.str.replace(r'[^A-Z0-9]', '', regex=True).str.contains('PITSTOP', na=False) & validos].copy()

        def ultimo(x):
            if x.empty:
                return None
            x = x.copy()
            x['_lib'] = pd.to_datetime(x['fim'], errors='coerce')
            x['_entrada'] = pd.to_datetime(x['inicio'], errors='coerce').fillna(pd.to_datetime(x['parada'], errors='coerce'))
            x['_ref'] = x['_entrada'].fillna(x['_lib'])
            return x.sort_values(['_ref', '_lib'], ascending=False, na_position='last').iloc[0]

        r_itr, r_rev, r_pit = ultimo(itr), ultimo(rev), ultimo(pit)
        c1, c2, c3 = st.columns(3)

        def card_preventiva(col, titulo, row, cor, intervalo):
            with col:
                with st.container(border=True):
                    st.markdown(f'**{cor} {titulo}**')
                    if row is None:
                        st.markdown('**Não encontrada**')
                        st.caption('Nenhum atendimento no histórico sincronizado.')
                        return
                    st.caption(f"OS/ID: {row['os_id']}")
                    lib, entrada = row['_lib'], row['_entrada']
                    data = lib if pd.notna(lib) else entrada
                    st.markdown(f"### {data.strftime('%d/%m/%Y') if pd.notna(data) else 'Data não informada'}")
                    if pd.isna(lib):
                        st.caption('Último atendimento • liberação da OS ainda não confirmada.')
                        if pd.notna(entrada):
                            st.caption(f"Início: {entrada.strftime('%d/%m/%Y %H:%M')}")
                        st.caption(f"Status: {row.get('status', 'Não informado')}")
                    else:
                        dias = max(0, (agora.normalize() - lib.normalize()).days)
                        prox = lib.normalize() + pd.Timedelta(days=intervalo)
                        st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **{prox.strftime('%d/%m/%Y')}**")
                        st.caption(f"Liberação da OS: {lib.strftime('%d/%m/%Y %H:%M')}")

        card_preventiva(c1, 'ÚLTIMA ITR', r_itr, '🔵', 20)
        card_preventiva(c2, 'ÚLTIMA REVISÃO', r_rev, '🟣', 120)
        with c3:
            with st.container(border=True):
                st.markdown('**🟢 ÚLTIMO PIT STOP**')
                if r_pit is None:
                    st.markdown('**Não encontrado**')
                    st.caption('Nenhum Pit Stop no histórico sincronizado.')
                else:
                    lib, entrada = r_pit['_lib'], r_pit['_entrada']
                    data = lib if pd.notna(lib) else entrada
                    st.caption(f"OS/ID: {r_pit['os_id']}")
                    st.markdown(f"### {data.strftime('%d/%m/%Y') if pd.notna(data) else 'Data não informada'}")
                    st.caption(f"Liberação: {lib.strftime('%d/%m/%Y %H:%M') if pd.notna(lib) else 'Ainda não confirmada'}")
                    with st.expander('Ver atendimento'):
                        st.write(f"OS/ID: {r_pit['os_id']}")
                        st.write(f"Evento: {r_pit['evento']}")
                        st.write(f"Descrição: {r_pit['descricao']}")
                        st.write(f"Status: {r_pit['status']}")
                        st.write(f"Início: {entrada.strftime('%d/%m/%Y %H:%M') if pd.notna(entrada) else 'Não informado'}")
                        st.write(f"Liberação: {lib.strftime('%d/%m/%Y %H:%M') if pd.notna(lib) else 'Não informada'}")

        conferir = inconsistencias_asn.loc[inconsistencias_asn['FROTA'].eq(fq)]
        if not conferir.empty:
            with st.expander(f'⚠️ Conferência ASN ({len(conferir)} registro(s))'):
                st.warning('OS pendente não confirma atendimento ainda em andamento.')
                st.dataframe(conferir, hide_index=True, use_container_width=True)
        st.markdown('#### Histórico de atendimentos')
        show = hist[['os_id', 'evento', 'descricao', 'parada', 'inicio', 'fim', 'status']].copy()
        show.columns = ['OS/ID', 'EVENTO', 'DESCRIÇÃO', 'PARADA', 'INÍCIO', 'FIM', 'STATUS']
        show.loc[hist['excluida_asn'], 'STATUS'] = 'Excluída na Lista ASN'
        estilos = show.style.apply(lambda row: ['text-decoration:line-through;color:#6b7280' if hist.loc[row.name, 'excluida_asn'] else '' for _ in row], axis=1)
        st.dataframe(estilos, use_container_width=True, hide_index=True)

    @st.fragment
    def render_consulta_rapida():
        q1, q2 = st.columns([5, 1])
        with q1:
            frota_q = st.text_input('Frota', placeholder='Ex.: 13725', label_visibility='collapsed')
        with q2:
            pesquisar = st.button('🔎 Pesquisar', use_container_width=True)
        if pesquisar and frota_q.strip():
            modal_historico_frota(norm_frota(frota_q))

    render_consulta_rapida()
    st.stop()
