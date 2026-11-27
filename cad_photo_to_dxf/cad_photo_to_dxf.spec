# -*- mode: python ; coding: utf-8 -*-
"""One-folder desktop application with offline OCR and a redistributable CJK font."""
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata


ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT))

from app.version import __version__
from scripts.prepare_cad_fonts import prepare_font_bundle
from scripts.prepare_ocr_models import prepare_ocr_models
from scripts.versioning import write_windows_version_info


version_info = write_windows_version_info(ROOT / "build/version_info.generated.txt", __version__)
font_directory = prepare_font_bundle(
    ROOT / "resources/fonts",
    allow_download=os.environ.get("CADPHOTO_SKIP_FONT_DOWNLOAD") != "1", strict=True,
)
ocr_directory = prepare_ocr_models(
    ROOT / "resources/ocr/rapidocr",
    allow_download=os.environ.get("CADPHOTO_SKIP_MODEL_DOWNLOAD") != "1",
)
datas = collect_data_files("ezdxf")
datas += collect_data_files("rapidocr", excludes=["models/*", "models/**/*"])
hiddenimports = collect_submodules("ezdxf")
hiddenimports += ["rapidocr.inference_engine.onnxruntime"]
binaries = []
for package in ("numpy", "scipy", "ezdxf", "PyMuPDF", "Pillow", "rapidocr", "onnxruntime"):
    datas += copy_metadata(package)
for package in ("pymupdf", "onnxruntime"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for filename in ("NotoSansCJKsc-Regular.otf", "OFL-1.1.txt",
                 "wqy-unicode.lff", "WQY-LICENSE-Apache-2.0.txt"):
    resource = font_directory / filename
    if not resource.is_file():
        raise FileNotFoundError(f"Required CAD font resource is missing: {resource}")
    datas.append((str(resource), "resources/fonts"))
datas += [(str(ocr_directory), "resources/ocr/rapidocr"),
          (str(ROOT / "README.md"), ".")]

a = Analysis(
    [str(ROOT / "main.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
    runtime_hooks=[str(ROOT / "scripts/frozen_runtime.py")],
    excludes=["pytesseract", "torch", "paddle", "tensorflow", "openvino"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="CADPhotoToDXF", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    version=str(version_info) if sys.platform == "win32" else None, icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CADPhotoToDXF")
