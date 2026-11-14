"""Verifica WebView2 como janela filha de um painel Tk, sem acessar produção."""
import sys,os,tempfile,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if '--child' in sys.argv:
 import webview,threading,ctypes
 from modules import MODULES,launch_module
 MODULES['Controle de veículos']['url']='data:text/html,<html><body><h1 id="ok">Modulo incorporado 10 Sul</h1></body></html>'
 os.environ['SUL_MANUTENCAO_DATA']=sys.argv[3]
 launch_module('Controle de veículos',int(sys.argv[2]))
else:
 import tkinter as tk
 import ctypes
 from ctypes import wintypes
 ctypes.windll.user32.SetProcessDPIAware()
 root=tk.Tk();root.geometry('1000x720');host=tk.Frame(root,bg='white');host.pack(fill='both',expand=True);root.update()
 with tempfile.TemporaryDirectory() as tmp:
  p=subprocess.Popen([sys.executable,__file__,'--child',str(host.winfo_id()),tmp]);deadline=time.time()+45;children=[]
  callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
  @callback_type
  def enum(hwnd,param):children.append(hwnd);return True
  while time.time()<deadline:
   root.update();children.clear();ctypes.windll.user32.EnumChildWindows(host.winfo_id(),enum,0)
   if children:break
   if p.poll() is not None:raise RuntimeError('WebView encerrou antes de incorporar')
   time.sleep(.1)
  if not children:
   p.terminate();raise RuntimeError('Nenhuma janela foi incorporada ao painel')
  print('OK WebView2 incorporado ao painel Tk:',len(children),'janela(s)')
  from PIL import ImageGrab
  Path('previews').mkdir(exist_ok=True);ImageGrab.grab().save('previews/embedded_windows.png')
  root.destroy()
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)
