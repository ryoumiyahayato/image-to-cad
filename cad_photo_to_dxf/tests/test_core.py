from __future__ import annotations

import unittest

import cv2
import numpy as np

from app.geometry.line_detect import LineDetectionParams, LineSegment, detect_lines
from app.core.perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE, auto_correct, detect_paper_corners, order_points, warp_perspective
from app.geometry.preprocess import PreprocessParams, preprocess_image_with_stages


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    width: float = 1.0,
    source: str,
) -> LineSegment:
    return LineSegment(
        x1,
        y1,
        x2,
        y2,
        width=width,
        source_ids=(source,),
        history=("test-input",),
    )


class PerspectiveTests(unittest.TestCase):
    def test_diamond_order_has_four_unique_points(self) -> None:
        points = np.array([[0, 1], [1, 0], [2, 1], [1, 2]], np.float32)
        ordered = order_points(points)
        self.assertEqual(len(np.unique(ordered, axis=0)), 4)

    def test_target_aspect_ratio_is_preserved(self) -> None:
        image = np.full((800, 1000, 3), 255, np.uint8)
        corners = np.array(
            [[100, 100], [900, 150], [800, 550], [250, 600]],
            np.float32,
        )
        corrected = warp_perspective(image, corners, target_aspect_ratio=2.0)
        self.assertAlmostEqual(
            corrected.shape[1] / corrected.shape[0],
            2.0,
            delta=0.01,
        )

    def test_blank_image_is_not_paper(self) -> None:
        blank = np.full((300, 500, 3), 255, np.uint8)
        self.assertIsNone(detect_paper_corners(blank))

    def test_internal_black_frame_on_white_background_is_not_paper(self) -> None:
        image = np.full((500, 700, 3), 255, np.uint8)
        cv2.rectangle(image, (100, 100), (600, 400), (0, 0, 0), 6)
        self.assertIsNone(auto_correct(image, target_aspect_ratio=297.0 / 210.0))

    def test_black_circle_is_not_paper(self) -> None:
        image = np.full((500, 700, 3), 255, np.uint8)
        cv2.circle(image, (350, 250), 150, (0, 0, 0), -1)
        self.assertIsNone(auto_correct(image, target_aspect_ratio=297.0 / 210.0))

    def test_clear_sheet_exceeds_strict_confidence(self) -> None:
        image = np.full((420, 640, 3), 50, np.uint8)
        cv2.rectangle(image, (40, 40), (600, 380), (255, 255, 255), -1)
        cv2.rectangle(image, (40, 40), (600, 380), (0, 0, 0), 4)
        result = auto_correct(image, target_aspect_ratio=297.0 / 210.0)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result.confidence, MIN_AUTOMATIC_PAPER_CONFIDENCE)


class PreprocessTests(unittest.TestCase):
    def test_default_preprocessing_retains_thin_lines_in_all_directions(self) -> None:
        for start, end in [
            ((20, 110), (200, 110)),
            ((110, 20), (110, 200)),
            ((20, 200), (200, 20)),
        ]:
            with self.subTest(start=start, end=end):
                image = np.full((220, 220), 255, np.uint8)
                cv2.line(image, start, end, 0, 1)
                result = preprocess_image_with_stages(image, PreprocessParams())
                self.assertGreater(np.count_nonzero(result.image == 0), 150)
                self.assertEqual(len(result.stages), 6)


class DetectionAndGeometryTests(unittest.TestCase):
    def test_thick_stroke_width_uses_centerline_search(self) -> None:
        image = np.full((240, 420), 255, np.uint8)
        cv2.line(image, (40, 120), (380, 120), 0, 12)
        detected = detect_lines(image, LineDetectionParams(min_line_length=80))
        self.assertTrue(detected)
        self.assertGreater(max(item.width for item in detected), 8.0)













if __name__ == "__main__":
    unittest.main()
