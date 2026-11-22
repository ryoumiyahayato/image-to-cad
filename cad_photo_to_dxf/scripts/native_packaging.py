"""Build-time native source evidence that travels with the frozen program."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess


def source_evidence_files(root: Path) -> list[Path]:
    root = Path(root).resolve()
    files = list((root / "app/native_objects").glob("*.py"))
    files += [root / "main.py"]
    files += [root / "app/core" / name for name in (
        "native_objects_entry.py", "processing.py", "native_worker.py",
        "native_job_manager.py", "packaged_runtime.py",
    )]
    if not files or any(not file.is_file() for file in files):
        raise FileNotFoundError("NATIVE_PACKAGING_SOURCE_EVIDENCE_MISSING")
    return sorted(set(files))


def write_build_manifest(root: Path, application_version: str) -> tuple[Path, list[tuple[str, str]]]:
    root = Path(root).resolve()
    files = source_evidence_files(root)
    source_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10,
    ).strip()
    versions = {}
    for package in ("PyInstaller", "numpy", "scipy", "ezdxf", "Pillow", "PyMuPDF", "rapidocr", "onnxruntime", "PySide6", "pytesseract", "psutil"):
        versions[package] = importlib.metadata.version(package)
    manifest = {
        "schema": "native-windows-build-v1",
        "source_commit": source_sha,
        "application_version": application_version,
        "python": platform.python_version(),
        "build_platform": platform.platform(),
        "application_sources": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
        "installed_packages": versions,
        "source_files_are_bundled_audit_resources": True,
        "original_checkout_required_at_runtime": False,
        "product_GO": False,
    }
    target = root / "resources/native-build.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target, [(str(path), path.relative_to(root).parent.as_posix()) for path in files]
