from __future__ import annotations

from pathlib import Path

from app import dwg_converter


def _isolate_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("ODA_FILE_CONVERTER", raising=False)
    monkeypatch.setattr(dwg_converter, "_CONFIGURED_CONVERTER_PATH", None)


def test_selected_converter_is_remembered_when_worker_receives_none(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_settings(monkeypatch, tmp_path)
    converter = tmp_path / "ODAFileConverter.exe"
    converter.write_bytes(b"fake executable")
    source = tmp_path / "drawing.dxf"
    source.write_text("0\nSECTION\n0\nEOF\n", encoding="ascii")
    destination = tmp_path / "drawing.dwg"
    calls: dict[str, object] = {}

    def fake_convert(source_path, destination_path, **kwargs) -> None:
        calls["source"] = Path(source_path)
        calls["destination"] = Path(destination_path)
        calls["version"] = kwargs["version"]
        Path(destination_path).write_bytes(b"fake dwg")

    monkeypatch.setattr(dwg_converter.odafc, "convert", fake_convert)
    monkeypatch.setattr(dwg_converter.odafc, "is_installed", lambda: False)

    assert dwg_converter.configure_oda_converter(converter)
    saved = dwg_converter._settings_path().read_text(encoding="utf-8").strip()
    assert Path(saved) == converter.resolve()

    # Simulate a later worker or application run where the caller passes None.
    monkeypatch.setattr(dwg_converter, "_CONFIGURED_CONVERTER_PATH", None)
    result = dwg_converter.convert_dxf_to_dwg(
        source,
        destination,
        version="R2018",
        converter_executable=None,
    )

    assert result == destination.resolve()
    assert calls["source"] == source.resolve()
    assert calls["destination"] == destination.resolve()
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
