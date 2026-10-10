"""Imagem do resumo CNP e compartilhamento manual, usando os dados exibidos no monitor."""
import base64
import re
from io import BytesIO
from pathlib import Path
from functools import lru_cache
import pandas as pd


def calcular_medias_monitor(df, agora):
    ESPECIAIS = {"13169", "13241", "11003", "11001", "11007", "11009"}
    def _chave_vinculo_laudo(valor):
        if valor is None or pd.isna(valor):
            return ""
        texto=str(valor).strip()
        if texto.lower() in ("nan","none","null","<na>"):
            return ""
        return re.sub(r"\.0$","",texto)

    def _base_evento(tipo):
        b=df.copy()
        e=b["evento"].fillna("").astype(str).str.upper().str.strip()
        mask=e.eq("ITR") if tipo=="ITR" else e.str.contains("REVIS",na=False)
        b=b[mask & ~b["frota"].isin(ESPECIAIS)].copy()
        b["ini_calc"]=b["inicio"].fillna(b["parada"])
        b["fim_calc"]=b["fim"].fillna(agora)
        b=b[b["ini_calc"].notna() & (b["fim_calc"]>=b["ini_calc"])].copy()
        # Em manutenção só entra após atingir o SLA; liberadas entram normalmente.
        aberto=b["fim"].isna() | b["status"].fillna("").astype(str).str.upper().str.contains("MANUT",na=False)
        total=(b["fim_calc"]-b["ini_calc"]).dt.total_seconds()/3600
        sla=12 if tipo=="ITR" else 24
        return b[(~aberto)|(total>=sla)].copy(), sla
    
    def _quebrar_por_dia(tipo, dias=7):
        b,sla=_base_evento(tipo)
        ini_janela=agora.normalize()-pd.Timedelta(days=dias-1)
        rows=[]
        for _,r in b.iterrows():
            ini=pd.Timestamp(r["ini_calc"]); fim=min(pd.Timestamp(r["fim_calc"]),agora)
            d=max(ini.normalize(),ini_janela)
            while d<=fim.normalize():
                a=max(ini,d)
                z=min(fim,d+pd.Timedelta(days=1))
                h=max(0,(z-a).total_seconds()/3600)
                if h>0: rows.append({"DIA_DT":d,"HORAS":h})
                d+=pd.Timedelta(days=1)
        if not rows:return pd.DataFrame(columns=["DIA_DT","MEDIA_H","DIA"]),None,sla
        q=pd.DataFrame(rows)
        g=q.groupby("DIA_DT",as_index=False)["HORAS"].mean().rename(columns={"HORAS":"MEDIA_H"})
        g["DIA"]=g["DIA_DT"].dt.strftime("%d/%m")
        hoje=g.loc[g["DIA_DT"].eq(agora.normalize()),"MEDIA_H"]
        return g,(float(hoje.iloc[0]) if len(hoje) else None),sla

    def _base_medias_origem(tipo,origem):
        """Médias das OS: datas de laudos não participam deste cálculo."""
        e=df["evento"].fillna("").astype(str).str.strip().str.upper()
        mask=e.eq("ITR") if tipo=="ITR" else e.str.contains("REVIS",na=False)
        b=df[mask & ~df["frota"].isin(ESPECIAIS)].copy()
        b["OS/ID"]=b["os_id"].apply(_chave_vinculo_laudo)
        b["FROTA"]=b["frota"].apply(_chave_vinculo_laudo)
        inicio_col = "parada" if origem == "Suzano" else "inicio"
        fim_col = "fim_asn" if origem == "Suzano" else "fim"
        b["INICIO_CALC"] = pd.to_datetime(b[inicio_col], errors="coerce")
        b["FIM_CALC"] = pd.to_datetime(b[fim_col], errors="coerce")
        base = b[["OS/ID", "FROTA", "INICIO_CALC", "FIM_CALC"]].copy()
        base = base.sort_values("FIM_CALC", na_position="first").drop_duplicates(["OS/ID", "FROTA"], keep="last")
        base=base[base["OS/ID"].ne("") & base["FROTA"].ne("") & base["INICIO_CALC"].notna() & base["FIM_CALC"].notna() & (base["FIM_CALC"]>=base["INICIO_CALC"]) & (base["FIM_CALC"]<=agora)].copy()
        base["HORAS"]=(base["FIM_CALC"]-base["INICIO_CALC"]).dt.total_seconds()/3600
        return base.sort_values("FIM_CALC",ascending=False).reset_index(drop=True)
    
    
    def _recorte_media_origem(base,periodo):
        if periodo=="Mês acumulado":
            inicio=agora.normalize().replace(day=1); fim=agora
            return base[base["FIM_CALC"].between(inicio,fim)].copy()
        dia=agora.normalize()-pd.Timedelta(days=1)
        return base[(base["FIM_CALC"]>=dia)&(base["FIM_CALC"]<dia+pd.Timedelta(days=1))].copy()
    resultado = []
    for tipo in ("ITR", "REVISÃO"):
        diaria, hoje, sla = _quebrar_por_dia(tipo, 7)
        origens = []
        for origem in ("Suzano", "10 Sul"):
            recorte = _recorte_media_origem(_base_medias_origem(tipo, origem), "Mês acumulado")
            origens.append({"origem": origem, "media": recorte["HORAS"].mean() if len(recorte) else None,
                            "quantidade": len(recorte)})
        resultado.append({"tipo": tipo, "sla": sla, "origens": origens, "diaria": diaria})
    return resultado


def calcular_oficina_agora(df):
    """Carretas distintas nas OS em manutenção, ainda sem liberação."""
    status = df["status"].fillna("").astype(str).str.upper()
    abertas = df[status.str.contains("MANUT", na=False) & df["fim"].isna()].copy()
    abertas["_inicio"] = abertas["inicio"].fillna(abertas["parada"])
    abertas = abertas.sort_values("_inicio", ascending=False).drop_duplicates("os_id", keep="first")
    evento = abertas["evento"].fillna("").astype(str).str.upper().str.strip()
    itr = evento.eq("ITR")
    revisao = evento.str.contains("REVIS", na=False)
    sos = evento.str.startswith("SOS", na=False)
    cnp = evento.str.contains("CORRETIVA", na=False) & (
        evento.str.contains("Ñ PROG", na=False) | evento.str.contains("NÃO PROG", na=False) |
        evento.str.contains("NAO PROG", na=False))
    def quantidade(mask=None):
        valores = abertas["frota"] if mask is None else abertas.loc[mask, "frota"]
        valores = valores.fillna("").astype(str).str.strip()
        return int(valores[valores.ne("")].nunique())
    return [("Total", quantidade()), ("ITR", quantidade(itr)), ("Revisão", quantidade(revisao)),
            ("CNP", quantidade(cnp)), ("SOS", quantidade(sos)),
            ("Outros", quantidade(~(itr | revisao | cnp | sos)))]


def calcular_tendencia_sos(df, agora):
    """Mesmos períodos e agrupamento semanal utilizados na tendência CNP."""
    evento = df["evento"].fillna("").astype(str).str.upper().str.strip()
    base = df[evento.str.startswith("SOS", na=False)].copy()
    base["ref"] = base["inicio"].fillna(base["parada"])
    base = base[base["ref"].notna()].copy()
    hoje = agora.normalize()
    mes_ini = hoje.replace(day=1)
    mes_ant_ini = (mes_ini-pd.offsets.MonthBegin(1)).normalize()
    sem_ini = hoje-pd.Timedelta(days=hoje.weekday())
    sem_ant_ini = sem_ini-pd.Timedelta(days=7)
    q_mes = int(((base["ref"] >= mes_ini) & (base["ref"] <= agora)).sum())
    q_mes_ant = int(((base["ref"] >= mes_ant_ini) & (base["ref"] < mes_ini)).sum())
    q_sem = int(((base["ref"] >= sem_ini) & (base["ref"] <= agora)).sum())
    q_sem_ant = int(((base["ref"] >= sem_ant_ini) & (base["ref"] < sem_ini)).sum())
    def delta(a, b):
        return None if b == 0 else (a-b)/b*100
    wk = pd.DataFrame(columns=["SEMANA", "QTD", "LAB"])
    if not base.empty:
        base["SEMANA"] = base["ref"].dt.to_period("W-MON").apply(lambda x: x.start_time)
        wk = base.groupby("SEMANA").size().sort_index().tail(8).reset_index(name="QTD")
        wk["LAB"] = wk["SEMANA"].apply(lambda d: f"S{d.isocalendar().week:02d}")
    return {"q_mes": q_mes, "q_mes_ant": q_mes_ant, "q_sem": q_sem,
            "q_sem_ant": q_sem_ant, "dm": delta(q_mes, q_mes_ant),
            "ds": delta(q_sem, q_sem_ant), "semanas": wk}


def gerar_imagem_resumo(hunt, agora, q_mes, q_mes_ant, q_sem, q_sem_ant, dm, ds, motivos, leitura, medias, oficina, sos):
    from PIL import Image, ImageDraw, ImageFont
    largura = 1200
    imagem = Image.new("RGB", (largura, 4000), "#f3f6fa")
    draw = ImageDraw.Draw(imagem)
    azul, texto, cinza = "#15364b", "#243746", "#667085"

    @lru_cache(maxsize=32)
    def fonte(size, bold=False):
        nome = "monitor_font_bold.b64" if bold else "monitor_font.b64"
        arquivo = Path(__file__).resolve().parent / "assets" / nome
        dados = base64.b64decode(arquivo.read_text(encoding="ascii"), validate=True)
        return ImageFont.truetype(BytesIO(dados), size)

    def txt(x, y, valor, size=24, color=texto, bold=False):
        draw.text((x, y), str(valor), font=fonte(size, bold), fill=color)

    def paragrafo(valor, x, y, width, size=24, color=texto):
        # Quebra pela largura real da fonte para preservar a leitura no celular.
        words = str(valor).split()
        linha = ""
        for word in words:
            proposta = (linha + " " + word).strip()
            if linha and draw.textlength(proposta, font=fonte(size)) > width:
                txt(x, y, linha, size, color)
                y += size + 10
                linha = word
            else:
                linha = proposta
        if linha:
            txt(x, y, linha, size, color)
            y += size + 10
        return y

    def delta(valor):
        if valor is None:
            return "Sem base anterior", cinza
        simbolo, cor = ("↑", "#dc2626") if valor > 0 else ("↓", "#16a34a") if valor < 0 else ("→", cinza)
        return (f"{simbolo} {abs(valor):.1f}%".replace(".", ","), cor)

    def titulo(y, valor):
        txt(60, y, valor, 30, azul, True)
        return y + 54

    draw.rectangle((0, 0, largura, 170), fill=azul)
    txt(50, 32, "10 SUL | MONITOR GERENCIAL", 38, "white", True)
    txt(50, 96, "ARA • Indicadores da manutenção", 25, "white")
    txt(50, 132, "Atualizado em " + agora.strftime("%d/%m/%Y %H:%M") + " • Brasília", 22, "white")

    def hhmm(valor):
        if valor is None or pd.isna(valor):
            return "--:--"
        minutos = max(0, int(round(float(valor) * 60)))
        return f"{minutos//60:02d}:{minutos%60:02d}"


    y = titulo(210, "Carretas em manutenção • agora")
    for indice, (nome, quantidade) in enumerate(oficina):
        x = 50 + indice * 185
        draw.rounded_rectangle((x, y, x + 175, y + 110), radius=12, fill=azul if indice == 0 else "white", outline="#dbe3ec", width=1)
        cor = "white" if indice == 0 else azul
        for yy, valor, size in ((y + 12, quantidade, 40), (y + 68, nome, 23)):
            xx = x + (175 - draw.textlength(str(valor), font=fonte(size, True))) / 2
            txt(xx, yy, valor, size, cor, True)
    y = paragrafo("Carretas distintas por tipo; uma carreta pode constar em mais de um tipo.",
                  60, y + 124, 1080, 20, cinza) + 18
    y = titulo(y, "Médias de ITR e Revisão • mês acumulado")

    for x, dados in zip((50, 620), medias):
        draw.rounded_rectangle((x, y, x + 530, y + 220), radius=16, fill="white", outline="#dbe3ec", width=2)
        txt(x + 24, y + 16, dados["tipo"] + " • SLA " + hhmm(dados["sla"]), 27, azul, True)
        for indice, origem in enumerate(dados["origens"]):
            yy = y + 65 + indice * 75
            media = origem["media"]
            cor = cinza if media is None or pd.isna(media) else "#16a34a" if media < dados["sla"] else "#dc2626"
            txt(x + 24, yy, origem["origem"], 24, texto, True)
            txt(x + 310, yy - 6, hhmm(media), 32, cor, True)
            txt(x + 24, yy + 32, str(origem["quantidade"]) + " OS no mês", 20, cinza)
    y += 245
    y = paragrafo("Mês pela liberação da OS • médias Suzano e 10 Sul • formato HH:MM.",
                  60, y, 1080, 21, cinza) + 18
    txt(60, y, "Média diária • tempo distribuído por dia • últimos 7 dias", 24, azul, True)
    y += 44
    dias = pd.date_range(agora.normalize()-pd.Timedelta(days=6), agora.normalize())
    draw.rectangle((50, y, 1150, y + 44), fill="#eaf0f4")
    txt(65, y + 8, "Dia", 21, azul, True)
    for indice, dia in enumerate(dias):
        txt(215 + indice * 132, y + 8, dia.strftime("%d/%m"), 21, azul, True)
    y += 44
    for indice, dados in enumerate(medias):
        serie = dados["diaria"].set_index("DIA_DT")["MEDIA_H"]
        draw.rectangle((50, y, 1150, y + 44), fill="white" if indice == 0 else "#edf2f6")
        txt(65, y + 8, dados["tipo"], 21, azul, True)
        for coluna, dia in enumerate(dias):
            valor = serie.get(dia)
            cor = cinza if valor is None or pd.isna(valor) else "#dc2626" if valor >= dados["sla"] else "#16a34a"
            txt(215 + coluna * 132, y + 8, hhmm(valor), 21, cor, True)
        y += 44
    y += 32
    y = titulo(y, "Tendências • CNP e SOS")
    cnp = {"q_mes": q_mes, "q_mes_ant": q_mes_ant, "q_sem": q_sem,
           "q_sem_ant": q_sem_ant, "dm": dm, "ds": ds}
    for x, nome, dados in ((50, "CNP", cnp), (620, "SOS", sos)):
        draw.rounded_rectangle((x, y, x + 530, y + 220), radius=16, fill="white", outline="#dbe3ec", width=2)
        txt(x + 24, y + 12, nome, 27, azul, True)
        for deslocamento, periodo, campo, anterior, dcampo in (
            (24, "Mês", "q_mes", "q_mes_ant", "dm"),
            (290, "Semana", "q_sem", "q_sem_ant", "ds"),
        ):
            xx = x + deslocamento
            txt(xx, y + 57, periodo, 23, texto, True)
            txt(xx, y + 86, dados[campo], 43, azul, True)
            txt(xx, y + 140, f"vs. {dados[anterior]} anterior", 20, cinza)
            valor, cor = delta(dados[dcampo])
            txt(xx, y + 172, valor, 23, cor, True)
    y += 240
    y = paragrafo("Comparação com mês e semana anteriores completos.",
                  60, y, 1080, 21, cinza) + 20
    wk_cnp = pd.DataFrame(columns=["SEMANA", "QTD", "LAB"])
    if not hunt.empty:
        tw = hunt.copy()
        tw["SEMANA"] = tw["ref"].dt.to_period("W-MON").apply(lambda x: x.start_time)
        wk_cnp = tw.groupby("SEMANA").size().sort_index().tail(8).reset_index(name="QTD")
        wk_cnp["LAB"] = wk_cnp["SEMANA"].apply(lambda d: f"S{d.isocalendar().week:02d}")
    for x, nome, wk, cor_linha in ((50, "CNP", wk_cnp, "#2583f7"), (620, "SOS", sos["semanas"], "#128c7e")):
        draw.rounded_rectangle((x, y, x + 530, y + 270), radius=16, fill="white")
        txt(x + 20, y + 12, nome + " • últimas 8 semanas com registros", 20, azul, True)
        if wk.empty:
            txt(x + 20, y + 110, "Sem dados no período.", 22, cinza)
            continue
        left, right, top, bottom = x + 55, x + 500, y + 72, y + 217
        maior = max(1, int(wk["QTD"].max()))
        for frac in (0, .5, 1):
            yy = bottom - frac * (bottom - top)
            draw.line((left, yy, right, yy), fill="#dbe3ec", width=2)
            txt(x + 10, yy - 9, round(maior * frac), 15, cinza)
        pontos = []
        for i, row in wk.iterrows():
            xx = (left + right) / 2 if len(wk) == 1 else left + i * (right - left) / (len(wk) - 1)
            yy = bottom - int(row["QTD"]) / maior * (bottom - top)
            pontos.append((xx, yy))
            txt(xx - 18, bottom + 18, row["LAB"], 16, cinza)
            txt(xx - 16, yy - 25, int(row["QTD"]), 18, azul, True)
        if len(pontos) > 1:
            draw.line(pontos, fill=cor_linha, width=4)
        for xx, yy in pontos:
            draw.ellipse((xx - 5, yy - 5, xx + 5, yy + 5), fill=cor_linha)
    y += 300

    y = titulo(y + 12, "Principais motivos das CNP — semana")
    draw.rectangle((50, y, 1150, y + 48), fill="#eaf0f4")
    txt(70, y + 9, "Motivo", 23, azul, True)
    txt(770, y + 9, "Qtde.", 23, azul, True)
    txt(920, y + 9, "Variação", 23, azul, True)
    y += 48
    for i, (nome, qtd, dif) in enumerate(motivos[:4]):
        draw.rectangle((50, y, 1150, y + 60), fill="white" if i % 2 == 0 else "#edf2f6")
        txt(70, y + 15, nome, 25)
        txt(785, y + 15, qtd, 25, azul, True)
        seta = "↑" if dif > 0 else "↓" if dif < 0 else "→"
        cor = "#dc2626" if dif > 0 else "#16a34a" if dif < 0 else cinza
        txt(940, y + 15, f"{seta} {abs(dif)}", 25, cor, True)
        draw.line((50, y + 59, 1150, y + 59), fill="#c6d2dc", width=1)
        y += 60
    y = paragrafo("Variação em relação à semana anterior. Uma OS pode aparecer em mais de um motivo.",
                  60, y + 18, 1080, 21, cinza) + 25
    y = titulo(y, "Leitura do período")
    y = paragrafo(leitura, 60, y, 1080, 25) + 30
    y = titulo(y, "Frotas reincidentes • últimos 30 dias")
    draw.rectangle((50, y, 1150, y + 48), fill="#eaf0f4")
    for x, label in ((70, "Frota"), (435, "Qtde. CNP"), (730, "Última ocorrência")):
        txt(x, y + 9, label, 23, azul, True)
    y += 48
    r30 = hunt[(hunt["ref"] >= agora.normalize()-pd.Timedelta(days=30)) & (hunt["ref"] <= agora)]
    if r30.empty:
        txt(70, y + 15, "Sem dados suficientes para identificar reincidências.", 23, cinza)
        y += 60
    else:
        rr = r30.groupby("frota").agg(QTDE=("ref", "size"), ULTIMA=("ref", "max")).sort_values(
            ["QTDE", "ULTIMA"], ascending=[False, False]).head(3)
        for i, (fr, row) in enumerate(rr.iterrows()):
            draw.rectangle((50, y, 1150, y + 60), fill="white" if i % 2 == 0 else "#edf2f6")
            txt(70, y + 15, fr, 26, azul, True)
            txt(470, y + 15, int(row["QTDE"]), 26)
            txt(730, y + 15, row["ULTIMA"].strftime("%d/%m/%Y"), 26)
            draw.line((50, y + 59, 1150, y + 59), fill="#c6d2dc", width=1)
            y += 60
    txt(60, y + 35, "Desenvolvido por Evandro Junior", 20, cinza)
    imagem = imagem.crop((0, 0, largura, y + 90))
    arquivo = BytesIO()
    imagem.save(arquivo, "PNG")
    return arquivo.getvalue()


def botao_compartilhar_imagem(png):
    import streamlit.components.v1 as components
    imagem_base64 = base64.b64encode(png).decode("ascii")
    html = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<style>
body{margin:0;font-family:Arial,sans-serif}button{width:100%;padding:13px;border:0;border-radius:8px;background:#128c7e;color:white;font-size:16px;cursor:pointer}button:disabled{opacity:.65}p{font-size:13px;color:#52616b;margin:8px 0}
</style>
<button id="share">Compartilhar imagem no WhatsApp</button>
<p id="status" role="status">Escolha o WhatsApp e o contato na tela de compartilhamento.</p>
<script>
const bytes=Uint8Array.from(atob("__PNG__"),c=>c.charCodeAt(0));
const file=new File([bytes],"resumo_monitor_10sul.png",{type:"image/png"});
const button=document.getElementById("share"), status=document.getElementById("status");
const navigators=[navigator];
try { if(window.parent!==window) navigators.unshift(window.parent.navigator); } catch(e) {}
button.onclick=async()=>{
 const sharing=navigators.find(n=>{try{return typeof n.share==="function"&&typeof n.canShare==="function"&&n.canShare({files:[file]});}catch(e){return false;}});
 if(!sharing){status.textContent="Este navegador não permite compartilhar imagens diretamente. Use Baixar imagem PNG e anexe no WhatsApp.";return;}
 button.disabled=true;
 try{
  await sharing.share({files:[file],title:"10 SUL — Resumo do Monitor Gerencial"});
  status.textContent="Imagem compartilhada com o aplicativo escolhido.";
 }catch(e){
  status.textContent=e.name==="AbortError"?"Compartilhamento cancelado. Você pode tentar novamente.":"Não foi possível abrir o compartilhamento. Use Baixar imagem PNG e anexe no WhatsApp.";
 }finally{button.disabled=false;}
};
</script></html>""".replace("__PNG__", imagem_base64)
    components.html(html, height=130, scrolling=False)
