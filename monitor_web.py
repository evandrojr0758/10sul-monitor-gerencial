import os
import re
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from monitor_delta import MonitorDeltaCache

HISTORICO_ONLY = st.query_params.get("pagina", "") == "historico"
MOBILE_READ_ONLY = HISTORICO_ONLY or bool(globals().get("MOBILE_READ_ONLY", False)) or st.query_params.get("mobile", "0") == "1"
st.set_page_config(page_title="10 Sul • Histórico de manutenção" if HISTORICO_ONLY else "10 Sul • Consulta Mobile" if MOBILE_READ_ONLY else "Monitor Gerencial 10 Sul", page_icon="📊", layout="wide")

_registrar_baixa_whatsapp = components.declare_component(
    "registrar_baixa_whatsapp", path=str(Path(__file__).parent / "whatsapp_liberacao")
)

def _secret(nome):
    try:
        return str(st.secrets[nome]).strip()
    except Exception:
        return os.getenv(nome, "").strip()

SUPABASE_URL = _secret("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = _secret("SUPABASE_KEY")

ESPECIAIS = {"13169","13241","11003","11001","11007","11009"}

st.markdown("""
<style>
.block-container{max-width:1600px;padding-top:1.2rem;padding-bottom:2rem}
#MainMenu,footer,header{visibility:hidden}
.mon-title{font-size:27px;font-weight:900;color:#10284a;margin-bottom:2px}
.mon-sub{font-size:12px;color:#667085;margin-bottom:14px}
.mon-section{background:#f4f9ff;border-left:5px solid #2583f7;border-radius:12px;padding:14px 18px;margin:16px 0 12px}
.mon-section-title{font-size:19px;font-weight:900;color:#10284a}
.mon-section-sub{font-size:12px;color:#667085;margin-top:4px}
.kpi{border:1px solid #dbe3ec;background:#f4f9ff;border-radius:11px;min-height:90px;padding:13px 8px;text-align:center}
.kpi-red{background:#fff2f4;border-color:#f7d8dd;color:#7f1d1d}
.kpi-orange{background:#fff8ef;border-color:#f3e4cf}
.kpi-n{font-size:24px;font-weight:900;line-height:1.05}
.kpi-l{font-size:12px;font-weight:800;margin-top:10px}
div[data-testid="stButton"] > button[kind="secondary"]{min-height:90px;border-radius:11px;font-weight:850;white-space:pre-line;font-size:14px}
.card{border:1px solid #dbe3ec;border-radius:12px;padding:14px;background:white}
.card-title{text-align:center;font-size:16px;font-weight:850;color:#10284a;margin-bottom:6px}
.card-center{text-align:center;font-size:13px}
.caption{font-size:12px;color:#667085;margin-top:5px}
.hunt-title{font-size:16px;font-weight:850;color:#10284a;margin-bottom:9px}
.hunt-kpi{font-size:30px;font-weight:900}
.hunt-compare{font-size:12px;color:#667085;margin-top:2px}
.up{color:#dc2626;font-weight:800}.down{color:#16a34a;font-weight:800}.flat{color:#667085;font-weight:800}
.top-card{border:1px solid #f0cfd4;border-radius:12px;padding:13px;background:#fff8f9;min-height:145px}
.top-title{font-size:13px;font-weight:850;color:#7f1d1d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.top-row{display:flex;justify-content:space-between;border-top:1px solid #f1dfe2;padding:7px 2px;font-size:13px}
.reinc-head,.reinc-row{display:grid;grid-template-columns:1fr 90px 125px;gap:8px;padding:7px 8px}
.reinc-head{background:#eef1f5;font-size:12px;font-weight:700;color:#667085}
.reinc-row{border-bottom:1px solid #e8edf2;font-size:13px}

@media (max-width: 768px) {
  .block-container{padding-left:.65rem!important;padding-right:.65rem!important;padding-top:.65rem!important;max-width:100%!important}
  .mon-title{font-size:1.35rem!important}.mon-sub{font-size:.78rem!important}
  .mon-section{padding:12px!important;margin-top:12px!important}.mon-section-title{font-size:.95rem!important}
  div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
  div[data-testid="column"]{min-width:100%!important;width:100%!important;flex:1 1 100%!important}
  div[data-testid="stDataFrame"]{max-width:100%!important;overflow-x:auto!important}
  div[role="dialog"]{width:calc(100vw - 18px)!important;max-width:calc(100vw - 18px)!important;margin:9px!important}
}

/* Painel de desempenho do supervisor: compacto no topo */
div[data-testid="stVegaLiteChart"]{margin-top:-4px;margin-bottom:-8px}
@media (max-width: 768px) {
  div[data-testid="stVegaLiteChart"]{width:100%!important;max-width:100%!important}
}
</style>
""", unsafe_allow_html=True)

def api_get(table, params=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados nos Secrets.")
    url=f"{SUPABASE_URL}/rest/v1/{table}"
    headers={"apikey":SUPABASE_KEY, "Authorization":f"Bearer {SUPABASE_KEY}"}
    r=requests.get(url,headers=headers,params=params or {},timeout=45)
    if not r.ok:
        raise RuntimeError(f"Supabase HTTP {r.status_code}: {r.text[:800]}")
    return r.json()

def api_post(path, payload):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados nos Secrets.")
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{path}",
                      headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
