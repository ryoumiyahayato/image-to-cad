# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.version import __version__
from scripts.versioning import write_windows_version_info


version_info = write_windows_version_info(
    ROOT / "build" / "version_info.generated.txt",
    __version__,
)
hiddenimports = collect_submodules("ezdxf")
hiddenimports += collect_submodules("pytesseract")
datas = collect_data_files("ezdxf")
datas += [
    ("README.md", "."),
    ("samples/test.jpg", "samples"),
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="CADPhotoToDXF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(version_info),
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CADPhotoToDXF",
)
