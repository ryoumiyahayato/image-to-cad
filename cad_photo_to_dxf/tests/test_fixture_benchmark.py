from __future__ import annotations

import unittest

from app.fixture_benchmark import DxfLine, compare_dxf_lines


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


if __name__ == "__main__":
    unittest.main()
