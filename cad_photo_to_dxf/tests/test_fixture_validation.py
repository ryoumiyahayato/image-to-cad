from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import ezdxf
import numpy as np

from app.fixture_validation import (
    validate_fixture_directory,
    validate_fixture_set,
)
from scripts import validate_fixtures as fixture_cli


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def create_valid_fixture(root: Path) -> Path:
    fixture = root / "real-photo-001"
    fixture.mkdir(parents=True)
    source = fixture / "source.png"
    image = np.full((120, 180, 3), 255, np.uint8)
    cv2.rectangle(image, (10, 10), (170, 110), (0, 0, 0), 2)
    if not cv2.imwrite(str(source), image):
        raise RuntimeError("test image could not be written")

    ground_truth = fixture / "ground_truth.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "WALL"})
    modelspace.add_line((100, 0), (100, 50), dxfattribs={"layer": "WALL"})
    document.saveas(ground_truth)

    manifest = {
        "id": "real-photo-001",
        "is_real_capture": True,
        "fixture_categories": ["mild_perspective", "original_cad_dimensions"],
        "source_file": source.name,
        "source_sha256": sha256(source),
        "source_provenance": "Project-owned camera capture of a printed test sheet",
        "licence": "Project test fixture; redistribution permitted",
        "reviewed_by": "Independent CAD reviewer",
        "expected_outcome": "vectorized_dxf",
        "ground_truth_file": ground_truth.name,
        "ground_truth_sha256": sha256(ground_truth),
        "paper": {"size": "A4", "orientation": "landscape"},
        "coordinate_mode": "model_mm",
        "calibration_reference": {
            "start_px": [10.0, 10.0],
            "end_px": [170.0, 10.0],
            "length_mm": 100.0,
        },
        "expected_corners_px": [[10, 10], [170, 10], [170, 110], [10, 110]],
        "corner_tolerance_px": 3.0,
        "calibration_dimensions": [100.0],
        "verification_dimensions": [50.0],
        "expected_entities": {"line_min": 2, "line_max": 4},
        "expected_layers": {"WALL": {"min": 2, "max": 4}},
        "intentional_open_contours": True,
        "tolerances": {
            "endpoint_mm": 1.0,
            "angle_degrees": 1.0,
            "scale_relative": 0.02,
            "hausdorff_mm": 2.0,
        },
        "freecad_version": "0.19.2",
    }
    (fixture / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return fixture


def create_negative_fixture(root: Path) -> Path:
    fixture = root / "non-paper-001"
    fixture.mkdir(parents=True)
    source = fixture / "source.png"
    image = np.full((160, 160, 3), 255, np.uint8)
    cv2.circle(image, (80, 80), 55, (0, 0, 0), 5)
    if not cv2.imwrite(str(source), image):
        raise RuntimeError("negative test image could not be written")

    manifest = {
        "id": "non-paper-001",
        "is_real_capture": True,
        "fixture_categories": ["non_paper_negative"],
        "source_file": source.name,
        "source_sha256": sha256(source),
        "source_provenance": "Project-owned camera capture of a non-paper object",
        "licence": "Project test fixture; redistribution permitted",
        "reviewed_by": "Independent fixture reviewer",
        "expected_outcome": "paper_rejected",
        "expected_rejection": "paper_detection",
    }
    (fixture / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return fixture


class FixtureValidationTests(unittest.TestCase):
    def test_complete_real_photo_fixture_qualifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_valid_fixture(Path(directory))
            result = validate_fixture_directory(fixture)

        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.fixture_id, "real-photo-001")
        self.assertEqual(result.expected_outcome, "vectorized_dxf")

    def test_non_paper_fixture_qualifies_without_ground_truth_dxf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_negative_fixture(Path(directory))
            result = validate_fixture_directory(fixture)

        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.expected_outcome, "paper_rejected")
        self.assertEqual(result.fixture_categories, ("non_paper_negative",))

    def test_placeholder_provenance_and_synthetic_capture_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = create_valid_fixture(Path(directory))
            manifest_path = fixture / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["is_real_capture"] = False
            manifest["source_provenance"] = "unknown"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_fixture_directory(fixture)

        self.assertFalse(result.passed)
        self.assertTrue(any("is_real_capture" in error for error in result.errors))
        self.assertTrue(any("source_provenance" in error for error in result.errors))

    def test_release_minimum_blocks_empty_fixture_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_fixture_set(directory, minimum_required=1)

        self.assertFalse(result.passed)
        self.assertEqual(result.qualifying_count, 0)
        self.assertIn("minimum required is 1", result.errors[0])

    def test_release_gate_requires_all_capture_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_valid_fixture(root)
            create_negative_fixture(root)
            report_path = root / "qualification.json"
            with patch.object(
                sys,
                "argv",
                [
                    "validate_fixtures.py",
                    str(root),
                    "--minimum",
                    "1",
                    "--output",
                    str(report_path),
                ],
            ):
                status = fixture_cli.main()
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertFalse(report["category_coverage_passed"])
        self.assertIn("flat_scan", report["missing_categories"])
        self.assertNotIn("non_paper_negative", report["missing_categories"])
        self.assertEqual(report["benchmarks"], [])


if __name__ == "__main__":
    unittest.main()
