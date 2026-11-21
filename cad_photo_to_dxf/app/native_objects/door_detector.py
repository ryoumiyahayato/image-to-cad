"""Automatic source-supported single/double-swing doors for frozen quarter.

No hand-entered object coordinates, template placement or old conversion run.
LSD straight observations propose leaf radii; both endpoints and both swing
directions are tested against the original 200 dpi scan.  A proposal needs a
supported quarter arc, matching full radial leaf, a mostly open closing line,
and source-supported wall continuations at both sides of the complete opening.
LSD observations are proposals, not source endpoints: the actual source stroke
axis is measured before jointly fitting a circle whose centre lies on that
axis. Double leaves have separate source-fitted radii and are paired only when
their opposing closing axes meet and both external jambs have source walls.
All coordinates in the evidence are original full-page pixels, y down.
"""

from __future__ import annotations

from .performance import profiled
import copy
from collections import Counter
from functools import lru_cache
import math
from pathlib import Path
import time

from contextvars import ContextVar
import cv2
import numpy as np

_CONTEXT = ContextVar("native_door_context")


class _ContextProxy:
    def __getattr__(self, name):
        return getattr(_CONTEXT.get(), name)


common = _ContextProxy()


VERSION = "source_endpoint_bounded_joint_double_door_v3"
# Search ranges describe this automatic proposal bank, not physical door sizes.
# They do not remove any original content or relax the frozen geometric bounds.
SEARCH = {
    "minimum_leaf_radius_px": 36.0,
    "maximum_leaf_radius_px": 260.0,
    "coarse_arc_samples": 48,
    "coarse_arc_support_min": 0.70,
    "final_arc_support_min": 0.97,
    "final_leaf_support_min": 0.97,
    "wall_stub_support_min": 0.75,
    "opening_white_fraction_min": 0.70,
    "other_three_quadrants_support_max": 0.45,
    "radial_refinement_band_px": 6.0,
    "radial_refinement_iterations": 3,
    "coarse_proposal_search_distance_px": 8.0,
    "maximum_leaf_seed_count": 14000,
    "sample_step_px": 0.75,
}


def _sample(field, points):
    p = np.asarray(points, dtype=float)
    shape = p.shape[:-1]
    p = p.reshape(-1, 2)
    x, y = p[:, 0], p[:, 1]
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    valid = (
        (ix >= 0) & (iy >= 0) & (ix + 1 < field.shape[1]) & (iy + 1 < field.shape[0])
    )
    result = np.full(len(p), 1e6, dtype=float)
    if valid.any():
        i, j = ix[valid], iy[valid]
        fx, fy = x[valid] - i, y[valid] - j
        result[valid] = (
            (1 - fx) * (1 - fy) * field[j, i]
            + fx * (1 - fy) * field[j, i + 1]
            + (1 - fx) * fy * field[j + 1, i]
            + fx * fy * field[j + 1, i + 1]
        )
    return result.reshape(shape)


def _support(field, points, tolerance, length):
    distances = _sample(field, points)
    supported = distances <= tolerance
    longest = run = 0
    for good in supported:
        run = 0 if good else run + 1
        longest = max(longest, run)
    step = length / max(1, len(points) - 1)
    return {
        "sample_count": len(points),
        "supported_fraction": float(np.mean(supported)),
        "maximum_source_distance_px": float(np.max(distances)),
        "longest_unsupported_run_px": float(longest * step),
        "source_distance_tolerance_px": float(tolerance),
    }


def _line_points(a, b, step=0.75):
    length = float(np.linalg.norm(np.asarray(b) - a))
    return np.linspace(a, b, max(2, int(math.ceil(length / step)) + 1)), length


def _arc_points(center, radius, angle, sweep, count=None):
    length = radius * abs(sweep)
    if count is None:
        count = max(24, int(math.ceil(length / SEARCH["sample_step_px"])) + 1)
    theta = np.linspace(angle, angle + sweep, count)
    return center + radius * np.column_stack((np.cos(theta), np.sin(theta))), length


@lru_cache(maxsize=8)
def _source_run_means(offset_values):
    """Exact old np.mean for every contiguous interval of fixed offsets.

    Do not replace mean with an endpoint average: that changes floating point
    tie behaviour for general offsets. The small cache stores read-only arrays.
    """
    offsets = np.asarray(offset_values, dtype=np.float64)
    count = len(offsets)
    means = np.full((count, count + 1), np.nan, dtype=np.float64)
    for start in range(count):
        for stop in range(start + 1, count + 1):
            means[start, stop] = np.mean(offsets[start:stop])
    means.setflags(write=False)
    return means


def _nearest_source_runs(distances, offsets):
    """Batch the old closest contiguous support-run choice, without fitting.

    Order is exactly abs(mean), then longest run, then its original position.
    Returned rows remain ascending so coordinate arithmetic retains its order.
    Start/stop indices are returned as auditable evidence of the chosen groups.
    """
    supported = np.asarray(distances) <= 0.65
    starts_mask = supported.copy()
    starts_mask[:, 1:] &= ~supported[:, :-1]
    stops_mask = supported.copy()
    stops_mask[:, :-1] &= ~supported[:, 1:]
    rows, starts = np.nonzero(starts_mask)
    _, last = np.nonzero(stops_mask)
    stops = last + 1
    if not len(rows):
        return rows, starts, stops, np.empty(0, dtype=np.float64)
    means = _source_run_means(tuple(np.asarray(offsets, dtype=np.float64)))[
        starts, stops
    ]
    order = np.lexsort((starts, -(stops - starts), np.abs(means), rows))
    sorted_rows = rows[order]
    selected = order[np.r_[True, sorted_rows[1:] != sorted_rows[:-1]]]
    return rows[selected], starts[selected], stops[selected], means[selected]


@profiled("door_detector._source_axis")
def _source_axis(a, b, field, tolerance, angular_bound):
    """Measure source ink centres, removing LSD's edge rather than axis bias.

    This changes no longitudinal endpoint position. Source-centred endpoints
    remain projections of the original LSD end stations; the final 3 px gate
    remains a bound on the jointly fitted circle/leaf endpoint displacement.
    """
    vector = b - a
    length = float(np.linalg.norm(vector))
    direction = vector / length
    normal = np.array([-direction[1], direction[0]])
    t = np.linspace(0.08, 0.92, 64)
    stations = a + t[:, None] * vector
    offsets = np.linspace(-tolerance, tolerance, 33)
    probe = stations[:, None, :] + offsets[None, :, None] * normal
    ds = _sample(field, probe)
    centres = []
    rows, _, _, means = _nearest_source_runs(ds, offsets)
    for row, mean in zip(rows, means):
        centres.append(stations[row] + float(mean) * normal)
    if len(centres) < 48:
        return (
            a,
            b,
            {
                "measured": False,
                "ink_centres": len(centres),
                "reason": "insufficient_source_axis_witnesses",
            },
        )
    points = np.asarray(centres)
    origin = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - origin, full_matrices=False)
    measured = vt[0]
    if measured @ direction < 0:
        measured = -measured
    adjustment = math.degrees(math.acos(float(np.clip(measured @ direction, -1, 1))))
    if adjustment > angular_bound:
        return (
            a,
            b,
            {
                "measured": False,
                "ink_centres": len(centres),
                "reason": "source_axis_direction_exceeds_frozen_adjustment_bound",
                "direction_adjustment_deg": adjustment,
            },
        )
    aa = origin + np.dot(a - origin, measured) * measured
    bb = origin + np.dot(b - origin, measured) * measured
    return (
        aa,
        bb,
        {
            "measured": True,
            "ink_centres": len(centres),
            "direction_adjustment_deg": adjustment,
            "normal_shift_endpoints_px": [
                float(np.linalg.norm(aa - a)),
                float(np.linalg.norm(bb - b)),
            ],
            "longitudinal_endpoint_extension_px": 0.0,
            "method": "closest_original_ink_centres_then_total_least_squares_no_snap",
        },
    )


@profiled("door_detector._refine_circle")
def _refine_circle(center, radius, angle, sweep, field):
    """Fit source circle jointly with the measured leaf axis, no direction snap."""
    c, r = np.asarray(center, dtype=float).copy(), float(radius)
    seed = c.copy()
    seed_r = r
    samples = np.linspace(angle, angle + sweep, 96)
    unit = np.column_stack((np.cos(samples), np.sin(samples)))
    offsets = np.linspace(
        -SEARCH["radial_refinement_band_px"], SEARCH["radial_refinement_band_px"], 33
    )
    used = 0
    for _ in range(SEARCH["radial_refinement_iterations"]):
        points = c[None, None, :] + (r + offsets)[None, :, None] * unit[:, None, :]
        distances = _sample(field, points)
        fit_points = []
        rows, _, _, means = _nearest_source_runs(distances, offsets)
        for i, mean in zip(rows, means):
            offset = float(mean)
            fit_points.append(c + (r + offset) * unit[i])
        used = len(fit_points)
        if used < 48:
            break
        p = np.asarray(fit_points)
        # The circle centre must lie on the measured radial leaf source axis.
        # Free 2D circle fitting in v1 could move the hinge off that line.
        q = p - seed
        leaf_unit = np.array([math.cos(angle), math.sin(angle)])
        bound = (
            common.CONFIG["tolerances_frozen_before_recognition"]["line_endpoint_px"]
            - 1e-7
        )
        # Search only the endpoint-feasible domain: centre shift=t;
        # tip shift=t+r-seed_r.  Both are independently bounded by 3 px.
        # This is candidate fitting under the existing constraint, not a
        # relaxed post-hoc endpoint criterion.
        shifts = np.linspace(-bound, bound, 61)
        lengths = np.linalg.norm(
            q[None, :, :] - shifts[:, None, None] * leaf_unit, axis=2
        )
        radii = np.mean(lengths, axis=1)
        radii = np.clip(radii, seed_r - bound - shifts, seed_r + bound - shifts)
        error = np.mean((lengths - radii[:, None]) ** 2, axis=1)
        best = int(np.argmin(error))
        proposed_c = seed + shifts[best] * leaf_unit
        proposed_r = float(radii[best])
        # This is only an algorithmic trust region.  The final frozen source
        # and endpoint bounds below remain authoritative.
        if np.linalg.norm(proposed_c - seed) > 6.0 or abs(proposed_r - seed_r) > 6.0:
            break
        c, r = proposed_c, proposed_r
    return (
        c,
        r,
        {
            "radial_ink_centres_used": used,
            "seed_center_shift_px": float(np.linalg.norm(c - seed)),
            "seed_radius_change_px": float(r - seed_r),
            "circle_center_constrained_to_measured_leaf_axis": True,
            "both_leaf_endpoints_constrained_during_fit": True,
        },
    )


def _opening_context(field, center, radius, closing_angle, tolerance):
    direction = np.array([math.cos(closing_angle), math.sin(closing_angle)])
    normal = np.array([-direction[1], direction[0]])
    opening, opening_length = _line_points(
        center + 0.12 * radius * direction, center + 0.88 * radius * direction
    )
    opening_distance = _sample(field, opening)
    white_fraction = float(np.mean(opening_distance > tolerance))
    near = max(5.0, 0.08 * radius)
    far = max(18.0, 0.32 * radius)
    left, length = _line_points(center - far * direction, center - near * direction)
    right, _ = _line_points(
        center + (radius + near) * direction, center + (radius + far) * direction
    )
    limit = min(20.0, max(5.0, 0.16 * radius))
    offsets = np.arange(-math.floor(limit), math.floor(limit) + 1, dtype=float)
    choices = []
    for offset in offsets:
        left_support = _support(field, left + offset * normal, tolerance, length)
        right_support = _support(field, right + offset * normal, tolerance, length)
        key = (
            min(
                left_support["supported_fraction"], right_support["supported_fraction"]
            ),
            left_support["supported_fraction"] + right_support["supported_fraction"],
            -abs(offset),
        )
        choices.append((key, float(offset), left_support, right_support))
    _, offset, lhs, rhs = max(choices, key=lambda item: item[0])
    return {
        "opening_white_fraction": white_fraction,
        "opening_interior_test_fraction": [0.12, 0.88],
        "wall_continuation_normal_offset_px": offset,
        "hinge_side_wall_stub": lhs,
        "latch_side_wall_stub": rhs,
        "wall_stub_near_px": near,
        "wall_stub_far_px": far,
        "closing_axis_direction_image": direction.tolist(),
        "closing_endpoint_local": (center + radius * direction).tolist(),
    }


def _candidate_bbox(center, radius, angle, sweep, offset):
    arc, _ = _arc_points(center, radius, angle, sweep, count=91)
    points = np.vstack((arc, center)) + offset
    return [
        float(points[:, 0].min()),
        float(points[:, 1].min()),
        float(points[:, 0].max()),
        float(points[:, 1].max()),
    ]


def _similar(a, b):
    ga, gb = a["geometry"], b["geometry"]
    angle = abs(
        (ga["leaf_angle_deg_image"] - gb["leaf_angle_deg_image"] + 180) % 360 - 180
    )
    return (
        np.linalg.norm(np.asarray(ga["hinge"]) - gb["hinge"]) <= 4.0
        and abs(ga["radius_px"] - gb["radius_px"]) <= 4.0
        and angle <= 3.0
        and (ga["end_deg_image"] - ga["start_deg_image"])
        * (gb["end_deg_image"] - gb["start_deg_image"])
        > 0
    )


@profiled("door_detector._bounded_leaf_variants")
def _bounded_leaf_variants(row, field, offset, tol):
    """Retain feasible alternatives for joint opening constraints.

    An independently lowest-error circle need not be the feasible solution of
    a complete double door.  Enumerate only the existing endpoint box and
    re-evaluate all original-source gates before any alternative is paired.
    No original image pixels, tolerance or hand-selected location changes.
    """
    ev = row["source_evidence"]
    g = row["geometry"]
    a, b = np.asarray(ev["leaf_observed_endpoints_px"]) - offset
    length = float(np.linalg.norm(b - a))
    unit = (b - a) / length
    angle = math.atan2(unit[1], unit[0])
    sweep = math.radians(g["sweep_deg_image"])
    bound = tol["line_endpoint_px"] - 1e-7
    grid = np.linspace(-bound, bound, 7)
    result = []
    for hinge_shift in grid:
        center = a + hinge_shift * unit
        for tip_shift in grid:
            radius = length + tip_shift - hinge_shift
            arc, arclen = _arc_points(center, radius, angle, sweep)
            arc_support = _support(field, arc, tol["arc_radial_px"], arclen)
            if (
                arc_support["supported_fraction"] < SEARCH["final_arc_support_min"]
                or arc_support["longest_unsupported_run_px"]
                > tol["max_unexplained_line_gap_px"]
            ):
                continue
            tip = center + radius * unit
            line, linelen = _line_points(center, tip)
            support = _support(field, line, tol["line_perpendicular_px"], linelen)
            if (
                support["supported_fraction"] < SEARCH["final_leaf_support_min"]
                or support["longest_unsupported_run_px"]
                > tol["max_unexplained_line_gap_px"]
            ):
                continue
            other, otherlen = _arc_points(
                center, radius, angle + sweep, 3 * sweep, count=144
            )
            other_support = _support(field, other, tol["arc_radial_px"], otherlen)
            if (
                other_support["supported_fraction"]
                > SEARCH["other_three_quadrants_support_max"]
            ):
                continue
            bbox = _candidate_bbox(center, radius, angle, sweep, offset)
            x0, y0, x1, y1 = common.CONFIG["roi_xyxy_px"]
            if bbox[0] < x0 or bbox[1] < y0 or bbox[2] > x1 or bbox[3] > y1:
                continue
            item = copy.deepcopy(row)
            item["geometry"].update(
                hinge=(center + offset).tolist(), radius_px=float(radius)
            )
            item["bbox_xyxy_px"] = bbox
            item["rejection_reasons"] = []
            item["source_evidence"].update(
                leaf_model_endpoints_px=[
                    (center + offset).tolist(),
                    (tip + offset).tolist(),
                ],
                hinge_endpoint_shift_px=float(abs(hinge_shift)),
                leaf_tip_shift_px=float(abs(tip_shift)),
                quarter_arc=arc_support,
                radial_leaf=support,
                other_three_quadrants=other_support,
                opening_context=None,
                source_bbox_xyxy_px=bbox,
                circle_refinement={
                    "selected_solution": "joint_endpoint_feasible_grid",
                    "seed_center_shift_px": float(abs(hinge_shift)),
                    "seed_radius_change_px": float(radius - length),
                    "circle_center_constrained_to_measured_leaf_axis": True,
                    "both_leaf_endpoints_constrained_during_fit": True,
                    "initial_individual_fit": ev["circle_refinement"],
                },
                class_evidence="source quarter arc and radial leaf; wall and opening evidence is checked on the complete paired doorway",
                joint_endpoint_feasible_proposal={
                    "hinge_axis_shift_px": float(hinge_shift),
                    "tip_axis_shift_px": float(tip_shift),
                    "search_box_px": [-float(bound), float(bound)],
                    "grid_points_per_endpoint": 7,
                    "acceptance_unchanged": True,
                    "candidate_from_original_source_axis": True,
                },
            )
            item["ranking_score"] = (
                arc_support["supported_fraction"]
                + support["supported_fraction"]
                - 0.01 * (abs(hinge_shift) + abs(tip_shift))
            )
            result.append(item)
    return result


@profiled("door_detector._pair_double_leaves")
def _pair_double_leaves(leaves, field, offset, tol):
    """Test full source doorway, without assuming equal leaf radii."""
    observations = []
    for row in sorted(
        leaves,
        key=lambda r: (
            -r["ranking_score"],
            r["source_evidence"]["leaf_observation_id"],
        ),
    ):
        key = (
            row["source_evidence"]["leaf_observation_id"],
            row["geometry"]["sweep_deg_image"],
            tuple(row["source_evidence"]["leaf_observed_endpoints_px"][0]),
        )
        if not any(key == key2 for key2, _ in observations):
            observations.append((key, row))
    bank = [
        variant
        for _, row in observations
        for variant in _bounded_leaf_variants(row, field, offset, tol)
    ]
    proposals = []
    rejected = []
    cosine = math.cos(math.radians(tol["max_direction_adjustment_deg"]))
    for i, a in enumerate(bank):
        ga = a["geometry"]
        ha = np.asarray(ga["hinge"]) - offset
        aa = math.radians(ga["leaf_angle_deg_image"])
        ea = math.radians(ga["end_deg_image"])
        ua = np.array([math.cos(aa), math.sin(aa)])
        va = np.array([math.cos(ea), math.sin(ea)])
        for b in bank[i + 1 :]:
            if (
                a["source_evidence"]["leaf_observation_id"]
                == b["source_evidence"]["leaf_observation_id"]
            ):
                continue
            gb = b["geometry"]
            hb = np.asarray(gb["hinge"]) - offset
            ab = math.radians(gb["leaf_angle_deg_image"])
            eb = math.radians(gb["end_deg_image"])
            ub = np.array([math.cos(ab), math.sin(ab)])
            vb = np.array([math.cos(eb), math.sin(eb)])
            span = float(np.linalg.norm(hb - ha))
            if span < max(ga["radius_px"], gb["radius_px"]):
                continue
            if ua @ ub < cosine or va @ vb > -cosine:
                continue
            close_a = ha + ga["radius_px"] * va
            close_b = hb + gb["radius_px"] * vb
            meeting = float(np.linalg.norm(close_a - close_b))
            if meeting > 2 * tol["line_endpoint_px"]:
                continue
            axis = (hb - ha) / span
            metrics = {
                "closing_endpoint_separation_px": meeting,
                "opening_span_px": span,
                "leaf_radius_sum_px": ga["radius_px"] + gb["radius_px"],
                "unequal_source_radii_retained": True,
                "hinge_axis_to_first_closing_perpendicular_px": float(
                    abs(np.cross(axis, va)) * span
                ),
                "hinge_axis_to_second_closing_perpendicular_px": float(
                    abs(np.cross(axis, vb)) * span
                ),
                "parallel_leaf_axis_difference_deg": math.degrees(
                    math.acos(float(np.clip(ua @ ub, -1, 1)))
                ),
                "opposed_closing_axis_difference_deg": math.degrees(
                    math.acos(float(np.clip(-va @ vb, -1, 1)))
                ),
            }
            reasons = []
            if meeting > tol["line_endpoint_px"]:
                reasons.append("DOUBLE_LEAF_CLOSING_ENDPOINTS_EXCEED_FROZEN_BOUND")
            if abs(span - ga["radius_px"] - gb["radius_px"]) > tol["line_endpoint_px"]:
                reasons.append("DOUBLE_LEAF_RADII_DO_NOT_SPAN_OBSERVED_OPENING")
            if (
                max(
                    metrics["hinge_axis_to_first_closing_perpendicular_px"],
                    metrics["hinge_axis_to_second_closing_perpendicular_px"],
                )
                > tol["line_perpendicular_px"]
            ):
                reasons.append("DOUBLE_LEAF_CLOSING_AXES_NOT_ALIGNED_WITH_HINGES")
            if va @ axis <= 0 or vb @ axis >= 0:
                reasons.append("DOUBLE_LEAVES_CLOSE_AWAY_FROM_EACH_OTHER")
            ctx = _opening_context(
                field,
                ha,
                span,
                math.atan2(axis[1], axis[0]),
                tol["line_perpendicular_px"],
            )
            if ctx["opening_white_fraction"] < SEARCH["opening_white_fraction_min"]:
                reasons.append("COMPLETE_DOUBLE_DOOR_SPAN_NOT_AN_OBSERVED_OPENING")
            if any(
                ctx[k]["supported_fraction"] < SEARCH["wall_stub_support_min"]
                or ctx[k]["longest_unsupported_run_px"]
                > tol["max_unexplained_line_gap_px"]
                for k in ("hinge_side_wall_stub", "latch_side_wall_stub")
            ):
                reasons.append("DOUBLE_DOOR_EXTERNAL_WALL_CONTEXT_NOT_ESTABLISHED")
            source_ids = [
                a["source_evidence"]["leaf_observation_id"],
                b["source_evidence"]["leaf_observation_id"],
            ]
            if reasons:
                rejected.append(
                    {
                        "leaf_observation_ids": source_ids,
                        "pair_metrics": metrics,
                        "opening_context": ctx,
                        "rejection_reasons": reasons,
                    }
                )
                continue
            bounds = [
                min(a["bbox_xyxy_px"][0], b["bbox_xyxy_px"][0]),
                min(a["bbox_xyxy_px"][1], b["bbox_xyxy_px"][1]),
                max(a["bbox_xyxy_px"][2], b["bbox_xyxy_px"][2]),
                max(a["bbox_xyxy_px"][3], b["bbox_xyxy_px"][3]),
            ]
            proposals.append(
                {
                    "kind": "DOOR",
                    "layer": "DOOR",
                    "template": "DOOR_DOUBLE_SWING",
                    "geometry": {"leaves": [ga, gb], "hinge": ga["hinge"]},
                    "bbox_xyxy_px": bounds,
                    "ranking_score": a["ranking_score"] + b["ranking_score"],
                    "source_evidence": {
                        "algorithm": VERSION,
                        "source_sha256": common.CONFIG["source_sha256"],
                        "leaf_observation_ids": source_ids,
                        "leaf_evidence": [a["source_evidence"], b["source_evidence"]],
                        "pair_metrics": metrics,
                        "complete_opening_context": ctx,
                        "class_evidence": "two source quarters with opposing collinear closing axes, meeting tips, matched radial leaves, and both external source wall continuations",
                        "human_trace_or_seed_coordinate": False,
                        "engineering_width_calibrated": False,
                    },
                    "rejection_reasons": [],
                }
            )
    result = []
    used = set()
    for row in sorted(
        proposals,
        key=lambda r: (
            -r["ranking_score"],
            r["source_evidence"]["leaf_observation_ids"],
        ),
    ):
        ids = set(row["source_evidence"]["leaf_observation_ids"])
        if used & ids:
            continue
        if any(
            any(
                _similar({"geometry": g}, {"geometry": p})
                for g in row["geometry"]["leaves"]
                for p in other["geometry"]["leaves"]
            )
            for other in result
        ):
            continue
        result.append(row)
        used.update(ids)
    return result, rejected, bank


def run(out=None):
    started = time.perf_counter()
    cv2.setNumThreads(1)
    cfg = common.CONFIG
    bounds = cfg["roi_xyxy_px"]
    ctx = cfg["context_px"]
    if common.sha(common.ROOT / cfg["source"]) != cfg["source_sha256"]:
        raise ValueError("Frozen original source changed")
    image = common.source_image()
    x0, y0, x1, y1 = bounds
    left, top = max(0, x0 - ctx), max(0, y0 - ctx)
    right, bottom = min(image.shape[1], x1 + ctx), min(image.shape[0], y1 + ctx)
    gray = image[top:bottom, left:right]
    offset = np.array([left, top], dtype=float)
    distance = cv2.distanceTransform(
        (gray >= 128).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    detected = lsd.detect(gray)[0]
    rows = [] if detected is None else detected.reshape(-1, 4).tolist()
    seeds = []
    for index, row in enumerate(rows):
        a, b = np.asarray(row[:2]), np.asarray(row[2:])
        length = float(np.linalg.norm(b - a))
        if (
            SEARCH["minimum_leaf_radius_px"]
            <= length
            <= SEARCH["maximum_leaf_radius_px"]
        ):
            seeds.append((index, a, b, length))
    seeds.sort(key=lambda row: (-row[3], row[0]))
    omitted = max(0, len(seeds) - SEARCH["maximum_leaf_seed_count"])
    seeds = seeds[: SEARCH["maximum_leaf_seed_count"]]
    tol = cfg["tolerances_frozen_before_recognition"]
    arc_tol, line_tol = tol["arc_radial_px"], tol["line_perpendicular_px"]
    gap_limit = tol["max_unexplained_line_gap_px"]
    counters = Counter()
    accepted = []
    reviews = []
    primitive_pass = []
    for seed_index, a, b, length in seeds:
        original_a, original_b = a.copy(), b.copy()
        a, b, axis_evidence = _source_axis(
            a, b, distance, line_tol, tol["max_direction_adjustment_deg"]
        )
        length = float(np.linalg.norm(b - a))
        for hinge, leaf_tip in ((a, b), (b, a)):
            original_hinge, original_tip = (
                (original_a, original_b)
                if np.linalg.norm(hinge - a) < 1e-6
                else (original_b, original_a)
            )
            direction = (leaf_tip - hinge) / length
            angle = math.atan2(direction[1], direction[0])
            for sign in (-1, 1):
                counters["leaf_arc_tests"] += 1
                sweep = sign * math.pi / 2
                coarse, _ = _arc_points(
                    hinge, length, angle, sweep, count=SEARCH["coarse_arc_samples"]
                )
                # A broad search annulus only generates fits. Final source
                # validation below still uses the frozen 2.5 px radial bound.
                if (
                    float(
                        np.mean(
                            _sample(distance, coarse)
                            <= SEARCH["coarse_proposal_search_distance_px"]
                        )
                    )
                    < SEARCH["coarse_arc_support_min"]
                ):
                    counters["coarse_arc_rejected"] += 1
                    continue
                center, radius, refinement = _refine_circle(
                    hinge, length, angle, sweep, distance
                )
                arc, arc_length = _arc_points(center, radius, angle, sweep)
                arc_support = _support(distance, arc, arc_tol, arc_length)
                final_tip = center + radius * direction
                leaf, leaf_length = _line_points(center, final_tip)
                leaf_support = _support(distance, leaf, line_tol, leaf_length)
                other, other_length = _arc_points(
                    center, radius, angle + sweep, sign * 3 * math.pi / 2, count=144
                )
                other_support = _support(distance, other, arc_tol, other_length)
                bbox = _candidate_bbox(center, radius, angle, sweep, offset)
                hinge_delta = float(np.linalg.norm(center - hinge))
                tip_delta = float(np.linalg.norm(final_tip - leaf_tip))
                failures = []
                if (
                    arc_support["supported_fraction"] < SEARCH["final_arc_support_min"]
                    or arc_support["longest_unsupported_run_px"] > gap_limit
                ):
                    failures.append("QUARTER_ARC_NOT_CONTINUOUSLY_SOURCE_SUPPORTED")
                if (
                    leaf_support["supported_fraction"]
                    < SEARCH["final_leaf_support_min"]
                    or leaf_support["longest_unsupported_run_px"] > gap_limit
                ):
                    failures.append("FULL_RADIAL_LEAF_NOT_SOURCE_SUPPORTED")
                if max(hinge_delta, tip_delta) > tol["line_endpoint_px"]:
                    failures.append(
                        "CIRCLE_LEAF_ENDPOINT_RELATION_EXCEEDS_FROZEN_BOUND"
                    )
                if (
                    other_support["supported_fraction"]
                    > SEARCH["other_three_quadrants_support_max"]
                ):
                    failures.append("SOURCE_CURVE_EXTENDS_BEYOND_A_DOOR_QUARTER_ARC")
                if bbox[0] < x0 or bbox[1] < y0 or bbox[2] > x1 or bbox[3] > y1:
                    failures.append("WHOLE_OBJECT_CROSSES_FROZEN_ROI")
                primitive_failures = list(failures)
                context = None
                if not failures:
                    context = _opening_context(
                        distance, center, radius, angle + sweep, line_tol
                    )
                    if (
                        context["opening_white_fraction"]
                        < SEARCH["opening_white_fraction_min"]
                    ):
                        failures.append("CLOSING_SPAN_NOT_AN_OBSERVED_OPENING")
                    if any(
                        context[k]["supported_fraction"]
                        < SEARCH["wall_stub_support_min"]
                        or context[k]["longest_unsupported_run_px"] > gap_limit
                        for k in ("hinge_side_wall_stub", "latch_side_wall_stub")
                    ):
                        failures.append(
                            "TWO_SIDED_WALL_OPENING_CONTEXT_NOT_ESTABLISHED"
                        )
                full_center = center + offset
                full_tip = final_tip + offset
                row = {
                    "kind": "DOOR",
                    "layer": "DOOR",
                    "bbox_xyxy_px": bbox,
                    "geometry": {
                        "hinge": full_center.tolist(),
                        "radius_px": float(radius),
                        "start_deg_image": math.degrees(angle),
                        "end_deg_image": math.degrees(angle + sweep),
                        "leaf_angle_deg_image": math.degrees(angle),
                        "sweep_deg_image": 90 * sign,
                        "swing_direction_image": "clockwise"
                        if sign > 0
                        else "counterclockwise",
                    },
                    "source_evidence": {
                        "algorithm": VERSION,
                        "source_sha256": cfg["source_sha256"],
                        "leaf_observation_id": f"LSD-{seed_index:06d}",
                        "leaf_observed_endpoints_px": [
                            (hinge + offset).tolist(),
                            (leaf_tip + offset).tolist(),
                        ],
                        "original_lsd_edge_endpoints_px": [
                            (original_hinge + offset).tolist(),
                            (original_tip + offset).tolist(),
                        ],
                        "source_leaf_axis_measurement": axis_evidence,
                        "leaf_model_endpoints_px": [
                            full_center.tolist(),
                            full_tip.tolist(),
                        ],
                        "hinge_endpoint_shift_px": hinge_delta,
                        "leaf_tip_shift_px": tip_delta,
                        "swing_direction_image": "clockwise"
                        if sign > 0
                        else "counterclockwise",
                        "quarter_arc": arc_support,
                        "radial_leaf": leaf_support,
                        "other_three_quadrants": other_support,
                        "circle_refinement": refinement,
                        "opening_context": context,
                        "source_bbox_xyxy_px": bbox,
                        "class_evidence": "quarter circular swing plus radial leaf and both source wall stubs; no character-based classification",
                        "engineering_width_calibrated": False,
                        "human_trace_or_seed_coordinate": False,
                    },
                    "rejection_reasons": failures,
                }
                score = (
                    arc_support["supported_fraction"]
                    + leaf_support["supported_fraction"]
                    - 0.01 * (hinge_delta + tip_delta)
                )
                row["ranking_score"] = float(score)
                if not primitive_failures or primitive_failures == [
                    "CIRCLE_LEAF_ENDPOINT_RELATION_EXCEEDS_FROZEN_BOUND"
                ]:
                    primitive_pass.append(row)
                if failures:
                    counters.update(failures)
                    reviews.append(row)
                else:
                    accepted.append(row)
    # Alternate LSD edges describe one candidate.  Keep one actual INSERT
    # proposal; duplicates remain in the evidence, never emitted twice.
    objects, pair_rejections, pair_bank = _pair_double_leaves(
        primitive_pass, distance, offset, tol
    )
    for i, row in enumerate(objects):
        row["id"] = f"DOOR-{i + 1:03d}"
        row["status"] = "AUTOMATIC_NATIVE_BLOCK_PROPOSAL_PENDING_INDEPENDENT_REVIEW"
    paired_leaves = [
        {"geometry": g} for obj in objects for g in obj["geometry"]["leaves"]
    ]
    duplicate = []
    singles = []
    for row in sorted(
        accepted,
        key=lambda r: (
            -r["ranking_score"],
            r["source_evidence"]["leaf_observation_id"],
            r["geometry"]["start_deg_image"],
        ),
    ):
        if any(_similar(row, g) for g in paired_leaves):
            duplicate.append(
                {
                    "observation": row["source_evidence"]["leaf_observation_id"],
                    "retained_object": "complete_double_door",
                    "geometry": row["geometry"],
                }
            )
            continue
        peer = next((o for o in singles if _similar(row, o)), None)
        if peer is not None:
            duplicate.append(
                {
                    "observation": row["source_evidence"]["leaf_observation_id"],
                    "retained_object": peer["id"],
                    "geometry": row["geometry"],
                }
            )
            continue
        row["id"] = f"DOOR-{len(objects) + 1:03d}"
        row["status"] = "AUTOMATIC_NATIVE_BLOCK_PROPOSAL_PENDING_INDEPENDENT_REVIEW"
        row["template"] = "DOOR_SINGLE_SWING"
        objects.append(row)
        singles.append(row)
    uncertainties = []
    for row in sorted(
        reviews,
        key=lambda r: (
            -r["ranking_score"],
            r["source_evidence"]["leaf_observation_id"],
        ),
    ):
        if any(_similar(row, o) for o in singles + paired_leaves) or any(
            _similar(row, o) for o in uncertainties
        ):
            continue
        row["id"] = f"DOOR-REVIEW-{len(uncertainties) + 1:03d}"
        row["status"] = "UNCERTAIN_DOOR_GEOMETRY_LEAVE_FORMAL_LAYER_BLANK"
        row["reason"] = "; ".join(row["rejection_reasons"])
        uncertainties.append(row)
    result = {
        "schema": "quarter-native-objects-v1",
        "algorithm": VERSION,
        "objects": objects,
        "uncertainties": uncertainties,
        "provenance": {
            "source": cfg["source"],
            "source_sha256": cfg["source_sha256"],
            "algorithm_source_sha256": common.sha(Path(__file__)),
            "quarter_config_sha256": common.config_sha256,
            "roi_xyxy_px": bounds,
            "context_xyxy_px": [left, top, right, bottom],
            "coordinate_system": "original_full_page_pixel_centres_y_down",
            "algorithm_parameters": SEARCH,
            "source_tolerances": tol,
            "detected_straight_observations": len(rows),
            "eligible_leaf_seeds": len(seeds),
            "leaf_seeds_omitted_by_capacity": omitted,
            "decision_counts": dict(counters),
            "duplicate_accepted_observations": duplicate,
            "double_leaf_primitive_bank_count": len(pair_bank),
            "double_leaf_pair_rejections": pair_rejections,
            "detector_does_not_claim_complete_door_inventory": True,
            "fire_classification": "NOT_ESTABLISHED_NO_SAME_DRAWING_LEGEND",
            "output_is_not_CAD_open_or_engineer_acceptance": True,
        },
        "resources": common.metric(started),
    }
    output = Path(out) if out else common.ROOT / "evidence/door_objects.json"
    common.dump(output, result)
    print(
        {
            "output": str(output),
            "door_proposals": len(objects),
            "uncertainties": len(uncertainties),
            "resources": result["resources"],
        },
        flush=True,
    )
    return result


@profiled("door_detector.detect_doors")
def detect_doors(gray, roi, output_dir, source_path):
    from types import SimpleNamespace
    import hashlib
    import json
    from .contracts import TOLERANCES, save_json

    source_path = Path(source_path).resolve()
    cfg = {
        "source": str(source_path),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "roi_xyxy_px": list(roi),
        "context_px": 160,
        "tolerances_frozen_before_recognition": TOLERANCES,
    }
    context = SimpleNamespace(
        CONFIG=cfg,
        ROOT=source_path.parent,
        source_image=lambda: gray,
        sha=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest(),
        dump=save_json,
        metric=lambda start: {"wall_seconds": time.perf_counter() - start},
        config_sha256=hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()
        ).hexdigest(),
    )
    token = _CONTEXT.set(context)
    try:
        return run(Path(output_dir) / "door_proposals.json")
    finally:
        _CONTEXT.reset(token)
