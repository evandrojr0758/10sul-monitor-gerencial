"""Integrações, aplicativos incorporados e manutenção do banco local."""
import json,os,queue,subprocess,sys,threading
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
from datetime import timedelta
from pathlib import Path
from core import now,stamp,shown
from modules import MODULES
from asn_sync import fetch_snapshot,apply_snapshot,sync_state,fetch_business_sources
from mirrors import mirror_snapshot
from history import list_tables,execute_sql,save_report,qi

class IntegrationUI:
    def init_integrations(self):
        self.sync_busy=False;self.sync_queue=queue.Queue();self.sync_error='';self.business_errors=[];self.active_modules=[]
        self.root.after(1000,self.sync_begin);self.root.after(200,self.sync_poll);self.root.after(60000,self.sync_cycle)
    def sync_cycle(self):
        self.sync_begin();self.root.after(60000,self.sync_cycle)
    def sync_begin(self):
        if os.environ.get('SUL_DISABLE_NETWORK')=='1' or self.sync_busy or not self.store.user:return
        self.sync_busy=True
        def work():
            try:self.sync_queue.put(('asn',fetch_snapshot()))
            except Exception as e:self.sync_queue.put(('error',str(e)))
            try:
                outputs,errors=fetch_business_sources(self.store.root);self.sync_queue.put(('business',(outputs,errors)))
            except Exception as e:self.sync_queue.put(('business',([], [str(e)])))
            finally:self.sync_queue.put(('done',None))
        threading.Thread(target=work,daemon=True).start();self.update_source_status()
    def sync_poll(self):
        changed=False
        try:
            while True:
                kind,data=self.sync_queue.get_nowait()
                if kind=='asn':
                    try:
                        actor=self.store.user;self.store.user='integração:ASN'
                        apply_snapshot(self.store,data);self.sync_error='';changed=True
                    except Exception as e:self.sync_error=str(e)
                    finally:self.store.user=actor
                elif kind=='error':self.sync_error=data
                elif kind=='business':
                    outputs,self.business_errors=data
                    for item in outputs:
                        actor=self.store.user;self.store.user='integração:'+item['module']
                        try:mirror_snapshot(self.store,item['table'],item['module'],item['origin'],item['records'],item['keys'])
                        except Exception as e:self.business_errors.append(str(e))
                        finally:self.store.user=actor
                elif kind=='done':self.sync_busy=False
        except queue.Empty:pass
        self.update_source_status()
        if changed and self.store.user and self.current in ('Monitor da oficina','Ordens de manutenção','Histórico por frota','Integração ASN'):
            if not any(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()):self.refresh()
        self.root.after(200,self.sync_poll)
    def source_text(self):
        s=sync_state(self.store)
        if not s:return 'ASN: aguardando primeira conexão'+(' • '+self.sync_error if self.sync_error else '')
        text='ASN: origem '+(shown(s.get('source_at')) or 'não informada')+' • cópia no computador '+shown(s.get('applied_at'))
        if self.sync_busy:text+=' • atualizando'
        if self.sync_error:text+=' • sem nova atualização; usando cópia local'
        return text
    def update_source_status(self):
        if hasattr(self,'source_label') and self.source_label.winfo_exists():self.source_label.configure(text=self.source_text())
    def render_integrations(self,name):
        if name=='Aplicativos integrados':
            ttk.Label(self.area,text='Aplicativos originais dentro do portal. Mantêm os dados, acessos e regras já existentes.\nOs módulos conectados precisam de internet; a consulta da oficina usa também a cópia local.',wraplength=850,justify='left').pack(anchor='w',pady=(0,15))
            canvas=tk.Canvas(self.area,highlightthickness=0,bg='#edf2f7');vs=ttk.Scrollbar(self.area,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=vs.set);vs.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
            grid=ttk.Frame(canvas);wid=canvas.create_window((0,0),window=grid,anchor='nw');grid.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(wid,width=e.width))
            for name,data in MODULES.items():
                frame=ttk.Frame(grid,padding=15);frame.pack(fill='x',pady=5);ttk.Label(frame,text=name,font=('Segoe UI',14,'bold')).pack(anchor='w');ttk.Label(frame,text=data['subtitle'],wraplength=750).pack(anchor='w',pady=5);self.button(frame,'Abrir no portal • conectado',lambda key=name:self.page(key),True).pack(anchor='w')
        elif name in MODULES:self.render_module(name)
        elif name=='Integração ASN':
            self.actions([('Sincronizar agora',self.sync_begin),('Ver tabelas',lambda:self.page('Manutenção SQL')),('Importar conexão do estoque',self.import_stock_connection)])
            ttk.Label(self.area,text=self.source_text(),wraplength=900,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=12)
            quality=sum(bool(r.get('asn_alert')) for r in self.store.orders())
            if quality:ttk.Label(self.area,text=f'{quality} OS com datas incompletas ou inconsistentes na origem. Confira a coluna Conferência ASN em Ordens de manutenção.',wraplength=900,foreground='#a36d18').pack(anchor='w',pady=6)
            ttk.Label(self.area,text='Origem: Lista ASN do SharePoint do cliente → integração existente → monitor_asn → cópia local.\nConsulta de leitura, atualização automática a cada minuto enquanto o portal está aberto.\nSem conexão, preserva a última base. A liberação 10 Sul não altera a OS do cliente.\nRegistros excluídos na origem saem do monitor, mantendo o histórico local.\nAs cópias dos demais aplicativos ficam em tabelas cloud_* com origem e data em source_catalog.',wraplength=900,justify='left').pack(anchor='w',pady=12)
            if self.sync_error:ttk.Label(self.area,text=self.sync_error,foreground='#a52935',wraplength=900).pack(anchor='w',pady=10)
            if self.business_errors:ttk.Label(self.area,text='\n'.join(self.business_errors),foreground='#a36d18',wraplength=900).pack(anchor='w',pady=10)
            self.table(self.area,[dict(r) for r in self.store.db.execute('SELECT * FROM source_catalog ORDER BY module,table_name')],['table_name','module','updated_at','description'])
        elif name=='Manutenção SQL':self.sql_page()
        elif name=='Histórico do sistema':
            self.actions([('Atualizar',self.refresh),('Ver alteração',self.history_detail),('Exportar',self.export)])
            self.table(self.area,[dict(r) for r in self.store.db.execute('SELECT * FROM change_history ORDER BY id DESC LIMIT 10000')],['id','changed_at','actor','table_name','action','row_key'],self.history_detail)
        else:return False
        return True
    def import_stock_connection(self):
        from credentials import save_stock_profile
        path=filedialog.askopenfilename(title='Conexão de leitura do estoque',filetypes=[('Conexão 10 Sul','*.10sul *.json')])
        if path:
            profile=json.loads(Path(path).read_text(encoding='utf-8-sig'));save_stock_profile(self.store,profile);messagebox.showinfo('Conexão do estoque','Conexão salva neste usuário Windows. Clique em Sincronizar agora.');self.sync_begin()
    def render_module(self,name):
        module=MODULES[name]
        ttk.Label(self.area,text='Aplicativo conectado • '+module['subtitle']+'\nUsa os mesmos dados e acessos do aplicativo original. A conexão é necessária para consultar e gravar no servidor.',wraplength=1050,justify='left').pack(anchor='w',pady=(0,10))
        if sys.platform!='win32':
            ttk.Label(self.area,text='O navegador incorporado está disponível no instalador Windows.').pack(anchor='w');return
        host=tk.Frame(self.area,bg='white');host.pack(fill='both',expand=True);self.root.update_idletasks()
        cmd=[sys.executable]
        if not getattr(sys,'frozen',False):cmd+=[str(Path(__file__).with_name('app.py'))]
        cmd+=['--module',name,'--parent',str(host.winfo_id())]
        process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.active_modules.append(process)
        self.module_host=host
    def sql_page(self):
        if not self.store.admin():raise ValueError('Acesso exclusivo do administrador.')
        line=ttk.Frame(self.area);line.pack(fill='x',pady=(0,8));self.write_sql=tk.BooleanVar(value=False)
        ttk.Checkbutton(line,text='Permitir comandos de alteração na base local',variable=self.write_sql).pack(side='top',anchor='w')
        self.button(line,'Executar SQL',self.sql_run,True).pack(side='left',padx=8);self.button(line,'Salvar consulta',self.sql_save).pack(side='left',padx=3);self.button(line,'Exportar resultado',self.export).pack(side='left',padx=3)
        saved=[dict(r) for r in self.store.db.execute('SELECT * FROM report_queries ORDER BY name')];self.saved_queries={r['name']:r for r in saved};self.saved_choice=tk.StringVar()
        line2=ttk.Frame(self.area);line2.pack(fill='x',pady=(0,8));ttk.Label(line2,text='Consultas salvas:').pack(side='left');box=ttk.Combobox(line2,textvariable=self.saved_choice,values=list(self.saved_queries),state='readonly',width=40);box.pack(side='left',padx=8);box.bind('<<ComboboxSelected>>',lambda e:self.sql_load())
        ttk.Label(self.area,text='Conexão: banco local SQLite. cloud_* são cópias de consulta; não executa comandos no SharePoint ou nos servidores.\nCada alteração local gera histórico. Comandos de escrita criam backup antes de executar. Uma instrução por execução.',wraplength=1050,foreground='#697f91').pack(anchor='w',pady=(0,8))
        upper=ttk.Panedwindow(self.area,orient='horizontal');upper.pack(fill='x');schema=ttk.Frame(upper);editor=ttk.Frame(upper);upper.add(schema,weight=1);upper.add(editor,weight=3)
        self.schema_tree=ttk.Treeview(schema,show='tree',height=4);self.schema_tree.pack(fill='both',expand=True)
        for table in list_tables(self.store):
            node=self.schema_tree.insert('','end',text=table['table']+' ('+str(table['rows'])+')',values=(table['table'],))
            for c in table['columns']:self.schema_tree.insert(node,'end',text=c['name']+' • '+c['type'])
        self.schema_tree.bind('<Double-1>',lambda e:self.sql_pick_table())
        self.sql_editor=tk.Text(editor,height=6,font=('Consolas',11),wrap='none',undo=True);self.sql_editor.pack(fill='both',expand=True);self.sql_editor.insert('1.0','SELECT * FROM orders LIMIT 100;')
        self.sql_result_frame=ttk.Frame(self.area);self.sql_result_frame.pack(fill='both',expand=True,pady=(10,0));self.table(self.sql_result_frame,[],['resultado'])
    def sql_pick_table(self):
        ids=self.schema_tree.selection()
        if not ids:return
        row=self.schema_tree.item(ids[0]);table=row['values'][0] if row['values'] else self.schema_tree.item(self.schema_tree.parent(ids[0]))['values'][0]
        self.sql_editor.delete('1.0','end');self.sql_editor.insert('1.0','SELECT * FROM '+qi(table)+' LIMIT 100;')
    def sql_load(self):self.sql_editor.delete('1.0','end');self.sql_editor.insert('1.0',self.saved_queries[self.saved_choice.get()]['sql_text'])
    def sql_save(self):
        name=simpledialog.askstring('Salvar consulta','Nome do relatório:',parent=self.root)
        if name:save_report(self.store,name,self.sql_editor.get('1.0','end'));messagebox.showinfo('Consulta salva','Consulta salva. Reabra a tela para atualizar a lista.')
    def sql_run(self):
        sql=self.sql_editor.get('1.0','end').strip();write=self.write_sql.get()
        if write:
            if not messagebox.askyesno('Executar comando na base local','Executar este comando de alteração? Será criado um backup e o comando ficará no histórico.\n\n'+sql[:1500]):return
            self.store.backup(self.store.root/('antes_sql_'+now().strftime('%Y%m%d_%H%M%S')+'.zip'))
        result=execute_sql(self.store,sql,write)
        for w in self.sql_result_frame.winfo_children():w.destroy()
        self.table(self.sql_result_frame,result['rows'],result['columns'] or ['resultado']);self.footer.configure(text=f"{result['affected']} registro(s)."+(' Resultado limitado a 20 mil linhas; ajuste o filtro.' if result['truncated'] else '')+' SQL registrado em sql_history.')
    def history_detail(self):
        r=self.selected();dialog=tk.Toplevel(self.root);dialog.title('Histórico da alteração #'+str(r['id']));dialog.geometry('950x650');box=tk.Text(dialog,wrap='none',font=('Consolas',10));box.pack(fill='both',expand=True)
        detail={**r}
        for key in ('before_json','after_json'):
            if detail.get(key):detail[key]=json.loads(detail[key])
        box.insert('1.0',json.dumps(detail,ensure_ascii=False,indent=2));box.configure(state='disabled')
