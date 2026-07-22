from __future__ import annotations

from pathlib import Path
import subprocess

from app import dwg_converter


def _isolate_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("ODA_FILE_CONVERTER", raising=False)
    monkeypatch.setattr(dwg_converter, "_CONFIGURED_CONVERTER_PATH", None)


def test_selected_converter_is_remembered_and_used_silently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    converter = tmp_path / "ODAFileConverter.exe"
    converter.write_bytes(b"fake executable")
    source = tmp_path / "drawing.dxf"
    source.write_text("0\nSECTION\n0\nEOF\n", encoding="ascii")
    destination = tmp_path / "renamed-output.dwg"
    calls: dict[str, object] = {}

    def fake_run(executable, source_path, output_dir, version):
        calls["executable"] = executable
        calls["source"] = source_path
        calls["version"] = version
        (output_dir / "drawing.dwg").write_bytes(b"fake dwg")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(dwg_converter, "_run_converter", fake_run)

    assert dwg_converter.configure_oda_converter(converter)
    saved = dwg_converter._settings_path().read_text(encoding="utf-8").strip()
    assert Path(saved) == converter.resolve()

    monkeypatch.setattr(dwg_converter, "_CONFIGURED_CONVERTER_PATH", None)
    result = dwg_converter.convert_dxf_to_dwg(
        source,
        destination,
        version="R2018",
        converter_executable=None,
    )

    assert result == destination.resolve()
    assert destination.read_bytes() == b"fake dwg"
    assert calls["executable"] == converter.resolve()
    assert calls["source"] == source.resolve()
    assert calls["version"] == "R2018"


def test_converter_directory_can_be_selected(monkeypatch, tmp_path: Path) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    folder = tmp_path / "ODA File Converter 27.11.0"
    folder.mkdir()
    executable = folder / "ODAFileConverter.exe"
    executable.write_bytes(b"fake executable")

    assert dwg_converter.find_oda_converter(folder) == executable.resolve()
    assert dwg_converter.configure_oda_converter(folder)


def test_app_local_oda_folder_is_detected(monkeypatch, tmp_path: Path) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    app_dir = tmp_path / "CADPhotoToDXF"
    app_dir.mkdir()
    app_executable = app_dir / "CADPhotoToDXF.exe"
    app_executable.write_bytes(b"fake app")
    oda_executable = app_dir / "ODAFileConverter" / "ODAFileConverter.exe"
    oda_executable.parent.mkdir()
    oda_executable.write_bytes(b"fake executable")
    monkeypatch.setattr(dwg_converter.sys, "executable", str(app_executable))

    assert dwg_converter.find_oda_converter() == oda_executable.resolve()


def test_oda_cli_arguments_do_not_open_folder_selection(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "ODAFileConverter.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "drawing.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    captured: dict[str, object] = {}

    def fake_subprocess_run(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(dwg_converter.subprocess, "run", fake_subprocess_run)
    dwg_converter._run_converter(executable, source, output_dir, "R2010")

    assert captured["arguments"] == [
        str(executable),
        str(tmp_path),
        str(output_dir),
        "ACAD2010",
        "DWG",
        "0",
        "1",
        "drawing.dxf",
    ]
