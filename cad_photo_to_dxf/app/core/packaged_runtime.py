"""Resolve the native OCR runtime shipped with a portable application.

Source deployments retain their explicit engine configuration. A frozen
Windows application always uses its own verified resources, never an author's
PATH, source checkout, or TESSDATA_PREFIX. No runtime download is performed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def verify_ocr_bundle(directory: Path) -> dict:
    directory = Path(directory).resolve()
    manifest = directory / "native-ocr.lock.json"
    if not manifest.is_file():
        raise FileNotFoundError("NATIVE_BUNDLED_TESSERACT_MANIFEST_MISSING")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != "native-windows-ocr-resources-v1":
        raise ValueError("NATIVE_BUNDLED_TESSERACT_MANIFEST_INVALID")
    files = data.get("files", {})
    required = {"tesseract.exe", "tessdata/eng.traineddata", "LICENSE-Tesseract.txt", "LICENSE-tessdata.txt"}
    if not required.issubset(files):
        raise ValueError("NATIVE_BUNDLED_TESSERACT_RESOURCES_INCOMPLETE")
    for name, expected in files.items():
        path = (directory / name).resolve()
        if directory not in path.parents or not path.is_file():
            raise ValueError("NATIVE_BUNDLED_TESSERACT_RESOURCE_MISSING:" + name)
        if path.stat().st_size != expected["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError("NATIVE_BUNDLED_TESSERACT_RESOURCE_CHANGED:" + name)
    return data


def configure_native_ocr() -> dict:
    """Called before native manager/worker startup, independently of cwd."""
    if sys.platform != "win32":
        return {"selection": "source_deployment_configuration", "runtime_download": False}
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    bundle = root / "resources/ocr/tesseract"
    frozen = bool(getattr(sys, "frozen", False))
    if not frozen and (os.environ.get("I2CAD_TESSERACT") or not bundle.is_dir()):
        return {"selection": "source_deployment_configuration", "runtime_download": False}
    if not bundle.is_dir():
        raise FileNotFoundError("NATIVE_BUNDLED_TESSERACT_MISSING")
    manifest = verify_ocr_bundle(bundle)
    os.environ["I2CAD_TESSERACT"] = str(bundle / "tesseract.exe")
    os.environ["TESSDATA_PREFIX"] = str(bundle / "tessdata")
    return {
        "selection": "verified_application_bundle",
        "executable": os.environ["I2CAD_TESSERACT"],
        "tessdata": os.environ["TESSDATA_PREFIX"],
        "resource_profile": manifest["profile"],
        "runtime_download": False,
    }
