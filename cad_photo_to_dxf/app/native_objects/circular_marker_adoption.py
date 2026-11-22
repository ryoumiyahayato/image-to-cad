"""Ordinary source-bound circular marker assembly and whole-object replacement.

One accepted marker is one independent CIRCLE plus one genuine TEXT in a
unique instance block.  Exterior connections never become block members.
Unconfirmed characters leave a separately counted boundary-only CIRCLE.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .circle_character_recognition import recognize_circle_character
from .circular_markers import (
    _mask_from_runs,
    discover_circular_markers,
    verify_circle_source_evidence,
)
from .connections import _dense_geometry
from .contracts import COORDINATES, plain, save_json
from .door_completion import native_members
from .execution import check_cancel


POLICY = {
    "version": "native-circular-marker-whole-object-adoption-v1",
    "native_sampling_step_px": 0.25,
    "replacement_geometry_distance_px": 0.85,
    "source_responsibility_distance_px": 0.85,
    "minimum_shared_native_interval_px": 1.0,
    "minimum_mixed_curve_ring_interval_px": 4.0,
    "whole_ring_fragment_tangent_deviation_deg": 20.0,
    "duplicate_tangent_deviation_deg": 5.0,
    "external_contact_guard_extra_px": 2.0,
    "terminal_contact_extent_px": 3.0,
    "partial_old_entity_retirement_permitted": False,
    "block_member_retirement_permitted": False,
    "external_connections_in_marker_block": False,
    "source_pixels_unique_partition_required": False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=plain).encode()).hexdigest()


def _text_box(obj):
    evidence = obj.get("source_evidence", {})
    geometry = obj.get("geometry", {})
    if obj.get("kind") in ("ROOM_LABEL", "CIRCULAR_MARKER"):
        geometry = geometry.get("text_geometry", {})
    box = geometry.get("bbox_xyxy_px") or evidence.get("bbox_xyxy_px")
    if box is not None and len(box) == 4:
        return list(map(float, box))
    if not all(key in geometry for key in ("x", "y", "height_px", "width_px")):
        return None
    x, y = float(geometry["x"]), float(geometry["y"])
    height, width = float(geometry["height_px"]), float(geometry["width_px"])
    angle = math.radians(float(geometry.get("rotation_deg_image", geometry.get("rotation_deg", 0))))
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    points = np.array([[0, -height], [width, -height], [width, 0], [0, 0]]) @ rotation.T + [x, y]
    return [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()]


def _formal_text_protection(prior_objects, text_regions):
    boxes = []
    for obj in prior_objects:
        if obj.get("kind") not in ("TEXT", "MTEXT", "ROOM_LABEL", "CIRCULAR_MARKER"):
            continue
        box = _text_box(obj)
        if box:
            boxes.append({"id": obj["id"], "bbox_xyxy_px": box, "confirmed": True})
    regions = text_regions.get("regions", []) if isinstance(text_regions, dict) else []
    for region in regions:
        if not (region.get("accepted") or region.get("source_review", {}).get("accepted")):
            continue
        if region.get("bbox_xyxy_px"):
            boxes.append({"id": region.get("id"), "bbox_xyxy_px": region["bbox_xyxy_px"],
                          "confirmed": True,
                          **({"glyph_source_runs": region["compact_source_ink_mask"]["runs_y_x0_x1"]}
                             if region.get("compact_source_ink_mask", {}).get("runs_y_x0_x1") else {})})
    return boxes


def _primitive_members(obj):
    kind, geometry = obj.get("kind"), obj.get("geometry", {})
    if kind in ("LINE", "CONNECTION_PATH", "ARC", "CIRCLE"):
        return [(kind, geometry, False)]
    if kind == "CIRCULAR_MARKER":
        return [("CIRCLE", geometry["circle_geometry"], True)]
    if kind == "WALL_SEGMENT":
        return [(member["kind"], member["geometry"], True) for member in geometry.get("members", [])]
    if kind == "DOOR":
        return [(member["kind"], member["geometry"], True) for member in native_members(obj)]
    if kind == "ROOM_LABEL":
        points = geometry.get("frame_points", [])
        result = [("LINE", {"start": a, "end": b}, True) for a, b in zip(points, points[1:] + points[:1])]
        result.extend((member["kind"], member["geometry"], True) for member in geometry.get("frame_source_remainders", []))
        return result
    return []


def _samples(kind, geometry):
    step = POLICY["native_sampling_step_px"]
    if kind == "LINE":
        points = np.asarray([geometry["start"], geometry["end"]], float)
        count = max(2, math.ceil(np.linalg.norm(points[1] - points[0]) / step) + 1)
        return np.linspace(points[0], points[1], count)
    if kind == "CONNECTION_PATH":
        return _dense_geometry(geometry, step)
    if kind in ("ARC", "CIRCLE"):
        center, radius = np.asarray(geometry["center"], float), float(geometry["radius_px"])
        start = 0.0 if kind == "CIRCLE" else math.radians(float(geometry["start_deg_image"]))
        sweep = 2 * math.pi if kind == "CIRCLE" else math.radians(float(geometry["sweep_deg_image"]))
        angle = np.linspace(start, start + sweep, max(2, math.ceil(abs(sweep) * radius / step) + 1))
        return center + radius * np.column_stack((np.cos(angle), np.sin(angle)))
    return np.empty((0, 2), float)


def _source_membership(points, mask, origin):
    """Every finite old sample must be supported by the replacement's source."""
    local = np.asarray(points, float) - origin
    index = np.rint(local).astype(int)
    inside = ((index[:, 0] >= 0) & (index[:, 0] < mask.shape[1])
              & (index[:, 1] >= 0) & (index[:, 1] < mask.shape[0]))
    distance = np.full(len(index), np.inf)
    if mask.any() and inside.any():
        field = cv2.distanceTransform(np.uint8(~mask), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        distance[inside] = cv2.remap(
            field, local[inside, 0].astype(np.float32)[:, None],
            local[inside, 1].astype(np.float32)[:, None], cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT, borderValue=1e6,
        ).ravel()
    return distance <= POLICY["source_responsibility_distance_px"], distance


def _run_lengths(mask, lengths):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False])).reshape(-1, 2)
    return [(int(a), int(b), float(lengths[a:b].sum())) for a, b in edges]


def _whole_fragment_proof(old, points, role, candidate, mask, origin):
    evidence = candidate["source_evidence"]
    supported, distance = _source_membership(points, mask, origin)
    result = {
        "old_object_id": old["id"], "replacement_object_id": candidate["id"],
        "replacement_member_role": role, "pass": False,
        "old_native_geometry_sha256": _digest(old["geometry"]),
        "replacement_geometry_sha256": _digest(candidate["geometry"]),
        "source_crop_sha256": evidence["crop_sha256"],
        "finite_native_samples": len(points),
        "all_old_samples_in_same_member_source": bool(supported.all()),
        "maximum_member_source_distance_px": float(distance.max()) if np.isfinite(distance).all() else None,
        "old_entity_remaining_intervals": [],
        "partial_old_retirement": False,
        "external_connection_owned": False,
    }
    if old.get("kind") not in ("LINE", "CONNECTION_PATH") or not supported.all():
        result["reason"] = "WHOLE_NATIVE_LINE_OR_PATH_MEMBER_SOURCE_NOT_PROVEN"
        return result
    raw = old.get("source_evidence", {}).get("source_path_points")
    if raw:
        raw_points = np.asarray(raw, float)
        raw_supported, _ = _source_membership(raw_points, mask, origin)
        result["old_source_path_points"] = len(raw_points)
        result["all_old_source_path_points_in_same_member"] = bool(raw_supported.all())
        if not raw_supported.all():
            result["reason"] = "OLD_PATH_SOURCE_HAS_UNREPLACED_OUTSIDE_CONTENT"
            return result
    if role == "circle_boundary":
        geometry = candidate["geometry"].get("circle_geometry", candidate["geometry"])
        center, radius = np.asarray(geometry["center"]), geometry["radius_px"]
        radial_error = np.abs(np.linalg.norm(points - center, axis=1) - radius)
        delta = np.diff(points, axis=0)
        length = np.linalg.norm(delta, axis=1)
        midpoint = (points[:-1] + points[1:]) * 0.5 - center
        tangents = np.column_stack((-midpoint[:, 1], midpoint[:, 0]))
        tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-300)
        dot = np.abs(np.sum(delta / np.maximum(length[:, None], 1e-300) * tangents, axis=1))
        valid = length > 1e-9
        geometry_pass = bool(radial_error.max() <= POLICY["replacement_geometry_distance_px"]
                             and np.all(dot[valid] >= math.cos(math.radians(POLICY["whole_ring_fragment_tangent_deviation_deg"]))))
        result["maximum_radial_geometry_error_px"] = float(radial_error.max())
        result["finite_geometry_fully_represented_by_circle"] = geometry_pass
        if not geometry_pass:
            result["reason"] = "OLD_GEOMETRY_NOT_WHOLLY_A_CIRCLE_BOUNDARY_FRAGMENT"
            return result
        guard = evidence["ring_geometry"]["stroke_width_px"] + POLICY["external_contact_guard_extra_px"]
        port_contacts = [p["contact_px"] for p in evidence.get("contact_ports", [])]
        near_ports = [p for p in port_contacts if np.linalg.norm(points - p, axis=1).min() <= guard]
        result["external_contact_ambiguities"] = near_ports
        if near_ports:
            result["reason"] = "OLD_FRAGMENT_HAS_EXTERNAL_PORT_RESPONSIBILITY_AMBIGUITY"
            return result
    elif candidate["kind"] != "CIRCULAR_MARKER":
        result["reason"] = "UNCONFIRMED_CHARACTER_CANNOT_RETIRE_ANY_GLYPH_LINE"
        return result
    result.update(pass_=True, reason="WHOLE_OLD_NATIVE_ENTITY_REPLACED_BY_PROVED_MEMBER")
    result["pass"] = result.pop("pass_")
    return result


def _matching_existing_boundary(candidate, prior_objects):
    circle = candidate["geometry"].get("circle_geometry", candidate["geometry"])
    for obj in prior_objects:
        if obj.get("kind") not in ("CIRCLE", "CIRCULAR_MARKER"):
            continue
        previous = obj["geometry"].get("circle_geometry", obj["geometry"])
        if (np.linalg.norm(np.asarray(circle["center"]) - previous["center"]) <= 0.25
                and abs(circle["radius_px"] - previous["radius_px"]) <= 0.25):
            return obj["id"]
    return None


def _responsibility(candidate, prior_objects):
    source = candidate["source_evidence"]
    bbox = source["crop_bbox_xyxy_px"]
    origin = np.asarray(bbox[:2])
    ring = _mask_from_runs(source["ring_support_runs_y_x0_x1"], bbox)
    interior = _mask_from_runs(source["interior_support_runs_y_x0_x1"], bbox)
    circle = candidate["geometry"].get("circle_geometry", candidate["geometry"])
    center, radius = np.asarray(circle["center"]), circle["radius_px"]
    complete = candidate["kind"] == "CIRCULAR_MARKER"
    result = {"retired_ids": [], "certificates": [], "conflicts": [], "unchanged_contacts": []}
    glyph_box = source.get("glyph_bbox_xyxy_px")
    for old in prior_objects:
        if complete and old.get("kind") in ("TEXT", "MTEXT", "ROOM_LABEL", "CIRCULAR_MARKER"):
            previous_box = _text_box(old)
            if glyph_box and previous_box and (
                previous_box[0] < glyph_box[2] and previous_box[2] > glyph_box[0]
                and previous_box[1] < glyph_box[3] and previous_box[3] > glyph_box[1]
            ):
                result["conflicts"].append({"old_object_id": old["id"], "reason": "EXISTING_FORMAL_TEXT_IS_NOT_RETIRED_OR_DUPLICATED"})
        for member_index, (kind, geometry, block_member) in enumerate(_primitive_members(old)):
            points = _samples(kind, geometry)
            if len(points) < 2 or not np.isfinite(points).all():
                continue
            if np.any(points.max(axis=0) < origin) or np.any(points.min(axis=0) > np.asarray(bbox[2:])):
                continue
            delta = np.diff(points, axis=0)
            lengths = np.linalg.norm(delta, axis=1)
            midpoint = (points[:-1] + points[1:]) * 0.5
            radial = midpoint - center
            norm = np.linalg.norm(radial, axis=1)
            tangent = np.column_stack((-radial[:, 1], radial[:, 0])) / np.maximum(norm[:, None], 1e-300)
            alignment = np.abs(np.sum(delta / np.maximum(lengths[:, None], 1e-300) * tangent, axis=1))
            tangent_near = (np.abs(norm - radius) <= POLICY["replacement_geometry_distance_px"])
            tangent_near &= alignment >= math.cos(math.radians(POLICY["duplicate_tangent_deviation_deg"]))
            ring_supported, _ = _source_membership(points, ring, origin)
            glyph_supported, _ = _source_membership(points, interior, origin)
            role = None
            if ring_supported.all():
                role = "circle_boundary"
            elif complete and glyph_supported.all():
                role = "interior_character"
            if role:
                proof = _whole_fragment_proof(old, points, role, candidate,
                                              ring if role == "circle_boundary" else interior, origin)
                proof["member_index"] = member_index
                if block_member:
                    proof.update({"pass": False, "reason": "EXISTING_BLOCK_MEMBER_CANNOT_BE_PARTIALLY_RETIRED"})
                if proof["pass"]:
                    result["retired_ids"].append(old["id"])
                    result["certificates"].append(proof)
                else:
                    result["conflicts"].append(proof)
                continue
            # A finite straight line touching/crossing a circle is not an arc
            # fragment.  For actual curves, sustained shared tangential runs
            # beyond a short endpoint contact are unresolved mixed ownership.
            runs = _run_lengths(tangent_near, lengths)
            ambiguous_runs = [run for run in runs
                              if run[2] >= POLICY["minimum_mixed_curve_ring_interval_px"]
                              and not ((run[0] == 0 or run[1] == len(lengths))
                                       and run[2] <= POLICY["terminal_contact_extent_px"])]
            if kind in ("CONNECTION_PATH", "ARC", "CIRCLE") and ambiguous_runs:
                result["conflicts"].append({
                    "old_object_id": old["id"], "member_index": member_index,
                    "reason": "OLD_CURVE_MIXES_RING_AND_UNREPLACED_OUTSIDE_CONTENT",
                    "shared_native_runs": ambiguous_runs,
                })
            if complete:
                inside_glyph = glyph_supported[:-1] & glyph_supported[1:]
                shared = float(lengths[inside_glyph].sum())
                if shared >= POLICY["minimum_shared_native_interval_px"]:
                    result["conflicts"].append({
                        "old_object_id": old["id"], "member_index": member_index,
                        "reason": "OLD_ENTITY_MIXES_GLYPH_AND_UNREPLACED_OUTSIDE_CONTENT",
                        "shared_glyph_length_px": shared,
                    })
            if ring_supported.any() or glyph_supported.any():
                result["unchanged_contacts"].append({"old_object_id": old["id"], "member_index": member_index,
                                                      "source_contact_does_not_transfer_ownership": True})
    result["retired_ids"] = sorted(set(result["retired_ids"]))
    result["pass"] = not result["conflicts"]
    if not result["pass"]:
        result["proposed_retirements_rolled_back"] = result["retired_ids"]
        result["retired_ids"] = []
    return result


def complete_circular_markers(
    gray, roi, source_sha, prior_objects, out, *, dpi, text_regions=None,
    observed_rounds=None, progress_callback=None,
):
    """Return new native objects and certified whole retirements for ordinary use."""
    output = Path(out)
    output.mkdir(parents=True, exist_ok=True)
    before = _digest(prior_objects)
    if len({obj["id"] for obj in prior_objects}) != len(prior_objects):
        raise ValueError("CIRCULAR_PRIOR_OBJECT_IDENTITIES_NOT_UNIQUE")
    protected = _formal_text_protection(prior_objects, text_regions)
    discovery = discover_circular_markers(gray, roi, protected_text_boxes=protected, observed_rounds=observed_rounds)
    save_json(output / "circular_marker_discovery.json", discovery)
    objects, uncertainties, decisions, retirement_records = [], [], [], []
    retired = set()
    new_tesseract_calls = new_model_calls = 0
    for index, row in enumerate(discovery["rows"]):
        check_cancel("CIRCULAR_MARKER_ASSEMBLY")
        decision = {"id": row["id"], "accepted": False, "retired_ids": [], "reasons": list(row["reasons"])}
        if not row["geometry_accepted"]:
            decision["status"] = row.get("composition_status", "BOUNDARY_GEOMETRY_PENDING")
            if not row.get("duplicate_of"):
                uncertainties.append({**decision, "seed_observation": row["seed_observation"]})
            decisions.append(decision)
            continue
        evidence = deepcopy(row["source_evidence"])
        evidence.update(source_sha256=source_sha, components_complete=False)
        candidate = {"id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
                     "geometry": deepcopy(row["geometry"]), "bbox_xyxy_px": deepcopy(row["bbox_xyxy_px"]),
                     "source_evidence": evidence}
        active = [old for old in prior_objects if old["id"] not in retired] + objects
        existing = _matching_existing_boundary(candidate, active)
        if existing:
            decision.update(status="EXISTING_COMPLETE_BOUNDARY_RETAINED_NO_DUPLICATE", existing_object_id=existing)
            decisions.append(decision)
            continue
        source_check = verify_circle_source_evidence(gray, roi, candidate)
        if not source_check["pass"]:
            decision.update(status="CURRENT_BOUNDARY_SOURCE_RECHECK_FAILED", reasons=source_check["reasons"])
            uncertainties.append(decision)
            decisions.append(decision)
            continue
        boundary_responsibility = _responsibility(candidate, active)
        if not boundary_responsibility["pass"]:
            decision.update(status="BOUNDARY_WHOLE_OBJECT_RESPONSIBILITY_PENDING", responsibility=boundary_responsibility)
            uncertainties.append(decision)
            decisions.append(decision)
            continue
        character = recognize_circle_character(
            gray, roi, row, output / "characters" / row["id"], dpi=dpi, evidence_root=output.parent,
        )
        new_tesseract_calls += character.get("new_Tesseract_calls", 0)
        new_model_calls += character.get("new_model_calls", 0)
        evidence["character_evidence"] = deepcopy(character.get("evidence"))
        evidence["character_pending_reasons"] = list(character.get("reasons", []))
        responsibility = boundary_responsibility
        if character.get("accepted"):
            full = deepcopy(candidate)
            full.update(kind="CIRCULAR_MARKER", layer="CIRCULAR_MARKERS",
                        geometry={"circle_geometry": deepcopy(row["geometry"]),
                                  "text_geometry": deepcopy(character["text_geometry"])})
            full["source_evidence"]["components_complete"] = True
            full_responsibility = _responsibility(full, active)
            if full_responsibility["pass"]:
                candidate, responsibility = full, full_responsibility
            else:
                evidence["character_pending_reasons"].append("CHARACTER_ASSEMBLY_WHOLE_OBJECT_RESPONSIBILITY_PENDING")
                evidence["character_responsibility_conflicts"] = full_responsibility["conflicts"]
        complete = candidate["kind"] == "CIRCULAR_MARKER"
        candidate["source_evidence"]["assembly_policy"] = dict(POLICY)
        candidate["source_evidence"]["whole_object_retirement"] = responsibility
        candidate["status"] = "COMPLETE_CIRCULAR_MARKER_PENDING_SAVED_AUDIT" if complete else "PARTIAL_BOUNDARY_ONLY_CHARACTER_PENDING"
        decision.update(accepted=True, status=candidate["status"], kind=candidate["kind"],
                        retired_ids=responsibility["retired_ids"], responsibility=responsibility,
                        character_reasons=candidate["source_evidence"].get("character_pending_reasons", []))
        retired.update(responsibility["retired_ids"])
        retirement_records.extend(responsibility["certificates"])
        objects.append(candidate)
        if not complete:
            uncertainties.append({"id": candidate["id"], "reason": "CIRCULAR_MARKER_INTERIOR_CHARACTER_PENDING",
                                  "boundary_restored": True, "complete_marker": False,
                                  "reasons": candidate["source_evidence"]["character_pending_reasons"]})
        decisions.append(decision)
        save_json(output / "adoption_progress.json", {
            "processed": index + 1, "total_round_observations": len(discovery["rows"]),
            "objects": objects, "retired_ids": sorted(retired), "decisions": decisions,
            "source_sha256": source_sha,
        })
        if progress_callback:
            progress_callback({"stage": "circular_marker_complete", "processed": index + 1,
                               "total": len(discovery["rows"]), "complete": complete,
                               "object_id": row["id"], "new_model_calls": new_model_calls})
    if _digest(prior_objects) != before:
        raise AssertionError("CIRCULAR_ADOPTION_MUTATED_PRIOR_OBJECTS")
    result = {
        "schema": "native-circular-marker-completion-v1", "coordinate_system": COORDINATES,
        "source_sha256": source_sha, "roi_xyxy_px": list(roi), "policy": dict(POLICY),
        "objects": objects, "retired_ids": sorted(retired), "retirement_records": retirement_records,
        "uncertainties": uncertainties, "decisions": decisions, "discovery": discovery,
        "prior_objects_sha256_before": before, "prior_objects_sha256_after": _digest(prior_objects),
        "source_pixels_modified": False,
        "summary": {
            "observed_round_boundaries": len(discovery["rows"]),
            "new_complete_markers": sum(obj["kind"] == "CIRCULAR_MARKER" for obj in objects),
            "new_partial_boundaries": sum(obj["kind"] == "CIRCLE" for obj in objects),
            "new_formal_objects": len(objects), "retired_old_whole_objects": len(retired),
            "retained_prior_objects": len(prior_objects) - len(retired),
            "pending_positions": len(uncertainties),
            "new_Tesseract_calls": new_tesseract_calls, "new_model_calls": new_model_calls,
            "circle_and_text_counted_as_one_complete_marker": True,
        },
    }
    result["raw_evidence_files"] = [
        {"path": path.relative_to(output.parent).as_posix(),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != output / "circular_markers.json"
    ]
    save_json(output / "circular_markers.json", result)
    return result
