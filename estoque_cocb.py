"""Controle de Estoque COCB | Streamlit + Supabase PostgreSQL.
Secrets do Streamlit: [connections.cocb] url = "postgresql://..."
"""
import io
import pandas as pd
import psycopg2
from psycopg2 import errors
import streamlit as st

st.set_page_config(page_title="10 Sul | Estoque COCB", page_icon="📦", layout="wide")

def conectar():
    try:
        uri = st.secrets["connections"]["cocb"]["url"]
    except (KeyError, FileNotFoundError):
        st.error("Configure [connections.cocb] url nos Secrets do Streamlit Cloud.")
        st.stop()
    try:
        return psycopg2.connect(uri, connect_timeout=12, sslmode="require")
    except psycopg2.Error:
        st.error("Não foi possível conectar ao Supabase. Confira a URI nos Secrets.")
        st.stop()

def consultar(sql, params=()):
    with conectar() as conn:
        return pd.read_sql_query(sql, conn, params=params)

def cadastrar(ni, descricao):
    ni, descricao = str(ni).strip(), str(descricao).strip()
    if not ni or not descricao:
        raise ValueError("NI e descrição são obrigatórios.")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.cocb_itens (ni,descricao) VALUES (%s,%s) ON CONFLICT (ni) DO NOTHING RETURNING ni",
                (ni, descricao))
            return cur.fetchone() is not None

def movimentar(ni, tipo, quantidade, observacao):
    if tipo not in ("ENTRADA", "SAIDA") or quantidade <= 0:
        raise ValueError("Movimento ou quantidade inválidos.")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT saldo_atual, estoque_inicial FROM public.cocb_itens WHERE ni=%s FOR UPDATE", (ni,))
            item = cur.fetchone()
            if item is None:
                raise ValueError("NI não encontrado.")
            saldo, inicial = item
            if tipo == "SAIDA" and inicial is None:
                raise ValueError("Registre a primeira ENTRADA antes de efetuar saídas.")
            novo = saldo + (quantidade if tipo == "ENTRADA" else -quantidade)
            if novo < 0:
                raise ValueError(f"Estoque insuficiente: saldo disponível {saldo}.")
            primeira = tipo == "ENTRADA" and inicial is None
            cur.execute(
                """UPDATE public.cocb_itens
                   SET saldo_atual=%s, estoque_inicial=CASE WHEN %s THEN %s ELSE estoque_inicial END
                   WHERE ni=%s""", (novo, primeira, quantidade, ni))
            cur.execute(
                """INSERT INTO public.cocb_movimentacoes
                   (ni,movimento,quantidade,saldo_apos,estoque_inicial_registrado,observacao)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (ni, tipo, quantidade, novo, primeira, observacao.strip()))
    return primeira, novo

def itens():
    return consultar("""SELECT ni AS "NI", descricao AS "DESCRIÇÃO",
                       estoque_inicial AS "ESTOQUE INICIAL", saldo_atual AS "SALDO ATUAL"
                       FROM public.cocb_itens ORDER BY descricao""")

def historico():
    return consultar("""SELECT m.data_hora AS "DATA/HORA", m.ni AS "NI",
                       i.descricao AS "DESCRIÇÃO", m.movimento AS "MOVIMENTO",
                       m.quantidade AS "QUANTIDADE", m.saldo_apos AS "SALDO APÓS",
                       m.estoque_inicial_registrado AS "PRIMEIRA ENTRADA",
                       m.observacao AS "OBSERVAÇÃO"
                       FROM public.cocb_movimentacoes m
                       JOIN public.cocb_itens i ON i.ni=m.ni ORDER BY m.id DESC""")

st.title("📦 10 SUL • ESTOQUE COCB")
st.caption("Desenvolvido por Evandro Junior")
pagina = st.query_params.get("pagina", "cadastro")
if pagina not in ("cadastro", "movimentacao"):
    pagina = "cadastro"
col1, col2 = st.columns(2)
col1.link_button("Cadastro de itens", "?pagina=cadastro", use_container_width=True)
col2.link_button("Movimentação", "?pagina=movimentacao", use_container_width=True)

if pagina == "cadastro":
    st.subheader("Cadastro de materiais")
    st.info("O estoque inicial será definido automaticamente pela primeira ENTRADA de cada material.")
    with st.form("novo_item", clear_on_submit=True):
        ni = st.text_input("NI (manual)")
        descricao = st.text_input("Descrição")
        gravar = st.form_submit_button("Cadastrar material", type="primary")
    if gravar:
        try:
            st.success("Material cadastrado.") if cadastrar(ni, descricao) else st.warning("NI já cadastrado; nenhum dado foi alterado.")
        except (ValueError, psycopg2.Error) as exc:
            st.error(str(exc) if isinstance(exc, ValueError) else "Falha ao cadastrar material.")
    st.subheader("Importar materiais por Excel")
    arquivo = st.file_uploader("Planilha com colunas NI e DESCRIÇÃO", type=["xlsx"])
    if arquivo:
        try:
            df = pd.read_excel(arquivo, dtype=str).fillna("")
            df.columns = [str(c).strip().upper().replace("Ç", "C").replace("Ã", "A") for c in df.columns]
            if not {"NI", "DESCRICAO"}.issubset(df.columns):
                st.error("A planilha precisa ter as colunas NI e DESCRIÇÃO.")
            else:
                st.dataframe(df[["NI", "DESCRICAO"]].head(30), hide_index=True)
                if st.button("Confirmar importação"):
                    novos, existentes, falhas = 0, 0, 0
                    for _, linha in df.iterrows():
                        try:
                            if cadastrar(linha["NI"], linha["DESCRICAO"]):
                                novos += 1
                            else:
                                existentes += 1
                        except (ValueError, psycopg2.Error):
                            falhas += 1
                    st.success(f"Novos: {novos}; existentes: {existentes}; não importados: {falhas}.")
        except Exception:
            st.error("Não foi possível ler a planilha.")
    st.subheader("Saldos")
    dados = itens()
    filtro = st.text_input("Buscar NI ou descrição")
    if filtro:
        dados = dados[dados["NI"].str.contains(filtro, case=False, regex=False) |
                      dados["DESCRIÇÃO"].str.contains(filtro, case=False, regex=False)]
    st.dataframe(dados, use_container_width=True, hide_index=True)
    st.download_button("Exportar saldos", dados.to_csv(index=False).encode("utf-8-sig"), "cocb_saldos.csv")
else:
    st.subheader("Entrada e saída")
    dados = itens()
    if dados.empty:
        st.info("Nenhum material cadastrado.")
    else:
        opcoes = {f"{r['NI']} | {r['DESCRIÇÃO']} | Saldo: {r['SALDO ATUAL']}": r["NI"]
                  for _, r in dados.iterrows()}
        with st.form("movimentar", clear_on_submit=True):
            selecionado = st.selectbox("Material", list(opcoes))
            tipo = st.selectbox("Movimento", ["ENTRADA", "SAÍDA"])
            quantidade = st.number_input("Quantidade", min_value=1, step=1)
            obs = st.text_input("Observação")
            enviar = st.form_submit_button("Registrar", type="primary")
        if enviar:
            try:
                primeira, novo = movimentar(opcoes[selecionado], "SAIDA" if tipo == "SAÍDA" else "ENTRADA", int(quantidade), obs)
                st.success(f"{'Estoque inicial registrado!' if primeira else 'Movimentação registrada!'} Novo saldo: {novo}")
            except ValueError as exc:
                st.error(str(exc))
            except psycopg2.Error:
                st.error("Erro ao salvar movimentação no banco.")
    st.subheader("Histórico")
    movs = historico()
    st.dataframe(movs, use_container_width=True, hide_index=True)
    st.download_button("Exportar histórico", movs.to_csv(index=False).encode("utf-8-sig"), "cocb_historico.csv")
