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


def near_overlap(first, second):
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
    deviation = max(abs(float((qa - c) @ vn)), abs(float((qb - c) @ vn)))
    if deviation > 2:
        return None
    return {
        "first_length_px": length,
        "second_length_px": other,
        "first_overlap_interval_px": list(overlap),
        "normal_deviation_px": deviation,
        "overlap_fraction_of_shorter": (overlap[1] - overlap[0]) / min(length, other),
    }


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


def replacement_support(gray, first, second, *, support_geometry=None):
    """Return justified parameter spans of ``first`` represented by ``second``.

    No OCR or source fitting is performed. A real white separation between two
    distinct nearest strokes vetoes replacement even when both fit tolerances
    overlap. Non-covered spans remain independent source responsibility.
    """
    relation = near_overlap(first, second)
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
    ts = np.linspace(lo, hi, max(2, int(math.ceil((hi - lo) / 0.5)) + 1))
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
    source_to_second, _ = distance_to_members(source)
    normal = np.array([-v[1], v[0]])
    normal_separation = np.abs((source - other_source) @ normal)
    middle = np.rint((source + other_source) / 2).astype(int)
    white = gray[middle[:, 1], middle[:, 0]] >= 128
    separators = (normal_separation >= 1.5) & white
    supported = distances <= 2
    covered = supported & (source_to_second <= 2) & ~separators
    step = (hi - lo) / (len(ts) - 1)
    changes = np.diff(np.r_[False, ~covered, False].astype(np.int8))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    gap = float(max(ends - starts, default=0) * step)
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
    return {
        **relation,
        "eligible": bool(intervals),
        "covered_intervals_px": intervals,
        "whole_overlap_replaced": whole,
        "source_supported_fraction": float(np.mean(supported)),
        "same_stroke_covered_fraction": fraction,
        "maximum_uncovered_gap_px": gap,
        "actual_white_separator_sample_count": int(separators.sum()),
        "uncovered_sample_count": int((~covered).sum()),
        "sample_count": len(ts),
        "nearest_source_samples_sha256": hashlib.sha256(
            source.astype("<i8").tobytes()
        ).hexdigest(),
        "uncovered_source_pixels": np.unique(source[~covered], axis=0)
        .astype(int)
        .tolist(),
        "source_pixels_modified": False,
        "source_thresholds_changed": False,
    }
