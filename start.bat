@echo off
setlocal enabledelayedexpansion
rem LEEBKIT by LEEBLAAB - start the offline webUI (http://127.0.0.1:8735)
cd /d "%~dp0"

rem Pick a python: prefer a full install at C:\PythonXY over whatever PATH
rem happens to point at (PATH python was 3.11 while the working venv was 3.14,
rem which triggered the self-heal below and wiped a good .venv offline).
set "PY=python"
if exist C:\Python314\python.exe set "PY=C:\Python314\python.exe"
set "PYVER="
for /f "tokens=2 delims= " %%v in ('"%PY%" --version 2^>nul') do set "PYVER=%%v"
echo [LEEBKIT] python: %PY% (%PYVER%)

rem rebuild .venv automatically if it was created by a different python version
if exist .venv\Scripts\python.exe (
  set "VVER="
  for /f "tokens=2 delims= " %%v in ('.venv\Scripts\python.exe --version 2^>nul') do set "VVER=%%v"
  if not "!VVER!"=="!PYVER!" (
    echo [LEEBKIT] venv built with python !VVER!, using %PYVER% - recreating...
    rmdir /s /q .venv 2>nul
  )
)

if not exist .venv\Scripts\python.exe (
  echo [LEEBKIT] first run: creating venv + installing deps ^(takes a minute^)...
  "%PY%" -m venv .venv || (echo [LEEBKIT] ERROR: could not create venv - is python installed? & pause & exit /b 1)
  call .venv\Scripts\python.exe -m pip install -q --upgrade pip
  call .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (echo [LEEBKIT] ERROR: dependency install failed ^(offline?^). & pause & exit /b 1)
)

rem NEVER delete a working venv over a missing download: only rebuild when the
rem server actually fails to boot, and keep the old one as .venv.bak.
.venv\Scripts\python.exe -c "import fastapi" 2>nul && goto :boot
echo [LEEBKIT] deps missing - trying reinstall...
call .venv\Scripts\python.exe -m pip install -q -r requirements.txt
.venv\Scripts\python.exe -c "import fastapi" 2>nul && goto :boot
if not exist .venv\Scripts\python.exe (echo [LEEBKIT] ERROR: venv gone and reinstall failed. & pause & exit /b 1)
echo [LEEBKIT] deps still broken - rebuilding venv once ^(old one kept as .venv.bak^)...
ren .venv .venv.bak 2>nul
"%PY%" -m venv .venv || (echo [LEEBKIT] ERROR: could not create venv. & pause & exit /b 1)
call .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (echo [LEEBKIT] ERROR: dependency install failed ^(offline?^). Old venv is in .venv.bak. & pause & exit /b 1)
:boot

rem live-test bug #2: the browser used to open BEFORE uvicorn started, so it
rem showed connection refused. Server now launches in its own window; the
rem browser opens only once the port answers (pure-cmd retry loop).
echo [LEEBKIT] starting at http://127.0.0.1:8735  ^(close the 'LEEBKIT server' window to stop^)
start "LEEBKIT server" /min .venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8735
set "_tries=0"
:waitport
timeout /t 1 /nobreak >nul
netstat -ano | findstr /r /c:":8735 .*LISTENING" >nul && goto :portup
set /a _tries+=1
if %_tries% geq 30 (
  echo [LEEBKIT] server did not come up within ~30s - check the 'LEEBKIT server' window for errors.
  pause & exit /b 1
)
goto :waitport
:portup
start "" http://127.0.0.1:8735
echo [LEEBKIT] browser opened after %_tries%s - server runs in the 'LEEBKIT server' window (close it to stop).
pause
