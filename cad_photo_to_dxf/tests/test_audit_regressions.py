from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import cv2
import ezdxf
import numpy as np

from app import __version__
from app.dxf_validator import validate_dxf
from app.line_detect import LineSegment, _refine_to_centerline
from scripts.versioning import parse_version, write_windows_version_info


class AuditRegressionTests(unittest.TestCase):
    def test_thick_stroke_edge_is_refined_to_its_centerline(self) -> None:
        binary = np.full((240, 420), 255, np.uint8)
        cv2.line(binary, (40, 120), (380, 120), 0, 12)
        foreground = 255 - binary
        distance_map = cv2.distanceTransform(foreground, cv2.DIST_L2, 3)

        edge_candidate = LineSegment(
            40,
            114,
            380,
            114,
            source_ids=("EDGE",),
            history=("test-input",),
        )
        refined = _refine_to_centerline(distance_map, edge_candidate)

        self.assertAlmostEqual(refined.y1, 120.0, delta=1.0)
        self.assertAlmostEqual(refined.y2, 120.0, delta=1.0)
        self.assertIn("refine_centerline", refined.history)

    def test_windows_version_metadata_uses_application_version(self) -> None:
        self.assertEqual(parse_version(__version__), (1, 1, 0, 0))
        with tempfile.TemporaryDirectory() as directory:
            output = write_windows_version_info(
                Path(directory) / "version_info.txt",
                __version__,
            )
            content = output.read_text(encoding="utf-8")
        self.assertIn(f"FileVersion', u'{__version__}'", content)
        self.assertIn(f"ProductVersion', u'{__version__}'", content)

    def test_dxf_validator_detects_duplicates_and_zero_length_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid_geometry.dxf"
            document = ezdxf.new("R2010")
            modelspace = document.modelspace()
            modelspace.add_line((0, 0), (100, 0))
            modelspace.add_line((100, 0), (0, 0))
            modelspace.add_line((25, 25), (25, 25))
            document.saveas(path)

            result = validate_dxf(path)

        self.assertFalse(result.passed)
        self.assertEqual(result.duplicate_line_count, 1)
        self.assertEqual(result.zero_length_count, 1)
        self.assertEqual(result.invalid_coordinate_count, 0)

    def test_topology_diagnostics_do_not_reject_open_drawing_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topology.dxf"
            document = ezdxf.new("R2010")
            modelspace = document.modelspace()
            modelspace.add_line((0, 0), (10, 0))
            modelspace.add_line((10.2, 0), (20, 0))
            modelspace.add_line((5, -5), (5, 5))
            document.saveas(path)

            result = validate_dxf(path, gap_tolerance=0.5)

        self.assertTrue(result.passed)
        self.assertEqual(result.near_gap_count, 1)
        self.assertEqual(result.unsplit_intersection_count, 1)
        self.assertEqual(result.open_component_count, 3)
        self.assertEqual(result.closed_component_count, 0)
        self.assertEqual(result.dangling_endpoint_count, 6)


if __name__ == "__main__":
    unittest.main()
