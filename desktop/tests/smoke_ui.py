"""Smoke real de todas as telas em ambiente gráfico; base temporária."""
import sys,tempfile,os
os.environ["SUL_DISABLE_NETWORK"]="1"
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from core import Store,stamp,now
from app import App
from datetime import timedelta

def run():
    with tempfile.TemporaryDirectory() as tmp:
        s=Store(tmp);s.add_user('teste','senha-teste-123','Administrador');s.login('teste','senha-teste-123')
        for i,event in enumerate(['ITR','REVISÃO 60','CORRETIVA Ñ PROG.','SOS MECÂNICA']):
            s.save_order({'os_id':str(1000+i),'frota':str(12000+i),'unidade':'ARA','evento':event,'parada':stamp(now()-timedelta(hours=14+i*3)),'local_manutencao':'Oficina Aracruz','descricao':'Registro demonstrativo de teste'})
        s.plan({'data':stamp(now()),'frota':'12000','evento':'ITR','unidade':'ARA','grupo':'A'})
        root=tk.Tk();app=App(root,s);s.login('teste','senha-teste-123');app.shell();root.update()
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args))
        app.error=lambda fn:fn()
        names=['Monitor da oficina','Ordens de manutenção','Histórico por frota','Programação preventiva','Laudos e atividades','Indicadores e SLA','Expurgos de SLA','Cadastros','Relatórios','Backup e restauração','Usuários e acessos','Auditoria','Aplicativos integrados','Integração ASN','Manutenção SQL','Histórico do sistema']
        for name in names:
            app.page(name);root.update()
            if name in ('Monitor da oficina','Manutenção SQL','Aplicativos integrados'):
                from PIL import ImageGrab
                out=Path('previews');out.mkdir(exist_ok=True);ImageGrab.grab().save(out/('monitor_windows.png' if name=='Monitor da oficina' else 'sql_windows.png' if name=='Manutenção SQL' else 'aplicativos_windows.png'))
            print('OK tela:',name)
        # Cada aplicativo abre consulta SQLite mesmo com a rede desligada.
        from offline_modules import DATASETS,apply_feed,local_rows
        for module,datasets in DATASETS.items():
            payload={'version':1,'module':module,'complete':True,'source_at':'2026-11-14T12:00:00-03:00','datasets':{label:[{**{k:'TESTE-1' for k in keys},'descricao':'Registro demonstrativo local'}] for label,(table,keys) in datasets.items()}}
            apply_feed(s,module,payload);app.page(module);root.update()
            assert app.rows and app.rows[0]['descricao']=='Registro demonstrativo local',module
            assert not app.active_modules,'Consulta local abriu processo conectado'
            if module=='Estoque do socorro':
                from PIL import ImageGrab
                ImageGrab.grab().save(Path('previews')/'estoque_local_windows.png')
            print('OK aplicativo offline:',module)
        # Formulário de OS longo, programação, usuário e cadastro.
        for fn in (app.order_form,app.plan_form):
            fn();root.update()
            for child in root.winfo_children():
                if isinstance(child,tk.Toplevel):child.destroy()
        if errors:raise AssertionError(errors)
        root.destroy();s.close()
if __name__=='__main__':run()
