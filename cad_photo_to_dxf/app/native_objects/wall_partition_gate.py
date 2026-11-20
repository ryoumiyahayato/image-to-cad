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
    changed = True
    while changed:
        changed = False
        for w in result["objects"]:
            parents = set(w["source_evidence"]["source_line_ids"])
            if w["id"] in bad_walls or parents & bad_parents:
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
        "restoring_standalone_line_is_not_wall_reconstruction_success": True,
    }
    if not bad_walls:
        evidence["pass"] = not failed
        result["partition_source_gate"] = evidence
        save_json(Path(out) / "partition_source_gate.json", evidence)
        return result
    surviving = [w for w in result["objects"] if w["id"] not in bad_walls]
    # Alternative hypotheses were never independent formal lines. On revoke,
    # restore the original input bank and recompute only surviving claims.
    kept, partition, withdrawals, cap_dup, cap_partition, cap_nearby = (
        ws._partition_wall_lines(gray, source_lines, surviving)
    )
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
            sum(w["source_evidence"]["observed_caps"]) for w in surviving
        ),
    )
    restored_checks = [
        {"id": sid, **_check(gray, inputs[sid]["geometry"])}
        for sid in sorted(bad_parents)
        if sid in inputs
    ]
    evidence["original_standalone_line_checks"] = restored_checks
    evidence["pass"] = all(row["pass"] for row in restored_checks)
    result["partition_source_gate"] = evidence
    save_json(Path(out) / "partition_source_gate.json", evidence)
    save_json(Path(out) / "wall_segments_after_partition_gate.json", result)
    return result
