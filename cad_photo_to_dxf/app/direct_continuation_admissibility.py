"""Conservative source-evidence gate for direct-continuation proposals.

This module is deliberately geometry preserving.  It qualifies an existing
fragment pair for DEV/dataset-mining use; it never creates, extends, snaps, or
otherwise mutates line geometry.  Semantic class and candidate identity are
not inputs to the decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


class DirectContinuationStatus(str, Enum):
    ADMISSIBLE = "DIRECT_CONTINUATION_ADMISSIBLE"
    REJECTED = "DIRECT_CONTINUATION_REJECTED"
    UNCERTAIN = "DIRECT_CONTINUATION_UNCERTAIN"


class DirectContinuationReason(str, Enum):
    CLEAR_DIRECT_TRAJECTORY = "CLEAR_DIRECT_TRAJECTORY"
    COMPETING_STRUCTURE = "COMPETING_STRUCTURE"
    NODE_OR_COMPONENT_MEDIATED = "NODE_OR_COMPONENT_MEDIATED"
    INTENTIONAL_OPENING_EVIDENCE = "INTENTIONAL_OPENING_EVIDENCE"
    PAIR_OFFSET_INCONSISTENT = "PAIR_OFFSET_INCONSISTENT"
    PARALLEL_COMPETING_EDGE = "PARALLEL_COMPETING_EDGE"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"


@dataclass(frozen=True)
class DirectContinuationEvidence:
    gap_length_px: int
    axis_delta_px: float
    centerline_support_fraction: float
    off_axis_ink_fraction: float
    transverse_crossing_columns: int
    endpoint_boundary_sides: int
    enclosed_contours: int
    volumetric_components: int
    parallel_run_fraction: float
    fragment_a_thickness_px: float
    fragment_b_thickness_px: float
    fragment_thickness_ratio: float


@dataclass(frozen=True)
class DirectContinuationDecision:
    status: DirectContinuationStatus
    reason: DirectContinuationReason
    evidence: DirectContinuationEvidence
    geometry_mutated: bool = False
    semantic_or_model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["reason"] = self.reason.value
        return payload


def _point(value: Sequence[float]) -> tuple[int, int]:
    return int(round(float(value[0]))), int(round(float(value[1])))


def _canonical_image_and_point(
    image: np.ndarray, point: Sequence[float], orientation: str
) -> tuple[np.ndarray, tuple[int, int]]:
    x, y = _point(point)
    if orientation == "horizontal":
        return image, (x, y)
    if orientation == "vertical":
        return image.T, (y, x)
    raise ValueError(f"unsupported orientation: {orientation}")


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    if gray.ndim != 2:
        raise ValueError("admissibility evidence requires one grayscale source image")
    blurred = cv2.GaussianBlur(gray.astype(np.uint8), (3, 3), 0)
    return cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]


def _clip_interval(start: int, end: int, maximum: int) -> tuple[int, int]:
    return max(0, min(start, maximum)), max(0, min(end, maximum))


def _line_thickness(
    ink: np.ndarray, start: tuple[int, int], end: tuple[int, int]
) -> float:
    x0, x1 = sorted((start[0], end[0]))
    length = max(1, x1 - x0)
    sample_start = x0 + max(1, length // 3)
    sample_end = x1 - max(1, length // 8)
    if sample_end <= sample_start:
        sample_start, sample_end = x0, x1
    values: list[int] = []
    for x in np.linspace(sample_start, sample_end, 9):
        xi = min(max(int(round(x)), 0), ink.shape[1] - 1)
        y = int(round(start[1] + (end[1] - start[1]) * ((xi - x0) / length)))
        run = 0
        for offset in range(-8, 9):
            yi = y + offset
            if 0 <= yi < ink.shape[0] and ink[yi, xi]:
                run += 1
        if run:
            values.append(run)
    return round(float(np.median(values)) if values else 0.0, 3)


def _extract_evidence(
    gray: np.ndarray,
    candidate: Mapping[str, Any],
) -> DirectContinuationEvidence:
    orientation = str(candidate["orientation"])
    canonical_gray, gap_a = _canonical_image_and_point(
        gray, candidate["gap_endpoint_a"], orientation
    )
    _, gap_b = _canonical_image_and_point(gray, candidate["gap_endpoint_b"], orientation)
    _, a_start = _canonical_image_and_point(
        gray, candidate["fragment_a_geometry"]["start"], orientation
    )
    _, a_end = _canonical_image_and_point(
        gray, candidate["fragment_a_geometry"]["end"], orientation
    )
    _, b_start = _canonical_image_and_point(
        gray, candidate["fragment_b_geometry"]["start"], orientation
    )
    _, b_end = _canonical_image_and_point(
        gray, candidate["fragment_b_geometry"]["end"], orientation
    )
    ink = _ink_mask(canonical_gray)
    if gap_a[0] > gap_b[0]:
        gap_a, gap_b = gap_b, gap_a
        a_start, a_end, b_start, b_end = b_start, b_end, a_start, a_end
    gap_length = max(1, gap_b[0] - gap_a[0])
    axis = int(round((gap_a[1] + gap_b[1]) / 2))
    # Keep the transverse evidence window proportional to the proposed gap.
    # A fixed wide window makes unrelated dense drawing context look like an
    # intervening component when the actual interruption is only a few pixels.
    half_width = max(6, min(28, int(round(gap_length * 0.65))))
    x0, x1 = _clip_interval(gap_a[0] - 3, gap_b[0] + 4, ink.shape[1])
    y0, y1 = _clip_interval(axis - half_width, axis + half_width + 1, ink.shape[0])
    patch = ink[y0:y1, x0:x1]
    center_y = axis - y0
    center0, center1 = max(0, center_y - 2), min(patch.shape[0], center_y + 3)
    path_x0 = max(0, gap_a[0] - x0)
    path_x1 = min(patch.shape[1], gap_b[0] - x0 + 1)
    center_band = patch[center0:center1, path_x0:path_x1]
    center_support = (
        float(np.mean(np.any(center_band > 0, axis=0)))
        if center_band.size and center_band.shape[1]
        else 0.0
    )
    off_axis = patch.copy()
    off_axis[center0:center1, :] = 0
    off_axis_fraction = float(np.mean(off_axis > 0)) if off_axis.size else 0.0

    crossing_columns = 0
    for local_x in range(path_x0, path_x1):
        above = patch[: max(0, center_y - 3), local_x]
        below = patch[min(patch.shape[0], center_y + 4) :, local_x]
        if np.any(above) and np.any(below):
            crossing_columns += 1

    def endpoint_sides(local_x: int) -> int:
        left = max(0, local_x - 2)
        right = min(patch.shape[1], local_x + 3)
        band = patch[:, left:right]
        above = band[: max(0, center_y - 3), :]
        below = band[min(band.shape[0], center_y + 4) :, :]
        return int(np.any(above)) + int(np.any(below))

    endpoint_boundary_sides = endpoint_sides(path_x0) + endpoint_sides(
        max(path_x0, path_x1 - 1)
    )

    contours, _ = cv2.findContours(patch, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    enclosed = 0
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        area = abs(float(cv2.contourArea(contour)))
        touches_boundary = bx <= 0 or by <= 0 or bx + bw >= patch.shape[1] or by + bh >= patch.shape[0]
        overlaps_path = bx <= path_x1 and bx + bw >= path_x0
        crosses_axis = by <= center_y <= by + bh
        if (
            not touches_boundary
            and overlaps_path
            and crosses_axis
            and bw >= 5
            and bh >= 6
            and area >= 12.0
        ):
            enclosed += 1

    component_count, _, stats, centroids = cv2.connectedComponentsWithStats(
        (patch > 0).astype(np.uint8), 8
    )
    volumetric = 0
    for label in range(1, component_count):
        bx, by, bw, bh, area = (int(value) for value in stats[label])
        cx, cy = centroids[label]
        overlaps_path = bx <= path_x1 and bx + bw >= path_x0
        near_axis = abs(float(cy) - center_y) <= max(4.0, bh / 2)
        axial_density = area / max(1, bw * bh)
        if (
            overlaps_path
            and near_axis
            and bw >= 4
            and bh >= 7
            and area >= 18
            and axial_density >= 0.16
        ):
            volumetric += 1

    parallel_best = 0.0
    for offset in list(range(-half_width + 2, -4)) + list(range(5, half_width - 1)):
        yi = center_y + offset
        if not 0 <= yi < patch.shape[0]:
            continue
        band0, band1 = max(0, yi - 1), min(patch.shape[0], yi + 2)
        coverage = float(
            np.mean(np.any(patch[band0:band1, path_x0:path_x1] > 0, axis=0))
        )
        parallel_best = max(parallel_best, coverage)

    thickness_a = _line_thickness(ink, a_start, a_end)
    thickness_b = _line_thickness(ink, b_start, b_end)
    positive = [value for value in (thickness_a, thickness_b) if value > 0]
    ratio = max(positive) / max(1.0, min(positive)) if len(positive) == 2 else 1.0
    axis_delta = abs(float(a_end[1]) - float(b_start[1]))
    return DirectContinuationEvidence(
        gap_length_px=gap_length,
        axis_delta_px=round(axis_delta, 3),
        centerline_support_fraction=round(center_support, 6),
        off_axis_ink_fraction=round(off_axis_fraction, 6),
        transverse_crossing_columns=crossing_columns,
        endpoint_boundary_sides=endpoint_boundary_sides,
        enclosed_contours=enclosed,
        volumetric_components=volumetric,
        parallel_run_fraction=round(parallel_best, 6),
        fragment_a_thickness_px=thickness_a,
        fragment_b_thickness_px=thickness_b,
        fragment_thickness_ratio=round(ratio, 6),
    )


def assess_direct_continuation(
    gray: np.ndarray, candidate: Mapping[str, Any]
) -> DirectContinuationDecision:
    """Return a deterministic, non-mutating direct-continuation decision.

    The rules deliberately require structural source evidence.  Candidate IDs,
    filenames, source families, semantic labels, and model outputs are ignored.
    """

    evidence = _extract_evidence(gray, candidate)
    # A very short interruption with no contour, crossing fan, or parallel
    # competitor is dominated by the two observed trajectory endpoints.  The
    # connected-component statistic is intentionally not used here because a
    # dense but unrelated neighborhood can touch the small analysis window.
    if (
        evidence.gap_length_px <= 11
        and evidence.enclosed_contours == 0
        and evidence.transverse_crossing_columns <= 2
        and evidence.parallel_run_fraction <= 0.35
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.ADMISSIBLE,
            DirectContinuationReason.CLEAR_DIRECT_TRAJECTORY,
            evidence,
        )
    # A fully observed center trajectory that dominates a sufficiently broad
    # corridor is admissible even when annotation/layout context is present.
    # This is geometric continuity evidence, not an annotation semantic rule.
    if (
        evidence.gap_length_px >= 25
        and evidence.centerline_support_fraction >= 0.98
        and evidence.off_axis_ink_fraction <= 0.12
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.ADMISSIBLE,
            DirectContinuationReason.CLEAR_DIRECT_TRAJECTORY,
            evidence,
        )
    if (
        evidence.gap_length_px >= 30
        and evidence.centerline_support_fraction <= 0.35
        and evidence.endpoint_boundary_sides >= 3
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.INTENTIONAL_OPENING_EVIDENCE,
            evidence,
        )
    # Offset parallel support with weak off-axis clutter is ambiguous rather
    # than a proven component: the raster does not retain vector identity.
    if (
        evidence.axis_delta_px >= 6
        and evidence.centerline_support_fraction >= 0.9
        and evidence.off_axis_ink_fraction < 0.08
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.UNCERTAIN,
            DirectContinuationReason.INSUFFICIENT_SUPPORT,
            evidence,
        )
    if evidence.enclosed_contours or evidence.volumetric_components:
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.NODE_OR_COMPONENT_MEDIATED,
            evidence,
        )
    if (
        evidence.gap_length_px >= 12
        and evidence.parallel_run_fraction >= 0.9
        and evidence.centerline_support_fraction >= 0.9
        and evidence.off_axis_ink_fraction >= 0.08
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.PARALLEL_COMPETING_EDGE,
            evidence,
        )
    if (
        evidence.parallel_run_fraction >= 0.72
        and evidence.centerline_support_fraction <= 0.35
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.PARALLEL_COMPETING_EDGE,
            evidence,
        )
    if (
        evidence.transverse_crossing_columns >= max(3, evidence.gap_length_px // 5)
        and evidence.off_axis_ink_fraction >= 0.08
        and evidence.centerline_support_fraction <= 0.55
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.COMPETING_STRUCTURE,
            evidence,
        )
    if (
        evidence.axis_delta_px >= 6
        and evidence.parallel_run_fraction >= 0.45
        and evidence.centerline_support_fraction <= 0.45
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.REJECTED,
            DirectContinuationReason.PAIR_OFFSET_INCONSISTENT,
            evidence,
        )
    if (
        evidence.axis_delta_px >= 6
        and evidence.centerline_support_fraction < 0.2
        and evidence.gap_length_px > 12
    ):
        return DirectContinuationDecision(
            DirectContinuationStatus.UNCERTAIN,
            DirectContinuationReason.INSUFFICIENT_SUPPORT,
            evidence,
        )
    return DirectContinuationDecision(
        DirectContinuationStatus.ADMISSIBLE,
        DirectContinuationReason.CLEAR_DIRECT_TRAJECTORY,
        evidence,
    )


__all__ = [
    "DirectContinuationDecision",
    "DirectContinuationEvidence",
    "DirectContinuationReason",
    "DirectContinuationStatus",
    "assess_direct_continuation",
]
