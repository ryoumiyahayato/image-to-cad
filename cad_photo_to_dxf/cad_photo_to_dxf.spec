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
from scripts.prepare_librecad_font import prepare_librecad_font
from scripts.versioning import write_windows_version_info


version_info = write_windows_version_info(
    ROOT / "build" / "version_info.generated.txt",
    __version__,
)
font_resource_directory = ROOT / "resources" / "fonts"
font_resource_directory.mkdir(parents=True, exist_ok=True)
font_license_path = font_resource_directory / "OFL-1.1.txt"
if not font_license_path.exists():
    font_license_path.write_text(
        "SIL Open Font License 1.1\n"
        "The packaged Noto CJK fonts are distributed under the OFL 1.1.\n"
        "Full license: https://openfontlicense.org/open-font-license-official-text/\n",
        encoding="utf-8",
    )
allow_font_download = os.environ.get("CADPHOTO_SKIP_FONT_DOWNLOAD", "0") != "1"
font_directory = prepare_font_bundle(
    font_resource_directory,
    allow_download=allow_font_download,
    strict=True,
)
prepare_librecad_font(
    font_resource_directory,
    allow_download=allow_font_download,
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
