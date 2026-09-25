"""Raw-raster axis qualification for DEV Hough primitives.

The existing span gate intentionally tolerates small perpendicular offsets by
looking inside a blurred, stroke-width corridor.  That is useful for damaged
strokes, but a narrow hollow band can make the corridor look fully supported
while the claimed primitive axis itself is white.  This module keeps the
broad-corridor evidence and separately measures raw on-axis and paired-flank
evidence.  It never moves, splits, or creates geometry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


class AxisSupportStatus(str, Enum):
    SUPPORTED = "PRIMITIVE_AXIS_SUPPORTED"
    REJECTED = "PRIMITIVE_AXIS_REJECTED"
    UNCERTAIN = "PRIMITIVE_AXIS_UNCERTAIN"


class AxisSupportReason(str, Enum):
    DIRECT_AXIS_SUPPORT = "DIRECT_AXIS_SUPPORT"
    SYMMETRIC_FLANK_WITH_CENTER_VOID = "SYMMETRIC_FLANK_WITH_CENTER_VOID"
    PERSISTENT_AXIS_SUPPORT_GAP = "PERSISTENT_AXIS_SUPPORT_GAP"
    POSSIBLE_PATTERNED_AXIS_SUPPORT = "POSSIBLE_PATTERNED_AXIS_SUPPORT"
    BROAD_SUPPORT_WITHOUT_AXIS_SUPPORT = "BROAD_SUPPORT_WITHOUT_AXIS_SUPPORT"
    NOISY_OR_DEGRADED_AXIS_SUPPORT = "NOISY_OR_DEGRADED_AXIS_SUPPORT"
    INSUFFICIENT_AXIS_EVIDENCE = "INSUFFICIENT_AXIS_EVIDENCE"


@dataclass(frozen=True)
class AxisSupportThresholds:
    """Generic normalized thresholds for the raw-raster axis profile."""

    supported_axis_fraction: float = 0.50
    supported_max_gap_fraction: float = 0.14
    symmetric_void_min_fraction: float = 0.58
    symmetric_void_max_axis_fraction: float = 0.30
    symmetric_void_min_broad_fraction: float = 0.78
    symmetric_void_min_flank_fraction: float = 0.62
    broad_without_axis_min_fraction: float = 0.72
    broad_without_axis_max_fraction: float = 0.42
    persistent_gap_min_fraction: float = 0.14
    material_gap_min_px: float = 3.0
    material_gap_min_span_fraction: float = 0.06


DEFAULT_AXIS_THRESHOLDS = AxisSupportThresholds()


@dataclass(frozen=True)
class AxisSample:
    sample_index: int
    t: float
    position_px: tuple[float, float]
    axis_darkness: float
    exact_axis_support: bool
    on_axis_direct_support: bool
    broad_corridor_support: bool
    left_flank_support: bool
    right_flank_support: bool
    left_flank_offset_px: float | None
    right_flank_offset_px: float | None
    symmetric_flank_support: bool
    center_void_with_symmetric_flanks: bool


@dataclass(frozen=True)
class AxisSupportRun:
    supported: bool
    start_index: int
    end_index: int
    start_t: float
    end_t: float
    length_px: float
    internal: bool


@dataclass(frozen=True)
class AxisSupportEvidence:
    length_px: float
    raw_otsu_threshold: float
    estimated_stroke_width_px: float
    broad_corridor_radius_px: int
    flank_search_radius_px: int
    sample_spacing_px: float
    exact_axis_support_fraction: float
    on_axis_direct_support_fraction: float
    broad_corridor_support_fraction: float
    left_flank_support_fraction: float
    right_flank_support_fraction: float
    symmetric_flank_support_fraction: float
    symmetric_flank_center_void_fraction: float
    center_to_flank_darkness_contrast: float
    median_left_flank_offset_px: float | None
    median_right_flank_offset_px: float | None
    longest_unsupported_axis_interval_px: float
    longest_unsupported_axis_interval_fraction: float
    unsupported_axis_interval_count: int
    material_unsupported_axis_interval_count: int
    repeated_gap_cadence: bool
    endpoint_axis_support: tuple[bool, bool]
    samples: tuple[AxisSample, ...]
    runs: tuple[AxisSupportRun, ...]


@dataclass(frozen=True)
class AxisSupportDecision:
    status: AxisSupportStatus
    reason: AxisSupportReason
    evidence: AxisSupportEvidence
    geometry_mutated: bool = False
    split_points_created: bool = False
    model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["reason"] = self.reason.value
        return payload


@dataclass(frozen=True)
class AxisRasterEvidence:
    """Image-level arrays shared by the cached DEV batch path."""

    gray: np.ndarray
    raw_ink: np.ndarray
    broad_ink: np.ndarray
    raw_otsu_threshold: float


def _point(value: Sequence[float]) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def prepare_axis_raster_evidence(gray: np.ndarray) -> AxisRasterEvidence:
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("axis support requires a non-empty grayscale source")
    source = gray.astype(np.uint8, copy=False)
    raw_threshold, raw_ink = cv2.threshold(
        source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    broad_ink = cv2.threshold(
        cv2.GaussianBlur(source, (3, 3), 0),
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )[1]
    return AxisRasterEvidence(
        gray=source,
        raw_ink=raw_ink,
        broad_ink=broad_ink,
        raw_otsu_threshold=round(float(raw_threshold), 4),
    )


def _sample_offsets(
    image: np.ndarray,
    cx: float,
    cy: float,
    nx: float,
    ny: float,
    radius: int,
) -> list[int]:
    values: list[int] = []
    for offset in range(-radius, radius + 1):
        x = int(round(cx + nx * offset))
        y = int(round(cy + ny * offset))
        values.append(
            int(image[y, x])
            if 0 <= x < image.shape[1] and 0 <= y < image.shape[0]
            else 0
        )
    return values


def _nearest_run_width(values: Sequence[int], center: int) -> int | None:
    indices = [index for index, value in enumerate(values) if value]
    if not indices:
        return None
    nearest = min(indices, key=lambda index: abs(index - center))
    left = nearest
    right = nearest
    while left > 0 and values[left - 1]:
        left -= 1
    while right + 1 < len(values) and values[right + 1]:
        right += 1
    return right - left + 1


def _estimate_stroke_width(
    raw_ink: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, math.hypot(dx, dy))
    nx, ny = -dy / length, dx / length
    radius = max(4, min(12, int(round(min(raw_ink.shape[:2]) * 0.004))))
    widths: list[int] = []
    for t_value in np.linspace(0.05, 0.95, 19):
        cx = start[0] + dx * float(t_value)
        cy = start[1] + dy * float(t_value)
        values = _sample_offsets(raw_ink, cx, cy, nx, ny, radius)
        width = _nearest_run_width(values, radius)
        if width is not None:
            widths.append(width)
    return round(float(np.median(widths)) if widths else 1.0, 3)


def _support_runs(
    samples: Sequence[AxisSample], spacing: float
) -> tuple[AxisSupportRun, ...]:
    if not samples:
        return ()
    output: list[AxisSupportRun] = []
    start = 0
    state = samples[0].on_axis_direct_support
    for index in range(1, len(samples) + 1):
        if index < len(samples) and samples[index].on_axis_direct_support == state:
            continue
        end = index - 1
        output.append(
            AxisSupportRun(
                supported=state,
                start_index=start,
                end_index=end,
                start_t=samples[start].t,
                end_t=samples[end].t,
                length_px=max(spacing, (end - start + 1) * spacing),
                internal=start > 0 and end < len(samples) - 1,
            )
        )
        if index < len(samples):
            start = index
            state = samples[index].on_axis_direct_support
    return tuple(output)


def _repeated_gap_cadence(gaps: Sequence[AxisSupportRun]) -> bool:
    if len(gaps) < 3:
        return False
    lengths = np.asarray([gap.length_px for gap in gaps], dtype=np.float64)
    centers = np.asarray(
        [(gap.start_t + gap.end_t) * 0.5 for gap in gaps], dtype=np.float64
    )
    intervals = np.diff(centers)
    if not intervals.size or float(np.mean(intervals)) <= 0.0:
        return False
    length_cv = float(np.std(lengths) / max(float(np.mean(lengths)), 1e-6))
    cadence_cv = float(np.std(intervals) / max(float(np.mean(intervals)), 1e-6))
    return length_cv <= 0.75 and cadence_cv <= 0.55


def _median_or_none(values: Sequence[float]) -> float | None:
    return round(float(np.median(values)), 4) if values else None


def build_axis_support_profile_from_evidence(
    raster: AxisRasterEvidence,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: AxisSupportThresholds = DEFAULT_AXIS_THRESHOLDS,
) -> AxisSupportEvidence:
    """Measure raw axis, paired flanks, and blurred broad-corridor support."""

    start = _point(geometry["start"])
    end = _point(geometry["end"])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        raise ValueError("axis support requires a primitive at least one pixel long")
    nx, ny = -dy / length, dx / length
    stroke_width = _estimate_stroke_width(raster.raw_ink, start, end)
    broad_radius = max(2, min(6, int(math.ceil(stroke_width * 1.5))))
    flank_radius = max(4, min(12, int(math.ceil(stroke_width * 3.0 + 1.0))))
    target_spacing = max(0.75, min(2.0, stroke_width * 0.65))
    sample_count = max(17, min(513, int(math.ceil(length / target_spacing)) + 1))
    spacing = length / float(sample_count - 1)

    samples: list[AxisSample] = []
    contrasts: list[float] = []
    left_offsets: list[float] = []
    right_offsets: list[float] = []
    for index, t_value in enumerate(np.linspace(0.0, 1.0, sample_count)):
        t = float(t_value)
        cx, cy = start[0] + dx * t, start[1] + dy * t
        raw = _sample_offsets(raster.raw_ink, cx, cy, nx, ny, flank_radius)
        gray_values = _sample_offsets(raster.gray, cx, cy, nx, ny, flank_radius)
        broad = _sample_offsets(
            raster.broad_ink, cx, cy, nx, ny, broad_radius
        )
        center = flank_radius
        exact_axis = bool(raw[center])
        left_indices = [
            offset
            for offset in range(1, flank_radius + 1)
            if raw[center - offset]
        ]
        right_indices = [
            offset
            for offset in range(1, flank_radius + 1)
            if raw[center + offset]
        ]
        left_offset = float(min(left_indices)) if left_indices else None
        right_offset = float(min(right_indices)) if right_indices else None
        symmetric = bool(
            left_offset is not None
            and right_offset is not None
            and abs(left_offset - right_offset)
            <= max(1.0, 0.35 * (left_offset + right_offset) * 0.5)
        )
        immediate_unilateral = bool(
            not symmetric
            and min(
                left_offset if left_offset is not None else float("inf"),
                right_offset if right_offset is not None else float("inf"),
            )
            <= 1.0
        )
        on_axis = bool(exact_axis or immediate_unilateral)
        center_void = bool(not exact_axis and symmetric)
        center_darkness = (255.0 - float(gray_values[center])) / 255.0
        if center_void and left_offset is not None and right_offset is not None:
            left_value = gray_values[center - int(left_offset)]
            right_value = gray_values[center + int(right_offset)]
            flank_darkness = (
                (255.0 - float(left_value)) / 255.0
                + (255.0 - float(right_value)) / 255.0
            ) * 0.5
            contrasts.append(flank_darkness - center_darkness)
        if left_offset is not None:
            left_offsets.append(left_offset)
        if right_offset is not None:
            right_offsets.append(right_offset)
        samples.append(
            AxisSample(
                sample_index=index,
                t=round(t, 6),
                position_px=(round(cx, 3), round(cy, 3)),
                axis_darkness=round(center_darkness, 6),
                exact_axis_support=exact_axis,
                on_axis_direct_support=on_axis,
                broad_corridor_support=any(broad),
                left_flank_support=left_offset is not None,
                right_flank_support=right_offset is not None,
                left_flank_offset_px=left_offset,
                right_flank_offset_px=right_offset,
                symmetric_flank_support=symmetric,
                center_void_with_symmetric_flanks=center_void,
            )
        )

    runs = _support_runs(samples, spacing)
    gaps = [run for run in runs if not run.supported and run.internal]
    longest = max((run.length_px for run in gaps), default=0.0)
    material = [
        gap
        for gap in gaps
        if gap.length_px
        >= max(thresholds.material_gap_min_px, stroke_width)
        and gap.length_px / length
        >= thresholds.material_gap_min_span_fraction
    ]
    count = float(len(samples))
    return AxisSupportEvidence(
        length_px=round(length, 4),
        raw_otsu_threshold=raster.raw_otsu_threshold,
        estimated_stroke_width_px=stroke_width,
        broad_corridor_radius_px=broad_radius,
        flank_search_radius_px=flank_radius,
        sample_spacing_px=round(spacing, 4),
        exact_axis_support_fraction=round(
            sum(item.exact_axis_support for item in samples) / count, 6
        ),
        on_axis_direct_support_fraction=round(
            sum(item.on_axis_direct_support for item in samples) / count, 6
        ),
        broad_corridor_support_fraction=round(
            sum(item.broad_corridor_support for item in samples) / count, 6
        ),
        left_flank_support_fraction=round(
            sum(item.left_flank_support for item in samples) / count, 6
        ),
        right_flank_support_fraction=round(
            sum(item.right_flank_support for item in samples) / count, 6
        ),
        symmetric_flank_support_fraction=round(
            sum(item.symmetric_flank_support for item in samples) / count, 6
        ),
        symmetric_flank_center_void_fraction=round(
            sum(item.center_void_with_symmetric_flanks for item in samples) / count,
            6,
        ),
        center_to_flank_darkness_contrast=round(
            float(np.median(contrasts)) if contrasts else 0.0, 6
        ),
        median_left_flank_offset_px=_median_or_none(left_offsets),
        median_right_flank_offset_px=_median_or_none(right_offsets),
        longest_unsupported_axis_interval_px=round(longest, 4),
        longest_unsupported_axis_interval_fraction=round(longest / length, 6),
        unsupported_axis_interval_count=len(gaps),
        material_unsupported_axis_interval_count=len(material),
        repeated_gap_cadence=_repeated_gap_cadence(gaps),
        endpoint_axis_support=(
            samples[0].on_axis_direct_support,
            samples[-1].on_axis_direct_support,
        ),
        samples=tuple(samples),
        runs=runs,
    )


def build_axis_support_profile(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: AxisSupportThresholds = DEFAULT_AXIS_THRESHOLDS,
) -> AxisSupportEvidence:
    raster = prepare_axis_raster_evidence(gray)
    return build_axis_support_profile_from_evidence(
        raster, geometry, thresholds=thresholds
    )


def decision_from_axis_evidence(
    evidence: AxisSupportEvidence,
    *,
    thresholds: AxisSupportThresholds = DEFAULT_AXIS_THRESHOLDS,
) -> AxisSupportDecision:
    axis = evidence.on_axis_direct_support_fraction
    broad = evidence.broad_corridor_support_fraction
    left = evidence.left_flank_support_fraction
    right = evidence.right_flank_support_fraction
    symmetric_void = evidence.symmetric_flank_center_void_fraction
    longest_gap = evidence.longest_unsupported_axis_interval_fraction

    if (
        symmetric_void >= thresholds.symmetric_void_min_fraction
        and axis <= thresholds.symmetric_void_max_axis_fraction
        and broad >= thresholds.symmetric_void_min_broad_fraction
        and min(left, right) >= thresholds.symmetric_void_min_flank_fraction
        and evidence.center_to_flank_darkness_contrast > 0.0
    ):
        status = AxisSupportStatus.REJECTED
        reason = AxisSupportReason.SYMMETRIC_FLANK_WITH_CENTER_VOID
    elif axis >= 0.80 and longest_gap <= 0.08:
        status = AxisSupportStatus.SUPPORTED
        reason = AxisSupportReason.DIRECT_AXIS_SUPPORT
    elif evidence.repeated_gap_cadence:
        status = AxisSupportStatus.UNCERTAIN
        reason = AxisSupportReason.POSSIBLE_PATTERNED_AXIS_SUPPORT
    elif (
        evidence.material_unsupported_axis_interval_count > 0
        and longest_gap >= thresholds.persistent_gap_min_fraction
        and broad >= thresholds.broad_without_axis_min_fraction
        and axis < thresholds.supported_axis_fraction
    ):
        status = AxisSupportStatus.REJECTED
        reason = AxisSupportReason.PERSISTENT_AXIS_SUPPORT_GAP
    elif (
        axis >= thresholds.supported_axis_fraction
        and longest_gap <= thresholds.supported_max_gap_fraction
    ):
        status = AxisSupportStatus.SUPPORTED
        reason = AxisSupportReason.DIRECT_AXIS_SUPPORT
    elif (
        broad >= thresholds.broad_without_axis_min_fraction
        and axis <= thresholds.broad_without_axis_max_fraction
    ):
        status = AxisSupportStatus.UNCERTAIN
        reason = AxisSupportReason.BROAD_SUPPORT_WITHOUT_AXIS_SUPPORT
    elif evidence.material_unsupported_axis_interval_count > 0 or axis >= 0.40:
        status = AxisSupportStatus.UNCERTAIN
        reason = AxisSupportReason.NOISY_OR_DEGRADED_AXIS_SUPPORT
    else:
        status = AxisSupportStatus.UNCERTAIN
        reason = AxisSupportReason.INSUFFICIENT_AXIS_EVIDENCE
    return AxisSupportDecision(status=status, reason=reason, evidence=evidence)


def assess_primitive_axis(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: AxisSupportThresholds = DEFAULT_AXIS_THRESHOLDS,
) -> AxisSupportDecision:
    """Qualify one primitive axis using only generic source-raster evidence."""

    evidence = build_axis_support_profile(
        gray, geometry, thresholds=thresholds
    )
    return decision_from_axis_evidence(evidence, thresholds=thresholds)


__all__ = [
    "AxisRasterEvidence",
    "AxisSample",
    "AxisSupportDecision",
    "AxisSupportEvidence",
    "AxisSupportReason",
    "AxisSupportRun",
    "AxisSupportStatus",
    "AxisSupportThresholds",
    "DEFAULT_AXIS_THRESHOLDS",
    "assess_primitive_axis",
    "build_axis_support_profile",
    "build_axis_support_profile_from_evidence",
    "decision_from_axis_evidence",
    "prepare_axis_raster_evidence",
]
