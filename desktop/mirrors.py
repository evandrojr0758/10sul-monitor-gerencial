"""Tabelas de consulta dos aplicativos conectados; fonte original preservada."""
import hashlib,json,sqlite3
from core import stamp,now
from history import qi,install_triggers

def mirror_snapshot(store,table,module,origin,records,key_fields,transaction=True):
    if not table.startswith('cloud_') or not table.replace('_','').isalnum():raise ValueError('Nome de tabela de consulta inválido.')
    if any(not isinstance(r,dict) for r in records):raise ValueError('Registros inválidos.')
    db=store.db
    try:
        if transaction:db.execute('BEGIN')
        db.execute('CREATE TABLE IF NOT EXISTS '+qi(table)+' (_source_id TEXT PRIMARY KEY,_source_present INTEGER NOT NULL DEFAULT 1)')
        existing={r[1] for r in db.execute('PRAGMA table_info('+qi(table)+')')}
        columns=sorted({str(k) for r in records for k in r if not str(k).startswith('_')})
        if len(columns)>70:raise ValueError('Tabela acima do limite de 70 colunas.')
        for column in columns:
            if column not in existing:
                values=[r[column] for r in records if r.get(column) is not None]
                affinity='INTEGER' if values and all(isinstance(v,(int,bool)) for v in values) else 'REAL' if values and all(isinstance(v,(int,float)) for v in values) else 'TEXT'
                db.execute('ALTER TABLE '+qi(table)+' ADD COLUMN '+qi(column)+' '+affinity)
        install_triggers(store)
        seen=set()
        for row in records:
            if any(row.get(k) is None for k in key_fields):raise ValueError('Registro da origem sem chave: '+table)
            key=json.dumps([row[k] for k in key_fields],ensure_ascii=False,sort_keys=True)
            if key in seen:raise ValueError('Chave repetida na consulta: '+table)
            seen.add(key);data={k:row.get(k) for k in columns}
            data={k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in data.items()}
            names=['_source_id','_source_present']+columns;values=[key,1]+[data[k] for k in columns]
            updates=','.join(qi(k)+'=excluded.'+qi(k) for k in names[1:])
            db.execute('INSERT INTO '+qi(table)+' ('+','.join(map(qi,names))+') VALUES ('+','.join('?' for _ in names)+') ON CONFLICT(_source_id) DO UPDATE SET '+updates,values)
        for r in db.execute('SELECT _source_id FROM '+qi(table)+' WHERE _source_present=1').fetchall():
            if r[0] not in seen:db.execute('UPDATE '+qi(table)+' SET _source_present=0 WHERE _source_id=?',(r[0],))
        db.execute('INSERT INTO source_catalog VALUES (?,?,?,?,?) ON CONFLICT(table_name) DO UPDATE SET updated_at=excluded.updated_at,description=excluded.description',(table,module,origin,stamp(now()),f'Cópia de consulta: {len(records)} registros presentes. _source_present=1 identifica o estado atual. Histórico em change_history.'))
        if transaction:db.commit()
    except Exception:
        if transaction:db.rollback()
        raise

FINANCE_CAPTURE=r'''(async()=>{
 const state=await fetch('/api/finance?resource=state',{cache:'no-store'}).then(r=>r.json());
 if(!state.user)return {ok:false,reason:'Entre no Financeiro para autorizar a cópia de consulta.'};
 const datasets=[{table:'cloud_finance_accounts',records:state.accounts||[],keys:['id']}];
 let list=[],page=0;
 while(true){const response=await fetch('/api/finance?resource=report&from=2000-01-01&to=2099-12-31&cancelled=1&page='+page,{cache:'no-store'});if(!response.ok)return {ok:false,reason:'Seu perfil não pode consultar lançamentos.'};const data=await response.json();if(!Array.isArray(data.list))return {ok:false};list.push(...data.list);if(list.length>=data.count)break;if(!data.list.length||page++>25000)return {ok:false};}
 datasets.push({table:'cloud_finance_entries',records:list,keys:['id']});
 window.__10SulEntryRevisions=window.__10SulEntryRevisions||{};
 const audit=[];
 for(const entry of list){const revision=String(entry.updated_at||'')+':'+String(entry.cancelled||0);if(window.__10SulEntryRevisions[entry.id]===revision)continue;const detail=await fetch('/api/finance?resource=detail&id='+encodeURIComponent(entry.id),{cache:'no-store'});if(!detail.ok)continue;const data=await detail.json();for(const event of data.audit||[]){const raw=JSON.stringify([entry.id,event.action,event.created_at,event.details]);const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));const event_key=Array.from(new Uint8Array(hash),n=>n.toString(16).padStart(2,'0')).join('');audit.push({...event,entry_id:entry.id,event_key});}window.__10SulEntryRevisions[entry.id]=revision;}
 if(audit.length)datasets.push({table:'cloud_finance_audit',records:audit,keys:['event_key'],append:true});
 const proposal=await fetch('/api/propostas',{cache:'no-store'});if(proposal.ok){const p=await proposal.json();if(Array.isArray(p.proposals)&&p.proposals.length<500)datasets.push({table:'cloud_commercial_proposals',records:p.proposals,keys:['id']});}
 const receivable=await fetch('/api/receber',{cache:'no-store'});if(receivable.ok){const p=await receivable.json();if(Array.isArray(p.receivables))datasets.push({table:'cloud_finance_receivables',records:p.receivables,keys:['id']});}
 return {ok:true,datasets};
})()'''

SOCORRO_CAPTURE=r'''(async()=>{let cursor='',records=[],seen=new Set();while(true){const response=await fetch('/api/gestao'+(cursor?'?cursor='+encodeURIComponent(cursor):''),{cache:'no-store'});if(!response.ok)return {ok:false};const data=await response.json();if(!Array.isArray(data.records))return {ok:false};records.push(...data.records);if(!data.nextCursor)break;if(seen.has(data.nextCursor))return {ok:false};seen.add(data.nextCursor);cursor=data.nextCursor;}return {ok:true,datasets:[{table:'cloud_socorro_atendimentos',records,keys:['id']}]};})()'''
