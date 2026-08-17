@echo off
setlocal
title Kawkabat AmiBroker - STOP
echo.
echo Stopping Kawkabat local Python service...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*kawkabat_ami_server.py*' }; if($p){$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host 'PASS - Kawkabat server stopped.' -ForegroundColor Green}else{Write-Host 'Kawkabat server is not running.' -ForegroundColor Yellow}"
timeout /t 1 /nobreak >nul
exit /b 0
