"""Reject wall editing partitions whose actual fragments fail source gates.

All input line coordinates remain frozen. An inadmissible partition is revoked
as a whole, and its original, already audited standalone lines are restored.
This is not a claim that any source fitting error has been corrected.
"""

from pathlib import Path
import math
import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates
from .contracts import save_json
from . import wall_segments as ws


def _check(gray, geometry):
    a, b = np.asarray(geometry["start"]), np.asarray(geometry["end"])
    length = float(np.linalg.norm(b - a))
    lo = np.maximum(0, np.floor(np.minimum(a, b)).astype(int) - 8)
    hi = np.minimum(
        [gray.shape[1], gray.shape[0]], np.ceil(np.maximum(a, b)).astype(int) + 9
    )
    dist = distance_transform_edt(gray[lo[1] : hi[1], lo[0] : hi[0]] >= 128)
    p = np.linspace(a, b, max(2, int(math.ceil(length / 0.25)) + 1))
    ds = map_coordinates(
        dist, [p[:, 1] - lo[1], p[:, 0] - lo[0]], order=1, mode="constant", cval=999
    )
    d = np.diff(np.r_[False, ds > 2, False].astype(int))
    s = np.flatnonzero(d == 1)
    t = np.flatnonzero(d == -1)
    gap = float(max(t - s, default=0) * length / max(1, len(p) - 1))
    fraction = float(np.mean(ds <= 2))
    return {
        "source_fraction": fraction,
        "maximum_gap_px": gap,
        "samples": len(p),
        "pass": fraction >= 0.98 and gap <= 5,
        "max_distance_px": float(ds.max()),
    }


def enforce_partition_source_gate(gray, source_lines, result, out):
    inputs = {o["id"]: o for o in result.get("candidate_source_lines", [])}
    inputs.update({o["id"]: o for o in source_lines})
    failed = []
    bad_parents = set()
    bad_walls = set()
    for o in result["remaining_lines"]:
        check = _check(gray, o["geometry"])
        if not check["pass"]:
            parent = o["source_evidence"].get("parent_line_id", o["id"])
            failed.append(
                {
                    "id": o["id"],
                    "geometry": o["geometry"],
                    "parent_line_id": parent,
                    "check": check,
                }
            )
            bad_parents.add(parent)
    for w in result["objects"]:
        for index, member in enumerate(w["geometry"]["members"]):
            check = _check(gray, member["geometry"])
            if not check["pass"]:
                failed.append(
                    {
                        "id": w["id"],
                        "member": index,
                        "geometry": member["geometry"],
                        "check": check,
                    }
                )
                bad_walls.add(w["id"])
    for partition in result.get("source_interval_partition", []):
        if partition["source_line_id"] in bad_parents:
            bad_walls.update(
                claim["wall_id"] for claim in partition.get("wall_claims", [])
            )
    unavailable_junction_dependencies = []
    changed = True
    while changed:
        changed = False
        for w in result["objects"]:
            parents = set(w["source_evidence"]["source_line_ids"])
            unavailable = [
                boundary
                for boundary in w["source_evidence"].get(
                    "junction_boundary_responsibilities", []
                )
                if set(boundary["represented_by_wall_ids"]) <= bad_walls
            ]
            if unavailable and w["id"] not in bad_walls:
                unavailable_junction_dependencies.append(
                    {
                        "wall_id": w["id"],
                        "original_cap_member_indices": [
                            boundary["original_member_index"]
                            for boundary in unavailable
                        ],
                        "reason": "ALL_JUNCTION_BOUNDARY_REPRESENTATIVES_REVOKED",
                    }
                )
            if w["id"] in bad_walls or parents & bad_parents or unavailable:
                if w["id"] not in bad_walls or not parents <= bad_parents:
                    changed = True
                bad_walls.add(w["id"])
                bad_parents.update(parents)
    evidence = {
        "failed_derived_fragments": failed,
        "revoked_wall_ids": sorted(bad_walls),
        "restored_source_line_ids": sorted(bad_parents),
        "source_line_coordinates_changed": False,
        "thresholds_changed": False,
        "unavailable_junction_dependencies": unavailable_junction_dependencies,
        "restoring_standalone_line_is_not_wall_reconstruction_success": True,
    }
    if not bad_walls:
        evidence["pass"] = not failed
        result["partition_source_gate"] = evidence
        save_json(Path(out) / "partition_source_gate.json", evidence)
        return result
    surviving = [w for w in result["objects"] if w["id"] not in bad_walls]
    surviving_ids = {wall["id"] for wall in surviving}

    # Keep the original evidence, but never advertise a revoked wall as an
    # active representative of a boundary removed from another object's caps.
    def active_boundary(boundary):
        owner_ids = {
            row["neighbor_wall_id"] for row in boundary["representative_evidence"]
        }
        boundary["represented_by_wall_ids"] = sorted(owner_ids & surviving_ids)
        boundary["revoked_representative_wall_ids"] = sorted(owner_ids - surviving_ids)
        boundary["owner_status"] = (
            "NEIGHBOR_OWNER_AMBIGUITY_RETAINED"
            if len(boundary["represented_by_wall_ids"]) > 1
            else "EXISTING_NEIGHBOR_BOUNDARY_REPRESENTATIVE"
        )
        return boundary

    for wall in surviving:
        wall["source_evidence"]["junction_boundary_responsibilities"] = [
            active_boundary(boundary)
            for boundary in wall["source_evidence"].get(
                "junction_boundary_responsibilities", []
            )
        ]
    from .wall_junction_ownership import junction_owner_uncertainties

    # Alternative hypotheses were never independent formal lines. On revoke,
    # restore the original input bank and recompute only surviving claims.
    probe_cache = {}
    kept, partition, withdrawals, cap_dup, cap_partition, cap_nearby = (
        ws._partition_wall_lines(gray, source_lines, surviving, probe_cache)
    )
    deferred = ws._deferred_edge_replacements(probe_cache, surviving)
    # A revoked edit group is retained in rejection evidence, never relabelled
    # as a successful wall merely because the original LINE still passes.
    for w in result["objects"]:
        if w["id"] in bad_walls:
            result["rejected_pairs"].append(
                {
                    **w["source_evidence"],
                    "rejected_object_id": w["id"],
                    "selection_rejection": "DERIVED_EDIT_PARTITION_SOURCE_GATE",
                }
            )
    result.update(
        objects=surviving,
        remaining_lines=kept,
        source_interval_partition=partition,
        supported_edge_replacements=withdrawals,
        deferred_edge_replacements=deferred,
        junction_boundary_responsibilities=[
            active_boundary(boundary)
            for boundary in result.get("junction_boundary_responsibilities", [])
            if boundary["wall_id"] not in bad_walls
        ],
        uncertainties=junction_owner_uncertainties(surviving, deferred),
        duplicate_cap_lines_consumed=cap_dup,
        cap_interval_partition=cap_partition,
        near_cap_lines_retained=cap_nearby,
    )
    for key in ("corners", "openings"):
        result[key] = [
            row for row in result[key] if not set(row["wall_ids"]) & bad_walls
        ]
    result["counts"].update(
        ordinary_LINE=sum(o["layer"] == "GEOMETRY" for o in kept),
        independent_short_LINE=sum(o["layer"] == "SHORT_STROKE" for o in kept),
        wall_segments=len(surviving),
        paired_edge_composite_candidates=len(surviving),
        wall_edge_members=2 * len(surviving),
        observed_cap_members=sum(
            member["role"] == "observed_end_cap"
            for wall in surviving
            for member in wall["geometry"]["members"]
        ),
        junction_boundary_caps_not_owned=len(
            result["junction_boundary_responsibilities"]
        ),
    )
    restored_checks = [
        {"id": sid, **_check(gray, inputs[sid]["geometry"])}
        for sid in sorted(bad_parents)
        if sid in inputs
    ]
    evidence["original_standalone_line_checks"] = restored_checks
    final_fragment_checks = [
        {"id": line["id"], **_check(gray, line["geometry"])} for line in kept
    ]
    evidence["recomputed_actual_fragment_checks"] = final_fragment_checks
    evidence["pass"] = all(
        row["pass"] for row in restored_checks + final_fragment_checks
    )
    result["partition_source_gate"] = evidence
    if any(not row["pass"] for row in final_fragment_checks):
        # Losing one external endpoint owner can expose a new short remainder.
        # Re-run the same conservative gate on that actual partition. Each
        # recursive call follows a nonempty wall revocation, so this contracts
        # the selected set rather than repeatedly accepting an unchecked tail.
        result = enforce_partition_source_gate(gray, source_lines, result, out)
        final_evidence = result["partition_source_gate"]
        final_evidence.setdefault("prior_revocation_passes", []).insert(0, evidence)
        for key in ("revoked_wall_ids", "restored_source_line_ids"):
            final_evidence[key] = sorted(set(final_evidence[key]) | set(evidence[key]))
        final_evidence["failed_derived_fragments"] = (
            evidence["failed_derived_fragments"]
            + final_evidence["failed_derived_fragments"]
        )
        final_evidence["unavailable_junction_dependencies"] = (
            evidence["unavailable_junction_dependencies"]
            + final_evidence["unavailable_junction_dependencies"]
        )
        evidence = final_evidence
    save_json(Path(out) / "partition_source_gate.json", evidence)
    save_json(Path(out) / "wall_segments_after_partition_gate.json", result)
    return result
