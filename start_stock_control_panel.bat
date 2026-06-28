@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -c "import flask, openpyxl, requests, pandas, numpy, matplotlib, PIL, FinMind" >nul 2>&1
if errorlevel 1 (
    echo [StockControlPanel] First-time setup: installing required packages...
    python -m pip install -r requirements.txt
)

start "" http://127.0.0.1:8765
python app.py
