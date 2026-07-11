from __future__ import annotations

import unittest

import cv2
import numpy as np

from app.line_detect import LineSegment, _refine_to_centerline


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


if __name__ == "__main__":
    unittest.main()
