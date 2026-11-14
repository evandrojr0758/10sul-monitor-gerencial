"""Conexões privadas ficam protegidas pelo usuário Windows (DPAPI)."""
import base64,ctypes,json,sqlite3,sys
from contextlib import closing
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

def protect(data,decrypt=False):
    if sys.platform!='win32':raise ValueError('Importe a conexão no aplicativo Windows.')
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    crypt=ctypes.windll.crypt32
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)];fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise ValueError('Não foi possível acessar a conexão protegida. Reimporte o arquivo de conexão neste usuário Windows.')
    try:return ctypes.string_at(out.data,out.size)
    finally:ctypes.windll.kernel32.LocalFree(out.data)

def save_stock_profile(store,profile):
    if not store.admin():raise ValueError('Apenas administrador pode configurar conexões.')
    u=urlparse(profile.get('endpoint',''))
    if u.scheme!='https' or u.hostname!='dezsul-estoque-api.peachycrown16.chatgpt.site' or u.path!='/api/estoque.json':raise ValueError('Arquivo de conexão não corresponde ao relatório de estoque 10 Sul.')
    headers=profile.get('headers',{})
    if set(headers)!={'X-API-Key','OAI-Sites-Authorization'} or any(not isinstance(v,str) or not v for v in headers.values()):raise ValueError('Conexão de leitura incompleta.')
    encrypted=base64.b64encode(protect(json.dumps(profile).encode())).decode()
    store.db.execute("INSERT INTO connection_profiles VALUES ('estoque',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(encrypted,));store.log('Conexão de leitura configurada','Estoque do socorro');store.db.commit()

def read_stock_profile(root):
    with closing(sqlite3.connect(Path(root)/'manutencao.sqlite3')) as db:
        row=db.execute("SELECT value FROM connection_profiles WHERE name='estoque'").fetchone()
    if not row:return None
    return json.loads(protect(base64.b64decode(row[0]),decrypt=True))
