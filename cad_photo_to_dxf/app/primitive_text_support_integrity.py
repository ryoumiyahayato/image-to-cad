"""DEV-only text/glyph support integrity for straight-line primitives.

The production pipeline already has a conservative text-protection pass.  The
offline continuation-candidate miner historically bypassed it and admitted raw
Hough segments after only span and axis checks.  This module reuses the same
deterministic text-region evidence without changing production semantics.

The hard-rejection boundary is intentionally narrow: a primitive is rejected
only when its source support is substantially text-owned and credible support
does not survive text-mask subtraction.  Text proximity or overlap alone is
never a rejection signal.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

import cv2
import numpy as np

from .line_detect import LineSegment
from .resolution import image_resolution_scale, scaled_int
from .text_protection import TextProtectionResult, detect_text_region_mask


class TextSupportStatus(str, Enum):
    INDEPENDENT = "TEXT_INDEPENDENT"
    UNCERTAIN = "TEXT_UNCERTAIN"
    REJECTED = "TEXT_REJECTED"


TEXT_ADJACENT = "TEXT_ADJACENT"
INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT = "INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT"
INSUFFICIENT_TEXT_MASK_EVIDENCE = "INSUFFICIENT_TEXT_MASK_EVIDENCE"
TEXT_CONTAMINATED_SUPPORT = "TEXT_CONTAMINATED_SUPPORT"
GLYPH_ONLY_SUPPORT = "GLYPH_ONLY_SUPPORT"
TEXT_DOMINATED_SUPPORT = "TEXT_DOMINATED_SUPPORT"
TEXT_COMPONENT_CHAIN = "TEXT_COMPONENT_CHAIN"
NO_NON_TEXT_AXIS_SUPPORT = "NO_NON_TEXT_AXIS_SUPPORT"


@dataclass(frozen=True)
class TextSupportDecision:
    status: TextSupportStatus
    reason: str
    text_mask_overlap_fraction: float
    source_support_fraction: float
    text_owned_support_fraction: float
    non_text_support_fraction: float
    post_text_removal_support_fraction: float
    longest_non_text_supported_run_px: float
    text_component_count: int
    support_run_count: int
    non_text_support_run_count: int
    endpoint_non_text_support: tuple[bool, bool]
    structural_connection_count: int
    text_region_count: int
    evidence_source: str = "existing_text_protection_mask_plus_component_ink"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "text_mask_overlap_fraction": round(self.text_mask_overlap_fraction, 6),
            "source_support_fraction": round(self.source_support_fraction, 6),
            "text_owned_support_fraction": round(self.text_owned_support_fraction, 6),
            "non_text_support_fraction": round(self.non_text_support_fraction, 6),
            "post_text_removal_support_fraction": round(
                self.post_text_removal_support_fraction, 6
            ),
            "longest_non_text_supported_run_px": round(
                self.longest_non_text_supported_run_px, 3
            ),
            "text_component_count": self.text_component_count,
            "support_run_count": self.support_run_count,
            "non_text_support_run_count": self.non_text_support_run_count,
            "endpoint_non_text_support": list(self.endpoint_non_text_support),
            "structural_connection_count": self.structural_connection_count,
            "text_region_count": self.text_region_count,
            "evidence_source": self.evidence_source,
        }


def _as_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim != 2 or image.size == 0 or image.dtype != np.uint8:
        raise ValueError("Text support integrity requires a non-empty uint8 image")
    return image


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("primitive points require two coordinates")
    return float(value[0]), float(value[1])


def _geometry(value: LineSegment | Mapping[str, Any]) -> tuple[tuple[float, float], tuple[float, float], float]:
    if isinstance(value, LineSegment):
        return (value.x1, value.y1), (value.x2, value.y2), max(1.0, float(value.width))
    start = _point(value["start"])
    end = _point(value["end"])
    return start, end, max(1.0, float(value.get("width", 1.0)))


def count_structural_connections(
    image_shape: tuple[int, ...],
    primitive: LineSegment | Mapping[str, Any],
    context_primitives: Sequence[LineSegment | Mapping[str, Any]],
) -> int:
    """Count distinct sufficiently long perpendicular rule crossings."""

    start, end, _width = _geometry(primitive)
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx <= dy * 0.08:
        orientation = "vertical"
        axis = (start[0] + end[0]) * 0.5
        lower, upper = sorted((start[1], end[1]))
    elif dy <= dx * 0.08:
        orientation = "horizontal"
        axis = (start[1] + end[1]) * 0.5
        lower, upper = sorted((start[0], end[0]))
    else:
        return 0
    scale = image_resolution_scale(image_shape)
    tolerance = max(3.0, 3.0 * scale)
    network_minimum = max(42.0 * scale, math.hypot(*image_shape[:2]) * 0.012)
    if math.dist(start, end) < network_minimum:
        return 0
    positions: list[float] = []
    for other in context_primitives:
        other_start, other_end, _ = _geometry(other)
        odx = abs(other_end[0] - other_start[0])
        ody = abs(other_end[1] - other_start[1])
        if math.dist(other_start, other_end) < network_minimum:
            continue
        if orientation == "vertical" and ody <= odx * 0.08:
            other_axis = (other_start[1] + other_end[1]) * 0.5
            left, right = sorted((other_start[0], other_end[0]))
            if left - tolerance <= axis <= right + tolerance and lower - tolerance <= other_axis <= upper + tolerance:
                positions.append(other_axis)
        elif orientation == "horizontal" and odx <= ody * 0.08:
            other_axis = (other_start[0] + other_end[0]) * 0.5
            top, bottom = sorted((other_start[1], other_end[1]))
            if top - tolerance <= axis <= bottom + tolerance and lower - tolerance <= other_axis <= upper + tolerance:
                positions.append(other_axis)
    distinct: list[float] = []
    for position in sorted(positions):
        if not distinct or position - distinct[-1] > tolerance:
            distinct.append(position)
    return len(distinct)


def _runs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    padded = np.concatenate(([False], values.astype(bool), [False]))
    starts = np.flatnonzero(padded[1:] & ~padded[:-1])
    ends = np.flatnonzero(~padded[1:] & padded[:-1])
    return starts, ends


def _sample_corridor(
    gray: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    half_width: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    length = math.dist(start, end)
    sample_count = max(2, min(4096, math.ceil(length) + 1))
    xs = np.linspace(start[0], end[0], sample_count)
    ys = np.linspace(start[1], end[1], sample_count)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    norm = max(math.hypot(dx, dy), 1e-9)
    normal_x = -dy / norm
    normal_y = dx / norm
    support = np.zeros(sample_count, dtype=bool)
    support_x = np.rint(xs).astype(int)
    support_y = np.rint(ys).astype(int)
    best_distance = np.full(sample_count, np.inf)
    for offset in range(-half_width, half_width + 1):
        xi = np.clip(np.rint(xs + normal_x * offset).astype(int), 0, gray.shape[1] - 1)
        yi = np.clip(np.rint(ys + normal_y * offset).astype(int), 0, gray.shape[0] - 1)
        dark = gray[yi, xi] < 220
        distance = np.abs(offset)
        replace = dark & (distance < best_distance)
        support_x[replace] = xi[replace]
        support_y[replace] = yi[replace]
        best_distance[replace] = distance
        support |= dark
    axis_x = np.clip(np.rint(xs).astype(int), 0, gray.shape[1] - 1)
    axis_y = np.clip(np.rint(ys).astype(int), 0, gray.shape[0] - 1)
    return support, support_x, support_y, np.stack((axis_x, axis_y), axis=1)


def _text_component_count(
    glyph_owned_mask: np.ndarray,
    support: np.ndarray,
    support_x: np.ndarray,
    support_y: np.ndarray,
) -> int:
    count, labels = cv2.connectedComponents(glyph_owned_mask, connectivity=8)
    if count <= 1:
        return 0
    values = labels[support_y[support], support_x[support]]
    return len({int(value) for value in values if int(value) > 0})


def build_dev_glyph_owned_mask(
    gray: np.ndarray,
    protection: TextProtectionResult,
) -> np.ndarray:
    """Recover component ink supporting the coarse text-region evidence.

    The existing production mask is deliberately a padded region rectangle.
    Treating every source pixel inside that rectangle as text would erase real
    table borders and lines passing through labels.  The DEV guard therefore
    intersects it with the same bounded connected-component family used by the
    detector, while leaving larger structural networks independent.
    """

    scale = image_resolution_scale(gray.shape)
    foreground = np.where(gray < 220, 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    min_height = scaled_int(2, scale, minimum=2)
    max_height = scaled_int(120, scale, minimum=24)
    max_width = scaled_int(180, scale, minimum=32)
    min_area = max(4, round(5.0 * scale * scale))
    max_area = max(320, round(12000.0 * scale * scale))
    owned = np.zeros_like(gray)
    for label in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label])
        if not (min_height <= height <= max_height):
            continue
        if not (1 <= width <= max_width and min_area <= area <= max_area):
            continue
        fill_ratio = area / max(float(width * height), 1.0)
        aspect = width / max(float(height), 1.0)
        if not (0.015 <= fill_ratio <= 1.0 and 0.015 <= aspect <= 80.0):
            continue
        labels_crop = labels[y : y + height, x : x + width]
        region_crop = protection.mask[y : y + height, x : x + width] > 0
        component_crop = labels_crop == label
        owned_crop = component_crop & region_crop
        if np.any(owned_crop):
            target = owned[y : y + height, x : x + width]
            target[owned_crop] = 255
    return owned


def assess_primitive_text_support(
    image: np.ndarray,
    primitive: LineSegment | Mapping[str, Any],
    *,
    protection: TextProtectionResult | None = None,
    glyph_owned_mask: np.ndarray | None = None,
    structural_connection_count: int = 0,
) -> TextSupportDecision:
    """Measure whether a straight primitive has support independent of text.

    ``post_text_removal_support_fraction`` is the fraction of originally
    supported axial samples that remain supported outside the existing text
    mask.  A real line crossing a label therefore retains long source-backed
    runs, while a glyph-only fit does not.
    """

    gray = _as_gray(image)
    start, end, width = _geometry(primitive)
    length = math.dist(start, end)
    if length <= 0:
        raise ValueError("primitive must have positive length")
    protection = protection or detect_text_region_mask(gray)
    if protection.mask.shape != gray.shape:
        raise ValueError("text mask shape must match source image")
    scale = image_resolution_scale(gray.shape)
    corridor = max(1, scaled_int(2.0, scale, minimum=1), math.ceil(width * 0.75))
    support, support_x, support_y, axis = _sample_corridor(
        gray, start, end, half_width=corridor
    )
    glyph_owned_mask = (
        build_dev_glyph_owned_mask(gray, protection)
        if glyph_owned_mask is None
        else glyph_owned_mask
    )
    if glyph_owned_mask.shape != gray.shape:
        raise ValueError("glyph-owned mask shape must match source image")
    axis_inside_text = protection.mask[axis[:, 1], axis[:, 0]] > 0
    support_inside_text = support & (glyph_owned_mask[support_y, support_x] > 0)
    non_text_support = support & ~support_inside_text
    support_count = int(np.count_nonzero(support))
    non_text_count = int(np.count_nonzero(non_text_support))
    source_support_fraction = support_count / float(support.size)
    text_owned_support_fraction = (
        int(np.count_nonzero(support_inside_text)) / float(max(support_count, 1))
    )
    non_text_support_fraction = non_text_count / float(support.size)
    post_text = non_text_count / float(max(support_count, 1))
    starts, ends = _runs(non_text_support)
    run_lengths = ends - starts
    sample_step = length / max(float(support.size - 1), 1.0)
    longest_non_text = (
        float(np.max(run_lengths)) * sample_step if run_lengths.size else 0.0
    )
    support_starts, _support_ends = _runs(support)
    endpoint_window = max(2, round(support.size * 0.15))
    endpoints = (
        bool(np.mean(non_text_support[:endpoint_window]) >= 0.55),
        bool(np.mean(non_text_support[-endpoint_window:]) >= 0.55),
    )
    component_count = _text_component_count(
        glyph_owned_mask, support_inside_text, support_x, support_y
    )
    overlap = float(np.mean(axis_inside_text))
    credible_run = max(12.0 * scale, 3.0 * width, length * 0.18)
    independent = bool(
        post_text >= 0.34
        and longest_non_text >= credible_run
        and (any(endpoints) or non_text_support_fraction >= 0.45)
    )

    structural_network = bool(
        structural_connection_count >= 2 and source_support_fraction >= 0.75
    )
    if structural_network:
        status = TextSupportStatus.INDEPENDENT
        reason = INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT
    elif protection.text_region_count == 0 or overlap < 0.10:
        status = TextSupportStatus.INDEPENDENT
        reason = TEXT_ADJACENT
    elif independent:
        status = TextSupportStatus.INDEPENDENT
        reason = INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT
    else:
        no_independent_axis = bool(
            post_text <= 0.12 and longest_non_text < max(6.0 * scale, length * 0.10)
        )
        component_chain = bool(
            component_count >= 3
            and text_owned_support_fraction >= 0.62
            and post_text <= 0.24
            and not any(endpoints)
        )
        compact_text_owned = bool(
            overlap >= 0.72
            and text_owned_support_fraction >= 0.72
            and post_text <= 0.20
            and length <= max(180.0 * scale, math.hypot(*gray.shape) * 0.09)
        )
        if (
            no_independent_axis
            and text_owned_support_fraction >= 0.78
            and component_count >= 3
        ):
            status = TextSupportStatus.REJECTED
            reason = GLYPH_ONLY_SUPPORT
        elif component_chain:
            status = TextSupportStatus.REJECTED
            reason = TEXT_COMPONENT_CHAIN
        elif compact_text_owned and component_count >= 3:
            status = TextSupportStatus.REJECTED
            reason = TEXT_DOMINATED_SUPPORT
        else:
            status = TextSupportStatus.UNCERTAIN
            reason = (
                TEXT_CONTAMINATED_SUPPORT
                if protection.text_region_count
                else INSUFFICIENT_TEXT_MASK_EVIDENCE
            )
    if status is TextSupportStatus.REJECTED and non_text_count == 0:
        reason = GLYPH_ONLY_SUPPORT
    elif status is TextSupportStatus.REJECTED and longest_non_text == 0:
        reason = NO_NON_TEXT_AXIS_SUPPORT

    return TextSupportDecision(
        status=status,
        reason=reason,
        text_mask_overlap_fraction=overlap,
        source_support_fraction=source_support_fraction,
        text_owned_support_fraction=text_owned_support_fraction,
        non_text_support_fraction=non_text_support_fraction,
        post_text_removal_support_fraction=post_text,
        longest_non_text_supported_run_px=longest_non_text,
        text_component_count=component_count,
        support_run_count=len(support_starts),
        non_text_support_run_count=len(starts),
        endpoint_non_text_support=endpoints,
        structural_connection_count=structural_connection_count,
        text_region_count=protection.text_region_count,
    )


def qualify_dev_text_support_primitives(
    image: np.ndarray,
    records: Sequence[Mapping[str, Any]],
    *,
    protection: TextProtectionResult | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Partition DEV primitive records without upgrading prior rejections."""

    gray = _as_gray(image)
    protection = protection or detect_text_region_mask(gray)
    glyph_owned_mask = build_dev_glyph_owned_mask(gray, protection)
    context = [record["raw_geometry"] for record in records]
    buckets: dict[str, list[dict[str, Any]]] = {
        "independent": [],
        "uncertain": [],
        "rejected": [],
    }
    for source in records:
        record = dict(source)
        decision = assess_primitive_text_support(
            gray,
            record["raw_geometry"],
            protection=protection,
            glyph_owned_mask=glyph_owned_mask,
            structural_connection_count=count_structural_connections(
                gray.shape,
                record["raw_geometry"],
                context,
            ),
        )
        record["text_support_integrity"] = decision.to_dict()
        if decision.status is TextSupportStatus.INDEPENDENT:
            buckets["independent"].append(record)
        elif decision.status is TextSupportStatus.UNCERTAIN:
            buckets["uncertain"].append(record)
        else:
            buckets["rejected"].append(record)
    return buckets


__all__ = [
    "GLYPH_ONLY_SUPPORT",
    "INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT",
    "INSUFFICIENT_TEXT_MASK_EVIDENCE",
    "NO_NON_TEXT_AXIS_SUPPORT",
    "TEXT_ADJACENT",
    "TEXT_COMPONENT_CHAIN",
    "TEXT_CONTAMINATED_SUPPORT",
    "TEXT_DOMINATED_SUPPORT",
    "TextSupportDecision",
    "TextSupportStatus",
    "assess_primitive_text_support",
    "build_dev_glyph_owned_mask",
    "count_structural_connections",
    "qualify_dev_text_support_primitives",
]
