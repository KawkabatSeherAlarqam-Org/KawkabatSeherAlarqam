#requires -Version 5.1
<#
Removes the "KawkabatMT5Bridge" scheduled task created by install-autostart.ps1.

By default, does not stop an already-running bridge process -- only removes
the autostart registration (useful during dev: keep testing the currently-
running instance after just pulling the autostart trigger). Pass
-StopRunning to also stop the running task instance and kill any lingering
supervisor/bridge processes -- the installer always uses this, since it is
about to delete the files those processes depend on.
#>
param(
    [switch]$StopRunning
)
$ErrorActionPreference = 'Stop'

$TaskName = 'KawkabatMT5Bridge'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "[INFO] لا توجد مهمة باسم '$TaskName' لإزالتها."
    if ($StopRunning) {
        Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like '*run-bridge-supervised.ps1*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Get-Process -Name KawkabatBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

if ($StopRunning) {
    # Unregister-ScheduledTask only removes the task DEFINITION -- an
    # already-running instance (the supervisor's own powershell.exe, and the
    # KawkabatBridge.exe it launched) keeps running from memory regardless,
    # since it no longer depends on the registration once started. Measured
    # live: this left a zombie supervisor loop retrying against deleted files
    # after an installer uninstall, holding a lock on its own script folder.
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*run-bridge-supervised.ps1*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name KawkabatBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] أُزيلت المهمة '$TaskName'."
if ($StopRunning) {
    Write-Host "     أُوقف أي جسر كان يعمل حالياً أيضاً (تمرير -StopRunning)."
} else {
    Write-Host "     لا يزال أي جسر يعمل حالياً يعمل بلا تغيير — هذا يزيل التشغيل التلقائي فقط. مرّر -StopRunning لإيقافه أيضاً."
}
