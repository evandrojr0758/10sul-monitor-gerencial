"""Interface Windows nativa do Portal da Manutenção 10 Sul."""
import html
import os
import sys
import tkinter as tk
import webbrowser
from datetime import datetime,timedelta
from pathlib import Path
from tkinter import ttk,messagebox,filedialog
from core import Store,EVENTS,FIELDS,VERSION,now,date,stamp,shown,duration,hours,group,is_open,metric_rows,daily_metrics,read_records,export_csv

BG='#edf2f7'; NAV='#10283f'; BLUE='#087f8c'; INK='#17334a'
LABELS={'os_id':'OS / ID','frota':'Frota','unidade':'Unidade','evento':'Evento','status':'Situação','parada':'Parada','inicio':'Início ajustado','fim_asn':'Fim do cliente','fim_liberacao_10sul':'Liberação 10 Sul','local_manutencao':'Local da manutenção','descricao':'Descrição','previsao':'Previsão de liberação','justificativa_previsao':'Justificativa sem previsão','aguardando_peca':'Aguardando peça','expurgo':'Expurgo','motivo_expurgo':'Motivo do expurgo','data':'Data','grupo':'Grupo','situacao':'Aderência','atividade':'Atividade','responsavel':'Responsável','fim':'Fim','arquivo':'Evidência','name':'Nome / código','detail':'Descrição','active':'Ativo','at':'Data/hora','username':'Usuário','action':'Ação','entity':'Registro','role':'Perfil','id':'ID','horas':'Horas','media':'Média (h)','quantidade':'Quantidade'}
DATE_FIELDS={'parada','inicio','fim_asn','fim_liberacao_10sul','previsao','data','fim','at'}
class App:
    def __init__(self,root,store):
        self.root=root;self.store=store;self.current=''; self.unit=tk.StringVar(value='Todas');self.search=tk.StringVar();self.status=tk.StringVar(value='Todos');self.kind=tk.StringVar(value='Todos');self.rows=[];self.cols=[]
        root.title('10 Sul • Portal da Manutenção • Offline '+VERSION);root.geometry('1360x820');root.minsize(1000,650);root.configure(bg=BG)
        st=ttk.Style();st.theme_use('clam');st.configure('.',font=('Segoe UI',10),background=BG,foreground=INK)
        st.configure('Treeview',background='white',fieldbackground='white',rowheight=32,borderwidth=0);st.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),background='#dce7ee',padding=9)
        st.map('Treeview',background=[('selected','#087f8c')],foreground=[('selected','white')]);st.configure('TButton',padding=(12,9));st.configure('Accent.TButton',background=BLUE,foreground='white');st.map('Accent.TButton',background=[('active','#05636d')]);st.configure('TEntry',padding=6);st.configure('TCombobox',padding=5)
        self.login()
    def error(self,fn):
        try:return fn()
        except Exception as e:messagebox.showerror('Não foi possível concluir',str(e),parent=self.root)
    def login(self):
        for w in self.root.winfo_children():w.destroy()
        outer=tk.Frame(self.root,bg=NAV);outer.pack(fill='both',expand=True)
        card=tk.Frame(outer,bg='white',padx=52,pady=36);card.place(relx=.5,rely=.5,anchor='center')
        tk.Label(card,text='10 SUL',bg='white',fg=BLUE,font=('Segoe UI',32,'bold')).pack()
        tk.Label(card,text='PORTAL DA MANUTENÇÃO',bg='white',fg=INK,font=('Segoe UI',17,'bold')).pack(pady=(8,4))
        first=not self.store.users(); tk.Label(card,text='Crie seu administrador local' if first else 'Acesse sua operação offline',bg='white',fg='#617487').pack(pady=(0,24))
        u=tk.StringVar();p=tk.StringVar();confirm=tk.StringVar()
        for label,var in [('Usuário',u),('Senha',p)]+([('Confirmar senha',confirm)] if first else []):
            tk.Label(card,text=label,bg='white',fg=INK,anchor='w').pack(fill='x');ttk.Entry(card,textvariable=var,show='•' if var is not u else '',width=35).pack(pady=(4,14))
        def enter():
            def go():
                if first:
                    if p.get()!=confirm.get():raise ValueError('As senhas não conferem.')
                    self.store.add_user(u.get(),p.get(),'Administrador')
                if self.store.login(u.get(),p.get()):self.shell()
                else:raise ValueError('Usuário ou senha inválidos.')
            self.error(go)
        ttk.Button(card,text='Criar administrador e entrar' if first else 'Entrar',command=enter,style='Accent.TButton').pack(fill='x',pady=6)
        tk.Label(card,text='Dados neste computador • Sem conexão obrigatória',bg='white',fg='#617487',font=('Segoe UI',9)).pack(pady=(20,4))
        tk.Label(card,text='Desenvolvido por Evandro Junior',bg='white',fg='#617487',font=('Segoe UI',9)).pack()
        self.root.bind('<Return>',lambda e:enter())
    def shell(self):
        self.root.unbind('<Return>')
        for w in self.root.winfo_children():w.destroy()
        nav=tk.Frame(self.root,bg=NAV,width=238);nav.pack(side='left',fill='y');nav.pack_propagate(False)
        tk.Label(nav,text='10 SUL',bg=NAV,fg='white',font=('Segoe UI',27,'bold')).pack(anchor='w',padx=25,pady=(28,0))
        tk.Label(nav,text='GESTÃO DA MANUTENÇÃO',bg=NAV,fg='#9ab5c9',font=('Segoe UI',9,'bold')).pack(anchor='w',padx=25,pady=(3,28))
        menus=['Monitor da oficina','Ordens de manutenção','Histórico por frota','Programação preventiva','Laudos e atividades','Indicadores e SLA','Expurgos de SLA','Cadastros','Relatórios','Backup e restauração']
        if self.store.admin():menus+=['Usuários e acessos','Auditoria']
        for name in menus:
            tk.Button(nav,text=name,anchor='w',bg=NAV,fg='#e0edf5',activebackground=BLUE,activeforeground='white',relief='flat',padx=24,pady=11,bd=0,command=lambda n=name:self.page(n)).pack(fill='x')
        tk.Button(nav,text='Sair • '+self.store.user,bg=NAV,fg='#9ab5c9',relief='flat',command=self.login).pack(side='bottom',fill='x',pady=18)
        self.body=tk.Frame(self.root,bg=BG);self.body.pack(side='left',fill='both',expand=True,padx=25,pady=22)
        self.page('Monitor da oficina')
        self.root.after(60000,self.tick)
    def tick(self):
        if self.current=='Monitor da oficina' and hasattr(self,'body') and self.body.winfo_exists():self.page(self.current)
        self.root.after(60000,self.tick)
    def units(self):return [r['name'] for r in self.store.catalogs('Unidades') if r['active']]
    def button(self,parent,title,fn,accent=False):return ttk.Button(parent,text=title,command=lambda:self.error(fn),style='Accent.TButton' if accent else 'TButton')
    def page(self,name):
        self.current=name
        for w in self.body.winfo_children():w.destroy()
        head=tk.Frame(self.body,bg=BG);head.pack(fill='x')
        tk.Label(head,text=name,bg=BG,fg=INK,font=('Segoe UI',23,'bold')).pack(side='left')
        tk.Label(head,text='● OFFLINE  |  '+now().strftime('%d/%m/%Y %H:%M'),bg=BG,fg=BLUE,font=('Segoe UI',10,'bold')).pack(side='right')
        tk.Label(self.body,text='Operação local • 10 Sul • Desenvolvido por Evandro Junior',bg=BG,fg='#697f91').pack(anchor='w',pady=(5,18))
        self.toolbar=tk.Frame(self.body,bg=BG);self.toolbar.pack(fill='x',pady=(0,12))
        self.area=tk.Frame(self.body,bg=BG);self.area.pack(fill='both',expand=True)
        self.footer=tk.Label(self.body,text='',bg=BG,fg='#64798a',anchor='w');self.footer.pack(fill='x',pady=(10,0))
        self.error(lambda:self.render(name))
    def filters(self,with_status=True):
        ttk.Label(self.toolbar,text='Unidade').pack(side='left');box=ttk.Combobox(self.toolbar,textvariable=self.unit,values=['Todas']+self.units(),state='readonly',width=10);box.pack(side='left',padx=(6,14));box.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        ttk.Entry(self.toolbar,textvariable=self.search,width=22).pack(side='left',padx=(0,8));self.button(self.toolbar,'Buscar',self.refresh).pack(side='left',padx=3)
        if with_status:
            b=ttk.Combobox(self.toolbar,textvariable=self.status,values=['Todos','Manutenção','Liberado'],state='readonly',width=13);b.pack(side='left',padx=5);b.bind('<<ComboboxSelected>>',lambda e:self.refresh())
            b=ttk.Combobox(self.toolbar,textvariable=self.kind,values=['Todos','ITR','REVISÃO','CNP','SOS','PIT STOP','OUTROS'],state='readonly',width=12);b.pack(side='left',padx=5);b.bind('<<ComboboxSelected>>',lambda e:self.refresh())
    def filtered(self):
        q=self.search.get().strip().lower();out=[]
        for r in self.store.orders():
            if self.unit.get()!='Todas' and r['unidade']!=self.unit.get():continue
            if q and not any(q in str(r[k]).lower() for k in ('os_id','frota','descricao','local_manutencao')):continue
            if self.status.get()!='Todos' and r['status']!=self.status.get():continue
            if self.kind.get()!='Todos' and group(r['evento'])!=self.kind.get():continue
            out.append(r)
        return out
    def refresh(self):self.page(self.current)
    def table(self,parent,rows,cols,double=None):
        self.rows=list(rows);self.cols=list(cols)
        wrap=tk.Frame(parent,bg='white');wrap.pack(fill='both',expand=True)
        tree=ttk.Treeview(wrap,columns=cols,show='headings',selectmode='browse');self.tree=tree
        for c in cols:tree.heading(c,text=LABELS.get(c,c));tree.column(c,width=180 if c in DATE_FIELDS or c in ('descricao','atividade','detail') else 115,minwidth=70,stretch=True)
        vs=ttk.Scrollbar(wrap,orient='vertical',command=tree.yview);hs=ttk.Scrollbar(wrap,orient='horizontal',command=tree.xview);tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew');vs.grid(row=0,column=1,sticky='ns');hs.grid(row=1,column=0,sticky='ew');wrap.rowconfigure(0,weight=1);wrap.columnconfigure(0,weight=1)
        tree.tag_configure('late',foreground='#a52935',background='#fff0f1');tree.tag_configure('odd',background='#f6f9fc')
        for i,r in enumerate(self.rows):
            vals=[]
            for c in cols:
                v=r.get(c,'')
                if c in DATE_FIELDS and v:
                    try:v=shown(v)
                    except ValueError:pass
                vals.append(v)
            late=r.get('_late',False);tree.insert('', 'end',iid=str(i),values=vals,tags=('late' if late else 'odd' if i%2 else '',))
        if double:tree.bind('<Double-1>',lambda e:self.error(double))
        self.footer.configure(text=f'{len(self.rows)} registros • Clique duas vezes para abrir quando disponível.')
    def selected(self):
        ids=self.tree.selection()
        if not ids:raise ValueError('Selecione um registro na lista.')
        return self.rows[int(ids[0])]
    def actions(self,items):
        f=tk.Frame(self.area,bg=BG);f.pack(fill='x',pady=(0,12))
        for i,(title,fn) in enumerate(items):self.button(f,title,fn,i==0).pack(side='left',padx=(0,7))
    def render(self,name):
        if name in ('Monitor da oficina','Ordens de manutenção','Histórico por frota'):
            self.filters();self.actions([('Nova manutenção',lambda:self.order_form()),('Editar / abrir',lambda:self.order_form(self.selected())),('Liberar 10 Sul',self.release_form),('Importar base',self.import_base),('Exportar',self.export)])
            rows=self.filtered()
            if name=='Monitor da oficina':
                allrows=rows;rows=[r for r in rows if is_open(r)]
                cards=tk.Frame(self.area,bg=BG);cards.pack(fill='x',pady=(0,16))
                for k in ('ITR','REVISÃO','CNP','SOS'):
                    rs=[r for r in rows if group(r['evento'])==k];c=tk.Frame(cards,bg='white',padx=18,pady=12);c.pack(side='left',fill='x',expand=True,padx=(0,10))
                    tk.Label(c,text=str(len(rs)),font=('Segoe UI',28,'bold'),bg='white',fg=BLUE).pack(anchor='w');tk.Label(c,text=k+' em manutenção',bg='white',fg=INK).pack(anchor='w')
                    tk.Label(c,text='Maior tempo: '+hours(max((duration(r) for r in rs),default=0)),bg='white',fg='#697f91').pack(anchor='w')
                    tk.Button(c,text='Ver relação',bg='white',fg=BLUE,relief='flat',command=lambda kind=k:self.card_filter(kind)).pack(anchor='w')
                for r in rows:
                    sla=3 if group(r['evento'])=='SOS' else 12 if group(r['evento'])=='ITR' else 24 if group(r['evento'])=='REVISÃO' else None
                    r['horas']=hours(duration(r));r['_late']=sla is not None and duration(r)>sla
                self.table(self.area,rows,['frota','os_id','evento','parada','horas','local_manutencao','previsao','aguardando_peca'],lambda:self.order_form(self.selected()))
            else:
                if name=='Histórico por frota':
                    info=tk.Frame(self.area,bg='white',padx=15,pady=12);info.pack(fill='x',pady=(0,12))
                    labels=[]
                    for k,interval in [('ITR',20),('REVISÃO',None),('PIT STOP',None)]:
                        rs=[r for r in rows if group(r['evento'])==k and not is_open(r)]
                        if rs:
                            r=max(rs,key=lambda x:date(x['fim_asn'] or x['fim_liberacao_10sul']));d=date(r['fim_asn'] or r['fim_liberacao_10sul']);s=f'Último {k}: {d:%d/%m/%Y} • há {(now().date()-d.date()).days} dias'
                            n=interval
                            if k=='REVISÃO':
                                n=120 if '120' in r['evento'] else 60 if '60' in r['evento'] else 90 if 'TRIMESTRAL' in r['evento'] else None
                            if n:s+=f' • Próximo: {d+timedelta(days=n):%d/%m/%Y}'
                            labels.append(s)
                    tk.Label(info,text='\n'.join(labels) if labels else 'Pesquise a frota para consultar as últimas manutenções concluídas.',bg='white',fg=INK,justify='left').pack(anchor='w')
                self.table(self.area,rows,['os_id','frota','unidade','evento','status','parada','fim_liberacao_10sul','local_manutencao'],lambda:self.order_form(self.selected()))
        elif name=='Programação preventiva':
            self.filters(False);self.actions([('Programar frota',self.plan_form),('Importar programação',self.import_plans),('Excluir programação',self.delete_plan),('Exportar',self.export)])
            rows=[r for r in self.store.plans() if (self.unit.get()=='Todas' or r['unidade']==self.unit.get()) and (not self.search.get() or self.search.get().lower() in r['frota'].lower())]
            self.table(self.area,rows,['data','frota','evento','unidade','grupo','situacao'])
        elif name=='Laudos e atividades':
            self.actions([('Adicionar atividade / laudo',self.activity_form),('Abrir evidência',self.open_attachment),('Exportar',self.export)])
            self.table(self.area,self.store.activities(),['os_id','frota','atividade','responsavel','inicio','fim','arquivo'])
        elif name=='Indicadores e SLA':self.indicators()
        elif name=='Expurgos de SLA':
            self.filters();self.actions([('Tratar OS selecionada',lambda:self.order_form(self.selected())),('Exportar',self.export)])
            rows=self.filtered();self.table(self.area,rows,['os_id','frota','evento','expurgo','motivo_expurgo'],lambda:self.order_form(self.selected()))
        elif name=='Cadastros':self.catalog_page()
        elif name=='Relatórios':
            ttk.Label(self.area,text='Exporte o recorte de cada tela ou gere o relatório completo da operação.',font=('Segoe UI',12)).pack(anchor='w',pady=15)
            self.button(self.area,'Relatório da oficina para impressão / PDF',self.report,True).pack(anchor='w',pady=8)
            self.button(self.area,'Exportar todas as manutenções em Excel',self.export_all).pack(anchor='w',pady=8)
            self.button(self.area,'Salvar modelo de importação',self.template).pack(anchor='w',pady=8)
        elif name=='Backup e restauração':
            ttk.Label(self.area,text='O backup inclui banco, usuários, auditoria e evidências.\nGuarde uma cópia em outro disco ou pasta da empresa.',font=('Segoe UI',12),justify='left').pack(anchor='w',pady=15)
            self.button(self.area,'Criar backup completo',self.backup,True).pack(anchor='w',pady=8)
            if self.store.admin():self.button(self.area,'Restaurar backup',self.restore).pack(anchor='w',pady=8)
            self.button(self.area,'Abrir pasta dos dados',lambda:self.open_file(self.store.root)).pack(anchor='w',pady=8)
            ttk.Label(self.area,text=str(self.store.root)).pack(anchor='w',pady=15)
        elif name=='Usuários e acessos':
            self.actions([('Criar / alterar usuário',self.user_form)]);self.table(self.area,self.store.users(),['username','role','active'])
        elif name=='Auditoria':
            self.actions([('Exportar',self.export)]);self.table(self.area,[dict(x) for x in self.store.db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 3000')],['at','username','action','entity','detail'])
    def card_filter(self,kind):self.kind.set(kind);self.status.set('Manutenção');self.page('Ordens de manutenção')
    def form(self,title,fields,initial,save):
        dialog=tk.Toplevel(self.root);dialog.title(title);dialog.geometry('680x700');dialog.transient(self.root);dialog.grab_set()
        canvas=tk.Canvas(dialog,bg=BG,highlightthickness=0);vs=ttk.Scrollbar(dialog,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=vs.set);vs.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        content=ttk.Frame(canvas,padding=24);wid=canvas.create_window((0,0),window=content,anchor='nw');content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(wid,width=e.width))
        variables={}
        for key,options in fields:
            ttk.Label(content,text=LABELS.get(key,key)).pack(anchor='w',pady=(9,4));value=initial.get(key,'') or ''
            if key in DATE_FIELDS and value:value=shown(value)
            var=tk.StringVar(value=str(value));variables[key]=var
            if options:entry=ttk.Combobox(content,textvariable=var,values=options,state='readonly')
            else:entry=ttk.Entry(content,textvariable=var,show='•' if key=='Senha' else '')
            entry.pack(fill='x')
        ttk.Label(content,text='Datas: DD/MM/AAAA HH:MM • Campos de fim vazios = em manutenção.',foreground='#697f91',wraplength=570).pack(anchor='w',pady=15)
        def commit():
            def run():save({k:v.get() for k,v in variables.items()});dialog.destroy();self.refresh()
            self.error(run)
        self.button(content,'Salvar',commit,True).pack(fill='x',pady=10)
        self.button(content,'Cancelar',dialog.destroy).pack(fill='x')
        return dialog
    def order_form(self,r=None):
        original=r or {}; initial=dict(original)
        if not r:initial.update(unidade=self.units()[0] if self.units() else 'ARA',evento='ITR',parada=stamp(now()))
        cols=['os_id','frota','unidade','evento','parada','inicio','fim_asn','fim_liberacao_10sul','local_manutencao','descricao','previsao','justificativa_previsao','aguardando_peca']
        if self.store.admin():cols+=['expurgo','motivo_expurgo']
        opts={'unidade':self.units(),'evento':EVENTS,'expurgo':['','Excluir','Limitar ao SLA']}
        def save(values):
            if r and (values['os_id']!=r['os_id'] or values['frota']!=r['frota']):raise ValueError('OS e frota identificam o registro e não podem ser alteradas na edição.')
            if not self.store.admin() and r:values.update(expurgo=r.get('expurgo',''),motivo_expurgo=r.get('motivo_expurgo',''))
            self.store.save_order(values)
        self.form('Editar manutenção' if r else 'Nova manutenção',[(c,opts.get(c)) for c in cols],initial,save)
    def release_form(self):
        r=self.selected()
        if not is_open(r):raise ValueError('Esta manutenção já possui fim registrado.')
        self.form('Liberação 10 Sul • '+r['frota'],[('fim_liberacao_10sul',None)],{'fim_liberacao_10sul':stamp(now())},lambda v:self.store.release((r['os_id'],r['frota']),v['fim_liberacao_10sul']) if v['fim_liberacao_10sul'] else (_ for _ in ()).throw(ValueError('Informe a data de liberação.')))
    def import_base(self):
        path=filedialog.askopenfilename(filetypes=[('Dados','*.xlsx *.csv *.json')])
        if not path:return
        records=read_records(path)
        if messagebox.askyesno('Importar base',f'Importar {len(records)} registros? OS existentes serão atualizadas pelo par OS + Frota. Liberações, previsões e expurgos locais serão preservados.'):
            self.store.backup(self.store.root/('antes_importacao_'+now().strftime('%Y%m%d_%H%M%S')+'.zip'))
            n=self.store.import_orders(records);messagebox.showinfo('Importação concluída',f'{n} registros importados.');self.refresh()
    def plan_form(self):self.form('Programação preventiva',[('data',None),('frota',None),('evento',['ITR','REVISÃO 60','REVISÃO 120','REVISÃO TRIMESTRAL']),('unidade',self.units()),('grupo',['','A','B'])],{'data':stamp(now()),'evento':'ITR','unidade':'ARA'},self.store.plan)
    def import_plans(self):
        path=filedialog.askopenfilename(filetypes=[('Programação','*.xlsx *.csv *.json')])
        if not path:return
        rows=read_records(path);prepared=[]
        # Valida todo o arquivo antes de escrever.
        from core import norm,fleet
        for i,r in enumerate(rows,2):
            d={norm(k):v for k,v in r.items()};p={'data':stamp(d.get('DATA') or d.get('DATA PROGRAMADA')),'frota':fleet(d.get('FROTA') or d.get('GO')),'evento':str(d.get('EVENTO') or d.get('TIPO') or 'ITR'),'unidade':str(d.get('UNIDADE') or d.get('UN') or 'ARA'),'grupo':str(d.get('GRUPO') or '')}
            if not p['data'] or not p['frota']:raise ValueError(f'Linha {i}: DATA e FROTA são obrigatórias. Use a planilha tabular com esses cabeçalhos.')
            prepared.append(p)
        for p in prepared:self.store.plan(p)
        messagebox.showinfo('Programação',f'{len(prepared)} programações importadas.');self.refresh()
    def delete_plan(self):
        r=self.selected()
        if messagebox.askyesno('Excluir programação',f"Excluir programação da frota {r['frota']} em {r['data']}?"):
            self.store.db.execute('DELETE FROM plans WHERE id=?',(r['id'],));self.store.log('Programação excluída',str(r['id']),r['frota']);self.store.db.commit();self.refresh()
    def activity_form(self):
        orders=self.store.orders()
        if not orders:raise ValueError('Cadastre ou importe uma manutenção antes de registrar o laudo.')
        keys={f"{r['os_id']} / {r['frota']}":r for r in orders}
        attachment=filedialog.askopenfilename(title='Selecione laudo PDF, foto ou evidência (Cancelar = sem anexo)',filetypes=[('Evidências','*.pdf *.png *.jpg *.jpeg *.mp4'),('Todos','*.*')])
        def save(v):
            r=keys[v.pop('Manutenção')];v.update(os_id=r['os_id'],frota=r['frota']);self.store.add_activity(v,attachment or None)
        self.form('Atividade / laudo',[('Manutenção',list(keys)),('atividade',None),('responsavel',None),('inicio',None),('fim',None)],{'Manutenção':next(iter(keys)),'inicio':stamp(now())},save)
    def open_attachment(self):
        r=self.selected()
        if not r['arquivo']:raise ValueError('Esta atividade não possui evidência anexada.')
        self.open_file(self.store.root/'anexos'/Path(r['arquivo']).name)
    def open_file(self,path):
        if sys.platform=='win32':os.startfile(str(path))
        else:webbrowser.open(Path(path).resolve().as_uri())
    def indicators(self):
        self.filters(False)
        self.start=tk.StringVar(value=now().replace(day=1).strftime('%d/%m/%Y'));self.end=tk.StringVar(value=now().strftime('%d/%m/%Y'))
        line=tk.Frame(self.area,bg=BG);line.pack(fill='x',pady=(0,12))
        for label,var in [('De',self.start),('Até',self.end)]:ttk.Label(line,text=label).pack(side='left',padx=5);ttk.Entry(line,textvariable=var,width=12).pack(side='left')
        self.button(line,'Calcular',self.calculate,True).pack(side='left',padx=10);self.button(line,'Exportar',self.export).pack(side='left')
        ttk.Label(self.area,text='Composição por início da manutenção. Abertas entram após o SLA; frotas especiais e expurgos são tratados.').pack(anchor='w',pady=(0,10))
        self.indicator_area=tk.Frame(self.area,bg=BG);self.indicator_area.pack(fill='both',expand=True);self.calculate()
    def calculate(self):
        a=date(self.start.get());z=date(self.end.get())+timedelta(days=1)
        if z<=a:raise ValueError('Período inválido.')
        for w in self.indicator_area.winfo_children():w.destroy()
        rows=[r for r in self.store.orders() if self.unit.get()=='Todas' or r['unidade']==self.unit.get()];summary=[];composition=[]
        for k in ('ITR','REVISÃO'):
            eligible=metric_rows(rows,k,a,z);avg=sum(v for r,v in eligible)/len(eligible) if eligible else 0
            summary.append(f'{k}: {hours(avg)} de média • {len(eligible)} OS • SLA {12 if k=="ITR" else 24}h')
            composition.extend({**r,'horas':hours(v)} for r,v in eligible)
        ttk.Label(self.indicator_area,text='\n'.join(summary),font=('Segoe UI',14,'bold')).pack(anchor='w',pady=(2,14))
        self.table(self.indicator_area,composition,['os_id','frota','evento','parada','horas','expurgo'])
        daily={k:daily_metrics(rows,k,a,z) for k in ('ITR','REVISÃO')}
        graph=tk.Canvas(self.indicator_area,height=160,bg='white',highlightthickness=0);graph.pack(fill='x',pady=(12,0));graph.bind('<Configure>',lambda e:self.draw_graph(graph,daily))
    def draw_graph(self,canvas,series):
        canvas.delete('all');w=max(canvas.winfo_width(),400);h=160;all_days=sorted(set(d for s in series.values() for d in s));mx=max([24]+[v for s in series.values() for v in s.values()]);canvas.create_text(15,15,anchor='w',text='Média diária • períodos divididos à meia-noite',fill=INK)
        if not all_days:canvas.create_text(w/2,90,text='Sem dados no período',fill='#697f91');return
        for k,color in [('ITR',BLUE),('REVISÃO','#c78118')]:
            points=[]
            for i,d in enumerate(all_days):
                if d in series[k]:points.extend([50+i*(w-90)/max(1,len(all_days)-1),130-series[k][d]/mx*90])
            if len(points)>=4:canvas.create_line(*points,fill=color,width=2)
            elif points:canvas.create_oval(points[0]-3,points[1]-3,points[0]+3,points[1]+3,fill=color)
            canvas.create_text(w-90,15 if k=='ITR' else 32,text=k,fill=color)
        canvas.create_text(50,147,text=all_days[0][5:],fill=INK);canvas.create_text(w-40,147,text=all_days[-1][5:],fill=INK)
    def catalog_page(self):
        self.catalog_kind=tk.StringVar(value=getattr(self,'last_catalog','Frotas'));b=ttk.Combobox(self.toolbar,textvariable=self.catalog_kind,values=['Frotas','Colaboradores','Unidades'],state='readonly');b.pack(side='left');b.bind('<<ComboboxSelected>>',lambda e:self.catalog_change())
        self.actions([('Novo / editar cadastro',self.catalog_form),('Exportar',self.export)]);self.table(self.area,self.store.catalogs(self.catalog_kind.get()),['name','detail','active'])
    def catalog_change(self):self.last_catalog=self.catalog_kind.get();self.refresh()
    def catalog_form(self):
        r=self.selected() if self.tree.selection() else {};kind=self.catalog_kind.get()
        self.form(kind,[('name',None),('detail',None),('active',['1','0'])],{'active':'1',**r},lambda v:self.store.catalog(kind,v['name'],v['detail'],v['active']=='1'))
    def user_form(self):
        r=self.selected() if self.tree.selection() else {}
        self.form('Usuário local',[('username',None),('Senha',None),('role',['Administrador','Operacional']),('active',['1','0'])],{'role':'Operacional','active':'1',**r},lambda v:self.save_user(v))
    def save_user(self,v):
        if v['username'].lower()==self.store.user and (v['role']!='Administrador' or v['active']!='1'):raise ValueError('Você não pode desativar ou rebaixar seu próprio usuário.')
        self.store.add_user(v['username'],v['Senha'],v['role'],v['active']=='1')
    def export(self):
        if not self.rows:raise ValueError('Nenhum registro para exportar.')
        p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV para Excel','*.csv')])
        if p:export_csv(p,self.rows,self.cols);messagebox.showinfo('Exportação','Arquivo salvo.')
    def export_all(self):
        p=filedialog.asksaveasfilename(defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')])
        if not p:return
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill
        w=Workbook();s=w.active;s.title='Manutenções';s.append(FIELDS)
        for r in self.store.orders():
            values=[]
            for c in FIELDS:
                v=r.get(c,'');values.append("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
            s.append(values)
        s.freeze_panes='A2';s.auto_filter.ref=s.dimensions
        for c in s[1]:c.fill=PatternFill('solid',fgColor='10283F');c.font=Font(color='FFFFFF',bold=True)
        for c in s.columns:s.column_dimensions[c[0].column_letter].width=23
        w.save(p);messagebox.showinfo('Exportação','Excel salvo.')
    def template(self):
        p=filedialog.asksaveasfilename(initialfile='modelo_manutencao.csv',defaultextension='.csv')
        if p:export_csv(p,[{'os_id':'EXEMPLO-001','frota':'12345','unidade':'ARA','evento':'ITR','parada':'14/11/2026 07:30','local_manutencao':'Oficina Aracruz'}],FIELDS)
    def report(self):
        rows=[r for r in self.store.orders() if is_open(r)];p=filedialog.asksaveasfilename(initialfile='Oficina_10Sul.html',defaultextension='.html')
        if not p:return
        cols=['frota','os_id','evento','parada','local_manutencao','previsao','aguardando_peca'];esc=lambda v:html.escape(str(v or ''))
        body=''.join('<tr>'+''.join('<td>'+esc(shown(r.get(c)) if c in DATE_FIELDS else r.get(c))+'</td>' for c in cols)+'</tr>' for r in rows)
        doc='<html lang="pt-BR"><meta charset="utf-8"><title>Oficina 10 Sul</title><style>body{font:14px Arial;color:#17334a;margin:30px}h1{color:#087f8c}table{border-collapse:collapse;width:100%}th,td{padding:9px;border:1px solid #ddd;text-align:left}th{background:#edf2f7}@media print{button{display:none}}</style><h1>10 Sul • Oficina em manutenção</h1><p>Emitido em '+esc(shown(now()))+' • '+str(len(rows))+' OS abertas</p><button onclick="window.print()">Imprimir / salvar PDF</button><table><tr>'+''.join('<th>'+esc(LABELS[c])+'</th>' for c in cols)+'</tr>'+body+'</table><p>Desenvolvido por Evandro Junior</p></html>'
        Path(p).write_text(doc,encoding='utf-8');self.open_file(p)
    def backup(self):
        p=filedialog.asksaveasfilename(initialfile='10Sul_Manutencao_'+now().strftime('%Y%m%d_%H%M')+'.zip',defaultextension='.zip')
        if p:self.store.backup(p);messagebox.showinfo('Backup','Backup completo salvo.')
    def restore(self):
        p=filedialog.askopenfilename(filetypes=[('Backup 10 Sul','*.zip')])
        if p and messagebox.askyesno('Restaurar','Substituir os dados locais por este backup? Uma cópia da base atual será guardada automaticamente. Será necessário entrar novamente.'):
            self.store.restore(p);self.store.user='';self.current='';self.login()

def main():
    root=tk.Tk();store=Store();App(root,store)
    def close():store.close();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.mainloop()
if __name__=='__main__':main()
