"""Leitura da base de Aracruz para a consulta independente de frotas."""

import pandas as pd
import psycopg
from psycopg import sql


def ler_historico(database_url):
    tabelas = ("monitor_atendimentos", "monitor_asn")
    lotes = []
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for tabela in tabelas:
            consulta = sql.SQL("""
                SELECT to_jsonb(registro)
                FROM public.{} AS registro
                WHERE unidade = 'ARA'
                  AND (parada >= DATE '2026-01-01'
                       OR (parada IS NULL AND inicio >= DATE '2026-01-01'))
                ORDER BY os_id, frota
            """).format(sql.Identifier(tabela))
            lotes.append(pd.DataFrame.from_records(linha[0] for linha in conn.execute(consulta)))
    historico, asn = lotes
    return historico, asn
