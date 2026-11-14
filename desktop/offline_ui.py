"""Telas dos aplicativos consultam somente o banco deste computador."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from offline_modules import DATASETS,module_tables,local_status,local_rows,local_history,apply_feed,save_connection,authorized

class OfflineModulesUI:
 def render_module(self,name):
  authorized(self.store,name)
  ttk.Label(self.area,text='Base local • consulta sem internet • integração somente de entrada.\nAs alterações da origem ficam registradas no histórico deste computador.',wraplength=1000,justify='left').pack(anchor='w',pady=(0,10))
  state=local_status(self.store,name)
  ready=sum(bool(r['updated_at']) for r in state if r['conjunto'] in DATASETS[name]);total=len(DATASETS[name])
  ttk.Label(self.area,text=f'{ready} de {total} conjuntos alimentados. '+('Integração parcial: confira os conjuntos pendentes.' if ready<total else 'Todos os conjuntos possuem uma cópia local.'),foreground='#a36d18' if ready<total else '#087f8c').pack(anchor='w',pady=(0,8))
  buttons=ttk.Frame(self.area);buttons.pack(fill='x',pady=(0,8))
  if self.store.can('sync.run'):
   self.button(buttons,'Atualizar agora',self.manual_sync,True).pack(side='left',padx=(0,6))
   self.button(buttons,'Importar alimentação JSON',lambda:self.import_module_feed(name)).pack(side='left',padx=3)
  if self.store.admin():self.button(buttons,'Configurar conexão de entrada',lambda:self.configure_module_feed(name)).pack(side='left',padx=3)
  self.button(buttons,'Histórico local',lambda:self.module_history(name,self.module_dataset.get())).pack(side='left',padx=3)
  if self.store.can('data.export'):self.button(buttons,'Exportar consulta',self.export).pack(side='left',padx=3)
  controls=ttk.Frame(self.area);controls.pack(fill='x',pady=(0,8));ttk.Label(controls,text='Conjunto').pack(side='left')
  self.module_dataset=tk.StringVar(value=next(iter(DATASETS[name])));self.module_absent=tk.BooleanVar(value=False);self.module_search=tk.StringVar()
  box=ttk.Combobox(controls,textvariable=self.module_dataset,values=list(module_tables(name)),state='readonly',width=25);box.pack(side='left',padx=6)
  ttk.Checkbutton(controls,text='Incluir ausentes da origem',variable=self.module_absent,command=lambda:self.module_load(name)).pack(side='left',padx=6)
  ttk.Entry(controls,textvariable=self.module_search,width=22).pack(side='left',padx=6);self.button(controls,'Buscar',lambda:self.module_load(name)).pack(side='left')
  self.module_info=ttk.Label(self.area,text='',wraplength=1000);self.module_info.pack(anchor='w',pady=(0,8))
  self.module_result=ttk.Frame(self.area);self.module_result.pack(fill='both',expand=True)
  box.bind('<<ComboboxSelected>>',lambda e:self.module_load(name));self.module_load(name)
 def module_load(self,name):
  dataset=self.module_dataset.get();rows=local_rows(self.store,name,dataset,self.module_absent.get(),self.module_search.get())
  state=next(r for r in local_status(self.store,name) if r['conjunto']==dataset)
  self.module_info.configure(text=state['situacao']+' • Última cópia: '+(state['updated_at'] or 'nenhuma')+f" • {state['registros_locais']} registros preservados, {state['presentes_na_origem']} presentes na última origem.\n"+('O conjunto ainda não foi importado; não representa uma base vazia.' if not state['updated_at'] else ''))
  for w in self.module_result.winfo_children():w.destroy()
  cols=sorted({k for r in rows for k in r if not k.startswith('_')})+['_source_present']
  self.table(self.module_result,rows,cols,lambda:self.module_record(name,dataset,self.selected()))
 def module_record(self,name,dataset,row):
  authorized(self.store,name)
  dialog=tk.Toplevel(self.root);dialog.title(name+' • registro local');dialog.geometry('900x650')
  self.button(dialog,'Histórico deste registro',lambda:self.module_history(name,dataset,row['_source_id'])).pack(anchor='w',padx=12,pady=10)
  box=tk.Text(dialog,wrap='word',font=('Consolas',10));box.pack(fill='both',expand=True,padx=12,pady=10);box.insert('1.0',json.dumps(row,ensure_ascii=False,indent=2));box.configure(state='disabled')
 def module_history(self,name,dataset,source_id=None):
  events=local_history(self.store,name,dataset,source_id);dialog=tk.Toplevel(self.root);dialog.title(name+' • histórico • '+dataset);dialog.geometry('950x680')
  ttk.Label(dialog,text=f'{len(events)} alterações registradas. Horários, origem e valores antes/depois são preservados.').pack(anchor='w',padx=12,pady=10)
  box=tk.Text(dialog,wrap='word',font=('Consolas',10));box.pack(fill='both',expand=True,padx=12,pady=10)
  for event in events:
   event=dict(event)
   for key in ('before_json','after_json'):
    if event.get(key):event[key]=json.loads(event[key])
   box.insert('end',json.dumps(event,ensure_ascii=False,indent=2)+'\n\n')
  box.configure(state='disabled')
 def import_module_feed(self,name):
  authorized(self.store,name);self.store.require('sync.run')
  path=filedialog.askopenfilename(title='Alimentação completa • '+name,filetypes=[('JSON','*.json')])
  if not path:return
  payload=json.loads(Path(path).read_text(encoding='utf-8-sig'));n=apply_feed(self.store,name,payload,'Importação de arquivo JSON');messagebox.showinfo('Base local alimentada',f'{n} registros processados. Histórico preservado.');self.page(name)
 def configure_module_feed(self,name):
  if not self.store.admin():raise ValueError('Somente administrador configura conexões.')
  path=filedialog.askopenfilename(title='Conexão de entrada • '+name,filetypes=[('Conexão JSON','*.json *.10sul')])
  if not path:return
  save_connection(self.store,name,json.loads(Path(path).read_text(encoding='utf-8-sig')));messagebox.showinfo('Conexão salva','Conexão protegida neste usuário Windows. A alimentação será consultada a cada minuto, com o portal aberto.');self.sync_begin()
