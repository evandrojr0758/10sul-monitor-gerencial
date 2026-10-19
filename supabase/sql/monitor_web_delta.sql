-- Read-only incremental feed. SECURITY INVOKER preserves the caller's table grants/RLS.
create or replace function public.monitor_web_delta(
  p_table text, p_since date, p_known jsonb default '{}'::jsonb,
  p_open_ids text[] default '{}'::text[]
) returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare result jsonb;
begin
  if p_table not in ('monitor_asn', 'monitor_atendimentos') or p_table is null then
    raise exception 'Tabela inválida';
  end if;
  if p_since is null or p_since < date '2026-01-01' or jsonb_typeof(p_known) <> 'object' or p_known is null then
    raise exception 'Parâmetros inválidos';
  end if;
  with source as materialized (
    select to_jsonb(a) as row_data from public.monitor_asn a
    where p_table = 'monitor_asn' and a.unidade = 'ARA'
      and coalesce(a.parada,a.inicio) >= timestamp '2026-01-01'
      and (coalesce(a.parada,a.inicio) >= p_since or a.status ilike '%MANUT%' or a.os_id = any(p_open_ids) or p_known ? jsonb_build_array(a.os_id,a.frota)::text)
    union all
    select to_jsonb(h) from public.monitor_atendimentos h
    where p_table = 'monitor_atendimentos' and h.unidade = 'ARA'
      and coalesce(h.parada,h.inicio) >= timestamp '2026-01-01'
      and (coalesce(h.parada,h.inicio) >= p_since or h.status ilike '%MANUT%' or h.os_id = any(p_open_ids) or p_known ? jsonb_build_array(h.os_id,h.frota)::text)
  ), current_rows as materialized (
    select distinct on (row_data->>'os_id',row_data->>'frota')
      jsonb_build_array(row_data->>'os_id',row_data->>'frota')::text as key,
      md5((row_data - 'sincronizado_em')::text) as hash, row_data
    from source order by row_data->>'os_id',row_data->>'frota',(row_data->>'id')::bigint desc nulls last
  )
  select jsonb_build_object(
    'changed', coalesce((select jsonb_agg(jsonb_build_object('key',key,'hash',hash,'row',row_data))
      from current_rows where p_known->>key is distinct from hash),'[]'::jsonb),
    'removed', coalesce((select jsonb_agg(k) from jsonb_object_keys(p_known) as known(k)
      where not exists(select 1 from current_rows c where c.key=k)),'[]'::jsonb),
    'sincronizado_em', (select max(row_data->>'sincronizado_em') from current_rows)
  ) into result;
  return result;
end;
$$;
revoke all on function public.monitor_web_delta(text,date,jsonb,text[]) from public;
grant execute on function public.monitor_web_delta(text,date,jsonb,text[]) to anon, authenticated, service_role;
notify pgrst, 'reload schema';
