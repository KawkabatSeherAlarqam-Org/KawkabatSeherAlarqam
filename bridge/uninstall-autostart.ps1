#requires -Version 5.1
<#
Removes the "KawkabatMT5Bridge" scheduled task created by install-autostart.ps1.
Does not stop an already-running bridge process — only removes the autostart
registration.
#>
$ErrorActionPreference = 'Stop'

$TaskName = 'KawkabatMT5Bridge'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "[INFO] لا توجد مهمة باسم '$TaskName' لإزالتها."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] أُزيلت المهمة '$TaskName'."
Write-Host "     لا يزال أي جسر يعمل حالياً يعمل بلا تغيير — هذا يزيل التشغيل التلقائي فقط."
