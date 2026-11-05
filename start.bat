@echo off
rem REELKIT by LEEBLAAB - start the offline webUI (http://127.0.0.1:8735)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo [REELKIT] first run: creating venv + installing deps...
  python -m venv .venv && .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8735
