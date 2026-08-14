#requires -Version 5.1
<#
Registers a per-user scheduled task ("KawkabatMT5Bridge") that starts the MT5
bridge at logon, hidden, without elevating privileges, and keeps it running.

The task's action runs run-bridge-supervised.ps1 (not start-mt5-bridge.bat
directly) — that script loops, restarting the bridge whenever it exits, for
any reason. Task Scheduler's own RestartCount/RestartInterval settings are
kept as a second safety net, but are not the primary restart mechanism: a
forcefully-killed python.exe was measured to report LastTaskResult=0
("success") to Task Scheduler, which the built-in policy only acts on for a
non-zero result — so relying on it alone left the bridge dead with no restart.
#>
$ErrorActionPreference = 'Stop'

$TaskName        = 'KawkabatMT5Bridge'
$ScriptDir       = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath         = Join-Path $ScriptDir 'start-mt5-bridge.bat'
$SupervisorPath  = Join-Path $ScriptDir 'run-bridge-supervised.ps1'

if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-Host "[FATAL] لم أجد start-mt5-bridge.bat في: $ScriptDir"
    exit 1
}
if (-not (Test-Path -LiteralPath $SupervisorPath)) {
    Write-Host "[FATAL] لم أجد run-bridge-supervised.ps1 في: $ScriptDir"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] المهمة '$TaskName' موجودة بالفعل — لن أنشئها من جديد."
    Write-Host "       للتحقق: Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "       لإعادة التثبيت من الصفر: شغّل uninstall-autostart.ps1 أولاً."
    exit 0
}

$psArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SupervisorPath`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $psArgs -WorkingDirectory $ScriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# LogonType S4U: يعمل بحساب المستخدم الحالي بلا كلمة مرور مخزَّنة وبلا نافذة
# مرئية (لا يُربط بمحطة نوافذ تفاعلية). RunLevel Limited: صلاحية عادية غير
# مرفوعة، حتى لو كان المستخدم الحالي عضواً في مجموعة المسؤولين.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description 'يشغّل جسر MT5 المحلي (bridge/mt5_bridge.py) تلقائياً عند تسجيل الدخول عبر run-bridge-supervised.ps1، بصلاحية المستخدم العادية بلا رفع صلاحيات. الحلقة المشرفة تعيد تشغيل الجسر خلال ثوانٍ من أي توقف، بصرف النظر عن كود الخروج.' `
    | Out-Null

Write-Host "[OK] أُنشئت المهمة '$TaskName'."
Write-Host "     تحقّق: Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName,State"
Write-Host "     تشغيل فوري بلا انتظار تسجيل الدخول: Start-ScheduledTask -TaskName '$TaskName'"
