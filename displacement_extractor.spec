# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec dosyası
# Build icin build.bat kullan veya Anaconda Prompt'ta:
#   "C:\ProgramData\anaconda3\python.exe" -m PyInstaller displacement_extractor.spec --clean

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

# Her paket icin tum modul/veri/binary'leri topla
for pkg in ("pyNastran", "h5py", "openpyxl", "numpy"):
    d, b, h = collect_all(pkg)
    datas        += d
    binaries     += b
    hiddenimports += h

# h5py bazen DLL'lerini atlayabiliyor, explicit ekle
binaries += collect_dynamic_libs("h5py")

# h5py C uzantilari icin explicit hidden imports
hiddenimports += [
    "h5py", "h5py._hl", "h5py._hl.files", "h5py._hl.group",
    "h5py._hl.dataset", "h5py._hl.attrs", "h5py._hl.base",
    "h5py.h5", "h5py.h5a", "h5py.h5d", "h5py.h5ds",
    "h5py.h5f", "h5py.h5fd", "h5py.h5g", "h5py.h5i",
    "h5py.h5l", "h5py.h5o", "h5py.h5p", "h5py.h5r",
    "h5py.h5s", "h5py.h5t", "h5py.h5z",
    "numpy", "numpy.core", "numpy.core._multiarray_umath",
]

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
    console=False,
)
