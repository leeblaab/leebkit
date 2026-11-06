@echo off
setlocal enabledelayedexpansion
rem LEEBKIT by LEEBLAAB - start the offline webUI (http://127.0.0.1:8735)
cd /d "%~dp0"

set "PYVER="
for /f "tokens=2 delims= " %%v in ('python --version 2^>nul') do set "PYVER=%%v"
echo [LEEBKIT] system python: %PYVER%

rem rebuild .venv automatically if it was created by a different python version
if exist .venv\Scripts\python.exe (
  set "VVER="
  for /f "tokens=2 delims= " %%v in ('.venv\Scripts\python.exe --version 2^>nul') do set "VVER=%%v"
  if not "!VVER!"=="!PYVER!" (
    echo [LEEBKIT] venv built with python !VVER!, system is %PYVER% - recreating...
    rmdir /s /q .venv 2>nul
  )
)

if not exist .venv\Scripts\python.exe (
  echo [LEEBKIT] first run: creating venv + installing deps ^(takes a minute^)...
  python -m venv .venv || (echo [LEEBKIT] ERROR: could not create venv - is python installed and on PATH? & pause & exit /b 1)
  call .venv\Scripts\python.exe -m pip install -q --upgrade pip
  call .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (echo [LEEBKIT] ERROR: dependency install failed. & pause & exit /b 1)
)

.venv\Scripts\python.exe -c "import fastapi" 2>nul || (echo [LEEBKIT] deps missing - reinstalling... & call .venv\Scripts\python.exe -m pip install -q -r requirements.txt)

echo [LEEBKIT] starting at http://127.0.0.1:8735  ^(close this window to stop^)
start "" http://127.0.0.1:8735
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8735
echo.
echo [LEEBKIT] server stopped. If the port was busy, one is already running - open http://127.0.0.1:8735
pause
