"""Independently bind a v2 continuation receipt to its actual saved evidence.

This module imports neither the continuation producer nor its authorization
function. It preserves the fresh result and verifies complete provenance,
current native content and detailed receipt consistency. It does not supply
new source-model permission for unadopted attached candidates.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

from PIL import Image

from . import independent_saved_geometry_audit as saved

SCHEMA = "independent-source-proof-continuation-binding-v1"
MODE = "SOURCE_CHECKPOINT_PROOF_CONTINUATION"
PRIMITIVES = {"LINE", "LWPOLYLINE", "ARC", "CIRCLE"}
CONTEXT = ("review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")
CAPSULE_KEYS = {"saved_dxf", "sidecar", "cold_audit", "export_manifest", "publication_manifest"}
GATE_CHECKS = {"historical_complete_source_proof", "current_complete_saved_content",
               "current_restored_evidence_bytes", "current_original_pixel_sampling",
               "current_repeated_segment_responsibility", "current_attached_stage",
               "complete_fresh_responsibility_inventory"}
HISTORICAL_CHECK_FIELDS = {
    "LINE": {"member", "max_distance_px", "source_fraction", "maximum_gap_px", "samples"},
    "LWPOLYLINE": {"member", "max_distance_px", "source_fraction", "maximum_gap_px", "samples"},
    "ARC": {"member", "max_distance_px", "samples", "tolerance_px", "sampled_sweep_deg"},
    "CIRCLE": {"member", "max_distance_px", "samples", "tolerance_px", "sampled_sweep_deg"},
    "NATIVE_TEXT_CANDIDATE_BINDING": {"scope", "actual_text_attributes", "saved_candidate_checks"},
    "SINGLE_LINE_TEXT_SOURCE_BINDING": {"saved_candidate_checks", "saved_candidate_pass", "source_replay",
        "actual_saved_text_round_clearance", "actual_saved_source_component_layout", "source_text_matches_candidate",
        "source_bbox_matches_candidate", "source_rotation_is_supported"},
    "TEXT_CONTACT_MANIFEST_BINDING": {"checks", "failures", "stage_context_checks"},
    "SAVED_TEXT_CONTACT_PATH_SOURCE": {"checks", "original_source_plan_replay", "actual_source_geometry", "shared_neighbor_source_checks"},
    "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT": {"checks"},
    "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION": {"protected_count", "objects"},
    "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES": {"conflicts"},
    "SAVED_CARRIER_SOURCE_AND_RETIREMENT": {"checks", "source_replay", "errors", "actual_same_source_residues"},
    "SAVED_RECONCILED_CARRIER_LINE": {"checks"}, "SAVED_CARRIER_NEIGHBOR_PROTECTION": {"objects"},
    "SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY": {"text", "kind", "actual_native_TEXT_members", "source_replay",
        "independent_graphic_owner_ids", "original_glyph_and_shared_core_samples_replayed",
        "original_and_partition_raw_conflicts_replayed", "minimum_complete_editing_group_verified"},
    "CIRCULAR_SOURCE_BINDING": {"saved_candidate_checks", "ring_source"},
    "CIRCLE_ENDPOINT_CONTACT": {"restored_endpoints", "actual_saved_geometry_checked", "original_source_records_preserved", "external_entity_is_independent"},
    "CIRCLE_WHITE_GAP_PROTECTION": {"protected_source_white_gaps", "actual_saved_line_checked",
        "original_source_records_preserved", "source_supported_exterior_line_preserved"},
}
HISTORICAL_REPLAY_FIELDS = {
    "SINGLE_LINE_TEXT_SOURCE_BINDING": {"text", "bbox_xyxy_px", "geometry", "layout_adoption",
        "all_raw_artifacts_read_and_hashed", "transcription_source_pass", "source_partition_replay_comparison",
        "Tesseract_views_replayed", "PP_OCR_views_replayed"},
    "SAVED_CARRIER_SOURCE_AND_RETIREMENT": {"checks", "replacement_ids", "retired_ids"},
    "SHORT_CONTACT_SAVED_SOURCE_AND_EDITING_RESPONSIBILITY": {"text", "layout", "complete_original_components_replayed",
        "original_and_derived_raw_replayed", "all_competing_readings_retained_and_rechecked"},
}
HISTORICAL_PROOF_FIELDS = {
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


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _same(left, right):
    return saved._exact(left) == saved._exact(right)


def _unique(rows):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows) or not all(isinstance(key, str) and key for key in result):
        raise ValueError("INVALID_OR_DUPLICATE_SOURCE_OBJECT_ID")
    return result


def _artifact_path(root, relative):
    rel = PurePosixPath(relative)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError("UNSAFE_PROOF_ARTIFACT_PATH")
    path = Path(root).joinpath(*rel.parts)
    if Path(root).resolve() not in path.resolve().parents or path.is_symlink():
        raise ValueError("PROOF_ARTIFACT_OUTSIDE_CHECKPOINT")
    return path


def _member(root, row):
    path = _artifact_path(root, row["path"])
    if path.stat().st_size != row["bytes"] or saved.sha256(path) != row["sha256"]:
        raise ValueError("PROOF_ARTIFACT_BYTES_CHANGED:" + row["path"])
    return path


def _project(cold, removed):
    counts = Counter(_digest(row) for row in cold["attached_stroke_source_checks"]["checks"])
    kept, excluded = [], []
    for row in cold["source_checks"]:
        key = _digest(row)
        if counts[key]:
            counts[key] -= 1
            excluded.append(row)
        elif row.get("id") in removed and row.get("type") in PRIMITIVES:
            excluded.append(row)
        else:
            kept.append(row)
    if any(counts.values()):
        raise ValueError("HISTORICAL_ATTACHED_CHECK_MULTISET_NOT_FOUND")
    return kept, excluded


def _inventory(rows):
    return Counter((row.get("id"), row.get("type"), row.get("member")) for row in rows)


def _inventory_digests(rows):
    return dict(Counter(_digest({key: row.get(key) for key in ("id", "type", "member")}) for row in rows))


def _historical_detail_valid(row, objects):
    required = HISTORICAL_CHECK_FIELDS.get(row.get("type"))
    if required is None or not {"id", "type", "pass"} | required <= set(row) or row.get("pass") is not True:
        return False
    for key in ("checks", "saved_candidate_checks", "stage_context_checks"):
        if key in row and (not isinstance(row[key], dict) or not row[key] or not all(value is True for value in row[key].values())):
            return False
    for key in ("source_replay", "original_source_plan_replay", "actual_source_geometry", "ring_source", "character_source",
                "actual_saved_text_round_clearance", "actual_saved_source_component_layout"):
        if key not in required and key not in row:
            continue
        body = row.get(key)
        fields = HISTORICAL_REPLAY_FIELDS.get(row["type"], set()) if key == "source_replay" else HISTORICAL_PROOF_FIELDS.get(key, set())
        if (not isinstance(body, dict) or body.get("pass") is not True or len(body) <= 1
                or not fields <= set(body)
                or ("checks" in body and (not isinstance(body["checks"], dict) or not body["checks"]
                    or not all(value is True for value in body["checks"].values())))):
            return False
    if row.get("type") == "CIRCULAR_SOURCE_BINDING" and objects.get(row.get("id"), {}).get("kind") == "CIRCULAR_MARKER":
        if not isinstance(row.get("character_source"), dict) or row["character_source"].get("pass") is not True:
            return False
    for key in ("saved_candidate_pass", "source_text_matches_candidate", "source_bbox_matches_candidate",
                "source_rotation_is_supported", "original_glyph_and_shared_core_samples_replayed",
                "original_and_partition_raw_conflicts_replayed", "minimum_complete_editing_group_verified",
                "actual_saved_geometry_checked", "original_source_records_preserved", "external_entity_is_independent",
                "actual_saved_line_checked", "source_supported_exterior_line_preserved"):
        if key in row and row[key] is not True:
            return False
    if "ring_source" in row:
        ring = row["ring_source"]
        if (ring["crop_hash_matches"] is not True or ring["all_source_runs_replayed"] is not True
                or not isinstance(ring["closed_source_enclosure"], dict) or ring["closed_source_enclosure"].get("pass") is not True):
            return False
    if "character_source" in row:
        character = row["character_source"]
        if (character["all_raw_artifacts_read_and_hashed"] is not True
                or character["original_glyph_pixels_and_model_tensors_rechecked"] is not True):
            return False
        if character["decision"].get("accepted") is not True and (
                not isinstance(character.get("source_reference_verification"), dict)
                or character["source_reference_verification"].get("pass") is not True
                or character.get("source_reference_resolution_recomputed") is not True):
            return False
    if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE":
        if ("actual_start_contacts_required_circle" in row["checks"]
                and not isinstance(row.get("actual_structural_endpoint_contacts"), dict)):
            return False
        if ("transverse_producer_kind_bound_to_actual_plan" in row["checks"]
                and not isinstance(row.get("actual_transverse_shared_source_responsibility"), dict)):
            return False
    if "objects" in required:
        if not isinstance(row["objects"], list) or not all(
                isinstance(member, dict) and member.get("pass") is True and isinstance(member.get("checks"), dict)
                and member["checks"] and all(value is True for value in member["checks"].values()) for member in row["objects"]):
            return False
        if "protected_count" in row and row["protected_count"] != len(row["objects"]):
            return False
    if any(row[key] != [] for key in ("failures", "errors", "conflicts", "actual_same_source_residues") if key in row):
        return False
    return row.get("type") not in PRIMITIVES or _direct_measurement_pass(row)


def _prior_binding(obj):
    evidence = obj.get("source_evidence", {})
    result = {key: obj[key] for key in ("id", "kind", "layer", "geometry")}
    result["source_evidence"] = {key: evidence.get(key) for key in ("source_path_points",
        "original_source_crop_xyxy_px", "original_source_crop_array_sha256", "source_pixels_modified", "text_contact_path")}
    result["source_evidence"].update({key: evidence[key] for key in ("short_contact_text", "text_layout", "text_geometry") if key in evidence})
    return result


def _current_contracts(source_root):
    producer_dir = Path(source_root) / "app/native_objects"
    additional = {name: saved.sha256(producer_dir / name) for name in
        ("attached_stroke_ink.py", "attached_stroke_contacts.py", "attached_stroke_numeric.py")}
    numerical = {"version": "attached-stroke-joint-derived-diagnostics-v3",
        "module_sha256": additional["attached_stroke_numeric.py"],
        "reference_arithmetic_contract": "attached-stroke-derived-diagnostics-interval-v1",
        "finite_reference_arithmetic_model_not_universal_math_library_error_promise": True,
        "raw_diagnostics_retained": True, "non_whitelisted_values_strict": True}
    joint = {"version": "attached-stroke-joint-evidence-contract-v3",
        "plan_schema": "source-attached-stroke-joint-plan-v3", "adoption_schema": "source-attached-stroke-joint-adoption-v3",
        "native_schema": "source-attached-stroke-joint-native-v3",
        "numerical_certificate_schema": "attached-stroke-joint-numerical-certificate-v3",
        "candidate_and_adopted_scopes_separate": True, "numerical_diagnostics_do_not_authorize_raw_source": True,
        "raw_ink_and_saved_native_geometry_exact": True}
    return additional, numerical, joint


def _direct_measurement_pass(row):
    kind = row.get("type")
    if kind not in PRIMITIVES or row.get("pass") is not True:
        return False
    if type(row.get("samples")) is not int or row["samples"] < (3 if kind in {"ARC", "CIRCLE"} else 2):
        return False
    if not isinstance(row.get("max_distance_px"), (float, int)) or not math.isfinite(row["max_distance_px"]):
        return False
    if kind in {"ARC", "CIRCLE"}:
        return (row.get("tolerance_px") == 2.5 and row["max_distance_px"] <= 2.5
                and isinstance(row.get("sampled_sweep_deg"), (float, int))
                and 0 < row["sampled_sweep_deg"] <= 360)
    fraction, gap = row.get("source_fraction"), row.get("maximum_gap_px")
    return (isinstance(fraction, (float, int)) and isinstance(gap, (float, int))
            and math.isfinite(fraction) and math.isfinite(gap) and .98 <= fraction <= 1 and 0 <= gap <= 5)


def _actual_retrace_bindings(old_dxf, current_dxf, old_cold, upstream, source_path, roi, dpi):
    old_doc, doc = saved.ezdxf.readfile(old_dxf), saved.ezdxf.readfile(current_dxf)
    old_entities, _, old_errors = saved._index(old_doc)
    entities, _, errors = saved._index(doc)
    if old_errors or errors:
        raise ValueError("RETRACE_NATIVE_IDENTITIES_INVALID")
    old_handles = {entity.dxf.handle: oid for oid, entity in old_entities.items()}
    if len(old_handles) != len(old_entities):
        raise ValueError("RETRACE_HISTORICAL_HANDLES_NOT_UNIQUE")
    rows = old_cold["same_owner_retrace_cold_proof"]["allowances"] + old_cold["text_contact_source_checks"]["allowances"]
    result, keys = [], set()
    mm = 25.4 / float(dpi)
    with Image.open(source_path) as image:
        gray = image.convert("L")
        for row in rows:
            oid = old_handles.get(row.get("handle"))
            if oid not in upstream:
                continue
            entity = entities[oid]
            indices = sorted(row["segment_indices"])
            if (row.get("id", oid) != oid or entity.dxftype() != "LWPOLYLINE" or entity.closed
                    or len(indices) != 2 or indices[0] == indices[1]
                    or any(not isinstance(i, int) or isinstance(i, bool) for i in indices)):
                raise ValueError("RETRACE_OWNER_OR_INDICES_CHANGED")
            vertices = [tuple(p[:2]) for p in entity.get_points("xyseb")]
            if indices[0] < 0 or indices[-1] >= len(vertices) - 1:
                raise ValueError("RETRACE_SEGMENT_OUTSIDE_CURRENT_ENTITY")
            segments = [tuple(sorted((vertices[i], vertices[i + 1]))) for i in indices]
            edge = [tuple(p) for p in row["source_edge"]]
            if (len(edge) != 2 or any(len(p) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                     or v != int(v) for v in p) for p in edge)
                    or not 0 < max(abs(edge[0][k] - edge[1][k]) for k in (0, 1)) <= 1
                    or not all(0 <= x < gray.width and 0 <= y < gray.height and gray.getpixel((int(x), int(y))) < 128 for x, y in edge)):
                raise ValueError("RETRACE_SOURCE_EDGE_NOT_ACTUAL_ADJACENT_INK")
            source_points = [tuple(p) for p in upstream[oid]["source_evidence"]["source_path_points"]]
            if tuple(sorted(edge)) not in {tuple(sorted(pair)) for pair in zip(source_points, source_points[1:])}:
                raise ValueError("RETRACE_SOURCE_EDGE_NOT_IN_COMPLETE_OWNER_PATH")
            expected = tuple(sorted(((float(x) - roi[0]) * mm, (roi[3] - float(y)) * mm) for x, y in edge))
            if segments[0] != segments[1] or not _same(segments[0], expected):
                raise ValueError("RETRACE_CURRENT_NATIVE_SEGMENT_NOT_EXACT_SOURCE_EDGE")
            key = (entity.dxf.handle, *indices)
            if key in keys:
                raise ValueError("DUPLICATE_RETRACE_ALLOWANCE")
            keys.add(key)
            result.append({"id": oid, "handle": entity.dxf.handle, "segment_indices": indices,
                "source_edge": row["source_edge"], "historical_allowance_sha256": _digest(row),
                "complete_current_native_path_exact": True, "original_adjacent_ink_rechecked": True, "pass": True})
    return result


def audit_source_proof_binding(*, dxf_path, metadata_path, source_path, manifest_path, manifest,
                               continuation, publication, request, source_root, plan, adoption):
    result = {"schema": SCHEMA, "status": "FAIL", "checks": {}, "errors": [],
              "fresh_legacy_result_promoted_to_pass": False,
              "historical_global_source_PASS_consumed": False,
              "new_candidate_source_authorized": False,
              "independent_source_model_reexecution": False}
    checks = result["checks"]
    try:
        parameters = request.get("parameters", {})
        if (parameters.get("orientation") != 0 or parameters.get("page_number") is not None
                or parameters.get("frame_number") is not None):
            raise ValueError("UNSUPPORTED_INDEPENDENT_PROOF_RASTER_ORIENTATION_PAGE_OR_FRAME")
        with Image.open(source_path) as original:
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("UNSUPPORTED_INDEPENDENT_PROOF_MULTIFRAME_RASTER")
        checks["supported_original_raster_selection"] = True
        root = Path(manifest_path).parent
        companion = Path(dxf_path).with_suffix(".native")
        evidence = companion / "evidence"
        gate_path = evidence / "source_proof_continuation_audit.json"
        fresh_path = evidence / "cold_audit.json"
        worker_path = companion / "publication_manifest.json"
        pipeline_path = companion / "result.report.json"
        gate, fresh, worker, pipeline = map(_read, (gate_path, fresh_path, worker_path, pipeline_path))
        before = {str(path): saved.sha256(path) for path in
                  (gate_path, fresh_path, worker_path, pipeline_path, Path(dxf_path), Path(metadata_path), Path(source_path))}
        core = {key: value for key, value in gate.items() if key != "effective_cold_audit"}
        gate_sha, fresh_sha = saved.sha256(gate_path), saved.sha256(fresh_path)
        published = publication["evidence_files"]
        checks["actual_published_gate_fresh_worker_and_report"] = all(
            published.get(name) == saved.sha256(path) for name, path in (
                ("evidence/source_proof_continuation_audit.json", gate_path),
                ("evidence/cold_audit.json", fresh_path),
                ("publication_manifest.json", worker_path), ("result.report.json", pipeline_path)))
        checks["current_gate_schema_and_mode"] = (gate.get("schema") == "source-proof-continuation-saved-audit-v1"
            and gate.get("mode") == MODE and gate.get("checkpoint_manifest_sha256") == saved.sha256(manifest_path))
        gate_execution = continuation["downstream"].get("saved_source_proof_continuation", {})
        checks["continuation_explicit_gate"] = (gate_execution.get("mode") == MODE
            and gate_execution.get("receipt_sha256") == gate_sha and gate_execution.get("pass") is True
            and gate_execution.get("status") == "EXECUTED" and gate_execution.get("receipt") == "source_proof_continuation_audit.json"
            and gate_execution.get("fresh_source_gate_pass") is fresh.get("source_gate_pass"))
        checks["export_explicit_gate_mode"] = (publication.get("source_gate_mode") == MODE
            and publication.get("source_proof_audit_sha256") == gate_sha)
        checks["worker_publication_explicit_mode"] = (worker.get("gates", {}).get("source_gate_mode") == MODE
            and worker["gates"].get("source_proof_audit_sha256") == gate_sha)
        checks["pipeline_report_explicit_mode"] = (pipeline.get("source_gate_mode") == MODE
            and pipeline.get("source_proof_audit_sha256") == gate_sha)
        checks["current_worker_identity"] = (worker.get("identity", {}).get("source_sha256") == request.get("source_sha256")
            and worker["identity"].get("algorithm_sha256") == request.get("algorithm", {}).get("sha256"))
        checks["current_reviewer_code_identity"] = request.get("algorithm", {}).get("files", {}).get(
            "app/native_objects/source_proof_continuation.py") == manifest.get("source_proof_reviewer_sha256") == saved.sha256(
                Path(source_root) / "app/native_objects/source_proof_continuation.py")
        checks["explicit_no_legacy_rewrite_or_geometry_construction"] = (
            gate.get("fresh_legacy_audit_rewritten") is False and gate.get("old_attached_result_reused") is False
            and gate.get("historical_DXF_read_for_proof_validation") is True
            and gate.get("old_DXF_entities_used_to_construct_output") is False
            and gate.get("uncached_recomputation_preservation_claimed") is False)
        checks["fresh_result_exactly_preserved"] = _same(gate.get("fresh_cold_audit"), {
            "path": "cold_audit.json", "sha256": fresh_sha, "source_gate_pass": fresh.get("source_gate_pass"),
            "failed_source_check_count": sum(row.get("pass") is not True for row in fresh["source_checks"]),
            "exact_duplicate_segment_count": len(fresh["exact_duplicate_segments"])})
        checks["fresh_actual_saved_identity"] = (fresh.get("dxf_sha256") == saved.sha256(dxf_path)
            and fresh.get("dxf_unchanged") is True and not fresh.get("ezdxf_errors") and not fresh.get("ezdxf_in_memory_fixes"))
        checks["current_saved_frame_binding"] = _same(gate.get("current_saved"), {
            "dxf_sha256": saved.sha256(dxf_path), "sidecar_sha256": saved.sha256(metadata_path),
            "source_sha256": request["source_sha256"], "roi": request["parameters"]["roi"],
            "dpi": request["parameters"]["dpi"]})
        capsule = manifest["historical_saved_proof"]
        checks["complete_capsule_schema_and_gate_copy"] = (
            capsule.get("schema") == "historical-complete-source-proof-capsule-v1"
            and set(capsule.get("artifacts", {})) == CAPSULE_KEYS and _same(gate.get("historical_saved_proof"), capsule))
        paths = {key: _member(root, row) for key, row in capsule["artifacts"].items()}
        before.update({str(path): saved.sha256(path) for path in paths.values()})
        old_meta, old_cold, old_export, old_worker = (_read(paths[key]) for key in
            ("sidecar", "cold_audit", "export_manifest", "publication_manifest"))
        old_request, state = _read(root / "origin/request.json"), _read(root / "upstream_state.json")
        old_adoption, old_plan = _read(root / "origin/attached_adoption.json"), _read(root / "origin/attached_plan.json")
        upstream, old_objects = _unique(state["objects"]), _unique(old_meta["objects"])
        removed = set(_unique(old_adoption["objects"]))
        checks["historical_attached_scope_exact"] = (
            _same(old_adoption.get("plan"), old_plan) and old_adoption.get("retired_ids") == []
            and removed == set(manifest["excluded_historical_stage_object_ids"])
            == {row["stroke_id"] for row in old_plan["paths"]}
            and all(_same(old_objects.get(row["id"]), row) for row in old_adoption["objects"]))
        proof_files = {"result.dxf": paths["saved_dxf"], "result.objects.json": paths["sidecar"],
                       "evidence/cold_audit.json": paths["cold_audit"]}
        checks["historical_worker_and_export_file_closure"] = all(
            old_worker.get("files", {}).get(name, {}).get("sha256") == saved.sha256(path)
            == old_export.get("evidence_files", {}).get(name) for name, path in proof_files.items())
        checks["historical_publication_digest"] = old_export.get("evidence_files", {}).get(
            "publication_manifest.json") == saved.sha256(paths["publication_manifest"])
        checks["historical_saved_file_identity"] = (saved.sha256(paths["saved_dxf"]) == old_meta.get("dxf_sha256")
            == old_cold.get("dxf_sha256") == old_export.get("DXF_sha256"))
        checks["historical_source_and_producer_identity"] = (
            old_worker.get("identity", {}).get("source_sha256") == old_export.get("source_sha256")
            == old_meta.get("source_sha256") == capsule.get("source_sha256") == old_request.get("source_sha256")
            == request["source_sha256"] and _same(old_export.get("algorithm"), old_request.get("algorithm"))
            and old_worker["identity"].get("algorithm_sha256") == old_request["algorithm"]["sha256"])
        checks["historical_frame_and_complete_source_state"] = (
            _same(old_request.get("parameters"), request.get("parameters"))
            and _same(capsule.get("parameters"), request.get("parameters"))
            and old_meta.get("roi_xyxy_px") == request["parameters"]["roi"]
            and old_meta.get("dpi") == request["parameters"]["dpi"] and old_meta.get("unit") == "paper_mm"
            and set(old_objects) == set(upstream) | removed
            and all(_same(old_objects.get(oid), obj) for oid, obj in upstream.items())
            and capsule.get("upstream_state_sha256") == _digest(state))
        kept, excluded = _project(old_cold, removed)
        expected_projection = {"source_check_count": len(kept), "source_checks_sha256": _digest(kept),
            "covered_object_ids": sorted(upstream), "excluded_stage_object_ids": sorted(removed),
            "excluded_check_count": len(excluded), "all_upstream_checks_passed": True,
            "complete_check_type_counts": dict(Counter(row["type"] for row in kept)),
            "whole_historical_source_gate_boolean_used": False, "source_checks": kept}
        checks["complete_historical_upstream_proof_projection"] = (
            bool(kept) and all(_historical_detail_valid(row, old_objects) for row in kept)
            and not any(row.get("id") in removed for row in kept)
            and set(upstream) <= {row.get("id") for row in kept}
            and capsule.get("historical_upstream_check_projection_sha256") == _digest(kept)
            and _same(gate.get("upstream_proof_projection"), expected_projection))
        checks["historical_structural_evidence"] = (old_cold.get("dxf_unchanged") is True
            and not old_cold.get("ezdxf_errors") and not old_cold.get("ezdxf_in_memory_fixes")
            and not old_cold.get("exact_duplicate_segments"))
        metadata = _read(metadata_path)
        current_objects, current_adopted = _unique(metadata["objects"]), _unique(adoption["objects"])
        checks["current_full_source_payload_and_adopted_scope"] = (
            not (set(upstream) & set(current_adopted)) and set(current_objects) == set(upstream) | set(current_adopted)
            and all(_same(current_objects.get(oid), obj) for oid, obj in {**upstream, **current_adopted}.items()))
        old_snapshot, snapshot = saved.snapshot_dxf(paths["saved_dxf"]), saved.snapshot_dxf(dxf_path)
        object_rows = [{"id": oid,
            "complete_native_and_recursive_members_exact": _same(snapshot["complete_formal"].get(oid), old_snapshot["complete_formal"].get(oid)),
            "source_payload_exact": _same(current_objects.get(oid), upstream[oid])} for oid in sorted(upstream)]
        for row in object_rows:
            row["pass"] = row["complete_native_and_recursive_members_exact"] and row["source_payload_exact"]
        contexts = {key: _same(snapshot[key], old_snapshot[key]) for key in CONTEXT}
        def portable_font(row):
            return {key: value for key, value in row.items() if key != "source"}
        contexts["sidecar_portable_font_records"] = (
            _same(portable_font(metadata["font"]), portable_font(old_meta["font"]))
            and _same([portable_font(row) for row in metadata["fonts"]], [portable_font(row) for row in old_meta["fonts"]]))
        for name in ("repair_regions", "native_schema", "serialization"):
            contexts["sidecar_" + name] = _same(metadata[name], old_meta[name])
        portable_resources = []
        for name, expected in sorted(old_export["files"].items()):
            if Path(name).suffix.lower() not in {".ttf", ".otf", ".lff"} and not Path(name).name.startswith("FONT_LICENSE_"):
                continue
            resource = _artifact_path(Path(dxf_path).parent, name)
            actual_sha = saved.sha256(resource)
            before[str(resource)] = actual_sha
            portable_resources.append({"path": name, "bytes": resource.stat().st_size,
                "sha256": actual_sha, "pass": actual_sha == expected})
        doc = saved.ezdxf.readfile(dxf_path)
        entities, _, entity_errors = saved._index(doc)
        written, old_written = _unique(metadata["written"]), _unique(old_meta["written"])
        written_rows = []
        for oid in sorted(current_objects):
            row, entity = written[oid], entities[oid]
            members = [member.dxftype() for member in doc.blocks[entity.dxf.name]] if entity.dxftype() == "INSERT" else []
            actual = (row.get("handle") == entity.dxf.handle and row.get("kind") == current_objects[oid]["kind"]
                and row.get("type") == entity.dxftype() and row.get("block_members") == members)
            old_exact = oid not in upstream or _same(
                {key: value for key, value in row.items() if key != "handle"},
                {key: value for key, value in old_written[oid].items() if key != "handle"})
            written_rows.append({"id": oid, "actual_current_handle_and_members_bound": actual,
                "upstream_written_payload_exact": old_exact, "pass": actual and old_exact})
        saved_pass = (all(row["pass"] for row in object_rows) and all(contexts.values())
                      and all(row["pass"] for row in written_rows) and all(row["pass"] for row in portable_resources))
        checks["actual_recursive_content_and_resources"] = (
            set(old_snapshot["formal"]) == set(old_objects) and set(snapshot["formal"]) == set(current_objects)
            and not any(snap[key] for snap in (snapshot, old_snapshot) for key in
                        ("identity_errors", "complete_object_dependency_errors"))
            and not entity_errors and set(written) == set(current_objects) and set(old_written) == set(old_objects)
            and saved_pass)
        checks["saved_content_detailed_receipt_exact"] = _same(gate.get("saved_content"), {
            "object_checks": object_rows, "context_checks": contexts,
            "portable_resource_checks": portable_resources, "written_receipt_checks": written_rows, "pass": saved_pass})
        restored = []
        for row in manifest["artifacts"]:
            if not row["path"].startswith("evidence/"):
                continue
            relative = row["path"][len("evidence/"):]
            actual = _member(evidence, {**row, "path": relative})
            before[str(actual)] = saved.sha256(actual)
            restored.append({"path": relative, "bytes": row["bytes"], "sha256": saved.sha256(actual), "pass": True})
            if old_export.get("evidence_files", {}).get(row["path"]) != row["sha256"]:
                raise ValueError("REUSED_SOURCE_ARTIFACT_NOT_HISTORICALLY_PUBLISHED")
        checks["restored_complete_proof_assets"] = bool(restored) and _same(gate.get("restored_evidence"), {
            "members": restored, "pass": all(row["pass"] for row in restored)})
        direct = gate["direct_source_checks"]
        raw_rows = [{key: value for key, value in row.items() if key != "segment"} for row in direct["checks"]]
        fresh_primitive = [row for row in fresh["source_checks"] if row.get("type") in PRIMITIVES]
        attached = fresh["attached_stroke_source_checks"]
        checks["actual_pixel_measurements_and_fresh_rows"] = (
            bool(raw_rows) and _same(raw_rows, fresh_primitive) and all(_direct_measurement_pass(row) for row in raw_rows)
            and direct.get("pass") is True and direct.get("source_distance_thresholds_changed") is False)
        expected_inventory_rows = [row for row in kept if row.get("type") not in PRIMITIVES] + raw_rows + attached["checks"]
        checks["whole_fresh_check_inventory_no_unknown_or_omitted_rows"] = (
            _inventory(fresh["source_checks"]) == _inventory(expected_inventory_rows)
            and _same(gate.get("fresh_source_check_inventory"), {
                "expected": _inventory_digests(expected_inventory_rows), "actual": _inventory_digests(fresh["source_checks"]),
                "pass": True, "independent_primitive_rows_exact": True}))
        graph_plan_sha = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        additional, numerical_contract, joint_contract = _current_contracts(source_root)
        stage = attached.get("stage_execution", {})
        stage_checks = {"stage_executed": attached.get("stage_execution", {}).get("status") == "EXECUTED",
            "saved_current_plan_bound_to_fresh_replay": attached.get("plan_replay", {}).get("saved_plan_sha256") == graph_plan_sha,
            "current_producer_and_schema": plan.get("schema") == "source-attached-stroke-joint-plan-v3"
                and adoption.get("schema") == "source-attached-stroke-joint-adoption-v3"
                and plan.get("producer_sha256") == saved.sha256(Path(source_root) / "app/native_objects/attached_stroke_graph.py")
                and _same(plan.get("additional_producer_sha256"), additional)
                and _same(plan.get("numerical_contract"), numerical_contract) and _same(plan.get("joint_contract"), joint_contract),
            "actual_adoption_stage_bound": _same(adoption.get("stage_execution"), attached.get("stage_execution"))
                and adoption.get("source_sha256") == request["source_sha256"]
                and _same(adoption.get("roi_xyxy_px"), plan.get("roi_xyxy_px"))
                and _same(plan.get("roi_xyxy_px"), request["parameters"]["roi"])
                and stage.get("stage") == "complete_attached_strokes" and stage.get("producer_sha256") == plan.get("producer_sha256")
                and _same(stage.get("additional_producer_sha256"), additional) and _same(stage.get("joint_contract"), joint_contract)
                and stage.get("source_graph_input") in {"REBUILT_FROM_ORIGINAL", "CALLER_SUPPLIED_BOUND_ORIGINAL_GRAPH"}
                and type(stage.get("adopted_path_count")) is int and stage["adopted_path_count"] == len(plan["paths"])
                and type(stage.get("candidate_path_count")) is int
                and stage["candidate_path_count"] == sum(len(row.get("candidate_paths", [])) for row in plan["components"])
                and _same(adoption.get("prior_object_bindings"), plan.get("prior_object_bindings"))
                and _same(plan.get("prior_object_bindings"), [_prior_binding(upstream[oid]) for oid in sorted(upstream)]),
            "complete_current_stage_audit": attached.get("pass") is True,
            "every_current_stage_check": bool(attached.get("checks")) and all(row.get("pass") is True for row in attached["checks"]),
            "complete_prior_bindings": {row.get("id") for row in attached.get("prior_object_checks", [])} == set(upstream)
                and len(attached.get("prior_object_checks", [])) == len(upstream)
                and all(row.get("pass") is True and row.get("sidecar_matches_prior_source_and_geometry") is True
                    and row.get("actual_saved_geometry_and_all_members_match") is True for row in attached.get("prior_object_checks", [])),
            "adopted_targets_exact": set(attached.get("targets", [])) == set(current_adopted)
                and {row["stroke_id"] for row in plan["paths"]} == set(current_adopted) and len(plan["paths"]) == len(current_adopted),
            "plan_replay": attached.get("plan_replay", {}).get("pass") is True
                and bool(attached.get("plan_replay", {}).get("checks"))
                and all(value is True for value in attached["plan_replay"]["checks"].values()),
            "complete_path_replay": attached.get("complete_path_replay", {}).get("pass") is True
                and attached.get("complete_path_replay", {}).get("strict_or_outside_interval_changes") == []}
        checks["current_attached_execution_detail"] = all(stage_checks.values()) and _same(gate.get("current_attached_stage"), {
            "checks": stage_checks, "pass": True,
            "plan_sha256": published["evidence/attached_strokes/plan.json"],
            "adoption_sha256": published["evidence/attached_strokes/adoption.json"],
            "stage_execution": attached["stage_execution"], "adopted_object_ids": sorted(current_adopted),
            "candidate_failures_not_promoted": True})
        checks["current_stage_execution_same_actual_adoption"] = _same(attached.get("stage_execution"), adoption.get("stage_execution"))
        duplicates = gate["duplicate_review"]
        checks["current_duplicate_enumeration_and_failure_preservation"] = (
            _same(duplicates.get("all_repeated_segments"), fresh["all_repeated_segments"])
            and _same(direct.get("all_repeated_segments"), [row for row in fresh["all_repeated_segments"] if "duplicate_kind" not in row])
            and duplicates.get("unproved_or_cross_owner_duplicates") == []
            and duplicates.get("pass") is True and duplicates.get("historical_handles_reused_as_current_handles") is False)
        bound = duplicates.get("bound_allowances", [])
        expected_bound = _actual_retrace_bindings(paths["saved_dxf"], dxf_path, old_cold, upstream,
            source_path, request["parameters"]["roi"], request["parameters"]["dpi"])
        checks["actual_retrace_owner_segments_pixels_and_historical_witnesses"] = _same(bound, expected_bound)
        certificates = {(row.get("handle"), *row.get("segment_indices", [])): row for row in bound}
        certified = duplicates.get("certified_same_owner_retraces", [])
        checks["complete_same_owner_certificate_rows"] = (
            len(certificates) == len(bound) and len(certified) == len(fresh["all_repeated_segments"])
            and all(row.get("pass") is True and row.get("complete_current_native_path_exact") is True
                    and row.get("original_adjacent_ink_rechecked") is True and row.get("id") in upstream for row in bound)
            and all(row.get("objects", [None, False])[0] == row.get("objects", [None, False])[1]
                    and row.get("actual_handles", [None, False])[0] == row.get("actual_handles", [None, False])[1]
                    and row.get("expanded_member_indices") == [0, 0]
                    and _same(row.get("source_certificate"), certificates.get((row["actual_handles"][0], *sorted(row["segment_indices"]))))
                    for row in certified)
            and _same([{key: value for key, value in row.items() if key != "source_certificate"} for row in certified],
                      fresh["all_repeated_segments"]))
        gate_checks = gate.get("checks", {})
        checks["all_required_gate_checks_present_and_true"] = (
            set(gate_checks) == GATE_CHECKS and all(value is True for value in gate_checks.values()) and gate.get("pass") is True)
        effective = gate["effective_cold_audit"]
        expected_effective_rows = [{**row, "continued_source_proof": True, "historical_check_sha256": _digest(row)} for row in kept]
        expected_effective_rows += direct["checks"] + attached["checks"]
        checks["effective_view_exact_evidence_composition"] = (
            effective.get("schema") == "source-proof-continuation-effective-audit-v1"
            and effective.get("source_gate_mode") == MODE
            and effective.get("checkpoint_manifest_sha256") == saved.sha256(manifest_path)
            and effective.get("fresh_cold_audit_sha256") == fresh_sha
            and effective.get("complete_proof_gate_sha256") == _digest(core)
            and _same(effective.get("source_checks"), expected_effective_rows)
            and all(_same(effective.get(key), fresh.get(key)) for key in
                    ("dxf_sha256", "dxf_unchanged", "ezdxf_errors", "ezdxf_in_memory_fixes", "snapshot"))
            and effective.get("source_gate_pass") is True and effective.get("source_geometry_gate_pass") is True
            and effective.get("local_retrace_certificate_gate_pass") is True
            and effective.get("exact_duplicate_segments") == []
            and _same(effective.get("all_repeated_segments"), fresh["all_repeated_segments"])
            and _same(effective.get("certified_same_owner_retraces"), certified))
        after = {path: saved.sha256(path) for path in before}
        checks["actual_proof_inputs_unchanged_during_check"] = before == after
        result.update(status="PASS" if all(checks.values()) else "FAIL",
            input_sha256_before=before, input_sha256_after=after,
            fresh_legacy_source_gate_pass=fresh.get("source_gate_pass"),
            fresh_legacy_failed_source_check_count=gate["fresh_cold_audit"]["failed_source_check_count"],
            actual_gate_path=str(gate_path), actual_gate_sha256=gate_sha,
            actual_fresh_path=str(fresh_path), actual_fresh_sha256=fresh_sha,
            complete_upstream_object_count=len(upstream), reused_source_check_count=len(kept),
            current_direct_sample_check_count=len(raw_rows),
            mode=MODE, failed_checks=[key for key, value in checks.items() if not value])
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, saved.ezdxf.DXFError) as exc:
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        result["reason"] = "INVALID_SOURCE_PROOF_CONTINUATION_EVIDENCE"
    return result
