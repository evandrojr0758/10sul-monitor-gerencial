import io
import hashlib
import requests
import re
import pandas as pd
import streamlit as st

def _frota(v):
    if pd.isna(v):
        return ""
    s = str(v).upper().strip()
    s = re.sub('^GO[\\s.:-]*', '', s)
    s = re.sub('\\.0+$', '', s)
    return str(int(s)) if re.fullmatch('[0-9]+', s) else ''

def _tipo(v):
    s = str(v or "").upper().strip()
    if "ITR" in s: return "ITR"
    if "REVIS" in s: return "REVISÃO"
    return s

def render_programacao_semanal(base):
    with st.expander("📅 CONFERÊNCIA DA PROGRAMAÇÃO SEMANAL", expanded=False):
        st.caption("Importe o Excel da programação. O cruzamento utiliza a aba GO_PLANO, a frota e o evento da ASN.")
        arquivo = st.file_uploader("Programação semanal (.xlsx)", type=["xlsx"], key="programacao_semanal_excel")
        import os
        def _secret(nome):
            try:
                return str(st.secrets[nome]).strip()
            except Exception:
                return os.getenv(nome, "").strip()
        url = _secret("SUPABASE_URL").rstrip("/")
        key = _secret("SUPABASE_WRITE_KEY") or _secret("SUPABASE_KEY")
        headers = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith(("sb_secret_", "sb_publishable_")):
            headers["Authorization"] = f"Bearer {key}"
        try:
            response = requests.get(f"{url}/rest/v1/monitor_programacoes_semanais",
                                    headers=headers, params={"select": "id,semana_inicio,nome_arquivo,hash_arquivo,dados",
                                                             "order": "semana_inicio.desc"}, timeout=25)
            response.raise_for_status()
            salvas = response.json()
        except Exception as exc:
            st.error(f"Não foi possível carregar o histórico salvo: {exc}")
            return
        if arquivo is not None:
            conteudo = arquivo.getvalue()
            digest = hashlib.sha256(conteudo).hexdigest()
            if not any(x["hash_arquivo"] == digest for x in salvas):
                if st.button("💾 Salvar programação no histórico", key="salvar_programacao"):
                    try:
                        import json
                        bruto = pd.read_excel(io.BytesIO(conteudo), sheet_name="GO_PLANO", header=1)
                        bruto.columns = [str(c).strip().upper() for c in bruto.columns]
                        if not {"GO", "DATA", "TIPO"}.issubset(bruto.columns):
                            st.error("A aba GO_PLANO precisa conter GO, DATA e TIPO.")
                        else:
                            datas = pd.to_datetime(bruto["DATA"], errors="coerce")
                            numeros = pd.to_numeric(bruto["DATA"], errors="coerce")
                            mask = numeros.between(30000, 80000)
                            datas.loc[mask] = pd.to_datetime(numeros.loc[mask], unit="D", origin="1899-12-30")
                            validas = datas.dropna()
                            if validas.empty:
                                st.error("Não foi encontrada uma data válida na programação.")
                            else:
                                bruto["DATA"] = datas.dt.strftime("%Y-%m-%d")
                                payload = {"semana_inicio": str(validas.min().date()),
                                           "nome_arquivo": arquivo.name, "hash_arquivo": digest,
                                           "dados": bruto.astype(object).where(pd.notna(bruto), None).to_dict(orient="records")}
                                resposta = requests.post(f"{url}/rest/v1/monitor_programacoes_semanais",
                                                         headers={**headers, "Prefer": "return=minimal"},
                                                         json=payload, timeout=35)
                                resposta.raise_for_status()
                                st.success("Programação salva permanentemente.")
                                st.rerun()
                    except Exception as exc:
                        st.error(f"Erro ao salvar programação: {exc}")
            else:
                st.success("Esta planilha já está salva no histórico.")
        if not salvas:
            st.info("Nenhuma programação salva ainda. Importe e clique em Salvar programação.")
            return
        opcoes = {str(x["id"]): f'{x["semana_inicio"]} • {x["nome_arquivo"]}' for x in salvas}
        escolhido = st.selectbox("Programações salvas", list(opcoes), format_func=lambda v: opcoes[v],
                                 key="programacao_salva_escolhida")
        registro_salvo = next(x for x in salvas if str(x["id"]) == escolhido)
        try:
            plano = pd.DataFrame(registro_salvo["dados"])
            plano.columns = [str(c).strip().upper() for c in plano.columns]
            obrigatorias = {"GO", "DATA", "TIPO"}
            if not obrigatorias.issubset(plano.columns):
                st.error("A aba GO_PLANO precisa conter GO, DATA e TIPO.")
                return
            plano = plano.copy()
            plano["FROTA"] = plano["GO"].map(_frota)
            plano["DATA PROGRAMADA"] = pd.to_datetime(plano["DATA"], errors="coerce")
            numeros = pd.to_numeric(plano["DATA"], errors="coerce")
            mask_numeros = numeros.between(30000, 80000)
            plano.loc[mask_numeros, "DATA PROGRAMADA"] = pd.to_datetime(numeros[mask_numeros], unit="D", origin="1899-12-30")
            plano["EVENTO"] = plano["TIPO"].map(_tipo)
            plano = plano.loc[plano["FROTA"].ne("") & plano["DATA PROGRAMADA"].notna()
                              & plano["EVENTO"].isin(["ITR", "REVISÃO"])].copy()
            if plano.empty:
                st.warning("Nenhuma programação válida encontrada.")
                return
            eventos = st.multiselect("Evento", sorted(plano["EVENTO"].unique()),
                                    default=sorted(plano["EVENTO"].unique()), key="programacao_eventos")
            if not eventos:
                st.info("Selecione pelo menos um evento.")
                return
            if "UN" in plano.columns:
                unidades = sorted(plano["UN"].dropna().astype(str).unique())
                unidade = st.multiselect("Unidade", unidades, default=unidades, key="programacao_unidades")
                plano = plano.loc[plano["UN"].astype(str).isin(unidade)].copy()
            plano = plano.loc[plano["EVENTO"].isin(eventos)].copy()
            if plano.empty:
                st.info("Nenhuma programação para esses filtros.")
                return
            dias = st.number_input("Tolerância após a data programada (dias)", min_value=0, max_value=7,
                                   value=0, key="programacao_tolerancia")
            b = base.copy()
            b["FROTA"] = b["frota"].map(_frota)
            b["EVENTO"] = b["evento"].map(_tipo)
            b["INÍCIO"] = pd.to_datetime(b["inicio"], errors="coerce")
            b = b.loc[b["FROTA"].ne("") & b["INÍCIO"].notna() & b["EVENTO"].isin(eventos)].copy()
            if "unidade" in b.columns and "UN" in plano.columns:
                b["UN"] = b["unidade"].fillna("").astype(str).str.upper().str.strip()
            resultados = []
            usados = set()
            for _, p in plano.iterrows():
                ini = p["DATA PROGRAMADA"].normalize()
                fim = ini + pd.Timedelta(days=int(dias) + 1)
                candidatos = b.loc[(b["FROTA"] == p["FROTA"]) & (b["EVENTO"] == p["EVENTO"])
                                    & (b["INÍCIO"] >= ini) & (b["INÍCIO"] < fim)]
                if "UN" in b.columns and "UN" in plano.columns:
                    candidatos = candidatos.loc[candidatos["UN"].eq(str(p["UN"]).upper().strip())]
                candidatos = candidatos.sort_values("INÍCIO")
                registro = candidatos.iloc[0] if not candidatos.empty else None
                if registro is not None:
                    usados.add(registro.name)
                resultados.append({
                    "FROTA": p["FROTA"], "EVENTO": p["EVENTO"],
                    "DATA PROGRAMADA": ini.strftime("%d/%m/%Y"),
                    "UNIDADE": p.get("UN", ""),
                    "SITUAÇÃO": "ATENDIDA" if registro is not None else "NÃO ATENDIDA",
                    "PARADA REAL": registro["INÍCIO"].strftime("%d/%m/%Y %H:%M") if registro is not None else "",
                    "OS": str(registro.get("os_id", "")) if registro is not None else "",
                })
            resultado = pd.DataFrame(resultados)
            atendidas = int(resultado["SITUAÇÃO"].eq("ATENDIDA").sum())
            c1, c2, c3 = st.columns(3)
            c1.metric("Programadas", len(resultado))
            c2.metric("Atendidas", atendidas)
            c3.metric("Não atendidas", len(resultado) - atendidas)
            st.caption("Atendida = parada do mesmo evento na data programada ou dentro da tolerância selecionada. Não atendida = sem registro correspondente na base disponível.")
            st.dataframe(resultado, hide_index=True, use_container_width=True)
            extras = b.loc[~b.index.isin(usados)].copy()
            inicio_semana = plano["DATA PROGRAMADA"].min().normalize()
            fim_semana = plano["DATA PROGRAMADA"].max().normalize() + pd.Timedelta(days=int(dias) + 1)
            extras = extras.loc[(extras["INÍCIO"] >= inicio_semana) & (extras["INÍCIO"] < fim_semana)]
            if not extras.empty:
                st.markdown("**Atendimentos sem correspondência na programação importada**")
                st.dataframe(extras[["FROTA", "EVENTO", "INÍCIO"]], hide_index=True, use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                resultado.to_excel(writer, index=False, sheet_name="Conferência")
                if not extras.empty:
                    extras[["FROTA", "EVENTO", "INÍCIO"]].to_excel(writer, index=False, sheet_name="Fora da programação")
            st.download_button("📥 Exportar conferência Excel", output.getvalue(),
                               file_name="conferencia_programacao_semanal.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="exportar_programacao_semanal")
        except Exception as exc:
            st.error(f"Não foi possível conferir a programação: {exc}")
