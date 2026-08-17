@echo off
setlocal
title Kawkabat - CHECK
echo.
echo ================================================================
echo  KAWKABAT SYSTEM CHECK
echo ================================================================
echo.
echo [FILES]
if exist "%~dp0public\kawkabat-v481-amibroker-local.html" (echo PASS - outer HTML) else (echo FAIL - outer HTML)
if exist "%~dp0public\wheel.html" (echo PASS - wheel.html) else (echo FAIL - wheel.html)
if exist "%~dp0tools\kawkabat_ami_server.py" (echo PASS - local server) else (echo FAIL - local server)
if exist "%~dp0AmiBroker\KAWKABAT_FAST_RT_RUNTIME_PATH_100MS.afl" (echo PASS - AmiBroker AFL) else (echo FAIL - AmiBroker AFL)
echo.
echo [PYTHON]
py -3.12 --version
echo.
echo [SERVICE]
powershell.exe -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 2; $r | ConvertTo-Json -Depth 4}catch{Write-Host 'OFFLINE - run START_KAWKABAT_AMIBROKER.cmd' -ForegroundColor Yellow}"
echo.
echo [QUOTE]
powershell.exe -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/quote' -TimeoutSec 2; $r | ConvertTo-Json -Depth 4}catch{Write-Host 'No live quote yet. Keep AmiBroker open and apply the included AFL.' -ForegroundColor Yellow}"
echo.
pause
