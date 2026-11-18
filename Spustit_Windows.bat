@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if not errorlevel 1 (
    py -3 start.py %*
) else (
    python start.py %*
)
if errorlevel 1 (
    echo.
    echo Spustenie zlyhalo. Skontroluj, ci je nainstalovany Python 3.11 alebo novsi.
    pause
)
