@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -Command "try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 1; if($r.ok){exit 0}else{exit 1}}catch{exit 1}"
if errorlevel 1 (
  call "%~dp0START_KAWKABAT_AMIBROKER.cmd"
  exit /b %errorlevel%
)
start "" "http://127.0.0.1:8080/kawkabat-v481-amibroker-local.html?v6=1"
exit /b 0
