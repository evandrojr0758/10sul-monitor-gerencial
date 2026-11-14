"""Contratos de alimentação: rede somente na sincronização, consultas no SQLite."""
import hashlib, json, ssl, urllib.request
from urllib.parse import urlparse
from modules import MODULES
from mirrors import mirror_snapshot
from history import qi
from core import now, stamp, date
from access import MODULE_PERMS

# Chaves e tabelas são do portal, nunca escolhidas por uma resposta remota.
DATASETS={
 'Controle de veículos':{'veiculos':('cloud_veiculos',['placa']),'movimentacoes':('cloud_movimentacoes',['id']),'consumo':('cloud_consumo_relatorios',['id'])},
 'Financeiro 10 Sul':{'contas':('cloud_finance_accounts',['id']),'lancamentos':('cloud_finance_entries',['id']),'recebimentos':('cloud_finance_receivables',['id']),'auditoria':('cloud_finance_audit',['event_key'])},
 'Estoque do socorro':{'itens':('cloud_estoque_itens',['id']),'movimentacoes':('cloud_estoque_movimentacoes',['id']),'inventarios':('cloud_estoque_inventarios',['id']),'reposicao':('cloud_estoque_reposicao',['ni'])},
 'Gestão do socorro':{'atendimentos':('cloud_socorro_atendimentos',['id'])},
 'Atendimento do socorrista':{'atendimentos':('cloud_socorro_atendimentos',['id'])},
 'Estoque de pneus':{'pneus':('cloud_pneus',['id']),'movimentacoes':('cloud_pneus_movimentacoes',['id'])},
 'Propostas comerciais':{'propostas':('cloud_commercial_proposals',['id'])},
 'Solicitações de peças PCM':{'solicitacoes':('cloud_pcm_solicitacoes',['id']),'itens':('cloud_pcm_itens',['id'])},
 'Projeto Lean':{'projetos':('cloud_lean_projetos',['id']),'itens':('cloud_lean_itens',['id']),'movimentacoes':('cloud_lean_movimentacoes',['id'])},
}
# Esse relatório já existe, mas não equivale ao estoque completo.
EXTRAS={'Estoque do socorro':{'metadados_reposicao':('cloud_estoque_relatorio_meta',['id'])}}

def module_tables(name):
 return {**DATASETS[name],**EXTRAS.get(name,{})}

def authorized(store,name):
 if name not in DATASETS:raise ValueError('Aplicativo desconhecido.')
 store.require(MODULE_PERMS[name])

def local_status(store,name):
 authorized(store,name);out=[]
 for label,(table,keys) in module_tables(name).items():
  catalog=store.db.execute('SELECT * FROM source_catalog WHERE table_name=?',(table,)).fetchone()
  exists=store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
  counts=store.db.execute('SELECT count(*),coalesce(sum(_source_present),0) FROM '+qi(table)).fetchone() if exists else (0,0)
  out.append({'conjunto':label,'table_name':table,'registros_locais':counts[0],'presentes_na_origem':counts[1],'updated_at':catalog['updated_at'] if catalog else '', 'situacao':'Disponível offline' if catalog else 'Aguardando primeira alimentação'})
 return out

def local_rows(store,name,dataset,include_absent=False,query=''):
 authorized(store,name)
 if dataset not in module_tables(name):raise ValueError('Conjunto de dados desconhecido.')
 table=module_tables(name)[dataset][0]
 if not store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():return []
 rows=[dict(r) for r in store.db.execute('SELECT * FROM '+qi(table)+('' if include_absent else ' WHERE _source_present=1')+' ORDER BY _source_id')]
 q=query.strip().casefold()
 return [r for r in rows if not q or any(q in str(v).casefold() for k,v in r.items() if not k.startswith('_'))]

def local_history(store,name,dataset,source_id=None):
 authorized(store,name)
 table=module_tables(name)[dataset][0]
 sql='SELECT * FROM change_history WHERE table_name=?';params=[table]
 # Chave do trigger é exatamente _source_id nas tabelas espelhadas.
 if source_id is not None:sql+=' AND row_key=?';params.append(source_id)
 return [dict(r) for r in store.db.execute(sql+' ORDER BY id DESC',params)]

def validate_feed(name,payload):
 if name not in DATASETS or not isinstance(payload,dict):raise ValueError('Alimentação inválida.')
 if payload.get('version')!=1 or payload.get('module')!=name or payload.get('complete') is not True:raise ValueError('Exigido pacote versão 1, aplicativo correto e complete=true. Páginas parciais não podem substituir a base.')
 if not payload.get('source_at') or not date(payload['source_at']):raise ValueError('Informe source_at com a data da extração completa na origem.')
 data=payload.get('datasets')
 if not isinstance(data,dict) or not data:raise ValueError('Nenhum conjunto informado na alimentação.')
 for dataset,rows in data.items():
  if dataset not in DATASETS[name]:raise ValueError('Conjunto não previsto: '+str(dataset))
  if not isinstance(rows,list) or len(rows)>1000000:raise ValueError('Lista inválida: '+dataset)
  keys=DATASETS[name][dataset][1];seen=set()
  for row in rows:
   if not isinstance(row,dict) or any(row.get(k) is None or str(row[k]).strip()=='' for k in keys):raise ValueError('Registro sem identificação: '+dataset)
   if any(not isinstance(k,str) or k.startswith('_') or k.casefold() in {'password','password_hash','passwordhash','senha','token','api_key','service_role_key'} for k in row):raise ValueError('Coluna reservada ou inválida: '+dataset)
   key=json.dumps([row[k] for k in keys],ensure_ascii=False,sort_keys=True,allow_nan=False)
   if key in seen:raise ValueError('Identificação repetida: '+dataset)
   seen.add(key)
 json.dumps(payload,ensure_ascii=False,allow_nan=False)
 return data

def apply_feed(store,name,payload,origin='Arquivo importado',automatic=False):
 if not automatic:authorized(store,name);store.require('sync.run')
 data=validate_feed(name,payload);actor=store.user
 try:
  store.db.execute('BEGIN');store.user='integração:'+name
  for dataset,rows in data.items():
   table,keys=DATASETS[name][dataset]
   digest=hashlib.sha256(json.dumps(sorted(rows,key=lambda r:json.dumps([r[k] for k in keys],sort_keys=True)),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
   prior=store.db.execute('SELECT value FROM sync_state WHERE name=?',('feed:'+table,)).fetchone()
   if prior:
    previous=json.loads(prior[0]);current=date(payload['source_at']);old=date(previous['source_at'])
    if current<old or (current==old and digest!=previous['digest']):raise ValueError('Extração anterior ou conflitante: '+dataset+'. Base local preservada.')
   mirror_snapshot(store,table,name,origin,rows,keys,transaction=False)
   store.db.execute('INSERT INTO sync_state VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',('feed:'+table,json.dumps({'source_at':payload['source_at'],'digest':digest,'applied_at':stamp(now())})))
  store.log('Alimentação local concluída',name,json.dumps({'conjuntos':list(data),'source_at':payload.get('source_at','')},ensure_ascii=False));store.db.commit()
 except Exception:store.db.rollback();raise
 finally:store.user=actor
 return sum(len(r) for r in data.values())

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise ValueError('A integração redirecionou. Configure o endereço HTTPS final.')

def validate_connection(name,profile):
 if name not in DATASETS or not isinstance(profile,dict):raise ValueError('Conexão inválida.')
 u=urlparse(profile.get('endpoint',''));expected=urlparse(MODULES[name]['url']).hostname
 if u.scheme!='https' or u.hostname!=expected or u.username or u.password or u.fragment or u.query:raise ValueError('Use um exportador HTTPS no domínio do aplicativo '+name+'.')
 headers=profile.get('headers',{})
 if not isinstance(headers,dict) or any(not isinstance(k,str) or not isinstance(v,str) or '\n' in k+v or '\r' in k+v for k,v in headers.items()):raise ValueError('Cabeçalhos da conexão inválidos.')
 return profile

def save_connection(store,name,profile):
 from credentials import protect
 import base64
 if not store.admin():raise ValueError('Somente administrador configura a integração.')
 validate_connection(name,profile)
 value=base64.b64encode(protect(json.dumps(profile).encode())).decode()
 store.db.execute('INSERT INTO connection_profiles VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',('feed:'+name,value));store.log('Conexão de alimentação configurada',name);store.db.commit()

def fetch_configured(root):
 import base64,sqlite3
 from contextlib import closing
 from pathlib import Path
 from credentials import protect
 # Conexão própria no worker; nenhuma instância de Store atravessa threads.
 with closing(sqlite3.connect(Path(root)/'manutencao.sqlite3')) as db:profiles=db.execute("SELECT name,value FROM connection_profiles WHERE name LIKE 'feed:%'").fetchall()
 outputs=[];errors=[]
 for key,value in profiles:
  name=key[5:]
  try:
   profile=json.loads(protect(base64.b64decode(value),decrypt=True));validate_connection(name,profile)
   req=urllib.request.Request(profile['endpoint'],headers={**profile.get('headers',{}),'Accept':'application/json','Cache-Control':'no-cache'})
   opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context()))
   with opener.open(req,timeout=25) as response:
    raw=response.read(50*1024*1024+1)
   if len(raw)>50*1024*1024:raise ValueError('Pacote acima de 50 MiB.')
   payload=json.loads(raw);validate_feed(name,payload);outputs.append((name,payload,profile['endpoint']))
  except Exception:errors.append(name+': alimentação não concluída; base local preservada. Confira a conexão de leitura.')
 return outputs,errors
