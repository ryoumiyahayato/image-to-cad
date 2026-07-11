from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from validation.validate_dxf import main as validate_dxf_main


def _run_validation(source: Path, evidence: Path, monkeypatch) -> dict[str, object]:
    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_dxf.py",
            "--input",
            str(source),
            "--output",
            str(evidence),
        ],
    )
    exit_code = validate_dxf_main()
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["_exit_code"] = exit_code
    return report


def test_machine_readable_validation_accepts_valid_line_and_circle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "valid.dxf"
    evidence = tmp_path / "valid.validation.json"
    document = ezdxf.new("R2010")
    document.layers.add("DETAIL")
    document.layers.add("CIRCLE_CONFIRMED")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "DETAIL"})
    modelspace.add_circle(
        (50, 50),
        10,
        dxfattribs={"layer": "CIRCLE_CONFIRMED"},
    )
    document.saveas(source)

    report = _run_validation(source, evidence, monkeypatch)
    assert report["_exit_code"] == 0
    assert report["success"] is True
    assert report["supported_entity_count"] == 2
    assert report["unexpected_entity_count"] == 0
    assert report["empty_geometry"] is False
    assert report["line_count"] == 1
    assert report["circle_count"] == 1
    assert report["exact_duplicate_line_count"] == 0
    assert report["exact_duplicate_circle_count"] == 0
    assert report["nonpositive_radius_circle_count"] == 0


def test_machine_readable_validation_rejects_duplicate_circles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "duplicate-circle.dxf"
    evidence = tmp_path / "duplicate-circle.validation.json"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_circle((50, 50), 10)
    modelspace.add_circle((50, 50), 10)
    document.saveas(source)

    report = _run_validation(source, evidence, monkeypatch)
    assert report["_exit_code"] == 1
    assert report["success"] is False
    assert report["exact_duplicate_circle_count"] == 1


def test_machine_readable_validation_rejects_empty_geometry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "empty.dxf"
    evidence = tmp_path / "empty.validation.json"
    ezdxf.new("R2010").saveas(source)

    report = _run_validation(source, evidence, monkeypatch)
    assert report["_exit_code"] == 1
    assert report["success"] is False
    assert report["empty_geometry"] is True
    assert report["supported_entity_count"] == 0


def test_machine_readable_validation_rejects_unexpected_entities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "unexpected.dxf"
    evidence = tmp_path / "unexpected.validation.json"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0))
    modelspace.add_text("unexpected")
    document.saveas(source)

    report = _run_validation(source, evidence, monkeypatch)
    assert report["_exit_code"] == 1
    assert report["success"] is False
    assert report["unexpected_entity_types"] == ["TEXT"]
    assert report["unexpected_entity_count"] == 1
