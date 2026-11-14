"""Aplicativos originais da Central 10 Sul, executados no navegador incorporado."""
MODULES={
 'Controle de veículos':{'subtitle':'Cadastro, saída/retorno, revisões, consumo e ranking mensal','url':'https://controle-veiculos-jpnsn36kukknr96dv9noma.streamlit.app/?view=admin&tab=veiculos&unidade=TODAS'},
 'Financeiro 10 Sul':{'subtitle':'Receitas, despesas, documentos, plano de contas e conciliação','url':'https://financeiro-10sul.peachycrown16.chatgpt.site/'},
 'Estoque do socorro':{'subtitle':'Movimentações, inventário e gestão do estoque por unidade','url':'https://10sul-estoque-cocb.streamlit.app/?pagina=painel'},
 'Gestão do socorro':{'subtitle':'Atendimentos, tempos, ranking e confronto com ASN/ECM','url':'https://socorro-atendimentos-10sul.peachycrown16.chatgpt.site/gestao.html'},
 'Atendimento do socorrista':{'subtitle':'Lançamento de atendimento e evidências; conserva a função offline do app original','url':'https://socorro-atendimentos-10sul.peachycrown16.chatgpt.site/atendimento.html'},
 'Estoque de pneus':{'subtitle':'Pneus novos, reformados, APV, movimentos e relatórios','url':'https://estoque-pneus-10sul.peachycrown16.chatgpt.site/'},
 'Propostas comerciais':{'subtitle':'Propostas, clientes, validação e recebimentos','url':'https://financeiro-10sul.peachycrown16.chatgpt.site/propostas'},
 'Solicitações de peças PCM':{'subtitle':'Importação, conferência e consulta de solicitações','url':'https://central-10sul.peachycrown16.chatgpt.site/solicitacoes-pcm.html'},
 'Projeto Lean':{'subtitle':'Estoque, composição e fabricação','url':'https://central-10sul.peachycrown16.chatgpt.site/projeto-lean.html'},
}

def launch_module(name,parent_hwnd=None):
    """Processo WebView2 isolado: nenhuma ponte Python exposta às páginas remotas."""
    import webview
    import ctypes,sys,time,threading,os
    from pathlib import Path
    from core import Store
    from webview.menu import Menu,MenuAction
    module=MODULES[name]
    data=Store();root=data.root;data.close()
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    window=webview.create_window('10 Sul • '+name,module['url'],width=1200,height=780,min_size=(800,550),confirm_close=False)
    def embed():
        if not parent_hwnd or sys.platform!='win32':return
        user=ctypes.windll.user32
        from ctypes import wintypes
        user.SetParent.argtypes=[wintypes.HWND,wintypes.HWND];user.SetParent.restype=wintypes.HWND
        user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        user.MoveWindow.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.BOOL]
        user.IsWindow.argtypes=[wintypes.HWND]
        # pywebview devolve um wrapper WinForms; Handle é o HWND real.
        hwnd=int(window.native.Handle.ToInt64())
        getlong=user.GetWindowLongW;getlong.argtypes=[wintypes.HWND,ctypes.c_int];getlong.restype=ctypes.c_long
        setlong=user.SetWindowLongW;setlong.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_long];setlong.restype=ctypes.c_long
        style=getlong(hwnd,-16);setlong(hwnd,-16,(style&~0x80CF0000)|0x40000000|0x10000000)
        user.SetParent(hwnd,int(parent_hwnd))
        if os.environ.get('SUL_EMBED_PROBE') and (module['url'].startswith('data:') or module['url'].startswith('http://127.0.0.1:')):
            value=window.evaluate_js("document.getElementById('ok')?.textContent")
            probe=Path(os.environ['SUL_EMBED_PROBE']);tmp=probe.with_suffix('.tmp');tmp.write_text(str(value),encoding='utf-8');tmp.replace(probe)
        while user.IsWindow(int(parent_hwnd)) and user.IsWindow(hwnd):
            rect=wintypes.RECT();user.GetClientRect(int(parent_hwnd),ctypes.byref(rect));user.MoveWindow(hwnd,0,0,rect.right,rect.bottom,True);time.sleep(.15)
        try:window.destroy()
        except Exception:pass
    if parent_hwnd:
        embedded_started=threading.Event()
        def loaded_embed():
            if not embedded_started.is_set():
                embedded_started.set();threading.Thread(target=embed,daemon=True).start()
        window.events.loaded+=loaded_embed
    def capture():
        import urllib.parse,hashlib,json
        from mirrors import FINANCE_CAPTURE,SOCORRO_CAPTURE,mirror_snapshot
        expected=urllib.parse.urlparse(module['url']).netloc
        while True:
            time.sleep(20)
            try:
                if urllib.parse.urlparse(window.get_current_url() or '').netloc!=expected:continue
                script=FINANCE_CAPTURE if 'financeiro-10sul' in expected else SOCORRO_CAPTURE if 'socorro-atendimentos' in expected else None
                if not script:return
                result=window.evaluate_js(script)
                if not isinstance(result,dict) or not result.get('ok'):continue
                db=Store();db.user='integração:'+name
                try:
                    for dataset in result['datasets']:
                        if dataset.get('append'):
                            exists=db.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(dataset['table'],)).fetchone()
                            if exists:
                                from history import qi
                                prior=[dict(r) for r in db.db.execute('SELECT * FROM '+qi(dataset['table']))]
                                index={r[dataset['keys'][0]]:r for r in prior};index.update({r[dataset['keys'][0]]:r for r in dataset['records']});dataset['records']=list(index.values())
                        mirror_snapshot(db,dataset['table'],name,module['url'],dataset['records'],dataset['keys'])
                finally:db.close()
            except Exception:
                if not webview.windows:return
            time.sleep(40)
    window.events.shown+=lambda:threading.Thread(target=capture,daemon=True).start()
    def reload_page():window.load_url(module['url'])
    try:
        webview.start(gui='edgechromium' if sys.platform=='win32' else None,private_mode=False,storage_path=str(root/'aplicativos'),menu=[Menu('Aplicativo',[MenuAction('Página inicial',reload_page),MenuAction('Atualizar',lambda:window.evaluate_js('location.reload()'))])])
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        r=tk.Tk();r.withdraw();messagebox.showerror('Aplicativo integrado','Não foi possível abrir o aplicativo. Confira se Microsoft Edge WebView2 Runtime está instalado.\n\n'+str(exc));r.destroy();raise
