"""Bounded, source-constrained completion of outlined single swing doors.

An observed finite rail is a proposal, not an engineering door boundary.
Find its second source rail and both original end caps before testing the
outer rail as a door radius.  This differs from fitting an arc around every
individual LSD segment: a rail continued into a wall need not have a finite
LSD length equal to the leaf.  No source-case coordinates or labels are read.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import time

try:
    import resource
except ImportError:  # Windows import remains possible; measurement is unknown.
    resource = None

import cv2
import numpy as np

from .contracts import COORDINATES, TOLERANCES, save_json, stable_id
from .door_detector import _sample, _opening_context

VERSION = "source_paired_rail_capped_single_door_v1"
POLICY = {
    "minimum_anchor_length_px": 36.0,
    "maximum_anchor_length_px": 260.0,
    "maximum_source_anchor_count": 128,
    "pair_offset_range_px": [3.0, 16.0],
    "pair_offset_step_px": 0.5,
    "rail_stations": 32,
    "rail_station_fraction": [0.12, 0.88],
    "parallel_rail_support_min": 0.90,
    "rail_ink_centre_distance_px": 0.65,
    "endpoint_grid_points": 13,
    "coarse_arc_samples": 48,
    "coarse_arc_search_band_px": 8.0,
    "coarse_arc_supported_fraction_min": 0.70,
    "fit_arc_step_px": 0.5,
    "dense_member_step_px": 0.05,
    "final_member_support_min": 0.97,
    "opening_white_fraction_min": 0.70,
    "wall_stub_support_min": 0.75,
    "other_three_quadrants_support_max": 0.45,
    "maximum_finalists_per_orientation": 3,
    "maximum_new_doors": 8,
    "generation_CPU_seconds": 36.0,
    "generation_wall_seconds": 50.0,
    "process_RSS_limit_MiB": 480.0,
    "source_threshold": 128,
    "retirement_sampling_step_px": 0.25,
    "minimum_retirement_interval_px": 2.0,
    "arc_fragment_tangent_deviation_deg": 12.0,
    "no_source_geometry_changed": True,
    "no_wall_across_opening_generated": True,
}


def _canonical_hash(value):
    import json

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _tol(config):
    return dict((config or {}).get("tolerances", TOLERANCES))


def _guard(started, cpu_started):
    from .execution import active_resource_limits, check_cancel

    check_cancel("DOOR_COMPLETION_RESOURCE_CHECK")
    limits, scope = active_resource_limits(
        {
            "CPU_seconds": POLICY["generation_CPU_seconds"],
            "wall_seconds": POLICY["generation_wall_seconds"],
            "RSS_MiB": POLICY["process_RSS_limit_MiB"],
        }
    )
    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    rss = (
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        if resource is not None
        else None
    )
    return {
        "wall_seconds": wall,
        "CPU_seconds": cpu,
        "peak_RSS_MiB": rss,
        "RSS_gate_measured": rss is not None,
        "active_limits": limits,
        "budget_scope": scope,
        "stop": bool(
            wall > limits["wall_seconds"]
            or cpu > limits["CPU_seconds"]
            or (rss is not None and rss > limits["RSS_MiB"])
        ),
    }


def _line(a, b, step):
    a, b = np.asarray(a, float), np.asarray(b, float)
    length = float(np.linalg.norm(b - a))
    return np.linspace(a, b, max(2, int(math.ceil(length / step)) + 1)), length


def _arc(center, radius, start, sweep, step):
    length = float(radius * abs(sweep))
    angles = np.linspace(
        start, start + sweep, max(3, int(math.ceil(length / step)) + 1)
    )
    return np.asarray(center) + radius * np.column_stack(
        (np.cos(angles), np.sin(angles))
    ), length


def _metrics(field, offset, points, length, tolerance, *, witnesses=False):
    distances = _sample(field, np.asarray(points) - offset)
    good = distances <= tolerance
    longest = run = 0
    for value in good:
        run = 0 if value else run + 1
        longest = max(longest, run)
    result = {
        "samples": len(points),
        "max_source_distance_px": float(distances.max()),
        "mean_source_distance_px": float(distances.mean()),
        "supported_fraction": float(good.mean()),
        "longest_unsupported_run_px": float(longest * length / max(1, len(points) - 1)),
        "tolerance_px": float(tolerance),
    }
    if witnesses:
        result["points_xy_px"] = np.asarray(points).tolist()
        result["source_distances_px"] = distances.tolist()
    return result


def _patch(gray, a, b):
    length = float(np.linalg.norm(b - a))
    margin = int(math.ceil(1.40 * length + 24))
    lo = np.maximum(0, np.floor(np.minimum(a, b)).astype(int) - margin)
    hi = np.minimum(
        [gray.shape[1], gray.shape[0]],
        np.ceil(np.maximum(a, b)).astype(int) + margin + 1,
    )
    crop = np.ascontiguousarray(gray[lo[1] : hi[1], lo[0] : hi[0]])
    field = cv2.distanceTransform(
        (crop >= POLICY["source_threshold"]).astype(np.uint8),
        cv2.DIST_L2,
        cv2.DIST_MASK_PRECISE,
    )
    return (
        field,
        lo.astype(float),
        {
            "bbox_xyxy_px": [*lo.tolist(), *hi.tolist()],
            "gray_payload_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
        },
    )


def _find_second_rails(a, b, field, offset, tolerance):
    vector = b - a
    length = float(np.linalg.norm(vector))
    u = vector / length
    n = np.array([-u[1], u[0]])
    stations = (
        np.linspace(*POLICY["rail_station_fraction"], POLICY["rail_stations"]) * length
    )
    distance_min, distance_max = POLICY["pair_offset_range_px"]
    found = []
    for sign in (-1, 1):
        offsets = sign * np.arange(
            distance_min, distance_max + 0.01, POLICY["pair_offset_step_px"]
        )
        probes = a + stations[:, None, None] * u + offsets[None, :, None] * n
        ds = _sample(field, probes - offset)
        supports = (ds <= POLICY["rail_ink_centre_distance_px"]).mean(axis=0)
        ids = np.flatnonzero(supports >= POLICY["parallel_rail_support_min"])
        if not len(ids):
            continue
        groups = np.split(ids, np.flatnonzero(np.diff(ids) > 1) + 1)
        # One nearest source rail per side, not a repeated parameter search.
        group = min(groups, key=lambda x: float(np.min(abs(offsets[x]))))
        centre_offset = float(np.mean(offsets[group]))
        local_offsets = centre_offset + np.linspace(-tolerance, tolerance, 33)
        probe = a + stations[:, None, None] * u + local_offsets[None, :, None] * n
        values = _sample(field, probe - offset)
        observed = []
        for s, row in zip(stations, values):
            black = np.flatnonzero(row <= POLICY["rail_ink_centre_distance_px"])
            if not len(black):
                continue
            pieces = np.split(black, np.flatnonzero(np.diff(black) > 1) + 1)
            piece = min(
                pieces,
                key=lambda q: abs(float(local_offsets[q].mean()) - centre_offset),
            )
            observed.append([float(s), float(local_offsets[piece].mean())])
        if len(observed) < math.ceil(
            POLICY["rail_stations"] * POLICY["parallel_rail_support_min"]
        ):
            continue
        witness = np.asarray(observed)
        slope, intercept = np.polyfit(witness[:, 0], witness[:, 1], 1)
        direction_delta = abs(math.degrees(math.atan(float(slope))))
        found.append(
            {
                "intercept_px": float(intercept),
                "normal_slope": float(slope),
                "direction_difference_deg": direction_delta,
                "observed_station_offset_pairs_px": observed,
                "probe_offsets_px": offsets.tolist(),
                "probe_supported_fractions": supports.tolist(),
                "estimated_pair_spacing_px": abs(centre_offset),
            }
        )
    return found


def _panel_points(a, u, n, length, rail, s0, s1):
    t0, t1 = float(s0), float(length + s1)
    inner0, inner1 = a + t0 * u, a + t1 * u
    outer0 = inner0 + (rail["intercept_px"] + rail["normal_slope"] * t0) * n
    outer1 = inner1 + (rail["intercept_px"] + rail["normal_slope"] * t1) * n
    return np.asarray([inner0, outer0, outer1, inner1])


def _member_checks(
    panel, center, radius, angle, sweep, field, offset, tolerances, dense=False
):
    step = POLICY["dense_member_step_px"] if dense else POLICY["fit_arc_step_px"]
    checks = []
    for index in range(4):
        points, length = _line(panel[index], panel[(index + 1) % 4], step)
        metric = _metrics(
            field, offset, points, length, tolerances["line_perpendicular_px"]
        )
        metric.update(kind="LINE", role="leaf_outline", member_index=index)
        checks.append(metric)
    points, length = _arc(center, radius, angle, sweep, step)
    metric = _metrics(field, offset, points, length, tolerances["arc_radial_px"])
    metric.update(kind="ARC", role="swing_arc", member_index=4)
    checks.append(metric)
    return checks


def _joint_candidates(a, b, rail, field, offset, tolerances, seed_id):
    vector = b - a
    length = float(np.linalg.norm(vector))
    u = vector / length
    n = np.array([-u[1], u[0]])
    bound = float(tolerances["line_endpoint_px"])
    shifts = np.linspace(-bound, bound, POLICY["endpoint_grid_points"])
    feasible = []
    cap_rows = []
    for end in (0, 1):
        accepted = []
        evidence = []
        for shift in shifts:
            panel = _panel_points(
                a,
                u,
                n,
                length,
                rail,
                shift if end == 0 else 0,
                shift if end == 1 else 0,
            )
            inner, outer = (panel[0], panel[1]) if end == 0 else (panel[3], panel[2])
            points, span = _line(inner, outer, 0.25)
            metric = _metrics(
                field, offset, points, span, tolerances["line_perpendicular_px"]
            )
            okay = (
                metric["max_source_distance_px"] <= tolerances["line_perpendicular_px"]
            )
            evidence.append(
                {
                    "shift_px": float(shift),
                    "points": [inner.tolist(), outer.tolist()],
                    "pass": bool(okay),
                    "support": metric,
                }
            )
            if okay:
                accepted.append(float(shift))
        feasible.append(accepted)
        cap_rows.append(evidence)
    evidence = {
        "source_anchor_id": seed_id,
        "rail": rail,
        "caps": cap_rows,
        "endpoint_bound_px": bound,
        "endpoint_grid_points": len(shifts),
    }
    if not all(feasible):
        return [], {**evidence, "status": "NO_TWO_SOURCE_SUPPORTED_END_CAPS"}
    results = []
    for hinge_end in (0, 1):
        for sign in (-1, 1):
            fitted = []
            # A predeclared finite joint endpoint grid: caps, leaf and arc must
            # use the same endpoints. No subsequent free circle recentering.
            for s0 in feasible[0]:
                for s1 in feasible[1]:
                    panel = _panel_points(a, u, n, length, rail, s0, s1)
                    center, tip = (
                        (panel[1], panel[2]) if hinge_end == 0 else (panel[2], panel[1])
                    )
                    radius = float(np.linalg.norm(tip - center))
                    angle = math.atan2(
                        float(tip[1] - center[1]), float(tip[0] - center[0])
                    )
                    sweep = sign * math.pi / 2
                    coarse_angles = np.linspace(
                        angle, angle + sweep, POLICY["coarse_arc_samples"]
                    )
                    coarse = center + radius * np.column_stack(
                        (np.cos(coarse_angles), np.sin(coarse_angles))
                    )
                    coarse_d = _sample(field, coarse - offset)
                    if (
                        float((coarse_d <= POLICY["coarse_arc_search_band_px"]).mean())
                        < POLICY["coarse_arc_supported_fraction_min"]
                    ):
                        continue
                    checks = _member_checks(
                        panel, center, radius, angle, sweep, field, offset, tolerances
                    )
                    objective = max(
                        c["max_source_distance_px"] / c["tolerance_px"] for c in checks
                    )
                    objective += 0.01 * sum(
                        c["mean_source_distance_px"] for c in checks
                    )
                    fitted.append(
                        (
                            float(objective),
                            abs(s0) + abs(s1),
                            s0,
                            s1,
                            panel,
                            center,
                            radius,
                            angle,
                            sweep,
                            checks,
                        )
                    )
            fitted.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            for rank, item in enumerate(
                fitted[: POLICY["maximum_finalists_per_orientation"]]
            ):
                _, _, s0, s1, panel, center, radius, angle, sweep, checks = item
                dense = _member_checks(
                    panel,
                    center,
                    radius,
                    angle,
                    sweep,
                    field,
                    offset,
                    tolerances,
                    dense=True,
                )
                other, other_length = _arc(
                    center, radius, angle + sweep, 3 * sweep, 2.0
                )
                other_metric = _metrics(
                    field, offset, other, other_length, tolerances["arc_radial_px"]
                )
                context = _opening_context(
                    field,
                    center - offset,
                    radius,
                    angle + sweep,
                    tolerances["line_perpendicular_px"],
                )
                reasons = []
                if any(x["max_source_distance_px"] > x["tolerance_px"] for x in dense):
                    reasons.append(
                        "DENSE_NATIVE_MEMBER_EXCEEDS_ORIGINAL_SOURCE_DISTANCE_BOUND"
                    )
                if any(
                    x["supported_fraction"] < POLICY["final_member_support_min"]
                    or x["longest_unsupported_run_px"]
                    > tolerances["max_unexplained_line_gap_px"]
                    for x in dense
                ):
                    reasons.append("LEAF_OR_ARC_NOT_CONTINUOUSLY_SOURCE_SUPPORTED")
                if (
                    other_metric["supported_fraction"]
                    > POLICY["other_three_quadrants_support_max"]
                ):
                    reasons.append("CURVE_NOT_DISTINCT_FROM_CIRCLE_OR_OTHER_QUADRANTS")
                if (
                    context["opening_white_fraction"]
                    < POLICY["opening_white_fraction_min"]
                ):
                    reasons.append("CLOSING_SPAN_NOT_A_SOURCE_WHITE_OPENING")
                if any(
                    context[k]["supported_fraction"] < POLICY["wall_stub_support_min"]
                    or context[k]["longest_unsupported_run_px"]
                    > tolerances["max_unexplained_line_gap_px"]
                    for k in ("hinge_side_wall_stub", "latch_side_wall_stub")
                ):
                    reasons.append("TWO_SOURCE_JAMB_WALL_CONTINUATIONS_NOT_ESTABLISHED")
                leaf = {
                    "hinge": center.tolist(),
                    "radius_px": radius,
                    "start_deg_image": math.degrees(angle),
                    "end_deg_image": math.degrees(angle + sweep),
                    "leaf_angle_deg_image": math.degrees(angle),
                    "sweep_deg_image": 90 * sign,
                    "swing_direction_image": "clockwise"
                    if sign > 0
                    else "counterclockwise",
                }
                members = [
                    {
                        "kind": "LINE",
                        "role": "leaf_outline",
                        "geometry": {
                            "start": panel[i].tolist(),
                            "end": panel[(i + 1) % 4].tolist(),
                        },
                    }
                    for i in range(4)
                ]
                members.append(
                    {
                        "kind": "ARC",
                        "role": "swing_arc",
                        "geometry": {
                            "center": center.tolist(),
                            "radius_px": radius,
                            "start_deg_image": leaf["start_deg_image"],
                            "end_deg_image": leaf["end_deg_image"],
                            "sweep_deg_image": leaf["sweep_deg_image"],
                        },
                    }
                )
                geometry = {
                    "hinge": center.tolist(),
                    "leaves": [leaf],
                    "native_members": members,
                    "source_panel_corners_px": panel.tolist(),
                }
                arc_pts, _ = _arc(center, radius, angle, sweep, 1.0)
                all_points = np.vstack((panel, arc_pts))
                bbox = [
                    *all_points.min(axis=0).tolist(),
                    *all_points.max(axis=0).tolist(),
                ]
                results.append(
                    {
                        "id": stable_id("DOOR_SINGLE", geometry),
                        "kind": "DOOR",
                        "layer": "DOOR",
                        "template": "DOOR_SINGLE_OUTLINED_SWING",
                        "geometry": geometry,
                        "bbox_xyxy_px": bbox,
                        "rejection_reasons": reasons,
                        "rank_objective": item[0],
                        "source_evidence": {
                            "algorithm": VERSION,
                            "source_anchor_id": seed_id,
                            "anchor_endpoints_px": [a.tolist(), b.tolist()],
                            "second_source_rail": rail,
                            "cap_grid_evidence": cap_rows,
                            "selected_endpoint_shifts_px": [s0, s1],
                            "same_joint_endpoints_for_caps_leaf_and_arc": True,
                            "finalist_rank": rank,
                            "dense_member_checks": dense,
                            "other_three_quadrants": other_metric,
                            "opening_context": context,
                            "manual_seed_or_trace": False,
                            "whole_outline_included": True,
                            "engineering_width_calibrated": False,
                        },
                    }
                )
    return results, {
        **evidence,
        "status": "JOINT_FINITE_GRID_COMPLETE",
        "candidate_count": len(results),
    }


def _same_door(a, b):
    ga, gb = a["geometry"], b["geometry"]
    for la in ga.get("leaves", [ga]):
        for lb in gb.get("leaves", [gb]):
            if (
                np.linalg.norm(np.asarray(la["hinge"]) - lb["hinge"]) < 5
                and abs(la["radius_px"] - lb["radius_px"]) < 5
            ):
                return True
    return False


def complete_doors(
    gray, roi, line_data, retained_doors, out, *, source_path, config=None
):
    """Return preserved verified doors plus new source-checked finite proposals.

    ``line_data`` is the actual upstream line dictionary or a LINE list. This
    API does not read source-case boxes, OCR expected strings, or old failures.
    CAD cold-reading and independent rendering remain a separate required gate.
    """
    started = time.perf_counter()
    cpu_started = time.process_time()
    cv2.setNumThreads(1)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tolerances = _tol(config)
    source_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    retained_before = _canonical_hash(retained_doors)
    lines = line_data.get("objects", []) if isinstance(line_data, dict) else line_data
    eligible = []
    for item in lines:
        if item.get("kind") != "LINE":
            continue
        g = item["geometry"]
        a, b = np.asarray(g["start"], float), np.asarray(g["end"], float)
        length = float(np.linalg.norm(b - a))
        if (
            POLICY["minimum_anchor_length_px"]
            <= length
            <= POLICY["maximum_anchor_length_px"]
        ):
            eligible.append((item, a, b, length))
    eligible.sort(key=lambda x: (-x[3], x[0]["id"]))
    seeds = eligible[: POLICY["maximum_source_anchor_count"]]
    raw = []
    seed_ledger = []
    resource_stop = False
    for index, (item, a, b, length) in enumerate(seeds):
        resources = _guard(started, cpu_started)
        if resources["stop"]:
            resource_stop = True
            break
        field, offset, patch = _patch(gray, a, b)
        rails = _find_second_rails(
            a, b, field, offset, tolerances["line_perpendicular_px"]
        )
        record = {
            "source_anchor_id": item["id"],
            "source_anchor_geometry": item["geometry"],
            "length_px": length,
            "source_patch": patch,
            "rail_count": len(rails),
            "rail_trials": [],
        }
        for rail in rails:
            if _guard(started, cpu_started)["stop"]:
                resource_stop = True
                break
            if (
                rail["direction_difference_deg"]
                > tolerances["max_direction_adjustment_deg"]
            ):
                record["rail_trials"].append(
                    {
                        "rail": rail,
                        "status": "SOURCE_RAIL_DIRECTION_DIFFERENCE_EXCEEDS_BOUND",
                    }
                )
                continue
            rows, diag = _joint_candidates(
                a, b, rail, field, offset, tolerances, item["id"]
            )
            record["rail_trials"].append(diag)
            for row in rows:
                box = row["bbox_xyxy_px"]
                if (
                    box[0] < roi[0]
                    or box[1] < roi[1]
                    or box[2] > roi[2]
                    or box[3] > roi[3]
                ):
                    row["rejection_reasons"].append("WHOLE_DOOR_CROSSES_REQUESTED_ROI")
                row["source_evidence"].update(
                    source_sha256=source_sha, source_patch=patch
                )
                save_json(
                    out / "candidates" / (row["id"] + "__" + item["id"] + ".json"), row
                )
                raw.append(row)
        seed_ledger.append(record)
        save_json(
            out / "generation_checkpoint.json",
            {
                "processed": len(seed_ledger),
                "seed_total": len(seeds),
                "raw_candidate_count": len(raw),
                "resource_stop": resource_stop,
                "resources": _guard(started, cpu_started),
            },
        )
        if resource_stop:
            break
    accepted = []
    rejected = []
    duplicates = []
    for row in sorted(
        raw, key=lambda x: (len(x["rejection_reasons"]), x["rank_objective"], x["id"])
    ):
        if row["rejection_reasons"]:
            rejected.append(row)
            continue
        matched = next(
            (x for x in list(retained_doors) + accepted if _same_door(row, x)), None
        )
        if matched is not None:
            duplicates.append({"candidate_id": row["id"], "kept_id": matched["id"]})
            continue
        if len(accepted) >= POLICY["maximum_new_doors"]:
            row["rejection_reasons"].append("PROPOSAL_CAPACITY_REACHED")
            rejected.append(row)
            continue
        row["status"] = (
            "NEW_AUTOMATIC_SOURCE_SUPPORTED_DOOR_PENDING_INDEPENDENT_DXF_AUDIT"
        )
        accepted.append(row)
    if _canonical_hash(retained_doors) != retained_before:
        raise AssertionError("VERIFIED_DOOR_INPUT_MUTATED")
    result = {
        "schema": "native_door_completion_T07_v1",
        "algorithm": VERSION,
        "coordinate_system": COORDINATES,
        "source_sha256": source_sha,
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "roi_xyxy_px": list(roi),
        "policy": POLICY,
        "tolerances_unchanged": tolerances,
        "objects": copy.deepcopy(retained_doors) + accepted,
        "new_objects": accepted,
        "retained_objects": copy.deepcopy(retained_doors),
        "rejected": rejected,
        "duplicates": duplicates,
        "source_anchor_ledger": seed_ledger,
        "eligible_source_anchor_count": len(eligible),
        "source_anchors_omitted_by_capacity": max(0, len(eligible) - len(seeds)),
        "resource_stop": resource_stop,
        "status": "RESOURCE_STOP_PARTIAL_NO_GO"
        if resource_stop
        else "BOUNDED_GENERATION_COMPLETE",
        "retained_objects_hash_before": retained_before,
        "retained_objects_hash_after": _canonical_hash(retained_doors),
        "old_door_fit_rerun": False,
        "source_cases_used_as_algorithm_input": False,
        "source_white_openings_filled": False,
        "fire_classification": "UNCONFIRMED_NO_FIRE_OBJECT_EMITTED",
        "resources": _guard(started, cpu_started),
        "production_GO": False,
    }
    save_json(out / "door_completion.json", result)
    return result


def native_members(door):
    g = door["geometry"]
    if g.get("native_members") is not None:
        return copy.deepcopy(g["native_members"])
    result = []
    for leaf in g.get("leaves", [g]):
        c = np.asarray(leaf["hinge"], float)
        r = leaf["radius_px"]
        theta = math.radians(leaf["leaf_angle_deg_image"])
        tip = c + r * np.array([math.cos(theta), math.sin(theta)])
        result.append(
            {
                "kind": "LINE",
                "role": "radial_leaf",
                "geometry": {"start": c.tolist(), "end": tip.tolist()},
            }
        )
        result.append(
            {
                "kind": "ARC",
                "role": "swing_arc",
                "geometry": {
                    "center": c.tolist(),
                    "radius_px": r,
                    "start_deg_image": leaf["start_deg_image"],
                    "end_deg_image": leaf["end_deg_image"],
                    "sweep_deg_image": leaf.get(
                        "sweep_deg_image",
                        leaf["end_deg_image"] - leaf["start_deg_image"],
                    ),
                },
            }
        )
    return result


def _covered(points, direction, member, tolerance):
    g = member["geometry"]
    p = np.asarray(points, float)
    if member["kind"] == "LINE":
        a, b = np.asarray(g["start"]), np.asarray(g["end"])
        v = b - a
        length = float(np.linalg.norm(v))
        u = v / length
        if abs(float(u @ direction)) < math.cos(
            math.radians(TOLERANCES["max_direction_adjustment_deg"])
        ):
            return np.zeros(p.shape[:-1], bool)
        along = (p - a) @ u
        normal = (p - a) @ np.array([-u[1], u[0]])
        # No endpoint round caps: retire only the actual finite projection span.
        return (along >= 0) & (along <= length) & (abs(normal) <= tolerance)
    c = np.asarray(g["center"])
    v = p - c
    r = np.linalg.norm(v, axis=-1)
    angle = np.degrees(np.arctan2(v[..., 1], v[..., 0]))
    sweep = g["sweep_deg_image"]
    progress = (
        (angle - g["start_deg_image"]) if sweep > 0 else (g["start_deg_image"] - angle)
    ) % 360
    tangent = np.stack((-v[..., 1], v[..., 0]), axis=-1) / np.maximum(
        r[..., None], 1e-9
    )
    aligned = abs(tangent @ direction) >= math.cos(
        math.radians(POLICY["arc_fragment_tangent_deviation_deg"])
    )
    return (abs(r - g["radius_px"]) <= tolerance) & (progress <= abs(sweep)) & aligned


def _intervals(a, b, member, tolerance):
    v = b - a
    length = float(np.linalg.norm(v))
    direction = v / length
    ts = np.linspace(
        0, 1, max(2, int(math.ceil(length / POLICY["retirement_sampling_step_px"])) + 1)
    )
    good = _covered(a + ts[:, None] * v, direction, member, tolerance)
    ids = np.flatnonzero(good)
    if not len(ids):
        return []
    groups = np.split(ids, np.flatnonzero(np.diff(ids) > 1) + 1)
    result = []

    def boundary(lo, hi, want_right):
        for _ in range(36):
            mid = (lo + hi) / 2
            inside = bool(
                _covered((a + mid * v)[None, :], direction, member, tolerance)[0]
            )
            if inside == want_right:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    for group in groups:
        left = int(group[0])
        right = int(group[-1])
        t0 = float(ts[left])
        t1 = float(ts[right])
        if left > 0:
            t0 = boundary(float(ts[left - 1]), t0, True)
        if right < len(ts) - 1:
            t1 = boundary(t1, float(ts[right + 1]), False)
        if (t1 - t0) * length > POLICY["minimum_retirement_interval_px"]:
            result.append([t0, t1])
    return result


def retire_door_fragments(lines, doors, config=None):
    """Replace only source-supported coincident parameter intervals.

    No complete-line erasure is used for partial overlap. Every complement
    retains the exact old segment direction and endpoints at its two original
    parameter values, including very short remainders. Curve/line ownership
    is explicit geometric responsibility, not an inferred electrical meaning.
    """
    tolerance = _tol(config)
    remaining = []
    ledger = []
    primitives = [
        (d["id"], i, m) for d in doors for i, m in enumerate(native_members(d))
    ]
    for obj in lines:
        if obj.get("kind") != "LINE":
            remaining.append(copy.deepcopy(obj))
            continue
        g = obj["geometry"]
        a, b = np.asarray(g["start"], float), np.asarray(g["end"], float)
        length = float(np.linalg.norm(b - a))
        if length <= 1e-12:
            remaining.append(copy.deepcopy(obj))
            continue
        epsilon = 64 * max(math.ulp(abs(float(v))) for v in [length, *a, *b, 1.0])
        parameter_epsilon = epsilon / length
        numeric_zero_records = []
        intervals = []
        for did, index, member in primitives:
            if member.get("role") == "leaf_end_remnant":
                # This explicitly owned source end must never claim a second
                # parent through the general proximity-based retirement path.
                if member.get("source_anchor_id") != obj["id"]:
                    continue
                start, end = map(float, member["source_parameter_interval"])
                actual = member["geometry"]
                if not (
                    0 <= start < end <= 1
                    and np.linalg.norm(
                        np.asarray(actual["start"]) - (a + start * (b - a))
                    )
                    <= epsilon
                    and np.linalg.norm(np.asarray(actual["end"]) - (a + end * (b - a)))
                    <= epsilon
                ):
                    raise ValueError(
                        "DECLARED_LEAF_END_REMNANT_DOES_NOT_MATCH_ORIGINAL_SOURCE_LINE"
                    )
                intervals.append(
                    {
                        "t0": start,
                        "t1": end,
                        "door_id": did,
                        "member_index": index,
                        "member_kind": "LINE",
                        "distance_tolerance_px": 0.0,
                        "exact_original_parameter_copy": True,
                        "source_role": "leaf_end_remnant",
                    }
                )
                continue
            tol = (
                tolerance["line_perpendicular_px"]
                if member["kind"] == "LINE"
                else tolerance["arc_radial_px"]
            )
            for start, end in _intervals(a, b, member, tol):
                intervals.append(
                    {
                        "t0": start,
                        "t1": end,
                        "door_id": did,
                        "member_index": index,
                        "member_kind": member["kind"],
                        "distance_tolerance_px": tol,
                    }
                )
        if not intervals:
            remaining.append(copy.deepcopy(obj))
            continue
        merged = []
        for part in sorted(intervals, key=lambda x: (x["t0"], x["t1"])):
            if merged and part["t0"] <= merged[-1][1] + parameter_epsilon:
                if part["t0"] > merged[-1][1]:
                    numeric_zero_records.append(
                        {
                            "kind": "merged_numeric_zero_gap",
                            "parameter_interval": [merged[-1][1], part["t0"]],
                            "length_px": (part["t0"] - merged[-1][1]) * length,
                        }
                    )
                merged[-1][1] = max(merged[-1][1], part["t1"])
            else:
                merged.append([part["t0"], part["t1"]])
        kept = []
        cursor = 0.0
        for start, end in merged:
            if start > cursor + parameter_epsilon:
                kept.append([cursor, start])
            elif start > cursor:
                numeric_zero_records.append(
                    {
                        "kind": "numeric_zero_remainder",
                        "parameter_interval": [cursor, start],
                        "length_px": (start - cursor) * length,
                    }
                )
            cursor = max(cursor, end)
        if cursor < 1.0 - parameter_epsilon:
            kept.append([cursor, 1.0])
        elif cursor < 1.0:
            numeric_zero_records.append(
                {
                    "kind": "numeric_zero_remainder",
                    "parameter_interval": [cursor, 1.0],
                    "length_px": (1.0 - cursor) * length,
                }
            )
        children = []
        for start, end in kept:
            geometry = {
                "start": (a + start * (b - a)).tolist(),
                "end": (a + end * (b - a)).tolist(),
            }
            child = copy.deepcopy(obj)
            child["geometry"] = geometry
            child["id"] = stable_id(
                "DOOR_REMAINDER",
                {"parent": obj["id"], "interval": [start, end], "geometry": geometry},
            )
            child["parent_line_id"] = obj["id"]
            child["parent_parameter_interval"] = [start, end]
            child.setdefault("source_evidence", {})["door_responsibility"] = {
                "original_line_id": obj["id"],
                "retained_parameter_interval": [start, end],
                "unchanged_original_line_parameterization": True,
            }
            remaining.append(child)
            children.append(
                {"id": child["id"], "interval": [start, end], "geometry": geometry}
            )
        retired_length = sum((y - x) * length for x, y in merged)
        remaining_length = sum((y - x) * length for x, y in kept)
        ledger.append(
            {
                "source_line_id": obj["id"],
                "original_geometry": copy.deepcopy(g),
                "original_length_px": length,
                "retired_claims": intervals,
                "retired_union_intervals": merged,
                "remaining_intervals": kept,
                "remaining_children": children,
                "retired_length_px": retired_length,
                "remaining_length_px": remaining_length,
                "parameter_partition_error_px": abs(
                    length - retired_length - remaining_length
                ),
                "numeric_zero_epsilon_px": epsilon,
                "numeric_zero_records": numeric_zero_records,
                "numeric_zero_threshold_definition": "64*max(ULP(abs(original endpoint coordinates), original length, 1))",
                "accounted_partition_error_px": abs(
                    length
                    - retired_length
                    - remaining_length
                    - sum(
                        x["length_px"]
                        for x in numeric_zero_records
                        if x["kind"] == "numeric_zero_remainder"
                    )
                ),
                "partial_overlap_never_erases_whole_line": True,
                "short_remainders_deleted": False,
                "real_length_deletion_threshold_applied": False,
            }
        )
    return {
        "remaining_lines": remaining,
        "retirement_ledger": ledger,
        "input_line_count": len(lines),
        "output_line_count": len(remaining),
        "whole_source_raster_modified": False,
        "method": "finite_member_distance_and_orientation_with_original_parameter_complements",
        "source_unknown_or_neighbor_content_not_reclassified": True,
    }


def append_leaf_end_responsibility(
    gray, roi, completion, line_data, original_retirement, out, config=None
):
    """Verify and attach exact finite-anchor end remnants without re-fitting.

    A short distance alone is insufficient. Require the already measured
    finite, unclipped, non-text-contact source rail; its original interval
    partition; actual outward source white termination; and no other observed
    source line sharing the end. Failing this proof defers the whole new door.
    The result preserves every original fitted candidate in raw_new_objects.
    """
    tol = _tol(config)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lines = line_data.get("objects", []) if isinstance(line_data, dict) else line_data
    by_id = {x["id"]: x for x in lines}
    partitions = {
        x["source_line_id"]: x for x in original_retirement["retirement_ledger"]
    }
    raw = copy.deepcopy(completion["new_objects"])
    before_hash = _canonical_hash(raw)
    adopted = copy.deepcopy(completion["retained_objects"])
    pending = []
    decisions = []
    for proposal in completion["new_objects"]:
        oid = proposal["id"]
        anchor_id = proposal["source_evidence"]["source_anchor_id"]
        anchor = by_id.get(anchor_id)
        partition = partitions.get(anchor_id)
        proof = {
            "door_id": oid,
            "source_anchor_id": anchor_id,
            "failures": [],
            "ends": [],
            "foreign_source_line_conflicts": [],
            "method": "finite_source_anchor_termination_and_exclusive_observation_proof",
        }
        if anchor is None or partition is None:
            proof["failures"].append("FINITE_SOURCE_ANCHOR_OR_INTERVAL_LEDGER_MISSING")
        else:
            source_ev = anchor.get("source_evidence", {})
            proof["original_anchor_evidence"] = copy.deepcopy(source_ev)
            proof["original_anchor_geometry"] = copy.deepcopy(anchor["geometry"])
            proof["original_interval_partition"] = copy.deepcopy(partition)
            if source_ev.get("boundary_clipped") is not False:
                proof["failures"].append(
                    "ANCHOR_NOT_PROVEN_UNCLIPPED_FINITE_SOURCE_LINE"
                )
            if not str(source_ev.get("method", "")).startswith(
                "native_tiled_source_centered_complete_lines"
            ):
                proof["failures"].append(
                    "ANCHOR_FULL_SOURCE_LINE_PROVENANCE_NOT_ESTABLISHED"
                )
            if (
                source_ev.get("text_contacts")
                or source_ev.get("text_relation") != "NO_TEXT_CONTACT"
            ):
                proof["failures"].append("DEFER_TEXT_CONTACT")
            if any(x["door_id"] != oid for x in partition["retired_claims"]):
                proof["failures"].append("ANCHOR_ALREADY_SHARED_BY_ANOTHER_DOOR")
            if partition["parameter_partition_error_px"] > 1e-8:
                proof["failures"].append("ORIGINAL_INTERVAL_PARTITION_NOT_COMPLETE")
            a, b = (
                np.asarray(anchor["geometry"]["start"], float),
                np.asarray(anchor["geometry"]["end"], float),
            )
            length = float(np.linalg.norm(b - a))
            u = (b - a) / length
            tails = partition["remaining_children"]
            if any(
                not (
                    abs(t["interval"][0]) <= 1e-12 or abs(t["interval"][1] - 1) <= 1e-12
                )
                for t in tails
            ):
                proof["failures"].append("REMAINDER_IS_INTERIOR_NOT_A_FINITE_LEAF_END")
            if any(
                (t["interval"][1] - t["interval"][0]) * length
                > tol["line_endpoint_px"] + 1e-8
                for t in tails
            ):
                proof["failures"].append("LONG_SOURCE_EXTENSION_REMAINS_OUTSIDE_LEAF")
            if not proof["failures"]:
                field, offset, patch = _patch(gray, a, b)
                proof["source_patch"] = patch
                for tail in tails:
                    t0, t1 = tail["interval"]
                    left = abs(t0) <= 1e-12
                    endpoint = a if left else b
                    outward = -u if left else u
                    # The first several pixels may be the finite ink end-cap.
                    # A real 6 px white run further along the same source rail
                    # must be observed; an indefinitely continued wall fails.
                    distances = np.linspace(0, 16, 65)
                    points = endpoint + distances[:, None] * outward
                    ds = _sample(field, points - offset)
                    white = ds > tol["line_perpendicular_px"]
                    runs = []
                    begin = None
                    for j, value in enumerate(white):
                        if value and begin is None:
                            begin = j
                        if begin is not None and (not value or j == len(white) - 1):
                            end = j if value and j == len(white) - 1 else j - 1
                            runs.append(
                                {
                                    "from_px": float(distances[begin]),
                                    "to_px": float(distances[end]),
                                    "length_px": float(
                                        distances[end] - distances[begin]
                                    ),
                                    "start_xy_px": points[begin].tolist(),
                                    "end_xy_px": points[end].tolist(),
                                }
                            )
                            begin = None
                    best = max(runs, key=lambda x: x["length_px"]) if runs else None
                    terminated = (
                        best is not None
                        and best["length_px"] >= tol["opening_minimum_preserved_px"]
                    )
                    tp, tl = _line(
                        tail["geometry"]["start"], tail["geometry"]["end"], 0.05
                    )
                    metric = _metrics(
                        field, offset, tp, tl, tol["line_perpendicular_px"]
                    )
                    conflicts = []
                    for other in lines:
                        if other["id"] == anchor_id or other.get("kind") != "LINE":
                            continue
                        oa, ob = (
                            np.asarray(other["geometry"]["start"], float),
                            np.asarray(other["geometry"]["end"], float),
                        )
                        ov = ob - oa
                        den = float(ov @ ov)
                        if den <= 1e-12:
                            continue
                        parameter = np.clip(((tp - oa) @ ov) / den, 0, 1)
                        nearest = oa + parameter[:, None] * ov
                        sep = np.linalg.norm(tp - nearest, axis=1)
                        hit = np.flatnonzero(sep <= tol["line_perpendicular_px"])
                        if len(hit):
                            conflicts.append(
                                {
                                    "other_source_line_id": other["id"],
                                    "minimum_distance_px": float(sep[hit].min()),
                                    "tail_conflict_points_xy_px": tp[hit].tolist(),
                                    "other_nearest_points_xy_px": nearest[hit].tolist(),
                                    "conflict_length_along_tail_px": float(
                                        (hit[-1] - hit[0]) * tl / max(1, len(tp) - 1)
                                    ),
                                }
                            )
                    row = {
                        "original_remainder_id": tail["id"],
                        "source_parameter_interval": tail["interval"],
                        "exact_original_geometry": tail["geometry"],
                        "length_px": tl,
                        "source_fit": metric,
                        "outward_probe_points_xy_px": points.tolist(),
                        "outward_source_distances_px": ds.tolist(),
                        "source_white_runs": runs,
                        "longest_source_white_run": best,
                        "finite_source_end_observed": bool(terminated),
                        "foreign_source_line_conflicts": conflicts,
                    }
                    proof["ends"].append(row)
                    proof["foreign_source_line_conflicts"].extend(conflicts)
                    if not terminated:
                        proof["failures"].append(
                            "SOURCE_RAIL_CONTINUATION_NOT_EXCLUDED"
                        )
                    if conflicts:
                        proof["failures"].append(
                            "OTHER_SOURCE_LINE_SHARES_END_REMAINDER"
                        )
                    if metric["max_source_distance_px"] > tol["line_perpendicular_px"]:
                        proof["failures"].append(
                            "EXACT_OLD_END_REMAINDER_EXCEEDS_UNCHANGED_SOURCE_BOUND"
                        )
        proof["failures"] = sorted(set(proof["failures"]))
        if proof["failures"]:
            proof.update(
                status="PENDING_INCOMPLETE_EDIT_RESPONSIBILITY", added_native_entities=0
            )
            pending.append(copy.deepcopy(proposal))
        else:
            obj = copy.deepcopy(proposal)
            original_members = copy.deepcopy(obj["geometry"]["native_members"])
            for tail in partition["remaining_children"]:
                obj["geometry"]["native_members"].append(
                    {
                        "kind": "LINE",
                        "role": "leaf_end_remnant",
                        "geometry": copy.deepcopy(tail["geometry"]),
                        "source_anchor_id": anchor_id,
                        "source_parameter_interval": list(tail["interval"]),
                        "original_remainder_id": tail["id"],
                    }
                )
            assert (
                obj["geometry"]["native_members"][: len(original_members)]
                == original_members
            )
            fit_box = list(obj["bbox_xyxy_px"])
            endpoints = [
                p
                for tail in partition["remaining_children"]
                for p in tail["geometry"].values()
            ]
            if endpoints:
                obj["bbox_xyxy_px"] = [
                    min([fit_box[0]] + [p[0] for p in endpoints]),
                    min([fit_box[1]] + [p[1] for p in endpoints]),
                    max([fit_box[2]] + [p[0] for p in endpoints]),
                    max([fit_box[3]] + [p[1] for p in endpoints]),
                ]
            proof.update(
                status="FINITE_LEAF_END_RESPONSIBILITY_PROVEN",
                added_native_entities=len(partition["remaining_children"]),
                original_fit_bbox_xyxy_px=fit_box,
                fitted_native_members_unchanged=True,
                retained_end_members_are_exact_original_LINEs=True,
            )
            obj["source_evidence"]["leaf_end_responsibility"] = copy.deepcopy(proof)
            obj["responsibility_revision"] = "source_finite_leaf_end_members_v1"
            adopted.append(obj)
        decisions.append(proof)
        save_json(out / (oid + "_responsibility.json"), proof)
    if _canonical_hash(completion["new_objects"]) != before_hash:
        raise AssertionError("RAW_FIT_CANDIDATES_CHANGED")
    result = {
        "schema": "T07_exact_finite_leaf_end_responsibility_v1",
        "adopted_objects": adopted,
        "pending_new_objects": pending,
        "raw_new_objects": raw,
        "responsibility_decisions": decisions,
        "source_fit_reruns": 0,
        "original_source_modified": False,
        "original_fitted_geometry_unchanged": True,
        "source_threshold_unchanged": POLICY["source_threshold"],
        "production_GO": False,
        "proof_scope": "source-supported finite anchor responsibility; not an engineering dimension or semantic annotation claim",
    }
    save_json(out / "responsibility_result.json", result)
    return result
