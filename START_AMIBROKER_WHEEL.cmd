@echo off
setlocal
title Kawkabat XAUUSD AmiBroker AFL
set "PROJECT=C:\KawkabatSeherAlarqam"
set "PORT=8080"
set "SCRIPT=%PROJECT%\tools\amibroker-local-server.ps1"
if not exist "%PROJECT%\runtime" mkdir "%PROJECT%\runtime"
echo Starting Kawkabat AFL service on 127.0.0.1:%PORT%...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -ProjectRoot "%PROJECT%" -Port %PORT% -Symbol XAUUSD
if errorlevel 1 (
 echo START FAILED. Verify port %PORT% is free.
 pause
)

