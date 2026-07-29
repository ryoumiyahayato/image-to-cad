from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from .line_detect import LineSegment
from .structural_roi import (
    StructuralRoi,
    rasterize_structural_roi_corridor_crop,
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


@dataclass(frozen=True)
class StructuralConnectivityContext:
    roi_id: str
    roi_bbox: tuple[int, int, int, int]
    page_shape: tuple[int, int]
    left: int
    top: int
    structural: np.ndarray
    structural_labels: np.ndarray
    repair_corridor: np.ndarray
    source_foreground: np.ndarray
    protected_mask: np.ndarray | None
    non_structural_protection: np.ndarray
    thickness: int
    component_count_before: int


def _roi_crop(
    roi: StructuralRoi,
    page_shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    page_height, page_width = page_shape
    x, y, width, height = roi.bbox
    left = max(0, int(x))
    top = max(0, int(y))
    right = min(page_width, int(x + width))
    bottom = min(page_height, int(y + height))
    if right <= left or bottom <= top:
        raise ValueError("Structural ROI does not overlap the connectivity source")
    return left, top, right, bottom


def _rasterize_roi_lines(
    lines: Sequence[LineSegment],
    line_indices: Sequence[int],
    *,
    left: int,
    top: int,
    shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for index in line_indices:
        line = lines[int(index)]
        cv2.line(
            mask,
            (
                int(round(line.x1)) - left,
                int(round(line.y1)) - top,
            ),
            (
                int(round(line.x2)) - left,
                int(round(line.y2)) - top,
            ),
            255,
            max(1, int(round(float(line.width)))),
            cv2.LINE_8,
        )
    return mask


def build_structural_connectivity_context(
    *,
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    source_foreground: np.ndarray,
    protected_mask: np.ndarray | None,
) -> StructuralConnectivityContext:
    """Freeze the source-only ROI state reused by every candidate bridge."""

    if source_foreground.ndim != 2 or source_foreground.dtype != np.uint8:
        raise ValueError("Connectivity source must be an 8-bit 2D mask")
    if protected_mask is not None and protected_mask.shape != source_foreground.shape:
        raise ValueError("Protected mask must match the connectivity source")
    left, top, right, bottom = _roi_crop(roi, source_foreground.shape)
    local_shape = (bottom - top, right - left)
    structural = _rasterize_roi_lines(
        lines,
        roi.line_indices,
        left=left,
        top=top,
        shape=local_shape,
    )
    corridor_left, corridor_top, repair_corridor = (
        rasterize_structural_roi_corridor_crop(
            roi,
            lines,
            image_shape=source_foreground.shape,
        )
    )
    if (
        corridor_left != left
        or corridor_top != top
        or repair_corridor.shape != local_shape
    ):
        raise AssertionError("Structural ROI corridor crop is inconsistent")
    component_count, structural_labels = cv2.connectedComponents(
        np.ascontiguousarray(structural, dtype=np.uint8),
        connectivity=8,
    )
    line_widths = [
        max(1.0, float(lines[index].width))
        for index in roi.line_indices
    ]
    source_crop = source_foreground[top:bottom, left:right]
    non_structural_protection = np.where(
        (source_crop > 0) & (structural == 0),
        255,
        0,
    ).astype(np.uint8)
    return StructuralConnectivityContext(
        roi_id=roi.roi_id,
        roi_bbox=roi.bbox,
        page_shape=source_foreground.shape,
        left=left,
        top=top,
        structural=structural,
        structural_labels=structural_labels,
        repair_corridor=repair_corridor,
        source_foreground=source_crop,
        protected_mask=(
            None
            if protected_mask is None
            else protected_mask[top:bottom, left:right]
        ),
        non_structural_protection=non_structural_protection,
        thickness=max(1, int(round(float(np.median(line_widths))))),
        component_count_before=max(0, int(component_count) - 1),
    )


def evaluate_structural_bridge(
    *,
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    start: tuple[float, float],
    end: tuple[float, float],
    source_foreground: np.ndarray,
    protected_mask: np.ndarray | None,
    context: StructuralConnectivityContext | None = None,
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
    if context is None:
        context = build_structural_connectivity_context(
            roi=roi,
            lines=lines,
            source_foreground=source_foreground,
            protected_mask=protected_mask,
        )
    elif (
        context.roi_id != roi.roi_id
        or context.roi_bbox != roi.bbox
        or context.page_shape != source_foreground.shape
    ):
        raise ValueError("Connectivity context does not match the structural ROI")

    start_x = int(round(start[0])) - context.left
    start_y = int(round(start[1])) - context.top
    end_x = int(round(end[0])) - context.left
    end_y = int(round(end[1])) - context.top
    padding = max(1, (context.thickness + 1) // 2 + 1)
    local_height, local_width = context.structural.shape
    crop_left = max(0, min(start_x, end_x) - padding)
    crop_top = max(0, min(start_y, end_y) - padding)
    crop_right = min(local_width, max(start_x, end_x) + padding + 1)
    crop_bottom = min(local_height, max(start_y, end_y) + padding + 1)
    if crop_right <= crop_left or crop_bottom <= crop_top:
        return ConnectivityDecision(
            False,
            "outside_structural_roi",
            roi.roi_id,
            0,
            context.component_count_before,
            context.component_count_before,
        )
    bridge = np.zeros(
        (crop_bottom - crop_top, crop_right - crop_left),
        dtype=np.uint8,
    )
    cv2.line(
        bridge,
        (
            start_x - crop_left,
            start_y - crop_top,
        ),
        (
            end_x - crop_left,
            end_y - crop_top,
        ),
        255,
        context.thickness,
        cv2.LINE_8,
    )
    bridge_pixels = int(cv2.countNonZero(bridge))
    corridor_crop = context.repair_corridor[
        crop_top:crop_bottom,
        crop_left:crop_right,
    ]
    if np.any((bridge > 0) & (corridor_crop == 0)):
        return ConnectivityDecision(
            False,
            "outside_structural_corridor",
            roi.roi_id,
            bridge_pixels,
            context.component_count_before,
            context.component_count_before,
        )
    protected_crop = (
        None
        if context.protected_mask is None
        else context.protected_mask[
            crop_top:crop_bottom,
            crop_left:crop_right,
        ]
    )
    if protected_crop is not None and np.any(
        (bridge > 0) & (protected_crop > 0)
    ):
        return ConnectivityDecision(
            False,
            "protected_object_crossing",
            roi.roi_id,
            bridge_pixels,
            context.component_count_before,
            context.component_count_before,
        )

    non_structural_crop = context.non_structural_protection[
        crop_top:crop_bottom,
        crop_left:crop_right,
    ]
    if np.any((bridge > 0) & (non_structural_crop > 0)):
        return ConnectivityDecision(
            False,
            "non_structural_component_merge",
            roi.roi_id,
            bridge_pixels,
            context.component_count_before,
            context.component_count_before,
        )

    before = context.component_count_before
    label_crop = context.structural_labels[
        crop_top:crop_bottom,
        crop_left:crop_right,
    ]
    touched = np.unique(label_crop[bridge > 0])
    touched_components = int(np.count_nonzero(touched > 0))
    after = (
        before + 1
        if touched_components == 0 and bridge_pixels > 0
        else before - max(0, touched_components - 1)
    )
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
