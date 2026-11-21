"""Source-supported wall-edge pairs, observed caps/corners and preserved gaps.

No BIM semantics or global orthogonal snapping. Each editing unit has a finite
observed span; long source lines outside that span remain separate objects.
"""

from pathlib import Path
import math
import time
import numpy as np
import cv2
from .contracts import save_json, stable_id
from .geometry import source_support
from .wall_candidate_ownership import near_overlap, replacement_support


def _vectors(o):
    a, b = np.array(o["geometry"]["start"]), np.array(o["geometry"]["end"])
    length = float(np.linalg.norm(b - a))
    return a, b, (b - a) / length, length


def _interval_epsilon(length):
    """Floating arithmetic allowance only, never a pixel-length cutoff."""
    return max(1e-12, 64 * math.ulp(max(1.0, float(length))))


def _positive_overlap(interval, existing, length):
    lo, hi = interval
    eps = _interval_epsilon(length)
    return any(min(hi, b) - max(lo, a) > eps for a, b in existing)


def _exact_collinear_overlap(first, second):
    a, b = np.asarray(first["start"], float), np.asarray(first["end"], float)
    c, d = np.asarray(second["start"], float), np.asarray(second["end"], float)
    length = float(np.linalg.norm(b - a))
    other = float(np.linalg.norm(d - c))
    if length <= 0 or other <= 0:
        raise ValueError("ZERO_LENGTH_COMPONENT_EDGE")
    u = (b - a) / length
    n = np.array([-u[1], u[0]])
    eps = _interval_epsilon(max(length, other))
    if max(abs(float((c - a) @ n)), abs(float((d - a) @ n))) > eps:
        return 0.0
    lo, hi = sorted((float((c - a) @ u), float((d - a) @ u)))
    overlap = max(0.0, min(length, hi) - max(0.0, lo))
    return overlap if overlap > eps else 0.0


def _partition_intervals(length, intervals):
    """Account for a source LINE's complete one-dimensional parameter domain.

    Every non-numerical remainder is retained, even below 3 px. The ledger
    records all bounds and any machine-scale residual separately. This is a
    parameter-coverage proof, not equality of a fitted wall's 2-D geometry.
    """
    length = float(length)
    eps = _interval_epsilon(length)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("INVALID_SOURCE_LINE_LENGTH")
    normalized = []
    for a, b in intervals:
        lo, hi = sorted((float(a), float(b)))
        if not math.isfinite(lo + hi):
            raise ValueError("NONFINITE_SOURCE_INTERVAL")
        if lo < -eps or hi > length + eps:
            raise ValueError("CLAIMED_INTERVAL_OUTSIDE_SOURCE_LINE")
        lo = max(0.0, min(length, lo))
        hi = max(0.0, min(length, hi))
        if hi - lo > eps:
            normalized.append((lo, hi))
    merged = []
    for lo, hi in sorted(normalized):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    remaining = []
    numerical = []
    last = 0.0
    for lo, hi in merged:
        if lo > last:
            (remaining if lo - last > eps else numerical).append((last, lo))
        last = max(last, hi)
    if length > last:
        (remaining if length - last > eps else numerical).append((last, length))
    claimed_length = math.fsum(b - a for a, b in merged)
    remaining_length = math.fsum(b - a for a, b in remaining)
    numerical_length = math.fsum(b - a for a, b in numerical)
    conservation = length - math.fsum(
        (claimed_length, remaining_length, numerical_length)
    )
    if abs(conservation) > eps * (len(merged) + len(remaining) + 2):
        raise AssertionError("SOURCE_INTERVAL_LENGTH_NOT_CONSERVED")
    ledger = {
        "original_length_px": length,
        "claimed_intervals_px": normalized,
        "claimed_union_intervals_px": merged,
        "remaining_intervals_px": remaining,
        "claimed_union_length_px": claimed_length,
        "remaining_length_px": remaining_length,
        "floating_point_only_intervals_px": numerical,
        "floating_point_only_length_px": numerical_length,
        "numerical_epsilon_px": eps,
        "length_conservation_error_px": conservation,
        "all_source_parameter_intervals_accounted": True,
        "geometric_pixel_cutoff_used": False,
    }
    return remaining, ledger


def _remainder_objects(original, spans, reason):
    a, b, u, length = _vectors(original)
    result = []
    for lo, hi in spans:
        g = {"start": (a + lo * u).tolist(), "end": (a + hi * u).tolist()}
        result.append(
            {
                **original,
                "id": stable_id("REMAIN", g),
                "geometry": g,
                "source_evidence": {
                    **original.get("source_evidence", {}),
                    "parent_line_id": original["id"],
                    reason: [lo, hi],
                    "positive_source_remainder_preserved": True,
                },
            }
        )
    return result


def _retire_exact_cap_overlaps(lines, caps):
    """Retire only numerically collinear cap spans, never nearby wall lines.

    The 2 px source tolerance does not establish duplicate identity. Near but
    non-collinear lines stay intact and are reported for independent review.
    Exact cap overlaps may retire part of a line; every outer remainder stays.
    """
    kept = []
    fully_consumed = []
    partitions = []
    nearby = []
    for o in lines:
        a, b, u, length = _vectors(o)
        normal = np.array([-u[1], u[0]])
        intervals = []
        owners = []
        for cap_index, cap in enumerate(caps):
            c, d = np.array(cap["start"]), np.array(cap["end"])
            v = d - c
            cap_length = float(np.linalg.norm(v))
            if cap_length <= 0:
                raise ValueError("ZERO_LENGTH_OBSERVED_CAP")
            if abs(float(u @ (v / cap_length))) < math.cos(math.radians(0.5)):
                continue
            deviation = max(abs(float((c - a) @ normal)), abs(float((d - a) @ normal)))
            if deviation > 2:
                continue
            lo, hi = sorted((float((c - a) @ u), float((d - a) @ u)))
            clipped = (max(0.0, lo), min(length, hi))
            eps = _interval_epsilon(max(length, cap_length))
            if clipped[1] - clipped[0] <= eps:
                continue
            evidence = {
                "source_line_id": o["id"],
                "cap_index": cap_index,
                "projection_interval_px": [lo, hi],
                "overlap_interval_px": list(clipped),
                "normal_deviation_px": deviation,
                "numerical_epsilon_px": eps,
            }
            if deviation > eps:
                nearby.append(
                    {**evidence, "decision": "RETAIN_NEAR_CAP_NOT_PROVEN_DUPLICATE"}
                )
                continue
            intervals.append(clipped)
            owners.append(evidence)
        if not intervals:
            kept.append(o)
            continue
        spans, ledger = _partition_intervals(length, intervals)
        ledger.update(
            source_line_id=o["id"],
            cap_claims=owners,
            reason="EXACT_COLLINEAR_CAP_OVERLAP_ONLY",
        )
        partitions.append(ledger)
        if spans:
            kept.extend(_remainder_objects(o, spans, "outside_observed_cap_spans"))
        else:
            fully_consumed.append(o["id"])
    return kept, fully_consumed, partitions, nearby


def _deferred_edge_replacements(probe_cache, walls):
    active = {wall["id"] for wall in walls}
    return [
        {
            "source_line_id": key[0],
            "wall_id": key[1],
            "wall_edge_parent": key[2],
            "candidate_wall_edge_geometry": {
                "start": list(key[3]),
                "end": list(key[4]),
            },
            "source_responsibility": proof,
            "status": "PENDING_SOURCE_INTERVAL_RESPONSIBILITY_NOT_TRANSFERRED",
        }
        for key, proof in probe_cache.items()
        if (
            proof.get("pending_supported_intervals_px")
            or proof.get("pending_junction_dependency_intervals")
        )
        and key[1] in active
    ]


def _partition_wall_lines(gray, lines, walls, probe_cache=None):
    """Retain every source-line span not justified by a selected whole wall."""
    from .wall_junction_ownership import joint_replacement_support

    probe_cache = {} if probe_cache is None else probe_cache
    kept = []
    partitions = []
    withdrawals = []
    for original in lines:
        a, b, u, length = _vectors(original)
        intervals = []
        claims = []
        feasible_partial_candidates = []
        for wall in walls:
            edges = [m for m in wall["geometry"]["members"] if m["role"] == "wall_edge"]
            parents = wall["source_evidence"]["source_line_ids"]
            for parent, member in zip(parents, edges):
                if parent == original["id"] and not wall["source_evidence"].get(
                    "candidate_group_representative_selection"
                ):
                    c, d = (
                        np.asarray(member["geometry"]["start"]),
                        np.asarray(member["geometry"]["end"]),
                    )
                    lo, hi = sorted((float((c - a) @ u), float((d - a) @ u)))
                    span = [max(0.0, lo), min(length, hi)]
                    if span[1] > span[0]:
                        intervals.append(span)
                        claims.append(
                            {
                                "wall_id": wall["id"],
                                "wall_edge_parent": parent,
                                "basis": "DIRECT_SOURCE_PARAMETER_PARTITION",
                                "covered_intervals_px": [span],
                            }
                        )
                    continue
                if original.get("layer") == "SHORT_STROKE":
                    continue
                key = (
                    original["id"],
                    wall["id"],
                    parent,
                    tuple(member["geometry"]["start"]),
                    tuple(member["geometry"]["end"]),
                )
                if key not in probe_cache:
                    owned_geometry = [
                        m["geometry"] for m in wall["geometry"]["members"]
                    ]
                    primary = replacement_support(
                        gray,
                        original["geometry"],
                        member["geometry"],
                        support_geometry=owned_geometry,
                    )
                    probe_cache[key] = joint_replacement_support(
                        gray,
                        original["geometry"],
                        member["geometry"],
                        owned_geometry,
                        wall["source_evidence"].get(
                            "junction_boundary_responsibilities", []
                        ),
                        primary,
                    )
                proof = probe_cache[key]
                if (
                    not proof["eligible"]
                    and proof.get("pending_supported_intervals_px")
                    and wall["source_evidence"].get(
                        "candidate_group_representative_selection"
                    )
                ):
                    feasible_partial_candidates.append((key, wall, parent, proof))
                if proof["eligible"]:
                    intervals.extend(proof["covered_intervals_px"])
                    claims.append(
                        {
                            "wall_id": wall["id"],
                            "wall_edge_parent": parent,
                            "basis": "EXPLICIT_WALL_AND_JUNCTION_SOURCE_RESPONSIBILITY"
                            if proof.get("junction_dependency_intervals")
                            else "UNCHANGED_SOURCE_STROKE_RESPONSIBILITY",
                            **proof,
                        }
                    )
        # A newly selected representative may expose a wider partial source
        # relation. It is safe only if the actual final remainder partition
        # passes the unchanged source gate; a failed trial stays pending and
        # cannot revoke an otherwise valid neighboring wall.
        from .wall_partition_gate import _check

        for key, wall, parent, proof in feasible_partial_candidates:
            spans = proof["pending_supported_intervals_px"]
            if any(_positive_overlap(span, intervals, length) for span in spans):
                continue
            remainder_spans, _ = _partition_intervals(length, intervals + spans)
            remainders = _remainder_objects(
                original, remainder_spans, "trial_source_partition"
            )
            checks = [
                {"id": o["id"], **_check(gray, o["geometry"])} for o in remainders
            ]
            if not all(check["pass"] for check in checks):
                proof["pending_partition_rejection"] = "ACTUAL_REMAINDER_SOURCE_GATE"
                proof["candidate_remainder_checks"] = checks
                continue
            accepted = {
                **proof,
                "eligible": True,
                "covered_intervals_px": spans,
                "pending_supported_intervals_px": [],
                "pending_reason": None,
                "ownership_basis": "PARTIAL_SOURCE_INTERVAL_WITH_FEASIBLE_ACTUAL_REMAINDERS",
                "wider_partial_source_evidence": proof,
                "actual_remainder_source_checks": checks,
            }
            probe_cache[key] = accepted
            intervals.extend(spans)
            claims.append(
                {
                    "wall_id": wall["id"],
                    "wall_edge_parent": parent,
                    "basis": "UNCHANGED_SOURCE_STROKE_RESPONSIBILITY",
                    **accepted,
                }
            )
        if not intervals:
            kept.append(original)
            continue
        spans, ledger = _partition_intervals(length, intervals)
        kept.extend(
            _remainder_objects(
                original, spans, "outside_selected_wall_source_responsibility"
            )
        )
        ledger.update(
            source_line_id=original["id"],
            wall_intervals_px=intervals,
            wall_claims=claims,
        )
        partitions.append(ledger)
        if any(c["basis"] != "DIRECT_SOURCE_PARAMETER_PARTITION" for c in claims):
            withdrawals.append(
                {
                    "source_line_id": original["id"],
                    "original_geometry": original["geometry"],
                    "fully_replaced": not spans,
                    "remaining_intervals_px": spans,
                    "wall_claims": claims,
                    "remaining_source_responsibility_preserved": True,
                    "original_source_pixels_deleted": 0,
                }
            )
    caps = [
        m["geometry"]
        for w in walls
        for m in w["geometry"]["members"]
        if m["role"] == "observed_end_cap"
    ]
    kept, cap_dup, cap_partition, cap_nearby = _retire_exact_cap_overlaps(kept, caps)
    return kept, partitions, withdrawals, cap_dup, cap_partition, cap_nearby


def assemble_walls(
    gray, roi, lines, out, *, candidate_lines=None, candidate_groups=None
):
    started = time.perf_counter()
    x0, y0, x1, y1 = roi
    origin = np.array([x0, y0])
    dist = cv2.distanceTransform(
        (gray[y0:y1, x0:x1] >= 128).astype("uint8"), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    bank = [
        o
        for o in lines
        if o["kind"] == "LINE"
        and o["layer"] != "SHORT_STROKE"
        and _vectors(o)[3] >= 100
    ]
    baseline_bank = list(bank)
    baseline_ids = {o["id"] for o in lines}
    candidate_audit = []
    # A candidate discarded by local deduplication remains a hypothesis. It
    # can participate only where a surviving input LINE already owns that
    # complete source stroke; consumed door/frame lines cannot be resurrected.
    for candidate in candidate_lines or []:
        if (
            candidate["id"] in baseline_ids
            or candidate.get("kind") != "LINE"
            or candidate.get("layer") == "SHORT_STROKE"
            or _vectors(candidate)[3] < 100
        ):
            continue
        anchors = []
        for original in baseline_bank:
            relation = near_overlap(candidate["geometry"], original["geometry"])
            if relation is None or relation["overlap_fraction_of_shorter"] <= 0.85:
                continue
            proof = replacement_support(
                gray, candidate["geometry"], original["geometry"]
            )
            # This is eligibility of an alternate fit, not duplicate proof.
            # Its full geometry must remain in a surviving source-line scope;
            # the later whole-wall/source-partition check decides its fate.
            ca, cb, cu, cl = _vectors(candidate)
            oa, ob, ou, ol = _vectors(original)
            projected = np.clip((np.asarray([ca, cb]) - oa) @ ou, 0.0, ol)
            endpoint_distances = np.linalg.norm(
                np.asarray([ca, cb]) - oa - projected[:, None] * ou, axis=1
            )
            if bool(np.all(endpoint_distances <= 2)):
                anchors.append(
                    {
                        "source_line_id": original["id"],
                        "source_responsibility": proof,
                        "complete_candidate_within_surviving_line_localization_scope": True,
                        "candidate_eligibility_is_not_duplicate_retirement_permission": True,
                    }
                )
        candidate_audit.append(
            {
                "candidate_id": candidate["id"],
                "geometry": candidate["geometry"],
                "surviving_source_anchors": anchors,
                "eligible_for_whole_wall_feasibility": bool(anchors),
                "decision": "RETAIN_CANDIDATE_UNTIL_COMPLETE_WALL_CHECK"
                if anchors
                else "NO_COMPLETE_SURVIVING_SOURCE_RESPONSIBILITY",
            }
        )
        if anchors:
            bank.append(candidate)
    # A short, source-supported return can witness a wall corner without
    # itself being promoted to a long paired wall edge. Independent dash
    # components remain excluded from this responsibility.
    corner_bank = [
        o
        for o in lines
        if o["kind"] == "LINE" and o["layer"] != "SHORT_STROKE" and _vectors(o)[3] >= 6
    ]
    candidates = []
    rejected = []
    for i, p in enumerate(bank):
        a, b, u, la = _vectors(p)
        n = np.array([-u[1], u[0]])
        for q in bank[i + 1 :]:
            c, d, v, lb = _vectors(q)
            if abs(u @ v) < math.cos(math.radians(0.5)):
                continue
            separation = float(n @ (c - a))
            width = abs(separation)
            if not 8 <= width <= 100:
                continue
            ts = sorted([(c - a) @ u, (d - a) @ u])
            lo, hi = max(0.0, ts[0]), min(la, ts[1])
            length = float(hi - lo)
            if length < max(100, 3 * width, 0.60 * min(la, lb)):
                continue
            pa, pb = a + lo * u, a + hi * u
            qa, qb = pa + separation * n, pb + separation * n
            # Both represented wall edges must themselves pass the source gate.
            edge_support = [
                source_support(pa, pb, dist, origin),
                source_support(qa, qb, dist, origin),
            ]
            if any(
                s["supported_fraction"] < 0.98 or s["maximum_white_gap_px"] > 5
                for s in edge_support
            ):
                continue
            cap_support = [
                source_support(pa, qa, dist, origin, 0.5),
                source_support(pb, qb, dist, origin, 0.5),
            ]
            caps = [
                s["supported_fraction"] >= 0.98 and s["max_distance_px"] <= 2
                for s in cap_support
            ]
            corner_witnesses = []
            for endpoint_pair in ((pa, qa), (pb, qb)):
                witnesses = []
                for k in corner_bank:
                    if k["id"] in (p["id"], q["id"]):
                        continue
                    e, f, w, lk = _vectors(k)
                    if abs(u @ w) > 0.15:
                        continue
                    # Endpoint incidence is evidence only, never a bridge.
                    near = [
                        min(np.linalg.norm(e - pt), np.linalg.norm(f - pt))
                        for pt in endpoint_pair
                    ]
                    if min(near) <= 4:
                        witnesses.append(
                            {
                                "line_id": k["id"],
                                "endpoint_distances_px": list(map(float, near)),
                            }
                        )
                corner_witnesses.append(witnesses)
            nearby = []
            for k in baseline_bank:
                if k["id"] in (p["id"], q["id"]):
                    continue
                e, f, w, lk = _vectors(k)
                if abs(u @ w) < math.cos(math.radians(0.5)):
                    continue
                dd = abs(n @ (e - a))
                tt = sorted([(e - a) @ u, (f - a) @ u])
                ov = max(0, min(hi, tt[1]) - max(lo, tt[0]))
                if dd <= max(110, 2 * width) and ov >= 0.75 * length:
                    # Alternate fits of an existing edge are not a repeated
                    # parallel field. They are still separate candidates.
                    if near_overlap(k["geometry"], p["geometry"]) or near_overlap(
                        k["geometry"], q["geometry"]
                    ):
                        continue
                    nearby.append(k["id"])
            reasons = []
            if len(nearby) >= 4:
                reasons.append("REPEATED_PARALLEL_FIELD_NOT_ESTABLISHED_AS_WALL")
            # The pair by itself is insufficient: require observed end/corner
            # structure and sufficiently thin drawn wall edges.
            clipped_ends = []
            for pair in ((pa, qa), (pb, qb)):
                clipped_ends.append(
                    any(
                        all(abs(point[axis] - value) <= 3 for point in pair)
                        and all(
                            min(abs(end[axis] - value) for end in _vectors(o)[:2])
                            <= 1e-7
                            for o in (p, q)
                        )
                        for axis, value in ((0, x0), (0, x1), (1, y0), (1, y1))
                    )
                )
            structural = (
                all(caps)
                or (any(caps) and any(corner_witnesses))
                or all(corner_witnesses)
                or (clipped_ends[0] and (caps[1] or bool(corner_witnesses[1])))
                or (clipped_ends[1] and (caps[0] or bool(corner_witnesses[0])))
            )
            if not structural:
                reasons.append("PARALLEL_ONLY_NO_END_OR_CORNER_EVIDENCE")
            widths = [
                float(z["source_evidence"].get("source_width_px", 99)) for z in (p, q)
            ]
            if max(widths) > 3:
                reasons.append("THICK_ELECTRICAL_OR_UNKNOWN_STROKE")
            record = {
                "source_line_ids": [p["id"], q["id"]],
                "span_px": length,
                "thickness_px": width,
                "edge_points": [pa.tolist(), pb.tolist(), qa.tolist(), qb.tolist()],
                "edge_support": edge_support,
                "cap_support": cap_support,
                "observed_caps": caps,
                "corner_witnesses": corner_witnesses,
                "nearby_parallel_lines": nearby,
                "ROI_clipped_open_ends": clipped_ends,
                "ROI_boundary_caps_invented": False,
                "source_ink_widths_px": widths,
                "rejection_reasons": reasons,
            }
            if reasons:
                rejected.append(record)
                continue
            record["score"] = (
                2 * sum(caps)
                + sum(bool(c) for c in corner_witnesses)
                + min(length / 300, 3)
                - len(nearby) * 0.2
            )
            candidates.append(record)
    used = {}
    walls = []
    probe_cache = {}
    from .wall_partition_gate import _check

    for r in sorted(
        candidates, key=lambda r: (-r["score"], -r["span_px"], r["source_line_ids"])
    ):
        pa, pb, qa, qb = map(np.array, r["edge_points"])
        parts = []
        intervals = []
        conflict = False
        for sid, start, end in zip(r["source_line_ids"], (pa, qa), (pb, qb)):
            base = next(z for z in bank if z["id"] == sid)
            a, b, u, length = _vectors(base)
            lo, hi = sorted([float((start - a) @ u), float((end - a) @ u)])
            eps = _interval_epsilon(length)
            if lo < -eps or hi > length + eps:
                r["interval_rejection"] = "CLAIMED_INTERVAL_OUTSIDE_SOURCE_LINE"
                conflict = True
                break
            lo = max(0.0, min(length, lo))
            hi = max(0.0, min(length, hi))
            if hi - lo <= eps:
                r["interval_rejection"] = "NUMERICALLY_EMPTY_WALL_SPAN"
                conflict = True
                break
            if _positive_overlap((lo, hi), used.get(sid, []), length):
                conflict = True
                break
            intervals.append((sid, lo, hi))
            parts.append(
                {
                    "kind": "LINE",
                    "geometry": {"start": start.tolist(), "end": end.tolist()},
                    "role": "wall_edge",
                }
            )
        if conflict:
            r["selection_rejection"] = "EDGE_SPAN_ALREADY_OWNED_BY_WALL"
            rejected.append(r)
            continue
        for cap, start, end in zip(r["observed_caps"], (pa, pb), (qa, qb)):
            if cap:
                parts.append(
                    {
                        "kind": "LINE",
                        "geometry": {"start": start.tolist(), "end": end.tolist()},
                        "role": "observed_end_cap",
                    }
                )
        # Caps do not originate from the paired source-line IDs. They also
        # need an ownership guard so two blocks cannot silently share an
        # exactly collinear positive segment. Reject the later whole proposal;
        # its untouched source lines remain available in the remainder bank.
        component_conflicts = []
        for part in parts:
            for previous in walls:
                for member in previous["geometry"]["members"]:
                    if (
                        part["role"] != "observed_end_cap"
                        and member["role"] != "observed_end_cap"
                    ):
                        continue
                    overlap = _exact_collinear_overlap(
                        part["geometry"], member["geometry"]
                    )
                    if overlap:
                        component_conflicts.append(
                            {
                                "previous_object_id": previous["id"],
                                "current_role": part["role"],
                                "previous_role": member["role"],
                                "positive_overlap_px": overlap,
                            }
                        )
        if component_conflicts:
            r["selection_rejection"] = "COMPONENT_CAP_SPAN_ALREADY_OWNED"
            r["component_span_conflicts"] = component_conflicts
            rejected.append(r)
            continue
        geom = {"members": parts}
        oid = stable_id("WALL", geom)
        proposal = {
            "id": oid,
            "kind": "WALL_SEGMENT",
            "layer": "WALL_SEGMENTS",
            "geometry": geom,
            "source_evidence": r,
            "classification": "SOURCE_SUPPORTED_PAIRED_EDGE_COMPOSITE_CANDIDATE",
            "semantic_wall_confirmed": False,
            "source_review_required": True,
            "editing_scope": "this finite observed pair and only its source-supported caps; not adjoining doors or annotations",
        }
        alias_conflicts = []
        for member in parts:
            if member["role"] != "wall_edge":
                continue
            for previous in walls:
                for prior in previous["geometry"]["members"]:
                    if prior["role"] != "wall_edge":
                        continue
                    relation = near_overlap(member["geometry"], prior["geometry"])
                    if not relation:
                        continue
                    proof = replacement_support(
                        gray, member["geometry"], prior["geometry"]
                    )
                    if proof["eligible"]:
                        alias_conflicts.append(
                            {
                                "previous_wall_id": previous["id"],
                                "responsibility": proof,
                            }
                        )
        if alias_conflicts:
            r["selection_rejection"] = "SAME_SOURCE_EDGE_ALREADY_OWNED_BY_COMPLETE_WALL"
            r["source_alias_conflicts"] = alias_conflicts
            rejected.append(r)
            continue
        member_checks = [_check(gray, m["geometry"]) for m in parts]
        provisional = _partition_wall_lines(
            gray, lines, walls + [proposal], probe_cache
        )
        remainder_checks = [
            {"id": o["id"], **_check(gray, o["geometry"])}
            for o in provisional[0]
            if o["id"] not in baseline_ids
        ]
        r["whole_wall_feasibility"] = {
            "member_checks": member_checks,
            "derived_remainder_checks": remainder_checks,
            "source_thresholds_changed": False,
            "chosen_before_local_alternative_retirement": True,
        }
        if not all(c["pass"] for c in member_checks + remainder_checks):
            r["selection_rejection"] = "WHOLE_WALL_OR_REMAINDER_SOURCE_GATE"
            rejected.append(r)
            continue
        walls.append(proposal)
        for sid, lo, hi in intervals:
            used.setdefault(sid, []).append((lo, hi))
    from .wall_group_representatives import refine_selected_wall_representatives
    from .wall_junction_ownership import (
        junction_owner_uncertainties,
        resolve_junction_boundaries,
    )

    _, original_junction_boundaries, _ = resolve_junction_boundaries(
        gray, walls, _check
    )
    walls, representative_audit = refine_selected_wall_representatives(
        gray,
        walls,
        lines,
        bank,
        candidate_groups or [],
        _check,
        _partition_wall_lines,
        {row["wall_id"] for row in original_junction_boundaries},
    )
    # A source-supported cross stroke can be a neighboring through boundary,
    # not an independently owned end cap. Resolve only among selected walls;
    # this does not alter candidate selection or any neighbor's wall edges.
    walls, junction_boundaries, junction_candidates = resolve_junction_boundaries(
        gray, walls, _check
    )
    # A cap no longer in the actual owned members cannot silently continue
    # supporting an earlier cached LINE withdrawal.
    if junction_boundaries or any(row.get("selected") for row in representative_audit):
        probe_cache.clear()
    kept, partition, withdrawals, cap_dup, cap_partition, cap_nearby = (
        _partition_wall_lines(gray, lines, walls, probe_cache)
    )
    if junction_boundaries:
        final_remainder_checks = [
            {"id": o["id"], **_check(gray, o["geometry"])}
            for o in kept
            if o["id"] not in baseline_ids
        ]
        for wall in walls:
            if wall["source_evidence"].get("junction_boundary_responsibilities"):
                feasibility = wall["source_evidence"]["whole_wall_feasibility"]
                feasibility["derived_remainder_checks"] = final_remainder_checks
                feasibility["remainder_checks_scope"] = (
                    "FINAL_PARTITION_AFTER_JUNCTION_ASSIGNMENT"
                )
    deferred = _deferred_edge_replacements(probe_cache, walls)
    corners = []
    openings = []
    for i, w in enumerate(walls):
        p = np.asarray(w["source_evidence"]["edge_points"])
        u = (p[1] - p[0]) / np.linalg.norm(p[1] - p[0])
        width = w["source_evidence"]["thickness_px"]
        for q in walls[i + 1 :]:
            z = np.asarray(q["source_evidence"]["edge_points"])
            v = (z[1] - z[0]) / np.linalg.norm(z[1] - z[0])
            if abs(u @ v) < 0.15:
                near = min(float(np.linalg.norm(a - b)) for a in p for b in z)
                if near <= 4:
                    corners.append(
                        {
                            "wall_ids": [w["id"], q["id"]],
                            "minimum_observed_endpoint_distance_px": near,
                            "angle_deg": math.degrees(
                                math.acos(float(np.clip(abs(u @ v), 0, 1)))
                            ),
                            "new_join_or_snap_created": False,
                        }
                    )
            elif (
                abs(u @ v) > math.cos(math.radians(0.5))
                and abs(width - q["source_evidence"]["thickness_px"]) <= 4
            ):
                n = np.array([-u[1], u[0]])
                for s in (0, 1):
                    a, b = p[s], p[s + 2]
                    for t in (0, 1):
                        c, d = z[t], z[t + 2]
                        gap = float(np.linalg.norm(c - a))
                        # Require matched edge offsets and white opening in
                        # both boundaries. No closing segment is ever emitted.
                        if not (6 <= gap <= 350) or abs((c - a) @ n) > 3:
                            continue
                        if abs((d - b) @ n) > 3:
                            continue
                        checks = [
                            source_support(a, c, dist, origin),
                            source_support(b, d, dist, origin),
                        ]
                        if max(sup["supported_fraction"] for sup in checks) > 0.3:
                            continue
                        openings.append(
                            {
                                "wall_ids": [w["id"], q["id"]],
                                "edge_gap_endpoints": [
                                    a.tolist(),
                                    c.tolist(),
                                    b.tolist(),
                                    d.tolist(),
                                ],
                                "gap_px": gap,
                                "source_edge_checks": checks,
                                "classification": "OBSERVED_OPENING_GAP_NOT_DOOR_CLASS",
                                "closing_entities_created": 0,
                            }
                        )
    result = {
        "objects": walls,
        "remaining_lines": kept,
        "candidate_pairs": len(candidates),
        "rejected_pairs": rejected,
        "candidate_source_lines": [o for o in bank if o["id"] not in baseline_ids],
        "local_alternative_candidate_audit": candidate_audit,
        "supported_edge_replacements": withdrawals,
        "deferred_edge_replacements": deferred,
        "diagnosis_origin": "RECONSTRUCTED_FROM_CURRENT_FROZEN_SOURCE_AND_CANDIDATES_NOT_MISSING_HISTORICAL_ORIGINAL",
        "source_interval_partition": partition,
        "junction_boundary_responsibilities": junction_boundaries,
        "junction_boundary_candidates": junction_candidates,
        "candidate_group_representative_audit": representative_audit,
        "original_junction_boundaries_before_group_selection": original_junction_boundaries,
        "uncertainties": junction_owner_uncertainties(walls, deferred),
        "duplicate_cap_lines_consumed": cap_dup,
        "cap_interval_partition": cap_partition,
        "near_cap_lines_retained": cap_nearby,
        "corners": corners,
        "openings": openings,
        "counts": {
            "ordinary_LINE": sum(o["layer"] == "GEOMETRY" for o in kept),
            "independent_short_LINE": sum(o["layer"] == "SHORT_STROKE" for o in kept),
            "wall_segments": len(walls),
            "paired_edge_composite_candidates": len(walls),
            "confirmed_wall_segments": 0,
            "wall_edge_members": 2 * len(walls),
            "observed_cap_members": sum(
                member["role"] == "observed_end_cap"
                for wall in walls
                for member in wall["geometry"]["members"]
            ),
            "junction_boundary_caps_not_owned": len(junction_boundaries),
        },
        "resources": {"wall_seconds": time.perf_counter() - started},
        "wall_segments_count_is_candidate_count": True,
        "semantic_scope": "Source-supported paired-edge editing candidates only; source pixel support does not confirm wall semantics; no BIM or inferred closure",
    }
    save_json(Path(out) / "wall_segments.json", result)
    return result
