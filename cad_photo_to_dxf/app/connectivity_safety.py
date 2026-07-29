from __future__ import annotations

from dataclasses import dataclass, field
from math import acos, degrees, hypot, isfinite
from typing import Sequence

import cv2
import numpy as np

from .line_detect import LineSegment
from .structural_roi import (
    StructuralRoi,
    rasterize_structural_roi_corridor_crop,
    segment_length,
)

CONNECTION_CONFIDENCE_THRESHOLD = 0.95
MAX_DIRECTION_ERROR_DEGREES = 1.0
MAX_LINE_WIDTH_DIFFERENCE_MM = 0.35
DEFAULT_CONNECTION_DPI = 300.0


def pixels_to_millimetres(pixels: float, dpi: float) -> float:
    normalized_dpi = float(dpi)
    if not isfinite(normalized_dpi) or normalized_dpi <= 0.0:
        raise ValueError("Connection DPI must be a positive finite number")
    return float(pixels) * 25.4 / normalized_dpi


def millimetres_to_pixels(millimetres: float, dpi: float) -> float:
    normalized_mm = float(millimetres)
    if not isfinite(normalized_mm) or normalized_mm < 0.0:
        raise ValueError(
            "Connection distance must be a non-negative finite value"
        )
    normalized_dpi = float(dpi)
    if not isfinite(normalized_dpi) or normalized_dpi <= 0.0:
        raise ValueError("Connection DPI must be a positive finite number")
    return normalized_mm * normalized_dpi / 25.4


@dataclass(frozen=True)
class ConnectivityEvidence:
    source_line_index: int = -1
    target_line_index: int = -1
    direction_error_degrees: float = 180.0
    maximum_direction_error_degrees: float = MAX_DIRECTION_ERROR_DEGREES
    source_line_width_mm: float = 0.0
    target_line_width_mm: float = 0.0
    line_width_difference_mm: float = 0.0
    maximum_line_width_difference_mm: float = MAX_LINE_WIDTH_DIFFERENCE_MM
    start_source_supported: bool = False
    peer_source_supported: bool = False
    gap_length_mm: float = 0.0
    minimum_resolvable_gap_mm: float = 0.0
    maximum_gap_mm: float = 0.0
    source_dpi: float = DEFAULT_CONNECTION_DPI
    same_structural_network: bool = False
    corridor_contained: bool = False
    protection_clear: bool = False
    non_structural_ink_clear: bool = False
    topology_compatible: bool = False
    checks: tuple[tuple[str, bool], ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "source_line_index": int(self.source_line_index),
            "target_line_index": int(self.target_line_index),
            "direction_error_degrees": float(
                self.direction_error_degrees
            ),
            "maximum_direction_error_degrees": float(
                self.maximum_direction_error_degrees
            ),
            "source_line_width_mm": float(self.source_line_width_mm),
            "target_line_width_mm": float(self.target_line_width_mm),
            "line_width_difference_mm": float(
                self.line_width_difference_mm
            ),
            "maximum_line_width_difference_mm": float(
                self.maximum_line_width_difference_mm
            ),
            "start_source_supported": bool(
                self.start_source_supported
            ),
            "peer_source_supported": bool(self.peer_source_supported),
            "gap_length_mm": float(self.gap_length_mm),
            "minimum_resolvable_gap_mm": float(
                self.minimum_resolvable_gap_mm
            ),
            "maximum_gap_mm": float(self.maximum_gap_mm),
            "source_dpi": float(self.source_dpi),
            "same_structural_network": bool(
                self.same_structural_network
            ),
            "corridor_contained": bool(self.corridor_contained),
            "protection_clear": bool(self.protection_clear),
            "non_structural_ink_clear": bool(
                self.non_structural_ink_clear
            ),
            "topology_compatible": bool(self.topology_compatible),
            "checks": {
                name: bool(passed) for name, passed in self.checks
            },
        }


@dataclass(frozen=True)
class ConnectivityDecision:
    allowed: bool
    reason_code: str
    roi_id: str
    bridge_pixels: int
    component_count_before: int
    component_count_after: int
    confidence: float = 0.0
    confidence_threshold: float = CONNECTION_CONFIDENCE_THRESHOLD
    evidence: ConnectivityEvidence = field(
        default_factory=ConnectivityEvidence
    )


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


def _point_has_source_support(
    source_foreground: np.ndarray,
    point: tuple[float, float],
    *,
    radius: int,
) -> bool:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    height, width = source_foreground.shape
    left = max(0, x - radius)
    top = max(0, y - radius)
    right = min(width, x + radius + 1)
    bottom = min(height, y + radius + 1)
    return bool(
        right > left
        and bottom > top
        and np.any(source_foreground[top:bottom, left:right] > 0)
    )


def _direction_error_degrees(
    source_line: LineSegment,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    source_x = float(source_line.x2) - float(source_line.x1)
    source_y = float(source_line.y2) - float(source_line.y1)
    bridge_x = float(end[0]) - float(start[0])
    bridge_y = float(end[1]) - float(start[1])
    source_length = hypot(source_x, source_y)
    bridge_length = hypot(bridge_x, bridge_y)
    if source_length <= 1e-9 or bridge_length <= 1e-9:
        return 180.0
    cosine = abs(
        (source_x * bridge_x + source_y * bridge_y)
        / (source_length * bridge_length)
    )
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def evaluate_structural_bridge(
    *,
    roi: StructuralRoi,
    lines: Sequence[LineSegment],
    source_line_index: int | None = None,
    target_line_index: int | None = None,
    start: tuple[float, float],
    end: tuple[float, float],
    peer_source_point: tuple[float, float] | None = None,
    maximum_gap: float | None = None,
    source_dpi: float = DEFAULT_CONNECTION_DPI,
    source_foreground: np.ndarray,
    protected_mask: np.ndarray | None,
    context: StructuralConnectivityContext | None = None,
) -> ConnectivityDecision:
    """Apply all conservative structural-connection gates in one place."""

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
    if (
        source_line_index is None
        or target_line_index is None
        or not 0 <= int(source_line_index) < len(lines)
        or not 0 <= int(target_line_index) < len(lines)
    ):
        return ConnectivityDecision(
            False,
            "missing_line_evidence",
            roi.roi_id,
            0,
            0,
            0,
        )
    normalized_source_index = int(source_line_index)
    normalized_target_index = int(target_line_index)
    source_line = lines[normalized_source_index]
    target_line = lines[normalized_target_index]
    normalized_dpi = float(source_dpi)
    if not isfinite(normalized_dpi) or normalized_dpi <= 0.0:
        return ConnectivityDecision(
            False,
            "missing_physical_scale",
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
    corridor_contained = not bool(
        np.any((bridge > 0) & (corridor_crop == 0))
    )
    protected_crop = (
        None
        if context.protected_mask is None
        else context.protected_mask[
            crop_top:crop_bottom,
            crop_left:crop_right,
        ]
    )
    protection_clear = bool(
        protected_crop is None
        or not np.any((bridge > 0) & (protected_crop > 0))
    )

    non_structural_crop = context.non_structural_protection[
        crop_top:crop_bottom,
        crop_left:crop_right,
    ]
    non_structural_ink_clear = not bool(
        np.any((bridge > 0) & (non_structural_crop > 0))
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
    topology_compatible = bool(
        touched_components > 0
        and not (before > 0 and after < before - 1)
    )

    gap_pixels = segment_length(start, end)
    maximum_gap_pixels = (
        gap_pixels if maximum_gap is None else float(maximum_gap)
    )
    direction_error = _direction_error_degrees(
        source_line,
        start,
        end,
    )
    source_width_mm = pixels_to_millimetres(
        max(1.0, float(source_line.width)),
        normalized_dpi,
    )
    target_width_mm = pixels_to_millimetres(
        max(1.0, float(target_line.width)),
        normalized_dpi,
    )
    width_difference_mm = abs(source_width_mm - target_width_mm)
    gap_length_mm = pixels_to_millimetres(gap_pixels, normalized_dpi)
    minimum_resolvable_gap_mm = (
        max(source_width_mm, target_width_mm)
        + pixels_to_millimetres(1.0, normalized_dpi)
    )
    support_radius = max(1, (context.thickness + 1) // 2)
    start_source_supported = _point_has_source_support(
        source_foreground,
        start,
        radius=support_radius,
    )
    peer_source_supported = _point_has_source_support(
        source_foreground,
        end if peer_source_point is None else peer_source_point,
        radius=support_radius,
    )
    same_structural_network = bool(
        normalized_source_index in roi.line_indices
        and normalized_target_index in roi.line_indices
    )
    checks = (
        (
            "direction_aligned",
            direction_error <= MAX_DIRECTION_ERROR_DEGREES,
        ),
        (
            "line_width_compatible",
            width_difference_mm <= MAX_LINE_WIDTH_DIFFERENCE_MM,
        ),
        (
            "gap_within_physical_budget",
            isfinite(maximum_gap_pixels)
            and maximum_gap_pixels > 0.0
            and gap_pixels <= maximum_gap_pixels + 1e-6,
        ),
        (
            "gap_has_resolvable_separation",
            gap_length_mm + 1e-6 >= minimum_resolvable_gap_mm,
        ),
        ("same_structural_network", same_structural_network),
        ("corridor_contained", corridor_contained),
        ("protection_clear", protection_clear),
        ("non_structural_ink_clear", non_structural_ink_clear),
        ("start_source_supported", start_source_supported),
        ("peer_source_supported", peer_source_supported),
        ("topology_compatible", topology_compatible),
    )
    confidence = sum(int(passed) for _name, passed in checks) / len(checks)
    evidence = ConnectivityEvidence(
        source_line_index=normalized_source_index,
        target_line_index=normalized_target_index,
        direction_error_degrees=direction_error,
        source_line_width_mm=source_width_mm,
        target_line_width_mm=target_width_mm,
        line_width_difference_mm=width_difference_mm,
        start_source_supported=start_source_supported,
        peer_source_supported=peer_source_supported,
        gap_length_mm=gap_length_mm,
        minimum_resolvable_gap_mm=minimum_resolvable_gap_mm,
        maximum_gap_mm=pixels_to_millimetres(
            maximum_gap_pixels,
            normalized_dpi,
        ),
        source_dpi=normalized_dpi,
        same_structural_network=same_structural_network,
        corridor_contained=corridor_contained,
        protection_clear=protection_clear,
        non_structural_ink_clear=non_structural_ink_clear,
        topology_compatible=topology_compatible,
        checks=checks,
    )
    reason_by_check = {
        "direction_aligned": "direction_mismatch",
        "line_width_compatible": "line_width_mismatch",
        "start_source_supported": "missing_start_pixel_support",
        "peer_source_supported": "missing_peer_pixel_support",
        "gap_within_physical_budget": "physical_gap_limit",
        "gap_has_resolvable_separation": "unresolved_structural_gap",
        "same_structural_network": "different_structural_network",
        "corridor_contained": "outside_structural_corridor",
        "protection_clear": "protected_object_crossing",
        "non_structural_ink_clear": "non_structural_component_merge",
        "topology_compatible": "incompatible_topology",
    }
    failed_check = next(
        (name for name, passed in checks if not passed),
        None,
    )
    allowed = bool(
        failed_check is None
        and confidence > CONNECTION_CONFIDENCE_THRESHOLD
    )
    return ConnectivityDecision(
        allowed,
        (
            "structural_bridge_allowed"
            if allowed
            else reason_by_check.get(
                str(failed_check),
                "connection_confidence_below_threshold",
            )
        ),
        roi.roi_id,
        bridge_pixels,
        before,
        after,
        confidence=confidence,
        evidence=evidence,
    )
