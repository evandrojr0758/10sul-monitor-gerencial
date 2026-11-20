"""Consultas do Histórico de Manutenção de Aracruz."""

import pandas as pd
import psycopg
from psycopg import sql


_RECORTE = """
    unidade = 'ARA'
    AND (parada >= DATE '2026-01-01'
         OR (parada IS NULL AND inicio >= DATE '2026-01-01'))
"""
_FROTA = r"regexp_replace(regexp_replace(frota::text, '^\s+|\s+$', '', 'g'), '\.0$', '')"
_OS = _FROTA.replace("frota::text", "os_id::text")
_RECORTAR_FROTA = sql.SQL("""
    SELECT to_jsonb(registro)
    FROM public.{tabela} AS registro
    WHERE {recorte} AND {frota} = %s
    ORDER BY os_id, frota
""")

# Igual à combinação do histórico completo: a ASN prevalece no evento,
# parada e exclusão (inclusive valores nulos), e o início salvo tem prioridade.
_SQL_RESUMO = r"""
    WITH historico AS (
        SELECT DISTINCT ON (os_normalizada, frota_normalizada)
            {os} AS os_normalizada, {frota} AS frota_normalizada,
            evento, parada, inicio, liberacao_10sul AT TIME ZONE 'America/Sao_Paulo' AS liberacao
        FROM public.monitor_atendimentos
        WHERE {recorte}
          AND regexp_replace(upper({frota}), '^GO\s*', '') = ANY(%s)
        ORDER BY os_normalizada, frota_normalizada, os_id DESC, frota DESC
    ),
    asn AS (
        SELECT DISTINCT ON (os_normalizada, frota_normalizada)
            {os} AS os_normalizada, {frota} AS frota_normalizada,
            evento, parada, inicio, fim, excluida_asn_em
        FROM public.monitor_asn
        WHERE {recorte}
          AND regexp_replace(upper({frota}), '^GO\s*', '') = ANY(%s)
        ORDER BY os_normalizada, frota_normalizada, os_id DESC, frota DESC
    ),
    servicos AS (
        SELECT regexp_replace(upper(coalesce(a.frota_normalizada, h.frota_normalizada)), '^GO\s*', '') AS frota,
            upper(btrim(coalesce(CASE WHEN a.os_normalizada IS NOT NULL THEN a.evento ELSE h.evento END, ''))) AS evento,
            coalesce(CASE WHEN a.os_normalizada IS NOT NULL THEN a.parada ELSE h.parada END, h.inicio, a.inicio) AS parada,
            coalesce(a.fim, h.liberacao) AS fim
        FROM historico h
        FULL JOIN asn a USING (os_normalizada, frota_normalizada)
        WHERE a.excluida_asn_em IS NULL
    )
    SELECT frota, max(coalesce(fim, parada)) AS ultimo_servico
    FROM servicos
    WHERE (evento = 'ITR' OR evento LIKE '%%REVIS%%'
           OR regexp_replace(evento, '[^A-Z0-9]', '', 'g') LIKE '%%PITSTOP%%')
      AND parada <= %s AND coalesce(fim, parada) <= %s
    GROUP BY frota
    HAVING max(coalesce(fim, parada))::date <= %s
""".format(os=_OS, frota=_FROTA, recorte=_RECORTE)


def ler_historico(database_url, frota):
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        lotes = []
        for tabela in ("monitor_atendimentos", "monitor_asn"):
            consulta = _RECORTAR_FROTA.format(
                tabela=sql.Identifier(tabela), recorte=sql.SQL(_RECORTE), frota=sql.SQL(_FROTA)
            )
            lotes.append(pd.DataFrame.from_records(linha[0] for linha in conn.execute(consulta, (frota,))))
    return tuple(lotes)


def ler_resumo(database_url, frotas_ativas, agora):
    frotas = sorted(frotas_ativas)
    agora = agora.to_pydatetime()
    limite = (pd.Timestamp(agora) - pd.Timedelta(days=8)).date()
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        linhas = conn.execute(_SQL_RESUMO, (frotas, frotas, agora, agora, limite)).fetchall()
        ultima_sincronizacao = conn.execute(
            "SELECT max(sincronizado_em) FROM public.monitor_asn WHERE " + _RECORTE
        ).fetchone()[0]
    resumo = pd.DataFrame.from_records(linhas, columns=['Frota', 'Último serviço válido'])
    datas = pd.to_datetime(resumo['Último serviço válido'])
    resumo['Dias sem serviço'] = (pd.Timestamp(agora).normalize() - datas.dt.normalize()).dt.days
    resumo['Dias de atraso'] = resumo['Dias sem serviço'] - 7
    return resumo.sort_values(['Dias sem serviço', 'Frota'], ascending=[False, True], ignore_index=True), ultima_sincronizacao
