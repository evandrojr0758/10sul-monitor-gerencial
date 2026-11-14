"""10 Sul Manutenção: regras e persistência local, sem dependência de rede."""
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import unicodedata
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

VERSION = '1.0.0'
EVENTS = ['ITR', 'REVISÃO 60', 'REVISÃO 120', 'REVISÃO TRIMESTRAL', 'CORRETIVA Ñ PROG.', 'SOS MECÂNICA', 'PIT STOP', 'OUTROS']
UNITS = ['ARA', 'MUC', 'TLS']
SPECIAL = {'13169','13241','11003','11001','11007','11009'}
FIELDS = ['os_id','frota','unidade','evento','status','parada','inicio','fim_asn','fim_liberacao_10sul','local_manutencao','descricao','previsao','justificativa_previsao','aguardando_peca','expurgo','motivo_expurgo']

def text(v):
    return '' if v is None else str(v).strip()

def norm(v):
    return ''.join(c for c in unicodedata.normalize('NFKD',text(v).upper()) if not unicodedata.combining(c))

def fleet(v):
    return re.sub(r'\.0+$','',re.sub(r'^GO[\s.:-]*','',text(v),flags=re.I)).strip()

def date(v):
    if not text(v): return None
    if isinstance(v,datetime): return v.replace(tzinfo=None)
    s=text(v)
    try:
        d=datetime.fromisoformat(s.replace('Z','+00:00'))
        if d.tzinfo:
            from datetime import timezone
            d=d.astimezone(timezone(timedelta(hours=-3)))
        return d.replace(tzinfo=None)
    except ValueError: pass
    for fmt in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M','%d/%m/%Y','%Y-%m-%d'):
        try: return datetime.strptime(s,fmt)
        except ValueError: pass
    raise ValueError(f'Data inválida: {s}. Use DD/MM/AAAA HH:MM.')

def stamp(v):
    d=date(v)
    return d.isoformat(timespec='seconds') if d else ''

def now():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)

def shown(v):
    return date(v).strftime('%d/%m/%Y %H:%M') if text(v) else ''

def group(event):
    e=norm(event)
    if e=='ITR': return 'ITR'
    if 'REVIS' in e: return 'REVISÃO'
    if e.startswith('SOS'): return 'SOS'
    if 'CORRETIVA' in e or e=='CNP': return 'CNP'
    if 'PIT' in e: return 'PIT STOP'
    return 'OUTROS'

def duration(row, at=None):
    start=date(row.get('inicio') or row.get('parada'))
    end=date(row.get('fim_asn') or row.get('fim_liberacao_10sul')) or at or now()
    return max(0,(end-start).total_seconds()/3600) if start else 0

def is_open(row):
    return not (row.get('fim_asn') or row.get('fim_liberacao_10sul'))

def hours(value):
    m=round(max(0,value)*60)
    return f'{m//60:02}:{m%60:02}'

def metric_rows(rows, kind, start=None, end=None, at=None):
    """Replica elegibilidade do monitor: abertas só após SLA; especiais excluídas."""
    at=at or now(); result=[]; sla=12 if kind=='ITR' else 24
    for r in rows:
        if group(r['evento'])!=kind or r['frota'] in SPECIAL or r.get('expurgo')=='Excluir': continue
        ini=date(r.get('inicio') or r.get('parada'))
        if not ini: continue
        finish=date(r.get('fim_asn') or r.get('fim_liberacao_10sul')) or at
        if finish<ini: continue
        total=duration(r,at)
        if is_open(r) and total<sla: continue
        # Janela aplicada ao início do atendimento, explícita na interface.
        if start and ini<start: continue
        if end and ini>=end: continue
        result.append((r,min(total,sla) if r.get('expurgo')=='Limitar ao SLA' else total))
    return result

def daily_metrics(rows, kind, start, end, at=None):
    daily={}; at=at or now()
    for r,_ in metric_rows(rows,kind,at=at):
        a=date(r.get('inicio') or r.get('parada')); z=date(r.get('fim_asn') or r.get('fim_liberacao_10sul')) or at
        d=max(a.replace(hour=0,minute=0,second=0,microsecond=0),start)
        while d<min(z,end):
            h=max(0,(min(z,d+timedelta(days=1),end)-max(a,d)).total_seconds()/3600)
            if r.get('expurgo')=='Limitar ao SLA':
                total=duration(r,at); h*=min(total,12 if kind=='ITR' else 24)/total if total else 0
            if h: daily.setdefault(d.date().isoformat(),[]).append(h)
            d+=timedelta(days=1)
    return {d:sum(v)/len(v) for d,v in sorted(daily.items())}

class Store:
    def __init__(self, root=None):
        self.root=Path(root or os.environ.get('SUL_MANUTENCAO_DATA') or Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'10Sul'/'Manutencao')
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'anexos').mkdir(exist_ok=True)
        self.path=self.root/'manutencao.sqlite3'
        self.db=sqlite3.connect(self.path)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders(os_id TEXT NOT NULL,frota TEXT NOT NULL,unidade TEXT NOT NULL,evento TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Manutenção',parada TEXT NOT NULL,inicio TEXT,fim_asn TEXT,fim_liberacao_10sul TEXT,local_manutencao TEXT,descricao TEXT,previsao TEXT,justificativa_previsao TEXT,aguardando_peca TEXT,expurgo TEXT,motivo_expurgo TEXT,updated_at TEXT,PRIMARY KEY(os_id,frota));
        CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,data TEXT NOT NULL,frota TEXT NOT NULL,evento TEXT NOT NULL,unidade TEXT NOT NULL,grupo TEXT,UNIQUE(data,frota,evento,unidade));
        CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY,os_id TEXT NOT NULL,frota TEXT NOT NULL,atividade TEXT NOT NULL,responsavel TEXT,inicio TEXT,fim TEXT,arquivo TEXT,FOREIGN KEY(os_id,frota) REFERENCES orders(os_id,frota));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,username TEXT NOT NULL,action TEXT NOT NULL,entity TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS catalogs(kind TEXT NOT NULL,name TEXT NOT NULL,detail TEXT,active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(kind,name));
        ''')
        for u in UNITS: self.db.execute('INSERT OR IGNORE INTO catalogs(kind,name) VALUES (?,?)',('Unidades',u))
        self.db.commit(); self.user=''
    def close(self): self.db.close()
    def log(self,action,entity='',detail=''):
        self.db.execute('INSERT INTO audit(at,username,action,entity,detail) VALUES (?,?,?,?,?)',(stamp(now()),self.user or 'sistema',action,entity,detail))
    def users(self): return [dict(x) for x in self.db.execute('SELECT username,role,active FROM users ORDER BY username')]
    def add_user(self,name,password,role='Operacional',active=True):
        if self.users() and not self.admin(): raise ValueError('Somente o administrador pode alterar usuários.')
        name=text(name).lower()
        if not name or len(password)<8: raise ValueError('Informe usuário e senha com pelo menos 8 caracteres.')
        salt=secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),250000).hex()
        self.db.execute('INSERT INTO users VALUES (?,?,?,?) ON CONFLICT(username) DO UPDATE SET password=excluded.password,role=excluded.role,active=excluded.active',(name,salt+':'+digest,role,int(active)))
        self.log('Usuário salvo',name,role); self.db.commit()
    def admin(self):
        r=self.db.execute('SELECT role FROM users WHERE username=? AND active=1',(self.user,)).fetchone()
        return bool(r and r[0]=='Administrador')
    def login(self,name,password):
        r=self.db.execute('SELECT * FROM users WHERE username=? AND active=1',(text(name).lower(),)).fetchone()
        if r:
            salt,digest=r['password'].split(':'); actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),250000).hex()
            if hmac.compare_digest(digest,actual):
                self.user=r['username']; self.log('Entrada no sistema'); self.db.commit(); return True
        return False
    def orders(self): return [dict(x) for x in self.db.execute('SELECT * FROM orders ORDER BY parada DESC')]
    def save_order(self,data,importing=False):
        r={k:text(data.get(k)) for k in FIELDS}
        r['os_id']=text(r['os_id']);r['frota']=fleet(r['frota']);r['unidade']=norm(r['unidade']) or 'ARA'
        if not r['os_id'] or not r['frota'] or not r['evento'] or not r['parada']: raise ValueError('OS, frota, evento e parada são obrigatórios.')
        for k in ('parada','inicio','fim_asn','fim_liberacao_10sul','previsao'): r[k]=stamp(r[k])
        if not r['inicio']: r['inicio']=r['parada']
        for k in ('fim_asn','fim_liberacao_10sul'):
            if r[k] and date(r[k])<date(r['inicio']): raise ValueError('Fim não pode ser anterior ao início.')
        if r['expurgo'] and not r['motivo_expurgo']: raise ValueError('Informe a justificativa do expurgo.')
        if r['expurgo'] and not importing and not self.admin(): raise ValueError('Expurgo requer administrador.')
        r['status']='Manutenção' if is_open(r) else 'Liberado'
        r['updated_at']=stamp(now())
        cols=FIELDS+['updated_at']; sql=','.join(f'{c}=excluded.{c}' for c in cols if c not in ('os_id','frota'))
        self.db.execute(f"INSERT INTO orders ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) ON CONFLICT(os_id,frota) DO UPDATE SET {sql}",[r[c] for c in cols])
        self.log('Importação OS' if importing else 'OS salva',r['os_id']+'/'+r['frota'],json.dumps(r,ensure_ascii=False))
        if not importing: self.db.commit()
        return r
    def release(self,key,when):
        r=dict(self.db.execute('SELECT * FROM orders WHERE os_id=? AND frota=?',key).fetchone()); r['fim_liberacao_10sul']=stamp(when);return self.save_order(r)
    def import_orders(self,records):
        aliases={'ID':'os_id','OS':'os_id','OS/ID':'os_id','GO':'frota','FROTA':'frota','UNIDADE':'unidade','UN':'unidade','EVENTO':'evento','STATUS':'status','PARADA':'parada','PARADA (DATA/HORA)':'parada','INICIO':'inicio','INICIO AJUSTADO':'inicio','FIM':'fim_asn','FIM (DATA/HORA)':'fim_asn','LOCAL':'local_manutencao','LOCAL DA MANUTENCAO':'local_manutencao','DESCRICAO':'descricao'}
        prepared=[]
        for i,r in enumerate(records,2):
            item={aliases.get(norm(k),text(k)):v for k,v in r.items()}
            old=self.db.execute('SELECT * FROM orders WHERE os_id=? AND frota=?',(text(item.get('os_id')),fleet(item.get('frota')))).fetchone()
            # Origem atualiza seus campos; decisões e registros locais são preservados.
            merged=dict(old) if old else {}
            protected={'fim_liberacao_10sul','previsao','justificativa_previsao','aguardando_peca','expurgo','motivo_expurgo'}
            for k,v in item.items():
                if old and (k in protected or k=='inicio'): continue
                merged[k]=v
            if 'fim' in item: merged['fim_asn']=item['fim']
            if norm(item.get('status'))=='MANUTENCAO' and not item.get('fim_asn') and old and old['fim_asn']:
                merged['fim_asn']=''
            prepared.append((i,merged))
        try:
            self.db.execute('BEGIN')
            for line,r in prepared:
                try: self.save_order(r,True)
                except ValueError as e: raise ValueError(f'Linha {line}: {e}')
            self.db.commit()
        except Exception: self.db.rollback(); raise
        return len(prepared)
    def plan(self,data):
        d=date(data['data']).date().isoformat(); f=fleet(data['frota'])
        if not f: raise ValueError('Informe a frota.')
        self.db.execute('INSERT INTO plans(data,frota,evento,unidade,grupo) VALUES (?,?,?,?,?) ON CONFLICT(data,frota,evento,unidade) DO UPDATE SET grupo=excluded.grupo',(d,f,data['evento'],data['unidade'],data.get('grupo','')))
        self.log('Programação salva',f,d);self.db.commit()
    def plans(self):
        rows=self.orders(); result=[]
        for p in self.db.execute('SELECT * FROM plans ORDER BY data DESC,frota'):
            r=dict(p); matches=[o for o in rows if o['frota']==r['frota'] and o['unidade']==r['unidade'] and group(o['evento'])==group(r['evento']) and date(o['parada']).date().isoformat()==r['data']]
            r['situacao']='Atendida' if matches else 'Não atendida' if r['data']<now().date().isoformat() else 'Aguardando';result.append(r)
        return result
    def add_activity(self,r,attachment=None):
        if not text(r.get('atividade')): raise ValueError('Informe a atividade.')
        a=date(r.get('inicio'));b=date(r.get('fim'))
        if b and not a: raise ValueError('Informe o início da atividade.')
        if a and b and b<a: raise ValueError('Fim anterior ao início.')
        stored=''
        if attachment:
            src=Path(attachment); stored=secrets.token_hex(12)+src.suffix.lower();shutil.copy2(src,self.root/'anexos'/stored)
        try:
            self.db.execute('INSERT INTO activities(os_id,frota,atividade,responsavel,inicio,fim,arquivo) VALUES (?,?,?,?,?,?,?)',(r['os_id'],r['frota'],r['atividade'],r.get('responsavel',''),stamp(a),stamp(b),stored))
            self.log('Atividade e evidência adicionadas',r['os_id'],r['atividade']);self.db.commit()
        except Exception:
            if stored: (self.root/'anexos'/stored).unlink(missing_ok=True)
            raise
    def activities(self): return [dict(x) for x in self.db.execute('SELECT * FROM activities ORDER BY id DESC')]
    def backup(self,target):
        self.db.commit()
        tmp=self.root/'backup_tmp.sqlite3'
        with sqlite3.connect(tmp) as dst: self.db.backup(dst)
        try:
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(tmp,'manutencao.sqlite3')
                for p in (self.root/'anexos').iterdir():
                    if p.is_file(): z.write(p,'anexos/'+p.name)
                z.writestr('versao.txt',VERSION)
        finally: tmp.unlink(missing_ok=True)
        self.log('Backup criado',Path(target).name);self.db.commit()
    def restore(self,source):
        if not self.admin(): raise ValueError('Restauração requer administrador.')
        import tempfile
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            tmp=Path(tmp)
            with zipfile.ZipFile(source) as z:
                if 'manutencao.sqlite3' not in z.namelist(): raise ValueError('Backup inválido.')
                for n in z.namelist():
                    p=Path(n)
                    if p.is_absolute() or '..' in p.parts: raise ValueError('Caminho inválido no backup.')
                    if n not in ('manutencao.sqlite3','versao.txt') and not (len(p.parts)==2 and p.parts[0]=='anexos'): raise ValueError('Conteúdo inesperado no backup.')
                z.extractall(tmp)
            check=sqlite3.connect(tmp/'manutencao.sqlite3')
            try:
                if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Banco corrompido.')
                for table in ('users','orders','activities','plans','audit','catalogs'): check.execute('SELECT * FROM '+table+' LIMIT 1')
                for r in check.execute('SELECT arquivo FROM activities WHERE arquivo!=""'):
                    if Path(r[0]).name!=r[0] or not (tmp/'anexos'/r[0]).is_file(): raise ValueError('Evidência ausente no backup.')
                self.backup(self.root/('antes_restauracao_'+now().strftime('%Y%m%d_%H%M%S')+'.zip'))
                check.backup(self.db)
                for p in (tmp/'anexos').glob('*'): shutil.copy2(p,self.root/'anexos'/p.name)
                self.db.commit()
            finally: check.close()
    def catalog(self,kind,name,detail='',active=True):
        if not text(name):raise ValueError('Informe o nome/código.')
        self.db.execute('INSERT INTO catalogs VALUES (?,?,?,?) ON CONFLICT(kind,name) DO UPDATE SET detail=excluded.detail,active=excluded.active',(kind,name,detail,int(active)));self.log('Cadastro salvo',kind,name);self.db.commit()
    def catalogs(self,kind):return [dict(x) for x in self.db.execute('SELECT * FROM catalogs WHERE kind=? ORDER BY name',(kind,))]

def read_records(path):
    p=Path(path)
    if p.suffix.lower()=='.json':
        r=json.loads(p.read_text(encoding='utf-8-sig'))
        if isinstance(r,dict): r=r.get('dados',r.get('data',r.get('records')))
        if not isinstance(r,list) or any(not isinstance(x,dict) for x in r): raise ValueError('JSON deve conter uma lista de registros.')
        return r
    if p.suffix.lower()=='.xlsx':
        from openpyxl import load_workbook
        w=load_workbook(p,read_only=True,data_only=True)
        try:
            rows=iter(w.active.values); cols=[text(v) for v in next(rows)];return [dict(zip(cols,row)) for row in rows if any(v is not None for v in row)]
        finally:w.close()
    raw=p.read_text(encoding='utf-8-sig')
    try:dialect=csv.Sniffer().sniff(raw[:8192],delimiters=';,\t')
    except csv.Error:dialect=csv.excel
    return list(csv.DictReader(raw.splitlines(),dialect=dialect))

def export_csv(path,rows,cols):
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=cols,delimiter=';',extrasaction='ignore');w.writeheader()
        for row in rows:
            clean={k: ("'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()};w.writerow(clean)
