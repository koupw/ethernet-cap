# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 以太网上位机 单文件打包"""

import os
import sys
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
    a.binaries,
    a.datas,
    [],
    name="ethernet-cap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # 无终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
