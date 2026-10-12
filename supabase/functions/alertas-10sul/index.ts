import postgres from 'npm:postgres@3.4.7';
import {buildPushPayload} from 'npm:@block65/webcrypto-web-push@2.0.0';
import {monitorAlerts, vehicleAlerts, stockAlerts, maintenanceSummary, HOUR, deliveryDue} from './rules.mjs';

const ORIGIN = 'https://central-10sul.peachycrown16.chatgpt.site';
const cors = {'Access-Control-Allow-Origin':ORIGIN,'Access-Control-Allow-Headers':'content-type','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Vary':'Origin'};
const json = (data:unknown,status=200) => new Response(JSON.stringify(data),{status,headers:{...cors,'Content-Type':'application/json','Cache-Control':'no-store'}});
const db = postgres(Deno.env.get('SUPABASE_DB_URL')!,{prepare:false,max:1,idle_timeout:5,connect_timeout:15});
const hash = async (text:string) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))).map(x=>x.toString(16).padStart(2,'0')).join('');
const bytes = (s:string) => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
const validEndpoint = (endpoint:string) => {
  const u = new URL(endpoint);
  return u.protocol==='https:' && !u.username && !u.password && (!u.port || u.port==='443') &&
    (['fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'].includes(u.hostname) || u.hostname.endsWith('.notify.windows.com'));
};
async function secrets(sql:any) {
  const rows = await sql`select name,decrypted_secret as value from vault.decrypted_secrets where name like '10sul_alertas_%'`;
  return Object.fromEntries(rows.map((r:any)=>[r.name,r.value]));
}
async function verifyManager(token:string,secret:string) {
  const [body,signature,...extra] = String(token||'').split('.');
  if (!body || !signature || extra.length) throw new Error('Acesso gerencial não autorizado.');
  const key = await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);
  if (!await crypto.subtle.verify('HMAC',key,bytes(signature),new TextEncoder().encode(body))) throw new Error('Acesso gerencial não autorizado.');
  const grant = JSON.parse(new TextDecoder().decode(bytes(body)));
  if (grant.group!=='veiculos_gerencial' || !Number.isFinite(grant.expires) || grant.expires<Date.now() || !/^[a-f0-9-]{36}$/.test(grant.nonce)) throw new Error('A autorização gerencial expirou.');
  return grant;
}
async function deliver(subscription:any,vapid:any,data:any) {
  const payload = await buildPushPayload({data:{title:data.title,body:String(data.body).slice(0,1000),tag:data.key,url:data.url},options:{ttl:300,urgency:'high'}},subscription,vapid);
  return await fetch(subscription.endpoint,{...payload,redirect:'error',signal:AbortSignal.timeout(12000)});
}
async function run() {
  return await db.begin(async sql=>{
    const [lock] = await sql`select pg_try_advisory_xact_lock(105001105001::bigint) as locked`;
    if (!lock.locked) return {skipped:'Já existe uma verificação em andamento.'};
    const [config] = await sql`select * from alertas_10sul.config where singleton`;
    const s = await secrets(sql); const vapid = JSON.parse(s['10sul_alertas_vapid']);
    const devices = await sql`select * from alertas_10sul.devices where enabled order by created_at`;
    const now=Date.now(); let source:any[]=[];
    const rhDevices = config.mode==='oficina' ? new Map((await sql`select d.device_id,d.activated_at from alertas_10sul.rh_devices d join public.rh_usuarios u on u.id=d.usuario_id where u.ativo=true and upper(u.perfil) in ('RH','ADMIN')`).map(r=>[r.device_id,r.activated_at])) : new Map();
    const warnings = config.mode==='oficina' && rhDevices.size ? await sql`select id,criado_em from public.rh_colaborador_ocorrencias where tipo in ('ADVERTÊNCIA VERBAL','ADVERTÊNCIA ESCRITA') and criado_em>=${config.rh_activated_at} order by criado_em,id` : [];
    if(config.mode==='oficina') source = await sql`
      select a.os_id,a.frota,a.evento,a.status,a.unidade,a.modal,
        to_char(coalesce(h.inicio,a.inicio,a.parada),'YYYY-MM-DD"T"HH24:MI:SS') as inicio,
        to_char(a.parada,'YYYY-MM-DD"T"HH24:MI:SS') as parada,
        a.fim::text as fim_asn,h.liberacao_10sul::text as fim_liberacao_10sul,
        h.previsao_liberacao_10sul::text as previsao_liberacao_10sul
      from public.monitor_asn a left join lateral(select * from public.monitor_atendimentos old where old.os_id=a.os_id and old.frota=a.frota order by id desc limit 1) h on true
      where a.excluida_asn_em is null and upper(trim(a.unidade))='ARA' and upper(a.status) like '%MANUT%' and a.fim is null and h.liberacao_10sul is null`;
    else source = await sql`select id,placa,destino,pessoas,condutor,km_final,status,
      data_hora_saida::text,data_hora_retorno::text from public.movimentacoes
      where status='EM USO' or data_hora_retorno>=${config.activated_at}`;
    const acknowledged = config.mode==='oficina' ? new Set((await sql`select os_id,frota from alertas_10sul.sos_justificativas`).map(r=>`sos:${r.os_id}:${r.frota}`)) : new Set();
    let sent=0,failed=0,expired=0,eligible=0;
    for(const device of devices) {
      const alerts = config.mode==='oficina' ? monitorAlerts(source,now) : vehicleAlerts(source,now,Math.max(new Date(config.activated_at).getTime(),new Date(device.created_at).getTime()));
      if(config.mode==='oficina') {
        alerts.unshift(maintenanceSummary(source,now));
        alerts.push(...stockAlerts(now));
      }
      if(rhDevices.has(device.id)) for(const warning of warnings) {
        if(new Date(warning.criado_em).getTime()<new Date(rhDevices.get(device.id)).getTime()) continue;
        alerts.push({key:`rh:advertencia:${warning.id}`,kind:'rh_advertencia',title:'🔔 PORTAL RH — NOVA ADVERTÊNCIA',body:'Nova advertência registrada no Portal RH. Entre com sua senha para consultar.',url:`https://10sul-app-rh-jacpdfktaczhihbjnuucm2.streamlit.app/?advertencia=${encodeURIComponent(warning.id)}`});
      }
      for(const alert of alerts) {
        if(sent+failed+expired>=40) break;
        if(alert.kind==='sos' && acknowledged.has(alert.key)) continue;
        if(alert.kind==='previsao' && device.last_forecast_at && now-new Date(device.last_forecast_at).getTime()<HOUR) continue;
        const [prior] = await sql`select * from alertas_10sul.deliveries where device_id=${device.id} and alert_key=${alert.key}`;
        if(!deliveryDue(alert,prior,now)) continue;
        eligible++;
        await sql`insert into alertas_10sul.deliveries(device_id,alert_key,kind,attempts,last_attempt_at)
          values(${device.id},${alert.key},${alert.kind},1,now()) on conflict(device_id,alert_key)
          do update set attempts=case when alertas_10sul.deliveries.last_error is null then 1 else alertas_10sul.deliveries.attempts+1 end,last_attempt_at=now()`;
        try {
          const response=await deliver({endpoint:device.endpoint,keys:{p256dh:device.p256dh,auth:device.auth_key}},vapid,alert);
          await response.body?.cancel();
          if(response.status===404 || response.status===410) {
            await sql`update alertas_10sul.devices set enabled=false where id=${device.id}`;expired++;break;
          }
          if(!response.ok) throw new Error(`Push HTTP ${response.status}`);
          await sql`update alertas_10sul.deliveries set sent_at=now(),last_error=null where device_id=${device.id} and alert_key=${alert.key}`;
          if(alert.kind==='previsao') await sql`update alertas_10sul.devices set last_forecast_at=now() where id=${device.id}`;
          sent++;
        } catch(e) {
          await sql`update alertas_10sul.deliveries set last_error=${String(e instanceof Error?e.message:e).slice(0,120)} where device_id=${device.id} and alert_key=${alert.key}`;failed++;
        }
      }
    }
    const result={mode:config.mode,devices:devices.length,source:source.length,eligible,sent,failed,expired};
    await sql`update alertas_10sul.config set last_run_at=now(),last_result=${sql.json(result)} where singleton`;
    return result;
  });
}

Deno.serve(async req=>{
  try {
    const route = new URL(req.url).pathname.split('/').pop();
    if(route==='run') {
      if(req.method!=='POST') return json({error:'Método inválido'},405);
      const s=await secrets(db);
      const supplied=req.headers.get('X-10Sul-Job')||'';
      if(!supplied || await hash(supplied)!==await hash(s['10sul_alertas_job'])) return json({error:'Não autorizado'},401);
      return json(await run());
    }
    if(req.method==='OPTIONS') return new Response(null,{status:204,headers:cors});
    const origin=req.headers.get('Origin');
    if(origin && origin!==ORIGIN) return json({error:'Origem não autorizada'},403);
    if(route==='public-key' && req.method==='GET') {
      const s=await secrets(db); return json({publicKey:JSON.parse(s['10sul_alertas_vapid']).publicKey});
    }
    if(req.method!=='POST' || !['subscribe','unsubscribe','test','sos-details','sos-save','unsubscribe-rh'].includes(route!)) return json({error:'Página não encontrada'},404);
    const raw=await req.text(); if(raw.length>16000) return json({error:'Solicitação muito grande'},413);
    const body=JSON.parse(raw);
    if(typeof body.deviceSecret!=='string' || !/^[a-f0-9]{64}$/.test(body.deviceSecret)) return json({error:'Identificação do celular inválida'},400);
    const manageHash=await hash(body.deviceSecret);
    if(route==='subscribe') {
      const sub=body.subscription;
      if(!sub || typeof sub.endpoint!=='string' || !validEndpoint(sub.endpoint) || bytes(sub.keys?.p256dh||'').length!==65 || bytes(sub.keys?.auth||'').length!==16) return json({error:'Inscrição inválida'},400);
      const s=await secrets(db); const [cfg]=await db`select mode from alertas_10sul.config where singleton`;
      const rhHash=body.rhToken ? await hash(String(body.rhToken)) : null;
      if(body.rhToken && (cfg.mode!=='oficina' || !/^[a-f0-9]{64}$/.test(body.rhToken))) throw Error('Autorização do RH inválida.');
      const grant=cfg.mode==='veiculos' ? await verifyManager(body.managerToken,s['10sul_alertas_manager']) : null;
      return json(await db.begin(async sql=>{
        let rhGrant:any=null;
        if(rhHash) {
          [rhGrant]=await sql`select g.* from public.rh_push_autorizacoes g join public.rh_usuarios u on u.id=g.usuario_id where g.token_hash=${rhHash} and g.expira_em>now() and u.ativo=true and upper(u.perfil) in ('RH','ADMIN') for update of g`;
          if(!rhGrant) throw Error('Autorização do RH inválida ou expirada. Gere outra no portal.');
        }
        const [old]=await sql`select id,manage_hash from alertas_10sul.devices where endpoint=${sub.endpoint} for update`;
        if(old && old.manage_hash!==manageHash) throw new Error('Este celular possui outra inscrição. Desative e reative as notificações no navegador.');
        if(!old) {
          const [count]=await sql`select count(*)::int as n from alertas_10sul.devices where enabled`;
          if(count.n>=1000) throw new Error('Limite de celulares atingido.');
        }
        const [device]=await sql`insert into alertas_10sul.devices(endpoint,p256dh,auth_key,manage_hash)
          values(${sub.endpoint},${sub.keys.p256dh},${sub.keys.auth},${manageHash}) on conflict(endpoint) do update
          set p256dh=excluded.p256dh,auth_key=excluded.auth_key,enabled=true returning id`;
        if(rhGrant) {
          if(rhGrant.device_id && rhGrant.device_id!==device.id) throw Error('Esta autorização do RH já foi usada em outro celular.');
          await sql`update public.rh_push_autorizacoes set device_id=${device.id} where token_hash=${rhHash}`;
          await sql`insert into alertas_10sul.rh_devices(device_id,usuario_id) values(${device.id},${rhGrant.usuario_id}) on conflict(device_id) do update set usuario_id=excluded.usuario_id`;
        }
        if(grant) {
          const [claimed]=await sql`insert into alertas_10sul.manager_grants(nonce,device_id) values(${grant.nonce},${device.id})
            on conflict(nonce) do update set nonce=excluded.nonce returning device_id`;
          if(claimed.device_id!==device.id) throw new Error('Esta autorização gerencial já foi usada em outro celular.');
        }
        return {id:device.id,enabled:true,group:cfg.mode};
      }));
    }
    const [device]=await db`select * from alertas_10sul.devices where id=${body.id} and manage_hash=${manageHash}`;
    if(!device) return json({error:'Inscrição não encontrada'},403);
    if(route==='sos-details' || route==='sos-save') {
      const [cfg]=await db`select mode from alertas_10sul.config where singleton`;
      if(cfg.mode!=='oficina' || !device.enabled) return json({error:'Ative os alertas da oficina neste celular.'},403);
      const os=String(body.os_id||'').trim(), fleet=String(body.frota||'').trim();
      if(!os || !fleet || os.length>100 || fleet.length>100) return json({error:'OS ou frota inválida.'},400);
      return json(await db.begin(async sql=>{
        // Same lock as the sender: acknowledgement cannot race a new delivery.
        await sql`select pg_advisory_xact_lock(105001105001::bigint)`;
        const [a]=await sql`select * from public.monitor_asn where os_id=${os} and frota=${fleet} for update`;
        if(!a || a.unidade?.trim().toUpperCase()!=='ARA' || !a.evento?.trim().toUpperCase().startsWith('SOS')) throw Error('SOS não encontrado.');
        const [h]=await sql`select * from public.monitor_atendimentos where os_id=${os} and frota=${fleet} order by id desc limit 1 for update`;
        const [saved]=await sql`select os_id,frota,responsavel,justificativa,previsao,registrado_em from alertas_10sul.sos_justificativas where os_id=${os} and frota=${fleet}`;
        const active=!a.excluida_asn_em && !a.fim && !h?.liberacao_10sul && String(a.status).toUpperCase().includes('MANUT');
        const details={os_id:os,frota:fleet,evento:a.evento,inicio:h?.inicio||a.inicio||a.parada,active,excluida_asn_em:a.excluida_asn_em||null,saved:saved||null};
        if(route==='sos-details' || saved) return details;
        if(!active) throw Error(a.excluida_asn_em ? 'Esta OS foi excluída na Lista ASN.' : 'Este atendimento já foi liberado.');
        const name=String(body.responsavel||'').trim(), note=String(body.justificativa||'').trim();
        if(name.length<2 || name.length>120 || note.length<5 || note.length>2000) throw Error('Informe responsável e justificativa (mínimo de 5 caracteres).');
        let forecast:string|null=null;
        if(body.sem_previsao!==true) {
          if(typeof body.previsao!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}-03:00$/.test(body.previsao)) throw Error('Informe data e hora da previsão.');
          const time=Date.parse(body.previsao);
          if(!Number.isFinite(time) || time<=Date.now()) throw Error('A previsão deve ser uma data e hora futura.');
          forecast=new Date(time).toISOString();
        }
        const [record]=await sql`insert into alertas_10sul.sos_justificativas(os_id,frota,responsavel,justificativa,previsao,device_id)
          values(${os},${fleet},${name},${note},${forecast},${device.id}) returning os_id,frota,responsavel,justificativa,previsao,registrado_em`;
        const observation=`${note}\nResponsável informado: ${name}${forecast?'':'\nSem previsão de liberação.'}`;
        if(h) await sql`update public.monitor_atendimentos set previsao_liberacao_10sul=${forecast},observacao_previsao_10sul=${observation} where id=${h.id}`;
        else await sql`insert into public.monitor_atendimentos(os_id,frota,evento,status,parada,inicio,descricao,modal,unidade,previsao_liberacao_10sul,observacao_previsao_10sul)
          values(${os},${fleet},${a.evento},${a.status},${a.parada},${a.inicio||a.parada},${a.descricao},${a.modal},${a.unidade},${forecast},${observation})`;
        return {...details,saved:record};
      }));
    }
    if(route==='unsubscribe-rh') {
      await db`delete from alertas_10sul.rh_devices where device_id=${device.id}`;
      return json({enabled:false});
    }
    if(route==='unsubscribe') {
      await db`update alertas_10sul.devices set enabled=false where id=${device.id}`;
      return json({enabled:false});
    }
    const s=await secrets(db); const response=await deliver({endpoint:device.endpoint,keys:{p256dh:device.p256dh,auth:device.auth_key}},JSON.parse(s['10sul_alertas_vapid']),{
      key:'10sul-teste',title:'✅ NOTIFICAÇÕES 10 SUL ATIVADAS',body:'Este celular está pronto para receber os alertas autorizados.',url:ORIGIN});
    await response.body?.cancel();
    return json({sent:response.ok},response.ok?200:502);
  } catch(e) { console.error('Falha alertas 10 Sul:',e instanceof Error?e.message:'erro');return json({error:e instanceof Error?e.message:'Não foi possível concluir a solicitação.'},400); }
});
