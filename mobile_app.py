"""Entrada independente de consulta, usando as regras do monitor existente."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("monitor_web.py")),
               init_globals={"MOBILE_READ_ONLY": True})
