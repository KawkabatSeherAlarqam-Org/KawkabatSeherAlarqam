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

$wasReplaced = $false
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    # Compare the CURRENTLY REGISTERED -ExePath against what we'd register
    # now, instead of just "task exists, skip" -- a reinstall/upgrade with a
    # different exe location (dev path vs. installed path, or an old install
    # dir) used to leave the OLD path registered silently, so the task kept
    # launching stale code while the user believed the new install was live.
    $currentArgs = $existing.Actions[0].Arguments
    $currentExePath = $null
    if ($currentArgs -match '-ExePath\s+"([^"]*)"') {
        try { $currentExePath = [System.IO.Path]::GetFullPath($Matches[1]) } catch { $currentExePath = $Matches[1] }
    }

    if ($currentExePath -and ($currentExePath -eq $ExePath)) {
        Write-Host "[INFO] المهمة '$TaskName' موجودة بالفعل وتشير لنفس المسار الصحيح — لا حاجة لإعادة التسجيل."
        Write-Host "       exe: $ExePath"
        exit 0
    }

    Write-Host "[INFO] المهمة '$TaskName' موجودة لكنها تشير لمسار مختلف عمّا طُلب الآن:"
    Write-Host "       المسجَّل حالياً: $(if ($currentExePath) { $currentExePath } else { '(تعذّر استخراج مسار من تسجيلها الحالي)' })"
    Write-Host "       المطلوب الآن:  $ExePath"
    Write-Host "       سأوقفها وأُلغي تسجيلها وأُعيد إنشاءها بالمسار الصحيح..."

    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    # Belt-and-suspenders: Stop-ScheduledTask relies on Task Scheduler's own
    # job-object cleanup to also kill the child KawkabatBridge.exe it
    # launched -- catch anything that survives that (e.g. a bridge started
    # some other way, not via this task).
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*run-bridge-supervised.ps1*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name KawkabatBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] أُلغي التسجيل القديم — سأتابع لإنشاء تسجيل جديد بالمسار الصحيح."
    $wasReplaced = $true
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

if ($wasReplaced) {
    Write-Host "[OK] أُعيد تسجيل المهمة '$TaskName' بالمسار الصحيح (كانت تشير لمسار مختلف)."
} else {
    Write-Host "[OK] أُنشئت المهمة '$TaskName'."
}
Write-Host "     exe: $ExePath"
Write-Host "     تحقّق: Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName,State"
Write-Host "     تحقّق أن المهمة تشير للـexe: (Get-ScheduledTask -TaskName '$TaskName').Actions"
Write-Host "     تشغيل فوري بلا انتظار تسجيل الدخول: Start-ScheduledTask -TaskName '$TaskName'"
