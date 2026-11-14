"""Cópia de leitura da ASN, alimentada pela integração existente do cliente."""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from core import now,stamp,text,date
from connection_defaults import ASN_URL, ASN_PUBLISHABLE_KEY

SELECT='os_id,frota,evento,status,parada,inicio,fim,descricao,modal,unidade,sincronizado_em,excluida_asn_em,local_manutencao,ausente_abertas_asn_em'

def fetch_snapshot(url=ASN_URL,key=ASN_PUBLISHABLE_KEY,page_size=500,requester=None):
    """Paginação completa e ordenada; nenhuma gravação se uma página falhar."""
    if not url.startswith('https://') or not key:raise ValueError('Configure uma conexão HTTPS de leitura da ASN.')
    if not 1<=page_size<=1000:raise ValueError('Tamanho de página inválido.')
    records=[];seen=set();offset=0;latest=None
    while True:
        query=urllib.parse.urlencode({'select':SELECT,'order':'os_id.asc,frota.asc','limit':str(page_size),'offset':str(offset)})
        req=urllib.request.Request(url.rstrip('/')+'/rest/v1/monitor_asn?'+query,headers={'apikey':key,'Accept':'application/json','Cache-Control':'no-cache'})
        try:
            if requester:page=requester(req)
            else:
                with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as response:page=json.load(response)
        except urllib.error.HTTPError as e:
            raise RuntimeError('A conexão da ASN recusou a consulta. Confira a chave de leitura e as permissões.' if e.code in (401,403) else f'Falha na consulta ASN (HTTP {e.code}). A cópia local foi preservada.') from None
        except Exception as e:
            raise RuntimeError('Sem atualização da ASN. A consulta continua usando a última cópia local.') from None
        if not isinstance(page,list):raise ValueError('Resposta inválida da ASN. Nenhum dado local foi alterado.')
        if not page:break
        for row in page:
            if not isinstance(row,dict) or not text(row.get('os_id')) or not text(row.get('frota')):raise ValueError('A ASN retornou uma OS sem identificação. Cópia local preservada.')
            identity=(text(row['os_id']),text(row['frota']))
            if identity in seen:raise ValueError('A base ASN mudou durante a paginação. A cópia local foi preservada; tente novamente.')
            seen.add(identity);records.append(row)
            at=date(row.get('sincronizado_em'))
            if at and (latest is None or at>latest):latest=at
        offset+=len(page)
        if len(page)<page_size:break
        if offset>1000000:raise ValueError('Consulta excedeu o limite de segurança. Cópia local preservada.')
    if not records:raise ValueError('A ASN retornou uma base vazia. A cópia anterior foi preservada para conferência.')
    return {'records':records,'downloaded_at':stamp(now()),'source_at':stamp(latest),'count':len(records)}

def setup_tables(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS asn_cache(os_id TEXT NOT NULL,frota TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(os_id,frota));
    CREATE TABLE IF NOT EXISTS sync_state(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    ''');store.db.commit()

def sync_state(store):
    row=store.db.execute("SELECT value FROM sync_state WHERE name='asn'").fetchone()
    return json.loads(row[0]) if row else {}

def apply_snapshot(store,snapshot):
    rows=snapshot['records'];normalized=[]
    for raw in rows:
        # Removidas permanecem na auditoria da origem, mas não aparecem como abertas.
        if raw.get('excluida_asn_em'):continue
        r=dict(raw);r['fim_asn']=r.get('fim') or '';r['inicio']=r.get('inicio') or r.get('parada')
        r['parada']=r.get('parada') or r.get('inicio')
        r['parada']=r['parada'] or ''
        r['evento']=r.get('evento') or 'OUTROS'
        normalized.append(r)
    try:
        store.db.execute('BEGIN')
        store.import_orders(normalized,commit=False,source=True)
        for previous in store.db.execute('SELECT * FROM asn_cache').fetchall():
            payload=json.loads(previous['payload']);payload['snapshot_absent']=True
            store.db.execute('UPDATE asn_cache SET payload=? WHERE os_id=? AND frota=?',(json.dumps(payload),previous['os_id'],previous['frota']))
        for r in rows:
            store.db.execute('INSERT INTO asn_cache VALUES (?,?,?) ON CONFLICT(os_id,frota) DO UPDATE SET payload=excluded.payload',(text(r['os_id']),text(r['frota']),json.dumps(r,ensure_ascii=False)))
        from mirrors import mirror_snapshot
        mirror_snapshot(store,'cloud_monitor_asn','Integração ASN',ASN_URL,rows,['os_id','frota'],transaction=False)
        state={k:v for k,v in snapshot.items() if k!='records'}
        state['message']='Atualização concluída';state['applied_at']=stamp(now())
        store.db.execute("INSERT INTO sync_state VALUES ('asn',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(json.dumps(state),))
        store.log('ASN atualizada','monitor_asn',str(len(rows))+' registros consultados; somente leitura')
        store.db.commit();return state
    except Exception:store.db.rollback();raise

def source_rows(store,orders):
    source={ (r['os_id'],r['frota']):json.loads(r['payload']) for r in store.db.execute('SELECT * FROM asn_cache') }
    state=sync_state(store);result=[]
    for r in orders:
        key=(r['os_id'],r['frota'])
        if key in source:
            a=source[key]
            if a.get('excluida_asn_em'):continue
            r['asn_managed']=True;r['asn_status']='Ausente na ASN' if a.get('snapshot_absent') else a.get('status') or '';r['asn_missing']=a.get('ausente_abertas_asn_em') or ''
            r['status']='Ausente na ASN' if a.get('snapshot_absent') else 'Manutenção' if 'MANUT' in str(a.get('status','')).upper() and not a.get('fim') else 'Liberado' if a.get('fim') else a.get('status') or r['status']
            r['asn_alert']='Sem data na origem' if not (a.get('parada') or a.get('inicio')) else 'Fim anterior ao início na origem' if a.get('fim') and date(a['fim'])<date(a.get('inicio') or a.get('parada')) else ''
            r['liberacao_oficina']='Liberado 10 Sul' if r.get('fim_liberacao_10sul') else 'Em atuação'
        result.append(r)
    return result

def fetch_table(url,key,table,order,key_fields,page_size=500):
    records=[];offset=0;seen=set()
    while True:
        query=urllib.parse.urlencode({'select':'*','order':order,'limit':str(page_size),'offset':str(offset)})
        req=urllib.request.Request(url.rstrip('/')+'/rest/v1/'+table+'?'+query,headers={'apikey':key,'Accept':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as r:page=json.load(r)
        except Exception:raise RuntimeError('Não foi possível atualizar a tabela '+table+'. A cópia anterior foi mantida.') from None
        if not isinstance(page,list):raise ValueError('Resposta inválida: '+table)
        for row in page:
            identity=json.dumps([row.get(k) for k in key_fields],sort_keys=True,ensure_ascii=False)
            if identity in seen:raise ValueError('Paginação alterada na origem: '+table)
            seen.add(identity);records.append(row)
        offset+=len(page)
        if len(page)<page_size:return records
        if offset>1000000:raise ValueError('Consulta excessiva: '+table)

def fetch_business_sources():
    from connection_defaults import VEHICLE_URL,VEHICLE_PUBLISHABLE_KEY
    outputs=[];errors=[]
    sources=[
        (VEHICLE_URL,VEHICLE_PUBLISHABLE_KEY,'veiculos','placa.asc',['placa'],'Controle de veículos'),
        (VEHICLE_URL,VEHICLE_PUBLISHABLE_KEY,'movimentacoes','id.asc',['id'],'Controle de veículos'),
        (VEHICLE_URL,VEHICLE_PUBLISHABLE_KEY,'consumo_relatorios','periodo.asc,id.asc',['id'],'Consumo de veículos'),
        (ASN_URL,ASN_PUBLISHABLE_KEY,'cocb_itens','id.asc',['id'],'Estoque do socorro'),
        (ASN_URL,ASN_PUBLISHABLE_KEY,'cocb_movimentacoes','id.asc',['id'],'Estoque do socorro')]
    for url,key,table,order,fields,module in sources:
        try:outputs.append({'table':'cloud_'+table,'module':module,'origin':url,'records':fetch_table(url,key,table,order,fields),'keys':fields})
        except Exception as e:errors.append(str(e))
    return outputs,errors
