"""Delivery safety/state tests; actual Windows/CAD checks are a separate gate."""

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

from app import cad_delivery as service


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha256(data).hexdigest()}


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    result = tmp_path / "real-text.dxf"
    doc = ezdxf.new()
    doc.styles.new("I2CAD_TEXT", dxfattribs={"font": "DejaVuSans.ttf"})
    doc.modelspace().add_text("TEST-A7,03", dxfattribs={"style": "I2CAD_TEXT", "height": 3})
    doc.modelspace().add_line((0, 0), (10, 0))
    block = doc.blocks.new("INDEPENDENT_MARKER")
    block.add_circle((0, 0), 2)
    block.add_text("Q", dxfattribs={"style": "I2CAD_TEXT", "height": 2})
    doc.modelspace().add_blockref(block.name, (50, 50))
    doc.saveas(result)
    resources = tmp_path / "bundle"
    resources.mkdir()
    font, license_file = resources / "I2CAD_TEXT.lff", resources / "I2CAD_TEXT.LICENSE.txt"
    font.write_bytes(b"# test-only resource\n[0041]\n0,0;1,1\n")
    license_file.write_bytes(b"Test resource permission\n")
    record = {"status": "verified", "font": font.name, "path": str(font), "style": "I2CAD_TEXT",
              "profile": "test-font-v1", **identity(font), "cad_loaded": False,
              "license": {"path": str(license_file), "file": license_file.name, **identity(license_file)}}
    destination = tmp_path / "Documents" / "librecad" / "fonts"
    executable = tmp_path / "LibreCAD.exe"
    executable.write_bytes(b"This is only a mocked unit-test executable")
    monkeypatch.setattr(service, "_resources", lambda *_args, **_kwargs: [record.copy()])
    monkeypatch.setattr(service, "_resolve_cad", lambda _selected: (executable, {"version": "2.2.1.6"}))
    monkeypatch.setattr(service, "_font_directory", lambda: destination)
    monkeypatch.setattr(service, "_cache_dir", lambda: tmp_path / "app-data" / "cache")
    monkeypatch.setattr(service, "_cad_processes", lambda: [])
    return SimpleNamespace(result=result, record=record, directory=destination, executable=executable)


def test_style_inspection_includes_editable_block_text(delivery):
    records = service._drawing_fonts(delivery.result)
    assert len(records) == 1
    assert records[0]["style"] == "I2CAD_TEXT"
    assert records[0]["entities"] == 2
    assert set("TEST-A7,03Q").issubset(records[0]["characters"])


def test_inspection_does_not_install_or_mutate_drawing(delivery):
    before = delivery.result.read_bytes()
    report = service.inspect_result_fonts(delivery.result)
    assert report["status"] == "NOT_PREPARED"
    assert report["can_prepare"] and not report["can_launch"]
    assert not delivery.directory.exists()
    assert delivery.result.read_bytes() == before
    assert Path(report["details"]["log_path"]).is_file()
    assert not report["cad_loaded_verified"]


def test_prepare_is_idempotent_and_preserves_unrelated_content(delivery):
    delivery.directory.mkdir(parents=True)
    unrelated = delivery.directory / "my-other-font.lff"
    unrelated.write_bytes(b"user-owned unrelated font")
    before = delivery.result.read_bytes()
    first = service.prepare_result_fonts(delivery.result)
    assert first["status"] == "PREPARED" and len(first["installed_files"]) == 2
    target = delivery.directory / "I2CAD_TEXT.lff"
    original_stat = target.stat()
    repeated = service.prepare_result_fonts(delivery.result)
    assert repeated["status"] == "PREPARED"
    assert repeated["installed_files"] == []
    assert len(repeated["unchanged_files"]) == 2
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert unrelated.read_bytes() == b"user-owned unrelated font"
    assert delivery.result.read_bytes() == before


@pytest.mark.parametrize("filename", ["I2CAD_TEXT.lff", "i2cad_text.LFF", "I2CAD_TEXT.cxf"])
def test_existing_different_font_is_preserved_before_any_copy(delivery, filename):
    delivery.directory.mkdir(parents=True)
    conflict = delivery.directory / filename
    conflict.write_bytes(b"existing user font, not ours")
    report = service.prepare_result_fonts(delivery.result)
    assert report["status"] == "FAILED"
    assert report["details"]["failure"]["code"] == "FONT_NAME_CONFLICT"
    assert conflict.read_bytes() == b"existing user font, not ours"
    assert list(delivery.directory.iterdir()) == [conflict]
    assert report["installed_files"] == []


def test_conflicting_license_preflight_cannot_leave_a_new_font(delivery):
    license_file = delivery.directory / "ImageToCAD-licenses" / "test-font-v1" / "I2CAD_TEXT.LICENSE.txt"
    license_file.parent.mkdir(parents=True)
    license_file.write_bytes(b"do not replace")
    report = service.prepare_result_fonts(delivery.result)
    assert report["status"] == "FAILED"
    assert not (delivery.directory / "I2CAD_TEXT.lff").exists()
    assert license_file.read_bytes() == b"do not replace"


def test_preexisting_cad_must_exit_but_new_cad_is_ready(delivery, monkeypatch):
    old_process = {"pid": 77, "create_time": 1.0, "name": "LibreCAD.exe"}
    monkeypatch.setattr(service, "_cad_processes", lambda: [old_process])
    report = service.prepare_result_fonts(delivery.result)
    assert report["status"] == "REOPEN_REQUIRED"
    assert not report["can_launch"] and not report["cad_loaded_verified"]
    repeated = service.prepare_result_fonts(delivery.result)
    assert repeated["status"] == "REOPEN_REQUIRED" and not repeated["installed_files"]
    monkeypatch.setattr(service, "_cad_processes", lambda: [])
    assert service.inspect_result_fonts(delivery.result)["status"] == "PREPARED"
    new_process = {"pid": 78, "create_time": (delivery.directory / "I2CAD_TEXT.lff").stat().st_mtime + 1}
    monkeypatch.setattr(service, "_cad_processes", lambda: [new_process])
    assert service.inspect_result_fonts(delivery.result)["status"] == "PREPARED"


def test_missing_cad_does_not_copy_fonts(delivery, monkeypatch):
    monkeypatch.setattr(service, "_resolve_cad", lambda _selected: (None, {"candidates": []}))
    report = service.prepare_result_fonts(delivery.result, "/not/a/LibreCAD.exe")
    assert report["status"] == "NOT_PREPARED" and not report["can_prepare"]
    assert not delivery.directory.exists()
    assert "选择" in report["message"]


def test_launch_uses_same_gate_and_never_claims_loaded_font(delivery, monkeypatch):
    calls = []
    monkeypatch.setattr(service.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(pid=99))
    assert not service.launch_result_in_cad(delivery.result)["launch_requested"]
    assert calls == []
    assert service.prepare_result_fonts(delivery.result)["status"] == "PREPARED"
    opened = service.launch_result_in_cad(delivery.result)
    assert opened["launch_requested"] and not opened["cad_loaded_verified"]
    assert calls[0][0] == [str(delivery.executable), str(delivery.result)]
    assert "shell" not in calls[0][1]


def test_actual_version_probe_uses_supported_subcommand(monkeypatch, tmp_path):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"LibreCAD v2.2.1.6\n", stderr=b"")
    monkeypatch.setattr(service.subprocess, "run", run)
    assert service._cad_version(tmp_path / "LibreCAD.exe")["version"] == "2.2.1.6"
    assert calls[0][0][1:] == ["dxf2pdf", "--version"]
    assert calls[0][1]["timeout"] <= 15


def test_cli_writes_a_report_without_recognition(delivery, monkeypatch, tmp_path):
    import main
    monkeypatch.setattr(main, "prepare_onnx_privacy", lambda: pytest.fail("CAD delivery must not start OCR setup"))
    target = tmp_path / "report.json"
    monkeypatch.setattr(main.sys, "argv", ["CADPhotoToDXF.exe", "cad-fonts", "prepare", "--result", str(delivery.result), "--report", str(target)])
    assert main.main() == 0
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["status"] == "PREPARED"
    assert not report["cad_loaded_verified"]


def test_unsupported_style_is_not_silently_replaced(tmp_path):
    with pytest.raises(service.PreparationError, match="UNSUPPORTED_TEXT_STYLE"):
        service._resources([{"style": "OTHER", "font": "other.ttf", "characters": "A"}], tmp_path)


def test_unknown_source_font_is_not_replaced_by_bundle(tmp_path):
    (tmp_path / "DejaVuSans.ttf").write_bytes(b"different file with same name")
    with pytest.raises(service.PreparationError, match="NATIVE_FONT_SOURCE_MISMATCH"):
        service._native_resource({"characters": "ABC"}, tmp_path, False)
