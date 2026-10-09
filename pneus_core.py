"""Conferências de pneus e relatórios. Sem dependências de interface."""
import html
import re
import smtplib
import ssl
from email.message import EmailMessage

CAMPOS = (
    ("385_novo", "385/65", "Novos"),
    ("385_reformado", "385/65", "Reformados"),
    ("385_apv", "385/65", "APV"),
    ("295_novo", "295/80", "Novos"),
    ("295_reformado", "295/80", "Reformados"),
    ("295_apv", "295/80", "APV"),
    ("tracao_novo", "Tração", "Novos"),
    ("tracao_reformado", "Tração", "Reformados"),
)


def emails_validos(texto):
    emails = list(dict.fromkeys(x.strip() for x in re.split(r"[;,\s]+", texto) if x.strip()))
    if any(not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", x) for x in emails):
        raise ValueError("Informe e-mails válidos, separados por vírgula ou ponto e vírgula.")
    return emails


def validar_itens(itens):
    if set(itens) != {x[0] for x in CAMPOS}:
        raise ValueError("Conferência incompleta.")
    for item in itens.values():
        n = item.get("quantidade")
        if n is not None and (type(n) is not int or n < 0):
            raise ValueError("Use quantidades inteiras iguais ou maiores que zero.")
        if len(item.get("observacao", "")) > 500:
            raise ValueError("Observação limitada a 500 caracteres.")
    if all(x["quantidade"] is None for x in itens.values()):
        raise ValueError("Informe pelo menos uma quantidade.")


def relatorio(registro):
    linhas = []
    texto = ["10 SUL — Estoque de pneus", "Conferência: " + registro["data_hora"],
             "Responsável: " + registro["responsavel"], ""]
    total = 0
    ausentes = 0
    for chave, medida, categoria in CAMPOS:
        item = registro["itens"][chave]
        n = item["quantidade"]
        ausentes += n is None
        total += n or 0
        valor = "Não informado" if n is None else str(n)
        obs = item.get("observacao", "")
        texto.append(f"{medida} | {categoria}: {valor}" + (f" — {obs}" if obs else ""))
        linhas.append("<tr>" + "".join(f'<td style="padding:10px;border-bottom:1px solid #dbe3ea">{html.escape(x)}</td>' for x in (medida, categoria, valor, obs)) + "</tr>")
    rodape = f"Total das quantidades informadas: {total}. Campos não informados: {ausentes}."
    texto.extend(["", rodape, "Observações não são somadas automaticamente às quantidades."])
    corpo = '<div style="font-family:Arial;color:#17384b;max-width:760px"><h2>10 SUL · Estoque de pneus</h2>'
    corpo += '<p>Conferência: ' + html.escape(registro["data_hora"]) + '<br>Responsável: ' + html.escape(registro["responsavel"]) + '</p>'
    corpo += '<table style="border-collapse:collapse;width:100%"><tr style="background:#17384b;color:white">'
    corpo += ''.join(f'<th style="padding:10px;text-align:left">{x}</th>' for x in ("Pneu", "Categoria", "Quantidade", "Observação")) + '</tr>' + ''.join(linhas) + '</table>'
    corpo += '<p><b>' + rodape + '</b></p><p>Observações não são somadas automaticamente às quantidades.</p></div>'
    return "\n".join(texto), corpo


def enviar_email(registro, destinatarios, config):
    if not destinatarios:
        raise ValueError("Informe pelo menos um destinatário.")
    exigidos = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
    if any(not config.get(k) for k in exigidos):
        raise ValueError("Configure a conta remetente: SMTP_HOST, SMTP_USER, SMTP_PASSWORD e SMTP_FROM.")
    texto, corpo = relatorio(registro)
    msg = EmailMessage()
    msg["From"] = config["SMTP_FROM"]
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = "10 SUL | Estoque de pneus | " + registro["data_hora"]
    msg.set_content(texto)
    msg.add_alternative(corpo, subtype="html")
    port = int(config.get("SMTP_PORT") or 587)
    if port == 465:
        servidor = smtplib.SMTP_SSL(config["SMTP_HOST"], port, timeout=30, context=ssl.create_default_context())
    else:
        servidor = smtplib.SMTP(config["SMTP_HOST"], port, timeout=30)
    with servidor as smtp:
        if port != 465:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        recusados = smtp.send_message(msg)
        if recusados:
            raise ValueError("O servidor recusou um ou mais destinatários; confira o envio antes de repetir.")
