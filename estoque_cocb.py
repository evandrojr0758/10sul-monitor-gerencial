"""Estoque COCB — armazenamento em repositório privado GitHub.
Secrets: GITHUB_TOKEN, DATA_REPOSITORY, opcional DATA_BRANCH.
A cada gravação usa SHA para impedir sobrescrita de versões concorrentes.
"""
import base64
import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

import pandas as pd
import streamlit as st

st.set_page_config(page_title="10 Sul | Estoque COCB", page_icon="📦", layout="wide")

MATERIAIS = [
    ("27179902", "Válvula relê Facchini"),
    ("27174139", "Parafuso Facchini"),
    ("27174074", "Porca Facchini"),
    ("27130048", "Parafuso 1/1.8"),
    ("27114780", "Porca de 1.1/8"),
    ("27145672", "Mangotes"),
    ("27094293", "Válvula prévia"),
    ("27258592", "Bolsa de ar Manos"),
    ("27033363", "Bolsa de ar Sergomel"),
    ("27251038", "Arruela cônica"),
    ("27243269", "Colar de alinhamento"),
]

class ErroEstoque(Exception):
    pass

class BaseGitHub:
    def __init__(self):
        try:
            self.repo = str(st.secrets["DATA_REPOSITORY"]).strip()
            self.token = str(st.secrets["GITHUB_TOKEN"]).strip()
            self.branch = str(st.secrets.get("DATA_BRANCH", "main")).strip()
        except (KeyError, FileNotFoundError):
            raise ErroEstoque("Configure DATA_REPOSITORY e GITHUB_TOKEN nos Secrets.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo) or not self.token:
            raise ErroEstoque("Repositório ou token inválido.")
        self.api = "https://api.github.com/repos/" + self.repo
        self.path = "/contents/dados/estoque_cocb.json"

    def requisitar(self, endpoint, metodo="GET", payload=None):
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "10Sul-Estoque-COCB"}
        corpo = json.dumps(payload).encode("utf-8") if payload is not None else None
        if corpo is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(self.api + endpoint, data=corpo, headers=headers, method=metodo), timeout=25) as resp:
                return json.load(resp)
        except HTTPError as exc:
            if exc.code == 404 and metodo == "GET" and endpoint.startswith("/contents/"):
                return None
            if exc.code in (409, 422):
                raise ErroEstoque("Outra pessoa atualizou o estoque. Recarregue e repita a operação.") from None
            raise ErroEstoque(f"Falha de comunicação com o GitHub (HTTP {exc.code}).") from None
        except (OSError, URLError):
            raise ErroEstoque("Não foi possível acessar a base. Tente novamente.") from None

    def verificar_privado(self):
        info = self.requisitar("")
        if not info or not info.get("private"):
            raise ErroEstoque("A base deve estar em um repositório PRIVADO.")

    def ler(self):
        arquivo = self.requisitar(self.path + "?ref=" + quote(self.branch, safe=""))
        if arquivo is None:
            dados = {"schema": 1, "itens": {}, "movimentos": []}
            for ni, descricao in MATERIAIS:
                dados["itens"][ni] = {"descricao": descricao, "estoque_inicial": None, "saldo": 0, "minimo": None, "maximo": None}
            return dados, None
        try:
            dados = json.loads(base64.b64decode(arquivo["content"]))
            if dados.get("schema") != 1 or not isinstance(dados.get("itens"), dict) or not isinstance(dados.get("movimentos"), list):
                raise ValueError()
            return dados, arquivo["sha"]
        except (ValueError, KeyError, TypeError):
            raise ErroEstoque("Base de estoque inválida. Nenhuma informação foi modificada.") from None

    def salvar(self, dados, sha):
        conteudo = base64.b64encode(json.dumps(dados, ensure_ascii=False, indent=2).encode()).decode()
        payload = {"message": "Atualizar estoque COCB", "branch": self.branch, "content": conteudo}
        if sha:
            payload["sha"] = sha
        self.requisitar(self.path, "PUT", payload)

def situacao(item):
    minimo, maximo = item.get("minimo"), item.get("maximo")
    saldo = item["saldo"]
    if minimo is not None and saldo < minimo:
        return "🔴 Abaixo do mínimo"
    if maximo is not None and saldo > maximo:
        return "🟠 Acima do máximo"
    if minimo is None or maximo is None:
        return "⚪ Não configurado"
    return "🟢 Dentro dos limites"

def itens_tabela(dados):
    return pd.DataFrame([{"NI": ni, "DESCRIÇÃO": item["descricao"],
                          "ESTOQUE INICIAL": item["estoque_inicial"],
                          "SALDO ATUAL": item["saldo"], "MÍNIMO": item.get("minimo"), "MÁXIMO": item.get("maximo"), "SITUAÇÃO": situacao(item)}
                         for ni, item in sorted(dados["itens"].items(), key=lambda x: x[1]["descricao"])])

def registrar(dados, ni, tipo, quantidade, obs):
    item = dados["itens"].get(ni)
    if item is None:
        raise ErroEstoque("Material não encontrado.")
    if quantidade <= 0:
        raise ErroEstoque("Informe uma quantidade positiva.")
    if tipo == "SAÍDA" and item["estoque_inicial"] is None:
        raise ErroEstoque("É necessário registrar a primeira ENTRADA antes de realizar saídas.")
    saldo = item["saldo"] + (quantidade if tipo == "ENTRADA" else -quantidade)
    if saldo < 0:
        raise ErroEstoque(f"Saldo insuficiente. Disponível: {item['saldo']}.")
    primeira = tipo == "ENTRADA" and item["estoque_inicial"] is None
    if primeira:
        item["estoque_inicial"] = quantidade
    item["saldo"] = saldo
    dados["movimentos"].append({
        "data_hora": datetime.now(timezone.utc).isoformat(),
        "ni": ni, "descricao": item["descricao"], "movimento": tipo,
        "quantidade": quantidade, "saldo_apos": saldo,
        "primeira_entrada": primeira, "observacao": obs.strip()})
    return primeira, saldo

st.title("📦 10 SUL • CONTROLE DE ESTOQUE COCB")
st.caption("Desenvolvido por Evandro Junior")
try:
    base = BaseGitHub()
    base.verificar_privado()
    dados, sha = base.ler()
except ErroEstoque as exc:
    st.error(str(exc))
    st.stop()

pagina = st.query_params.get("pagina", "cadastro")
if pagina not in ("cadastro", "movimentacao"):
    pagina = "cadastro"
a, b = st.columns(2)
a.link_button("Cadastro de itens", "?pagina=cadastro", use_container_width=True)
b.link_button("Movimentação de estoque", "?pagina=movimentacao", use_container_width=True)

if pagina == "cadastro":
    st.subheader("Cadastro de materiais")
    st.info("A primeira ENTRADA de cada material definirá o estoque inicial.")
    with st.form("cadastro", clear_on_submit=True):
        ni = st.text_input("NI (informado manualmente)")
        descricao = st.text_input("Descrição")
        gravar = st.form_submit_button("Cadastrar", type="primary")
    if gravar:
        ni, descricao = ni.strip(), descricao.strip()
        if not ni or not descricao:
            st.error("Preencha NI e descrição.")
        elif ni in dados["itens"]:
            st.warning("Este NI já existe; nada foi alterado.")
        else:
            dados["itens"][ni] = {"descricao": descricao, "estoque_inicial": None, "saldo": 0, "minimo": None, "maximo": None}
            try:
                base.salvar(dados, sha)
                st.success("Material cadastrado.")
                st.rerun()
            except ErroEstoque as exc:
                st.error(str(exc))
    st.subheader("Configurar estoque mínimo e máximo")
    if dados["itens"]:
        escolhas = {f"{ni} | {item['descricao']}": ni for ni, item in sorted(dados["itens"].items())}
        with st.form("limites"):
            escolhido_limite = st.selectbox("Material para configurar", list(escolhas))
            item_limite = dados["itens"][escolhas[escolhido_limite]]
            col_min, col_max = st.columns(2)
            minimo = col_min.number_input("Estoque mínimo", min_value=0, value=int(item_limite.get("minimo") or 0), step=1)
            maximo = col_max.number_input("Estoque máximo", min_value=0, value=int(item_limite.get("maximo") or 0), step=1)
            salvar_limites = st.form_submit_button("Salvar limites", type="primary")
        if salvar_limites:
            if maximo < minimo:
                st.error("O estoque máximo não pode ser menor que o mínimo.")
            else:
                item_limite["minimo"] = int(minimo)
                item_limite["maximo"] = int(maximo)
                try:
                    base.salvar(dados, sha)
                    st.success("Limites atualizados.")
                    st.rerun()
                except ErroEstoque as exc:
                    st.error(str(exc))
    st.subheader("Importar materiais")
    arquivo = st.file_uploader("Excel com NI e DESCRIÇÃO", type=["xlsx"])
    if arquivo:
        try:
            planilha = pd.read_excel(arquivo, dtype=str).fillna("")
            planilha.columns = [str(c).strip().upper().replace("Ç", "C").replace("Ã", "A") for c in planilha.columns]
            if not {"NI", "DESCRICAO"}.issubset(planilha.columns):
                st.error("A planilha precisa conter NI e DESCRIÇÃO.")
            else:
                st.dataframe(planilha[["NI", "DESCRICAO"]].head(30), hide_index=True)
                if st.button("Importar"):
                    novos = 0
                    for _, linha in planilha.iterrows():
                        ni, descricao = str(linha["NI"]).strip(), str(linha["DESCRICAO"]).strip()
                        if ni and descricao and ni not in dados["itens"]:
                            dados["itens"][ni] = {"descricao": descricao, "estoque_inicial": None, "saldo": 0, "minimo": None, "maximo": None}
                            novos += 1
                    if novos:
                        try:
                            base.salvar(dados, sha)
                            st.success(f"{novos} materiais importados.")
                            st.rerun()
                        except ErroEstoque as exc:
                            st.error(str(exc))
                    else:
                        st.info("Nenhum NI novo encontrado.")
        except Exception:
            st.error("Não foi possível ler o Excel.")
    st.subheader("Consulta de estoque")
    tabela = itens_tabela(dados)
    busca = st.text_input("Buscar NI ou descrição")
    if busca:
        tabela = tabela[tabela["NI"].str.contains(busca, case=False, regex=False) |
                        tabela["DESCRIÇÃO"].str.contains(busca, case=False, regex=False)]
    st.dataframe(tabela, use_container_width=True, hide_index=True)
    st.download_button("Exportar saldos", tabela.to_csv(index=False).encode("utf-8-sig"), "saldos_cocb.csv")
else:
    st.subheader("Movimentação")
    tabela = itens_tabela(dados)
    if tabela.empty:
        st.info("Cadastre materiais antes de movimentar.")
    else:
        opcoes = {f"{r['NI']} | {r['DESCRIÇÃO']} | Saldo: {r['SALDO ATUAL']}": r["NI"] for _, r in tabela.iterrows()}
        with st.form("movimentacao", clear_on_submit=True):
            escolhido = st.selectbox("Material", list(opcoes))
            tipo = st.selectbox("Movimento", ["ENTRADA", "SAÍDA"])
            quantidade = st.number_input("Quantidade", min_value=1, step=1)
            observacao = st.text_input("Observação (opcional)")
            confirmar = st.form_submit_button("Registrar movimentação", type="primary")
        if confirmar:
            try:
                primeira, saldo = registrar(dados, opcoes[escolhido], tipo, int(quantidade), observacao)
                base.salvar(dados, sha)
                st.success(f"{'Estoque inicial registrado!' if primeira else 'Movimentação registrada!'} Saldo: {saldo}")
                st.rerun()
            except ErroEstoque as exc:
                st.error(str(exc))
    st.subheader("Histórico")
    movimentos = pd.DataFrame(reversed(dados["movimentos"]))
    st.dataframe(movimentos, use_container_width=True, hide_index=True)
    st.download_button("Exportar histórico", movimentos.to_csv(index=False).encode("utf-8-sig"), "historico_cocb.csv")
