@echo off
setlocal enabledelayedexpansion
rem LEEBKIT by LEEBLAAB - download piper TTS + voice models into vo/models/ (needs internet once)
cd /d "%~dp0"

set "PY311=[scrubbed]"
if not exist "%PY311%" (
  echo [LEEBKIT] ERROR: Python 3.11 not found at %PY311%
  echo           piper TTS needs it - install Python 3.11 or edit PY311 in this file.
  pause & exit /b 1
)

echo [LEEBKIT] installing piper-tts into Python 3.11...
call "%PY311%" -m pip install -q piper-tts || (echo [LEEBKIT] ERROR: pip install piper-tts failed. & pause & exit /b 1)

if not exist vo\models mkdir vo\models
pushd vo\models

rem --- voices already on this machine are kept; missing ones are fetched ---
call :get en_US-lessac-medium "en/en_US/medium"
call :get en_US-ryan-high     "en/en_US/high"
call :get en_US-kristin-medium "en/en_US/medium"
call :get en_GB-alba-medium    "en/en_GB/medium"

popd
echo [LEEBKIT] voices in vo\models:
dir /b vo\models\*.onnx 2>nul
echo [LEEBKIT] done - restart the app to see new voices in the Voice dropdown.
pause
exit /b 0

:get
set "V=%~1"
set "P=%~2"
if exist "%V%.onnx" if exist "%V%.onnx.json" (echo [LEEBKIT] %V% already present & exit /b 0)
echo [LEEBKIT] downloading %V% ...
curl -sSL --retry 3 --fail -o "%V%.onnx"      "https://huggingface.co/rhasspy/piper-voices/resolve/main/%P%/%V%.onnx"      || (echo [LEEBKIT] WARN: download failed for %V% \(no internet?\) & exit /b 0)
curl -sSL --retry 3 --fail -o "%V%.onnx.json" "https://huggingface.co/rhasspy/piper-voices/resolve/main/%P%/%V%.onnx.json" || (echo [LEEBKIT] WARN: config download failed for %V% & del /q "%V%.onnx" 2>nul & exit /b 0)
exit /b 0
