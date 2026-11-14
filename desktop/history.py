"""Histórico de alterações e console SQL local com transações e auditoria."""
import json,re,sqlite3,time
from core import now,stamp
PROTECTED={'change_history','sql_history','audit','users','sync_state','asn_cache','source_catalog','report_queries','connection_profiles','access_profiles','module_tickets'}
IGNORE={'sqlite_sequence','change_history','sql_history','audit','sync_state','asn_cache','source_catalog','report_queries','connection_profiles','module_tickets'}

def qi(name):return '"'+str(name).replace('"','""')+'"'

def setup_history(store):
    db=store.db
    db.create_function('current_actor',0,lambda:store.user or 'sistema')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS change_history(id INTEGER PRIMARY KEY,changed_at TEXT NOT NULL,actor TEXT NOT NULL,table_name TEXT NOT NULL,action TEXT NOT NULL,row_key TEXT,before_json TEXT,after_json TEXT);
    CREATE INDEX IF NOT EXISTS ix_history_table_at ON change_history(table_name,changed_at);
    CREATE TABLE IF NOT EXISTS sql_history(id INTEGER PRIMARY KEY,executed_at TEXT NOT NULL,actor TEXT NOT NULL,sql_text TEXT NOT NULL,mode TEXT NOT NULL,success INTEGER NOT NULL,rows_count INTEGER,error TEXT);
    CREATE TABLE IF NOT EXISTS report_queries(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,sql_text TEXT NOT NULL,created_by TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS connection_profiles(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_catalog(table_name TEXT PRIMARY KEY,module TEXT NOT NULL,origin TEXT NOT NULL,updated_at TEXT NOT NULL,description TEXT);
    ''')
    install_triggers(store);db.commit()

def install_triggers(store):
    db=store.db
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        table=row[0]
        if table in IGNORE:continue
        columns=[r[1] for r in db.execute('PRAGMA table_info('+qi(table)+')')]
        visible=[c for c in columns if c not in ('password','password_hash','token','passwordHash','api_key')]
        def obj(alias):return 'json_object('+','.join("'"+c.replace("'","''")+"',"+alias+'.'+qi(c) for c in visible)+')'
        primary=[r[1] for r in db.execute('PRAGMA table_info('+qi(table)+')') if r[5]] or columns[:1]
        def key(alias):return '||\'/\'||'.join('coalesce(CAST('+alias+'.'+qi(c)+" AS TEXT),'')" for c in primary)
        relevant=[c for c in columns if c not in ('updated_at','_seen_at','sincronizado_em')]
        changed=' OR '.join('OLD.'+qi(c)+' IS NOT NEW.'+qi(c) for c in relevant) or '1'
        for action,old,new,alias in [('INSERT','NULL',obj('NEW'),'NEW'),('UPDATE',obj('OLD'),obj('NEW'),'NEW'),('DELETE',obj('OLD'),'NULL','OLD')]:
            trigger='hist_'+table+'_'+action.lower();db.execute('DROP TRIGGER IF EXISTS '+qi(trigger))
            db.execute('CREATE TRIGGER '+qi(trigger)+' AFTER '+action+' ON '+qi(table)+(' WHEN '+changed if action=='UPDATE' else '')+' BEGIN INSERT INTO change_history(changed_at,actor,table_name,action,row_key,before_json,after_json) VALUES(strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\'),current_actor(),'+"'"+table.replace("'","''")+"','"+action+"',"+key(alias)+','+old+','+new+'); END')

def list_tables(store):
    rows=[]
    for r in store.db.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        name=r['name'];columns=[dict(x) for x in store.db.execute('PRAGMA table_info('+qi(name)+')')]
        rows.append({'table':name,'type':r['type'],'columns':columns,'rows':store.db.execute('SELECT count(*) FROM '+qi(name)).fetchone()[0]})
    return rows

def execute_sql(store,sql,write=False,limit=20000):
    store.require('sql.write' if write else 'sql.read')
    sql=sql.strip()
    if not sql:raise ValueError('Digite uma consulta ou comando SQL.')
    if len(sql)>100000:raise ValueError('SQL acima do limite de 100 mil caracteres.')
    db=store.db;started=time.monotonic();truncated=False;result={};error='';success=False
    read_ops={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
    ddl={sqlite3.SQLITE_CREATE_INDEX,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_DROP_INDEX,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_CREATE_VIEW,sqlite3.SQLITE_DROP_VIEW}
    def auth(action,a,b,d,trigger):
        if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH,sqlite3.SQLITE_TRANSACTION,sqlite3.SQLITE_SAVEPOINT,sqlite3.SQLITE_CREATE_VTABLE,sqlite3.SQLITE_DROP_VTABLE):return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_FUNCTION and str(b or a).lower() in ('load_extension','writefile','readfile'):return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_PRAGMA:return sqlite3.SQLITE_OK if str(a).lower() in ('table_info','index_list','index_info','foreign_key_list','integrity_check','foreign_key_check','database_list','table_list') else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
            if trigger and str(trigger).startswith('hist_') and a=='change_history':return sqlite3.SQLITE_OK
            if not write or a in PROTECTED or str(a).startswith('cloud_'):return sqlite3.SQLITE_DENY
        if action in ddl:
            target=b if action==sqlite3.SQLITE_ALTER_TABLE else a
            if not write or target in PROTECTED or str(target).startswith('cloud_'):return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_CREATE_TRIGGER):return sqlite3.SQLITE_DENY
        if not write and action not in read_ops and action!=sqlite3.SQLITE_PRAGMA:return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    try:
        db.execute('BEGIN');db.set_authorizer(auth);db.set_progress_handler(lambda:1 if time.monotonic()-started>10 else 0,10000)
        cur=db.execute(sql)
        columns=[];used=set()
        for index,description in enumerate(cur.description or []):
            base=description[0] or 'coluna_'+str(index+1);name=base;suffix=2
            while name in used:name=base+'_'+str(suffix);suffix+=1
            used.add(name);columns.append(name)
        rows=cur.fetchmany(limit+1) if columns else [];truncated=len(rows)>limit;rows=rows[:limit]
        result={'columns':columns,'rows':[dict(zip(columns,r)) for r in rows],'affected':cur.rowcount if not columns else len(rows),'truncated':truncated}
        cur.close()
        db.set_authorizer(None);db.set_progress_handler(None,0)
        if write:install_triggers(store)
        db.commit();success=True
    except Exception as exc:
        db.set_authorizer(None);db.set_progress_handler(None,0);db.rollback();error=str(exc)
    db.execute('INSERT INTO sql_history(executed_at,actor,sql_text,mode,success,rows_count,error) VALUES (?,?,?,?,?,?,?)',(stamp(now()),store.user,sql,'Escrita' if write else 'Consulta',int(success),result.get('affected',0),error));db.commit()
    if not success:raise ValueError('SQL não executado: '+error)
    return result

def save_report(store,name,sql):
    store.require('sql.read')
    if not name.strip() or not sql.strip():raise ValueError('Informe nome e SQL.')
    store.db.execute('INSERT INTO report_queries(name,sql_text,created_by,updated_at) VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET sql_text=excluded.sql_text,updated_at=excluded.updated_at',(name.strip(),sql.strip(),store.user,stamp(now())));store.log('Consulta salva',name);store.db.commit()
