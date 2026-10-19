import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor_delta import MonitorDeltaCache

cache = MonitorDeltaCache()
responses = [
    {'changed': [{'key':'a','hash':'1','row':{'os_id':'1','frota':'13','fim':None}}, {'key':'b','hash':'2','row':{'os_id':'2','frota':'23','fim':None}}], 'removed': [], 'sincronizado_em':'2026-10-19T23:00:00Z'},
    {'changed': [], 'removed': [], 'sincronizado_em':'2026-10-19T23:01:00Z'},
    {'changed': [{'key':'a','hash':'3','row':{'os_id':'1','frota':'13','fim':'2026-10-19'}}], 'removed': ['b']},
    {'changed': [{'key':'a','hash':'4','row':{'os_id':'1','frota':'13','fim':None}}], 'removed': []},
]
calls=[]
def fetch(path,payload):
    calls.append(payload)
    return responses.pop(0)
read=lambda:cache.read(fetch,'monitor_asn','2026-08-01',['old-open'])
a=read();assert len(a)==2 and calls[-1]['p_known']=={}
a.loc[0,'frota']='tampered'
b=read();assert len(b)==2 and b.loc[0,'frota']=='13' and calls[-1]['p_known']=={'a':'1','b':'2'}
assert b.attrs['sincronizado_em']=='2026-10-19T23:01:00Z'
c=read();assert len(c)==1 and c.iloc[0]['fim']=='2026-10-19'
d=read();assert len(d)==1 and d.iloc[0]['fim'] is None
try:
    cache.read(lambda *_: (_ for _ in ()).throw(RuntimeError('network')), 'monitor_asn','2026-08-01',['old-open'])
except RuntimeError:pass
else:raise AssertionError('Network failure must be surfaced')
e=cache.read(lambda path,payload: {'changed':[],'removed':[]},'monitor_asn','2026-08-01',['old-open'])
assert len(e)==1 and e.iloc[0]['fim'] is None
f=cache.read(lambda path,payload: {'changed':[],'removed':['a']},'monitor_asn','2026-08-01',['old-open'])
assert f.empty
print('PASS: initial load, no-op reuse, partial updates, closure, reopening, deletion, detached frames, failure recovery')

# Exercise the production stitching function: old open OS must close/reopen/disappear.
import ast
source = (Path(__file__).resolve().parents[1] / 'monitor_web.py').read_text()
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_atendimentos_com_historico')
archive = __import__('pandas').DataFrame([
    {'os_id':'old-open','frota':'13','status':'Manutenção','fim':None},
    {'os_id':'old-closed','frota':'23','status':'Liberado','fim':'2026-06-01'},
])
class Feed:
    frame = None
    def read(self,*args):return self.frame.copy()
feed=Feed()
scope={'pd':__import__('pandas'), '_historico_fixo':lambda *_:archive.copy(), '_cache_incremental_monitor':lambda:feed, 'api_post':None}
exec(compile(ast.Module(body=[node], type_ignores=[]), 'monitor_web.py', 'exec'),scope)
feed.frame=__import__('pandas').DataFrame([{'os_id':'old-open','frota':'13','status':'Liberado','fim':'2026-10-19'}])
result=scope['_atendimentos_com_historico']('monitor_asn','2026-08-01')
assert len(result)==2 and result.loc[result.os_id=='old-open','fim'].iloc[0]=='2026-10-19'
feed.frame=__import__('pandas').DataFrame()
result=scope['_atendimentos_com_historico']('monitor_asn','2026-08-01')
assert list(result.os_id)==['old-closed']
print('PASS: archived open OS closure and deletion do not resurrect stale maintenance')
