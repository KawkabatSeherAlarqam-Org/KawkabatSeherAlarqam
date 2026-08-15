# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for KawkabatBridge.exe.

Build with bridge/build/build.ps1 (wraps `python -m PyInstaller` on this
file), not by editing this file's Analysis()/EXE() calls to add CLI flags —
this *is* the CLI-flag equivalent, checked into Git on purpose so the build
is reproducible without remembering a flag list.

One-file, windowed (no console) by default — see the runtime --console
switch (bridge/mt5_bridge.py: _configure_runtime_io) for live-log viewing
without rebuilding.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

BRIDGE_DIR = Path(SPECPATH).resolve().parent  # SPECPATH is bridge/build/ already -> bridge/
ENTRY_SCRIPT = str(BRIDGE_DIR / "mt5_bridge.py")

# PyInstaller's static import scan can miss submodules that Flask/Werkzeug/
# Jinja2 reach via importlib rather than a plain `import` statement — listed
# explicitly rather than discovered by trial and error against the built exe.
HIDDEN_IMPORTS = (
    # MetaTrader5's compiled _core extension imports numpy internally (via
    # its C API), invisible to PyInstaller's Python-level static analysis —
    # measured live: omitting this crashes the built exe immediately with
    # "ImportError: numpy._core.multiarray failed to import".
    ["MetaTrader5", "numpy"]
    + collect_submodules("flask")
    + collect_submodules("flask_cors")
    + collect_submodules("werkzeug")
    + collect_submodules("jinja2")
    + collect_submodules("click")
    + collect_submodules("itsdangerous")
    + collect_submodules("blinker")
)

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[str(BRIDGE_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KawkabatBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
