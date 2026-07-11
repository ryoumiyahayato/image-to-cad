from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from validation.validate_dxf import main as validate_dxf_main


def test_machine_readable_validation_accepts_valid_line_and_circle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "valid.dxf"
    evidence = tmp_path / "valid.validation.json"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "DETAIL"})
    modelspace.add_circle(
        (50, 50),
        10,
        dxfattribs={"layer": "CIRCLE_CONFIRMED"},
    )
    document.saveas(source)

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
    assert validate_dxf_main() == 0
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["success"] is True
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
    assert validate_dxf_main() == 1
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["success"] is False
    assert report["exact_duplicate_circle_count"] == 1
