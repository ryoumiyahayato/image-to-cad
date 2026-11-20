"""Choose a clearer existing fit inside an already selected finite wall span.

Local line groups are hypotheses, not permission to combine independent strokes.
Only an alternate admitted from the same recorded group can replace a member;
the selected object, opposite edge and observed finite span are preserved.
"""

from copy import deepcopy
import hashlib
import json
import math

import numpy as np

from .wall_candidate_ownership import near_overlap, replacement_support
from .wall_junction_ownership import resolve_junction_boundaries


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def refine_selected_wall_representatives(
    gray,
    walls,
    source_lines,
    admitted_lines,
    groups,
    source_check,
    partitioner,
    junction_wall_ids,
):
    by_id = {line["id"]: line for line in admitted_lines}
    formal = {line["id"]: line for line in source_lines}
    group_by_id = {sid: group for group in groups for sid in group["candidate_ids"]}
    selected = list(walls)
    audit = []
    for wall_index, original_wall in enumerate(walls):
        # This refinement belongs to the observed-cap/junction ownership
        # repair. Uncapped or ROI-clipped neighbors keep their existing fits
        # and unresolved ownership; they are not silently refitted here.
        if original_wall["id"] not in junction_wall_ids:
            continue
        for edge_index, parent in enumerate(
            original_wall["source_evidence"]["source_line_ids"]
        ):
            group = group_by_id.get(parent)
            # A provisional alternate must explain its surviving formal group
            # representative. Existing formal parents retain their prior scope.
            if parent in formal or not group or len(group["candidate_ids"]) < 2:
                continue
            group_sources = [
                formal[sid] for sid in group["candidate_ids"] if sid in formal
            ]
            if not group_sources:
                continue
            wall = selected[wall_index]
            current = wall["geometry"]["members"][edge_index]["geometry"]
            before_checks = [
                replacement_support(
                    gray, line["geometry"], current, sample_step_px=0.25
                )
                for line in group_sources
            ]
            if all(check.get("whole_overlap_replaced") for check in before_checks):
                continue
            anchor = wall["geometry"]["members"][1 - edge_index]["geometry"]
            a, b = np.asarray(anchor["start"]), np.asarray(anchor["end"])
            length = float(np.linalg.norm(b - a))
            direction = (b - a) / length
            normal = np.array([-direction[1], direction[0]])
            trials = []
            replacement = None
            alternative_ids = sorted(
                (
                    sid
                    for sid in group["candidate_ids"]
                    if sid != parent and sid in by_id
                ),
                key=lambda sid: (sid != group["representative_id"], sid),
            )
            for alternative_id in alternative_ids:
                alternative = by_id[alternative_id]
                c, d = (
                    np.asarray(alternative["geometry"]["start"]),
                    np.asarray(alternative["geometry"]["end"]),
                )
                other_direction = (d - c) / np.linalg.norm(d - c)
                if abs(float(direction @ other_direction)) < math.cos(
                    math.radians(0.5)
                ):
                    continue
                separation = float((c - a) @ normal)
                if not 8 <= abs(separation) <= 100:
                    continue
                geometry = {
                    "start": (a + separation * normal).tolist(),
                    "end": (b + separation * normal).tolist(),
                }
                proposal = deepcopy(wall)
                proposal["geometry"]["members"][edge_index]["geometry"] = geometry
                edges = proposal["geometry"]["members"][:2]
                cap_ends = iter(
                    i
                    for i, cap in enumerate(
                        proposal["source_evidence"]["observed_caps"]
                    )
                    if cap
                )
                for member in proposal["geometry"]["members"][2:]:
                    endpoint = ("start", "end")[next(cap_ends)]
                    member["geometry"] = {
                        "start": edges[0]["geometry"][endpoint],
                        "end": edges[1]["geometry"][endpoint],
                    }
                checks = [
                    source_check(gray, m["geometry"])
                    for m in proposal["geometry"]["members"]
                ]
                group_checks = [
                    replacement_support(
                        gray, line["geometry"], geometry, sample_step_px=0.25
                    )
                    for line in group_sources
                ]
                span_proof = replacement_support(
                    gray, geometry, alternative["geometry"], sample_step_px=0.25
                )
                intervals = span_proof["covered_intervals_px"]
                eps = max(1e-12, 64 * math.ulp(max(1.0, length)))
                complete_span = (
                    span_proof.get("whole_overlap_replaced")
                    and len(intervals) == 1
                    and abs(intervals[0][0]) <= eps
                    and abs(intervals[0][1] - length) <= eps
                )
                trial = {
                    "alternative_source_line_id": alternative_id,
                    "proposed_member_geometry": geometry,
                    "actual_member_source_checks": checks,
                    "formal_group_source_checks": group_checks,
                    "finite_span_source_proof": span_proof,
                    "finite_span_preserved": bool(complete_span),
                }
                trials.append(trial)
                if (
                    not complete_span
                    or not all(check["pass"] for check in checks)
                    or any(check["max_distance_px"] > 2 for check in checks[2:])
                    or not all(
                        check.get("whole_overlap_replaced") for check in group_checks
                    )
                ):
                    trial["rejection"] = "COMPLETE_MEMBER_CAP_OR_GROUP_SOURCE_GATE"
                    continue
                alias_conflicts = []
                for other_wall in selected:
                    if other_wall["id"] == wall["id"]:
                        continue
                    for member in other_wall["geometry"]["members"]:
                        if member["role"] != "wall_edge" or not near_overlap(
                            geometry, member["geometry"]
                        ):
                            continue
                        proof = replacement_support(gray, geometry, member["geometry"])
                        if proof["eligible"]:
                            alias_conflicts.append(
                                {
                                    "wall_id": other_wall["id"],
                                    "source_responsibility": proof,
                                }
                            )
                if alias_conflicts:
                    trial["rejection"] = "SELECTED_WALL_SOURCE_ALIAS_CONFLICT"
                    trial["alias_conflicts"] = alias_conflicts
                    continue
                change = {
                    "original_proposal_id": wall["id"],
                    "group_representative_id": group["representative_id"],
                    "group_candidate_ids": sorted(group["candidate_ids"]),
                    "replaced_source_line_id": parent,
                    "selected_source_line_id": alternative_id,
                    "member_index": edge_index,
                    "before_member_geometry": current,
                    "after_member_geometry": geometry,
                    "before_geometry_sha256": _digest(wall["geometry"]),
                    "after_geometry_sha256": _digest(proposal["geometry"]),
                    "unchanged_anchor_geometry": anchor,
                    "finite_wall_span_preserved": True,
                    "new_fit_created": False,
                    "source_thresholds_changed": False,
                    "formal_group_source_checks": group_checks,
                }
                evidence = proposal["source_evidence"]
                evidence.setdefault(
                    "candidate_group_representative_selection", []
                ).append(change)
                evidence["source_line_ids"][edge_index] = alternative_id
                evidence["edge_points"] = [
                    edges[i]["geometry"][key]
                    for i in (0, 1)
                    for key in ("start", "end")
                ]
                evidence["thickness_px"] = abs(separation)
                feasibility = evidence["whole_wall_feasibility"]
                feasibility["member_checks"] = checks
                provisional = list(selected)
                provisional[wall_index] = proposal
                _, junctions, _ = resolve_junction_boundaries(
                    gray, provisional, source_check
                )
                if not any(row["wall_id"] == wall["id"] for row in junctions):
                    trial["rejection"] = "EXISTING_JUNCTION_SOURCE_SCOPE_NOT_PRESERVED"
                    continue
                kept, partitions, *_ = partitioner(gray, source_lines, provisional)
                remainder_checks = [
                    {"id": line["id"], **source_check(gray, line["geometry"])}
                    for line in kept
                ]
                trial["actual_final_remainder_checks"] = remainder_checks
                if not all(check["pass"] for check in remainder_checks):
                    trial["rejection"] = "ACTUAL_FINAL_REMAINDER_SOURCE_GATE"
                    continue
                feasibility["derived_remainder_checks"] = remainder_checks
                feasibility["member_checks_scope"] = (
                    "EXISTING_GROUP_REPRESENTATIVE_WITHIN_SELECTED_WALL_SPAN"
                )
                change["source_partition_line_ids"] = [
                    row["source_line_id"] for row in partitions
                ]
                trial["selected"] = True
                replacement = proposal
                break
            row = {
                "wall_id": wall["id"],
                "member_index": edge_index,
                "original_source_line_id": parent,
                "group": group,
                "formal_source_line_ids": [line["id"] for line in group_sources],
                "before_dense_group_source_checks": before_checks,
                "candidate_trials": trials,
                "selected": replacement is not None,
                "status": "EXISTING_GROUP_REPRESENTATIVE_SELECTED"
                if replacement is not None
                else "PENDING_GROUP_REPRESENTATIVE_SOURCE_CONFLICT",
                "geometry": current,
            }
            audit.append(row)
            if replacement is not None:
                selected[wall_index] = replacement
    return selected, audit
