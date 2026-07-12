from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.fixture_benchmark import (
    DxfLine,
    compare_dxf_lines,
    run_fixture_benchmark,
)
from app.pipeline import PaperDetectionError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_negative_fixture(root: Path) -> Path:
    fixture = root / "non-paper"
    fixture.mkdir(parents=True)
    source = fixture / "source.png"
    image = np.full((160, 160, 3), 255, np.uint8)
    cv2.circle(image, (80, 80), 55, (0, 0, 0), 5)
    if not cv2.imwrite(str(source), image):
        raise RuntimeError("negative fixture image could not be written")
    manifest = {
        "id": "non-paper",
        "is_real_capture": True,
        "fixture_categories": ["non_paper_negative"],
        "source_file": source.name,
        "source_sha256": _sha256(source),
        "source_provenance": "Project-owned camera capture",
        "licence": "Project fixture; redistribution permitted",
        "reviewed_by": "Independent fixture reviewer",
        "expected_outcome": "paper_rejected",
        "expected_rejection": "paper_detection",
    }
    (fixture / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return fixture


class FixtureBenchmarkTests(unittest.TestCase):
    def test_identical_geometry_has_zero_error(self) -> None:
        truth = [
            DxfLine((0.0, 0.0), (100.0, 0.0), "WALL"),
            DxfLine((100.0, 0.0), (100.0, 50.0), "WALL"),
        ]
        metrics = compare_dxf_lines(list(truth), truth)

        self.assertEqual(metrics.candidate_line_count, 2)
        self.assertEqual(metrics.ground_truth_line_count, 2)
        self.assertAlmostEqual(metrics.endpoint_hausdorff, 0.0)
        self.assertAlmostEqual(metrics.sampled_hausdorff, 0.0)
        self.assertAlmostEqual(metrics.maximum_angle_error_degrees, 0.0)
        self.assertAlmostEqual(metrics.scale_relative_error, 0.0)
        self.assertEqual(metrics.candidate_layer_counts, {"WALL": 2})

    def test_scaled_geometry_reports_scale_and_distance_error(self) -> None:
        truth = [DxfLine((0.0, 0.0), (100.0, 0.0), "WALL")]
        candidate = [DxfLine((0.0, 0.0), (200.0, 0.0), "WALL")]
        metrics = compare_dxf_lines(candidate, truth)

        self.assertAlmostEqual(metrics.scale_relative_error, 1.0)
        self.assertGreater(metrics.endpoint_hausdorff, 0.0)
        self.assertGreater(metrics.sampled_hausdorff, 0.0)

    def test_rotated_geometry_reports_acute_angle_error(self) -> None:
        truth = [DxfLine((-50.0, 0.0), (50.0, 0.0), "AXIS")]
        candidate = [DxfLine((0.0, -50.0), (0.0, 50.0), "AXIS")]
        metrics = compare_dxf_lines(candidate, truth)

        self.assertAlmostEqual(metrics.maximum_angle_error_degrees, 90.0)

    def test_non_paper_fixture_passes_only_on_paper_detection_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _create_negative_fixture(root)
            with patch(
                "app.fixture_benchmark.run_pipeline",
                side_effect=PaperDetectionError("paper not detected"),
            ):
                result = run_fixture_benchmark(fixture, root / "output")

        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.expected_outcome, "paper_rejected")
        self.assertIsNone(result.metrics)

    def test_non_paper_fixture_fails_when_pipeline_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = _create_negative_fixture(root)
            with patch("app.fixture_benchmark.run_pipeline", return_value=object()):
                result = run_fixture_benchmark(fixture, root / "output")

        self.assertFalse(result.passed)
        self.assertIn("accepted as a paper drawing", result.errors[0])


if __name__ == "__main__":
    unittest.main()
