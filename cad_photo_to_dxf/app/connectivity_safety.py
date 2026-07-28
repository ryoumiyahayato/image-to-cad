from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from .line_detect import LineSegment
from .structural_roi import (
    StructuralRoi,
    rasterize_structural_lines,
    segment_length,
)


@dataclass(frozen=True)
class ConnectivityDecision:
    allowed: bool
    reason_code: str
    roi_id: str
    bridge_pixels: int
    component_count_before: int
    component_count_after: int


def _component_count(mask: np.ndarray) -> int:
    count, _labels = cv2.connectedComponents(
        np.where(mask > 0, 255, 0).astype(np.uint8),
        connectivity=8,
    )
    return max(0, int(count) - 1)


def evaluate_structural_bridge(
    *,
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    start: tuple[float, float],
    end: tuple[float, float],
    source_foreground: np.ndarray,
    protected_mask: np.ndarray | None,
) -> ConnectivityDecision:
    """Judge a bridge by connected components without changing object ownership."""

    if not roi.contains(start) or not roi.contains(end):
        return ConnectivityDecision(
            False,
            "outside_structural_roi",
            roi.roi_id,
            0,
            0,
            0,
        )
    if segment_length(start, end) <= 0.0:
        return ConnectivityDecision(
            False,
            "empty_bridge",
            roi.roi_id,
            0,
            0,
            0,
        )
    if source_foreground.ndim != 2 or source_foreground.dtype != np.uint8:
        raise ValueError("Connectivity source must be an 8-bit 2D mask")
    if protected_mask is not None and protected_mask.shape != source_foreground.shape:
        raise ValueError("Protected mask must match the connectivity source")

    structural = rasterize_structural_lines(
        lines,
        roi.line_indices,
        image_shape=source_foreground.shape,
    )
    bridge = np.zeros_like(source_foreground)
    line_widths = [max(1.0, float(lines[index].width)) for index in roi.line_indices]
    thickness = max(1, int(round(float(np.median(line_widths)))))
    cv2.line(
        bridge,
        (int(round(start[0])), int(round(start[1]))),
        (int(round(end[0])), int(round(end[1]))),
        255,
        thickness,
        cv2.LINE_8,
    )
    bridge_pixels = int(cv2.countNonZero(bridge))
    if protected_mask is not None and np.any(
        (bridge > 0) & (protected_mask > 0)
    ):
        return ConnectivityDecision(
            False,
            "protected_object_crossing",
            roi.roi_id,
            bridge_pixels,
            _component_count(structural),
            _component_count(structural),
        )

    non_structural_ink = (
        (source_foreground > 0)
        & (structural == 0)
        & (bridge > 0)
    )
    if np.any(non_structural_ink):
        return ConnectivityDecision(
            False,
            "non_structural_component_merge",
            roi.roi_id,
            bridge_pixels,
            _component_count(structural),
            _component_count(structural),
        )

    before = _component_count(structural)
    after = _component_count(cv2.max(structural, bridge))
    if before > 0 and after < before - 1:
        return ConnectivityDecision(
            False,
            "multiple_component_merge",
            roi.roi_id,
            bridge_pixels,
            before,
            after,
        )
    return ConnectivityDecision(
        True,
        "structural_bridge_allowed",
        roi.roi_id,
        bridge_pixels,
        before,
        after,
    )
