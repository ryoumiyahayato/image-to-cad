"""Full-span source-support qualification for DEV Hough primitives.

The Local-D mining detector is intentionally separate from production line
reconstruction.  This module qualifies its already-detected Hough geometry;
it never changes endpoints, invents split points, or emits replacement lines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from .primitive_axis_support_integrity import (
    AxisSupportStatus,
    build_axis_support_profile_from_evidence,
    decision_from_axis_evidence,
    prepare_axis_raster_evidence,
)


class SpanIntegrityStatus(str, Enum):
    SUPPORTED = "SPAN_INTEGRITY_SUPPORTED"
    REJECTED = "SPAN_INTEGRITY_REJECTED"
    UNCERTAIN = "SPAN_INTEGRITY_UNCERTAIN"


class SpanIntegrityReason(str, Enum):
    CONTINUOUS_SOURCE_SUPPORT = "CONTINUOUS_SOURCE_SUPPORT"
    MATERIAL_INTERNAL_SUPPORT_COLLAPSE = "MATERIAL_INTERNAL_SUPPORT_COLLAPSE"
    COMPETING_STRUCTURE_IN_SPAN = "COMPETING_STRUCTURE_IN_SPAN"
    POSSIBLE_PATTERNED_STROKE = "POSSIBLE_PATTERNED_STROKE"
    NOISY_OR_DEGRADED_SUPPORT = "NOISY_OR_DEGRADED_SUPPORT"
    INSUFFICIENT_SOURCE_EVIDENCE = "INSUFFICIENT_SOURCE_EVIDENCE"


@dataclass(frozen=True)
class SpanIntegrityThresholds:
    """Normalized thresholds; pixel floor only guards sub-pixel sampling noise."""

    material_gap_min_px: float = 2.5
    material_gap_min_stroke_widths: float = 0.75
    material_gap_min_span_fraction: float = 0.06
    patterned_max_support_fraction: float = 0.85
    short_pattern_max_support_fraction: float = 0.92
    short_pattern_max_span_stroke_widths: float = 16.0
    noisy_max_support_fraction: float = 0.72


DEFAULT_THRESHOLDS = SpanIntegrityThresholds()


@dataclass(frozen=True)
class SpanSample:
    sample_index: int
    t: float
    position_px: tuple[float, float]
    centerline_support: bool
    nearby_support: bool
    local_support_ratio: float
    distance_to_nearest_source_ink_px: float
    crossing_structure_evidence: bool


@dataclass(frozen=True)
class SupportRun:
    supported: bool
    start_index: int
    end_index: int
    start_t: float
    end_t: float
    length_px: float
    internal: bool


@dataclass(frozen=True)
class SpanIntegrityEvidence:
    length_px: float
    estimated_stroke_width_px: float
    corridor_radius_px: int
    sample_spacing_px: float
    supported_fraction: float
    centerline_supported_fraction: float
    longest_internal_gap_px: float
    longest_internal_gap_fraction: float
    longest_internal_gap_stroke_widths: float
    internal_gap_count: int
    material_internal_gap_count: int
    repeated_gap_cadence: bool
    competing_structure_samples: int
    endpoint_support: tuple[bool, bool]
    samples: tuple[SpanSample, ...]
    runs: tuple[SupportRun, ...]


@dataclass(frozen=True)
class SpanIntegrityDecision:
    status: SpanIntegrityStatus
    reason: SpanIntegrityReason
    evidence: SpanIntegrityEvidence
    geometry_mutated: bool = False
    split_points_created: bool = False
    model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["reason"] = self.reason.value
        return payload


def _point(value: Sequence[float]) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("span integrity requires a non-empty grayscale source")
    source = gray.astype(np.uint8, copy=False)
    blurred = cv2.GaussianBlur(source, (3, 3), 0)
    return cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]


def _sample_offsets(
    mask: np.ndarray,
    cx: float,
    cy: float,
    nx: float,
    ny: float,
    radius: int,
) -> list[bool]:
    values: list[bool] = []
    for offset in range(-radius, radius + 1):
        x = int(round(cx + nx * offset))
        y = int(round(cy + ny * offset))
        values.append(
            bool(mask[y, x])
            if 0 <= x < mask.shape[1] and 0 <= y < mask.shape[0]
            else False
        )
    return values


def _estimate_stroke_width(
    ink: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, math.hypot(dx, dy))
    nx, ny = -dy / length, dx / length
    widths: list[int] = []
    search_radius = max(4, min(12, int(round(min(ink.shape[:2]) * 0.004))))
    for t in np.linspace(0.05, 0.95, 19):
        cx, cy = start[0] + dx * float(t), start[1] + dy * float(t)
        values = _sample_offsets(ink, cx, cy, nx, ny, search_radius)
        center = search_radius
        ink_indices = [index for index, value in enumerate(values) if value]
        if not ink_indices:
            continue
        nearest = min(ink_indices, key=lambda index: abs(index - center))
        left = nearest
        right = nearest
        while left > 0 and values[left - 1]:
            left -= 1
        while right + 1 < len(values) and values[right + 1]:
            right += 1
        widths.append(right - left + 1)
    return round(float(np.median(widths)) if widths else 1.0, 3)


def _runs(samples: Sequence[SpanSample], spacing: float) -> tuple[SupportRun, ...]:
    if not samples:
        return ()
    output: list[SupportRun] = []
    start = 0
    state = samples[0].nearby_support
    for index in range(1, len(samples) + 1):
        if index < len(samples) and samples[index].nearby_support == state:
            continue
        end = index - 1
        output.append(
            SupportRun(
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
            state = samples[index].nearby_support
    return tuple(output)


def _repeated_gap_cadence(gaps: Sequence[SupportRun]) -> bool:
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


def _build_span_support_profile_from_arrays(
    ink: np.ndarray,
    distance: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: SpanIntegrityThresholds = DEFAULT_THRESHOLDS,
) -> SpanIntegrityEvidence:
    """Build a deterministic, ordered, scale-aware full-span support profile."""

    start = _point(geometry["start"])
    end = _point(geometry["end"])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        raise ValueError("span integrity requires a primitive at least one pixel long")
    nx, ny = -dy / length, dx / length
    stroke_width = _estimate_stroke_width(ink, start, end)
    corridor_radius = max(1, min(6, int(math.ceil(stroke_width * 0.50))))
    target_spacing = max(0.75, min(2.0, stroke_width * 0.65))
    sample_count = max(17, min(513, int(math.ceil(length / target_spacing)) + 1))
    spacing = length / float(sample_count - 1)
    competing_radius = min(14, corridor_radius + max(3, int(math.ceil(stroke_width * 2.0))))

    samples: list[SpanSample] = []
    for index, t_value in enumerate(np.linspace(0.0, 1.0, sample_count)):
        t = float(t_value)
        cx, cy = start[0] + dx * t, start[1] + dy * t
        corridor = _sample_offsets(ink, cx, cy, nx, ny, corridor_radius)
        wide = _sample_offsets(ink, cx, cy, nx, ny, competing_radius)
        center_index = corridor_radius
        centerline = corridor[center_index]
        nearby = any(corridor)
        outer = wide[: competing_radius - corridor_radius] + wide[
            competing_radius + corridor_radius + 1 :
        ]
        left_outer = wide[: max(0, competing_radius - corridor_radius)]
        right_outer = wide[min(len(wide), competing_radius + corridor_radius + 1) :]
        crossing = (any(left_outer) and any(right_outer)) or (
            not nearby and sum(outer) >= max(2, int(round(stroke_width)))
        )
        px = min(max(int(round(cx)), 0), ink.shape[1] - 1)
        py = min(max(int(round(cy)), 0), ink.shape[0] - 1)
        samples.append(
            SpanSample(
                sample_index=index,
                t=round(t, 6),
                position_px=(round(cx, 3), round(cy, 3)),
                centerline_support=centerline,
                nearby_support=nearby,
                local_support_ratio=round(sum(corridor) / len(corridor), 6),
                distance_to_nearest_source_ink_px=round(float(distance[py, px]), 4),
                crossing_structure_evidence=crossing,
            )
        )

    runs = _runs(samples, spacing)
    gaps = [run for run in runs if not run.supported and run.internal]
    longest = max((run.length_px for run in gaps), default=0.0)
    gap_fraction = longest / length
    gap_widths = longest / max(1.0, stroke_width)
    # A material collapse must be both locally wide relative to the stroke and
    # occupy a meaningful part of the claimed span. This keeps isolated raster
    # dropout from becoming a global "gap = bad" rule.
    material = [
        gap
        for gap in gaps
        if gap.length_px
        >= max(
            thresholds.material_gap_min_px,
            stroke_width * thresholds.material_gap_min_stroke_widths,
        )
        and gap.length_px / length >= thresholds.material_gap_min_span_fraction
    ]
    gap_extent = (
        (min(gap.start_index for gap in gaps), max(gap.end_index for gap in gaps))
        if gaps
        else None
    )
    competing_samples = sum(
        sample.crossing_structure_evidence
        for sample in samples
        if gap_extent is not None
        and gap_extent[0] <= sample.sample_index <= gap_extent[1]
    )
    return SpanIntegrityEvidence(
        length_px=round(length, 4),
        estimated_stroke_width_px=stroke_width,
        corridor_radius_px=corridor_radius,
        sample_spacing_px=round(spacing, 4),
        supported_fraction=round(
            sum(sample.nearby_support for sample in samples) / len(samples), 6
        ),
        centerline_supported_fraction=round(
            sum(sample.centerline_support for sample in samples) / len(samples), 6
        ),
        longest_internal_gap_px=round(longest, 4),
        longest_internal_gap_fraction=round(gap_fraction, 6),
        longest_internal_gap_stroke_widths=round(gap_widths, 4),
        internal_gap_count=len(gaps),
        material_internal_gap_count=len(material),
        repeated_gap_cadence=_repeated_gap_cadence(gaps),
        competing_structure_samples=competing_samples,
        endpoint_support=(samples[0].nearby_support, samples[-1].nearby_support),
        samples=tuple(samples),
        runs=runs,
    )


def build_span_support_profile(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: SpanIntegrityThresholds = DEFAULT_THRESHOLDS,
) -> SpanIntegrityEvidence:
    """Build a deterministic, ordered, scale-aware full-span support profile."""

    ink = _ink_mask(gray)
    distance = cv2.distanceTransform((ink == 0).astype(np.uint8), cv2.DIST_L2, 5)
    return _build_span_support_profile_from_arrays(
        ink, distance, geometry, thresholds=thresholds
    )


def _decision_from_evidence(
    evidence: SpanIntegrityEvidence,
    *,
    thresholds: SpanIntegrityThresholds = DEFAULT_THRESHOLDS,
) -> SpanIntegrityDecision:
    internal_gaps = [
        run for run in evidence.runs if not run.supported and run.internal
    ]
    span_in_stroke_widths = evidence.length_px / max(
        1.0, evidence.estimated_stroke_width_px
    )
    patterned = (
        evidence.internal_gap_count >= 3
        and evidence.supported_fraction < thresholds.patterned_max_support_fraction
    ) or (
        evidence.internal_gap_count >= 2
        and evidence.supported_fraction
        <= thresholds.short_pattern_max_support_fraction
        and span_in_stroke_widths
        <= thresholds.short_pattern_max_span_stroke_widths
    )
    material = evidence.material_internal_gap_count > 0
    if material and evidence.competing_structure_samples > 0:
        status = SpanIntegrityStatus.REJECTED
        reason = SpanIntegrityReason.COMPETING_STRUCTURE_IN_SPAN
    elif patterned:
        status = SpanIntegrityStatus.UNCERTAIN
        reason = SpanIntegrityReason.POSSIBLE_PATTERNED_STROKE
    elif material:
        status = SpanIntegrityStatus.REJECTED
        reason = SpanIntegrityReason.MATERIAL_INTERNAL_SUPPORT_COLLAPSE
    elif not all(evidence.endpoint_support) and evidence.supported_fraction < 0.55:
        status = SpanIntegrityStatus.UNCERTAIN
        reason = SpanIntegrityReason.INSUFFICIENT_SOURCE_EVIDENCE
    elif evidence.supported_fraction < thresholds.noisy_max_support_fraction or (
        len(internal_gaps) >= 3 and evidence.supported_fraction < 0.88
    ):
        status = SpanIntegrityStatus.UNCERTAIN
        reason = SpanIntegrityReason.NOISY_OR_DEGRADED_SUPPORT
    else:
        status = SpanIntegrityStatus.SUPPORTED
        reason = SpanIntegrityReason.CONTINUOUS_SOURCE_SUPPORT
    return SpanIntegrityDecision(status=status, reason=reason, evidence=evidence)


def assess_primitive_span(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: SpanIntegrityThresholds = DEFAULT_THRESHOLDS,
) -> SpanIntegrityDecision:
    """Qualify one claimed primitive span from generic raster evidence only."""

    evidence = build_span_support_profile(gray, geometry, thresholds=thresholds)
    return _decision_from_evidence(evidence, thresholds=thresholds)


def _combined_bucket(
    span_status: SpanIntegrityStatus,
    axis_status: AxisSupportStatus,
) -> str:
    """Compose the additive DEV guards without weakening either result."""

    if (
        span_status is SpanIntegrityStatus.REJECTED
        or axis_status is AxisSupportStatus.REJECTED
    ):
        return "rejected"
    if (
        span_status is SpanIntegrityStatus.UNCERTAIN
        or axis_status is AxisSupportStatus.UNCERTAIN
    ):
        return "uncertain"
    return "supported"


def qualify_dev_hough_primitives(
    gray: np.ndarray,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Separate Local-D raw Hough records before normalization/pair mining.

    Only ``supported`` records may flow into ordinary continuation mining.
    Uncertain records remain available for diagnostics but are not promoted as
    fully credible primitives. Rejected records are retained only as evidence.
    """

    buckets: dict[str, list[dict[str, Any]]] = {
        "supported": [],
        "uncertain": [],
        "rejected": [],
    }
    axis_raster = prepare_axis_raster_evidence(gray)
    for record in records:
        geometry = record.get("raw_geometry")
        if not isinstance(geometry, Mapping):
            raise ValueError("DEV Hough record is missing raw_geometry")
        decision = assess_primitive_span(gray, geometry)
        axis_evidence = build_axis_support_profile_from_evidence(
            axis_raster, geometry
        )
        axis_decision = decision_from_axis_evidence(axis_evidence)
        qualified = dict(record)
        qualified["span_integrity"] = decision.to_dict()
        qualified["axis_support_integrity"] = axis_decision.to_dict()
        qualified["primitive_integrity_bucket"] = _combined_bucket(
            decision.status, axis_decision.status
        )
        buckets[qualified["primitive_integrity_bucket"]].append(qualified)
    return {key: tuple(value) for key, value in buckets.items()}


def qualify_dev_hough_primitives_cached(
    gray: np.ndarray,
    records: Sequence[Mapping[str, Any]],
    *,
    thresholds: SpanIntegrityThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Qualify a raw-Hough batch with shared source-support evidence.

    This is a semantics-preserving DEV batch path.  It uses the same mask,
    sampling, thresholds, status rules, and serialized decision payload as
    :func:`qualify_dev_hough_primitives`, while calculating the source mask and
    distance transform once per source image instead of once per primitive.
    """

    ink = _ink_mask(gray)
    distance = cv2.distanceTransform((ink == 0).astype(np.uint8), cv2.DIST_L2, 5)
    axis_raster = prepare_axis_raster_evidence(gray)
    buckets: dict[str, list[dict[str, Any]]] = {
        "supported": [],
        "uncertain": [],
        "rejected": [],
    }
    for record in records:
        geometry = record.get("raw_geometry")
        if not isinstance(geometry, Mapping):
            raise ValueError("DEV Hough record is missing raw_geometry")
        evidence = _build_span_support_profile_from_arrays(
            ink, distance, geometry, thresholds=thresholds
        )
        decision = _decision_from_evidence(evidence, thresholds=thresholds)
        axis_evidence = build_axis_support_profile_from_evidence(
            axis_raster, geometry
        )
        axis_decision = decision_from_axis_evidence(axis_evidence)
        qualified = dict(record)
        qualified["span_integrity"] = decision.to_dict()
        qualified["axis_support_integrity"] = axis_decision.to_dict()
        qualified["primitive_integrity_bucket"] = _combined_bucket(
            decision.status, axis_decision.status
        )
        buckets[qualified["primitive_integrity_bucket"]].append(qualified)
    return {key: tuple(value) for key, value in buckets.items()}


def detect_and_qualify_local_d_hough(
    gray: np.ndarray,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Run the exact Local-D Hough producer and gate it before normalization.

    This is the remediated DEV entry point for any future candidate remining.
    Frozen-case regression intentionally consumes persisted raw ancestors and
    does not call this function, so no candidate set is remined in V1.
    """

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    lines = cv2.HoughLinesP(
        binary, 1, np.pi / 180, threshold=45, minLineLength=28, maxLineGap=3
    )
    records: list[dict[str, Any]] = []
    if lines is not None:
        for index, raw in enumerate(lines[:, 0, :]):
            x1, y1, x2, y2 = (int(value) for value in raw)
            dx, dy = x2 - x1, y2 - y1
            accepted = abs(dx) >= 3 * max(1, abs(dy)) or abs(dy) >= 3 * max(
                1, abs(dx)
            )
            records.append(
                {
                    "id": f"raw-hough-{index:06d}",
                    "detector": "HOUGH",
                    "raw_geometry": {"start": [x1, y1], "end": [x2, y2]},
                    "accepted_by_orientation_filter": accepted,
                }
            )
    oriented = [item for item in records if item["accepted_by_orientation_filter"]]
    return qualify_dev_hough_primitives(gray, oriented)
