"""Current whole-path adoption shared by ordinary and bounded reconstruction.

A proposed complete chain may replace a whole old LINE only after source ink,
finite geometry, all endpoints and every old sample prove the same ownership.
No partial member retirement, old approval, case identifier or expected string
can authorize a change. A failed complete group rolls back its retirements.
"""

from copy import deepcopy
import hashlib

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

from .connections import POLICY, _dense_geometry, _retirement_proposals, _support
from .contracts import TOLERANCES
from .completion_stages import (
    _connection_path_responsibility, _existing_arc_overlap, _existing_line_members,
    _quarantine_native_duplicate_groups, _finalize_complete_connection_groups,
)


def _line_source_coverage(proposal, line):
    points = np.asarray(proposal["source_evidence"]["source_path_points"], float)
    a, b = (np.asarray(line["geometry"][key], float) for key in ("start", "end"))
    delta = b - a
    fraction = np.clip((points - a) @ delta / max(float(delta @ delta), 1e-12), 0, 1)
    distance = np.linalg.norm(points - (a + fraction[:, None] * delta), axis=1)
    return {
        "source_to_old_finite_line_max_px": float(distance.max()),
        "source_to_old_finite_line_p95_px": float(np.percentile(distance, 95)),
        "observed_endpoint_distances_px": distance[[0, -1]].tolist(),
        "already_complete_within_existing_line_tolerances": bool(
            distance.max() <= TOLERANCES["line_perpendicular_px"]
            and max(distance[0], distance[-1]) <= TOLERANCES["line_endpoint_px"]
        ),
    }


def _simple_component_line_contacts(gray, proposal, members):
    """Find old ownership on an isolated chain even off its exact centreline.

    A narrow parallel-geometry test is only a candidate interval finder. An
    older source-supported approximation can be a pixel away and still own
    the same ink. This broader responsibility search applies only when the
    complete original component is a proven simple chain; shared junctions
    continue to use their port-specific ownership rules.
    """
    source = proposal["source_evidence"]
    if not source.get("whole_simple_source_chain", {}).get("pass"):
        return []
    x0, y0, x1, y1 = source["original_source_crop_xyxy_px"]
    crop = gray[y0:y1, x0:x1]
    if hashlib.sha256(crop.tobytes()).hexdigest() != source["original_source_crop_array_sha256"]:
        raise ValueError("CONNECTION_REPLACEMENT_SOURCE_CHANGED")
    ink = crop < POLICY["source_threshold"]
    _, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    origin = np.array([x0, y0])
    raw = np.asarray(source["source_path_points"], float)
    samples = np.rint(raw - origin).astype(int)
    owner_labels = set(labels[samples[:, 1], samples[:, 0]].tolist())
    if len(owner_labels) != 1 or 0 in owner_labels:
        return []
    label = owner_labels.pop()
    distance, nearest = distance_transform_edt(~ink, return_indices=True)
    radius = POLICY["source_perpendicular_px"]
    lo, hi = raw.min(axis=0) - radius, raw.max(axis=0) + radius
    contacts = []
    for member in members:
        g = member["geometry"]
        endpoints = np.asarray([g["start"], g["end"]], float)
        if np.any(endpoints.max(axis=0) < lo) or np.any(endpoints.min(axis=0) > hi):
            continue
        line = _dense_geometry({"points": endpoints.tolist(), "bulges": [0, 0]})
        index = np.rint(line - origin).astype(int)
        inside = ((index[:, 0] >= 0) & (index[:, 0] < ink.shape[1])
                  & (index[:, 1] >= 0) & (index[:, 1] < ink.shape[0]))
        index = index[inside]
        if not len(index):
            continue
        owners = labels[nearest[0, index[:, 1], index[:, 0]],
                        nearest[1, index[:, 1], index[:, 0]]]
        supported = distance[index[:, 1], index[:, 0]] <= radius
        if np.any((owners == label) & supported):
            contacts.append(member["id"])
    return contacts


def _whole_line_responsibility(gray, proposal, line):
    """Certify an entire old LINE on one fully accounted simple ink chain.

    Parallel intervals alone cannot authorize retirement. Original ink labels
    must assign every old line sample to this same isolated source component;
    the current chain certificate owns every source adjacency and both ends.
    No partial block member, extra component, branch or outside remainder is
    silently removed. The normal old-line source tolerances stay unchanged.
    """
    source = proposal["source_evidence"]
    certificate = source.get("whole_simple_source_chain", {})
    result = {"old_object_id": line["id"], "pass": False}
    if line["kind"] != "LINE" or not certificate.get("pass"):
        result["reason"] = "WHOLE_SIMPLE_COMPONENT_RESPONSIBILITY_NOT_PROVEN"
        return result
    x0, y0, x1, y1 = source["original_source_crop_xyxy_px"]
    crop = gray[y0:y1, x0:x1]
    if hashlib.sha256(crop.tobytes()).hexdigest() != source["original_source_crop_array_sha256"]:
        raise ValueError("CONNECTION_REPLACEMENT_SOURCE_CHANGED")
    ink = crop < POLICY["source_threshold"]
    _, labels = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    origin = np.array([x0, y0])
    raw = np.asarray(source["source_path_points"], float)
    q = np.rint(raw - origin).astype(int)
    if not np.array_equal(q + origin, raw):
        raise ValueError("CONNECTION_REPLACEMENT_NONPIXEL_SOURCE_CHAIN")
    expected = set(labels[q[:, 1], q[:, 0]].tolist())
    if len(expected) != 1 or 0 in expected:
        result["reason"] = "SOURCE_CHAIN_NOT_ON_ONE_ORIGINAL_INK_COMPONENT"
        return result
    component = expected.pop()
    g = line["geometry"]
    dense = _dense_geometry({"points": [g["start"], g["end"]], "bulges": [0, 0]})
    local = dense - origin
    index = np.rint(local).astype(int)
    if (np.any(index < 0) or np.any(index[:, 0] >= ink.shape[1])
            or np.any(index[:, 1] >= ink.shape[0])):
        result["reason"] = "OLD_LINE_EXTENDS_OUTSIDE_CURRENT_SOURCE_EVIDENCE"
        return result
    distance, nearest = distance_transform_edt(~ink, return_indices=True)
    owners = labels[nearest[0, index[:, 1], index[:, 0]],
                    nearest[1, index[:, 1], index[:, 0]]]
    support = _support(dense, distance, origin)
    coverage = _line_source_coverage(proposal, line)
    checks = {
        "complete_simple_source_chain": bool(certificate["pass"]),
        "whole_old_LINE_on_same_original_ink_component": bool(np.all(owners == component)),
        "whole_old_LINE_passes_unchanged_source_gate": support["pass"],
        "not_a_block_member": line["kind"] == "LINE",
    }
    result.update(
        checks=checks, source_component_label=int(component),
        original_source_crop_array_sha256=source["original_source_crop_array_sha256"],
        old_line_source_support=support, old_line_coverage=coverage,
        pass_=all(checks.values()),
        source_pixels_modified=False, old_line_remaining_intervals=[],
        basis="whole original ink component responsibility; not parallel-overlap intervals",
    )
    result["pass"] = result.pop("pass_")
    return result


def adopt_connection_paths(gray, proposals, prior_objects, *, additional_reasons=None):
    """Apply whole-object ownership and duplicate gates to live discoveries.

    This also protects already adequate old lines: a more complex polyline is
    not a new recovery when the old editable line already covers the source.
    """
    additional_reasons = additional_reasons or {}
    prior = {obj["id"]: obj for obj in prior_objects}
    if len(prior) != len(prior_objects):
        raise ValueError("CONNECTION_CHECKPOINT_DUPLICATE_PRIOR_ID")
    quarantine = _quarantine_native_duplicate_groups(proposals, prior_objects)
    quarantined_ids = set(quarantine["quarantined_ids"])
    adopted, decisions, retired = [], [], set()
    for candidate in proposals:
        if candidate["kind"] != "CONNECTION_PATH":
            raise ValueError("CONNECTION_CHECKPOINT_NONPATH_PROPOSAL")
        obj = deepcopy(candidate)
        row = {"id": obj["id"], "adopted": False, "reasons": [],
               "retired_ids": [], "existing_adequate_ids": [], "whole_line_certificates": [],
               "shared_source_core_checks": []}
        if obj["id"] in quarantined_ids:
            row.update(_connection_path_responsibility(gray, obj, prior_objects))
            row["decision"] = "PENDING_NATIVE_DUPLICATE_SOURCE_GROUP"
            row["reasons"].append("SOURCE_GROUP_HAS_DUPLICATE_NATIVE_SEGMENTS")
            decisions.append(row)
            continue
        active = [p for p in prior_objects if p["id"] not in retired] + adopted
        row.update(_connection_path_responsibility(gray, obj, active))
        row["reasons"].extend(additional_reasons.get(obj["id"], ()))
        if row["existing_adequate_ids"]:
            row["decision"] = "RETAIN_EXISTING_COMPLETE_PATH_NO_DUPLICATE"
            decisions.append(row)
            continue
        members = _existing_line_members(active)
        overlap, neighbors = _retirement_proposals(obj["geometry"], members)
        row["parallel_overlap_records"] = overlap
        row["unchanged_crossing_neighbors"] = neighbors
        component_contacts = _simple_component_line_contacts(gray, obj, members)
        row["same_simple_source_component_line_contacts"] = component_contacts
        proposed_retirements = []
        ownership_ids = sorted(set(component_contacts)
                               | {conflict["prior_object_id"] for conflict in overlap})
        for oid in ownership_ids:
            old = prior.get(oid)
            if old is None or old["kind"] != "LINE":
                row["reasons"].append("EXISTING_BLOCK_MEMBER_OR_NONLINE_RESPONSIBILITY_PENDING")
                continue
            proof = _whole_line_responsibility(gray, obj, old)
            row["whole_line_certificates"].append(proof)
            if not proof["pass"]:
                row["reasons"].append("WHOLE_OLD_LINE_RESPONSIBILITY_NOT_CERTIFIED")
            elif proof["old_line_coverage"]["already_complete_within_existing_line_tolerances"]:
                row["existing_adequate_ids"].append(oid)
            else:
                proposed_retirements.append(oid)
        arc_overlap = _existing_arc_overlap(obj, active)
        row["arc_overlap_records"] = arc_overlap
        if arc_overlap:
            row["reasons"].append("EXISTING_NATIVE_ARC_RESPONSIBILITY_PENDING")
        if row["existing_adequate_ids"]:
            row["decision"] = "RETAIN_EXISTING_ADEQUATE_LINE_NO_DUPLICATE"
        elif row["reasons"]:
            row["decision"] = "PENDING_WHOLE_OBJECT_RESPONSIBILITY"
        else:
            row.update(adopted=True, retired_ids=sorted(set(proposed_retirements)),
                       decision="REPLACE_WHOLE_INCOMPLETE_LINES" if proposed_retirements else "ADD_COMPLETE_PATH")
            retired.update(proposed_retirements)
            obj["source_evidence"]["checkpoint_responsibility_resolution"] = deepcopy(row)
            adopted.append(obj)
        decisions.append(row)
    final_groups = _finalize_complete_connection_groups(proposals, prior_objects, adopted, decisions, retired)
    adopted, decisions, retired = final_groups["objects"], final_groups["decisions"], final_groups["retired_ids"]
    return {
        "objects": adopted, "retired_ids": sorted(retired), "decisions": decisions,
        "uncertainties": [{"reason": "CONNECTION_EDIT_RESPONSIBILITY_PENDING", **row}
                          for row in decisions if row.get("decision") in (
                              "PENDING_WHOLE_OBJECT_RESPONSIBILITY", "PENDING_NATIVE_DUPLICATE_SOURCE_GROUP",
                              "PENDING_INCOMPLETE_FINAL_SOURCE_GROUP")],
        "native_duplicate_group_quarantine": quarantine,
        "final_complete_group_gate": {key: value for key, value in final_groups.items()
                                      if key not in ("objects", "decisions")},
        "source_pixels_modified": False,
        "partial_old_entity_retirement_permitted": False,
    }


