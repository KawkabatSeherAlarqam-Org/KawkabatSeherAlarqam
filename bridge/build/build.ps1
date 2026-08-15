#requires -Version 5.1
<#
Builds bridge/build/dist/KawkabatBridge/ (a FOLDER: KawkabatBridge.exe plus an
_internal/ subfolder of dependencies -- --onedir, not --onefile) from
bridge/mt5_bridge.py via kawkabat_bridge.spec, then reports its total size
and path. Ship/copy the whole folder, not just the .exe file inside it.

Requires PyInstaller: pip install -r bridge/build/requirements-build.txt
(or: pip install pyinstaller)
#>
$ErrorActionPreference = 'Stop'

$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpecPath = Join-Path $BuildDir 'kawkabat_bridge.spec'

if (-not (Test-Path -LiteralPath $SpecPath)) {
    Write-Host "[FATAL] Spec file not found: $SpecPath"
    exit 1
}

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FATAL] PyInstaller is not installed. Run: pip install -r `"$BuildDir\requirements-build.txt`""
    exit 1
}

Write-Host "[INFO] Building via $SpecPath ..."
Push-Location $BuildDir
python -m PyInstaller --noconfirm --clean $SpecPath
$buildExit = $LASTEXITCODE
Pop-Location

if ($buildExit -ne 0) {
    Write-Host "[FATAL] PyInstaller build failed (exit $buildExit)."
    exit 1
}

$DistDir = Join-Path $BuildDir 'dist\KawkabatBridge'
$ExePath = Join-Path $DistDir 'KawkabatBridge.exe'
if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Host "[FATAL] Build finished but $ExePath is missing."
    exit 1
}

$TotalBytes = (Get-ChildItem -LiteralPath $DistDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$SizeMb = [Math]::Round($TotalBytes / 1MB, 1)
$FileCount = (Get-ChildItem -LiteralPath $DistDir -Recurse -File | Measure-Object).Count
Write-Host "[OK] $DistDir ($SizeMb MB across $FileCount files)"
Write-Host "     exe: $ExePath"
Write-Host "[WARNING] Test it from a folder OTHER than bridge/ (e.g. C:\Temp) before trusting the result -"
Write-Host "          copy the WHOLE KawkabatBridge\ folder there, not just the .exe file -- it needs"
Write-Host "          the _internal\ subfolder next to it to run. Running it from inside bridge/ can"
Write-Host "          also silently pick up dev-environment packages instead of what is actually bundled."
