"""Consulta independente do historico de manutencao da frota."""
import unicodedata
from html import escape

import pandas as pd
import streamlit as st


CREDITO_HISTORICO = 'Desenvolvido por Evandro Junior - Analista de manutenção'
_ESTILO_CREDITO_DIALOGO = '''
<style>
.historico-credit-row { position: relative; }
.historico-credit {
    display: block;
    color: #344b5b;
    color: color-mix(in srgb, currentColor 85%, #52738a);
    font-size: .8125rem;
    line-height: 1.4;
}
@media (min-width: 52rem) {
    .historico-credit {
        position: absolute;
        inset-block-start: -3.625rem;
        inset-inline-end: 1.75rem;
    }
}
</style>
'''

# Relação oficial de frotas ativas informada em 17/11/2026.
FROTAS_ATIVAS = frozenset('''
13441 13449 13455 13461 13463 13477 13479 13481 13483 13485
13491 13505 13517 13519 13533 13539 13541 13543 13545 13555
13559 13561 13565 13569 13579 13585 13589 13591 13593 13595
13597 13599 13601 13605 13607 13609 13611 13613 13617 13623
13625 13627 13629 13631 13633 13635 13637 13639 13641 13643
13645 13647 13649 13651 13653 13655 13657 13659 13661 13663
13665 13667 13669 13671 13673 13675 13677 13679 13681 13683
13685 13687 13689 13693 13695 13697 13699 13701 13703 13705
13707 13709 13711 13715 13717 13719 13721 13723 13725 13727
13729 13731 13733 13737 13739 13741 13743 13745 13747 13749
13751 13761 13763 13765 13767 13769 13771 13773 13775 13777
13779 13781 13783 13785 13787 13789 13791 13793 13795 13797
13799 13801 13803 13805 13807 13809 13811 13813 13815 13817
13819 13821 13823 13825 13827 13829 13831 13833 13835 13837
13839 13841 13843 13845 13847 13849 13851 13853 13855 13857
13859 13863 13865 13867 13869 13871 13873 13875 13877 13879
13881 13883 13885 13887 13889 13891 13893 13895 23276 23298
23300 23338 23340 23341 23361 23362 23370 23373 23374 23384
23385 23386 13897 23365 23376 23354 13861
'''.split())


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


def listar_frotas_atrasadas(df, agora):
    """Uma linha por frota, usando o mesmo prazo do card de Pit Stop."""
    linhas = []
    base = df.copy()
    base['frota'] = (base['frota'].fillna('').astype(str).str.strip().str.upper()
                     .str.replace(r'^GO\s*', '', regex=True)
                     .str.replace(r'\.0$', '', regex=True))
    base['excluida_asn'] = base.get('excluida_asn_em', pd.Series(None, index=base.index)).notna()
    base = base.loc[base['frota'].isin(FROTAS_ATIVAS)]
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


def _preparar_historico(df, converter_hora, norm_frota):
    df = df.copy()
    for c in ['parada', 'inicio', 'fim', 'fim_asn', 'fim_liberacao_10sul', 'previsao_liberacao_10sul']:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c].map(converter_hora), errors='coerce')
        else:
            df[c] = pd.NaT
    for c in ['os_id', 'frota', 'evento', 'status', 'descricao', 'modal', 'unidade']:
        if c not in df.columns:
            df[c] = ''
    df['frota'] = df['frota'].apply(norm_frota)
    df['excluida_asn'] = df.get('excluida_asn_em', pd.Series(None, index=df.index)).notna()
    return df


def render_consulta(carregar, converter_hora, norm_frota, inconsistencias_asn, *, carregar_resumo=None):
    agora = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None)
    try:
        if carregar_resumo is None:
            base = carregar()
            if base.empty:
                st.warning('A base do monitor está vazia. Confira a sincronização da Lista ASN.')
                st.stop()
            atualizado_em = base.attrs.get('sincronizado_em')
            df = _preparar_historico(base, converter_hora, norm_frota)
            atrasadas = listar_frotas_atrasadas(df, agora)
        else:
            atrasadas, atualizado_em = carregar_resumo()
    except Exception:
        st.error('Não foi possível carregar o histórico. Tente novamente.')
        st.stop()
    sincronizado_em = converter_hora(atualizado_em)

    @st.dialog('🔎 Histórico da frota', width='large')
    def modal_historico_frota(fq):
        st.markdown(
            f'{_ESTILO_CREDITO_DIALOGO}'
            '<div class="historico-credit-row">'
            f'<span class="historico-credit">{CREDITO_HISTORICO}</span></div>'
            f'\n\n### Frota {escape(str(fq))}',
            unsafe_allow_html=True,
        )
        try:
            if carregar_resumo is None:
                hist = df.loc[df['frota'].eq(fq)].copy()
            else:
                hist = _preparar_historico(carregar(fq), converter_hora, norm_frota)
        except Exception:
            st.error('Não foi possível consultar esta frota. Tente novamente.')
            return
        if hist.empty:
            st.warning('Frota não encontrada na base sincronizada.')
            return
        # Mantém OS excluídas depois das ativas em caso de empate no início.
        hist = hist.sort_values(['inicio', 'excluida_asn'], ascending=[False, True]).reset_index(drop=True)
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

        conferir = inconsistencias_asn(hist.loc[validos])
        if not conferir.empty:
            with st.expander(f'⚠️ Conferência ASN ({len(conferir)} registro(s))'):
                st.warning('OS pendente não confirma atendimento ainda em andamento.')
                st.dataframe(conferir, hide_index=True, use_container_width=True)
        st.markdown('#### Histórico de atendimentos')
        col_periodo, col_busca = st.columns([1, 2])
        with col_periodo:
            periodo = st.selectbox(
                'Período',
                ['Todo período', 'Últimos 7 dias', 'Últimos 15 dias', 'Mês atual', 'Mês anterior'],
                key=f'historico_periodo_{fq}',
            )
        with col_busca:
            termos = st.text_input(
                'Pesquisar na descrição',
                placeholder='Digite um ou mais termos',
                key=f'historico_descricao_{fq}',
            )

        filtrado = hist.copy()
        data_referencia = pd.to_datetime(filtrado['parada'], errors='coerce').fillna(
            pd.to_datetime(filtrado['inicio'], errors='coerce')
        )
        inicio_mes = agora.normalize().replace(day=1)
        if periodo == 'Últimos 7 dias':
            filtrado = filtrado.loc[data_referencia.ge(agora - pd.Timedelta(days=7))]
        elif periodo == 'Últimos 15 dias':
            filtrado = filtrado.loc[data_referencia.ge(agora - pd.Timedelta(days=15))]
        elif periodo == 'Mês atual':
            filtrado = filtrado.loc[data_referencia.ge(inicio_mes) & data_referencia.lt(inicio_mes + pd.offsets.MonthBegin(1))]
        elif periodo == 'Mês anterior':
            inicio_mes_anterior = inicio_mes - pd.offsets.MonthBegin(1)
            filtrado = filtrado.loc[data_referencia.ge(inicio_mes_anterior) & data_referencia.lt(inicio_mes)]

        termos_busca = [
            unicodedata.normalize('NFKD', termo).encode('ascii', 'ignore').decode().casefold()
            for termo in str(termos or '').split() if termo.strip()
        ]
        if termos_busca:
            descricoes = filtrado['descricao'].fillna('').astype(str).map(
                lambda valor: unicodedata.normalize('NFKD', valor).encode('ascii', 'ignore').decode().casefold()
            )
            corresponde = pd.Series(True, index=filtrado.index)
            for termo in termos_busca:
                corresponde &= descricoes.str.contains(termo, regex=False, na=False)
            filtrado = filtrado.loc[corresponde]

        st.caption(f'{len(filtrado)} atendimento(s) encontrados.')
        show = filtrado[['os_id', 'evento', 'descricao', 'parada', 'inicio', 'fim', 'status']].copy()
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
                st.caption(f'Somente frotas da relação oficial de {len(FROTAS_ATIVAS)} ativas • Maior tempo primeiro.')
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
    if pd.notna(sincronizado_em):
        st.caption(f"Última atualização da Lista ASN: {sincronizado_em:%d/%m/%Y às %H:%M} (horário de Brasília)")
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
