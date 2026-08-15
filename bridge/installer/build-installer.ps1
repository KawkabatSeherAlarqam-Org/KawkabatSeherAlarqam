#requires -Version 5.1
<#
Builds bridge/installer/dist/KawkabatSetup.exe from KawkabatSetup.iss via
Inno Setup's ISCC.exe, then reports its size and path.

Requires an already-built bridge/build/dist/KawkabatBridge/ -- run
bridge/build/build.ps1 first. This script only packages that existing
folder into an installer; it does not build the bridge itself.

Requires Inno Setup (ISCC.exe) on PATH or in a well-known install location.
Install via: choco install innosetup -y
Or download: https://jrsoftware.org/isdl.php
#>
$ErrorActionPreference = 'Stop'

$InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$IssPath      = Join-Path $InstallerDir 'KawkabatSetup.iss'
$BridgeDir    = Split-Path -Parent $InstallerDir
$ExePath      = Join-Path $BridgeDir 'build\dist\KawkabatBridge\KawkabatBridge.exe'

if (-not (Test-Path -LiteralPath $IssPath)) {
    Write-Host "[FATAL] Iss file not found: $IssPath"
    exit 1
}
if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Host "[FATAL] $ExePath not found."
    Write-Host "        Build it first: powershell -ExecutionPolicy Bypass -File `"$BridgeDir\build\build.ps1`""
    exit 1
}

$Iscc = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $CommonPaths = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ChocolateyInstall\bin\ISCC.exe",
        "C:\ProgramData\chocolatey\bin\ISCC.exe"
    )
    foreach ($p in $CommonPaths) {
        if ($p -and (Test-Path -LiteralPath $p)) { $Iscc = Get-Item -LiteralPath $p; break }
    }
}
if (-not $Iscc) {
    Write-Host "[FATAL] ISCC.exe (Inno Setup) not found. Install it first: choco install innosetup -y"
    Write-Host "        Or download from: https://jrsoftware.org/isdl.php"
    exit 1
}

Write-Host "[INFO] Building via $IssPath ..."
& $Iscc.Source $IssPath
$buildExit = $LASTEXITCODE

if ($buildExit -ne 0) {
    Write-Host "[FATAL] ISCC.exe build failed (exit $buildExit)."
    exit 1
}

$SetupExe = Join-Path $InstallerDir 'dist\KawkabatSetup.exe'
if (-not (Test-Path -LiteralPath $SetupExe)) {
    Write-Host "[FATAL] Build finished but $SetupExe is missing."
    exit 1
}

$SizeMb = [Math]::Round((Get-Item -LiteralPath $SetupExe).Length / 1MB, 1)
Write-Host "[OK] $SetupExe ($SizeMb MB)"
