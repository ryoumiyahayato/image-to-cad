from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import cv2
import ezdxf
import numpy as np

from app.auxiliary_recognition import recognize_auxiliary
from app.cancellation import CancellationToken, ProcessingCancelled
from app.geometry_cleaner import (
    GeometryCleanParams,
    clean_geometry_with_report,
    snap_endpoints,
)
from app.layer_classifier import classify_layers_with_report
from app.line_detect import LineDetectionParams, LineSegment, detect_lines
from app.perspective import (
    MIN_AUTOMATIC_PAPER_CONFIDENCE,
    auto_correct,
    detect_paper_corners,
    order_points,
    warp_perspective,
)
from app.pipeline import InvalidInputError, PaperDetectionError, run_pipeline
from app.preprocess import PreprocessParams, preprocess_image_with_stages
from app.reporting import build_lineage


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

    def test_snap_cluster_does_not_grow_transitively_past_threshold(self) -> None:
        lines = [
            line(0, 0, 0, 100, source="A"),
            line(5, 0, 5, 100, source="B"),
            line(10, 0, 10, 100, source="C"),
        ]
        snapped = snap_endpoints(lines, 6)
        starts = [item.x1 for item in snapped]
        self.assertGreater(max(starts) - min(starts), 0.0)

    def test_final_shared_junction_stays_connected(self) -> None:
        lines = [
            line(0, 0, 100, 0, source="H"),
            line(100, 4, 100, 50, source="V"),
        ]
        result = clean_geometry_with_report(
            lines,
            GeometryCleanParams(
                snap_distance=6,
                max_bridge_gap=0,
                angle_tolerance=3,
                collinear_distance=0.1,
                duplicate_distance=0.1,
                min_line_length=1,
            ),
        )
        self.assertEqual(len(result.lines), 2)
        gap = min(
            np.linalg.norm(a - b)
            for a in (result.lines[0].p1, result.lines[0].p2)
            for b in (result.lines[1].p1, result.lines[1].p2)
        )
        self.assertAlmostEqual(float(gap), 0.0, places=6)

    def test_duplicate_merge_preserves_both_source_ids(self) -> None:
        raw = [
            line(0, 0, 100, 0, source="H1"),
            line(0.5, 0.2, 100.5, 0.2, source="L1"),
        ]
        result = clean_geometry_with_report(
            raw,
            GeometryCleanParams(
                snap_distance=0,
                max_bridge_gap=1,
                collinear_distance=1,
                duplicate_distance=1,
                min_line_length=1,
            ),
        )
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(set(result.lines[0].source_ids), {"H1", "L1"})
        lineage = build_lineage(raw, result.lines)
        self.assertTrue(lineage["source_to_final"]["H1"])
        self.assertTrue(lineage["source_to_final"]["L1"])

    def test_final_snap_duplicates_are_removed_and_lineage_is_merged(self) -> None:
        raw = [
            line(
                2.9269615525,
                11.3803862825,
                37.7234740625,
                9.9308263498,
                source="0",
            ),
            line(
                1.1371511362,
                17.7149278235,
                -2.2889548350,
                58.8239200503,
                source="1",
            ),
            line(
                9.3037162704,
                2.0352096877,
                5.9589627418,
                47.4757844199,
                source="2",
            ),
            line(
                19.3244831869,
                11.9628042627,
                16.5017612816,
                47.2551766396,
                source="3",
            ),
            line(
                14.3569525662,
                11.6433421780,
                14.2987226052,
                74.9764771152,
                source="4",
            ),
            line(
                2.1187277612,
                14.6855856500,
                38.7206310517,
                11.8738760768,
                source="5",
            ),
        ]
        result = clean_geometry_with_report(
            raw,
            GeometryCleanParams(
                snap_distance=6,
                max_bridge_gap=12,
                angle_tolerance=3,
                collinear_distance=3,
                duplicate_distance=0.2,
                min_line_length=1,
            ),
        )
        keys = {
            (
                round(item.x1, 8),
                round(item.y1, 8),
                round(item.x2, 8),
                round(item.y2, 8),
            )
            for item in result.lines
        }
        self.assertEqual(len(keys), len(result.lines))
        self.assertGreaterEqual(result.report.final_duplicate_merges, 1)
        self.assertTrue(
            any({"0", "5"}.issubset(set(item.source_ids)) for item in result.lines)
        )

    def test_cancelled_geometry_stops_cooperatively(self) -> None:
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(ProcessingCancelled):
            clean_geometry_with_report(
                [line(0, 0, 100, 0, source="A")],
                cancellation_token=token,
            )


class ClassificationTests(unittest.TestCase):
    def test_thick_parallel_walls_are_not_deleted_as_hatch(self) -> None:
        walls = [
            line(
                100,
                100 + index * 12,
                400,
                100 + index * 12,
                width=10,
                source=f"W{index}",
            )
            for index in range(5)
        ]
        result = classify_layers_with_report(
            walls,
            (1000, 1000),
            preserve_hatch=False,
        )
        self.assertEqual(len(result.lines), len(walls))
        self.assertNotIn("HATCH", [item.layer for item in result.lines])

    def test_regular_thin_family_inside_box_is_high_confidence_hatch(self) -> None:
        boundaries = [
            line(80, 80, 240, 80, width=6, source="TOP"),
            line(80, 180, 240, 180, width=6, source="BOTTOM"),
            line(80, 80, 80, 180, width=6, source="LEFT"),
            line(240, 80, 240, 180, width=6, source="RIGHT"),
        ]
        hatch = [
            line(
                100,
                100 + index * 10,
                220,
                100 + index * 10,
                source=f"F{index}",
            )
            for index in range(7)
        ]
        result = classify_layers_with_report(
            boundaries + hatch,
            (400, 400),
            preserve_hatch=False,
        )
        self.assertGreaterEqual(result.report.hatch_lines_dropped, 5)
        remaining_sources = {
            source for item in result.lines for source in item.source_ids
        }
        self.assertTrue({"TOP", "BOTTOM", "LEFT", "RIGHT"}.issubset(remaining_sources))


class AuxiliaryTests(unittest.TestCase):
    def test_circle_is_reported_as_auxiliary_only(self) -> None:
        image = np.full((240, 240), 255, np.uint8)
        cv2.circle(image, (120, 120), 45, 0, 2)
        result = recognize_auxiliary(image)
        self.assertTrue(result.circles)
        self.assertTrue(result.warnings)


class PipelineTests(unittest.TestCase):
    def test_blank_strict_pipeline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "blank.png"
            cv2.imwrite(str(source), np.full((300, 500, 3), 255, np.uint8))
            with self.assertRaises(InvalidInputError):
                run_pipeline(
                    source,
                    root / "blank.dxf",
                    strict_perspective=True,
                    fail_on_empty=True,
                )

    def test_non_paper_strict_pipeline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "circle.png"
            image = np.full((500, 700, 3), 255, np.uint8)
            cv2.circle(image, (350, 250), 150, (0, 0, 0), -1)
            cv2.imwrite(str(source), image)
            with self.assertRaises(PaperDetectionError):
                run_pipeline(
                    source,
                    root / "circle.dxf",
                    paper_size="A4",
                    paper_orientation="landscape",
                    strict_perspective=True,
                    fail_on_empty=True,
                )

    def test_pipeline_writes_report_debug_stages_and_valid_dxf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "drawing.png"
            image = np.full((420, 640, 3), 50, np.uint8)
            cv2.rectangle(image, (40, 40), (600, 380), (255, 255, 255), -1)
            cv2.rectangle(image, (40, 40), (600, 380), (0, 0, 0), 4)
            for y in (120, 200, 280):
                cv2.line(image, (100, y), (540, y), (0, 0, 0), 4)
            for x in (160, 320, 480):
                cv2.line(image, (x, 90), (x, 330), (0, 0, 0), 3)
            cv2.imwrite(str(source), image)

            output = root / "drawing.dxf"
            report_path = root / "drawing.report.json"
            result = run_pipeline(
                source,
                output,
                preview_path=root / "preview.png",
                report_path=report_path,
                debug_dir=root / "debug",
                paper_size="A4",
                paper_orientation="landscape",
                strict_perspective=True,
                fail_on_empty=True,
                detection_params=LineDetectionParams(min_line_length=30),
            )
            self.assertGreater(result.export.line_count, 0)
            self.assertTrue(result.export.calibrated)
            self.assertTrue(report_path.exists())
            self.assertTrue((root / "debug" / "01_grayscale.png").exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["application_version"], "1.3.0-preview.1")
            self.assertEqual(report["export"]["coordinate_space"], "paper_mm")
            self.assertEqual(
                report["lineage"]["final_entity_count"],
                result.export.line_count,
            )
            document = ezdxf.readfile(output)
            self.assertFalse(document.audit().errors)


if __name__ == "__main__":
    unittest.main()
