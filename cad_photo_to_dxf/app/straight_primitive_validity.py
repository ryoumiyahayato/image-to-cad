"""DEV-only validity gate for claimed straight source primitives.

The span, axis, and text guards answer different questions.  This stage asks
whether the source evidence associated with a primitive follows one straight
trajectory over the claimed extent.  It deliberately reuses the local
trajectory profile from :mod:`primitive_coherence_endpoint_audit`; no semantic
class, candidate identity, filename, or model output participates in a verdict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from itertools import pairwise
from typing import Any

import numpy as np

from .primitive_coherence_endpoint_audit import (
    CoherenceEvidence,
    build_coherence_profile,
)


class StraightValidityStatus(str, Enum):
    SUPPORTED = "STRAIGHT_SUPPORTED"
    UNCERTAIN = "STRAIGHT_UNCERTAIN"
    REJECTED = "STRAIGHT_REJECTED"


class StraightWindowState(str, Enum):
    CLEAN = "CLEAN_STRAIGHT_WINDOW"
    CROSSING = "CROSSING_CONTAMINATED_WINDOW"
    INCONSISTENT = "TRAJECTORY_INCONSISTENT_WINDOW"


class StraightValidityReason(str, Enum):
    CONFIRMED = "STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED"
    CURVED = "CURVED_CONTOUR_STRAIGHT_FIT"
    PIECEWISE = "PIECEWISE_OFFSET_COLLAPSE"
    BOUNDARY_SWITCH = "SOURCE_BOUNDARY_SWITCH"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_STRAIGHT_TRAJECTORY_SUPPORT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class StraightValidityThresholds:
    minimum_support_fraction: float = 0.82
    minimum_continuity_fraction: float = 0.82
    rejected_gap_fraction: float = 0.075
    rejected_piecewise_jump_widths: float = 1.55
    rejected_drift_px: float = 3.5
    rejected_drift_fraction: float = 0.06
    rejected_tangent_deviation_degrees: float = 8.0
    supported_tangent_deviation_degrees: float = 22.0
    minimum_credible_window_fraction: float = 0.75
    switch_minimum_px: float = 2.5
    switch_length_fraction: float = 0.06
    crossing_minimum_fraction: float = 0.18
    crossing_max_gap_fraction: float = 0.25
    crossing_neighbor_window_count: int = 4
    crossing_offset_tolerance_widths: float = 1.0
    crossing_stable_bin_fraction: float = 0.80
    crossing_max_local_window_fraction: float = 0.08
    crossing_max_endpoint_window_fraction: float = 0.20
    crossing_max_internal_abnormal_fraction: float = 0.03


DEFAULT_THRESHOLDS = StraightValidityThresholds()


@dataclass(frozen=True)
class StraightValidityEvidence:
    trajectory: CoherenceEvidence
    support_run_count: int
    credible_straight_window_fraction: float
    max_sustained_lateral_drift_px: float
    max_sustained_lateral_drift_fraction: float
    local_tangent_deviation_p95_degrees: float | None
    abrupt_support_identity_switches: int
    ridge_width_to_length_ratio: float | None
    usable_trajectory_window_count: int
    crossing_contaminated_window_fraction: float
    clean_straight_window_fraction: float
    trajectory_inconsistent_window_fraction: float
    longest_abnormal_run_fraction: float
    internal_abnormal_window_fraction: float
    crossing_recovered_gap_fraction: float
    longest_unrecovered_gap_fraction: float
    effective_support_fraction: float
    effective_continuity_fraction: float
    robust_offset_stability_fraction: float
    robust_tangent_deviation_p95_degrees: float | None
    robust_tangent_estimator: str
    piecewise_jump_crossing_compatible: bool
    crossing_aware_straight_window: bool
    window_states: tuple[str, ...]


@dataclass(frozen=True)
class StraightValidityDecision:
    status: StraightValidityStatus
    reason: StraightValidityReason
    evidence: StraightValidityEvidence
    geometry_mutated: bool = False
    semantic_or_model_evidence_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["reason"] = self.reason.value
        return result


def _true_run_count(values: Sequence[bool]) -> int:
    count = 0
    previous = False
    for value in values:
        if value and not previous:
            count += 1
        previous = value
    return count


def _runs(values: Sequence[bool]) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate((*values, False)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            output.append((start, index - 1))
            start = None
    return output


def _sample_bin(index: int, sample_count: int, bin_count: int = 8) -> int:
    if sample_count <= 1:
        return 0
    return min(bin_count - 1, int(index * bin_count / sample_count))


def _median_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _crossing_profile(
    trajectory: CoherenceEvidence,
    *,
    thresholds: StraightValidityThresholds,
) -> dict[str, Any]:
    """Build a crossing-aware profile without changing source-coherence data.

    Crossing windows are only discounted when the associated ridge agrees on
    both sides.  An internal offset shift, an unbounded gap, or a sustained
    abnormal run remains trajectory evidence against a straight primitive.
    """

    samples = trajectory.samples
    sample_count = len(samples)
    if not sample_count:
        return {
            "states": (),
            "crossing_fraction": 0.0,
            "clean_fraction": 0.0,
            "inconsistent_fraction": 0.0,
            "longest_abnormal_run_fraction": 0.0,
            "internal_abnormal_fraction": 0.0,
            "recovered_gap_fraction": 0.0,
            "longest_unrecovered_gap_fraction": 0.0,
            "effective_support_fraction": 0.0,
            "effective_continuity_fraction": 0.0,
            "robust_offset_stability_fraction": 0.0,
            "robust_tangent": None,
            "robust_tangent_estimator": "NONE",
            "piecewise_jump_crossing_compatible": False,
            "crossing_aware": False,
        }

    supported = [
        bool(item.associated_support and item.center_offset_px is not None)
        for item in samples
    ]
    crossing = [
        bool(supported[index] and item.junction_or_crossing_evidence)
        for index, item in enumerate(samples)
    ]
    states = [
        StraightWindowState.CROSSING.value
        if crossing[index]
        else (
            StraightWindowState.CLEAN.value
            if supported[index]
            else StraightWindowState.INCONSISTENT.value
        )
        for index in range(sample_count)
    ]

    offsets = [
        float(item.center_offset_px)
        for index, item in enumerate(samples)
        if supported[index] and item.center_offset_px is not None
    ]
    offset_median = _median_or_none(offsets)
    offset_tolerance_px = max(
        1.5,
        trajectory.estimated_stroke_width_px
        * thresholds.crossing_offset_tolerance_widths,
    )
    abnormal = [
        bool(
            supported[index]
            and offset_median is not None
            and samples[index].center_offset_px is not None
            and abs(float(samples[index].center_offset_px) - offset_median)
            > offset_tolerance_px
        )
        for index in range(sample_count)
    ]
    endpoint_abnormal = set[int]()
    endpoint_limit = max(
        1, int(sample_count * thresholds.crossing_max_endpoint_window_fraction)
    )
    for boundary, step in ((0, 1), (sample_count - 1, -1)):
        candidates = [
            index
            for index in range(
                boundary,
                max(-1, boundary + step * endpoint_limit),
                step,
            )
            if abnormal[index]
        ]
        if not candidates:
            continue
        last = candidates[-1] if step < 0 else candidates[0]
        region = range(
            boundary,
            last + step,
            step,
        )
        if all(crossing[index] or not supported[index] for index in region) and any(
            crossing[index] for index in region
        ):
            endpoint_abnormal.update(region)

    recovered = set[int]()
    for start, end in _runs([not value for value in supported]):
        run_fraction = (end - start + 1) / sample_count
        if (
            start == 0
            or end == sample_count - 1
            or run_fraction > thresholds.crossing_max_gap_fraction
            or not crossing[start - 1]
            or not crossing[end + 1]
        ):
            continue
        neighbor_count = thresholds.crossing_neighbor_window_count
        before = [
            float(samples[index].center_offset_px)
            for index in range(max(0, start - neighbor_count), start)
            if supported[index] and samples[index].center_offset_px is not None
        ]
        after = [
            float(samples[index].center_offset_px)
            for index in range(
                end + 1, min(sample_count, end + neighbor_count + 1)
            )
            if supported[index] and samples[index].center_offset_px is not None
        ]
        if len(before) < 2 or len(after) < 2:
            continue
        if abs(float(np.median(before)) - float(np.median(after))) <= offset_tolerance_px:
            recovered.update(range(start, end + 1))
            for index in range(start, end + 1):
                states[index] = StraightWindowState.CROSSING.value

    for start, end in _runs(abnormal):
        run_fraction = (end - start + 1) / sample_count
        crossing_only = all(crossing[index] for index in range(start, end + 1))
        neighbor_count = thresholds.crossing_neighbor_window_count
        before = [
            float(samples[index].center_offset_px)
            for index in range(max(0, start - neighbor_count), start)
            if supported[index] and not abnormal[index]
            and samples[index].center_offset_px is not None
        ]
        after = [
            float(samples[index].center_offset_px)
            for index in range(
                end + 1, min(sample_count, end + neighbor_count + 1)
            )
            if supported[index] and not abnormal[index]
            and samples[index].center_offset_px is not None
        ]
        bounded_by_same_trajectory = bool(
            before
            and after
            and abs(float(np.median(before)) - float(np.median(after)))
            <= offset_tolerance_px
        )
        endpoint_contamination = (
            crossing_only
            and run_fraction <= thresholds.crossing_max_endpoint_window_fraction
            and (start == 0 or end == sample_count - 1)
        )
        local_contamination = (
            crossing_only
            and run_fraction <= thresholds.crossing_max_local_window_fraction
            and bounded_by_same_trajectory
        )
        endpoint_region_contamination = all(
            index in endpoint_abnormal for index in range(start, end + 1)
        )
        if endpoint_contamination or endpoint_region_contamination or local_contamination:
            for index in range(start, end + 1):
                states[index] = StraightWindowState.CROSSING.value
        else:
            for index in range(start, end + 1):
                states[index] = StraightWindowState.INCONSISTENT.value

    effective_supported = [
        supported[index] or index in recovered for index in range(sample_count)
    ]
    if recovered:
        effective_support_fraction = sum(effective_supported) / sample_count
        max_step = max(1.5, trajectory.estimated_stroke_width_px * 1.25)
        continuity: list[bool] = []
        for index in range(sample_count - 1):
            if not effective_supported[index] or not effective_supported[index + 1]:
                continuity.append(False)
            elif index in recovered or index + 1 in recovered:
                continuity.append(True)
            else:
                left, right = samples[index], samples[index + 1]
                continuity.append(
                    left.center_offset_px is not None
                    and right.center_offset_px is not None
                    and abs(right.center_offset_px - left.center_offset_px)
                    <= max_step
                )
        effective_continuity_fraction = sum(continuity) / max(1, len(continuity))
    else:
        effective_support_fraction = trajectory.associated_support_fraction
        effective_continuity_fraction = trajectory.local_continuity_fraction

    longest_unrecovered = 0
    current = 0
    for value in effective_supported:
        if value:
            longest_unrecovered = max(longest_unrecovered, current)
            current = 0
        else:
            current += 1
    longest_unrecovered = max(longest_unrecovered, current)
    longest_unrecovered_gap_fraction = longest_unrecovered / sample_count

    finite_bins = [
        float(value) for value in trajectory.offset_bin_medians_px if value is not None
    ]
    bin_median = _median_or_none(finite_bins)
    robust_offset_stability_fraction = (
        sum(abs(value - float(bin_median)) <= offset_tolerance_px for value in finite_bins)
        / len(finite_bins)
        if finite_bins and bin_median is not None
        else 0.0
    )

    clean_tangents = [
        float(item.local_tangent_delta_degrees)
        for index, item in enumerate(samples)
        if supported[index]
        and not crossing[index]
        and item.local_tangent_delta_degrees is not None
    ]
    all_tangents = [
        float(item.local_tangent_delta_degrees)
        for index, item in enumerate(samples)
        if supported[index] and item.local_tangent_delta_degrees is not None
    ]
    minimum_clean_samples = max(5, int(np.ceil(sample_count * 0.10)))
    if len(clean_tangents) >= minimum_clean_samples:
        robust_tangent = float(np.percentile(np.asarray(clean_tangents), 95.0))
        robust_tangent_estimator = "CLEAN_WINDOW_P95"
    elif all_tangents:
        robust_tangent = float(np.median(np.asarray(all_tangents)))
        robust_tangent_estimator = "ALL_SUPPORT_MEDIAN"
    else:
        robust_tangent = None
        robust_tangent_estimator = "NONE"

    abnormal_runs = _runs(abnormal)
    internal_abnormal_count = sum(
        abnormal[index]
        and index not in endpoint_abnormal
        for index in range(sample_count)
    )
    internal_abnormal = internal_abnormal_count / sample_count
    longest_abnormal_run_fraction = max(
        ((end - start + 1) / sample_count for start, end in abnormal_runs),
        default=0.0,
    )

    bin_states: list[list[str]] = [[] for _ in range(8)]
    for index, state in enumerate(states):
        bin_states[_sample_bin(index, sample_count)].append(state)
    jump_indices = [
        index
        for index, (left, right) in enumerate(
            zip(trajectory.offset_bin_medians_px, trajectory.offset_bin_medians_px[1:])
        )
        if left is not None
        and right is not None
        and abs(float(right) - float(left))
        / max(trajectory.estimated_stroke_width_px, 1e-6)
        >= thresholds.rejected_piecewise_jump_widths
    ]
    piecewise_jump_crossing_compatible = True
    for index in jump_indices:
        boundary_jump = index in (0, 6)
        surrounding_states = bin_states[index] + bin_states[index + 1]
        crossing_only = bool(surrounding_states) and all(
            state == StraightWindowState.CROSSING.value
            for state in surrounding_states
        )
        if not boundary_jump and internal_abnormal > thresholds.crossing_max_internal_abnormal_fraction:
            piecewise_jump_crossing_compatible = False
        elif not boundary_jump:
            left_context = trajectory.offset_bin_medians_px[index - 1] if index else None
            right_context = (
                trajectory.offset_bin_medians_px[index + 2]
                if index + 2 < len(trajectory.offset_bin_medians_px)
                else None
            )
            context_agrees = (
                left_context is not None
                and right_context is not None
                and abs(float(left_context) - float(right_context)) <= offset_tolerance_px
            )
            if not (crossing_only and context_agrees):
                piecewise_jump_crossing_compatible = False
        elif not crossing_only:
            piecewise_jump_crossing_compatible = False

    crossing_present = (
        sum(crossing) / sample_count >= thresholds.crossing_minimum_fraction
        or bool(recovered)
    )
    # The credible-window test is supplied by evidence_from_trajectory after
    # this helper returns.  Keep the geometric profile independent of that
    # derived scalar here.
    crossing_aware = bool(
        crossing_present
        and effective_support_fraction >= thresholds.minimum_support_fraction
        and effective_continuity_fraction >= thresholds.minimum_continuity_fraction
        and robust_offset_stability_fraction >= thresholds.crossing_stable_bin_fraction
        and (robust_tangent is not None)
        and robust_tangent < thresholds.rejected_tangent_deviation_degrees
        and internal_abnormal <= thresholds.crossing_max_internal_abnormal_fraction
        and piecewise_jump_crossing_compatible
    )
    return {
        "states": tuple(states),
        "crossing_fraction": sum(
            state == StraightWindowState.CROSSING.value for state in states
        )
        / sample_count,
        "clean_fraction": sum(
            state == StraightWindowState.CLEAN.value for state in states
        )
        / sample_count,
        "inconsistent_fraction": sum(
            state == StraightWindowState.INCONSISTENT.value for state in states
        )
        / sample_count,
        "longest_abnormal_run_fraction": longest_abnormal_run_fraction,
        "internal_abnormal_fraction": internal_abnormal,
        "recovered_gap_fraction": len(recovered) / sample_count,
        "longest_unrecovered_gap_fraction": longest_unrecovered_gap_fraction,
        "effective_support_fraction": effective_support_fraction,
        "effective_continuity_fraction": effective_continuity_fraction,
        "robust_offset_stability_fraction": robust_offset_stability_fraction,
        "robust_tangent": robust_tangent,
        "robust_tangent_estimator": robust_tangent_estimator,
        "piecewise_jump_crossing_compatible": piecewise_jump_crossing_compatible,
        "crossing_aware": crossing_aware,
    }


def evidence_from_trajectory(
    trajectory: CoherenceEvidence,
    *,
    thresholds: StraightValidityThresholds = DEFAULT_THRESHOLDS,
) -> StraightValidityEvidence:
    """Derive straightness-specific evidence from the existing local profile."""

    bins = [
        float(value)
        for value in trajectory.offset_bin_medians_px
        if value is not None
    ]
    if bins:
        median = float(np.median(np.asarray(bins, dtype=np.float64)))
        tolerance = max(1.5, trajectory.length_px * 0.025)
        credible = sum(abs(value - median) <= tolerance for value in bins) / len(bins)
        drift = max(bins) - min(bins)
        switch_limit = max(
            thresholds.switch_minimum_px,
            trajectory.length_px * thresholds.switch_length_fraction,
        )
        switches = sum(
            abs(right - left) >= switch_limit
            for left, right in pairwise(bins)
        )
    else:
        credible = 0.0
        drift = 0.0
        switches = 0
    crossing = _crossing_profile(trajectory, thresholds=thresholds)
    crossing_aware = bool(
        crossing["crossing_aware"]
        and credible >= thresholds.crossing_stable_bin_fraction
    )
    return StraightValidityEvidence(
        trajectory=trajectory,
        support_run_count=_true_run_count(
            [sample.associated_support for sample in trajectory.samples]
        ),
        credible_straight_window_fraction=round(credible, 6),
        max_sustained_lateral_drift_px=round(drift, 6),
        max_sustained_lateral_drift_fraction=round(
            drift / max(trajectory.length_px, 1e-6), 6
        ),
        local_tangent_deviation_p95_degrees=(
            trajectory.local_tangent_delta_p95_degrees
        ),
        abrupt_support_identity_switches=switches,
        ridge_width_to_length_ratio=(
            round(trajectory.width_median_px / trajectory.length_px, 6)
            if trajectory.width_median_px is not None
            else None
        ),
        usable_trajectory_window_count=len(bins),
        crossing_contaminated_window_fraction=round(
            crossing["crossing_fraction"], 6
        ),
        clean_straight_window_fraction=round(crossing["clean_fraction"], 6),
        trajectory_inconsistent_window_fraction=round(
            crossing["inconsistent_fraction"], 6
        ),
        longest_abnormal_run_fraction=round(
            crossing["longest_abnormal_run_fraction"], 6
        ),
        internal_abnormal_window_fraction=round(
            crossing["internal_abnormal_fraction"], 6
        ),
        crossing_recovered_gap_fraction=round(
            crossing["recovered_gap_fraction"], 6
        ),
        longest_unrecovered_gap_fraction=round(
            crossing["longest_unrecovered_gap_fraction"], 6
        ),
        effective_support_fraction=round(
            crossing["effective_support_fraction"], 6
        ),
        effective_continuity_fraction=round(
            crossing["effective_continuity_fraction"], 6
        ),
        robust_offset_stability_fraction=round(
            crossing["robust_offset_stability_fraction"], 6
        ),
        robust_tangent_deviation_p95_degrees=(
            round(crossing["robust_tangent"], 6)
            if crossing["robust_tangent"] is not None
            else None
        ),
        robust_tangent_estimator=crossing["robust_tangent_estimator"],
        piecewise_jump_crossing_compatible=bool(
            crossing["piecewise_jump_crossing_compatible"]
        ),
        crossing_aware_straight_window=crossing_aware,
        window_states=crossing["states"],
    )


def decision_from_straight_evidence(
    evidence: StraightValidityEvidence,
    *,
    thresholds: StraightValidityThresholds = DEFAULT_THRESHOLDS,
) -> StraightValidityDecision:
    trajectory = evidence.trajectory
    raw_support_fraction = trajectory.associated_support_fraction
    raw_tangent = evidence.local_tangent_deviation_p95_degrees or 0.0
    raw_jump = trajectory.max_sustained_offset_jump_widths or 0.0
    raw_gap_failure = (
        trajectory.longest_disjoint_interval_fraction
        >= thresholds.rejected_gap_fraction
        and raw_support_fraction >= 0.45
    )
    raw_piecewise_failure = raw_jump >= thresholds.rejected_piecewise_jump_widths
    raw_curved_failure = (
        evidence.max_sustained_lateral_drift_px >= thresholds.rejected_drift_px
        and evidence.max_sustained_lateral_drift_fraction
        >= thresholds.rejected_drift_fraction
        and raw_tangent >= thresholds.rejected_tangent_deviation_degrees
        and evidence.credible_straight_window_fraction < 0.80
    )
    raw_boundary_failure = (
        evidence.abrupt_support_identity_switches > 0
        and evidence.credible_straight_window_fraction
        < thresholds.minimum_credible_window_fraction
    )
    crossing_correction = bool(
        evidence.crossing_aware_straight_window
        and (
            raw_gap_failure
            or raw_piecewise_failure
            or raw_curved_failure
            or raw_boundary_failure
        )
    )
    support_fraction = (
        evidence.effective_support_fraction
        if crossing_correction
        else raw_support_fraction
    )
    continuity_fraction = (
        evidence.effective_continuity_fraction
        if crossing_correction
        else trajectory.local_continuity_fraction
    )
    tangent = (
        evidence.robust_tangent_deviation_p95_degrees
        if crossing_correction
        else raw_tangent
    ) or 0.0
    jump = 0.0 if crossing_correction else raw_jump

    if (
        evidence.longest_unrecovered_gap_fraction
        >= thresholds.rejected_gap_fraction
        and support_fraction >= 0.45
    ):
        status = StraightValidityStatus.REJECTED
        reason = StraightValidityReason.INSUFFICIENT_SUPPORT
    elif jump >= thresholds.rejected_piecewise_jump_widths:
        status = StraightValidityStatus.REJECTED
        reason = StraightValidityReason.PIECEWISE
    elif (
        evidence.max_sustained_lateral_drift_px >= thresholds.rejected_drift_px
        and evidence.max_sustained_lateral_drift_fraction
        >= thresholds.rejected_drift_fraction
        and tangent >= thresholds.rejected_tangent_deviation_degrees
        and evidence.credible_straight_window_fraction < 0.80
    ):
        status = StraightValidityStatus.REJECTED
        reason = StraightValidityReason.CURVED
    elif (
        evidence.abrupt_support_identity_switches > 0
        and evidence.credible_straight_window_fraction
        < thresholds.minimum_credible_window_fraction
    ):
        status = StraightValidityStatus.REJECTED
        reason = StraightValidityReason.BOUNDARY_SWITCH
    elif (
        evidence.max_sustained_lateral_drift_px >= 1.75
        and tangent >= 3.0
    ):
        # Mild curvature and scan wobble overlap.  Keep this region explicitly
        # uncertain unless the stronger, scale-aware rejection test above fires.
        status = StraightValidityStatus.UNCERTAIN
        reason = StraightValidityReason.INSUFFICIENT_EVIDENCE
    elif (
        support_fraction >= thresholds.minimum_support_fraction
        and continuity_fraction >= thresholds.minimum_continuity_fraction
        and evidence.credible_straight_window_fraction
        >= thresholds.minimum_credible_window_fraction
        and tangent <= thresholds.supported_tangent_deviation_degrees
        and evidence.abrupt_support_identity_switches == 0
    ):
        status = StraightValidityStatus.SUPPORTED
        reason = StraightValidityReason.CONFIRMED
    else:
        status = StraightValidityStatus.UNCERTAIN
        reason = (
            StraightValidityReason.INSUFFICIENT_SUPPORT
            if support_fraction < thresholds.minimum_support_fraction
            else StraightValidityReason.INSUFFICIENT_EVIDENCE
        )
    return StraightValidityDecision(status=status, reason=reason, evidence=evidence)


def assess_straight_primitive_validity(
    gray: np.ndarray,
    geometry: Mapping[str, Sequence[float]],
    *,
    thresholds: StraightValidityThresholds = DEFAULT_THRESHOLDS,
) -> StraightValidityDecision:
    trajectory = build_coherence_profile(gray, geometry)
    evidence = evidence_from_trajectory(trajectory, thresholds=thresholds)
    return decision_from_straight_evidence(evidence, thresholds=thresholds)


def qualify_dev_straight_primitives(
    gray: np.ndarray,
    primitives: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Bucket DEV raw primitives without changing geometry or prior verdicts."""

    buckets: dict[str, list[dict[str, Any]]] = {
        "supported": [],
        "uncertain": [],
        "rejected": [],
    }
    for primitive in primitives:
        geometry = primitive.get("raw_geometry", primitive)
        decision = assess_straight_primitive_validity(gray, geometry)
        item = dict(primitive)
        item["straight_primitive_validity"] = decision.to_dict()
        bucket = {
            StraightValidityStatus.SUPPORTED: "supported",
            StraightValidityStatus.UNCERTAIN: "uncertain",
            StraightValidityStatus.REJECTED: "rejected",
        }[decision.status]
        buckets[bucket].append(item)
    return buckets


__all__ = [
    "DEFAULT_THRESHOLDS",
    "StraightValidityDecision",
    "StraightValidityEvidence",
    "StraightValidityReason",
    "StraightValidityStatus",
    "StraightValidityThresholds",
    "StraightWindowState",
    "assess_straight_primitive_validity",
    "decision_from_straight_evidence",
    "evidence_from_trajectory",
    "qualify_dev_straight_primitives",
]
