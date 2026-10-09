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

UNIDADES = ("ARA", "MUC", "COCB", "NAN")

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
            normalizar(dados)
            return dados, arquivo["sha"]
        except (ValueError, KeyError, TypeError):
            raise ErroEstoque("Base de estoque inválida. Nenhuma informação foi modificada.") from None

    def salvar(self, dados, sha):
        conteudo = base64.b64encode(json.dumps(dados, ensure_ascii=False, indent=2).encode()).decode()
        payload = {"message": "Atualizar estoque COCB", "branch": self.branch, "content": conteudo}
        if sha:
            payload["sha"] = sha
        self.requisitar(self.path, "PUT", payload)


def normalizar(dados):
    """Preserva o saldo legado em COCB; as demais unidades começam vazias."""
    for item in dados["itens"].values():
        if "unidades" not in item:
            item["unidades"] = {
                u: {"saldo": item.get("saldo", 0) if u == "COCB" else 0,
                    "estoque_inicial": item.get("estoque_inicial") if u == "COCB" else None,
                    "minimo": item.get("minimo") if u == "COCB" else None,
                    "maximo": item.get("maximo") if u == "COCB" else None}
                for u in UNIDADES
            }

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
    normalizar(dados)
    linhas = []
    for ni, item in sorted(dados["itens"].items(), key=lambda x: x[1]["descricao"]):
        registro = item["unidades"][unidade]
        linhas.append({"NI": ni, "DESCRIÇÃO": item["descricao"],
                       **{u: item["unidades"][u]["saldo"] for u in UNIDADES},
                       "TOTAL": sum(item["unidades"][u]["saldo"] for u in UNIDADES),
                       "UNIDADE": unidade, "SALDO ATUAL": registro["saldo"],
                       "ESTOQUE INICIAL": registro["estoque_inicial"],
                       "MÍNIMO": registro.get("minimo"), "MÁXIMO": registro.get("maximo"),
                       "SITUAÇÃO": situacao(registro)})
    return pd.DataFrame(linhas, columns=["NI", "DESCRIÇÃO", "MÍNIMO", "MÁXIMO", *UNIDADES, "TOTAL", "UNIDADE",
                                        "SALDO ATUAL", "ESTOQUE INICIAL", "SITUAÇÃO"])

def registrar(dados, ni, tipo, quantidade, obs, unidade="COCB", go_carreta=""):
    normalizar(dados)
    material = dados["itens"].get(ni)
    if material is None:
        raise ErroEstoque("Material não encontrado.")
    if unidade not in UNIDADES or tipo not in ("ENTRADA", "SAÍDA"):
        raise ErroEstoque("Unidade ou movimento inválido.")
    go_carreta = str(go_carreta).strip().upper()
    if tipo == "SAÍDA" and not go_carreta:
        raise ErroEstoque("Informe o GO da carreta que receberá o material.")
    item = material["unidades"][unidade]
    if quantidade <= 0:
        raise ErroEstoque("Informe uma quantidade positiva.")
    if tipo == "SAÍDA" and item["estoque_inicial"] is None:
        raise ErroEstoque("Registre a primeira ENTRADA nesta unidade antes de realizar saídas.")
    saldo = item["saldo"] + (quantidade if tipo == "ENTRADA" else -quantidade)
    if saldo < 0:
        raise ErroEstoque(f"Saldo insuficiente. Disponível: {item['saldo']}.")
    primeira = tipo == "ENTRADA" and item["estoque_inicial"] is None
    if primeira:
        item["estoque_inicial"] = quantidade
    item["saldo"] = saldo
    if unidade == "COCB":
        material["saldo"] = saldo
        material["estoque_inicial"] = item["estoque_inicial"]
    dados["movimentos"].append({
        "data_hora": datetime.now(timezone.utc).isoformat(),
        "ni": ni, "descricao": material["descricao"], "unidade": unidade, "movimento": tipo,
        "quantidade": quantidade, "saldo_apos": saldo,
        "primeira_entrada": primeira, "go_carreta": go_carreta if tipo == "SAÍDA" else "", "observacao": obs.strip()})
    return primeira, saldo



def exportar_criticos_excel(tabela, unidade):
    from io import BytesIO
    from zoneinfo import ZoneInfo
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Itens críticos"
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:G1")
    ws["A1"] = "10 SUL — ITENS ABAIXO DO MÍNIMO"
    ws["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="15364B")
    ws.row_dimensions[1].height = 34
    ws.merge_cells("A2:G2")
    ws["A2"] = "Unidade: " + unidade + " | " + datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    cabecalhos = ["NI", "DESCRIÇÃO", "MÍNIMO", "MÁXIMO", "ESTOQUE ATUAL", "REPOR ATÉ MÁXIMO", "UNIDADE"]
    ws.append([])
    ws.append(cabecalhos)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="15364B")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[4].height = 32
    for numero, (_, item) in enumerate(tabela.iterrows(), start=5):
        atual, maximo = int(item["SALDO ATUAL"]), item["MÁXIMO"]
        ws.append([str(item["NI"]), str(item["DESCRIÇÃO"]), item["MÍNIMO"],
                   None if pd.isna(maximo) else maximo, atual,
                   None if pd.isna(maximo) else max(0, maximo - atual), unidade])
        for c in ws[numero]:
            c.alignment = Alignment(vertical="center", wrap_text=True)
            if numero % 2:
                c.fill = PatternFill("solid", fgColor="F0F4F7")
            if c.column in (3, 4, 5, 6):
                c.number_format = "#,##0"
        ws.cell(numero, 6).font = Font(bold=True, color="B42318")
        ws.row_dimensions[numero].height = 30
    for coluna, largura in enumerate((16, 48, 13, 13, 19, 23, 13), start=1):
        ws.column_dimensions[get_column_letter(coluna)].width = largura
    ws.freeze_panes = "C5"
    ws.auto_filter.ref = f"A4:G{ws.max_row}"
    ws.print_title_rows = "1:4"
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:G{ws.max_row}"
    arquivo = BytesIO()
    wb.save(arquivo)
    return arquivo.getvalue()


def gerar_imagem_reposicao(dados, unidade):
    from io import BytesIO
    import textwrap
    from zoneinfo import ZoneInfo
    from PIL import Image, ImageDraw, ImageFont

    normalizar(dados)
    grupos = []
    for campo, titulo, cor in (
        ("minimo", "ITENS ABAIXO DO MÍNIMO", "#b42318"),
        ("maximo", "ITENS ABAIXO DO MÁXIMO", "#b76e00"),
    ):
        linhas = []
        for ni, material in sorted(dados["itens"].items(), key=lambda x: x[1]["descricao"]):
            estoque = material["unidades"][unidade]
            limite = estoque.get(campo)
            if limite is not None and estoque["saldo"] < limite:
                descricao = textwrap.wrap(material["descricao"], width=42) or [""]
                linhas.append((ni, descricao, estoque["saldo"], limite, limite - estoque["saldo"]))
        grupos.append((titulo, cor, linhas))

    def fonte(tamanho):
        from pathlib import Path
        embutida = Path(__file__).resolve().parent / "assets" / "relatorio_font.b64"
        if embutida.exists():
            return ImageFont.truetype(BytesIO(base64.b64decode(embutida.read_text())), tamanho)
        for caminho in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(caminho, tamanho)
            except OSError:
                pass
        return ImageFont.load_default(size=tamanho)

    altura = 200 + sum(140 + sum(max(48, len(l[1]) * 27 + 16) for l in linhas)
                        for _, _, linhas in grupos)
    imagem = Image.new("RGB", (1200, altura), "white")
    desenho = ImageDraw.Draw(imagem)
    desenho.rectangle((0, 0, 1200, 140), fill="#15364b")
    desenho.text((36, 25), "10 SUL | NECESSIDADE DE REPOSIÇÃO", font=fonte(32), fill="white")
    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    desenho.text((36, 82), f"Unidade: {unidade}  |  Atualizado em {agora}", font=fonte(23), fill="white")
    y = 165
    for titulo, cor, linhas in grupos:
        desenho.text((36, y), f"{titulo} ({len(linhas)})", font=fonte(26), fill=cor)
        y += 45
        desenho.rectangle((30, y, 1170, y + 40), fill="#eaf0f4")
        for x, texto in ((42, "NI"), (210, "MATERIAL"), (800, "ATUAL"), (920, "LIMITE"), (1040, "REPOR")):
            desenho.text((x, y + 8), texto, font=fonte(19), fill="#15364b")
        y += 40
        if not linhas:
            desenho.text((42, y + 12), "Nenhum item nesta condição.", font=fonte(21), fill="#52616b")
            y += 48
        for indice, (ni, descricao, saldo, limite, repor) in enumerate(linhas):
            h = max(48, len(descricao) * 27 + 16)
            desenho.rectangle((30, y, 1170, y + h), fill="#f5f7f9" if indice % 2 == 0 else "white")
            desenho.text((42, y + 10), ni, font=fonte(21), fill="#243746")
            for n, trecho in enumerate(descricao):
                desenho.text((210, y + 8 + n * 27), trecho, font=fonte(21), fill="#243746")
            for x, numero in ((800, saldo), (920, limite), (1040, repor)):
                desenho.text((x, y + 10), str(numero), font=fonte(22), fill=cor if x == 1040 else "#243746")
            y += h
        y += 25
    desenho.text((36, y), "A lista abaixo do máximo também inclui os itens abaixo do mínimo.",
                 font=fonte(19), fill="#52616b")
    imagem = imagem.crop((0, 0, 1200, y + 50))
    arquivo = BytesIO()
    imagem.save(arquivo, format="PNG")
    return arquivo.getvalue()

@st.dialog("Relatório de reposição", width="large")
def abrir_relatorio_reposicao(dados, unidade):
    png = gerar_imagem_reposicao(dados, unidade)
    st.image(png, use_container_width=True)
    st.download_button("Baixar imagem PNG", png, f"reposicao_{unidade}.png", mime="image/png")


st.title("📦 10 SUL • CONTROLE DE ESTOQUE")
st.caption("Desenvolvido por Evandro Junior")
try:
    base = BaseGitHub()
    base.verificar_privado()
    dados, sha = base.ler()
except ErroEstoque as exc:
    st.error(str(exc))
    st.stop()

normalizar(dados)
unidade = st.selectbox("Unidade para movimentações e limites", UNIDADES, index=2)
if st.button("📷 Relatório para enviar ao cliente", type="primary", use_container_width=True):
    abrir_relatorio_reposicao(dados, unidade)

pagina = st.query_params.get("pagina", "painel")
if pagina not in ("painel", "cadastro", "movimentacao"):
    pagina = "painel"
a, b, c = st.columns(3)
a.link_button("📊 Painel", "?pagina=painel", use_container_width=True)
b.link_button("📋 Cadastro", "?pagina=cadastro", use_container_width=True)
c.link_button("📦 Movimentação", "?pagina=movimentacao", use_container_width=True)

if pagina == "painel":
    st.subheader("Painel de Estoque — " + unidade)
    tabela = itens_tabela(dados)
    criticos = tabela[tabela["SITUAÇÃO"] == "🔴 Abaixo do mínimo"].copy()
    configurados = sum(x["unidades"][unidade].get("minimo") is not None and x["unidades"][unidade].get("maximo") is not None for x in dados["itens"].values())
    a1, a2, a3 = st.columns(3)
    a1.metric("Materiais", len(dados["itens"]))
    a2.metric("Abaixo do mínimo", len(criticos))
    a3.metric("Limites definidos", configurados)
    st.subheader("🔴 Itens abaixo do mínimo")
    if criticos.empty:
        st.success("Nenhum material abaixo do mínimo.")
    else:
        criticos["REPOR ATÉ MÍNIMO"] = criticos["MÍNIMO"] - criticos["SALDO ATUAL"]
        st.dataframe(criticos[["NI", "DESCRIÇÃO", "SALDO ATUAL", "MÍNIMO", "MÁXIMO", "REPOR ATÉ MÍNIMO"]], hide_index=True, use_container_width=True)
        st.download_button("Exportar itens críticos em Excel", exportar_criticos_excel(criticos, unidade), f"estoque_critico_{unidade}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.subheader("Alertas de todas as unidades")
    alertas = []
    for ni, material in dados["itens"].items():
        for u in UNIDADES:
            estoque = material["unidades"][u]
            if situacao(estoque) == "🔴 Abaixo do mínimo":
                alertas.append({"NI": ni, "DESCRIÇÃO": material["descricao"], "UNIDADE": u,
                                "ATUAL": estoque["saldo"], "MÍNIMO": estoque["minimo"],
                                "MÁXIMO": estoque["maximo"]})
    if alertas:
        st.dataframe(pd.DataFrame(alertas), hide_index=True, use_container_width=True)
    else:
        st.info("Nenhum item abaixo do mínimo nas quatro unidades.")
    st.subheader("Consulta geral")
    apenas_criticos = st.checkbox("Mostrar apenas itens abaixo do mínimo")
    st.dataframe(criticos if apenas_criticos else tabela, hide_index=True, use_container_width=True)
elif pagina == "cadastro":
    st.subheader("Cadastro de materiais")
    st.info("A primeira ENTRADA de cada material definirá o estoque inicial.")
    with st.form("cadastro", clear_on_submit=True):
        ni = st.text_input("NI (informado manualmente)")
        descricao = st.text_input("Descrição")
        minimo_novo = st.number_input("Estoque mínimo", min_value=0, step=1)
        maximo_novo = st.number_input("Estoque máximo", min_value=0, step=1)
        gravar = st.form_submit_button("Cadastrar", type="primary")
    if gravar:
        ni, descricao = ni.strip(), descricao.strip()
        if not ni or not descricao:
            st.error("Preencha NI e descrição.")
        elif ni in dados["itens"]:
            st.warning("Este NI já existe; nada foi alterado.")
        elif maximo_novo < minimo_novo:
            st.error("O máximo não pode ser menor que o mínimo.")
        else:
            dados["itens"][ni] = {"descricao": descricao, "estoque_inicial": None, "saldo": 0, "minimo": None, "maximo": None}
            normalizar(dados)
            dados["itens"][ni]["unidades"][unidade].update(minimo=int(minimo_novo), maximo=int(maximo_novo))
            try:
                base.salvar(dados, sha)
                st.success("Material cadastrado.")
                st.rerun()
            except ErroEstoque as exc:
                st.error(str(exc))
    st.subheader("Editar item e limites — " + unidade)
    if dados["itens"]:
        escolhas = {f"{ni} | {item['descricao']}": ni for ni, item in sorted(dados["itens"].items())}
        escolhido_limite = st.selectbox("Material para editar", list(escolhas))
        ni_editar = escolhas[escolhido_limite]
        material = dados["itens"][ni_editar]
        item_limite = material["unidades"][unidade]
        with st.form("limites_" + ni_editar + "_" + unidade):
            descricao_editada = st.text_input("Descrição do item", value=material["descricao"])
            col_min, col_max = st.columns(2)
            minimo = col_min.number_input("Estoque mínimo", min_value=0, value=int(item_limite.get("minimo") or 0), step=1)
            maximo = col_max.number_input("Estoque máximo", min_value=0, value=int(item_limite.get("maximo") or 0), step=1)
            salvar_limites = st.form_submit_button("Salvar alterações", type="primary")
        if salvar_limites:
            if not descricao_editada.strip():
                st.error("Informe a descrição.")
            elif maximo < minimo:
                st.error("O estoque máximo não pode ser menor que o mínimo.")
            else:
                material["descricao"] = descricao_editada.strip()
                item_limite["minimo"] = int(minimo)
                item_limite["maximo"] = int(maximo)
                try:
                    base.salvar(dados, sha)
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
elif pagina == "movimentacao":
    st.subheader("Movimentação")
    tabela = itens_tabela(dados)
    if tabela.empty:
        st.info("Cadastre materiais antes de movimentar.")
    else:
        opcoes = {f"{r['NI']} | {r['DESCRIÇÃO']} | Saldo: {r['SALDO ATUAL']}": r["NI"] for _, r in tabela.iterrows()}
        tipo = st.selectbox("Movimento", ["ENTRADA", "SAÍDA"], key="tipo_movimentacao")
        with st.form("movimentacao_" + tipo, clear_on_submit=True):
            escolhido = st.selectbox("Material", list(opcoes))
            quantidade = st.number_input("Quantidade", min_value=1, step=1)
            go_carreta = ""
            if tipo == "SAÍDA":
                go_carreta = st.text_input("GO da carreta (obrigatório)", placeholder="Ex.: 13795")
            observacao = st.text_input("Observação (opcional)")
            confirmar = st.form_submit_button("Registrar movimentação", type="primary")
        if confirmar:
            try:
                primeira, saldo = registrar(dados, opcoes[escolhido], tipo, int(quantidade), observacao, unidade, go_carreta)
                base.salvar(dados, sha)
                st.success(f"{'Estoque inicial registrado!' if primeira else 'Movimentação registrada!'} Saldo: {saldo}")
                st.rerun()
            except ErroEstoque as exc:
                st.error(str(exc))
    st.subheader("Histórico")
    movimentos = pd.DataFrame(reversed(dados["movimentos"]))
    if not movimentos.empty:
        movimentos["unidade"] = movimentos.get("unidade", pd.Series("COCB", index=movimentos.index)).fillna("COCB")
        movimentos["GO DA CARRETA"] = movimentos.get("go_carreta", pd.Series("", index=movimentos.index)).fillna("")
        movimentos = movimentos.drop(columns=["go_carreta"], errors="ignore")
        movimentos = movimentos[movimentos["unidade"] == unidade]
    st.dataframe(movimentos, use_container_width=True, hide_index=True)
    st.download_button("Exportar histórico", movimentos.to_csv(index=False).encode("utf-8-sig"), "historico_cocb.csv")
