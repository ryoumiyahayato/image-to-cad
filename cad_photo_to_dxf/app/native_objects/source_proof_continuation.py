"""Audit a current save against a complete, bound upstream source proof.

Historical CAD is read only as audit evidence. Source assembly is the sole
construction input. Fresh legacy cold replay is retained without modification.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import ezdxf
import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates

from .contracts import save_json
from .execution import file_sha, read_json
from .independent_saved_geometry_audit import _snapshot_doc, _index

SCHEMA = "source-proof-continuation-saved-audit-v1"
CAPSULE_SCHEMA = "historical-complete-source-proof-capsule-v1"
MODE = "SOURCE_CHECKPOINT_PROOF_CONTINUATION"
AUDIT_NAME = "source_proof_continuation_audit.json"
PRIMITIVE_TYPES = {"LINE", "LWPOLYLINE", "ARC", "CIRCLE"}
_OLD_CHECK_FIELDS = {
    "LINE": {"member", "max_distance_px", "source_fraction", "maximum_gap_px", "samples"},
    "LWPOLYLINE": {"member", "max_distance_px", "source_fraction", "maximum_gap_px", "samples"},
    "ARC": {"member", "max_distance_px", "samples", "tolerance_px", "sampled_sweep_deg"},
    "CIRCLE": {"member", "max_distance_px", "samples", "tolerance_px", "sampled_sweep_deg"},
    "NATIVE_TEXT_CANDIDATE_BINDING": {"scope", "actual_text_attributes", "saved_candidate_checks"},
    "SINGLE_LINE_TEXT_SOURCE_BINDING": {"saved_candidate_checks", "saved_candidate_pass", "source_replay",
                                         "actual_saved_text_round_clearance", "actual_saved_source_component_layout",
                                         "source_text_matches_candidate", "source_bbox_matches_candidate", "source_rotation_is_supported"},
    "TEXT_CONTACT_MANIFEST_BINDING": {"checks", "failures", "stage_context_checks"},
    "SAVED_TEXT_CONTACT_PATH_SOURCE": {"checks", "original_source_plan_replay",
                                       "actual_source_geometry", "shared_neighbor_source_checks"},
    "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT": {"checks"},
    "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION": {"protected_count", "objects"},
    "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES": {"conflicts"},
    "SAVED_CARRIER_SOURCE_AND_RETIREMENT": {"checks", "source_replay", "errors", "actual_same_source_residues"},
    "SAVED_RECONCILED_CARRIER_LINE": {"checks"},
    "SAVED_CARRIER_NEIGHBOR_PROTECTION": {"objects"},
    "SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY": {"text", "kind", "actual_native_TEXT_members", "source_replay",
        "independent_graphic_owner_ids", "original_glyph_and_shared_core_samples_replayed",
        "original_and_partition_raw_conflicts_replayed", "minimum_complete_editing_group_verified"},
    "CIRCULAR_SOURCE_BINDING": {"saved_candidate_checks", "ring_source"},
    "CIRCLE_ENDPOINT_CONTACT": {"restored_endpoints", "actual_saved_geometry_checked", "original_source_records_preserved",
                                "external_entity_is_independent"},
    "CIRCLE_WHITE_GAP_PROTECTION": {"protected_source_white_gaps", "actual_saved_line_checked",
                                     "original_source_records_preserved", "source_supported_exterior_line_preserved"},
}
_SOURCE_REPLAY_FIELDS = {
    "SINGLE_LINE_TEXT_SOURCE_BINDING": {"text", "bbox_xyxy_px", "geometry", "layout_adoption",
        "all_raw_artifacts_read_and_hashed", "transcription_source_pass", "source_partition_replay_comparison",
        "Tesseract_views_replayed", "PP_OCR_views_replayed"},
    "SAVED_CARRIER_SOURCE_AND_RETIREMENT": {"checks", "replacement_ids", "retired_ids"},
    "SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY": {"text", "layout", "complete_original_components_replayed",
        "original_and_derived_raw_replayed", "all_competing_readings_retained_and_rechecked"},
}
_PROOF_FIELDS = {
    "original_source_plan_replay": {"checks", "reason"},
    "actual_source_geometry": {"checks", "actual_source_support"},
    "ring_source": {"object_id", "reasons", "crop_hash_matches", "all_source_runs_replayed", "full_circle_samples",
        "minimum_center_ink", "maximum_centerline_source_distance_px", "interior_component_evidence_recomputed",
        "closed_source_enclosure", "contact_port_count", "external_connection_geometry_owned"},
    "character_source": {"text", "text_geometry", "decision", "adoption_basis", "complete_source_raw_characters",
        "source_bbox_xyxy_px", "independent_engine_families", "all_raw_artifacts_read_and_hashed",
        "Tesseract_views_replayed", "PP_OCR_views_replayed", "original_glyph_pixels_and_model_tensors_rechecked"},
    "actual_saved_text_round_clearance": {"schema", "policy", "source_partition_sha256", "actual_text_attributes_sha256",
        "font_sha256", "source_pixels_modified", "font_or_text_geometry_modified", "relations"},
}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _digest(value):
    from .source_stage_checkpoint import digest
    return digest(value)


def _unique(rows):
    result = {row["id"]: row for row in rows}
    _require(len(result) == len(rows), "PROOF_DUPLICATE_SOURCE_OBJECT_ID")
    return result


def _validate_historical_check(row):
    required = _OLD_CHECK_FIELDS.get(row.get("type"))
    _require(required is not None and {"id", "type", "pass"} | required <= set(row),
             "HISTORICAL_UPSTREAM_CHECK_SCHEMA_UNKNOWN_OR_INCOMPLETE")
    _require(isinstance(row["id"], str) and row["pass"] is True, "HISTORICAL_UPSTREAM_CHECK_FAILED")
    for key in ("checks", "saved_candidate_checks", "stage_context_checks"):
        if key in row:
            _require(isinstance(row[key], dict) and row[key] and all(value is True for value in row[key].values()),
                     "HISTORICAL_UPSTREAM_CHECK_DETAIL_FAILED:" + key)
    for key in ("source_replay", "original_source_plan_replay", "actual_source_geometry", "ring_source", "character_source",
                "actual_saved_text_round_clearance", "actual_saved_source_component_layout"):
        value = row.get(key)
        if key in required or key in row:
            _require(isinstance(value, dict) and value.get("pass") is True and len(value) > 1,
                     "HISTORICAL_UPSTREAM_CHECK_DETAIL_FAILED:" + key)
            fields = _SOURCE_REPLAY_FIELDS.get(row["type"], set()) if key == "source_replay" else _PROOF_FIELDS.get(key, set())
            _require(fields <= set(value), "HISTORICAL_UPSTREAM_PROOF_BODY_INCOMPLETE:" + key)
            if "checks" in value:
                _require(isinstance(value["checks"], dict) and value["checks"]
                         and all(result is True for result in value["checks"].values()),
                         "HISTORICAL_UPSTREAM_NESTED_CHECK_FAILED:" + key)
    for key in ("saved_candidate_pass", "source_text_matches_candidate", "source_bbox_matches_candidate",
                "source_rotation_is_supported", "original_glyph_and_shared_core_samples_replayed",
                "original_and_partition_raw_conflicts_replayed", "minimum_complete_editing_group_verified",
                "actual_saved_geometry_checked", "original_source_records_preserved", "external_entity_is_independent",
                "actual_saved_line_checked", "source_supported_exterior_line_preserved"):
        if key in row:
            _require(row[key] is True, "HISTORICAL_UPSTREAM_RESPONSIBILITY_FAILED:" + key)
    if "ring_source" in row:
        ring = row["ring_source"]
        _require(ring["crop_hash_matches"] is True and ring["all_source_runs_replayed"] is True
                 and isinstance(ring["closed_source_enclosure"], dict) and ring["closed_source_enclosure"].get("pass") is True,
                 "HISTORICAL_CLOSED_RING_PROOF_FAILED")
    if "character_source" in row:
        character = row["character_source"]
        _require(character["all_raw_artifacts_read_and_hashed"] is True
                 and character["original_glyph_pixels_and_model_tensors_rechecked"] is True,
                 "HISTORICAL_CHARACTER_RAW_PROOF_FAILED")
        if character["decision"].get("accepted") is not True:
            _require(isinstance(character.get("source_reference_verification"), dict)
                     and character["source_reference_verification"].get("pass") is True
                     and character.get("source_reference_resolution_recomputed") is True,
                     "HISTORICAL_COMPETING_CHARACTER_REFERENCE_PROOF_REQUIRED")
    for key in ("failures", "errors", "conflicts", "actual_same_source_residues"):
        if key in row:
            _require(row[key] == [], "HISTORICAL_UPSTREAM_CHECK_CONFLICT:" + key)
    if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE":
        if "actual_start_contacts_required_circle" in row["checks"]:
            _require(isinstance(row.get("actual_structural_endpoint_contacts"), dict),
                     "HISTORICAL_STRUCTURAL_ENDPOINT_VARIANT_INCOMPLETE")
        if "transverse_producer_kind_bound_to_actual_plan" in row["checks"]:
            _require(isinstance(row.get("actual_transverse_shared_source_responsibility"), dict),
                     "HISTORICAL_TRANSVERSE_SHARED_SOURCE_VARIANT_INCOMPLETE")
    if "objects" in required:
        _require(isinstance(row["objects"], list) and all(
            isinstance(member, dict) and member.get("pass") is True and member.get("checks")
            and all(value is True for value in member["checks"].values()) for member in row["objects"]),
            "HISTORICAL_NEIGHBOR_PROOF_INCOMPLETE_OR_FAILED")
        if "protected_count" in row:
            _require(row["protected_count"] == len(row["objects"]), "HISTORICAL_PROTECTED_NEIGHBOR_COUNT_CHANGED")
    if row["type"] in {"LINE", "LWPOLYLINE"}:
        _require(row["source_fraction"] >= .98 and row["maximum_gap_px"] <= 5 and row["samples"] >= 2,
                 "HISTORICAL_PRIMITIVE_SOURCE_SAMPLE_FAILED")
    elif row["type"] in {"ARC", "CIRCLE"}:
        _require(row["tolerance_px"] == 2.5 and row["max_distance_px"] <= 2.5 and row["samples"] >= 3,
                 "HISTORICAL_CURVE_SOURCE_SAMPLE_FAILED")


def project_historical_checks(cold, removed_ids):
    """Remove only the bound old attached stage, never a current failure list."""
    removed = set(removed_ids)
    stage = cold["attached_stroke_source_checks"]["checks"]
    counts = Counter(_digest(row) for row in stage)
    kept, excluded = [], []
    for row in cold["source_checks"]:
        key = _digest(row)
        if counts[key]:
            counts[key] -= 1
            excluded.append(row)
        elif row.get("id") in removed and row.get("type") in PRIMITIVE_TYPES:
            excluded.append(row)
        else:
            kept.append(row)
    _require(not any(counts.values()), "HISTORICAL_ATTACHED_CHECKS_NOT_IN_COMPLETE_COLD_PROOF")
    _require(not any(row.get("id") in removed for row in kept), "HISTORICAL_REMOVED_OBJECT_HAS_UNPROJECTABLE_PROOF")
    _require(kept and all(row.get("pass") is True for row in kept),
             "HISTORICAL_UPSTREAM_SOURCE_PROOF_MISSING_OR_FAILED")
    for row in kept:
        _validate_historical_check(row)
    return kept, excluded


def create_historical_capsule(evidence, request, state, removed_ids, output, historical_export=None):
    from .source_stage_checkpoint import _inside, _copy, _record

    evidence, output = Path(evidence), Path(output)
    saved = evidence.parent
    export_path = Path(historical_export) if historical_export else saved.parent / (saved.name.removesuffix(".native") + ".export.json")
    export = read_json(export_path)
    # The original export is verified in full before projecting reusable proof.
    for name, expected in export["evidence_files"].items():
        path = _inside(saved, name)
        _require(path.is_file() and file_sha(path) == expected, "HISTORICAL_EXPORT_MEMBER_CHANGED:" + name)
    for name, expected in export["files"].items():
        path = _inside(export_path.parent, name)
        _require(path.is_file() and file_sha(path) == expected, "HISTORICAL_EXPORT_ROOT_MEMBER_CHANGED:" + name)
    inputs = {"saved_dxf": saved / "result.dxf", "sidecar": saved / "result.objects.json",
              "cold_audit": evidence / "cold_audit.json", "export_manifest": export_path,
              "publication_manifest": saved / "publication_manifest.json"}
    names = {"saved_dxf": "result.dxf", "sidecar": "result.objects.json", "cold_audit": "cold_audit.json",
             "export_manifest": "export.json", "publication_manifest": "publication_manifest.json"}
    artifacts = {}
    for key, path in inputs.items():
        name = "origin/saved_proof/" + names[key]
        _copy(path, output / name)
        artifacts[key] = _record(output / name, name)
    checks, _ = project_historical_checks(read_json(inputs["cold_audit"]), removed_ids)
    return {"schema": CAPSULE_SCHEMA, "artifacts": artifacts,
            "source_sha256": request["source_sha256"], "parameters": request["parameters"],
            "upstream_state_sha256": _digest(state),
            "historical_upstream_check_projection_sha256": _digest(checks),
            "historical_export_members_verified_at_creation": len(export["evidence_files"]),
            "historical_DXF_read_for_proof_validation": True,
            "old_DXF_entities_used_to_construct_output": False}


def validate_historical_capsule(root, capsule, state, request, removed_ids, evidence_artifacts):
    from .source_stage_checkpoint import _checked

    root = Path(root)
    _require(capsule.get("schema") == CAPSULE_SCHEMA, "HISTORICAL_SOURCE_PROOF_CAPSULE_REQUIRED")
    required = {"saved_dxf", "sidecar", "cold_audit", "export_manifest", "publication_manifest"}
    _require(set(capsule["artifacts"]) == required, "HISTORICAL_PROOF_ARTIFACT_SET_CHANGED")
    paths = {key: _checked(root, row) for key, row in capsule["artifacts"].items()}
    meta, cold = read_json(paths["sidecar"]), read_json(paths["cold_audit"])
    export, publication = read_json(paths["export_manifest"]), read_json(paths["publication_manifest"])
    dxf_sha, meta_sha, cold_sha = (file_sha(paths[key]) for key in ("saved_dxf", "sidecar", "cold_audit"))
    _require(meta["dxf_sha256"] == cold["dxf_sha256"] == export["DXF_sha256"] == dxf_sha,
             "HISTORICAL_DXF_SIDECAR_COLD_EXPORT_BINDING_CHANGED")
    _require(export["source_sha256"] == meta["source_sha256"] == capsule["source_sha256"] == request["source_sha256"]
             and export["algorithm"] == request["algorithm"], "HISTORICAL_SOURCE_OR_WORKER_PRODUCER_CHANGED")
    _require(meta["roi_xyxy_px"] == request["parameters"]["roi"]
             and meta["dpi"] == request["parameters"]["dpi"] and meta["unit"] == "paper_mm"
             and capsule["parameters"] == request["parameters"], "HISTORICAL_FRAME_OR_UNITS_CHANGED")
    expected = {"result.dxf": dxf_sha, "result.objects.json": meta_sha, "evidence/cold_audit.json": cold_sha,
                "publication_manifest.json": file_sha(paths["publication_manifest"])}
    for name, sha in expected.items():
        _require(export["evidence_files"].get(name) == sha, "HISTORICAL_EXPORT_PROOF_CLOSURE_CHANGED:" + name)
        if name != "publication_manifest.json":
            _require(publication["files"].get(name, {}).get("sha256") == sha,
                     "HISTORICAL_WORKER_PUBLICATION_PROOF_CHANGED:" + name)
    identity = publication["identity"]
    _require(identity["source_sha256"] == request["source_sha256"]
             and identity["algorithm_sha256"] == request["algorithm"]["sha256"],
             "HISTORICAL_PUBLICATION_WORKER_IDENTITY_CHANGED")
    for row in evidence_artifacts:
        _require(export["evidence_files"].get(row["path"]) == row["sha256"],
                 "HISTORICAL_REUSED_SOURCE_ASSET_NOT_EXPORT_BOUND:" + row["path"])
    old, upstream = _unique(meta["objects"]), _unique(state["objects"])
    _require(set(old) == set(upstream) | set(removed_ids)
             and all(old.get(oid) == obj for oid, obj in upstream.items()),
             "HISTORICAL_COMPLETE_SOURCE_OBJECT_PAYLOAD_CHANGED")
    _require(_digest(state) == capsule["upstream_state_sha256"], "HISTORICAL_UPSTREAM_STATE_CHANGED")
    kept, excluded = project_historical_checks(cold, removed_ids)
    for row in kept:
        if row["type"] == "CIRCULAR_SOURCE_BINDING" and old[row["id"]]["kind"] == "CIRCULAR_MARKER":
            _require(isinstance(row.get("character_source"), dict) and row["character_source"].get("pass") is True,
                     "HISTORICAL_CIRCLE_CHARACTER_VARIANT_INCOMPLETE")
    _require(set(upstream) <= {row.get("id") for row in kept}
             and _digest(kept) == capsule["historical_upstream_check_projection_sha256"],
             "HISTORICAL_UPSTREAM_PROOF_COVERAGE_CHANGED")
    _require(cold.get("dxf_unchanged") is True and not cold.get("ezdxf_errors")
             and not cold.get("ezdxf_in_memory_fixes") and not cold.get("exact_duplicate_segments"),
             "HISTORICAL_SAVED_STRUCTURE_OR_DUPLICATE_PROOF_FAILED")
    _require(capsule.get("historical_DXF_read_for_proof_validation") is True
             and capsule.get("old_DXF_entities_used_to_construct_output") is False,
             "HISTORICAL_DXF_RESPONSIBILITY_FLAGS_CHANGED")
    doc = ezdxf.readfile(paths["saved_dxf"])
    snapshot = _snapshot_doc(doc)
    _require(set(snapshot["formal"]) == set(old) and not snapshot["identity_errors"]
             and not snapshot["complete_object_dependency_errors"], "HISTORICAL_ACTUAL_SAVED_IDENTITY_INVALID")
    return {"paths": paths, "metadata": meta, "cold": cold, "export": export,
            "publication": publication, "document": doc, "snapshot": snapshot,
            "upstream_checks": kept, "excluded_checks": excluded,
            "projection": {"source_check_count": len(kept), "source_checks_sha256": _digest(kept),
                           "covered_object_ids": sorted(upstream), "excluded_stage_object_ids": sorted(removed_ids),
                           "excluded_check_count": len(excluded), "all_upstream_checks_passed": True,
                           "complete_check_type_counts": dict(Counter(row["type"] for row in kept)),
                           "whole_historical_source_gate_boolean_used": False}}


def _expanded(entity):
    if entity.dxftype() == "INSERT":
        for member in entity.virtual_entities():
            yield from _expanded(member)
    elif entity.dxftype() == "LWPOLYLINE" and any(abs(float(b)) > 0 for *_, b in entity.get_points("xyb")):
        yield from entity.virtual_entities()
    else:
        yield entity


def sample_current_geometry(doc, gray, roi, dpi):
    """Repeat the existing direct sample rules, without any source refitting."""
    mm = 25.4 / float(dpi)
    x0, y0, x1, y1 = roi
    ox, oy = max(0, x0 - 8), max(0, y0 - 8)
    rx, by = min(gray.shape[1], x1 + 8), min(gray.shape[0], y1 + 8)
    dist = distance_transform_edt(gray[oy:by, ox:rx] >= 128)
    actual, _, errors = _index(doc)
    _require(not errors, "CURRENT_SAVED_IDENTITY_INVALID")
    checks, repetitions, seen = [], [], {}
    def px(point):
        return np.array([point[0] / mm + x0, y1 - point[1] / mm])
    for oid, parent in actual.items():
        for index, member in enumerate(_expanded(parent)):
            kind = member.dxftype()
            if kind in {"TEXT", "MTEXT"}:
                continue
            if kind in {"ARC", "CIRCLE"}:
                center, radius = px(member.dxf.center), member.dxf.radius / mm
                start = float(member.dxf.start_angle) if kind == "ARC" else 0.
                sweep = (float(member.dxf.end_angle) - start) % 360 if kind == "ARC" else 360.
                angle = np.deg2rad(np.linspace(start, start + sweep, max(3, int(math.ceil(radius * math.radians(sweep) / .05)) + 1)))
                points = center + radius * np.column_stack((np.cos(angle), -np.sin(angle)))
                distances = map_coordinates(dist, [points[:, 1] - oy, points[:, 0] - ox], order=1, mode="constant", cval=999)
                checks.append({"id": oid, "member": index, "type": kind, "max_distance_px": float(distances.max()),
                               "samples": len(distances), "tolerance_px": 2.5, "sampled_sweep_deg": sweep,
                               "pass": bool(distances.max() <= 2.5)})
                continue
            if kind == "LINE":
                segments = [(px(member.dxf.start), px(member.dxf.end))]
            elif kind == "LWPOLYLINE":
                points = [px(p) for p in member.get_points("xy")]
                segments = list(zip(points, points[1:] + (points[:1] if member.closed else [])))
            else:
                raise ValueError("UNSUPPORTED_CURRENT_NATIVE_SOURCE_MEMBER:" + kind)
            for segment, (a, b) in enumerate(segments):
                length = float(np.linalg.norm(b - a))
                points = np.linspace(a, b, max(2, int(math.ceil(length / .25)) + 1))
                distances = map_coordinates(dist, [points[:, 1] - oy, points[:, 0] - ox], order=1, mode="constant", cval=999)
                transitions = np.diff(np.r_[False, distances > 2, False].astype(int))
                starts, ends = np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1)
                gap = float(max(ends - starts, default=0) * length / max(1, len(points) - 1))
                fraction = float(np.mean(distances <= 2))
                checks.append({"id": oid, "member": index, "segment": segment, "type": kind,
                               "max_distance_px": float(distances.max()), "source_fraction": fraction,
                               "maximum_gap_px": gap, "samples": len(distances),
                               "pass": fraction >= .98 and gap <= 5})
                # The existing cold audit's exact duplicate-report convention;
                # authorization below requires exact actual complete geometry.
                key = json.dumps(sorted([np.round(a, 7).tolist(), np.round(b, 7).tolist()]))
                current = {"id": oid, "handle": parent.dxf.handle, "member": index, "segment": segment}
                if key in seen:
                    previous = seen[key]
                    repetitions.append({"objects": [previous["id"], oid], "same_geometry": key,
                                        "actual_handles": [previous["handle"], parent.dxf.handle],
                                        "expanded_member_indices": [previous["member"], index],
                                        "segment_indices": [previous["segment"], segment]})
                else:
                    seen[key] = current
    return {"checks": checks, "all_repeated_segments": repetitions,
            "source_distance_thresholds_changed": False,
            "pass": bool(checks) and all(row["pass"] for row in checks)}


def rebind_retrace_allowances(old_doc, current_doc, old_cold, objects, upstream_ids, repeated, gray, roi, dpi):
    old_entities, _, old_errors = _index(old_doc)
    current, _, errors = _index(current_doc)
    _require(not errors and not old_errors, "RETRACE_ACTUAL_IDENTITY_INVALID")
    old_by_handle = {entity.dxf.handle: oid for oid, entity in old_entities.items()}
    _require(len(old_by_handle) == len(old_entities), "RETRACE_HISTORICAL_HANDLE_NOT_UNIQUE")
    rows = old_cold["same_owner_retrace_cold_proof"]["allowances"] + old_cold["text_contact_source_checks"]["allowances"]
    allowed = {}
    for row in rows:
        oid = old_by_handle.get(row.get("handle"))
        if oid not in upstream_ids:
            continue
        _require(oid in current and row.get("id", oid) == oid, "RETRACE_HISTORICAL_OWNER_CHANGED")
        entity = current[oid]
        _require(entity.dxftype() == "LWPOLYLINE" and not entity.closed, "RETRACE_CURRENT_OWNER_NOT_OPEN_POLYLINE")
        indices = tuple(sorted(row["segment_indices"]))
        vertices = [tuple(p[:2]) for p in entity.get_points("xyseb")]
        _require(len(indices) == 2 and indices[0] != indices[1] and min(indices) >= 0
                 and max(indices) < len(vertices) - 1, "RETRACE_ACTUAL_SEGMENT_INDEX_INVALID")
        segments = [tuple(sorted((vertices[i], vertices[i + 1]))) for i in indices]
        _require(segments[0] == segments[1], "RETRACE_ACTUAL_FINITE_SEGMENTS_DIFFER")
        edge = [tuple(p) for p in row["source_edge"]]
        _require(len(edge) == 2 and all(len(p) == 2 and all(isinstance(v, (int, float)) and v == int(v) for v in p) for p in edge),
                 "RETRACE_SOURCE_EDGE_NOT_INTEGER")
        _require(all(0 <= x < gray.shape[1] and 0 <= y < gray.shape[0] and gray[int(y), int(x)] < 128 for x, y in edge)
                 and 0 < max(abs(edge[0][k] - edge[1][k]) for k in (0, 1)) <= 1,
                 "RETRACE_SOURCE_EDGE_IS_NOT_ORIGINAL_ADJACENT_INK")
        source_path = [tuple(p) for p in objects[oid]["source_evidence"]["source_path_points"]]
        key = tuple(sorted(edge))
        _require(key in {tuple(sorted(pair)) for pair in zip(source_path, source_path[1:])},
                 "RETRACE_SOURCE_EDGE_NOT_IN_COMPLETE_OWNER_PATH")
        mm = 25.4 / float(dpi)
        expected = tuple(sorted(((float(x) - roi[0]) * mm, (roi[3] - float(y)) * mm) for x, y in edge))
        _require(segments[0] == expected, "RETRACE_ACTUAL_SEGMENT_DIFFERS_FROM_SOURCE_EDGE")
        actual_key = (entity.dxf.handle, *indices)
        _require(actual_key not in allowed, "RETRACE_DUPLICATE_ALLOWANCE")
        allowed[actual_key] = {"id": oid, "handle": entity.dxf.handle, "segment_indices": list(indices),
                               "source_edge": row["source_edge"], "historical_allowance_sha256": _digest(row),
                               "complete_current_native_path_exact": True, "original_adjacent_ink_rechecked": True,
                               "pass": True}
    certified, conflicts = [], []
    for row in repeated:
        handles, ids, members = row.get("actual_handles", []), row.get("objects", []), row.get("expanded_member_indices", [])
        indices = row.get("segment_indices", [])
        binding = allowed.get((handles[0], *sorted(indices))) if len(handles) == len(indices) == 2 else None
        if (len(ids) != 2 or ids[0] != ids[1] or handles[0] != handles[1] or members != [0, 0]
                or binding is None or binding["id"] != ids[0]):
            conflicts.append(row)
        else:
            certified.append({**row, "source_certificate": binding})
    return {"all_repeated_segments": repeated, "bound_allowances": list(allowed.values()),
            "certified_same_owner_retraces": certified, "unproved_or_cross_owner_duplicates": conflicts,
            "historical_handles_reused_as_current_handles": False,
            "pass": not conflicts and all(row["pass"] for row in allowed.values())}


def review_bound_saved_proof(path, gray, roi, dpi, evidence_root, root, manifest, state):
    """Core review; publication callers first verify the complete v2 checkpoint."""
    from .source_stage_checkpoint import _checked, _inside

    path, evidence_root, root = Path(path), Path(evidence_root), Path(root)
    fresh_path = evidence_root / "cold_audit.json"
    fresh, meta = read_json(fresh_path), read_json(path.with_suffix(".objects.json"))
    evidence_rows = [row for row in manifest["artifacts"] if row["path"].startswith("evidence/")]
    old = validate_historical_capsule(root, manifest["historical_saved_proof"], state,
                                     read_json(root / "origin/request.json"),
                                     manifest["excluded_historical_stage_object_ids"], evidence_rows)
    restored = []
    for row in evidence_rows:
        relative = row["path"][len("evidence/"):]
        _checked(evidence_root, {**row, "path": relative})
        restored.append({"path": relative, "bytes": row["bytes"], "sha256": row["sha256"], "pass": True})
    source = manifest["source"]
    _require(hashlib.sha256(np.asarray(gray).tobytes()).hexdigest() == source["working_array_sha256"]
             and list(roi) == source["working_roi_xyxy_px"] and dpi == source["parameters"]["dpi"],
             "CURRENT_ORIGINAL_PIXELS_OR_FRAME_CHANGED")
    dxf_sha = file_sha(path)
    _require(meta["dxf_sha256"] == fresh["dxf_sha256"] == dxf_sha and fresh.get("dxf_unchanged") is True,
             "CURRENT_SAVED_SIDECAR_OR_FRESH_AUDIT_STALE")
    _require(meta["source_sha256"] == source["source_sha256"] and meta["roi_xyxy_px"] == list(roi)
             and meta["dpi"] == dpi and meta["unit"] == "paper_mm", "CURRENT_SAVED_SOURCE_FRAME_CHANGED")
    _require(not fresh.get("ezdxf_errors") and not fresh.get("ezdxf_in_memory_fixes"), "CURRENT_DXF_COLD_STRUCTURE_FAILED")
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    _require(not auditor.errors and not auditor.fixes, "CURRENT_DXF_AUDIT_FAILED")
    current, upstream = _unique(meta["objects"]), _unique(state["objects"])
    adoption_path, plan_path = evidence_root / "attached_strokes/adoption.json", evidence_root / "attached_strokes/plan.json"
    adoption, plan = read_json(adoption_path), read_json(plan_path)
    adopted = _unique(adoption["objects"])
    _require(adoption["plan"] == plan and adoption.get("retired_ids") == []
             and not (set(adopted) & set(upstream)) and set(current) == set(upstream) | set(adopted),
             "CURRENT_ADOPTION_OR_COMPLETE_OBJECT_SCOPE_CHANGED")
    _require(all(current.get(oid) == obj for oid, obj in upstream.items())
             and all(current.get(oid) == obj for oid, obj in adopted.items()), "CURRENT_COMPLETE_SOURCE_PAYLOAD_CHANGED")
    snapshot = _snapshot_doc(doc)
    _require(not snapshot["identity_errors"] and not snapshot["complete_object_dependency_errors"]
             and set(snapshot["formal"]) == set(current), "CURRENT_COMPLETE_NATIVE_IDENTITY_FAILED")
    object_checks = [{"id": oid, "complete_native_and_recursive_members_exact": snapshot["complete_formal"].get(oid) == old["snapshot"]["complete_formal"].get(oid),
                      "source_payload_exact": current.get(oid) == upstream[oid]} for oid in sorted(upstream)]
    for row in object_checks:
        row["pass"] = row["complete_native_and_recursive_members_exact"] and row["source_payload_exact"]
    contexts = {name: snapshot[name] == old["snapshot"][name] for name in (
        "review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")}
    def portable_font(row):
        return {key: value for key, value in row.items() if key != "source"}
    contexts["sidecar_portable_font_records"] = (
        portable_font(meta["font"]) == portable_font(old["metadata"]["font"])
        and [portable_font(row) for row in meta["fonts"]] == [portable_font(row) for row in old["metadata"]["fonts"]])
    for name in ("repair_regions", "native_schema", "serialization"):
        contexts["sidecar_" + name] = meta[name] == old["metadata"][name]
    portable_resources = []
    for name, expected in sorted(old["export"]["files"].items()):
        if Path(name).suffix.lower() in {".ttf", ".otf", ".lff"} or Path(name).name.startswith("FONT_LICENSE_"):
            resource = _inside(path.parent, name)
            _require(resource.is_file() and file_sha(resource) == expected, "CURRENT_PORTABLE_RESOURCE_BYTES_CHANGED:" + name)
            portable_resources.append({"path": name, "bytes": resource.stat().st_size, "sha256": expected, "pass": True})
    current_entities, _, _ = _index(doc)
    written, old_written = _unique(meta["written"]), _unique(old["metadata"]["written"])
    _require(set(written) == set(current), "CURRENT_WRITTEN_RECEIPT_SET_CHANGED")
    written_checks = []
    for oid, obj in sorted(current.items()):
        row, entity = written[oid], current_entities[oid]
        members = [member.dxftype() for member in doc.blocks[entity.dxf.name]] if entity.dxftype() == "INSERT" else []
        actual = (row.get("handle") == entity.dxf.handle and row.get("kind") == obj["kind"]
                  and row.get("type") == entity.dxftype() and row.get("block_members") == members)
        prior_exact = oid not in upstream or ({key: value for key, value in row.items() if key != "handle"}
                                              == {key: value for key, value in old_written[oid].items() if key != "handle"})
        written_checks.append({"id": oid, "actual_current_handle_and_members_bound": actual,
                               "upstream_written_payload_exact": prior_exact, "pass": actual and prior_exact})
    saved_content = {"object_checks": object_checks, "context_checks": contexts,
                     "portable_resource_checks": portable_resources, "written_receipt_checks": written_checks,
                     "pass": all(row["pass"] for row in object_checks) and all(contexts.values())
                        and all(row["pass"] for row in written_checks)}
    _require(saved_content["pass"], "CURRENT_RECURSIVE_NATIVE_CONTENT_OR_RESOURCES_CHANGED")
    attached = fresh["attached_stroke_source_checks"]
    from . import attached_stroke_graph as graph

    expected_additional = {"attached_stroke_ink.py": graph.attached_ink.producer_sha256(),
                           "attached_stroke_contacts.py": graph.prior_contacts.producer_sha256(),
                           "attached_stroke_numeric.py": graph.numerical.contract_identity()["module_sha256"]}
    stage = attached.get("stage_execution", {})
    stage_checks = {"stage_executed": attached.get("stage_execution", {}).get("status") == "EXECUTED",
                    "saved_current_plan_bound_to_fresh_replay": attached.get("plan_replay", {}).get("saved_plan_sha256") == graph._digest(plan),
                    "current_producer_and_schema": plan.get("schema") == graph.SCHEMA
                        and adoption.get("schema") == "source-attached-stroke-joint-adoption-v3"
                        and plan.get("producer_sha256") == file_sha(graph.__file__)
                        and plan.get("additional_producer_sha256") == expected_additional
                        and plan.get("joint_contract") == graph.numerical.joint_contract_identity()
                        and plan.get("numerical_contract") == graph.numerical.contract_identity(),
                    "actual_adoption_stage_bound": adoption.get("stage_execution") == attached.get("stage_execution")
                        and adoption.get("source_sha256") == source["source_sha256"]
                        and adoption.get("roi_xyxy_px") == plan.get("roi_xyxy_px") == list(roi)
                        and stage.get("stage") == "complete_attached_strokes"
                        and stage.get("producer_sha256") == plan.get("producer_sha256")
                        and stage.get("additional_producer_sha256") == expected_additional
                        and stage.get("joint_contract") == plan.get("joint_contract")
                        and stage.get("source_graph_input") in {"REBUILT_FROM_ORIGINAL", "CALLER_SUPPLIED_BOUND_ORIGINAL_GRAPH"}
                        and type(stage.get("adopted_path_count")) is int and stage["adopted_path_count"] == len(plan["paths"])
                        and type(stage.get("candidate_path_count")) is int
                        and stage["candidate_path_count"] == sum(len(row.get("candidate_paths", [])) for row in plan["components"])
                        and adoption.get("prior_object_bindings") == plan.get("prior_object_bindings")
                        and plan.get("prior_object_bindings") == sorted([graph.object_binding(obj) for obj in upstream.values()], key=lambda obj: obj["id"]),
                    "complete_current_stage_audit": attached.get("pass") is True,
                    "every_current_stage_check": bool(attached.get("checks"))
                        and all(row.get("pass") is True for row in attached["checks"]),
                    "complete_prior_bindings": {row.get("id") for row in attached.get("prior_object_checks", [])} == set(upstream)
                        and len(attached.get("prior_object_checks", [])) == len(upstream)
                        and all(row.get("pass") is True and row.get("sidecar_matches_prior_source_and_geometry") is True
                                and row.get("actual_saved_geometry_and_all_members_match") is True
                                for row in attached.get("prior_object_checks", [])),
                    "adopted_targets_exact": set(attached.get("targets", [])) == set(adopted)
                        and {row["stroke_id"] for row in plan["paths"]} == set(adopted) and len(plan["paths"]) == len(adopted),
                    "plan_replay": attached.get("plan_replay", {}).get("pass") is True
                        and bool(attached.get("plan_replay", {}).get("checks"))
                        and all(value is True for value in attached.get("plan_replay", {}).get("checks", {}).values()),
                    "complete_path_replay": attached.get("complete_path_replay", {}).get("pass") is True
                        and attached.get("complete_path_replay", {}).get("strict_or_outside_interval_changes") == []}
    _require(all(stage_checks.values()), "CURRENT_ATTACHED_SOURCE_CONTACT_OR_NUMERICAL_STAGE_FAILED")
    direct = sample_current_geometry(doc, gray, roi, dpi)
    _require(direct["pass"], "CURRENT_ACTUAL_GEOMETRY_FAILED_ORIGINAL_PIXEL_SAMPLING")
    direct_legacy_rows = [{key: value for key, value in row.items() if key != "segment"} for row in direct["checks"]]
    _require(direct_legacy_rows == [row for row in fresh["source_checks"] if row.get("type") in PRIMITIVE_TYPES],
             "CURRENT_DIRECT_SAMPLES_DIFFER_FROM_COMPLETE_FRESH_COLD")
    def inventory(rows):
        return Counter(_digest({key: row.get(key) for key in ("id", "type", "member")}) for row in rows)
    expected_inventory = inventory([row for row in old["upstream_checks"] if row.get("type") not in PRIMITIVE_TYPES]
                                   + direct_legacy_rows + attached["checks"])
    _require(expected_inventory == inventory(fresh["source_checks"]), "CURRENT_FRESH_SOURCE_RESPONSIBILITY_INVENTORY_CHANGED")
    circular_duplicates = [row for row in fresh["all_repeated_segments"] if "duplicate_kind" in row]
    _require(direct["all_repeated_segments"] == [row for row in fresh["all_repeated_segments"] if "duplicate_kind" not in row],
             "CURRENT_DUPLICATE_ENUMERATION_DIFFERS_FROM_FRESH_COLD")
    duplicates = rebind_retrace_allowances(old["document"], doc, old["cold"], current, set(upstream),
                                         direct["all_repeated_segments"] + circular_duplicates, gray, roi, dpi)
    _require(duplicates["pass"], "CURRENT_DUPLICATE_HAS_NO_COMPLETE_SAME_OWNER_SOURCE_PROOF")
    report = {"schema": SCHEMA, "mode": MODE, "checkpoint_manifest_sha256": file_sha(root / "manifest.json"),
              "historical_saved_proof": manifest["historical_saved_proof"],
              "fresh_cold_audit": {"path": "cold_audit.json", "sha256": file_sha(fresh_path),
                                   "source_gate_pass": fresh["source_gate_pass"],
                                   "failed_source_check_count": sum(row.get("pass") is not True for row in fresh["source_checks"]),
                                   "exact_duplicate_segment_count": len(fresh["exact_duplicate_segments"])},
              "current_saved": {"dxf_sha256": dxf_sha, "sidecar_sha256": file_sha(path.with_suffix(".objects.json")),
                                "source_sha256": source["source_sha256"], "roi": list(roi), "dpi": dpi},
              "upstream_proof_projection": {**old["projection"], "source_checks": old["upstream_checks"]},
              "saved_content": saved_content, "restored_evidence": {"members": restored, "pass": all(r["pass"] for r in restored)},
              "direct_source_checks": direct, "duplicate_review": duplicates,
              "fresh_source_check_inventory": {"expected": dict(expected_inventory),
                                                "actual": dict(inventory(fresh["source_checks"])), "pass": True,
                                                "independent_primitive_rows_exact": True},
              "current_attached_stage": {"checks": stage_checks, "pass": all(stage_checks.values()),
                                         "plan_sha256": file_sha(plan_path), "adoption_sha256": file_sha(adoption_path),
                                         "stage_execution": attached["stage_execution"], "adopted_object_ids": sorted(adopted),
                                         "candidate_failures_not_promoted": True},
              "checks": {"historical_complete_source_proof": True, "current_complete_saved_content": saved_content["pass"],
                         "complete_fresh_responsibility_inventory": True,
                         "current_restored_evidence_bytes": all(r["pass"] for r in restored),
                         "current_original_pixel_sampling": direct["pass"], "current_repeated_segment_responsibility": duplicates["pass"],
                         "current_attached_stage": all(stage_checks.values())},
              "historical_DXF_read_for_proof_validation": True, "old_DXF_entities_used_to_construct_output": False,
              "old_attached_result_reused": False, "new_upstream_fits": 0, "new_OCR_calls": 0,
              "fresh_legacy_audit_rewritten": False, "uncached_recomputation_preservation_claimed": False}
    report["pass"] = all(report["checks"].values())
    continued = [{**deepcopy(row), "continued_source_proof": True, "historical_check_sha256": _digest(row)} for row in old["upstream_checks"]]
    effective = {key: deepcopy(fresh[key]) for key in ("dxf_sha256", "dxf_unchanged", "ezdxf_errors", "ezdxf_in_memory_fixes",
                 "formal_modelspace_types", "expanded_formal_types", "texts", "room_block_definitions_are_unique", "snapshot")}
    effective.update(schema="source-proof-continuation-effective-audit-v1", source_gate_mode=MODE,
                     checkpoint_manifest_sha256=report["checkpoint_manifest_sha256"], fresh_cold_audit_sha256=report["fresh_cold_audit"]["sha256"],
                     complete_proof_gate_sha256=_digest(report), source_checks=continued + direct["checks"] + deepcopy(attached["checks"]),
                     source_gate_pass=report["pass"], source_geometry_gate_pass=report["pass"],
                     local_retrace_certificate_gate_pass=duplicates["pass"],
                     exact_duplicate_segments=duplicates["unproved_or_cross_owner_duplicates"],
                     all_repeated_segments=duplicates["all_repeated_segments"],
                     certified_same_owner_retraces=duplicates["certified_same_owner_retraces"],
                     source_distance_thresholds_changed=False, CAD_GUI="NOT_RUN_BY_THIS_AUDIT", engineer_UAT="NOT_MEASURED")
    report["effective_cold_audit"] = effective
    return report


def audit_source_proof_continuation(path, gray, roi, dpi, evidence_root, binding, source, *, save=True):
    from .source_stage_checkpoint import verify_checkpoint, CAPTURE_SCHEMA

    _require(binding.get("schema") == CAPTURE_SCHEMA, "EXPLICIT_CAPTURED_V2_SOURCE_CHECKPOINT_REQUIRED")
    root = Path(binding["manifest_path"]).parent
    manifest = verify_checkpoint(root / "manifest.json", source=source, parameters=binding["parameters"],
                                 expected_sha256=binding["manifest_sha256"])
    state = read_json(root / "upstream_state.json")
    report = review_bound_saved_proof(path, gray, roi, dpi, evidence_root, root, manifest, state)
    if save:
        save_json(Path(evidence_root) / AUDIT_NAME, report)
    return report


def verify_saved_continuation_gate(path, evidence_root, binding, source):
    """Independently re-audit persisted bytes after publication or renaming."""
    from .job import make_job
    from .source_import import prepare_source

    saved = read_json(Path(evidence_root) / AUDIT_NAME)
    _require(saved.get("schema") == SCHEMA and saved.get("mode") == MODE and saved.get("pass") is True,
             "SAVED_CONTINUATION_GATE_MISSING_OR_FAILED")
    parameters = binding["parameters"]
    job = make_job(source, path, parameters["roi"], dpi=parameters["dpi"],
                   page_number=parameters.get("page_number"), frame_number=parameters.get("frame_number"),
                   orientation=parameters.get("orientation", 0), job_id="continued-proof-independent-verification")
    prepared = prepare_source(job, persist=False)
    actual = audit_source_proof_continuation(path, prepared.gray, prepared.working_roi, job.dpi,
                                           evidence_root, binding, source, save=False)
    _require(_digest(actual) == _digest(saved), "SAVED_CONTINUATION_GATE_DOES_NOT_REPLAY")
    return actual
