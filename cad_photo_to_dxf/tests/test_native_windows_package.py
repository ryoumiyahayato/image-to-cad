"""Protect portable OCR binding and actual saved-content smoke comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import ezdxf
import pytest

from app.core import packaged_runtime
from scripts import native_packaging
from scripts import prepare_windows_native_runtime as setup
from scripts.windows_native_smoke import entity_geometry


def make_resource_bundle(root: Path) -> Path:
    bundle = root / "resources/ocr/tesseract"
    files = {}
    for name in ("tesseract.exe", "tessdata/eng.traineddata", "LICENSE-Tesseract.txt", "LICENSE-tessdata.txt", "engine.dll"):
        data = ("synthetic transport fixture, never executed: " + name).encode()
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (bundle / "native-ocr.lock.json").write_text(json.dumps({
        "schema": "native-windows-ocr-resources-v1", "profile": "unit-test-nonexecutable",
        "files": files,
    }), encoding="utf-8")
    return bundle


def test_frozen_runtime_uses_verified_bundle_despite_author_environment(tmp_path, monkeypatch):
    bundle = make_resource_bundle(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "C:/author/private/tesseract.exe")
    monkeypatch.setenv("TESSDATA_PREFIX", "C:/author/private/models")
    result = packaged_runtime.configure_native_ocr()
    assert result["selection"] == "verified_application_bundle"
    assert Path(result["executable"]) == bundle / "tesseract.exe"
    assert Path(result["tessdata"]) == bundle / "tessdata"
    assert result["runtime_download"] is False


def test_frozen_missing_bundle_does_not_fall_back_to_host_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "host-tesseract")
    with pytest.raises(FileNotFoundError, match="NATIVE_BUNDLED_TESSERACT_MISSING"):
        packaged_runtime.configure_native_ocr()


def test_non_windows_frozen_runtime_keeps_existing_deployment_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("I2CAD_TESSERACT", "/opt/controlled/tesseract")
    assert packaged_runtime.configure_native_ocr()["selection"] == "source_deployment_configuration"


@pytest.mark.parametrize("name", ["tesseract.exe", "tessdata/eng.traineddata", "engine.dll", "LICENSE-tessdata.txt"])
def test_changed_bundled_runtime_data_or_license_is_rejected(tmp_path, name):
    bundle = make_resource_bundle(tmp_path)
    (bundle / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="RESOURCE_CHANGED"):
        packaged_runtime.verify_ocr_bundle(bundle)


def test_manifest_cannot_resolve_outside_bundle(tmp_path):
    bundle = make_resource_bundle(tmp_path)
    path = bundle / "native-ocr.lock.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["../../../outside"] = {"bytes": 0, "sha256": "0" * 64}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="RESOURCE_MISSING"):
        packaged_runtime.verify_ocr_bundle(bundle)


def test_unverified_installer_rejected_before_extraction_or_staging(tmp_path, monkeypatch):
    installer = tmp_path / "untrusted.exe"
    installer.write_bytes(b"not the pinned release")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: pytest.fail("unverified installer was extracted"))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="DOWNLOAD_IDENTITY_MISMATCH"):
        setup.prepare(output, installer=installer)
    assert not output.exists()


def test_packaged_provenance_includes_every_current_native_producer():
    root = Path(__file__).resolve().parents[1]
    files = set(native_packaging.source_evidence_files(root))
    assert set((root / "app/native_objects").glob("*.py")).issubset(files)
    assert root / "app/core/native_worker.py" in files
    assert root / "app/core/native_job_manager.py" in files
    assert root / "main.py" in files


def test_actual_geometry_comparison_detects_text_endpoint_and_block_member_change():
    document = ezdxf.new()
    line = document.modelspace().add_line((1, 2), (3, 4))
    text = document.modelspace().add_text("ROOM 17", dxfattribs={"height": 3})
    block = document.blocks.new("independent")
    member = block.add_line((0, 0), (4, 0))
    insert = document.modelspace().add_blockref("independent", (20, 20))
    line_before = entity_geometry(line, document)
    text_before = entity_geometry(text, document)
    block_before = entity_geometry(insert, document)
    line.dxf.end = (9, 4)
    text.dxf.text = "ROOM 19"
    member.dxf.end = (2, 0)
    assert entity_geometry(line, document) != line_before
    assert entity_geometry(text, document) != text_before
    assert entity_geometry(insert, document) != block_before
