import json,tempfile,unittest,sys
from datetime import datetime
from pathlib import Path
from core import Store,is_open
from asn_sync import apply_snapshot,fetch_snapshot,sync_state
from history import execute_sql
from mirrors import mirror_snapshot

class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.s=Store(self.t.name);self.s.add_user('admin','senha-teste-123','Administrador');self.s.login('admin','senha-teste-123')
 def tearDown(self):self.s.close();self.t.cleanup()
 def row(self,**kw):return {'os_id':'100','frota':'12345','evento':'ITR','unidade':'ARA','parada':'2026-11-14T08:00:00','inicio':'2026-11-14T08:00:00','status':'Manutenção','fim':None,'sincronizado_em':'2026-11-14T11:01:00Z',**kw}
 def snap(self,rows):return {'records':rows,'downloaded_at':'2026-11-14T08:02:00','source_at':'2026-11-14T08:01:00','count':len(rows)}
 def test_asn_client_open_preserved_after_local_release(self):
  apply_snapshot(self.s,self.snap([self.row()]));self.s.release(('100','12345'),'14/11/2026 10:00');apply_snapshot(self.s,self.snap([self.row()]))
  r=self.s.orders()[0];self.assertTrue(is_open(r));self.assertEqual(r['status'],'Manutenção');self.assertTrue(r['fim_liberacao_10sul']);self.assertEqual(r['liberacao_oficina'],'Liberado 10 Sul')
 def test_source_close_and_delete(self):
  apply_snapshot(self.s,self.snap([self.row()]));apply_snapshot(self.s,self.snap([self.row(status='Liberado',fim='2026-11-14T11:00:00')]))
  self.assertFalse(is_open(self.s.orders()[0]));apply_snapshot(self.s,self.snap([self.row(excluida_asn_em='2026-11-14T12:00:00Z')]))
  self.assertEqual(self.s.orders(),[]);self.assertEqual(self.s.db.execute('select count(*) from orders').fetchone()[0],1)
 def test_missing_snapshot_not_phantom_open(self):
  apply_snapshot(self.s,self.snap([self.row()]));apply_snapshot(self.s,self.snap([self.row(os_id='200')]))
  old=next(r for r in self.s.orders() if r['os_id']=='100');self.assertFalse(is_open(old));self.assertEqual(old['status'],'Ausente na ASN')
 def test_failed_snapshot_atomic(self):
  apply_snapshot(self.s,self.snap([self.row()]));state=sync_state(self.s)
  with self.assertRaises(ValueError):apply_snapshot(self.s,self.snap([self.row(local_manutencao='não deve gravar'),self.row(os_id='200',parada='INVÁLIDA')]))
  self.assertEqual(self.s.orders()[0]['local_manutencao'],'');self.assertEqual(sync_state(self.s),state)
 def test_source_bad_end_preserved_and_flagged(self):
  apply_snapshot(self.s,self.snap([self.row(fim='2026-11-14T07:00:00',status='Liberado')]))
  self.assertEqual(self.s.orders()[0]['asn_alert'],'Fim anterior ao início na origem')
  self.assertEqual(self.s.orders()[0]['fim_asn'],'2026-11-14T07:00:00')
 def test_pagination_complete_and_failure(self):
  pages=iter([[self.row()], [self.row(os_id='200')], []]);r=fetch_snapshot(page_size=1,requester=lambda req:next(pages));self.assertEqual(r['count'],2)
  pages=iter([[self.row()],[self.row()]])
  with self.assertRaises(ValueError):fetch_snapshot(page_size=1,requester=lambda req:next(pages))
 def test_history_sql_catches_changes_and_rollback(self):
  self.s.save_order(self.row());before=self.s.db.execute('select count(*) from change_history where table_name="orders"').fetchone()[0]
  execute_sql(self.s,"UPDATE orders SET descricao='Novo serviço' WHERE os_id='100'",True)
  last=dict(self.s.db.execute('select * from change_history where table_name="orders" order by id desc').fetchone());self.assertEqual(last['actor'],'admin');self.assertEqual(json.loads(last['after_json'])['descricao'],'Novo serviço');self.assertEqual(self.s.db.execute('select count(*) from change_history where table_name="orders"').fetchone()[0],before+1)
  with self.assertRaises(ValueError):execute_sql(self.s,'UPDATE orders SET descricao="proibido"')
  self.assertEqual(self.s.orders()[0]['descricao'],'Novo serviço')
 def test_audit_not_editable_and_transactions_blocked(self):
  for sql in ['DELETE FROM change_history','DROP TABLE change_history','ATTACH DATABASE "other.db" AS other','PRAGMA writable_schema=ON','BEGIN']:
   with self.assertRaises(ValueError,msg=sql):execute_sql(self.s,sql,True)
  self.assertEqual(self.s.db.execute('select count(*) from sql_history').fetchone()[0],5)
 def test_custom_table_gets_history(self):
  execute_sql(self.s,'CREATE TABLE teste_relatorio(id INTEGER PRIMARY KEY,valor TEXT)',True);execute_sql(self.s,"INSERT INTO teste_relatorio(valor) VALUES ('valor')",True)
  self.assertEqual(self.s.db.execute('select action from change_history where table_name="teste_relatorio"').fetchone()[0],'INSERT')
 def test_mirror_no_false_changes_and_sql_readonly(self):
  args=('cloud_teste','Teste','origem',[{'id':1,'valor':10}],['id']);mirror_snapshot(self.s,*args);n=self.s.db.execute('select count(*) from change_history').fetchone()[0];mirror_snapshot(self.s,*args)
  self.assertEqual(self.s.db.execute('select count(*) from change_history').fetchone()[0],n)
  mirror_snapshot(self.s,'cloud_teste','Teste','origem',[{'id':1,'valor':20}],['id']);mirror_snapshot(self.s,'cloud_teste','Teste','origem',[],['id'])
  self.assertEqual(self.s.db.execute('select _source_present from cloud_teste').fetchone()[0],0)
  with self.assertRaises(ValueError):execute_sql(self.s,'UPDATE cloud_teste SET valor=5',True)
 def test_password_not_in_history(self):
  events=self.s.db.execute('select after_json from change_history where table_name="users"').fetchall();self.assertTrue(events);self.assertNotIn('password',events[0][0])
 @unittest.skipUnless(sys.platform=='win32','DPAPI disponível somente no Windows')
 def test_connection_profile_encrypted_roundtrip(self):
  from credentials import save_stock_profile,read_stock_profile
  profile={'endpoint':'https://dezsul-estoque-api.peachycrown16.chatgpt.site/api/estoque.json','headers':{'X-API-Key':'test-read-only','OAI-Sites-Authorization':'Bearer test-only'}}
  save_stock_profile(self.s,profile);self.assertEqual(read_stock_profile(self.s.root),profile)
  stored=self.s.db.execute('select value from connection_profiles').fetchone()[0];self.assertNotIn('test-read-only',stored)
 def test_pragma_schema_readable(self):self.assertTrue(execute_sql(self.s,'PRAGMA table_info(orders)')['rows'])

if __name__=='__main__':unittest.main()
