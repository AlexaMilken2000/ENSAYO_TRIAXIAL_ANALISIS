# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "trial2.0.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "img triaxial 1.webp"), "."),
        (str(ROOT / "img logo 2.png"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pylatex"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EnsayoTriaxial",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "log32.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="EnsayoTriaxial",
)
