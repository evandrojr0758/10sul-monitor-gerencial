import io
import re
import pandas as pd
import streamlit as st

def _frota(v):
    s = str(v or "").upper().strip()
    m = re.search(r"(?:GO\s*)?(\d{5})", s)
    return m.group(1) if m else ""

def _tipo(v):
    s = str(v or "").upper().strip()
    if "ITR" in s: return "ITR"
    if "REVIS" in s: return "REVISÃO"
    return s

def render_programacao_semanal(base):
    with st.expander("📅 CONFERÊNCIA DA PROGRAMAÇÃO SEMANAL", expanded=False):
        st.caption("Importe o Excel da programação. O cruzamento utiliza a aba GO_PLANO, a frota e o evento da ASN.")
        arquivo = st.file_uploader("Programação semanal (.xlsx)", type=["xlsx"], key="programacao_semanal_excel")
        if arquivo is None:
            st.info("Selecione a planilha da semana para conferir atendimentos e faltas.")
            return
        try:
            plano = pd.read_excel(arquivo, sheet_name="GO_PLANO", header=1)
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
