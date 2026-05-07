# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec dosyası — Anaconda Prompt'ta şunu çalıştır:
#   pyinstaller displacement_extractor.spec

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = []

for pkg in ("pyNastran", "h5py", "openpyxl", "numpy"):
    d, b, h = collect_all(pkg)
    datas     += d
    binaries  += b
    hiddenimports += h

a = Analysis(
    ["displacement_extractor.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="DisplacementExtractor",
    debug=False,
    strip=False,
    upx=False,
    console=False,   # Siyah terminal penceresi çıkmaz
)
