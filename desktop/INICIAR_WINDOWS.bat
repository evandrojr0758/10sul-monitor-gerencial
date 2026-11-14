@echo off
setlocal
cd /d "%~dp0"
if exist "dist\10SulManutencao.exe" (
 start "" "dist\10SulManutencao.exe"
 exit /b
)
py -3 -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
 echo Instale Python 3.12 e as dependencias de requirements.txt ou use o instalador .exe.
 pause
 exit /b 1
)
py -3 app.py
if errorlevel 1 pause
