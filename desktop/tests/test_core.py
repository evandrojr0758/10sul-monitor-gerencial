import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime,timedelta
from core import Store,date,duration,is_open,metric_rows,daily_metrics,read_records,export_csv

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'data');self.s.add_user('admin','senha-teste-123','Administrador');self.assertTrue(self.s.login('admin','senha-teste-123'))
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def row(self,**kw):return {'os_id':'100','frota':'12345','unidade':'ARA','evento':'ITR','parada':'14/11/2026 08:00',**kw}
    def test_persistence_and_release_separate_from_client(self):
        self.s.save_order(self.row());self.s.release(('100','12345'),'14/11/2026 10:00');r=self.s.orders()[0];self.assertEqual(r['fim_asn'],'');self.assertEqual(duration(r),2);self.assertFalse(is_open(r))
        self.s.close();self.s=Store(Path(self.tmp.name)/'data');self.assertEqual(self.s.orders()[0]['status'],'Liberado')
    def test_import_preserves_local_decisions(self):
        self.s.save_order(self.row(inicio='14/11/2026 09:00',previsao='14/11/2026 16:00',expurgo='Limitar ao SLA',motivo_expurgo='Aguardou peça'))
        self.s.release(('100','12345'),'14/11/2026 10:00')
        self.s.import_orders([self.row(inicio='14/11/2026 08:30',descricao='Origem atualizada',fim='14/11/2026 11:00')])
        r=self.s.orders()[0];self.assertEqual(r['inicio'],'2026-11-14T09:00:00');self.assertEqual(r['fim_liberacao_10sul'],'2026-11-14T10:00:00');self.assertEqual(r['expurgo'],'Limitar ao SLA');self.assertEqual(r['fim_asn'],'2026-11-14T11:00:00')
    def test_invalid_import_rolls_back_all_rows(self):
        with self.assertRaises(ValueError):self.s.import_orders([self.row(),self.row(os_id='101',parada='data quebrada')])
        self.assertEqual(self.s.orders(),[])
    def test_metrics_sla_open_special_exclusion_cap(self):
        at=datetime(2026,11,15,8)
        rows=[self.row(inicio='14/11/2026 08:00'),self.row(frota='13169'),self.row(os_id='2',inicio='15/11/2026 07:00'),self.row(os_id='3',expurgo='Excluir'),self.row(os_id='4',inicio='14/11/2026 08:00',expurgo='Limitar ao SLA')]
        got=metric_rows(rows,'ITR',at=at);self.assertEqual([v for r,v in got],[24,12])
    def test_daily_split_at_midnight(self):
        rows=[self.row(inicio='14/11/2026 22:00',fim_asn='15/11/2026 02:00')]
        got=daily_metrics(rows,'ITR',datetime(2026,11,14),datetime(2026,11,16),datetime(2026,11,16));self.assertEqual(got,{'2026-11-14':2,'2026-11-15':2})
    def test_backup_with_evidence_restore(self):
        self.s.save_order(self.row());p=Path(self.tmp.name)/'laudo.pdf';p.write_bytes(b'%PDF teste')
        self.s.add_activity({'os_id':'100','frota':'12345','atividade':'Inspeção','inicio':'14/11/2026 08:00','fim':'14/11/2026 09:00'},p)
        b=Path(self.tmp.name)/'backup.zip';self.s.backup(b);self.s.save_order(self.row(os_id='101'));self.s.restore(b)
        self.assertEqual(len(self.s.orders()),1);a=self.s.activities()[0];self.assertEqual((self.s.root/'anexos'/a['arquivo']).read_bytes(),p.read_bytes())
    def test_reject_zip_traversal(self):
        b=Path(self.tmp.name)/'bad.zip'
        with zipfile.ZipFile(b,'w') as z:z.writestr('../escape','bad');z.writestr('manutencao.sqlite3','bad')
        with self.assertRaises(ValueError):self.s.restore(b)
        self.assertFalse((self.s.root.parent/'escape').exists())
    def test_credentials_and_role(self):
        self.assertFalse(self.s.login('admin','wrong'));self.s.add_user('operador','senha-operador');self.assertTrue(self.s.login('operador','senha-operador'))
        with self.assertRaises(ValueError):self.s.add_user('intruso','12345678','Administrador')
        with self.assertRaises(ValueError):self.s.save_order(self.row(expurgo='Excluir',motivo_expurgo='teste'))
    def test_operator_can_edit_without_changing_existing_expurgo(self):
        self.s.save_order(self.row(expurgo='Limitar ao SLA',motivo_expurgo='Decisão do gestor'))
        self.s.add_user('operador','senha-operador');self.s.login('operador','senha-operador')
        r=self.s.orders()[0];r['descricao']='Serviço executado';self.s.save_order(r)
        self.assertEqual(self.s.orders()[0]['expurgo'],'Limitar ao SLA')
        r['motivo_expurgo']='alterado'
        with self.assertRaises(ValueError):self.s.save_order(r)
    def test_plan_matches_unit_fleet_event_day(self):
        self.s.save_order(self.row());self.s.plan({'data':'14/11/2026','frota':'GO 12345','evento':'ITR','unidade':'ARA'});self.s.plan({'data':'14/11/2026','frota':'12345','evento':'ITR','unidade':'MUC'})
        result=self.s.plans();self.assertEqual([r['situacao'] for r in result if r['unidade']=='ARA'],['Atendida']);self.assertNotEqual([r['situacao'] for r in result if r['unidade']=='MUC'],['Atendida'])
    def test_export_roundtrip_and_formula_guard(self):
        p=Path(self.tmp.name)/'data.csv';export_csv(p,[self.row(descricao='=1+1')],['os_id','frota','evento','descricao']);r=read_records(p);self.assertEqual(r[0]['descricao'],"'=1+1")
    def test_end_before_start_rejected(self):
        with self.assertRaises(ValueError):self.s.save_order(self.row(fim_asn='13/11/2026 10:00'))
    def test_timezone_conversion(self):self.assertEqual(date('2026-11-14T11:00:00Z'),datetime(2026,11,14,8))

if __name__=='__main__':unittest.main()
