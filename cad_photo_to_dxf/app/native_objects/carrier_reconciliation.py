"""Replace proved whole duplicate receiving lines from unchanged source ink.

Two nearby old lines are only candidates.  Adoption requires the same thin
source stroke over their full extents, two separately observed return strokes,
and no straight continuation beyond either return.  Ink shared with a crossing
stroke at an old extrapolated end does not assign that crossing to the carrier.
The caller discovers receiving IDs from ordinary structural contact discovery;
IDs, source positions and recognition labels never decide source ownership.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import json
import math

import numpy as np
from scipy.ndimage import distance_transform_edt

from .circle_endpoint_contacts import _segment_cells
from .contracts import TOLERANCES, stable_id
from .geometry import fit_source, source_support


SCHEMA = "source-existing-carrier-reconciliation-v1"
EVIDENCE_SCHEMA = "source-whole-reconciled-carrier-v1"
POLICY = {
    "version": "whole-thin-source-stroke-with-independent-end-returns-v1",
    "source_threshold": 128,
    "minimum_length_px": 48.0,
    "maximum_candidate_angle_deg": TOLERANCES["max_direction_adjustment_deg"],
    "maximum_candidate_normal_px": 4.0,
    "minimum_mutual_overlap_fraction": 0.90,
    "source_station_step_px": 0.5,
    "source_normal_step_px": 0.25,
    "source_profile_radius_px": 8.0,
    "maximum_thin_run_width_px": 5.0,
    "maximum_center_residual_px": 1.5,
    "minimum_thin_source_fraction": 0.70,
    "minimum_transverse_competitor_span_px": 4.0,
    "minimum_transverse_competitor_angle_deg": 20.0,
    "minimum_return_span_px": 24.0,
    "return_start_normal_px": 6.0,
    "return_search_radius_px": 24.0,
    "maximum_return_angle_deviation_deg": 8.0,
    "maximum_return_residual_px": 1.0,
    "maximum_existing_return_angle_deg": 3.0,
    "maximum_return_tracking_step_px": 1.5,
    "maximum_endpoint_transition_px": 24.0,
    "maximum_endpoint_source_cap_px": TOLERANCES["line_endpoint_px"],
    "maximum_external_probe_px": 48.0,
    "minimum_external_white_run_px": TOLERANCES["opening_minimum_preserved_px"],
    "strict_source_normal_px": 1.0,
    "minimum_strict_source_fraction": 0.98,
    "partial_old_line_retirement_permitted": False,
    "source_pixels_modified": False,
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _binding(obj):
    return {key: deepcopy(obj[key]) for key in ("id", "kind", "layer", "geometry")}


def _line(obj):
    pts = np.asarray([obj["geometry"][k] for k in ("start", "end")], float)
    vector = pts[1] - pts[0]
    length = float(np.linalg.norm(vector))
    if not np.all(np.isfinite(pts)) or length <= 0:
        raise ValueError("CARRIER_NONFINITE_OR_ZERO_LENGTH_LINE")
    if vector[int(np.argmax(np.abs(vector)))] < 0:
        pts = pts[::-1].copy()
    return pts, length


def _angle(a, b):
    return math.degrees(math.acos(float(np.clip(abs(a @ b), -1.0, 1.0))))


def _candidate(a, b):
    if a.get("kind") != "LINE" or b.get("kind") != "LINE":
        return None
    aa, al = _line(a)
    bb, bl = _line(b)
    if min(al, bl) < POLICY["minimum_length_px"]:
        return None
    u, v = (aa[1] - aa[0]) / al, (bb[1] - bb[0]) / bl
    normal = np.array([-u[1], u[0]])
    positions = (bb - aa[0]) @ u
    overlap = max(0.0, min(al, positions[1]) - max(0.0, positions[0]))
    angle = _angle(u, v)
    residual = float(np.max(np.abs((bb - aa[0]) @ normal)))
    if (
        angle > POLICY["maximum_candidate_angle_deg"]
        or residual > POLICY["maximum_candidate_normal_px"]
        or overlap / max(al, bl) < POLICY["minimum_mutual_overlap_fraction"]
    ):
        return None
    return {
        "angle_deg": angle,
        "maximum_normal_separation_px": residual,
        "mutual_overlap_fraction": overlap / max(al, bl),
        "whole_lengths_px": [al, bl],
    }


def _ink(gray, points):
    index = np.floor(np.asarray(points) + 0.5).astype(int)
    inside = (
        (index[..., 0] >= 0)
        & (index[..., 0] < gray.shape[1])
        & (index[..., 1] >= 0)
        & (index[..., 1] < gray.shape[0])
    )
    result = np.zeros(inside.shape, bool)
    result[inside] = (
        gray[index[..., 1][inside], index[..., 0][inside]] < POLICY["source_threshold"]
    )
    return result


def _runs(values, coordinates, step):
    changes = np.diff(np.r_[False, values, False].astype(np.int8))
    rows = []
    for lo, hi in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)):
        rows.append(
            {
                "lo": float(coordinates[lo] - step / 2),
                "hi": float(coordinates[hi - 1] + step / 2),
                "center": float((coordinates[lo] + coordinates[hi - 1]) / 2),
                "width": float((hi - lo) * step),
                "clipped": bool(lo == 0 or hi == len(values)),
            }
        )
    return rows


def _band_hits(gray, points, normal, radius):
    offsets = np.arange(-radius, radius + 0.001, POLICY["source_normal_step_px"])
    return _ink(
        gray, np.asarray(points)[:, None, :] + offsets[None, :, None] * normal
    ).any(axis=1)


def _source_support(gray, a, b):
    lo = np.maximum(0, np.floor(np.minimum(a, b) - 5).astype(int))
    hi = np.minimum(
        [gray.shape[1], gray.shape[0]], np.ceil(np.maximum(a, b) + 6).astype(int)
    )
    distance = distance_transform_edt(
        gray[lo[1] : hi[1], lo[0] : hi[0]] >= POLICY["source_threshold"]
    )
    result = source_support(a, b, distance, lo, step=0.25)
    result["pass"] = bool(
        result["supported_fraction"] >= 0.98
        and result["maximum_white_gap_px"] <= TOLERANCES["max_unexplained_line_gap_px"]
    )
    return result


def _transverse_competitor(profiles, index, selected):
    """A crossing's departing ink is not a second parallel line owner.

    Follow the actual separate cross-section run in both directions.  A short
    parallel spur or another unresolved alternative fails; a certified branch
    must merge into the shared track or leave the observed normal corridor and
    have a measured nonparallel tangent.  It remains an independent source
    responsibility, never part of the replacement geometry.
    """
    step = POLICY["source_station_step_px"]
    start = profiles[index][selected]
    observed, stops = [(index * step, start["center"])], []
    for direction in (-1, 1):
        previous = start
        for advance in range(1, 33):
            j = index + direction * advance
            if not 0 <= j < len(profiles):
                stops.append("OBSERVATION_BOUNDARY")
                break
            choices = [
                run
                for run in profiles[j]
                if abs(run["center"] - previous["center"]) <= 1.5
            ]
            if len(choices) != 1:
                stops.append("MISSING_OR_COMPETING_RUN")
                break
            current = choices[0]
            if current["lo"] <= 0 <= current["hi"]:
                observed.append((j * step, current["center"]))
                stops.append("MERGED_IN_ORIGINAL_COMMON_TRACK")
                break
            observed.append((j * step, current["center"]))
            if current["clipped"]:
                stops.append("LEFT_SOURCE_NORMAL_CORRIDOR")
                break
            previous = current
    samples = np.asarray(sorted(observed), float)
    span = float(np.ptp(samples[:, 0]))
    slope = float(np.polyfit(samples[:, 0], samples[:, 1], 1)[0]) if span else 0.0
    angle = abs(math.degrees(math.atan(slope)))
    passed = bool(
        span >= POLICY["minimum_transverse_competitor_span_px"]
        and angle >= POLICY["minimum_transverse_competitor_angle_deg"]
        and any(
            s in ("MERGED_IN_ORIGINAL_COMMON_TRACK", "LEFT_SOURCE_NORMAL_CORRIDOR")
            for s in stops
        )
        and not any(
            s in ("MISSING_OR_COMPETING_RUN", "OBSERVATION_BOUNDARY") for s in stops
        )
    )
    return {
        "pass": passed,
        "observed_station_normal_points_px": samples.tolist(),
        "span_px": span,
        "angle_to_carrier_deg": angle,
        "stops": stops,
        "source_branch_preserved_independently": True,
    }


def _same_source_profiles(gray, old, origin, u, length):
    normal = np.array([-u[1], u[0]])
    steps = np.arange(0.0, length + 0.001, POLICY["source_station_step_px"])
    offsets = np.arange(
        -POLICY["source_profile_radius_px"],
        POLICY["source_profile_radius_px"] + 0.001,
        POLICY["source_normal_step_px"],
    )
    points = origin + steps[:, None] * u
    ink = _ink(gray, points[:, None, :] + offsets[None, :, None] * normal)
    profiles = [_runs(row, offsets, POLICY["source_normal_step_px"]) for row in ink]
    finite = []
    for obj in old:
        pts, _ = _line(obj)
        t = (pts - origin) @ u
        z = (pts - origin) @ normal
        finite.append((t, z))
    thin, shared, compared, missing, different, samples = 0, 0, 0, [], [], []
    competitors = []
    for i, t in enumerate(steps):
        runs = profiles[i]
        selected = []
        active = []
        for projections, zs in finite:
            if t < projections[0] - 1e-7 or t > projections[1] + 1e-7:
                continue
            z = float(np.interp(t, projections, zs))
            distances = [max(run["lo"] - z, z - run["hi"], 0.0) for run in runs]
            if not distances:
                missing.append(float(t))
                continue
            least = min(distances)
            choices = [
                j for j, value in enumerate(distances) if abs(value - least) <= 1e-9
            ]
            if least > TOLERANCES["line_perpendicular_px"] or len(choices) != 1:
                missing.append(float(t))
                continue
            selected.append(choices[0])
            active.append(z)
        if len(active) == 2:
            compared += 1
            if len(set(selected)) != 1:
                central = min(selected, key=lambda j: abs(runs[j]["center"]))
                alternative = next(j for j in selected if j != central)
                proof = _transverse_competitor(profiles, i, alternative)
                competitors.append({"station_px": float(t), **proof})
                if (
                    abs(runs[central]["center"]) > POLICY["maximum_center_residual_px"]
                    or not proof["pass"]
                ):
                    different.append(float(t))
                    continue
                selected = [central, central]
            run = runs[selected[0]]
            if (
                not run["clipped"]
                and run["width"] <= POLICY["maximum_thin_run_width_px"]
                and abs(run["center"]) <= POLICY["maximum_center_residual_px"]
            ):
                thin += 1
                samples.append((points[i] + run["center"] * normal).tolist())
            else:
                shared += 1
    return {
        "pass": bool(
            compared
            and not different
            and thin / compared >= POLICY["minimum_thin_source_fraction"]
        ),
        "station_count": len(steps),
        "mutually_owned_station_count": compared,
        "same_unique_thin_run_count": thin,
        "shared_crossing_profile_count": shared,
        "distinct_original_runs_at_stations_px": different,
        "unsupported_or_ambiguous_stations_px": missing,
        "transverse_competitor_proofs": competitors,
        "same_thin_run_fraction": thin / max(1, compared),
        "thin_source_centers_px": samples,
        "all_source_profiles_examined": True,
        "connected_component_identity_used_as_ownership": False,
    }


def _return_candidates(gray, origin, u, expected, endpoints, inward):
    """Find a unique perpendicular source return and certify its finite end."""
    normal = np.array([-u[1], u[0]])
    radius = POLICY["return_search_radius_px"]
    ts = np.arange(min(endpoints) - radius, max(endpoints) + radius + 0.001, 0.5)
    ss = np.arange(
        POLICY["return_start_normal_px"],
        POLICY["return_start_normal_px"] + POLICY["minimum_return_span_px"] + 0.001,
        1.0,
    )
    found = []
    for side in (-1, 1):
        grid = origin + ts[None, :, None] * u + side * ss[:, None, None] * normal
        pixels = _ink(gray, grid)
        row_runs = [
            [
                run
                for run in _runs(row, ts, 0.5)
                if not run["clipped"]
                and run["width"] <= POLICY["maximum_thin_run_width_px"]
            ]
            for row in pixels
        ]
        for seed in row_runs[0]:
            tracked = [seed["center"]]
            for runs in row_runs[1:]:
                possible = [
                    run["center"]
                    for run in runs
                    if abs(run["center"] - tracked[-1])
                    <= POLICY["maximum_return_tracking_step_px"]
                ]
                if len(possible) != 1:
                    break
                tracked.append(possible[0])
            if len(tracked) != len(ss):
                continue
            slope, intercept = np.polyfit(side * ss, tracked, 1)
            fit = slope * side * ss + intercept
            residual = float(np.max(np.abs(np.asarray(tracked) - fit)))
            deviation = abs(math.degrees(math.atan(slope)))
            if (
                residual > POLICY["maximum_return_residual_px"]
                or deviation > POLICY["maximum_return_angle_deviation_deg"]
            ):
                continue
            t = float(intercept)
            point = origin + t * u
            if not _ink(gray, point[None, :])[0]:
                continue
            first_return = origin + tracked[0] * u + side * ss[0] * normal
            return_join_cells = _segment_cells(point, first_return)
            if not _ink(gray, np.asarray(return_join_cells, float)).all():
                continue
            inner_steps = np.arange(0, POLICY["minimum_return_span_px"] + 0.001, 0.25)
            inner = _band_hits(
                gray,
                point + inward * inner_steps[:, None] * u,
                normal,
                POLICY["strict_source_normal_px"],
            )
            if float(inner.mean()) < POLICY["minimum_strict_source_fraction"]:
                continue
            # All old endpoint projections must lie within this same bounded
            # transition.  A farther independent end is not silently discarded.
            extra = max(float(-inward * (v - t)) for v in endpoints)
            if extra > POLICY["maximum_endpoint_transition_px"]:
                continue
            probe = np.arange(0, POLICY["maximum_external_probe_px"] + 0.001, 0.25)
            outer_points = point - inward * probe[:, None] * u
            outer = _band_hits(
                gray, outer_points, normal, POLICY["strict_source_normal_px"]
            )
            white = _runs(~outer, probe, 0.25)
            white = [
                r
                for r in white
                if r["width"] >= POLICY["minimum_external_white_run_px"]
            ]
            if not white:
                continue
            first_white = white[0]
            departure = _outward_departure(
                gray, point, -inward * u, normal, first_white["lo"]
            )
            if not departure["pass"]:
                continue
            # Beyond the shared end core there must be no restored thin
            # collinear stroke in the bounded exterior observation.  A white
            # gap between real parallel/extending strokes stays explicit.
            after = outer[probe > first_white["hi"]]
            return_points = (
                origin + np.asarray(tracked)[:, None] * u + side * ss[:, None] * normal
            )
            found.append(
                {
                    "point_px": point.tolist(),
                    "projection_px": t,
                    "side": side,
                    "return_source_centers_px": return_points.tolist(),
                    "return_span_px": float(ss[-1] - ss[0]),
                    "return_join_original_closed_pixel_cells": return_join_cells,
                    "return_join_cells_all_original_ink": True,
                    "return_fit_maximum_residual_px": residual,
                    "return_angle_deviation_deg": deviation,
                    "inward_original_source_fraction": float(inner.mean()),
                    "exterior_first_white_interval_px": [
                        first_white["lo"],
                        first_white["hi"],
                    ],
                    "exterior_original_ink_hits": outer.tolist(),
                    "exterior_departure_proof": departure,
                    "independent_original_ink_beyond_white_run_preserved": bool(
                        np.any(after)
                    ),
                    "old_endpoint_projections_px": list(map(float, endpoints)),
                    "maximum_old_endpoint_extrapolation_px": max(0.0, extra),
                    "no_source_continuation_across_white_run": True,
                    "crossing_source_not_assigned_to_carrier": True,
                }
            )
    # Equivalent numerical seeds may follow the same source return.  Two
    # distinct return strokes remain competitors; no nearest-return choice.
    unique = []
    for row in found:
        if not any(
            row["side"] == other["side"]
            and abs(row["projection_px"] - other["projection_px"]) < 0.5
            for other in unique
        ):
            unique.append(row)
    return {
        "pass": len(unique) == 1,
        "candidate_returns": unique,
        "expected_old_endpoint_projection_px": float(expected),
        "reason": "UNIQUE_ORIGINAL_RETURN_AND_NO_FORWARD_STROKE"
        if len(unique) == 1
        else "END_RETURN_MISSING_OR_COMPETING",
    }


def _outward_departure(gray, point, outward, normal, first_white):
    """Reject a normal T with a short but real straight continuation.

    White somewhere beyond an end candidate is insufficient: an unchanged
    straight line can continue for several pixels before its actual endpoint.
    Any exterior ink beyond a localization cap must visibly depart along a
    nonparallel branch and leave the normal corridor, with no competing thin
    run continuing in the carrier direction.
    """
    if first_white <= POLICY["maximum_endpoint_source_cap_px"]:
        return {
            "pass": True,
            "kind": "NATURAL_SOURCE_CAP_BEFORE_CLEAR_WHITE",
            "first_white_px": float(first_white),
        }
    steps = np.arange(
        POLICY["maximum_endpoint_source_cap_px"],
        POLICY["maximum_external_probe_px"] + 0.001,
        0.5,
    )
    offsets = np.arange(
        -POLICY["source_profile_radius_px"],
        POLICY["source_profile_radius_px"] + 0.001,
        0.25,
    )
    profiles = [
        _runs(row, offsets, 0.25)
        for row in _ink(
            gray,
            point + steps[:, None, None] * outward + offsets[None, :, None] * normal,
        )
    ]
    first = [run for run in profiles[0] if run["lo"] <= 1.0 and run["hi"] >= -1.0]
    if len(first) != 1:
        return {"pass": False, "kind": "END_DEPARTURE_MISSING_OR_COMPETING_SOURCE"}
    previous = first[0]
    tracked = [(float(steps[0]), previous["center"])]
    terminal = "DID_NOT_LEAVE_SOURCE_NORMAL_CORRIDOR"
    competing = []
    for t, runs in zip(steps[1:], profiles[1:]):
        choices = [
            run for run in runs if abs(run["center"] - previous["center"]) <= 1.5
        ]
        if len(choices) != 1:
            terminal = "MISSING_OR_COMPETING_DEPARTURE_RUN"
            break
        current = choices[0]
        # A distinct thin run near the carrier axis remains a valid continuing
        # source even when a thicker diagonal also departs through the core.
        alternatives = [
            run
            for run in runs
            if run is not current
            and run["width"] <= POLICY["maximum_thin_run_width_px"]
            and abs(run["center"]) <= POLICY["maximum_center_residual_px"]
        ]
        if alternatives:
            competing.append(float(t))
        tracked.append((float(t), current["center"]))
        if current["clipped"]:
            terminal = "LEFT_SOURCE_NORMAL_CORRIDOR"
            break
        previous = current
    samples = np.asarray(tracked)
    span = float(np.ptp(samples[:, 0]))
    slope = float(np.polyfit(samples[:, 0], samples[:, 1], 1)[0]) if span else 0.0
    angle = abs(math.degrees(math.atan(slope)))
    passed = bool(
        span >= POLICY["minimum_transverse_competitor_span_px"]
        and angle >= POLICY["minimum_transverse_competitor_angle_deg"]
        and terminal == "LEFT_SOURCE_NORMAL_CORRIDOR"
        and not competing
    )
    return {
        "pass": passed,
        "kind": "NONPARALLEL_INDEPENDENT_END_CROSSING",
        "source_station_normal_points_px": samples.tolist(),
        "source_span_px": span,
        "departure_angle_deg": angle,
        "terminal": terminal,
        "competing_collinear_stations_px": competing,
        "departing_source_stroke_adopted_as_part_of_carrier": False,
    }


def _bind_existing_return(gray, corner, carrier_direction, prior_objects, excluded):
    """Intersect a source-matched finite return; never snap to the nearest line."""
    point = np.asarray(corner["point_px"], float)
    raw = np.asarray(corner["return_source_centers_px"], float)
    direction = raw[-1] - raw[0]
    direction /= np.linalg.norm(direction)
    matches, rejected = [], []
    for obj in prior_objects:
        if obj["id"] in excluded or obj["kind"] != "LINE":
            continue
        pts, length = _line(obj)
        unit = (pts[1] - pts[0]) / length
        normal = np.array([-unit[1], unit[0]])
        residual = np.abs((raw - pts[0]) @ normal)
        if (
            _angle(unit, direction) > POLICY["maximum_existing_return_angle_deg"]
            or residual.max() > POLICY["maximum_center_residual_px"]
        ):
            continue
        along = (raw - pts[0]) @ unit
        if along.min() < 0 or along.max() > length:
            continue
        try:
            travel, finite = np.linalg.solve(
                np.column_stack((carrier_direction, -unit)),
                pts[0] - point,
            )
        except np.linalg.LinAlgError:
            continue
        intersection = point + travel * carrier_direction
        if (
            not (0 <= finite <= length)
            or abs(travel) > POLICY["maximum_center_residual_px"]
        ):
            continue
        samples = np.linspace(*pts, max(2, int(np.ceil(length / 0.25)) + 1))
        strict_fraction = float(
            _band_hits(gray, samples, normal, POLICY["strict_source_normal_px"]).mean()
        )
        support = _source_support(gray, *pts)
        cells = _segment_cells(point, intersection)
        all_ink = bool(_ink(gray, np.asarray(cells, float)).all())
        row = {
            "object_binding": _binding(obj),
            "source_return_maximum_native_normal_px": float(residual.max()),
            "existing_return_whole_source_support": support,
            "existing_return_whole_strict_source_fraction": strict_fraction,
            "source_fit_point_px": point.tolist(),
            "finite_native_intersection_px": intersection.tolist(),
            "finite_return_projection_px": float(finite),
            "finite_return_length_px": length,
            "native_endpoint_adjustment_px": float(abs(travel)),
            "adjustment_original_closed_pixel_cells": cells,
            "adjustment_cells_all_original_ink": all_ink,
        }
        if (
            support["pass"]
            and strict_fraction >= POLICY["minimum_strict_source_fraction"]
            and all_ink
        ):
            matches.append(row)
        else:
            rejected.append(row)
    result = {
        "pass": len(matches) <= 1 and not rejected,
        "matched_existing_returns": matches,
        "rejected_existing_returns": rejected,
        "reason": "UNIQUE_FINITE_SOURCE_MATCHED_NATIVE_RETURN"
        if len(matches) == 1 and not rejected
        else "SOURCE_RETURN_WITHOUT_EXISTING_NATIVE_OWNER"
        if not matches and not rejected
        else "COMPETING_OR_UNPROVED_EXISTING_NATIVE_RETURNS",
    }
    if result["pass"] and matches:
        result["native_point_px"] = matches[0]["finite_native_intersection_px"]
    else:
        result["native_point_px"] = point.tolist()
    return result


def prove_existing_carrier_pair(gray, first, second, *, prior_objects=()):
    """Prove full old-old responsibility; never accept by proximity alone."""
    old = sorted([first, second], key=lambda obj: obj["id"])
    result = {
        "old_object_ids": [o["id"] for o in old],
        "pass": False,
        "checks": {},
        "old_object_bindings": [_binding(o) for o in old],
        "partial_old_line_retirement_permitted": False,
        "source_pixels_modified": False,
    }
    candidate = _candidate(*old)
    result["candidate_geometry"] = candidate
    if candidate is None:
        result["reason"] = "NOT_TWO_FULL_NEAR_OVERLAPPING_LINE_EXPRESSIONS"
        return result
    aa, _ = _line(old[0])
    bb, _ = _line(old[1])
    seed = (aa + bb) / 2
    fitted, reason = fit_source(seed.ravel(), gray, np.array([0, 0]))
    if fitted is None:
        result["reason"] = "COMMON_ORIGINAL_SOURCE_FIT_REJECTED:" + reason
        return result
    origin, end, width = fitted
    length = float(np.linalg.norm(end - origin))
    u = (end - origin) / length
    projections = [(pts - origin) @ u for pts in (aa, bb)]
    start_t = min(p[0] for p in projections)
    end_t = max(p[1] for p in projections)
    origin = origin + start_t * u
    length = end_t - start_t
    projections = [p - start_t for p in projections]
    profile = _same_source_profiles(gray, old, origin, u, length)
    result["full_extent_source_profiles"] = profile
    result["checks"]["same_original_stroke_over_complete_old_extents"] = profile["pass"]
    supports = [_source_support(gray, *pts) for pts in (aa, bb)]
    result["old_whole_source_support"] = supports
    result["checks"]["both_old_lines_pass_unchanged_source_gate"] = all(
        r["pass"] for r in supports
    )
    if not all(result["checks"].values()):
        result["reason"] = "WHOLE_SHARED_ORIGINAL_STROKE_NOT_PROVED"
        return result
    corners = [
        _return_candidates(gray, origin, u, 0.0, [p[0] for p in projections], 1),
        _return_candidates(gray, origin, u, length, [p[1] for p in projections], -1),
    ]
    result["endpoint_return_proofs"] = corners
    result["checks"]["both_complete_endpoints_have_unique_source_returns"] = all(
        c["pass"] for c in corners
    )
    if not all(result["checks"].values()):
        result["reason"] = "FULL_ENDPOINT_RESPONSIBILITY_NOT_PROVED"
        return result
    native_bindings = [
        _bind_existing_return(
            gray,
            corner["candidate_returns"][0],
            u,
            prior_objects,
            {obj["id"] for obj in old},
        )
        for corner in corners
    ]
    result["native_endpoint_return_bindings"] = native_bindings
    result["checks"]["existing_native_returns_are_unique_finite_source_matches"] = all(
        row["pass"] for row in native_bindings
    )
    points = np.asarray([row["native_point_px"] for row in native_bindings])
    limits = [c["candidate_returns"][0]["projection_px"] for c in corners]
    result["checks"]["no_missing_source_profile_inside_complete_endpoints"] = all(
        t < limits[0] or t > limits[1]
        for t in profile["unsupported_or_ambiguous_stations_px"]
    )
    if (points[1] - points[0]) @ u < POLICY["minimum_length_px"]:
        result["reason"] = "SOURCE_RETURNS_DO_NOT_BOUND_A_COMPLETE_LONG_LINE"
        return result
    support = _source_support(gray, *points)
    count = max(2, int(np.ceil(np.linalg.norm(points[1] - points[0]) / 0.25)) + 1)
    dense = np.linspace(*points, count)
    strict = _band_hits(
        gray, dense, np.array([-u[1], u[0]]), POLICY["strict_source_normal_px"]
    )
    result["replacement_source_support"] = support
    result["replacement_strict_source_fraction"] = float(strict.mean())
    result["checks"]["whole_replacement_has_original_ink"] = (
        support["pass"]
        and float(strict.mean()) >= POLICY["minimum_strict_source_fraction"]
    )
    result["replacement_geometry"] = {
        "start": points[0].tolist(),
        "end": points[1].tolist(),
    }
    result["source_width_px"] = width
    result["pass"] = all(result["checks"].values())
    result["reason"] = (
        "TWO_WHOLE_OLD_APPROXIMATIONS_TO_ONE_COMPLETE_SOURCE_LINE"
        if result["pass"]
        else "REPLACEMENT_SOURCE_SUPPORT_FAILED"
    )
    result["old_endpoint_excess_disposition"] = (
        "WITHDRAW_UNSUPPORTED_LINEAR_EXTRAPOLATION_IN_SHARED_END_INK; OTHER_SOURCE_STROKES_REMAIN_INDEPENDENT"
    )
    return result


def plan_existing_carrier_reconciliation(
    gray, roi, prior_objects, *, receiving_object_ids=None
):
    """Plan atomic whole replacements before ordinary contact-plan regeneration."""
    source = np.asarray(gray)
    if source.ndim != 2:
        raise ValueError("CARRIER_SOURCE_MUST_BE_GRAYSCALE")
    bindings = sorted(
        [_binding(obj) for obj in prior_objects], key=lambda obj: obj["id"]
    )
    if len({obj["id"] for obj in bindings}) != len(bindings):
        raise ValueError("CARRIER_DUPLICATE_PRIOR_ID")
    selected = sorted(set(receiving_object_ids or ()))
    all_lines = receiving_object_ids is None
    if not set(selected) <= {obj["id"] for obj in bindings}:
        raise ValueError("CARRIER_SCOPE_REFERENCES_MISSING_PRIOR_OBJECT")
    lines = [obj for obj in bindings if obj["kind"] == "LINE"]
    decisions = []
    for a, b in combinations(lines, 2):
        if not all_lines and not ({a["id"], b["id"]} & set(selected)):
            continue
        if _candidate(a, b) is None:
            continue
        proof = prove_existing_carrier_pair(source, a, b, prior_objects=bindings)
        decisions.append(
            {
                "old_object_ids": proof["old_object_ids"],
                "adopted": proof["pass"],
                "proof": proof,
            }
        )
    # An old object never takes part in two independently accepted pair edits.
    counts = {}
    for row in decisions:
        if row["adopted"]:
            for oid in row["old_object_ids"]:
                counts[oid] = counts.get(oid, 0) + 1
    for row in decisions:
        if row["adopted"] and any(counts[oid] != 1 for oid in row["old_object_ids"]):
            row.update(
                adopted=False, reason="COMPETING_WHOLE_OLD_LINE_GROUP_RESPONSIBILITY"
            )
    core = {
        "schema": SCHEMA,
        "policy": deepcopy(POLICY),
        "source_array_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "source_size_px": [source.shape[1], source.shape[0]],
        "roi_xyxy_px": list(roi),
        "prior_object_bindings": bindings,
        "scope_mode": "ALL_EXISTING_LINE_PAIRS"
        if all_lines
        else "DISCOVERED_RECEIVER_PAIRS",
        "receiving_object_ids": selected,
        "decisions": decisions,
        "source_pixels_modified": False,
    }
    core_sha = digest(core)
    objects, retired = [], []
    for index, row in enumerate(decisions):
        if not row["adopted"]:
            continue
        geometry = deepcopy(row["proof"]["replacement_geometry"])
        obj = {
            "id": stable_id("CARRIER", geometry),
            "kind": "LINE",
            "layer": "GEOMETRY",
            "geometry": geometry,
            "source_evidence": {
                "method": "whole_duplicate_carrier_source_reconciliation",
                "source_pixels_modified": False,
                "support": deepcopy(row["proof"]["replacement_source_support"]),
                "carrier_reconciliation": {
                    "schema": EVIDENCE_SCHEMA,
                    "source_array_sha256": core["source_array_sha256"],
                    "plan_core_sha256": core_sha,
                    "decision_index": index,
                    "decision_sha256": digest(row),
                    "retired_object_ids": row["old_object_ids"],
                    "source_pixels_modified": False,
                },
            },
        }
        objects.append(obj)
        retired.extend(row["old_object_ids"])
    return {
        **core,
        "plan_core_sha256": core_sha,
        "objects": objects,
        "retired_ids": sorted(retired),
        "uncertainties": [
            {
                "reason": row.get("reason", row["proof"]["reason"]),
                "old_object_ids": row["old_object_ids"],
            }
            for row in decisions
            if not row["adopted"]
        ],
        "required_followup": "REGENERATE_ORDINARY_STRUCTURE_CONTACT_PLAN_WITH_ACTIVE_FINITE_CARRIERS",
    }


def verify_existing_carrier_reconciliation(gray, roi, plan):
    """Cold re-run all candidates, full source profiles and endpoint competitors."""
    checks = {
        "schema": plan.get("schema") == SCHEMA,
        "policy": plan.get("policy") == POLICY,
        "roi": plan.get("roi_xyxy_px") == list(roi),
    }
    try:
        replay = plan_existing_carrier_reconciliation(
            gray,
            roi,
            plan["prior_object_bindings"],
            receiving_object_ids=(
                None
                if plan.get("scope_mode") == "ALL_EXISTING_LINE_PAIRS"
                else plan["receiving_object_ids"]
            ),
        )
        checks["complete_original_source_replay"] = digest(replay) == digest(plan)
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        checks["complete_original_source_replay"] = False
        return {"pass": False, "checks": checks, "failure": str(exc)}
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "retired_ids": replay["retired_ids"],
        "replacement_ids": [obj["id"] for obj in replay["objects"]],
    }
