"""Página independente dentro do aplicativo de estoque existente."""
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pneus_core import CAMPOS, emails_validos, validar_itens, relatorio, enviar_email


def renderizar(st, BaseGitHub, ErroEstoque):
    import base64
    import json
    from urllib.parse import quote
    class BasePneus(BaseGitHub):
        def __init__(self):
            super().__init__()
            self.path = "/contents/dados/estoque_pneus.json"

        def ler(self):
            arquivo = self.requisitar(self.path + "?ref=" + quote(self.branch, safe=""))
            if arquivo is None:
                return {"schema": 1, "conferencias": [], "email": {"destinatarios": [], "horario": "18:00", "ativo": False}, "envios": []}, None
            try:
                dados = json.loads(base64.b64decode(arquivo["content"]))
                if dados.get("schema") != 1 or not isinstance(dados.get("conferencias"), list):
                    raise ValueError()
                return dados, arquivo["sha"]
            except (ValueError, TypeError, KeyError):
                raise ErroEstoque("Base de pneus inválida. Nenhuma informação foi alterada.") from None

    st.title("10 SUL · Estoque de pneus")
    st.caption("Desenvolvido por Evandro Junior")
    st.markdown('<style>.block-container{max-width:1000px;padding-top:1.5rem} [data-testid="stForm"]{border-radius:16px}</style>', unsafe_allow_html=True)
    try:
        base = BasePneus()
        base.verificar_privado()
        dados, sha = base.ler()
    except ErroEstoque as exc:
        st.error(str(exc))
        return
    if st.session_state.pop("pneus_salvo", False):
        st.success("Conferência gravada. Consulte o registro no histórico.")
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    lancamento, historico, email = st.tabs(["Lançar estoque", "Histórico", "E-mail"])
    with lancamento:
        st.info("Registre o estoque contado neste horário. Campo vazio significa não informado; use 0 quando não houver pneus.")
        with st.form("conferencia_pneus", clear_on_submit=True):
            a, b = st.columns(2)
            data = a.date_input("Data da conferência", value=agora.date(), max_value=agora.date())
            hora = b.time_input("Horário da conferência", value=agora.time().replace(second=0, microsecond=0))
            responsavel = st.text_input("Responsável pela conferência", placeholder="Nome de quem contou o estoque", max_chars=100)
            itens = {}
            anterior = None
            for chave, medida, categoria in CAMPOS:
                if medida != anterior:
                    st.subheader(medida)
                    anterior = medida
                a, b = st.columns([1, 2])
                quantidade = a.text_input(categoria, key="q_" + chave, placeholder="Quantidade")
                observacao = b.text_input("Observação · " + categoria, key="obs_" + chave, placeholder="Ex.: +1 SOS", max_chars=500)
                itens[chave] = {"quantidade": quantidade.strip(), "observacao": observacao.strip()}
            gravar = st.form_submit_button("Gravar conferência", type="primary", use_container_width=True)
        if gravar:
            try:
                momento = datetime.combine(data, hora, tzinfo=ZoneInfo("America/Sao_Paulo"))
                if momento > agora:
                    raise ValueError("A conferência não pode ter horário futuro.")
                if not responsavel.strip():
                    raise ValueError("Informe o responsável pela conferência.")
                for item in itens.values():
                    n = item["quantidade"]
                    if n and (not n.isascii() or not n.isdigit()):
                        raise ValueError("Preencha a quantidade apenas com números; coloque informações de SOS na observação.")
                    item["quantidade"] = int(n) if n else None
                validar_itens(itens)
                horario = momento.isoformat(timespec="minutes")
                dados, sha = base.ler()
                if any(x["data_hora"] == horario for x in dados["conferencias"]):
                    raise ValueError("Já existe uma conferência neste dia e horário. Consulte o histórico.")
                dados["conferencias"].append({"id": str(uuid.uuid4()), "data_hora": horario, "responsavel": responsavel.strip(), "itens": itens, "gravado_em": agora.isoformat()})
                base.salvar(dados, sha)
                st.session_state["pneus_salvo"] = True
                st.rerun()
            except (ErroEstoque, ValueError) as exc:
                st.error(str(exc))
    registros = sorted(dados["conferencias"], key=lambda x: x["data_hora"], reverse=True)
    with historico:
        if not registros:
            st.info("Nenhuma conferência registrada.")
        else:
            dia = st.date_input("Consultar dia", value=datetime.fromisoformat(registros[0]["data_hora"]).date())
            opcoes = [r for r in registros if r["data_hora"][:10] == dia.isoformat()]
            if not opcoes:
                st.info("Nenhum lançamento neste dia.")
            else:
                idx = st.selectbox("Conferência", range(len(opcoes)), format_func=lambda i: opcoes[i]["data_hora"][11:16] + " · " + opcoes[i]["responsavel"])
                registro = opcoes[idx]
                linhas = [{"Pneu": medida, "Categoria": categoria, "Quantidade": "Não informado" if registro["itens"][chave]["quantidade"] is None else str(registro["itens"][chave]["quantidade"]), "Observação": registro["itens"][chave]["observacao"]} for chave, medida, categoria in CAMPOS]
                total = sum(x["quantidade"] or 0 for x in registro["itens"].values())
                st.metric("Total informado", total)
                st.dataframe(linhas, hide_index=True, use_container_width=True)
                st.caption("Observações como +1 SOS não são somadas automaticamente ao total.")
                txt, html = relatorio(registro)
                st.download_button("Baixar relatório", html.encode(), "estoque_pneus_" + dia.isoformat() + ".html", "text/html")
    with email:
        cfg = dados.get("email", {})
        if dados.get("envios"):
            st.write("Últimos envios automáticos")
            st.dataframe([{"Data": x["dia"], "Situação": x["estado"], "Destinatários": "; ".join(x.get("destinatarios", []))} for x in reversed(dados["envios"][-10:])], hide_index=True, use_container_width=True)
        st.write("O envio diário utiliza a última conferência do dia. Sem lançamento no dia, nenhum estoque antigo será enviado.")
        st.caption("O envio automático exige configurar a conta remetente e o serviço de agendamento. Salvar destinatários não ativa o serviço.")
        with st.form("email_pneus"):
            destinatarios = st.text_area("Destinatários padrão", value="; ".join(cfg.get("destinatarios", [])), placeholder="email@empresa.com; outro@empresa.com")
            horario = st.time_input("Horário diário · Brasília", value=time.fromisoformat(cfg.get("horario", "18:00")))
            ativo = st.checkbox("Autorizar envio automático diário quando o serviço estiver configurado", value=cfg.get("ativo", False))
            salvar = st.form_submit_button("Salvar configuração", type="primary")
        if salvar:
            try:
                lista = emails_validos(destinatarios)
                if ativo and not lista:
                    raise ValueError("Informe destinatários antes de autorizar o envio.")
                dados, sha = base.ler()
                dados["email"] = {"destinatarios": lista, "horario": horario.strftime("%H:%M"), "ativo": ativo}
                base.salvar(dados, sha)
                st.success("Configuração salva.")
            except (ValueError, ErroEstoque) as exc:
                st.error(str(exc))
        st.subheader("Enviar agora")
        adicionais = st.text_input("Destinatários adicionais neste envio", placeholder="Opcional")
        if st.button("Enviar última conferência por e-mail", disabled=not registros):
            try:
                atuais, _ = base.ler()
                lista = emails_validos(";".join(atuais.get("email", {}).get("destinatarios", [])) + ";" + adicionais)
                enviar_email(registros[0], lista, dict(st.secrets))
                st.success("Relatório aceito pelo servidor de e-mail.")
            except (ValueError, OSError) as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else "Falha de conexão com o servidor de e-mail. Confira a configuração do remetente.")
