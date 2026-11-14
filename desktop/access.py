"""Perfis locais vinculados aos usuários e permissões por tela/ação."""
import json,hashlib,secrets,time
PAGES={
'Monitor da oficina':'dashboard.view','Ordens de manutenção':'orders.view','Histórico por frota':'history.view','Programação preventiva':'plans.view','Laudos e atividades':'activities.view','Conferência de laudos':'inspections.view','Indicadores e SLA':'indicators.view','Expurgos de SLA':'expurgos.view','Cadastros':'catalogs.view','Relatórios':'reports.view','Backup e restauração':'backup.view','Aplicativos integrados':'apps.view','Integração ASN':'sync.view','Manutenção SQL':'sql.read','Histórico do sistema':'audit.view','Auditoria':'audit.view','Usuários e acessos':'admin.users','Perfis de acesso':'admin.profiles'}
MODULE_PERMS={
'Controle de veículos':'module.vehicles','Financeiro 10 Sul':'module.finance','Estoque do socorro':'module.stock','Gestão do socorro':'module.rescue','Atendimento do socorrista':'module.rescuer','Estoque de pneus':'module.tires','Propostas comerciais':'module.proposals','Solicitações de peças PCM':'module.pcm','Projeto Lean':'module.lean'}
PERMISSIONS={
'dashboard.view':('Visão geral','Painel gerencial'),
'orders.view':('Oficina','Consultar OS'),'orders.edit':('Oficina','Cadastrar e editar OS'),'orders.release':('Oficina','Liberar 10 Sul'),'orders.import':('Oficina','Importar base'),
'history.view':('Oficina','Histórico por frota'),'plans.view':('Oficina','Consultar programação'),'plans.edit':('Oficina','Lançar/importar programação'),'plans.anticipate':('Oficina','Registrar oportunidade de antecipação'),
'activities.view':('Laudos','Consultar atividades e evidências'),'activities.edit':('Laudos','Lançar atividades e evidências'),'inspections.view':('Laudos','Consultar conferência de laudos'),'inspections.import':('Laudos','Importar laudo e ler com Gemini'),'inspections.review':('Laudos','Conferir e gravar laudo'),
'indicators.view':('Indicadores','Consultar médias e rankings'),'expurgos.view':('Indicadores','Consultar expurgos'),'expurgos.edit':('Indicadores','Tratar expurgos de SLA'),
'catalogs.view':('Cadastros','Consultar cadastros'),'catalogs.edit':('Cadastros','Alterar cadastros'),'reports.view':('Relatórios','Consultar relatórios'),'data.export':('Relatórios','Exportar resultados'),
'apps.view':('Aplicativos','Central de aplicativos'),
'sync.view':('Integração','Consultar situação ASN'),'sync.run':('Integração','Atualizar ASN manualmente'),
'backup.view':('Administração','Acessar backup'),'backup.create':('Administração','Criar backup'),'backup.restore':('Administração','Restaurar backup'),
'sql.read':('Administração','Executar consultas SQL locais'),'sql.write':('Administração','Executar comandos de alteração SQL'),'audit.view':('Administração','Consultar trilhas de histórico'),
}
for module,key in MODULE_PERMS.items():PERMISSIONS[key]=('Aplicativos','Acessar '+module)
READ={'dashboard.view','orders.view','history.view','plans.view','activities.view','inspections.view','indicators.view','reports.view','data.export','sync.view','sync.run'}
DEFAULTS={
'Administrador':set(PERMISSIONS)|{'admin.users','admin.profiles'},
'Operacional':READ|{'orders.edit','orders.release','orders.import','plans.edit','plans.anticipate','activities.edit','inspections.import','inspections.review','apps.view','module.vehicles','module.rescue','module.rescuer','module.stock','module.tires','module.pcm'},
'Gestão':READ|{'apps.view','expurgos.view','module.vehicles','module.rescue','module.stock','module.finance','module.proposals','audit.view'},
'Consulta':READ-{'sync.run'},
}

def setup_access(store):
 db=store.db;db.executescript('''CREATE TABLE IF NOT EXISTS access_profiles(name TEXT PRIMARY KEY,description TEXT NOT NULL,permissions TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);CREATE TABLE IF NOT EXISTS module_tickets(token_hash TEXT PRIMARY KEY,username TEXT NOT NULL,module TEXT NOT NULL,expires REAL NOT NULL);''')
 for name,permissions in DEFAULTS.items():db.execute('INSERT OR IGNORE INTO access_profiles VALUES (?,?,?,1)',(name,'Perfil inicial do sistema',json.dumps(sorted(permissions))))
 columns={r[1] for r in db.execute('PRAGMA table_info(users)')}
 if 'profile' not in columns:
  db.execute("ALTER TABLE users ADD COLUMN profile TEXT NOT NULL DEFAULT 'Operacional'");db.execute("UPDATE users SET profile=CASE WHEN role='Administrador' THEN 'Administrador' ELSE 'Operacional' END")
 db.commit()

def profile_of(store):
 return store.db.execute('SELECT p.* FROM users u JOIN access_profiles p ON p.name=u.profile WHERE u.username=? AND u.active=1 AND p.active=1',(store.user,)).fetchone()

def can(store,permission):
 row=profile_of(store)
 return bool(row and (row['name']=='Administrador' or permission in json.loads(row['permissions'])))

def require(store,permission):
 if not can(store,permission):raise ValueError('Seu perfil não tem permissão para esta ação: '+PERMISSIONS.get(permission,('',permission))[1])

def profiles(store,active_only=False):
 sql='SELECT * FROM access_profiles'+(' WHERE active=1' if active_only else '')+' ORDER BY name'
 return [dict(r) for r in store.db.execute(sql)]

def save_profile(store,name,description,permissions,active=True):
 if not store.admin():raise ValueError('Apenas o administrador pode alterar perfis.')
 name=name.strip()
 if not name:raise ValueError('Informe o nome do perfil.')
 if name=='Administrador':raise ValueError('O perfil Administrador é reservado e mantém acesso completo.')
 permissions=set(permissions)
 if not permissions<=set(PERMISSIONS):raise ValueError('Permissão inválida no perfil.')
 # Relações implícitas: uma ação não libera automaticamente a visualização da tela.
 store.db.execute('INSERT INTO access_profiles VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description,permissions=excluded.permissions,active=excluded.active',(name,description,json.dumps(sorted(permissions)),int(active)))
 store.log('Perfil salvo',name,json.dumps({'active':active,'permissions':sorted(permissions)},ensure_ascii=False));store.db.commit()

def issue_module_ticket(store,module):
 require(store,MODULE_PERMS[module]);token=secrets.token_urlsafe(32)
 store.db.execute('DELETE FROM module_tickets WHERE expires<?',(time.time(),));store.db.execute('INSERT INTO module_tickets VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),store.user,module,time.time()+90));store.db.commit();return token

def consume_module_ticket(store,module,token):
 digest=hashlib.sha256((token or '').encode()).hexdigest();store.db.execute('BEGIN IMMEDIATE')
 try:
  row=store.db.execute('SELECT * FROM module_tickets WHERE token_hash=?',(digest,)).fetchone()
  if not row or row['module']!=module or row['expires']<time.time():raise ValueError('Acesso integrado expirado. Abra o módulo pelo portal autenticado.')
  store.user=row['username'];require(store,MODULE_PERMS[module]);store.db.execute('DELETE FROM module_tickets WHERE token_hash=?',(digest,));store.log('Aplicativo integrado aberto',module);store.db.commit()
 except Exception:store.db.rollback();raise
