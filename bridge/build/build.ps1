#requires -Version 5.1
<#
Builds bridge/build/dist/KawkabatBridge.exe from bridge/mt5_bridge.py via
kawkabat_bridge.spec, then reports its size and path.

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

$ExePath = Join-Path $BuildDir 'dist\KawkabatBridge.exe'
if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Host "[FATAL] Build finished but $ExePath is missing."
    exit 1
}

$SizeMb = [Math]::Round((Get-Item -LiteralPath $ExePath).Length / 1MB, 1)
Write-Host "[OK] $ExePath ($SizeMb MB)"
Write-Host "[WARNING] Test it from a folder OTHER than bridge/ (e.g. C:\Temp) before trusting the result -"
Write-Host "          running it from inside bridge/ can silently pick up dev-environment packages"
Write-Host "          instead of what is actually bundled in the exe."
