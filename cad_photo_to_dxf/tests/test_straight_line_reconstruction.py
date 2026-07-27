from __future__ import annotations

import cv2
import numpy as np

from app.line_detect import LineSegment
from app.straight_line_reconstruction import (
    extend_lines_to_first_intersection,
    reconstruct_straight_lines,
    suppress_reconstructed_lines,
)


def test_gapped_perpendicular_lines_extend_only_to_intersection() -> None:
    horizontal = LineSegment(10.0, 50.0, 46.0, 50.0)
    vertical = LineSegment(50.0, 54.0, 50.0, 90.0)

    resolved = extend_lines_to_first_intersection(
        [horizontal, vertical],
        maximum_extension=8.0,
    )

    assert (resolved[0].x2, resolved[0].y2) == (50.0, 50.0)
    assert (resolved[1].x1, resolved[1].y1) == (50.0, 50.0)


def test_endpoint_stops_at_nearest_theoretical_intersection() -> None:
    horizontal = LineSegment(10.0, 50.0, 45.0, 50.0)
    nearer = LineSegment(50.0, 45.0, 50.0, 55.0)
    farther = LineSegment(56.0, 45.0, 56.0, 55.0)

    resolved = extend_lines_to_first_intersection(
        [horizontal, nearer, farther],
        maximum_extension=12.0,
    )

    assert (resolved[0].x2, resolved[0].y2) == (50.0, 50.0)


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
