"""Controle de Estoque COCB — aplicativo independente (Streamlit).

Execute: streamlit run estoque_cocb.py
Links independentes: /?pagina=cadastro e /?pagina=movimentacao
IMPORTANTE: SQLite local é adequado apenas para teste em armazenamento persistente.
Para uso compartilhado no Streamlit Cloud, migrar para PostgreSQL hospedado.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="10 Sul | Estoque COCB", page_icon="📦", layout="wide")
DB_PATH = Path(os.getenv("COCB_DB_PATH", "estoque_cocb.sqlite3"))


def conexao():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    return db


def inicializar():
    with conexao() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS itens (
            ni TEXT PRIMARY KEY, descricao TEXT NOT NULL,
            saldo INTEGER NOT NULL DEFAULT 0 CHECK(saldo >= 0),
            criado_em TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS movimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ni TEXT NOT NULL REFERENCES itens(ni),
            tipo TEXT NOT NULL CHECK(tipo IN ('ENTRADA','SAÍDA','ESTOQUE INICIAL')),
            quantidade INTEGER NOT NULL CHECK(quantidade > 0),
            saldo_apos INTEGER NOT NULL, data_hora TEXT NOT NULL,
            observacao TEXT NOT NULL DEFAULT '')""")


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cadastrar(ni, descricao, inicial):
    ni, descricao = str(ni).strip(), str(descricao).strip()
    if not ni or not descricao or inicial < 0:
        raise ValueError("Informe NI, descrição e estoque inicial válido.")
    with conexao() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO itens VALUES (?,?,?,?)", (ni, descricao, inicial, agora()))
        if inicial:
            db.execute("""INSERT INTO movimentos
                (ni,tipo,quantidade,saldo_apos,data_hora,observacao)
                VALUES (?,?,?,?,?,?)""", (ni, "ESTOQUE INICIAL", inicial, inicial, agora(), "Cadastro"))


def movimentar(ni, tipo, quantidade, observacao=""):
    if tipo not in ("ENTRADA", "SAÍDA") or quantidade <= 0:
        raise ValueError("Movimento ou quantidade inválida.")
    with conexao() as db:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute("SELECT saldo FROM itens WHERE ni=?", (ni,)).fetchone()
        if item is None:
            raise ValueError("Material não encontrado.")
        novo = item["saldo"] + (quantidade if tipo == "ENTRADA" else -quantidade)
        if novo < 0:
            raise ValueError(f"Saldo insuficiente. Disponível: {item['saldo']}.")
        db.execute("UPDATE itens SET saldo=? WHERE ni=?", (novo, ni))
        db.execute("""INSERT INTO movimentos
            (ni,tipo,quantidade,saldo_apos,data_hora,observacao)
            VALUES (?,?,?,?,?,?)""", (ni, tipo, quantidade, novo, agora(), observacao.strip()))


def itens_df():
    with conexao() as db:
        return pd.read_sql_query("SELECT ni AS NI, descricao AS DESCRIÇÃO, saldo AS ESTOQUE FROM itens ORDER BY descricao", db)


def movimentos_df():
    with conexao() as db:
        return pd.read_sql_query("""SELECT m.data_hora AS 'DATA/HORA', m.ni AS NI,
            i.descricao AS DESCRIÇÃO, m.tipo AS MOVIMENTO,
            m.quantidade AS QUANTIDADE, m.saldo_apos AS 'SALDO APÓS',
            m.observacao AS OBSERVAÇÃO FROM movimentos m
            JOIN itens i ON i.ni=m.ni ORDER BY m.id DESC""", db)


inicializar()
st.title("📦 10 SUL • CONTROLE DE ESTOQUE COCB")
st.caption("Desenvolvido por Evandro Junior")
pagina = st.query_params.get("pagina", "cadastro")
if pagina not in ("cadastro", "movimentacao"):
    pagina = "cadastro"
a, b = st.columns(2)
a.link_button("Cadastro de itens", "?pagina=cadastro", use_container_width=True)
b.link_button("Movimentação de estoque", "?pagina=movimentacao", use_container_width=True)

if pagina == "cadastro":
    st.subheader("Cadastro de itens")
    with st.form("cadastro", clear_on_submit=True):
        ni = st.text_input("NI (código original)", max_chars=100)
        descricao = st.text_input("Descrição do material")
        inicial = st.number_input("Estoque inicial", min_value=0, step=1)
        salvar = st.form_submit_button("Cadastrar material", type="primary")
    if salvar:
        try:
            cadastrar(ni, descricao, int(inicial))
            st.success("Material cadastrado.")
        except sqlite3.IntegrityError:
            st.error("Este NI já está cadastrado. O saldo existente não foi alterado.")
        except (ValueError, sqlite3.Error) as e:
            st.error(str(e))

    st.subheader("Importar cadastro do Excel")
    st.caption("Colunas: NI, DESCRICAO, ESTOQUE INICIAL. NI existente será ignorado, sem alterar saldo.")
    arquivo = st.file_uploader("Selecione um arquivo .xlsx", type=["xlsx"])
    if arquivo:
        try:
            planilha = pd.read_excel(arquivo, dtype={"NI": str}).fillna("")
            planilha.columns = [str(c).strip().upper().replace("Ç", "C").replace("Ã", "A") for c in planilha.columns]
            if not {"NI", "DESCRICAO", "ESTOQUE INICIAL"}.issubset(planilha.columns):
                st.error("A planilha precisa conter NI, DESCRICAO e ESTOQUE INICIAL.")
            else:
                st.dataframe(planilha.head(30), use_container_width=True, hide_index=True)
                if st.button("Confirmar importação"):
                    novos, existentes, erros = 0, 0, []
                    for linha, r in planilha.iterrows():
                        try:
                            valor = float(r["ESTOQUE INICIAL"])
                            if not valor.is_integer() or valor < 0:
                                raise ValueError("Estoque inicial deve ser inteiro e não negativo")
                            cadastrar(r["NI"], r["DESCRICAO"], int(valor))
                            novos += 1
                        except sqlite3.IntegrityError:
                            existentes += 1
                        except (ValueError, TypeError, sqlite3.Error) as e:
                            erros.append(f"Linha {linha + 2}: {e}")
                    st.success(f"Importados: {novos}. NI já existentes: {existentes}.")
                    if erros:
                        st.warning("\n".join(erros[:30]))
        except Exception as e:
            st.error(f"Não foi possível ler a planilha: {e}")

    st.subheader("Saldo atual")
    tabela = itens_df()
    filtro = st.text_input("Pesquisar NI ou descrição")
    if filtro:
        tabela = tabela[tabela["NI"].str.contains(filtro, case=False, regex=False) |
                        tabela["DESCRIÇÃO"].str.contains(filtro, case=False, regex=False)]
    st.dataframe(tabela, hide_index=True, use_container_width=True)
    st.download_button("Exportar saldos CSV", tabela.to_csv(index=False).encode("utf-8-sig"),
                       "saldos_cocb.csv", "text/csv")
else:
    st.subheader("Entrada e saída de materiais")
    tabela = itens_df()
    if tabela.empty:
        st.info("Cadastre um material antes de movimentar o estoque.")
    else:
        opcoes = {f"{r.NI} | {r.DESCRIÇÃO} | Saldo: {r.ESTOQUE}": r.NI
                  for r in tabela.itertuples(index=False)}
        with st.form("movimentacao", clear_on_submit=True):
            escolha = st.selectbox("Descrição / NI", list(opcoes))
            tipo = st.selectbox("Movimento", ["ENTRADA", "SAÍDA"])
            quantidade = st.number_input("Quantidade", min_value=1, step=1)
            observacao = st.text_input("Observação (opcional)")
            confirmar = st.form_submit_button("Registrar movimentação", type="primary")
        if confirmar:
            try:
                movimentar(opcoes[escolha], tipo, int(quantidade), observacao)
                st.success("Movimentação registrada e saldo atualizado.")
            except (ValueError, sqlite3.Error) as e:
                st.error(str(e))
    st.subheader("Histórico de movimentações")
    historico = movimentos_df()
    st.dataframe(historico, hide_index=True, use_container_width=True)
    st.download_button("Exportar histórico CSV",
                       historico.to_csv(index=False).encode("utf-8-sig"),
                       "historico_cocb.csv", "text/csv")
