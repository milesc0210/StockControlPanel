@echo off
setlocal
cd /d "%~dp0"

if exist "stop_8765_port.bat" call "stop_8765_port.bat" >nul 2>&1
ping 127.0.0.1 -n 2 >nul

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" goto fail_venv

call ".venv\Scripts\activate.bat"
python -c "import flask, openpyxl, requests, pandas, numpy, matplotlib, PIL, FinMind" >nul 2>&1
if errorlevel 1 python -m pip install -r requirements.txt
if errorlevel 1 goto fail_requirements

python launch_stock_control_panel.py
if errorlevel 1 goto fail_launch

exit /b 0

:fail_venv
echo [StockControlPanel] Failed to create or find .venv\Scripts\python.exe
pause
exit /b 1

:fail_requirements
echo [StockControlPanel] Failed to install requirements.
pause
exit /b 1

:fail_launch
echo [StockControlPanel] Launch failed. Check logs\stock_control_panel.log
pause
exit /b 1
