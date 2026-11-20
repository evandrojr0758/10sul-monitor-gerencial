"""Leituras incrementais do painel do Monitor no Neon."""

import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


def _tabela(tabela):
    if tabela not in ("monitor_asn", "monitor_atendimentos"):
        raise ValueError("Tabela do Monitor inválida.")
    return sql.Identifier(tabela)


def ler_historico_fixo(database_url, tabela, inicio_recentes):
    consulta = sql.SQL("""
        SELECT to_jsonb(registro)
        FROM public.{} AS registro
        WHERE unidade = 'ARA'
          AND coalesce(parada, inicio) >= DATE '2026-01-01'
          AND coalesce(parada, inicio) < %s::date
        ORDER BY os_id, frota
    """).format(_tabela(tabela))
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        return pd.DataFrame.from_records(row[0] for row in conn.execute(consulta, (inicio_recentes,)))


def ler_delta(database_url, dados):
    consulta = sql.SQL("""
        WITH current_rows AS MATERIALIZED (
            SELECT jsonb_build_array(os_id, frota)::text AS key,
                   md5((to_jsonb(registro) - 'sincronizado_em')::text) AS hash,
                   to_jsonb(registro) AS row_data
            FROM public.{} AS registro
            WHERE unidade = 'ARA'
              AND coalesce(parada, inicio) >= DATE '2026-01-01'
              AND (coalesce(parada, inicio) >= %(desde)s::date
                OR status ILIKE '%%MANUT%%' OR os_id = ANY(%(abertas)s::text[])
                OR %(conhecidas)s::jsonb ? jsonb_build_array(os_id, frota)::text)
        )
        SELECT jsonb_build_object(
            'changed', coalesce((SELECT jsonb_agg(jsonb_build_object('key', key, 'hash', hash, 'row', row_data))
                FROM current_rows WHERE %(conhecidas)s::jsonb ->> key IS DISTINCT FROM hash), '[]'::jsonb),
            'removed', coalesce((SELECT jsonb_agg(k) FROM jsonb_object_keys(%(conhecidas)s::jsonb) AS known(k)
                WHERE NOT EXISTS (SELECT 1 FROM current_rows WHERE key = k)), '[]'::jsonb),
            'sincronizado_em', (SELECT max(row_data->>'sincronizado_em') FROM current_rows)
        )
    """).format(_tabela(dados["p_table"]))
    params = {"desde": dados["p_since"], "abertas": dados["p_open_ids"], "conhecidas": Jsonb(dados["p_known"])}
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        return conn.execute(consulta, params).fetchone()[0]
