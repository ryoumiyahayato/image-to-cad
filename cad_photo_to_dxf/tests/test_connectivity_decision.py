from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.connectivity_safety import (
    CONNECTION_CONFIDENCE_THRESHOLD,
    evaluate_structural_bridge,
    millimetres_to_pixels,
)
from app.line_detect import LineSegment
from app.structural_roi import StructuralRoi


def _case(
    *,
    dpi: float = 300.0,
    scale: float = 1.0,
    source_width: float = 1.0,
    target_width: float = 1.0,
    draw_target: bool = True,
) -> tuple[
    list[LineSegment],
    StructuralRoi,
    np.ndarray,
    tuple[float, float],
    tuple[float, float],
]:
    lines = [
        LineSegment(
            10.0 * scale,
            20.0 * scale,
            40.0 * scale,
            20.0 * scale,
            width=source_width,
        ),
        LineSegment(
            42.0 * scale,
            10.0 * scale,
            42.0 * scale,
            40.0 * scale,
            width=target_width,
        ),
    ]
    page = np.zeros(
        (int(round(60 * scale)), int(round(70 * scale))),
        dtype=np.uint8,
    )
    for index, line in enumerate(lines):
        if index == 1 and not draw_target:
            continue
        cv2.line(
            page,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            max(1, int(round(line.width))),
            cv2.LINE_8,
        )
    maximum_gap = millimetres_to_pixels(0.4, dpi)
    roi = StructuralRoi(
        roi_id="table-001",
        purpose="table",
        bbox=(0, 0, page.shape[1], page.shape[0]),
        line_indices=(0, 1),
        evidence_intersections=(),
        confidence=1.0,
        expansion_distance=maximum_gap,
        source_types=("table_line_network", "local_endpoint_corridor"),
    )
    return (
        lines,
        roi,
        page,
        (40.0 * scale, 20.0 * scale),
        (42.0 * scale, 20.0 * scale),
    )


def _decision(
    lines: list[LineSegment],
    roi: StructuralRoi,
    page: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    dpi: float,
    protected_mask: np.ndarray | None = None,
):
    return evaluate_structural_bridge(
        roi=roi,
        lines=lines,
        source_line_index=0,
        target_line_index=1,
        start=start,
        end=end,
        peer_source_point=end,
        maximum_gap=millimetres_to_pixels(0.4, dpi),
        source_dpi=dpi,
        source_foreground=page,
        protected_mask=protected_mask,
    )


def test_connection_requires_every_hard_gate_and_explicit_confidence() -> None:
    lines, roi, page, start, end = _case()

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=300.0,
    )

    assert decision.allowed
    assert decision.reason_code == "structural_bridge_allowed"
    assert decision.confidence == 1.0
    assert decision.confidence > CONNECTION_CONFIDENCE_THRESHOLD
    assert all(decision.evidence.payload()["checks"].values())


def test_direction_mismatch_is_rejected_before_geometry_side_effects() -> None:
    lines, roi, page, start, _end = _case()

    decision = _decision(
        lines,
        roi,
        page,
        start,
        (42.0, 25.0),
        dpi=300.0,
    )

    assert not decision.allowed
    assert decision.reason_code == "direction_mismatch"
    assert decision.evidence.direction_error_degrees > 1.0


def test_line_width_mismatch_is_rejected_in_physical_units() -> None:
    lines, roi, page, start, end = _case(
        source_width=1.0,
        target_width=10.0,
    )

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=300.0,
    )

    assert not decision.allowed
    assert decision.reason_code == "line_width_mismatch"
    assert (
        decision.evidence.line_width_difference_mm
        > decision.evidence.maximum_line_width_difference_mm
    )


def test_sub_linewidth_gap_is_rejected_as_unresolved_source_evidence() -> None:
    lines, roi, page, start, end = _case(
        source_width=2.0,
        target_width=2.0,
    )

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=300.0,
    )

    assert not decision.allowed
    assert decision.reason_code == "unresolved_structural_gap"
    assert (
        decision.evidence.gap_length_mm
        < decision.evidence.minimum_resolvable_gap_mm
    )


def test_both_candidate_endpoints_require_original_pixel_support() -> None:
    lines, roi, page, start, end = _case(draw_target=False)
    page[18:23, 41:45] = 0

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=300.0,
    )

    assert not decision.allowed
    assert decision.reason_code == "missing_peer_pixel_support"
    assert decision.evidence.start_source_supported
    assert not decision.evidence.peer_source_supported


def test_protected_object_crossing_is_a_hard_rejection() -> None:
    lines, roi, page, start, end = _case()
    protected = np.zeros_like(page)
    protected[18:23, 40:43] = 255

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=300.0,
        protected_mask=protected,
    )

    assert not decision.allowed
    assert decision.reason_code == "protected_object_crossing"
    assert not decision.evidence.protection_clear


@pytest.mark.parametrize("dpi", [150.0, 300.0, 600.0])
def test_connection_distance_has_same_physical_effect_across_dpi(
    dpi: float,
) -> None:
    scale = dpi / 150.0
    lines, roi, page, start, end = _case(
        dpi=dpi,
        scale=scale,
        source_width=scale,
        target_width=scale,
    )

    decision = _decision(
        lines,
        roi,
        page,
        start,
        end,
        dpi=dpi,
    )

    assert decision.allowed
    assert decision.evidence.gap_length_mm == pytest.approx(
        2.0 * 25.4 / 150.0,
    )
    assert decision.evidence.maximum_gap_mm == pytest.approx(0.4)
    assert (
        decision.evidence.gap_length_mm
        >= decision.evidence.minimum_resolvable_gap_mm
    )
