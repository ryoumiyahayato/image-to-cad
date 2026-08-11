from __future__ import annotations

import cv2
import numpy as np

from app.line_detect import LineSegment
from app.straight_line_reconstruction import (
    _prepare_late_restorations,
    collapse_scan_parallel_duplicates,
    extend_lines_to_first_intersection,
    reconstruct_straight_lines,
    suppress_parallel_duplicate_detections,
    suppress_reconstructed_lines,
)
from app.structural_roi import detect_structural_rois


def test_gapped_perpendicular_lines_are_not_extended_without_structural_roi() -> None:
    horizontal = LineSegment(10.0, 50.0, 46.0, 50.0)
    vertical = LineSegment(50.0, 54.0, 50.0, 90.0)

    resolved = extend_lines_to_first_intersection(
        [horizontal, vertical],
        maximum_extension=8.0,
    )

    assert (resolved[0].x2, resolved[0].y2) == (46.0, 50.0)
    assert (resolved[1].x1, resolved[1].y1) == (50.0, 54.0)


def test_late_restoration_output_is_additive_and_deduplicates_base_geometry() -> None:
    gray = np.zeros((120, 160), dtype=np.uint8)
    base = [LineSegment(20.0, 50.0, 100.0, 50.0, width=2.0)]
    candidates = [
        LineSegment(20.0, 50.0, 100.0, 50.0, width=2.0),
        LineSegment(20.0, 80.0, 100.0, 80.0, width=2.0),
    ]

    prepared = _prepare_late_restorations(
        candidates,
        base,
        gray=gray,
        scale=1.0,
    )

    assert prepared == (candidates[1],)


def test_late_restoration_output_rejects_thick_candidates() -> None:
    gray = np.zeros((120, 160), dtype=np.uint8)
    candidate = LineSegment(20.0, 80.0, 100.0, 80.0, width=7.0)

    prepared = _prepare_late_restorations(
        [candidate],
        (),
        gray=gray,
        scale=1.0,
    )

    assert prepared == ()


def test_gapped_frame_rules_reconnect_only_inside_detected_roi() -> None:
    lines = [
        LineSegment(14.0, 10.0, 86.0, 10.0),
        LineSegment(14.0, 50.0, 86.0, 50.0),
        LineSegment(10.0, 14.0, 10.0, 46.0),
        LineSegment(90.0, 14.0, 90.0, 46.0),
    ]
    foreground = np.zeros((80, 110), dtype=np.uint8)
    for line in lines:
        cv2.line(
            foreground,
            (int(line.x1), int(line.y1)),
            (int(line.x2), int(line.y2)),
            255,
            1,
        )
    rois = detect_structural_rois(
        lines,
        image_shape=foreground.shape,
        extension_budget=8.0,
    )

    resolved = extend_lines_to_first_intersection(
        lines,
        maximum_extension=8.0,
        structural_rois=rois,
        source_foreground=foreground,
    )

    assert len(rois.rois) == 1
    assert rois.rois[0].purpose == "frame"
    assert (resolved[0].x1, resolved[0].x2) == (10.0, 90.0)
    assert (resolved[2].y1, resolved[2].y2) == (10.0, 50.0)


def test_protected_body_region_blocks_structural_bridge() -> None:
    lines = [
        LineSegment(14.0, 10.0, 86.0, 10.0),
        LineSegment(14.0, 50.0, 86.0, 50.0),
        LineSegment(10.0, 14.0, 10.0, 46.0),
        LineSegment(90.0, 14.0, 90.0, 46.0),
    ]
    foreground = np.zeros((80, 110), dtype=np.uint8)
    for line in lines:
        cv2.line(
            foreground,
            (int(line.x1), int(line.y1)),
            (int(line.x2), int(line.y2)),
            255,
            1,
        )
    protected = np.zeros_like(foreground)
    protected[8:13, 8:16] = 255
    rois = detect_structural_rois(
        lines,
        image_shape=foreground.shape,
        extension_budget=8.0,
    )

    resolved = extend_lines_to_first_intersection(
        lines,
        maximum_extension=8.0,
        structural_rois=rois,
        source_foreground=foreground,
        protected_mask=protected,
    )

    assert (resolved[0].x1, resolved[0].y1) == (14.0, 10.0)
    assert (resolved[2].x1, resolved[2].y1) == (10.0, 14.0)


def test_existing_crossing_is_not_extended_or_shortened() -> None:
    horizontal = LineSegment(10.0, 50.0, 90.0, 50.0)
    vertical = LineSegment(50.0, 10.0, 50.0, 90.0)

    resolved = extend_lines_to_first_intersection(
        [horizontal, vertical],
        maximum_extension=12.0,
    )

    assert resolved[0].p1.tolist() == horizontal.p1.tolist()
    assert resolved[0].p2.tolist() == horizontal.p2.tolist()
    assert resolved[1].p1.tolist() == vertical.p1.tolist()
    assert resolved[1].p2.tolist() == vertical.p2.tolist()


def test_reconstructed_rules_are_removed_from_contour_source() -> None:
    binary = np.full((180, 240), 255, dtype=np.uint8)
    cv2.line(binary, (20, 80), (220, 80), 0, 5, cv2.LINE_8)
    cv2.line(binary, (120, 20), (120, 160), 0, 5, cv2.LINE_8)

    lines = reconstruct_straight_lines(binary)
    residual = suppress_reconstructed_lines(binary, lines)

    assert len(lines) >= 2
    assert np.count_nonzero(residual == 0) < np.count_nonzero(binary == 0) * 0.25


def test_shallow_artifact_crossing_does_not_trigger_extension() -> None:
    horizontal = LineSegment(10.0, 50.0, 46.0, 50.0)
    crease = LineSegment(50.0, 51.0, 95.0, 65.0)

    resolved = extend_lines_to_first_intersection(
        [horizontal, crease],
        maximum_extension=12.0,
    )

    assert resolved[0].p2.tolist() == horizontal.p2.tolist()
    assert resolved[1].p1.tolist() == crease.p1.tolist()


def test_extension_distance_is_bounded_by_source_line_length() -> None:
    short = LineSegment(10.0, 50.0, 30.0, 50.0)
    vertical = LineSegment(38.0, 40.0, 38.0, 60.0)

    resolved = extend_lines_to_first_intersection(
        [short, vertical],
        maximum_extension=12.0,
    )

    assert resolved[0].p2.tolist() == short.p2.tolist()


def test_crossing_rule_segments_are_not_globally_rejoined() -> None:
    binary = np.full((260, 360), 255, dtype=np.uint8)
    cv2.rectangle(binary, (15, 15), (345, 245), 0, 3)
    cv2.line(binary, (95, 95), (265, 95), 0, 4)
    cv2.line(binary, (180, 65), (180, 130), 0, 4)

    lines = reconstruct_straight_lines(binary)

    assert lines
    horizontal = [
        line
        for line in lines
        if abs((line.y1 + line.y2) * 0.5 - 95.0) <= 4.0
    ]
    assert any(max(line.x1, line.x2) < 180.0 for line in horizontal)
    assert any(min(line.x1, line.x2) > 180.0 for line in horizontal)
    assert not any(
        min(line.x1, line.x2) < 170.0
        and max(line.x1, line.x2) > 190.0
        for line in horizontal
    )


def test_duplicate_suppression_keeps_one_original_segment() -> None:
    gray = np.full((100, 120), 255, dtype=np.uint8)
    cv2.line(gray, (10, 50), (90, 50), 0, 5, cv2.LINE_8)
    longest = LineSegment(10.0, 49.0, 90.0, 49.0)
    duplicate = LineSegment(20.0, 51.0, 80.0, 51.0)

    resolved = suppress_parallel_duplicate_detections(
        [duplicate, longest],
        gray=gray,
        scale=1.0,
    )

    assert len(resolved) == 1
    assert (
        resolved[0].x1,
        resolved[0].y1,
        resolved[0].x2,
        resolved[0].y2,
    ) == (
        longest.x1,
        longest.y1,
        longest.x2,
        longest.y2,
    )
    assert "suppress_parallel_duplicate_detection" in resolved[0].history


def test_low_contrast_crop_and_fold_edges_do_not_become_blue_lines() -> None:
    gray = np.full((900, 1200), 235, dtype=np.uint8)
    binary = np.full_like(gray, 255)

    cv2.line(gray, (120, 300), (1080, 300), 45, 3, cv2.LINE_AA)
    cv2.line(binary, (120, 300), (1080, 300), 0, 3, cv2.LINE_8)

    cv2.line(gray, (2, 80), (2, 820), 178, 3, cv2.LINE_AA)
    cv2.line(binary, (2, 80), (2, 820), 0, 3, cv2.LINE_8)
    cv2.line(gray, (640, 100), (640, 800), 172, 3, cv2.LINE_AA)
    cv2.line(binary, (640, 100), (640, 800), 0, 3, cv2.LINE_8)

    lines = reconstruct_straight_lines(
        binary,
        scan_support_gray=gray,
    )

    assert any(abs((line.y1 + line.y2) * 0.5 - 300.0) <= 4.0 for line in lines)
    assert all(abs((line.x1 + line.x2) * 0.5 - 2.0) > 6.0 for line in lines)
    assert all(abs((line.x1 + line.x2) * 0.5 - 640.0) > 6.0 for line in lines)


def test_deep_supported_broken_scan_rules_are_not_extended_across_large_gap() -> None:
    gray = np.full((500, 700), 235, dtype=np.uint8)
    binary = np.full_like(gray, 255)
    cv2.line(gray, (80, 250), (345, 250), 45, 3, cv2.LINE_AA)
    cv2.line(binary, (80, 250), (345, 250), 0, 3, cv2.LINE_8)
    cv2.line(gray, (350, 255), (350, 440), 45, 3, cv2.LINE_AA)
    cv2.line(binary, (350, 255), (350, 440), 0, 3, cv2.LINE_8)

    lines = reconstruct_straight_lines(
        binary,
        scan_support_gray=gray,
    )

    horizontal = max(
        (line for line in lines if abs(line.angle) <= 4.0),
        key=lambda line: line.length,
    )
    vertical = max(
        (line for line in lines if abs(line.angle - 90.0) <= 4.0),
        key=lambda line: line.length,
    )
    assert 340.0 <= horizontal.x2 <= 346.0
    assert 250.0 <= vertical.y1 <= 254.0


def test_scanned_thick_rule_edges_collapse_without_erasing_double_rules() -> None:
    gray = np.full((300, 420), 235, dtype=np.uint8)
    cv2.line(gray, (30, 103), (390, 103), 35, 9, cv2.LINE_8)
    cv2.line(gray, (203, 30), (203, 270), 35, 9, cv2.LINE_8)
    cv2.line(gray, (30, 150), (390, 150), 35, 1, cv2.LINE_8)
    cv2.line(gray, (30, 158), (390, 158), 35, 1, cv2.LINE_8)

    lines = [
        LineSegment(30.0, 100.0, 390.0, 100.0),
        LineSegment(30.0, 106.0, 390.0, 106.0),
        LineSegment(200.0, 30.0, 200.0, 270.0),
        LineSegment(206.0, 30.0, 206.0, 270.0),
        LineSegment(30.0, 150.0, 390.0, 150.0),
        LineSegment(30.0, 158.0, 390.0, 158.0),
    ]

    resolved = collapse_scan_parallel_duplicates(
        lines,
        gray=gray,
        scale=2.0,
    )

    horizontal_coordinates = sorted(
        round((line.y1 + line.y2) * 0.5)
        for line in resolved
        if abs(line.y2 - line.y1) < 1.0
    )
    vertical_coordinates = sorted(
        round((line.x1 + line.x2) * 0.5)
        for line in resolved
        if abs(line.x2 - line.x1) < 1.0
    )
    assert horizontal_coordinates == [103, 150, 158]
    assert vertical_coordinates == [203]
    assert (
        sum("collapse_scan_parallel_duplicate" in line.history for line in resolved)
        == 2
    )
