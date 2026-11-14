@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto erro
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto erro
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto erro
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name 10SulManutencao --hidden-import openpyxl app.py
if errorlevel 1 goto erro
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
 "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer.iss
 if errorlevel 1 goto erro
 echo Instalador criado na pasta output.
) else (
 echo Executavel criado em dist\10SulManutencao.exe.
 echo Para gerar o instalador, instale Inno Setup 6 e compile installer.iss.
)
pause
exit /b 0
:erro
echo Falha na compilacao. Confira o erro acima.
pause
exit /b 1
