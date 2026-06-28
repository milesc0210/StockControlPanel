@echo off
setlocal
set PORT=8765
set PID=

echo Checking port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    set PID=%%a
    goto :found
)

echo No LISTENING process found on port %PORT%.
goto :end

:found
echo Found PID %PID% on port %PORT%.
taskkill /F /PID %PID%
if errorlevel 1 (
    echo Failed to stop PID %PID%.
    exit /b 1
) else (
    echo Port %PORT% process stopped successfully.
)

:end
endlocal
