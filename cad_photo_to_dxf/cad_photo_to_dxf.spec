# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules


ROOT = Path(SPECPATH)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.version import __version__
from scripts.prepare_cad_fonts import prepare_font_bundle
from scripts.versioning import write_windows_version_info


version_info = write_windows_version_info(
    ROOT / "build" / "version_info.generated.txt",
    __version__,
)
font_directory = prepare_font_bundle(
    ROOT / "resources" / "fonts",
    allow_download=os.environ.get("CADPHOTO_SKIP_FONT_DOWNLOAD", "0") != "1",
    strict=True,
)
hiddenimports = collect_submodules("ezdxf")
hiddenimports += collect_submodules("pytesseract")
datas = collect_data_files("ezdxf")
binaries = []
for package in ("pypdfium2", "pypdfium2_raw", "rapidocr", "onnxruntime"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

datas += [
    ("README.md", "."),
    ("samples/test.jpg", "samples"),
    (str(font_directory), "resources/fonts"),
]


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
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
