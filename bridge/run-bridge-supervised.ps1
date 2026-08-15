#requires -Version 5.1
<#
Supervisor loop for the MT5 bridge — this is what the scheduled task actually
runs. Launches KawkabatBridge.exe (the packaged build) directly, not
python/mt5_bridge.py and not start-mt5-bridge.bat.

Why: Task Scheduler's own RestartCount/RestartInterval only fires when
LastTaskResult is non-zero. Tested empirically here: killing the bridge's
python.exe with Stop-Process -Force made Windows record LastTaskResult=0
("successful completion") — no restart ever fired, even after 60+ seconds.
This loop restarts the bridge unconditionally whenever it exits, for any
reason, instead of trusting that exit code.
#>
param(
    # Path to KawkabatBridge.exe (inside the KawkabatBridge\ folder produced
    # by an --onedir build — the exe needs its sibling _internal\ folder to
    # run, so this path must stay inside that folder). Falls back to
    # $env:KAWKABAT_BRIDGE_EXE, then to the dev-build-tree default below.
    # install-autostart.ps1 always passes this explicitly (the resolved path
    # it validated at install time), so the fallbacks here only matter when
    # this script is run standalone.
    [string]$ExePath
)
$ErrorActionPreference = 'Continue'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $ExePath) {
    if ($env:KAWKABAT_BRIDGE_EXE) {
        $ExePath = $env:KAWKABAT_BRIDGE_EXE
    } else {
        # NOTE: this default becomes
        # %LOCALAPPDATA%\Kawkabat\KawkabatBridge\KawkabatBridge.exe once the
        # Phase 2 installer lands (it copies the whole KawkabatBridge\ folder
        # there) — bridge\build\dist\ is a dev-build-tree path only.
        $ExePath = Join-Path $ScriptDir 'build\dist\KawkabatBridge\KawkabatBridge.exe'
    }
}

$LogDir    = Join-Path $ScriptDir 'logs'
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$SupervisorLog = Join-Path $LogDir 'supervisor.log'

function Write-SupervisorLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`t$Message"
    Add-Content -LiteralPath $SupervisorLog -Value $line -Encoding UTF8
}

# Restart pacing: 2s normally (a real crash/kill should recover fast), but
# backs off to 10s after 3 consecutive failures so a PERMANENT fault (exe
# missing, or crashing on every launch) doesn't spin the loop every 2s
# forever. "Failure" = either the exe wasn't found, or it exited within
# $FastFailThresholdSeconds of starting (a genuinely-running bridge that gets
# killed later has been up far longer than that; anything faster reads as a
# startup crash, not a normal stop). Resets to 0 on any run that clears the
# threshold, so a single manual kill of an otherwise-healthy bridge never
# triggers the backoff.
$BaseSleepSeconds        = 2
$BackoffSleepSeconds     = 10
$BackoffThreshold        = 3
$FastFailThresholdSeconds = 3
$consecutiveFailures = 0

function Get-RestartDelay {
    if ($consecutiveFailures -ge $BackoffThreshold) { return $BackoffSleepSeconds }
    return $BaseSleepSeconds
}

Write-SupervisorLog "supervisor started (exe: $ExePath)"
while ($true) {
    if (-not (Test-Path -LiteralPath $ExePath)) {
        # Deliberately does NOT fall back to python/mt5_bridge.py — a silent
        # fallback here would hide exactly the packaging gap this check exists
        # to catch. Keeps retrying so it self-heals once the exe is rebuilt,
        # with no need to restart the scheduled task by hand.
        $consecutiveFailures++
        $delay = Get-RestartDelay
        Write-SupervisorLog "[FATAL] KawkabatBridge.exe not found at: $ExePath -- build it first: powershell -ExecutionPolicy Bypass -File `"$ScriptDir\build\build.ps1`" (or set KAWKABAT_BRIDGE_EXE / pass -ExePath). Retrying in ${delay}s (consecutive failures: $consecutiveFailures) -- will NOT fall back to python/mt5_bridge.py."
        Start-Sleep -Seconds $delay
        continue
    }
    Write-SupervisorLog 'starting bridge'
    # Captured independently of the app's own file logging (bridge-YYYY-MM-DD.log)
    # on purpose: that logging goes through DailyFileHandler inside the exe
    # itself, and any exception constructing it is swallowed silently by
    # Python's logging module when stderr is unavailable (the exe's default,
    # windowed state) — this redirect is the one channel that still works even
    # if the app's own logging is broken, e.g. under the scheduled task's S4U
    # logon context where LOCALAPPDATA-relative writes have behaved differently.
    $StdOutLog = Join-Path $LogDir 'bridge-stdout.log'
    $StdErrLog = Join-Path $LogDir 'bridge-stderr.log'
    $launchedAt = Get-Date
    $proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru -Wait -WindowStyle Hidden `
        -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog
    $ranSeconds = ((Get-Date) - $launchedAt).TotalSeconds

    if ($ranSeconds -lt $FastFailThresholdSeconds) {
        $consecutiveFailures++
    } else {
        $consecutiveFailures = 0
    }
    $delay = Get-RestartDelay
    Write-SupervisorLog "bridge exited (code $($proc.ExitCode)) after $([Math]::Round($ranSeconds, 1))s -- restarting in ${delay}s (consecutive failures: $consecutiveFailures)"
    Start-Sleep -Seconds $delay
}
