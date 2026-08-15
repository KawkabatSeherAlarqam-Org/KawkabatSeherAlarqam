#requires -Version 5.1
<#
Registers a per-user scheduled task ("KawkabatMT5Bridge") that starts the MT5
bridge at logon, hidden, without elevating privileges, and keeps it running.

The task's action runs run-bridge-supervised.ps1 (not KawkabatBridge.exe
directly) — that script loops, restarting the bridge whenever it exits, for
any reason. Task Scheduler's own RestartCount/RestartInterval settings are
kept as a second safety net, but are not the primary restart mechanism: a
forcefully-killed process was measured to report LastTaskResult=0 ("success")
to Task Scheduler, which the built-in policy only acts on for a non-zero
result — so relying on it alone left the bridge dead with no restart.
#>
param(
    # Path to KawkabatBridge.exe, resolved once here and passed explicitly to
    # run-bridge-supervised.ps1 as -ExePath so the running task always uses
    # exactly what was validated at install time. Falls back to
    # $env:KAWKABAT_BRIDGE_EXE, then to the dev-build-tree default below.
    [string]$ExePath
)
$ErrorActionPreference = 'Stop'

$TaskName        = 'KawkabatMT5Bridge'
$ScriptDir       = Split-Path -Parent $MyInvocation.MyCommand.Path
$SupervisorPath  = Join-Path $ScriptDir 'run-bridge-supervised.ps1'

if (-not $ExePath) {
    if ($env:KAWKABAT_BRIDGE_EXE) {
        $ExePath = $env:KAWKABAT_BRIDGE_EXE
    } else {
        # NOTE: this default becomes
        # %LOCALAPPDATA%\Kawkabat\KawkabatBridge\KawkabatBridge.exe once the
        # Phase 2 installer lands (it copies the whole KawkabatBridge\ folder
        # there) — bridge\build\dist\ is a dev-build-tree path only. The exe
        # is an --onedir build: it needs its sibling _internal\ folder, so
        # this path must stay inside the KawkabatBridge\ folder, not point
        # directly at a standalone .exe.
        $ExePath = Join-Path $ScriptDir 'build\dist\KawkabatBridge\KawkabatBridge.exe'
    }
}
$ExePath = [System.IO.Path]::GetFullPath($ExePath)

if (-not (Test-Path -LiteralPath $SupervisorPath)) {
    Write-Host "[FATAL] لم أجد run-bridge-supervised.ps1 في: $ScriptDir"
    exit 1
}
if (-not (Test-Path -LiteralPath $ExePath)) {
    # No silent fallback to python/mt5_bridge.py — registering a task that
    # points at a non-existent exe would just reproduce the same failure on
    # every logon instead of failing loudly once, right here, at install time.
    Write-Host "[FATAL] لم أجد الملف التنفيذي: $ExePath"
    Write-Host "        ابنِه أولاً: powershell -ExecutionPolicy Bypass -File `"$ScriptDir\build\build.ps1`""
    Write-Host "        أو اضبط KAWKABAT_BRIDGE_EXE أو مرّر -ExePath إلى مسار صحيح."
    exit 1
}
$InternalDir = Join-Path (Split-Path -Parent $ExePath) '_internal'
if (-not (Test-Path -LiteralPath $InternalDir)) {
    # This build is --onedir: the exe alone will not run without its sibling
    # _internal\ folder (all its DLLs/dependencies) sitting right next to it —
    # a common mistake when copying just the .exe instead of the whole folder.
    Write-Host "[FATAL] وُجد $ExePath لكن مجلد _internal المجاور له غير موجود: $InternalDir"
    Write-Host "        هذا بناء --onedir — انسخ مجلد KawkabatBridge\ كاملاً، لا الملف التنفيذي وحده."
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] المهمة '$TaskName' موجودة بالفعل — لن أنشئها من جديد."
    Write-Host "       للتحقق: Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "       لإعادة التثبيت من الصفر: شغّل uninstall-autostart.ps1 أولاً."
    exit 0
}

$psArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SupervisorPath`" -ExePath `"$ExePath`""
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
    -Description "يشغّل جسر MT5 المحلي (KawkabatBridge.exe عند $ExePath) تلقائياً عند تسجيل الدخول عبر run-bridge-supervised.ps1، بصلاحية المستخدم العادية بلا رفع صلاحيات. الحلقة المشرفة تعيد تشغيل الجسر خلال ثوانٍ من أي توقف، بصرف النظر عن كود الخروج." `
    | Out-Null

Write-Host "[OK] أُنشئت المهمة '$TaskName'."
Write-Host "     exe: $ExePath"
Write-Host "     تحقّق: Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName,State"
Write-Host "     تحقّق أن المهمة تشير للـexe: (Get-ScheduledTask -TaskName '$TaskName').Actions"
Write-Host "     تشغيل فوري بلا انتظار تسجيل الدخول: Start-ScheduledTask -TaskName '$TaskName'"
