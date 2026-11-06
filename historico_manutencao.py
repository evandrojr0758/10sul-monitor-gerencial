"""Página independente de consulta ao histórico sincronizado do Monitor Web."""
import re

import pandas as pd


def normalizar_frota(valor):
    texto = re.sub(r"^GO[\s:-]*", "", str(valor or "").strip().upper())
    return re.sub(r"\.0$", "", texto).strip()


def preparar_historico(base, converter_hora):
    dados = base.copy()
    for coluna in ("os_id", "frota", "evento", "descricao", "status"):
        if coluna not in dados:
            dados[coluna] = ""
    dados["frota"] = dados["frota"].fillna("").map(normalizar_frota)
    for coluna in ("parada", "inicio", "fim"):
        if coluna not in dados:
            dados[coluna] = pd.NaT
        dados[coluna] = pd.to_datetime(dados[coluna].map(converter_hora), errors="coerce")
    dados["excluida"] = dados.get(
        "excluida_asn_em", pd.Series(None, index=dados.index, dtype=object)
    ).notna()
    dados["referencia"] = dados["inicio"].fillna(dados["parada"]).fillna(dados["fim"])
    return dados.sort_values("referencia", ascending=False, na_position="last")


def ultima_preventiva(dados, revisao=False):
    eventos = dados["evento"].fillna("").astype(str).str.upper().str.strip()
    mascara = eventos.str.contains("REVIS", na=False) if revisao else eventos.eq("ITR")
    registros = dados.loc[mascara & ~dados["excluida"]]
    return None if registros.empty else registros.iloc[0]


def render_consulta(carregar, converter_hora):
    import streamlit as st

    st.title("🔎 Histórico de manutenção")
    st.caption("10 Sul • Somente consulta • Datas e horários de Brasília")
    if st.button("↻ Atualizar histórico", use_container_width=True):
        carregar.clear()
    try:
        dados = preparar_historico(carregar(), converter_hora)
    except Exception:
        st.error("Não foi possível carregar o histórico. Tente atualizar novamente.")
        st.stop()
    if dados.empty:
        st.info("Nenhum atendimento na base sincronizada.")
        st.stop()

    frota = normalizar_frota(st.text_input(
        "Frota / GO", value=str(st.query_params.get("frota", "")),
        placeholder="Ex.: 13725"))
    consulta = dados.loc[dados["frota"].eq(frota)].copy() if frota else dados.copy()
    if frota:
        st.subheader("Frota " + frota)
        if consulta.empty:
            st.info("Frota não encontrada na base sincronizada.")
            st.stop()
        for coluna, revisao, titulo in zip(st.columns(2), (False, True), ("Última ITR", "Última revisão")):
            with coluna:
                with st.container(border=True):
                    st.markdown("**" + titulo + "**")
                    registro = ultima_preventiva(consulta, revisao)
                    if registro is None:
                        st.caption("Não encontrada na base sincronizada.")
                    else:
                        st.caption("OS/ID: " + str(registro["os_id"]))
                        if pd.notna(registro["fim"]):
                            st.markdown("### " + registro["fim"].strftime("%d/%m/%Y"))
                            st.caption("Liberação: " + registro["fim"].strftime("%d/%m/%Y %H:%M"))
                        else:
                            entrada = registro["inicio"] if pd.notna(registro["inicio"]) else registro["parada"]
                            st.markdown("### " + (entrada.strftime("%d/%m/%Y") if pd.notna(entrada) else "Sem data"))
                            st.caption("Último atendimento • liberação ainda não confirmada.")
        st.caption("Última ITR e revisão consideram todo o histórico da frota, antes dos filtros abaixo.")

    a, b = st.columns(2)
    periodo = a.selectbox("Período", ["Todo o histórico", "Últimos 30 dias", "Últimos 7 dias", "Personalizado"])
    eventos = b.multiselect("Evento", sorted(consulta["evento"].dropna().astype(str).unique()))
    if eventos:
        consulta = consulta.loc[consulta["evento"].isin(eventos)]
    if periodo != "Todo o histórico":
        hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
        inicio = hoje - pd.Timedelta(days=29 if periodo == "Últimos 30 dias" else 6)
        fim = hoje
        if periodo == "Personalizado":
            a, b = st.columns(2)
            inicio = a.date_input("Data inicial", value=hoje.replace(day=1))
            fim = b.date_input("Data final", value=hoje)
        if inicio > fim:
            st.warning("A data inicial deve ser anterior ou igual à data final.")
            st.stop()
        consulta = consulta.loc[consulta["referencia"].dt.date.between(inicio, fim)]
    incluir_excluidas = st.checkbox("Incluir OS excluídas na Lista ASN", value=False)
    if not incluir_excluidas:
        consulta = consulta.loc[~consulta["excluida"]]
    if consulta.empty:
        st.info("Nenhum atendimento encontrado para os filtros selecionados.")
        st.stop()
    tabela = consulta[["os_id", "frota", "evento", "descricao", "parada", "inicio", "fim", "status"]].copy()
    tabela.loc[consulta["excluida"], "status"] = "Excluída na Lista ASN"
    for campo in ("parada", "inicio", "fim"):
        tabela[campo] = tabela[campo].dt.strftime("%d/%m/%Y %H:%M").fillna("")
    tabela.columns = ["OS/ID", "FROTA", "EVENTO", "DESCRIÇÃO", "PARADA", "INÍCIO", "FIM", "STATUS"]
    st.caption(f"{len(tabela)} atendimento(s) • {consulta['frota'].nunique()} frota(s)")
    st.dataframe(tabela, hide_index=True, use_container_width=True)
    st.download_button("📥 Baixar histórico em CSV", tabela.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name="historico_manutencao.csv", mime="text/csv")
    st.caption("Desenvolvido por Evandro Junior")
    st.stop()
