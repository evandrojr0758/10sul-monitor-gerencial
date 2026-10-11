import ast
from pathlib import Path
import pandas as pd
source=(Path(__file__).resolve().parents[1] / 'monitor_web.py').read_text()
scope={'pd':pd}
for node in ast.parse(source).body:
    if isinstance(node,ast.FunctionDef) and node.name in {'_hora_brasilia','_inconsistencias_asn'}:
        exec(compile(ast.Module(body=[node],type_ignores=[]),'monitor','exec'),scope)
def row(os,parada,fim=None,status='Manutenção',**kw):
    return dict(os_id=os,frota='13769',evento='SOS PNEU',parada=parada,fim_asn=fim,status=status,sincronizado_em='2026-10-11T20:00:00Z',**kw)
check=lambda rows:scope['_inconsistencias_asn'](pd.DataFrame(rows))
old=row('141493','2026-10-11 14:36:00','2026-10-11 11:59:00','Liberado')
new=row('141506','2026-10-11 17:26:00')
issues=check([old,new])
assert len(issues)==1 and 'anterior à parada' in issues.iloc[0]['SITUAÇÃO']
assert issues.iloc[0]['OS/ID']=='141493' and issues.iloc[0]['OS RELACIONADA']==''
assert check([{**old,'fim_asn':'2026-10-11 15:50:00'},new]).empty
open_old={**old,'fim_asn':None,'status':'Manutenção'}
issues=check([open_old,new]);assert len(issues)==1
assert issues.iloc[0]['OS RELACIONADA']=='141506' and 'sem baixa' in issues.iloc[0]['SITUAÇÃO']
assert check([{**open_old,'excluida_asn_em':'2026-10-11T21:00:00Z'},new]).empty
assert check([{**open_old,'sincronizado_em':None},new]).empty
assert 'sobrepostos' in check([{**old,'fim_asn':'2026-10-11 18:00:00'},new]).iloc[0]['SITUAÇÃO']
assert len(check([open_old,open_old,new]))==1
assert 'liberado sem' in check([{**open_old,'status':'Liberado'}]).iloc[0]['SITUAÇÃO']
assert 'com fim preenchido' in check([{**new,'fim_asn':'2026-10-11 19:00:00'}]).iloc[0]['SITUAÇÃO']
assert check([new]).empty
print('PASS: actual 13769 case, sequential OS, pending older OS, overlapping periods, excluded OS, history-only rows, duplicate source rows and contradictory closure status')
