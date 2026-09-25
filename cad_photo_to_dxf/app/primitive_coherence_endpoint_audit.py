"""Deterministic DEV diagnostics for primitive coherence and endpoint integrity.

Span integrity asks whether ink exists across the claimed length and axis
integrity asks whether that ink is on the claimed axis.  This module measures a
third, deliberately separate layer: whether the locally associated ink follows
one stable trajectory.  Endpoint evidence is reported independently because a
mostly valid primitive can still capture a foreign terminal stroke.

The functions in this module are diagnostics.  They do not alter geometry and
are not composed into the DEV qualification path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping, Sequence

import numpy as np

from .primitive_axis_support_integrity import prepare_axis_raster_evidence


class CoherenceStatus(str, Enum):
    SUPPORTED = "PRIMITIVE_COHERENCE_SUPPORTED"
    UNCERTAIN = "PRIMITIVE_COHERENCE_UNCERTAIN"
    REJECTED = "PRIMITIVE_COHERENCE_REJECTED"


class CoherenceReason(str, Enum):
    COHERENT_LOCAL_TRAJECTORY = "COHERENT_LOCAL_TRAJECTORY"
    PIECEWISE_LATERAL_SHIFT = "PIECEWISE_LATERAL_SHIFT"
    DISJOINT_LOCAL_TRAJECTORY = "DISJOINT_LOCAL_TRAJECTORY"
    IDENTITY_CHANGE_ACROSS_STRUCTURE = "IDENTITY_CHANGE_ACROSS_STRUCTURE"
    EXCESSIVE_LOCAL_DIRECTION_CHANGE = "EXCESSIVE_LOCAL_DIRECTION_CHANGE"
    INSUFFICIENT_COHERENCE_EVIDENCE = "INSUFFICIENT_COHERENCE_EVIDENCE"


class EndpointStatus(str, Enum):
    SUPPORTED = "ENDPOINTS_SUPPORTED"
    UNCERTAIN = "ENDPOINT_OVERSHOOT_UNCERTAIN"
    REJECTED = "ENDPOINT_OVERSHOOT_REJECTED"


class EndpointReason(str, Enum):
    SOURCE_TERMINATION_ALIGNED = "SOURCE_TERMINATION_ALIGNED"
    OVERSHOOT_BEYOND_SOURCE_TERMINATION = "OVERSHOOT_BEYOND_SOURCE_TERMINATION"
    FOREIGN_STROKE_CAPTURE = "FOREIGN_STROKE_CAPTURE"
    ENDPOINT_IDENTITY_CHANGE = "ENDPOINT_IDENTITY_CHANGE"
    INSUFFICIENT_ENDPOINT_EVIDENCE = "INSUFFICIENT_ENDPOINT_EVIDENCE"


@dataclass(frozen=True)
class CoherenceThresholds:
    supported_fraction: float = 0.82
    supported_continuity_fraction: float = 0.82
    supported_offset_jump_widths: float = 0.90
    rejected_offset_jump_widths: float = 1.55
    rejected_gap_fraction: float = 0.075
    excessive_tangent_degrees: float = 22.0
    structure_fraction: float = 0.18
    endpoint_tail_fraction: float = 0.18


DEFAULT_THRESHOLDS = CoherenceThresholds()


@dataclass(frozen=True)
class LocalTrajectorySample:
    sample_index: int
    t: float
    position_px: tuple[float, float]
    associated_support: bool
    center_offset_px: float | None
    width_px: float | None
    local_tangent_delta_degrees: float | None
    cross_section_peak_count: int
    junction_or_crossing_evidence: bool


@dataclass(frozen=True)
class CoherenceEvidence:
    length_px: float
    estimated_stroke_width_px: float
    sample_spacing_px: float
    associated_support_fraction: float
    local_continuity_fraction: float
    longest_disjoint_interval_px: float
    longest_disjoint_interval_fraction: float
    center_offset_median_px: float | None
    center_offset_range_px: float | None
    center_offset_range_widths: float | None
    max_sustained_offset_jump_px: float | None
    max_sustained_offset_jump_widths: float | None
    local_tangent_delta_median_degrees: float | None
    local_tangent_delta_p95_degrees: float | None
    width_median_px: float | None
    width_p95_px: float | None
    width_p95_to_median_ratio: float | None
    multi_peak_fraction: float
    junction_or_crossing_fraction: float
    offset_bin_medians_px: tuple[float | None, ...]
    samples: tuple[LocalTrajectorySample, ...]


@dataclass(frozen=True)
class EndpointSampleEvidence:
    endpoint: str
    inside_support_fraction: float
    beyond_support_fraction: float
    tail_offset_change_px: float | None
    tail_offset_change_widths: float | None
    tail_width_ratio: float | None
    tail_junction_fraction: float
    internal_gap_before_supported_tail_fraction: float
    source_termination_distance_px: float | None
    status: EndpointStatus
    reason: EndpointReason


@dataclass(frozen=True)
class EndpointEvidence:
    extension_distance_px: float
    start: EndpointSampleEvidence
    end: EndpointSampleEvidence


@dataclass(frozen=True)
class CoherenceDecision:
    status: CoherenceStatus
    reason: CoherenceReason
    evidence: CoherenceEvidence
    geometry_mutated: bool = False
    split_points_created: bool = False
    model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["reason"] = self.reason.value
        return result


@dataclass(frozen=True)
class EndpointDecision:
    status: EndpointStatus
    reason: EndpointReason
    evidence: EndpointEvidence
    geometry_mutated: bool = False
    split_points_created: bool = False
    model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["reason"] = self.reason.value
        for name in ("start", "end"):
            item = result["evidence"][name]
            item["status"] = item["status"].value
            item["reason"] = item["reason"].value
        return result


def _point(value: Sequence[float]) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def _runs(values: Sequence[int]) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate((*values, 0)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            output.append((start, index - 1))
            start = None
    return output


def _cross_section(
    gray: np.ndarray,
    raw_ink: np.ndarray,
    cx: float,
    cy: float,
    nx: float,
    ny: float,
    radius: int,
    association_radius: float,
) -> tuple[bool, float | None, float | None, int]:
    mask: list[int] = []
    darkness: list[float] = []
    for offset in range(-radius, radius + 1):
        x = int(round(cx + nx * offset))
        y = int(round(cy + ny * offset))
        if 0 <= x < raw_ink.shape[1] and 0 <= y < raw_ink.shape[0]:
            mask.append(int(raw_ink[y, x] > 0))
            darkness.append((255.0 - float(gray[y, x])) / 255.0)
        else:
            mask.append(0)
            darkness.append(0.0)
    runs = _runs(mask)
    if not runs:
        return False, None, None, 0
    center = radius
    distances = [
        0.0
        if left <= center <= right
        else float(min(abs(left - center), abs(right - center)))
        for left, right in runs
    ]
    selected_index = int(np.argmin(distances))
    if distances[selected_index] > association_radius:
        return False, None, None, len(runs)
    left, right = runs[selected_index]
    weights = np.asarray(darkness[left : right + 1], dtype=np.float64)
    offsets = np.arange(left - center, right - center + 1, dtype=np.float64)
    if float(np.sum(weights)) <= 1e-8:
        centroid = float(np.mean(offsets))
    else:
        centroid = float(np.sum(offsets * weights) / np.sum(weights))
    return True, centroid, float(right - left + 1), len(runs)


def _estimate_stroke_width(
    gray: np.ndarray,
    raw_ink: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, math.hypot(dx, dy))
    nx, ny = -dy / length, dx / length
    widths: list[float] = []
    for t in np.linspace(0.05, 0.95, 25):
        supported, _offset, width, _peaks = _cross_section(
            gray,
            raw_ink,
            start[0] + dx * float(t),
            start[1] + dy * float(t),
            nx,
            ny,
            12,
            3.0,
        )
        if supported and width is not None:
            widths.append(width)
    return max(1.0, float(np.median(widths)) if widths else 1.0)


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values), q)), 6)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _longest_false_run(
    samples: Sequence[LocalTrajectorySample], spacing: float
) -> float:
    longest = 0
    current = 0
    for item in samples:
        if item.associated_support:
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    return float(max(longest, current)) * spacing


def _offset_bins(
    samples: Sequence[LocalTrajectorySample], count: int = 8
) -> tuple[float | None, ...]:
    result: list[float | None] = []
    for bin_index in range(count):
        low, high = bin_index / count, (bin_index + 1) / count
        values = [
            item.center_offset_px
            for item in samples
            if item.center_offset_px is not None
            and low <= item.t <= high + (1e-9 if bin_index == count - 1 else 0.0)
        ]
        result.append(_rounded(float(np.median(values))) if values else None)
    return tuple(result)


def build_coherence_profile(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
) -> CoherenceEvidence:
    """Measure local center, direction, width, and bounded continuity."""

    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("coherence requires a non-empty grayscale source")
    start, end = _point(geometry["start"]), _point(geometry["end"])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        raise ValueError("coherence requires a primitive at least one pixel long")
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    raster = prepare_axis_raster_evidence(gray)
    stroke_width = _estimate_stroke_width(gray, raster.raw_ink, start, end)
    spacing_target = max(0.75, min(2.0, stroke_width * 0.60))
    sample_count = max(21, min(601, int(math.ceil(length / spacing_target)) + 1))
    spacing = length / float(sample_count - 1)
    radius = max(5, min(18, int(math.ceil(stroke_width * 4.0 + 2.0))))
    association_radius = max(1.25, min(5.0, stroke_width * 1.35))

    basic: list[tuple[float, float, float, bool, float | None, float | None, int]] = []
    for t_value in np.linspace(0.0, 1.0, sample_count):
        t = float(t_value)
        cx, cy = start[0] + dx * t, start[1] + dy * t
        supported, offset, width, peaks = _cross_section(
            gray,
            raster.raw_ink,
            cx,
            cy,
            nx,
            ny,
            radius,
            association_radius,
        )
        basic.append((t, cx, cy, supported, offset, width, peaks))

    tangent_values: list[float | None] = []
    half_window = max(2, min(8, int(round(max(3.0, stroke_width * 2.0) / spacing))))
    for index, item in enumerate(basic):
        local = [
            (basic[j][0] * length, basic[j][4])
            for j in range(
                max(0, index - half_window), min(len(basic), index + half_window + 1)
            )
            if basic[j][4] is not None
        ]
        if len(local) < 3:
            tangent_values.append(None)
            continue
        axial = np.asarray([value[0] for value in local], dtype=np.float64)
        offsets = np.asarray([float(value[1]) for value in local], dtype=np.float64)
        slope = float(np.polyfit(axial, offsets, 1)[0])
        tangent_values.append(abs(math.degrees(math.atan(slope))))

    widths = [float(item[5]) for item in basic if item[5] is not None]
    width_median = float(np.median(widths)) if widths else stroke_width
    samples: list[LocalTrajectorySample] = []
    for index, (item, tangent) in enumerate(zip(basic, tangent_values)):
        t, cx, cy, supported, offset, width, peaks = item
        junction = bool(
            supported
            and (
                peaks >= 2
                or (width is not None and width >= max(4.0, width_median * 2.25))
            )
        )
        samples.append(
            LocalTrajectorySample(
                sample_index=index,
                t=round(t, 6),
                position_px=(round(cx, 3), round(cy, 3)),
                associated_support=supported,
                center_offset_px=_rounded(offset),
                width_px=_rounded(width),
                local_tangent_delta_degrees=_rounded(tangent),
                cross_section_peak_count=peaks,
                junction_or_crossing_evidence=junction,
            )
        )

    offsets = [
        float(item.center_offset_px)
        for item in samples
        if item.center_offset_px is not None
    ]
    tangents = [
        float(item.local_tangent_delta_degrees)
        for item in samples
        if item.local_tangent_delta_degrees is not None
    ]
    bins = _offset_bins(samples)
    adjacent = [
        abs(float(right) - float(left))
        for left, right in zip(bins, bins[1:])
        if left is not None and right is not None
    ]
    max_jump = max(adjacent, default=None)
    continuity_states: list[bool] = []
    max_step = max(1.5, stroke_width * 1.25)
    for left, right in zip(samples, samples[1:]):
        continuity_states.append(
            bool(
                left.associated_support
                and right.associated_support
                and left.center_offset_px is not None
                and right.center_offset_px is not None
                and abs(right.center_offset_px - left.center_offset_px) <= max_step
            )
        )
    longest_gap = _longest_false_run(samples, spacing)
    width_p95 = _percentile(widths, 95.0)
    return CoherenceEvidence(
        length_px=round(length, 6),
        estimated_stroke_width_px=round(stroke_width, 6),
        sample_spacing_px=round(spacing, 6),
        associated_support_fraction=round(
            sum(item.associated_support for item in samples) / len(samples), 6
        ),
        local_continuity_fraction=round(
            sum(continuity_states) / max(1, len(continuity_states)), 6
        ),
        longest_disjoint_interval_px=round(longest_gap, 6),
        longest_disjoint_interval_fraction=round(longest_gap / length, 6),
        center_offset_median_px=_percentile(offsets, 50.0),
        center_offset_range_px=(
            round(max(offsets) - min(offsets), 6) if offsets else None
        ),
        center_offset_range_widths=(
            round((max(offsets) - min(offsets)) / stroke_width, 6) if offsets else None
        ),
        max_sustained_offset_jump_px=_rounded(max_jump),
        max_sustained_offset_jump_widths=(
            _rounded(max_jump / stroke_width) if max_jump is not None else None
        ),
        local_tangent_delta_median_degrees=_percentile(tangents, 50.0),
        local_tangent_delta_p95_degrees=_percentile(tangents, 95.0),
        width_median_px=_rounded(width_median),
        width_p95_px=width_p95,
        width_p95_to_median_ratio=(
            _rounded(float(width_p95) / width_median)
            if width_p95 is not None and width_median > 0
            else None
        ),
        multi_peak_fraction=round(
            sum(item.cross_section_peak_count >= 2 for item in samples) / len(samples),
            6,
        ),
        junction_or_crossing_fraction=round(
            sum(item.junction_or_crossing_evidence for item in samples) / len(samples),
            6,
        ),
        offset_bin_medians_px=bins,
        samples=tuple(samples),
    )


def decision_from_coherence_evidence(
    evidence: CoherenceEvidence,
    *,
    thresholds: CoherenceThresholds = DEFAULT_THRESHOLDS,
) -> CoherenceDecision:
    jump = evidence.max_sustained_offset_jump_widths or 0.0
    tangent = evidence.local_tangent_delta_p95_degrees or 0.0
    if (
        evidence.longest_disjoint_interval_fraction >= thresholds.rejected_gap_fraction
        and evidence.associated_support_fraction >= 0.45
    ):
        status = CoherenceStatus.REJECTED
        reason = CoherenceReason.DISJOINT_LOCAL_TRAJECTORY
    elif jump >= thresholds.rejected_offset_jump_widths:
        status = CoherenceStatus.REJECTED
        reason = CoherenceReason.PIECEWISE_LATERAL_SHIFT
    elif (
        tangent >= thresholds.excessive_tangent_degrees
        and evidence.center_offset_range_widths is not None
        and evidence.center_offset_range_widths >= 1.2
    ):
        status = CoherenceStatus.UNCERTAIN
        reason = CoherenceReason.EXCESSIVE_LOCAL_DIRECTION_CHANGE
    elif evidence.junction_or_crossing_fraction >= thresholds.structure_fraction and (
        jump >= 0.65 or evidence.local_continuity_fraction < 0.78
    ):
        status = CoherenceStatus.UNCERTAIN
        reason = CoherenceReason.IDENTITY_CHANGE_ACROSS_STRUCTURE
    elif (
        evidence.associated_support_fraction >= thresholds.supported_fraction
        and evidence.local_continuity_fraction
        >= thresholds.supported_continuity_fraction
        and jump <= thresholds.supported_offset_jump_widths
    ):
        status = CoherenceStatus.SUPPORTED
        reason = CoherenceReason.COHERENT_LOCAL_TRAJECTORY
    else:
        status = CoherenceStatus.UNCERTAIN
        reason = CoherenceReason.INSUFFICIENT_COHERENCE_EVIDENCE
    return CoherenceDecision(status=status, reason=reason, evidence=evidence)


def assess_primitive_coherence(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: CoherenceThresholds = DEFAULT_THRESHOLDS,
) -> CoherenceDecision:
    evidence = build_coherence_profile(gray, geometry)
    return decision_from_coherence_evidence(evidence, thresholds=thresholds)


def _endpoint_profile(
    gray: np.ndarray,
    raw_ink: np.ndarray,
    samples: Sequence[LocalTrajectorySample],
    point: tuple[float, float],
    inward: tuple[float, float],
    normal: tuple[float, float],
    stroke_width: float,
    extension: float,
    name: str,
) -> EndpointSampleEvidence:
    radius = max(5, min(18, int(math.ceil(stroke_width * 4.0 + 2.0))))
    association_radius = max(1.25, min(5.0, stroke_width * 1.35))
    inside_values: list[tuple[bool, float | None, float | None, int]] = []
    beyond_values: list[tuple[bool, float | None, float | None, int]] = []
    for distance in np.linspace(0.0, extension, 17):
        for target, direction in ((inside_values, 1.0), (beyond_values, -1.0)):
            cx = point[0] + inward[0] * float(distance) * direction
            cy = point[1] + inward[1] * float(distance) * direction
            target.append(
                _cross_section(
                    gray,
                    raw_ink,
                    cx,
                    cy,
                    normal[0],
                    normal[1],
                    radius,
                    association_radius,
                )
            )
    tail_count = max(4, int(math.ceil(len(samples) * 0.18)))
    tail = list(samples[:tail_count] if name == "start" else samples[-tail_count:])
    core = list(samples[tail_count:-tail_count]) or list(samples)
    tail_offsets = [
        item.center_offset_px for item in tail if item.center_offset_px is not None
    ]
    core_offsets = [
        item.center_offset_px for item in core if item.center_offset_px is not None
    ]
    tail_widths = [item.width_px for item in tail if item.width_px is not None]
    core_widths = [item.width_px for item in core if item.width_px is not None]
    tail_offset_change = (
        abs(float(np.median(tail_offsets)) - float(np.median(core_offsets)))
        if tail_offsets and core_offsets
        else None
    )
    median_tail_width_ratio = (
        float(np.median(tail_widths)) / max(float(np.median(core_widths)), 1e-6)
        if tail_widths and core_widths
        else None
    )
    cap = tail[:3] if name == "start" else tail[-3:]
    cap_widths = [item.width_px for item in cap if item.width_px is not None]
    cap_width_ratio = (
        max(float(value) for value in cap_widths)
        / max(float(np.median(core_widths)), 1e-6)
        if cap_widths and core_widths
        else None
    )
    available_width_ratios = [
        value
        for value in (median_tail_width_ratio, cap_width_ratio)
        if value is not None
    ]
    tail_width_ratio = max(available_width_ratios, default=None)
    states = [item.associated_support for item in tail]
    last_gap = 0
    if any(states):
        supported_indices = [index for index, value in enumerate(states) if value]
        for index in range(min(supported_indices), max(supported_indices) + 1):
            if not states[index]:
                last_gap += 1
    gap_fraction = last_gap / max(1, len(states))
    inside_fraction = sum(item[0] for item in inside_values) / len(inside_values)
    beyond_fraction = sum(item[0] for item in beyond_values[1:]) / max(
        1, len(beyond_values) - 1
    )
    tail_junction = sum(item.junction_or_crossing_evidence for item in tail) / len(tail)
    offset_widths = (
        tail_offset_change / stroke_width if tail_offset_change is not None else None
    )
    termination_distance: float | None = None
    for index, value in enumerate(beyond_values[1:], 1):
        if not value[0]:
            termination_distance = extension * index / 16.0
            break

    if gap_fraction >= 0.12 and sum(states[-max(2, len(states) // 4) :]) >= 2:
        status = EndpointStatus.REJECTED
        reason = EndpointReason.OVERSHOOT_BEYOND_SOURCE_TERMINATION
    elif (
        offset_widths is not None
        and offset_widths >= 1.25
        and (tail_junction >= 0.20 or (tail_width_ratio or 0.0) >= 1.75)
    ):
        status = EndpointStatus.UNCERTAIN
        reason = EndpointReason.FOREIGN_STROKE_CAPTURE
    elif (tail_width_ratio or 0.0) >= 2.5 or tail_junction >= 0.55:
        status = EndpointStatus.UNCERTAIN
        reason = EndpointReason.ENDPOINT_IDENTITY_CHANGE
    elif inside_fraction >= 0.70 and beyond_fraction <= 0.35:
        status = EndpointStatus.SUPPORTED
        reason = EndpointReason.SOURCE_TERMINATION_ALIGNED
    else:
        status = EndpointStatus.UNCERTAIN
        reason = EndpointReason.INSUFFICIENT_ENDPOINT_EVIDENCE
    return EndpointSampleEvidence(
        endpoint=name,
        inside_support_fraction=round(inside_fraction, 6),
        beyond_support_fraction=round(beyond_fraction, 6),
        tail_offset_change_px=_rounded(tail_offset_change),
        tail_offset_change_widths=_rounded(offset_widths),
        tail_width_ratio=_rounded(tail_width_ratio),
        tail_junction_fraction=round(tail_junction, 6),
        internal_gap_before_supported_tail_fraction=round(gap_fraction, 6),
        source_termination_distance_px=_rounded(termination_distance),
        status=status,
        reason=reason,
    )


def assess_primitive_endpoints(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    coherence: CoherenceEvidence | None = None,
) -> EndpointDecision:
    """Inspect both bounded endpoint neighborhoods without moving endpoints."""

    evidence = coherence or build_coherence_profile(gray, geometry)
    start, end = _point(geometry["start"]), _point(geometry["end"])
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    extension = max(
        6.0, min(24.0, max(evidence.estimated_stroke_width_px * 5.0, length * 0.08))
    )
    raster = prepare_axis_raster_evidence(gray)
    start_result = _endpoint_profile(
        gray,
        raster.raw_ink,
        evidence.samples,
        start,
        (ux, uy),
        (nx, ny),
        evidence.estimated_stroke_width_px,
        extension,
        "start",
    )
    end_result = _endpoint_profile(
        gray,
        raster.raw_ink,
        evidence.samples,
        end,
        (-ux, -uy),
        (nx, ny),
        evidence.estimated_stroke_width_px,
        extension,
        "end",
    )
    status_rank = {
        EndpointStatus.REJECTED: 3,
        EndpointStatus.UNCERTAIN: 2,
        EndpointStatus.SUPPORTED: 1,
    }
    reason_rank = {
        EndpointReason.OVERSHOOT_BEYOND_SOURCE_TERMINATION: 5,
        EndpointReason.FOREIGN_STROKE_CAPTURE: 4,
        EndpointReason.ENDPOINT_IDENTITY_CHANGE: 3,
        EndpointReason.INSUFFICIENT_ENDPOINT_EVIDENCE: 2,
        EndpointReason.SOURCE_TERMINATION_ALIGNED: 1,
    }
    chosen = max(
        (start_result, end_result),
        key=lambda result: (status_rank[result.status], reason_rank[result.reason]),
    )
    return EndpointDecision(
        status=chosen.status,
        reason=chosen.reason,
        evidence=EndpointEvidence(
            extension_distance_px=round(extension, 6),
            start=start_result,
            end=end_result,
        ),
    )


__all__ = [
    "CoherenceDecision",
    "CoherenceEvidence",
    "CoherenceReason",
    "CoherenceStatus",
    "CoherenceThresholds",
    "DEFAULT_THRESHOLDS",
    "EndpointDecision",
    "EndpointEvidence",
    "EndpointReason",
    "EndpointSampleEvidence",
    "EndpointStatus",
    "LocalTrajectorySample",
    "assess_primitive_coherence",
    "assess_primitive_endpoints",
    "build_coherence_profile",
    "decision_from_coherence_evidence",
]
