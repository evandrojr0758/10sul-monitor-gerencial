-- Banco LOCAL SQLite. Uma consulta por execução. Cópias cloud_* não alteram a origem.
-- OS atuais da integração ASN (depois da primeira sincronização):
SELECT os_id, frota, unidade, evento, parada, local_manutencao
FROM cloud_monitor_asn
WHERE _source_present = 1 AND excluida_asn_em IS NULL
  AND upper(status) LIKE '%MANUT%' AND fim IS NULL
ORDER BY parada;

-- Histórico completo de alterações capturadas no computador:
SELECT changed_at, actor, table_name, action, row_key, before_json, after_json
FROM change_history ORDER BY id DESC;

-- Alterações de uma frota. JSON válido armazenado nas versões anteriores e novas:
SELECT * FROM change_history
WHERE json_extract(after_json, '$.frota') = '12345'
   OR json_extract(before_json, '$.frota') = '12345'
ORDER BY id DESC;

-- Todas as execuções da manutenção SQL, inclusive falhas:
SELECT * FROM sql_history ORDER BY id DESC;

-- Origem e data das cópias consultáveis offline:
SELECT * FROM source_catalog ORDER BY module, table_name;

-- Movimentações de veículos que já foram baixadas:
SELECT * FROM cloud_movimentacoes WHERE _source_present = 1;

-- Financeiro: valores são CENTAVOS; divide por 100 só na apresentação:
SELECT substr(date,1,7) AS mes, kind, round(sum(cents)/100.0,2) AS valor
FROM cloud_finance_entries
WHERE _source_present = 1 AND cancelled = 0
GROUP BY substr(date,1,7),kind ORDER BY mes,kind;

-- Financeiro: trilha original por lançamento recebida com o perfil conectado:
SELECT * FROM cloud_finance_audit ORDER BY created_at DESC;
