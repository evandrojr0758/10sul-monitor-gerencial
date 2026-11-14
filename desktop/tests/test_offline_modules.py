import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core import Store
from offline_modules import DATASETS,apply_feed,local_rows,local_history,local_status,validate_feed,validate_connection
class OfflineModulesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.store.add_user('admin','senha-teste-123','Administrador');self.store.login('admin','senha-teste-123')
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def feed(self,module,data,at='2026-11-14T12:00:00-03:00'):
  return {'version':1,'module':module,'complete':True,'source_at':at,'datasets':data}
 def test_every_module_offline_after_restart(self):
  for module,datasets in DATASETS.items():apply_feed(self.store,module,self.feed(module,{label:[{**{k:'1' for k in keys},'descricao':'Exemplo'}] for label,(table,keys) in datasets.items()}))
  self.store.close();self.store=Store(self.tmp.name);self.store.login('admin','senha-teste-123')
  with patch('urllib.request.urlopen',side_effect=AssertionError('Consulta offline tentou acessar a rede')):
   for module,datasets in DATASETS.items():
    for label in datasets:
     self.assertEqual(local_rows(self.store,module,label)[0]['descricao'],'Exemplo');self.assertTrue(local_history(self.store,module,label))
 def test_changes_absence_reappearance_preserve_history(self):
  name='Estoque de pneus';dataset='pneus'
  for value,minute in [(10,0),(7,1),(None,2)]:apply_feed(self.store,name,self.feed(name,{dataset:[{'id':'P1','quantidade':value}] if value is not None else []},f'2026-11-14T12:0{minute}:00-03:00'))
  self.assertEqual(local_rows(self.store,name,dataset),[]);self.assertEqual(local_rows(self.store,name,dataset,True)[0]['quantidade'],7)
  events=local_history(self.store,name,dataset);self.assertEqual(len(events),3);self.assertEqual(json.loads(events[1]['before_json'])['quantidade'],10);self.assertEqual(json.loads(events[1]['after_json'])['quantidade'],7)
  apply_feed(self.store,name,self.feed(name,{dataset:[{'id':'P1','quantidade':8}]},'2026-11-14T12:03:00-03:00'));self.assertEqual(len(local_rows(self.store,name,dataset,True)),1)
 def test_idempotent_snapshot_with_reordered_rows(self):
  name='Financeiro 10 Sul';feed=self.feed(name,{'contas':[{'id':1,'valor':1},{'id':2,'valor':2}]});apply_feed(self.store,name,feed);feed['datasets']['contas'].reverse();apply_feed(self.store,name,feed);self.assertEqual(len(local_history(self.store,name,'contas')),2)
 def test_partial_duplicate_stale_conflicting_rejected(self):
  name='Projeto Lean';apply_feed(self.store,name,self.feed(name,{'projetos':[{'id':1,'valor':10}]}))
  for bad in [self.feed(name,{'projetos':[{'id':1},{'id':1}]}),{**self.feed(name,{'projetos':[]}),'complete':False},self.feed(name,{'projetos':[]},'2026-11-13T12:00:00-03:00'),self.feed(name,{'projetos':[]})]:
   with self.assertRaises(ValueError):apply_feed(self.store,name,bad)
  self.assertEqual(local_rows(self.store,name,'projetos')[0]['valor'],10)
 def test_atomic_rollback_of_data_and_history(self):
  name='Solicitações de peças PCM';wide={'id':'2',**{'campo'+str(i):i for i in range(75)}}
  with self.assertRaises(ValueError):apply_feed(self.store,name,self.feed(name,{'solicitacoes':[{'id':'1'}],'itens':[wide]}))
  self.assertFalse(local_rows(self.store,name,'solicitacoes'));self.assertFalse(local_history(self.store,name,'solicitacoes'));self.assertFalse(self.store.db.execute('SELECT * FROM source_catalog WHERE module=?',(name,)).fetchall())
 def test_unconfigured_is_not_empty(self):
  name='Estoque do socorro';apply_feed(self.store,name,self.feed(name,{'reposicao':[]}));status={r['conjunto']:r for r in local_status(self.store,name)};self.assertEqual(status['reposicao']['situacao'],'Disponível offline');self.assertEqual(status['movimentacoes']['situacao'],'Aguardando primeira alimentação')
 def test_backup_restores_data_and_history(self):
  name='Propostas comerciais';apply_feed(self.store,name,self.feed(name,{'propostas':[{'id':1,'valor':123}]}));backup=Path(self.tmp.name)/'backup.zip';self.store.backup(backup)
  apply_feed(self.store,name,self.feed(name,{'propostas':[]},'2026-11-14T12:01:00-03:00'));self.store.restore(backup);self.store.login('admin','senha-teste-123');self.assertEqual(local_rows(self.store,name,'propostas')[0]['valor'],123);self.assertTrue(local_history(self.store,name,'propostas'))
 def test_profile_cannot_read_or_import(self):
  self.store.add_user('consulta','senha-teste-123','Operacional',profile='Consulta');self.store.login('consulta','senha-teste-123')
  with self.assertRaises(ValueError):local_rows(self.store,'Financeiro 10 Sul','contas')
  with self.assertRaises(ValueError):apply_feed(self.store,'Financeiro 10 Sul',self.feed('Financeiro 10 Sul',{'contas':[]}))
 def test_arbitrary_tables_credentials_and_hosts_rejected(self):
  name='Estoque do socorro'
  for data in [{'users':[{'id':'1'}]},{'itens':[{'id':'1','password':'senha'}]}]:
   with self.assertRaises(ValueError):validate_feed(name,self.feed(name,data))
  for endpoint in ['http://10sul-estoque-cocb.streamlit.app/feed','https://outro.exemplo/feed','https://10sul-estoque-cocb.streamlit.app/feed?token=segredo']:
   with self.assertRaises(ValueError):validate_connection(name,{'endpoint':endpoint})
