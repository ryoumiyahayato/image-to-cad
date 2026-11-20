"""Keep a crossing neighbor's boundary out of a wall's owned end caps.

Only selected, source-supported wall edges can represent such a boundary.
Their geometry is never cut or changed. An ambiguous set of neighboring wall
owners remains explicit; this module does not deduplicate those walls.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

import numpy as np
from scipy.spatial import cKDTree

from .wall_candidate_ownership import (
    SOURCE_LOCALIZATION_PX,
    replacement_support,
    source_overlap_candidate,
)


def _geometry_digest(geometry):
    return hashlib.sha256(
        json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _finite_neighbor_geometry(owner):
    geometry = owner["neighbor_member_geometry"]
    start, end = np.asarray(geometry["start"]), np.asarray(geometry["end"])
    direction = (end - start) / np.linalg.norm(end - start)
    lo, hi = owner["cap_projection_interval_px"]
    return {
        "start": (start + lo * direction).tolist(),
        "end": (start + hi * direction).tolist(),
    }


def _junction_interval_support(gray, first, interval, neighbor):
    """Check an explicit junction interval against a real finite neighbor edge.

    This is not an alternate collinear fit search. The caller must already have
    a complete cap-to-through-boundary source proof. Every 0.25 px sample needs
    common original ink within each unchanged 2 px support neighborhood, and
    the actual white midpoint veto is retained in both member orientations.
    """
    a, b = np.asarray(first["start"]), np.asarray(first["end"])
    direction = (b - a) / np.linalg.norm(b - a)
    lo, hi = interval
    ts = np.linspace(lo, hi, max(2, int(math.ceil((hi - lo) / 0.25)) + 1))
    samples = a + ts[:, None] * direction
    c, d = np.asarray(neighbor["start"]), np.asarray(neighbor["end"])
    length = float(np.linalg.norm(d - c))
    other_direction = (d - c) / length

    def project(points):
        position = np.clip((points - c) @ other_direction, 0, length)
        return c + position[:, None] * other_direction

    points = np.asarray([samples[0], samples[-1], c, d])
    low = np.maximum(0, np.floor(points.min(axis=0)).astype(int) - 4)
    high = np.minimum(
        [gray.shape[1], gray.shape[0]], np.ceil(points.max(axis=0)).astype(int) + 5
    )
    yy, xx = np.nonzero(gray[low[1] : high[1], low[0] : high[0]] < 128)
    ink = np.column_stack((xx + low[0], yy + low[1]))
    if not len(ink):
        return {"pass": False, "reason": "NO_ORIGINAL_JUNCTION_SOURCE_INK"}
    tree = cKDTree(ink)
    first_distances, first_indices = tree.query(samples)
    projected = project(samples)
    _, second_indices = tree.query(projected)
    source, other_source = ink[first_indices], ink[second_indices]
    nearest_source_to_neighbor = np.linalg.norm(source - project(source), axis=1)
    middle = np.rint((source + other_source) / 2).astype(int)
    white = gray[middle[:, 1], middle[:, 0]] >= 128
    normal = np.array([-direction[1], direction[0]])
    other_normal = np.array([-other_direction[1], other_direction[0]])
    separators = white & (
        (np.abs((source - other_source) @ normal) >= 1.5)
        | (np.abs((source - other_source) @ other_normal) >= 1.5)
    )
    ink_to_neighbor = np.linalg.norm(ink - project(ink), axis=1)
    common_ink = ink[ink_to_neighbor <= SOURCE_LOCALIZATION_PX]
    if not len(common_ink):
        return {"pass": False, "reason": "NO_COMMON_ORIGINAL_JUNCTION_SOURCE_INK"}
    distances, indices = cKDTree(common_ink).query(samples)
    common = common_ink[indices]
    to_neighbor = np.linalg.norm(common - project(common), axis=1)
    common_supported = distances <= SOURCE_LOCALIZATION_PX
    covered = (
        (first_distances <= SOURCE_LOCALIZATION_PX) & common_supported & ~separators
    )
    return {
        "pass": bool(covered.all()),
        "source_parameter_interval_px": list(interval),
        "sample_count": len(ts),
        "maximum_sample_step_px": 0.25,
        "common_source_witness_count": int(common_supported.sum()),
        "covered_sample_count_after_white_veto": int(covered.sum()),
        "actual_white_separator_sample_count": int(separators.sum()),
        "first_fit_to_common_source_max_px": float(distances.max()),
        "replacement_to_common_source_max_px": float(to_neighbor.max()),
        "nearest_original_source_to_neighbor_max_px": float(
            nearest_source_to_neighbor.max()
        ),
        "common_original_source_witnesses_sha256": hashlib.sha256(
            common.astype("<i8").tobytes()
        ).hexdigest(),
        "source_witness_samples": [
            {
                "first_parameter_px": float(ts[i]),
                "first_sample": samples[i].tolist(),
                "actual_neighbor_projection": projected[i].tolist(),
                "common_original_source_pixel": common[i].astype(int).tolist(),
                "literal_source_gray": int(gray[common[i, 1], common[i, 0]]),
                "first_fit_to_common_source_px": float(distances[i]),
                "replacement_to_common_source_px": float(to_neighbor[i]),
                "nearest_original_source_to_neighbor_px": float(
                    nearest_source_to_neighbor[i]
                ),
                "first_nearest_original_pixel": source[i].astype(int).tolist(),
                "replacement_nearest_original_pixel": other_source[i]
                .astype(int)
                .tolist(),
                "nearest_support_midpoint_pixel": middle[i].tolist(),
                "nearest_support_midpoint_gray": int(gray[middle[i, 1], middle[i, 0]]),
                "white_separator_veto": bool(separators[i]),
                "covered": bool(covered[i]),
            }
            for i in range(len(ts))
        ],
        "source_thresholds_changed": False,
        "original_source_pixels_modified": False,
    }


def joint_replacement_support(gray, first, second, owned_geometry, boundaries, primary):
    """Resolve only finite endpoint responsibility at a proven wall junction.

    The old primary-only white veto remains in the returned evidence. The
    conservative primary interval and its 2 px unsafe-sample margin are kept;
    only its endpoint remainder can depend on an already represented boundary.
    No removed cap is put back into the wall's supporting member geometry.
    """
    if not boundaries:
        return primary
    primary_spans = primary.get("covered_intervals_px") or primary.get(
        "pending_supported_intervals_px", []
    )
    if len(primary_spans) != 1 or "sampled_interval_px" not in primary:
        return primary
    lo, hi = primary["sampled_interval_px"]
    safe_lo, safe_hi = primary_spans[0]
    requests = [
        {"span": span, "required": True, "outside_primary_overlap": False}
        for span in ((lo, safe_lo), (safe_hi, hi))
        if span[1] > span[0]
    ]
    requests += [
        {"span": span, "required": False, "outside_primary_overlap": True}
        for span in ((0.0, lo), (hi, primary["first_length_px"]))
        if span[1] > span[0]
    ]
    if not requests:
        return primary
    a, b = np.asarray(first["start"]), np.asarray(first["end"])
    direction = (b - a) / np.linalg.norm(b - a)
    primary_geometry = {
        "start": (a + safe_lo * direction).tolist(),
        "end": (a + safe_hi * direction).tolist(),
    }
    dense_primary = replacement_support(
        gray,
        primary_geometry,
        second,
        support_geometry=owned_geometry,
        sample_step_px=0.25,
    )
    if not dense_primary.get("whole_overlap_replaced"):
        return primary
    dependencies = []
    pending = []
    candidate_checks = []
    required_failed = False
    resolved_lo, resolved_hi = lo, hi
    for request in requests:
        tail = request["span"]
        representatives = []
        attempted = []
        for boundary in boundaries:
            cap = boundary["original_member"]["geometry"]
            cap_length = float(np.linalg.norm(np.asarray(cap["end"]) - cap["start"]))
            if tail[1] - tail[0] > cap_length:
                continue
            for owner in boundary["representative_evidence"]:
                if owner["neighbor_wall_id"] not in boundary["represented_by_wall_ids"]:
                    continue
                finite = _finite_neighbor_geometry(owner)
                check = _junction_interval_support(gray, first, tail, finite)
                # Outside the primary overlap, do not consume a true source
                # tail merely because a more distant common pixel is nearby.
                # Its own nearest original ink must also be represented by
                # this actual neighbor under the unchanged localization gate.
                nearest_supported = (
                    not request["outside_primary_overlap"]
                    or check.get("nearest_original_source_to_neighbor_max_px", math.inf)
                    <= SOURCE_LOCALIZATION_PX
                )
                candidate = {
                    "junction_original_cap_member_index": boundary[
                        "original_member_index"
                    ],
                    "neighbor_wall_id": owner["neighbor_wall_id"],
                    "neighbor_member_index": owner["neighbor_member_index"],
                    "actual_neighbor_member_geometry": owner[
                        "neighbor_member_geometry"
                    ],
                    "finite_support_geometry_on_neighbor": finite,
                    "neighbor_member_projection_interval_px": owner[
                        "cap_projection_interval_px"
                    ],
                    "source_responsibility": check,
                    "outside_primary_overlap": request["outside_primary_overlap"],
                    "nearest_original_ink_represented_for_domain_extension": nearest_supported,
                    "accepted_as_interval_representative": bool(
                        check["pass"] and nearest_supported
                    ),
                }
                attempted.append(candidate)
                if candidate["accepted_as_interval_representative"]:
                    representatives.append(candidate)
        candidate_checks.extend(attempted)
        if not representatives:
            if not attempted and request["required"]:
                return primary
            if attempted or request["required"]:
                pending.append(
                    {
                        "source_parameter_interval_px": list(tail),
                        "source_interval_geometry": {
                            "start": (a + tail[0] * direction).tolist(),
                            "end": (a + tail[1] * direction).tolist(),
                        },
                        "outside_primary_overlap": request["outside_primary_overlap"],
                        "reason": "NO_ACTIVE_NEIGHBOR_PROVES_ENTIRE_ENDPOINT_INTERVAL",
                    }
                )
            required_failed |= request["required"]
            continue
        resolved_lo, resolved_hi = min(resolved_lo, tail[0]), max(resolved_hi, tail[1])
        dependencies.append(
            {
                "source_parameter_interval_px": list(tail),
                "represented_by_wall_ids": sorted(
                    {r["neighbor_wall_id"] for r in representatives}
                ),
                "representative_evidence": representatives,
                "responsibility": "EXTERNAL_JUNCTION_BOUNDARY_DEPENDENCY_NOT_TARGET_OWNED_CAP",
                "outside_primary_overlap": request["outside_primary_overlap"],
                "unique_neighbor_owner_established": False,
            }
        )
    if required_failed or not dependencies:
        return (
            {
                **primary,
                "pending_junction_dependency_intervals": pending,
                "junction_dependency_candidate_checks": candidate_checks,
            }
            if pending
            else primary
        )
    primary_evidence = replacement_support(
        gray,
        first,
        second,
        support_geometry=owned_geometry,
        include_sample_evidence=True,
    )
    primary_evidence["source_witness_samples"] = [
        row for row in primary_evidence["source_witness_samples"] if not row["covered"]
    ]
    primary_evidence["source_witness_sample_scope"] = "FAILED_PRIMARY_SAMPLES_ONLY"
    dense_primary["source_parameter_offset_px"] = safe_lo
    return {
        "eligible": True,
        "whole_overlap_replaced": True,
        "covered_intervals_px": [[resolved_lo, resolved_hi]],
        "pending_supported_intervals_px": [],
        "ownership_basis": "OWNED_WALL_EDGE_WITH_EXPLICIT_EXTERNAL_JUNCTION_DEPENDENCY",
        "primary_only_support": primary_evidence,
        "primary_owned_intervals_px": [[safe_lo, safe_hi]],
        "primary_dense_recheck": dense_primary,
        "junction_dependency_intervals": dependencies,
        "pending_junction_dependency_intervals": pending,
        "junction_dependency_candidate_checks": candidate_checks,
        "first_length_px": primary["first_length_px"],
        "primary_original_overlap_interval_px": [lo, hi],
        "sampled_interval_px": [resolved_lo, resolved_hi],
        "maximum_sample_step_px": 0.25,
        "actual_white_separator_veto_removed": False,
        "virtual_cap_used_as_owned_support": False,
        "source_pixels_modified": False,
        "source_thresholds_changed": False,
    }


def junction_owner_uncertainties(walls, deferred=()):
    """Expose ambiguous neighbor ownership to the existing located issue list."""
    by_id = {wall["id"]: wall for wall in walls}
    uncertainties = []
    for wall in walls:
        for boundary in wall["source_evidence"].get(
            "junction_boundary_responsibilities", []
        ):
            owners = boundary["represented_by_wall_ids"]
            if len(owners) < 2:
                continue
            points = np.asarray(
                [
                    member["geometry"][key]
                    for owner in owners
                    for member in by_id[owner]["geometry"]["members"]
                    for key in ("start", "end")
                ]
            )
            lo, hi = points.min(axis=0), points.max(axis=0)
            uncertainties.append(
                {
                    "reason": "WALL_JUNCTION_NEIGHBOR_OWNER_AMBIGUITY",
                    "status": "PENDING_SOURCE_OWNER_REVIEW",
                    "wall_id": wall["id"],
                    "neighbor_wall_ids": owners,
                    "original_cap_member_index": boundary["original_member_index"],
                    "source_bbox_xyxy_px": [*lo.tolist(), *hi.tolist()],
                    "junction_geometry": boundary["original_member"]["geometry"],
                    "evidence_file": "walls/wall_segments.json",
                    "evidence_key": "junction_boundary_responsibilities",
                    "unique_neighbor_owner_established": False,
                    "neighbor_wall_independence_established": False,
                    "instruction": "Review the full neighboring wall source ownership; the cap assignment does not prove those walls are independent or uniquely owned.",
                }
            )
    for row in deferred:
        for pending in row["source_responsibility"].get(
            "pending_junction_dependency_intervals", []
        ):
            uncertainties.append(
                {
                    "reason": "WALL_JUNCTION_ENDPOINT_RESPONSIBILITY_PENDING",
                    "status": "PENDING_SOURCE_OWNER_REVIEW",
                    "wall_id": row["wall_id"],
                    "source_line_id": row["source_line_id"],
                    "geometry": pending["source_interval_geometry"],
                    "source_parameter_interval_px": pending[
                        "source_parameter_interval_px"
                    ],
                    "outside_primary_overlap": pending["outside_primary_overlap"],
                    "evidence_file": "walls/wall_segments.json",
                    "evidence_key": "deferred_edge_replacements",
                    "untransferred_source_span_retained": True,
                }
            )
    return uncertainties


def resolve_junction_boundaries(gray, walls, source_check):
    """Assign a fully shared cap to an already represented through boundary.

    The neighbor must extend on both sides by at least one cap length, with
    actual local source support under the existing dense gate. This does not
    assert that every raster cross-section is black: the original source gate
    allows localized scan gaps, which remain unchanged in the source.
    """
    resolved = []
    responsibilities = []
    candidates = []
    for wall in walls:
        removed = {}
        for cap_index, cap in enumerate(wall["geometry"]["members"]):
            if cap["role"] != "observed_end_cap":
                continue
            cap_geometry = cap["geometry"]
            cap_points = np.asarray([cap_geometry["start"], cap_geometry["end"]])
            cap_length = float(np.linalg.norm(cap_points[1] - cap_points[0]))
            cap_check = source_check(gray, cap_geometry)
            owners = []
            for neighbor in walls:
                if neighbor["id"] == wall["id"]:
                    continue
                for member_index, member in enumerate(neighbor["geometry"]["members"]):
                    if member["role"] != "wall_edge":
                        continue
                    geometry = member["geometry"]
                    if source_overlap_candidate(cap_geometry, geometry) is None:
                        continue
                    start, end = (
                        np.asarray(geometry["start"]),
                        np.asarray(geometry["end"]),
                    )
                    length = float(np.linalg.norm(end - start))
                    direction = (end - start) / length
                    lo, hi = sorted(map(float, (cap_points - start) @ direction))
                    extensions = [lo, length - hi]
                    row = {
                        "wall_id": wall["id"],
                        "original_cap_member_index": cap_index,
                        "neighbor_wall_id": neighbor["id"],
                        "neighbor_member_index": member_index,
                        "neighbor_member_geometry": deepcopy(geometry),
                        "cap_projection_interval_px": [lo, hi],
                        "geometric_extensions_beyond_cap_px": extensions,
                        "required_local_extension_px": cap_length,
                    }
                    if min(extensions) < cap_length:
                        candidates.append(
                            {
                                **row,
                                "decision": "RETAIN_CAP_NO_TWO_SIDED_THROUGH_BOUNDARY",
                            }
                        )
                        continue
                    local_extensions = [
                        {
                            "start": (start + left * direction).tolist(),
                            "end": (start + right * direction).tolist(),
                        }
                        for left, right in (
                            (lo - cap_length, lo),
                            (hi, hi + cap_length),
                        )
                    ]
                    extension_checks = [source_check(gray, g) for g in local_extensions]
                    member_check = source_check(gray, geometry)
                    proof = replacement_support(
                        gray, cap_geometry, geometry, include_sample_evidence=True
                    )
                    eps = max(1e-12, 64 * math.ulp(max(1.0, cap_length)))
                    intervals = proof["covered_intervals_px"]
                    complete_cap = (
                        proof.get("whole_overlap_replaced", False)
                        and len(intervals) == 1
                        and abs(intervals[0][0]) <= eps
                        and abs(intervals[0][1] - cap_length) <= eps
                        and proof.get("common_source_witness_count", 0)
                        == proof.get("sample_count", -1)
                        and proof.get("actual_white_separator_sample_count", 1) == 0
                    )
                    supported = all(
                        check["pass"]
                        for check in [cap_check, member_check, *extension_checks]
                    )
                    row.update(
                        cap_source_check=cap_check,
                        neighbor_member_source_check=member_check,
                        local_extension_geometries=local_extensions,
                        local_extension_source_checks=extension_checks,
                        source_responsibility=proof,
                        pixel_gap_free_continuity_claimed=False,
                        original_source_pixels_modified=False,
                        decision="JUNCTION_BOUNDARY_REPRESENTED_BY_EXISTING_NEIGHBOR"
                        if complete_cap and supported
                        else "RETAIN_CAP_INCOMPLETE_SHARED_SOURCE_OR_LOCAL_EXTENSION",
                    )
                    candidates.append(row)
                    if complete_cap and supported:
                        owners.append(row)
            if owners:
                removed[cap_index] = {
                    "schema": "wall-junction-boundary-responsibility/v1",
                    "wall_id": wall["id"],
                    "role": "junction_boundary",
                    "original_member_index": cap_index,
                    "original_member": deepcopy(cap),
                    "owned_member_emitted": False,
                    "represented_by_wall_ids": sorted(
                        {owner["neighbor_wall_id"] for owner in owners}
                    ),
                    "representative_evidence": owners,
                    "owner_status": "NEIGHBOR_OWNER_AMBIGUITY_RETAINED"
                    if len(owners) > 1
                    else "EXISTING_NEIGHBOR_BOUNDARY_REPRESENTATIVE",
                    "unique_neighbor_owner_established": False,
                    "neighbor_wall_independence_established": False,
                    "neighbor_geometries_changed": False,
                    "original_wall_proposal_id_preserved": True,
                    "source_thresholds_changed": False,
                }
        if not removed:
            resolved.append(wall)
            continue
        updated = deepcopy(wall)
        updated["geometry"]["members"] = [
            member
            for index, member in enumerate(updated["geometry"]["members"])
            if index not in removed
        ]
        evidence = updated["source_evidence"]
        evidence["junction_boundary_responsibilities"] = list(removed.values())
        evidence["junction_ownership_geometry_change"] = {
            "original_proposal_id": wall["id"],
            "before_geometry_sha256": _geometry_digest(wall["geometry"]),
            "after_owned_geometry_sha256": _geometry_digest(updated["geometry"]),
            "removed_cap_member_indices": list(removed),
            "wall_edge_coordinates_changed": False,
            "original_observed_caps_remain_source_observations": True,
        }
        feasibility = evidence.setdefault("whole_wall_feasibility", {})
        feasibility["before_junction_assignment_member_checks"] = feasibility.get(
            "member_checks", []
        )
        feasibility["member_checks"] = [
            source_check(gray, member["geometry"])
            for member in updated["geometry"]["members"]
        ]
        feasibility["member_checks_scope"] = (
            "ACTUAL_OWNED_MEMBERS_AFTER_JUNCTION_ASSIGNMENT"
        )
        feasibility["source_thresholds_changed"] = False
        updated["editing_scope"] = (
            "this finite paired edge and its actual owned caps; referenced junction "
            "boundaries remain with the explicitly recorded neighboring wall owners"
        )
        resolved.append(updated)
        responsibilities.extend(removed.values())
    return resolved, responsibilities, candidates
