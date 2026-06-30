@echo off
setlocal
cd /d "%~dp0"

if exist "stop_8765_port.bat" (
    call "stop_8765_port.bat" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -c "import flask, openpyxl, requests, pandas, numpy, matplotlib, PIL, FinMind" >nul 2>&1
if errorlevel 1 (
    echo [StockControlPanel] First-time setup: installing required packages...
    python -m pip install -r requirements.txt
)

python launch_stock_control_panel.py
if errorlevel 1 (
    echo [StockControlPanel] 啟動失敗，請查看 logs\stock_control_panel.log
    pause
    exit /b 1
)

exit /b 0
