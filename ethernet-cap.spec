# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 以太网上位机 onedir 打包"""

from pathlib import Path

_base = Path(SPECPATH).resolve()

a = Analysis(
    [str(_base / "gui" / "main_window.py")],
    pathex=[str(_base / "gui")],
    binaries=[],
    datas=[
        (str(_base / "ethernet-cap-engine.exe"), "."),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
        "numpy",
        "pyqtgraph",
        "pyqtgraph.exporters",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ethernet-cap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ethernet-cap",
)
