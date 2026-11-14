"""Verifica WebView2 como janela filha de um painel Tk, sem acessar produção."""
import sys,os,tempfile,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if '--child' in sys.argv:
 import webview,threading,ctypes
 from modules import MODULES,launch_module
 MODULES['Controle de veículos']['url']=os.environ['SUL_EMBED_TEST_URL']
 os.environ['SUL_MANUTENCAO_DATA']=sys.argv[3]
 os.environ['SUL_EMBED_PROBE']=str(Path(sys.argv[3])/'probe.txt')
 launch_module('Controle de veículos',int(sys.argv[2]))
else:
 import tkinter as tk
 import ctypes,threading
 from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
 from ctypes import wintypes
 ctypes.windll.user32.SetProcessDPIAware()
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   body=b'<html><body><h1 id="ok">Modulo incorporado 10 Sul</h1></body></html>';self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();root.geometry('1000x720');host=tk.Frame(root,bg='white');host.pack(fill='both',expand=True);root.update()
 with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
  env=os.environ.copy();env['SUL_EMBED_TEST_URL']='http://127.0.0.1:'+str(server.server_port)+'/';env['SUL_MANUTENCAO_DATA']=tmp;env['SUL_EMBED_PROBE']=str(Path(tmp)/'probe.txt')
  command=[os.environ['SUL_PACKAGED_EXE'],'--module-test','--parent',str(host.winfo_id())] if os.environ.get('SUL_PACKAGED_EXE') else [sys.executable,__file__,'--child',str(host.winfo_id()),tmp]
  p=subprocess.Popen(command,env=env);deadline=time.time()+60;children=[]
  callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
  @callback_type
  def enum(hwnd,param):children.append(hwnd);return True
  while time.time()<deadline:
   root.update();children.clear();ctypes.windll.user32.EnumChildWindows(host.winfo_id(),enum,0)
   if children and (Path(tmp)/'probe.txt').exists():
    if (Path(tmp)/'probe.txt').read_text(encoding='utf-8')!='Modulo incorporado 10 Sul':raise RuntimeError('Conteúdo incorporado inválido: '+repr((Path(tmp)/'probe.txt').read_text(encoding='utf-8')))
    break
   if p.poll() is not None:raise RuntimeError('WebView encerrou antes de incorporar')
   time.sleep(.1)
  if not children or not (Path(tmp)/'probe.txt').exists():
   p.terminate();raise RuntimeError('Nenhuma janela foi incorporada ao painel')
  print('OK WebView2 incorporado ao painel Tk:',len(children),'janela(s)')
  from PIL import ImageGrab
  Path('previews').mkdir(exist_ok=True);ImageGrab.grab().save('previews/embedded_windows.png')
  root.destroy()
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)
