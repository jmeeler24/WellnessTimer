# PyInstaller spec for WellnessTimer.
# Build with:  pyinstaller build.spec
# Output:      dist/WellnessTimer.exe (single file, no console)
# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH).resolve()
ICON_PATH = SPEC_DIR / "assets" / "icon.ico"

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[
        (str(ICON_PATH), "assets"),
    ],
    hiddenimports=[
        "PIL._tkinter_finder",
        "pystray._win32",
        "winrt.windows.ui.notifications",
        "winrt.windows.data.xml.dom",
        "winotify",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "scipy", "pandas",
        "pytest", "IPython", "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="WellnessTimer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # --windowed: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)
