@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYEXE=.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH. Install Python 3.10+ and try again.
        pause
        exit /b 1
    )
    set "PYEXE=python"
)

echo Starting MT5 bridge on 127.0.0.1:8771 ...
"%PYEXE%" mt5_bridge.py
if errorlevel 1 (
    echo.
    echo [ERROR] Bridge exited with an error. See logs\ for details.
    pause
)
endlocal
