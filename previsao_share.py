"""Imagem compacta das previsões de todas as frotas exibidas no card."""
import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=16)
def _fonte(tamanho, negrito=False):
    nome = "monitor_font_bold.b64" if negrito else "monitor_font.b64"
    dados = base64.b64decode((Path(__file__).parent / "assets" / nome).read_text(encoding="ascii"), validate=True)
    return ImageFont.truetype(BytesIO(dados), tamanho)


def _quebrar(texto, largura, fonte, draw):
    linhas, atual = [], ""
    for palavra in str(texto).split():
        proposta = (atual + " " + palavra).strip()
        if draw.textlength(proposta, font=fonte) <= largura:
            atual = proposta
            continue
        if atual:
            linhas.append(atual)
            atual = ""
        for caractere in palavra:
            if atual and draw.textlength(atual + caractere, font=fonte) > largura:
                linhas.append(atual)
                atual = ""
            atual += caractere
    if atual:
        linhas.append(atual)
    return linhas or ["—"]


def gerar_imagem_previsoes(previsoes, agora, resumir_evento):
    if previsoes.empty:
        raise ValueError("Nenhuma frota neste card.")
    largura = 900
    teste = ImageDraw.Draw(Image.new("RGB", (largura, 100)))
    rows = []
    for _, row in previsoes.sort_values(["frota", "evento"]).iterrows():
        evento = resumir_evento(row["evento"])
        if pd.notna(row["previsao"]):
            valor = pd.Timestamp(row["previsao"]).strftime("%d/%m %H:%M")
        else:
            nota = row.get("observacao")
            valor = " ".join(str(nota).split()) if pd.notna(nota) and str(nota).strip() else "—"
        eventos = _quebrar(evento, 140, _fonte(23), teste)
        valores = _quebrar(valor, 520, _fonte(24), teste)
        altura = max(58, max(len(eventos), len(valores)) * 31 + 22)
        rows.append((str(row["frota"]), eventos, valores, altura))
    altura_total = 182 + sum(row[3] for row in rows) + 46
    imagem = Image.new("RGB", (largura, altura_total), "#ffffff")
    draw = ImageDraw.Draw(imagem)
    azul, texto, borda = "#15364b", "#243746", "#dbe4eb"
    draw.rectangle((0, 0, largura, 122), fill=azul)
    draw.text((30, 20), "10 SUL | PREVISÃO DE LIBERAÇÃO", font=_fonte(29, True), fill="white")
    data = pd.Timestamp(agora).strftime("%d/%m %H:%M")
    draw.text((30, 70), f"{len(rows)} frotas • Atualizado em {data}", font=_fonte(21), fill="#d7e5ed")
    draw.rectangle((30, 140, 870, 181), fill="#eaf0f5")
    for x, label in [(42, "FROTA"), (182, "EVENTO"), (342, "PREVISÃO / OBSERVAÇÃO")]:
        draw.text((x, 150), label, font=_fonte(19, True), fill=azul)
    y = 182
    for indice, (frota, eventos, valores, altura) in enumerate(rows):
        if indice % 2:
            draw.rectangle((30, y, 870, y + altura), fill="#f5f8fa")
        draw.text((42, y + 13), frota, font=_fonte(26, True), fill=azul)
        for linha, evento in enumerate(eventos):
            draw.text((182, y + 13 + linha * 31), evento, font=_fonte(23), fill=texto)
        for linha, valor in enumerate(valores):
            draw.text((342, y + 13 + linha * 31), valor, font=_fonte(24), fill=texto)
        y += altura
        draw.line((30, y, 870, y), fill=borda, width=1)
    draw.text((30, y + 14), "Desenvolvido por Evandro Junior", font=_fonte(17), fill="#667085")
    arquivo = BytesIO()
    imagem.save(arquivo, format="PNG", optimize=True)
    return arquivo.getvalue()
