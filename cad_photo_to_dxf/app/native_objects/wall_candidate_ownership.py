"""Account for alternative wall fits using the unchanged source strokes.

Near coordinates alone never authorize withdrawal.  Each replacement retains
the nearest source samples, actual intervening white pixels and any unsupported
span.  The 2 px / 98 percent / 5 px bounds are the existing line source gate.
"""

from __future__ import annotations

import hashlib
import math
import numpy as np
from scipy.spatial import cKDTree


SOURCE_LOCALIZATION_PX = 2.0


def _parallel_overlap(first, second):
    a, b = (np.asarray(first[k], float) for k in ("start", "end"))
    c, d = (np.asarray(second[k], float) for k in ("start", "end"))
    length, other = float(np.linalg.norm(b - a)), float(np.linalg.norm(d - c))
    if not length or not other:
        return None
    u, v = (b - a) / length, (d - c) / other
    if abs(float(u @ v)) < math.cos(math.radians(0.5)):
        return None
    lo, hi = sorted((float((c - a) @ u), float((d - a) @ u)))
    overlap = (max(0.0, lo), min(length, hi))
    if overlap[1] <= overlap[0]:
        return None
    # Compare at the overlapping span; a long source line may have a short
    # wall span without extending that wall into its neighboring objects.
    qa, qb = a + overlap[0] * u, a + overlap[1] * u
    vn = np.array([-v[1], v[0]])
    signed = [float((qa - c) @ vn), float((qb - c) @ vn)]
    deviation = max(map(abs, signed))
    minimum_deviation = 0.0 if signed[0] * signed[1] <= 0 else min(map(abs, signed))
    return {
        "first_length_px": length,
        "second_length_px": other,
        "first_overlap_interval_px": list(overlap),
        "normal_deviation_px": deviation,
        "minimum_normal_deviation_px": minimum_deviation,
        "overlap_fraction_of_shorter": (overlap[1] - overlap[0]) / min(length, other),
    }


def near_overlap(first, second):
    """Keep the existing geometric screen used to admit alternate wall fits."""
    relation = _parallel_overlap(first, second)
    if relation and relation["normal_deviation_px"] <= SOURCE_LOCALIZATION_PX:
        return relation
    return None


def source_overlap_candidate(first, second):
    """Screen for possible shared source support, never authorize retirement.

    Two fits each within the unchanged 2 px source gate can be up to 2+2 px
    apart. This triangle-inequality bound only avoids impossible comparisons;
    actual common original pixels and white-separator vetoes decide ownership.
    A maximum deviation over a long fit must not veto a supported local span.
    """
    relation = _parallel_overlap(first, second)
    if (
        relation
        and relation["minimum_normal_deviation_px"] <= 2 * SOURCE_LOCALIZATION_PX
    ):
        return relation
    return None


def _source_tree(gray, first, second):
    points = np.asarray(
        [first["start"], first["end"], second["start"], second["end"]], float
    )
    low = np.maximum(0, np.floor(points.min(axis=0)).astype(int) - 4)
    high = np.minimum(
        [gray.shape[1], gray.shape[0]], np.ceil(points.max(axis=0)).astype(int) + 5
    )
    yy, xx = np.nonzero(gray[low[1] : high[1], low[0] : high[0]] < 128)
    ink = np.column_stack((xx + low[0], yy + low[1]))
    return ink, cKDTree(ink) if len(ink) else None


def replacement_support(
    gray,
    first,
    second,
    *,
    support_geometry=None,
    include_sample_evidence=False,
    sample_step_px=0.5,
):
    """Return justified parameter spans of ``first`` represented by ``second``.

    No OCR or source fitting is performed. A real white separation between two
    distinct nearest strokes vetoes replacement even when both fit tolerances
    overlap. Non-covered spans remain independent source responsibility.
    """
    if not 0 < sample_step_px <= 0.5:
        raise ValueError("SOURCE_OWNERSHIP_SAMPLING_MUST_NOT_BE_COARSER_THAN_0_5_PX")
    relation = source_overlap_candidate(first, second)
    if relation is None:
        return {
            "eligible": False,
            "covered_intervals_px": [],
            "reason": "NO_NEAR_COLLINEAR_OVERLAP",
        }
    a, b = np.asarray(first["start"], float), np.asarray(first["end"], float)
    c, d = np.asarray(second["start"], float), np.asarray(second["end"], float)
    length, other = relation["first_length_px"], relation["second_length_px"]
    u, v = (b - a) / length, (d - c) / other
    lo, hi = relation["first_overlap_interval_px"]
    # Numerical endpoint variations may refer to the same real endpoint.
    # Extending this responsibility needs actual source checks below.
    support_geometry = support_geometry or [second]

    def distance_to_members(points):
        all_distances = []
        all_projections = []
        for geometry in support_geometry:
            start, end = (
                np.asarray(geometry["start"], float),
                np.asarray(geometry["end"], float),
            )
            delta = end - start
            size = float(np.linalg.norm(delta))
            direction = delta / size
            position = np.clip((points - start) @ direction, 0.0, size)
            projection = start + position[:, None] * direction
            all_projections.append(projection)
            all_distances.append(np.linalg.norm(points - projection, axis=1))
        distances = np.asarray(all_distances)
        choice = distances.argmin(axis=0)
        projections = np.asarray(all_projections)[choice, np.arange(len(points))]
        return distances.min(axis=0), projections

    endpoint_distances, _ = distance_to_members(np.asarray([a, b]))
    if endpoint_distances[0] <= 2:
        lo = 0.0
    if endpoint_distances[1] <= 2:
        hi = length
    ts = np.linspace(lo, hi, max(2, int(math.ceil((hi - lo) / sample_step_px)) + 1))
    samples = a + ts[:, None] * u
    _, projected = distance_to_members(samples)
    ink, tree = _source_tree(gray, first, second)
    if tree is None:
        return {
            **relation,
            "eligible": False,
            "covered_intervals_px": [],
            "reason": "NO_SOURCE_INK",
        }
    distances, indices = tree.query(samples)
    _, second_indices = tree.query(projected)
    source, other_source = ink[indices], ink[second_indices]
    normal = np.array([-v[1], v[0]])
    normal_separation = np.abs((source - other_source) @ normal)
    middle = np.rint((source + other_source) / 2).astype(int)
    white = gray[middle[:, 1], middle[:, 0]] >= 128
    separators = (normal_separation >= 1.5) & white
    supported = distances <= SOURCE_LOCALIZATION_PX
    # The nearest ink pixel is not a stroke identity. On a multi-pixel stroke,
    # one fit can be nearest to one side and the other fit to its adjacent side.
    # Require an actual common original ink pixel within the unchanged 2 px of
    # both fits instead of imposing a third, asymmetric nearest-pixel-to-fit
    # constraint. A real white separation between their own nearest supports
    # still vetoes replacement, even when localization neighborhoods overlap.
    ink_to_members, _ = distance_to_members(ink)
    common_ink = ink[ink_to_members <= SOURCE_LOCALIZATION_PX]
    if len(common_ink):
        common_distances, common_indices = cKDTree(common_ink).query(samples)
        common_source = common_ink[common_indices]
        common_to_second, _ = distance_to_members(common_source)
    else:
        common_distances = np.full(len(samples), np.inf)
        common_source = np.empty((0, 2), dtype=np.int64)
        common_to_second = np.full(len(samples), np.inf)
    common_supported = common_distances <= SOURCE_LOCALIZATION_PX
    covered = supported & common_supported & ~separators
    step = (hi - lo) / (len(ts) - 1)
    changes = np.diff(np.r_[False, ~covered, False].astype(np.int8))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    gap = float(max(ends - starts, default=0) * step)
    missing_changes = np.diff(np.r_[False, ~common_supported, False].astype(np.int8))
    missing_starts = np.flatnonzero(missing_changes == 1)
    missing_ends = np.flatnonzero(missing_changes == -1)
    missing_common_gap = float(max(missing_ends - missing_starts, default=0) * step)
    fraction = float(np.mean(covered))
    whole = fraction >= 0.98 and gap <= 5 and not bool(separators.any())
    intervals = []
    if whole:
        intervals = [[float(lo), float(hi)]]
    else:
        # Keep a full existing localization neighborhood around every
        # non-covered sample; do not replace a real short foreign fragment.
        unsafe = np.zeros(len(ts), bool)
        radius = int(math.ceil(2 / max(step, 1e-9)))
        for index in np.flatnonzero(~covered):
            unsafe[max(0, index - radius) : min(len(ts), index + radius + 1)] = True
        changes = np.diff(np.r_[False, ~unsafe, False].astype(np.int8))
        for begin, end in zip(
            np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        ):
            left, right = float(ts[begin]), float(ts[end - 1])
            if right > left:
                intervals.append([left, right])
        # Select one continuous justified replacement span. Isolated small
        # coincidences in an otherwise different neighboring stroke do not
        # authorize punching several holes in that source object's identity.
        if intervals:
            intervals = [max(intervals, key=lambda span: span[1] - span[0])]
    # Beyond the old geometric screen, only complete-overlap source ownership
    # is established enough for automatic withdrawal. A partly supported wider
    # hypothesis must not split an independently valid old line into small
    # remainders that fail the unchanged source gate and revoke another wall.
    # Keep its local evidence as pending instead of broadening the gate or
    # pretending those intervals have already been transferred.
    pending_intervals = []
    if not whole and relation["normal_deviation_px"] > SOURCE_LOCALIZATION_PX:
        pending_intervals = intervals
        intervals = []
    result = {
        **relation,
        "eligible": bool(intervals),
        "covered_intervals_px": intervals,
        "whole_overlap_replaced": whole,
        "pending_supported_intervals_px": pending_intervals,
        "pending_reason": "WIDER_FIT_REQUIRES_COMPLETE_OVERLAP_SOURCE_RESPONSIBILITY"
        if pending_intervals
        else None,
        "source_supported_fraction": float(np.mean(supported)),
        "same_stroke_covered_fraction": fraction,
        "maximum_uncovered_gap_px": gap,
        "actual_white_separator_sample_count": int(separators.sum()),
        "uncovered_sample_count": int((~covered).sum()),
        "sample_count": len(ts),
        "sampled_interval_px": [float(lo), float(hi)],
        "maximum_sample_step_px": sample_step_px,
        "nearest_source_samples_sha256": hashlib.sha256(
            source.astype("<i8").tobytes()
        ).hexdigest(),
        "common_original_source_witnesses_sha256": hashlib.sha256(
            common_source[common_supported].astype("<i8").tobytes()
            if len(common_source)
            else b""
        ).hexdigest(),
        "common_source_witness_count": int(common_supported.sum()),
        "covered_sample_count_after_white_veto": int(covered.sum()),
        "missing_common_source_witness_sample_count": int((~common_supported).sum()),
        "maximum_missing_common_source_witness_gap_px": missing_common_gap,
        "first_fit_to_common_source_max_px": float(
            common_distances[common_supported].max()
        )
        if common_supported.any()
        else None,
        "replacement_to_common_source_max_px": float(
            common_to_second[common_supported].max()
        )
        if common_supported.any()
        else None,
        "ownership_basis": "COMMON_ORIGINAL_INK_WITHIN_EACH_UNCHANGED_SOURCE_GATE",
        "uncovered_source_pixels": np.unique(source[~covered], axis=0)
        .astype(int)
        .tolist(),
        "source_pixels_modified": False,
        "source_thresholds_changed": False,
    }
    if include_sample_evidence:
        result["source_witness_samples"] = [
            {
                "sample_index": index,
                "first_parameter_px": float(ts[index]),
                "first_sample": samples[index].tolist(),
                "first_nearest_original_pixel": source[index].astype(int).tolist(),
                "replacement_nearest_original_pixel": other_source[index]
                .astype(int)
                .tolist(),
                "nearest_support_midpoint_pixel": middle[index].tolist(),
                "nearest_support_midpoint_gray": int(
                    gray[middle[index, 1], middle[index, 0]]
                ),
                "common_original_source_pixel": common_source[index]
                .astype(int)
                .tolist()
                if common_supported[index]
                else None,
                "literal_source_gray": int(
                    gray[common_source[index, 1], common_source[index, 0]]
                )
                if common_supported[index]
                else None,
                "first_fit_to_common_source_px": float(common_distances[index])
                if common_supported[index]
                else None,
                "replacement_to_common_source_px": float(common_to_second[index])
                if common_supported[index]
                else None,
                "white_separator_veto": bool(separators[index]),
                "covered": bool(covered[index]),
            }
            for index in range(len(ts))
        ]
    return result
