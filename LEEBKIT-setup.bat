@echo off
setlocal enabledelayedexpansion
rem LEEBKIT by LEEBLAAB - one-click Windows installer.
rem Checks prerequisites, downloads portable ffmpeg if missing, then launches the app.
cd /d "%~dp0"

echo ============================================
echo  LEEBKIT setup  ^(by LEEBLAAB^)
echo ============================================
echo.

rem ---------- 1) python on PATH (venv is built by start.bat) ----------
set "PYVER="
for /f "tokens=2 delims= " %%v in ('python --version 2^>nul') do set "PYVER=%%v"
if not defined PYVER (
  echo [LEEBKIT] ERROR: Python was not found on PATH.
  echo           Install Python 3.11+ from https://www.python.org/downloads/
  echo           and CHECK the "Add python.exe to PATH" box, then re-run this file.
  pause & exit /b 1
)
echo [LEEBKIT] found python %PYVER%

rem ---------- 2) ffmpeg (needed for video encode; scoop copy is fine) ----------
where ffmpeg >nul 2>nul
if %errorlevel%==0 (
  echo [LEEBKIT] ffmpeg found on PATH.
) else (
  if exist "tools\ffmpeg\bin\ffmpeg.exe" (
    echo [LEEBKIT] ffmpeg found in tools\ffmpeg.
  ) else (
    echo [LEEBKIT] ffmpeg not found - downloading portable build to tools\ffmpeg ^(about 80 MB, internet needed once^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; New-Item -ItemType Directory -Force -Path tools | Out-Null; Invoke-WebRequest -Uri 'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip' -OutFile 'tools\ffmpeg.zip'; if ($LASTEXITCODE -ne 0) { exit 1 }; Expand-Archive -Force 'tools\ffmpeg.zip' 'tools\_ffx'; $d=Get-ChildItem 'tools\_ffx' -Directory | Select-Object -First 1; if (Test-Path 'tools\ffmpeg') { Remove-Item -Recurse -Force 'tools\ffmpeg' }; Move-Item $d.FullName 'tools\ffmpeg'; Remove-Item -Recurse -Force 'tools\_ffx','tools\ffmpeg.zip'" 
    if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
      echo [LEEBKIT] WARN: automatic ffmpeg download failed. You can still install it yourself
      echo           ^(scoop install ffmpeg, or any ffmpeg on PATH^) before rendering video.
    ) else (
      echo [LEEBKIT] ffmpeg ready in tools\ffmpeg.
    )
  )
)

rem ---------- 3) launch (start.bat builds the venv + deps on first run) ----------
echo.
echo [LEEBKIT] starting LEEBKIT (first run installs python deps, takes a minute)...
call start.bat
