"""Consulta independente do historico de manutencao da frota."""
import pandas as pd
import streamlit as st


def situacao_pit_stop(hist, pit, agora):
    """Conta oito dias desde o último Pit Stop, ITR ou revisão efetivamente iniciado."""
    lib, entrada = (pit['_lib'], pit['_entrada']) if pit is not None else (pd.NaT, pd.NaT)
    data = lib if pd.notna(lib) else entrada
    if pd.isna(data):
        data = pd.NaT
    # Corretivas e SOS não reiniciam o prazo de manutenção programada.
    # Uma programação futura sem entrada efetiva também não reinicia o prazo.
    paradas = pd.to_datetime(hist['parada'], errors='coerce').fillna(
        pd.to_datetime(hist['inicio'], errors='coerce'))
    liberacoes = pd.to_datetime(hist['fim'], errors='coerce')
    referencias = liberacoes.fillna(paradas)
    eventos = hist['evento'].fillna('').astype(str).str.upper().str.strip()
    programadas = (eventos.eq('ITR') | eventos.str.contains('REVIS', na=False)
                   | eventos.str.replace(r'[^A-Z0-9]', '', regex=True).str.contains('PITSTOP', na=False))
    validos = ~hist['excluida_asn'].fillna(False).astype(bool)
    realizadas = validos & programadas & paradas.le(agora) & referencias.le(agora)
    datas = referencias.loc[realizadas].dropna().tolist()
    if pd.notna(data) and data <= agora:
        datas.append(data)
    if not datas:
        return None, pd.NaT, False
    referencia = max(datas)
    dias = max(0, (agora.normalize() - referencia.normalize()).days)
    return dias, referencia, dias >= 8


def frotas_validas_recentes(df, agora):
    """Valida o GO por ITR recente e pelo menos seis OS nos últimos 60 dias."""
    datas = pd.to_datetime(df['parada'], errors='coerce').fillna(
        pd.to_datetime(df['inicio'], errors='coerce'))
    excluidas = df.get('excluida_asn_em', pd.Series(None, index=df.index)).notna()
    recentes = df.loc[~excluidas & datas.ge(agora.normalize() - pd.Timedelta(days=60))
                      & datas.le(agora)].copy()
    eventos = recentes['evento'].fillna('').astype(str).str.upper().str.strip()
    com_itr = set(recentes.loc[eventos.eq('ITR'), 'frota'].dropna())
    ids = recentes.get('os_id', pd.Series('', index=recentes.index)).fillna('').astype(str).str.strip()
    ids = ids.str.replace(r'\.0$', '', regex=True)
    identificadas = ids.ne('') & ~ids.str.lower().isin(['nan', 'none', 'nat', '<na>'])
    recentes['_os_validacao'] = ids
    com_os = recentes.loc[identificadas].drop_duplicates(['frota', '_os_validacao'])
    # Sem OS/ID, eliminar cópias do mesmo atendimento pelas informações disponíveis.
    campos = [c for c in ['frota', 'evento', 'parada', 'inicio', 'fim', 'descricao'] if c in recentes.columns]
    sem_os = recentes.loc[~identificadas].drop_duplicates(campos)
    atendimentos = pd.concat([com_os, sem_os], ignore_index=True)
    contagem = atendimentos.groupby('frota').size()
    return com_itr.intersection(contagem.loc[contagem.gt(5)].index)


def listar_frotas_atrasadas(df, agora):
    """Uma linha por frota, usando o mesmo prazo do card de Pit Stop."""
    linhas = []
    base = df.copy()
    base['excluida_asn'] = base.get('excluida_asn_em', pd.Series(None, index=base.index)).notna()
    frotas_validas = frotas_validas_recentes(base, agora)
    base = base.loc[base['frota'].isin(frotas_validas)]
    for frota, hist in base.groupby('frota', sort=False):
        if not str(frota).strip():
            continue
        dias, referencia, atrasado = situacao_pit_stop(hist, None, agora)
        if atrasado:
            linhas.append({'Frota': str(frota), 'Último serviço válido': referencia,
                           'Dias sem serviço': dias, 'Dias de atraso': dias - 7})
    colunas = ['Frota', 'Último serviço válido', 'Dias sem serviço', 'Dias de atraso']
    return pd.DataFrame(linhas, columns=colunas).sort_values(
        ['Dias sem serviço', 'Frota'], ascending=[False, True], ignore_index=True)


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
    atrasadas = listar_frotas_atrasadas(df, agora)

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

        def intervalo_revisao(row):
            if row is None:
                return None
            evento = str(row.get('evento', '')).upper()
            if '60' in evento:
                return 60
            if '120' in evento:
                return 120
            if 'TRIMESTRAL' in evento:
                return 90
            return None

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
                    if pd.notna(data):
                        dias = max(0, (agora.normalize() - data.normalize()).days)
                        if intervalo is not None:
                            prox = data.normalize() + pd.Timedelta(days=intervalo)
                            sufixo = ' (previsão provisória)' if pd.isna(lib) else ''
                            st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **{prox.strftime('%d/%m/%Y')}**{sufixo}")
                        else:
                            st.markdown(f"Há **{dias} dia(s)** • Próxima por tempo: **intervalo não identificado**")
                    if pd.isna(lib):
                        st.caption('Último atendimento • liberação da OS ainda não confirmada.')
                        if pd.notna(entrada):
                            st.caption(f"Início: {entrada.strftime('%d/%m/%Y %H:%M')}")
                        st.caption(f"Status: {row.get('status', 'Não informado')}")
                    else:
                        st.caption(f"Liberação da OS: {lib.strftime('%d/%m/%Y %H:%M')}")

        card_preventiva(c1, 'ÚLTIMA ITR', r_itr, '🔵', 20)
        card_preventiva(c2, 'ÚLTIMA REVISÃO', r_rev, '🟣', intervalo_revisao(r_rev))
        with c3:
            with st.container(border=True):
                dias_pit, referencia_pit, pit_atrasado = (
                    situacao_pit_stop(hist, r_pit, agora)
                )
                st.markdown('**:red[🔴 ÚLTIMO PIT STOP]**' if pit_atrasado else '**🟢 ÚLTIMO PIT STOP**')
                if r_pit is None:
                    st.markdown('**Não encontrado**')
                    st.caption('Nenhum Pit Stop no histórico sincronizado.')
                    if dias_pit is not None:
                        st.caption(f"Última parada programada: {referencia_pit.strftime('%d/%m/%Y')} • há {dias_pit} dia(s)")
                    if pit_atrasado:
                        st.error(f'Pit Stop atrasado — {dias_pit} dias sem Pit Stop, ITR ou revisão.')
                else:
                    lib, entrada = r_pit['_lib'], r_pit['_entrada']
                    data = lib if pd.notna(lib) else entrada
                    st.caption(f"OS/ID: {r_pit['os_id']}")
                    st.markdown(f"### {data.strftime('%d/%m/%Y') if pd.notna(data) else 'Data não informada'}")
                    st.caption(f"Liberação: {lib.strftime('%d/%m/%Y %H:%M') if pd.notna(lib) else 'Ainda não confirmada'}")
                    if dias_pit is not None:
                        st.caption(f"Última parada programada/Pit Stop: {referencia_pit.strftime('%d/%m/%Y')} • há {dias_pit} dia(s)")
                    if pit_atrasado:
                        st.error(f'Pit Stop atrasado — {dias_pit} dias sem Pit Stop, ITR ou revisão.')
                    elif dias_pit is not None:
                        st.caption('Dentro do prazo: alerta a partir do 8º dia sem Pit Stop, ITR ou revisão.')
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
        q1, q2, q3 = st.columns([5, 2, 3])
        with q1:
            frota_q = st.text_input('Frota', placeholder='Ex.: 13725', label_visibility='collapsed')
        with q2:
            pesquisar = st.button('🔎 Pesquisar', use_container_width=True)
        with q3:
            if st.button(f'Pit Stop atrasado · {len(atrasadas)}', use_container_width=True):
                st.session_state['historico_mostrar_atrasadas'] = not st.session_state.get('historico_mostrar_atrasadas', False)
        if st.session_state.get('historico_mostrar_atrasadas', False):
            if atrasadas.empty:
                st.success('Nenhuma frota com Pit Stop atrasado na base sincronizada.')
            else:
                st.caption('Frotas com ITR e pelo menos 6 atendimentos nos últimos 60 dias • Maior tempo primeiro.')
                st.caption('Selecione uma frota para abrir o histórico.')
                tabela = atrasadas.copy()
                tabela['Último serviço válido'] = tabela['Último serviço válido'].dt.strftime('%d/%m/%Y')

                def selecionar_atrasada():
                    estado = st.session_state.get('historico_tabela_atrasadas', {})
                    selecionadas = estado.get('selection', {}).get('rows', [])
                    if selecionadas and selecionadas[0] < len(atrasadas):
                        st.session_state['historico_frota_selecionada'] = atrasadas.iloc[selecionadas[0]]['Frota']

                st.dataframe(tabela, hide_index=True, use_container_width=True,
                             key='historico_tabela_atrasadas', on_select=selecionar_atrasada,
                             selection_mode='single-row', height=min(420, 38 + 35 * len(tabela)))
        selecionada = st.session_state.pop('historico_frota_selecionada', None)
        if pesquisar and frota_q.strip():
            modal_historico_frota(norm_frota(frota_q))
        elif selecionada:
            modal_historico_frota(selecionada)

    render_consulta_rapida()
    st.markdown(
        """
        <div style="margin-top:48px;padding:18px 0 12px;border-top:1px solid #e5e7eb;
                    text-align:center;color:#667085;font-size:12px;">
            Desenvolvido por Evandro Junior
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()
