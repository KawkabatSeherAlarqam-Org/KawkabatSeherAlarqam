#requires -Version 5.1
<#
Supervisor loop for the MT5 bridge — this is what the scheduled task actually
runs, not start-mt5-bridge.bat directly.

Why: Task Scheduler's own RestartCount/RestartInterval only fires when
LastTaskResult is non-zero. Tested empirically here: killing the bridge's
python.exe with Stop-Process -Force made Windows record LastTaskResult=0
("successful completion") — no restart ever fired, even after 60+ seconds.
This loop restarts the bridge unconditionally whenever it exits, for any
reason, instead of trusting that exit code.
#>
$ErrorActionPreference = 'Continue'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath   = Join-Path $ScriptDir 'start-mt5-bridge.bat'
$LogDir    = Join-Path $ScriptDir 'logs'
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$SupervisorLog = Join-Path $LogDir 'supervisor.log'

function Write-SupervisorLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`t$Message"
    Add-Content -LiteralPath $SupervisorLog -Value $line -Encoding UTF8
}

Write-SupervisorLog 'supervisor started'
while ($true) {
    Write-SupervisorLog 'starting bridge'
    $proc = Start-Process -FilePath $BatPath -WorkingDirectory $ScriptDir -PassThru -Wait -WindowStyle Hidden
    Write-SupervisorLog "bridge exited (code $($proc.ExitCode)) — restarting in 5s"
    Start-Sleep -Seconds 5
}
