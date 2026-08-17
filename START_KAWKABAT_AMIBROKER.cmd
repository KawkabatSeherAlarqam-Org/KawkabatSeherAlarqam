@echo off
setlocal EnableExtensions
title Kawkabat AmiBroker - START
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PAGE=kawkabat-v481-amibroker-local.html"
set "URL=http://127.0.0.1:8080/%PAGE%?v6=1"

echo.
echo ================================================================
echo   KAWKABAT / AMIBROKER - START COMPLETE SYSTEM
echo ================================================================
echo.

if not exist "%ROOT%public\%PAGE%" (
  echo ERROR: Missing:
  echo %ROOT%public\%PAGE%
  pause
  exit /b 2
)

if not exist "%ROOT%public\wheel.html" (
  echo ERROR: Missing:
  echo %ROOT%public\wheel.html
  pause
  exit /b 3
)

if not exist "%ROOT%tools\kawkabat_ami_server.py" (
  echo ERROR: Missing local server.
  pause
  exit /b 4
)

py -3.12 -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 was not found through the Windows py launcher.
  echo Install/repair Python 3.12 or verify: py -3.12 --version
  pause
  exit /b 5
)

echo [1/4] Checking Kawkabat service on port 8080...
powershell.exe -NoProfile -Command ^
  "try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 1; if($r.ok -and $r.service -eq 'Kawkabat AmiBroker Local'){exit 0}else{exit 1}}catch{exit 1}"

if errorlevel 1 (
  echo [2/4] Service is not active. Checking whether port 8080 is free...
  powershell.exe -NoProfile -Command ^
    "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8080);$c.Close();exit 1}catch{exit 0}"
  if errorlevel 1 (
    echo.
    echo ERROR: Port 8080 is occupied by another service.
    echo Run STOP_KAWKABAT_SERVER.cmd first if it is an old Kawkabat/Python server.
    echo Then run this START file again.
    echo.
    pause
    exit /b 6
  )

  echo [2/4] Starting unified Kawkabat service...
  start "Kawkabat AmiBroker Server 8080" /min py -3.12 "%ROOT%tools\kawkabat_ami_server.py"

  echo [3/4] Waiting for service...
  powershell.exe -NoProfile -Command ^
    "$ok=$false; 1..30 | %% { try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 1; if($r.ok){$ok=$true;break}}catch{}; Start-Sleep -Milliseconds 200 }; if($ok){exit 0}else{exit 1}"
  if errorlevel 1 (
    echo ERROR: Kawkabat service did not start.
    pause
    exit /b 7
  )
) else (
  echo [2/4] Kawkabat service is already running.
)

echo [4/4] Opening wheel...
start "" "%URL%"

echo.
echo READY
echo Wheel : %URL%
echo Quote : http://127.0.0.1:8080/api/quote
echo Health: http://127.0.0.1:8080/health
echo.
echo AmiBroker AFL:
echo %ROOT%AmiBroker\KAWKABAT_FAST_RT_RUNTIME_PATH_100MS.afl
echo.
timeout /t 2 /nobreak >nul
exit /b 0
