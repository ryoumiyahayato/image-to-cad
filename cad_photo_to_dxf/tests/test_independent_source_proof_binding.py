"""Synthetic receipt mutations for the explicit v2 provenance interface.

The fixtures declare a tiny historical/current proof pair. They are not an
actual ordinary conversion or original-image proof replay, and are never
delivered as one. Actual DXF bytes and recursive contents are used for binding.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import shutil
import subprocess
import sys

import ezdxf
import pytest
from PIL import Image

from app.native_objects.independent_saved_geometry_audit import entity_identity, sha256, snapshot_dxf
from app.native_objects.attached_stroke_numeric import contract_identity, joint_contract_identity
from app.native_objects.independent_source_proof_binding import (
    MODE, GATE_CHECKS, _digest, _inventory_digests, audit_source_proof_binding,
)
from app.native_objects.independent_stage_binding import digest, audit_stage_binding
from .test_independent_stage_binding import (
    _fixture, _checkpoint_fixture, _stage, _write, _publish, _numerical_fixture, REPO, COMMON,
)


def _record(path, root):
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}


def _v2_fixture(tmp_path):
    x = _fixture(tmp_path)
    x["plan"].update(numerical_contract=contract_identity(), joint_contract=joint_contract_identity())
    x["adoption"]["stage_execution"]["joint_contract"] = deepcopy(x["plan"]["joint_contract"])
    doc = ezdxf.readfile(x["dxf"])
    x["metadata"]["written"] = []
    for entity in doc.modelspace():
        identity = entity_identity(entity)
        if identity is not None:
            x["metadata"]["written"].append({"id": identity["id"], "kind": identity["kind"],
                "type": entity.dxftype(), "handle": entity.dxf.handle,
                "block_members": [member.dxftype() for member in doc.blocks[entity.dxf.name]] if entity.dxftype() == "INSERT" else []})
    x["metadata"].update(font={"file": "fixture-font.ttf", "source": "declared-fixture-source"},
        fonts=[{"file": "fixture-font.ttf", "source": "declared-fixture-source"}], repair_regions=[],
        native_schema="DECLARED_TEST_NATIVE_SCHEMA", serialization={"format": "declared-test"})
    # These byte fixtures are not real fonts or a font/render qualification.
    for name in ("fixture-font.ttf", "fixture-font.lff", "FONT_LICENSE_FIXTURE.txt"):
        (tmp_path / name).write_bytes(("Declared byte-binding fixture: " + name).encode())
    x["portable_resource_hashes"] = {name: sha256(tmp_path / name) for name in
        ("fixture-font.ttf", "fixture-font.lff", "FONT_LICENSE_FIXTURE.txt")}
    manifest_path, manifest, continuation_path, continuation, _ = _checkpoint_fixture(x, tmp_path)
    root = manifest_path.parent
    upstream = deepcopy(x["metadata"]["objects"])
    bindings = [{**{key: deepcopy(row[key]) for key in ("id", "kind", "layer", "geometry")},
                 "source_evidence": {key: None for key in ("source_path_points", "original_source_crop_xyxy_px",
                     "original_source_crop_array_sha256", "source_pixels_modified", "text_contact_path")}}
                for row in sorted(upstream, key=lambda row: row["id"])]
    x["plan"].update(prior_object_bindings=bindings, prior_object_bindings_sha256=digest(bindings))
    x["adoption"]["prior_object_bindings"] = deepcopy(bindings)
    x["adoption"]["plan"] = deepcopy(x["plan"])
    old_request = deepcopy(x["request"])
    old_request.pop("source_stage_checkpoint")
    for name, data in (("request", old_request), ("attached_plan", x["plan"]), ("attached_adoption", x["adoption"])):
        _write(root / "origin" / (name + ".json"), data)
    stored = root / "origin/saved_proof"
    stored.mkdir(parents=True)
    old_dxf, old_meta = stored / "result.dxf", stored / "result.objects.json"
    old_dxf.write_bytes(x["baseline"].read_bytes())
    old_metadata = deepcopy(x["metadata"])
    old_metadata["dxf_sha256"] = sha256(old_dxf)
    _write(old_meta, old_metadata)
    primitive = [{"id": row["id"], "member": 0, "type": "LINE", "max_distance_px": 0.,
        "source_fraction": 1., "maximum_gap_px": 0., "samples": 37, "pass": True} for row in upstream]
    old_stage_row = {"id": "OLD_ATTACHED_STAGE", "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": True}
    old_cold = {"dxf_sha256": sha256(old_dxf), "dxf_unchanged": True, "source_gate_pass": True,
        "ezdxf_errors": [], "ezdxf_in_memory_fixes": [], "exact_duplicate_segments": [],
        "source_checks": deepcopy(primitive) + [old_stage_row],
        "attached_stroke_source_checks": {"checks": [old_stage_row]},
        "same_owner_retrace_cold_proof": {"allowances": []}, "text_contact_source_checks": {"allowances": []}}
    attached_row = {"id": "CURRENT_ATTACHED_STAGE", "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": True}
    attached = {"stage_execution": deepcopy(x["adoption"]["stage_execution"]), "pass": True, "checks": [attached_row],
        "prior_object_checks": [{"id": row["id"], "pass": True, "sidecar_matches_prior_source_and_geometry": True,
            "actual_saved_geometry_and_all_members_match": True} for row in upstream], "targets": [],
        "plan_replay": {"pass": True, "saved_plan_sha256": digest(x["plan"]), "checks": {"schema": True}},
        "complete_path_replay": {"pass": True, "strict_or_outside_interval_changes": []}}
    fresh = {"dxf_sha256": sha256(x["dxf"]), "dxf_unchanged": True, "source_gate_pass": False,
        "ezdxf_errors": [], "ezdxf_in_memory_fixes": [], "source_checks": deepcopy(primitive) + [attached_row],
        "exact_duplicate_segments": [], "all_repeated_segments": [], "attached_stroke_source_checks": attached,
        "snapshot": {"declared_fixture_snapshot": True}, "formal_modelspace_types": {}, "expanded_formal_types": {},
        "texts": [], "room_block_definitions_are_unique": True}
    old_snapshot, current_snapshot = snapshot_dxf(old_dxf), snapshot_dxf(x["dxf"])
    object_checks = [{"id": row["id"], "complete_native_and_recursive_members_exact": True,
                     "source_payload_exact": True, "pass": True} for row in sorted(upstream, key=lambda row: row["id"])]
    contexts = {key: old_snapshot[key] == current_snapshot[key] for key in
        ("review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")}
    contexts.update({key: True for key in ("sidecar_portable_font_records", "sidecar_repair_regions",
                                          "sidecar_native_schema", "sidecar_serialization")})
    portable_resources = [{"path": name, "bytes": (tmp_path / name).stat().st_size, "sha256": expected, "pass": True}
                          for name, expected in sorted(x["portable_resource_hashes"].items())]
    written_checks = [{"id": row["id"], "actual_current_handle_and_members_bound": True,
                       "upstream_written_payload_exact": True, "pass": True} for row in sorted(upstream, key=lambda row: row["id"])]
    stage_checks = {"stage_executed": True, "complete_current_stage_audit": True, "every_current_stage_check": True,
        "complete_prior_bindings": True, "adopted_targets_exact": True, "plan_replay": True,
        "saved_current_plan_bound_to_fresh_replay": True, "current_producer_and_schema": True,
        "actual_adoption_stage_bound": True, "complete_path_replay": True}
    gate = {"schema": "source-proof-continuation-saved-audit-v1", "mode": MODE,
        "saved_content": {"object_checks": object_checks, "context_checks": contexts,
                          "portable_resource_checks": portable_resources, "written_receipt_checks": written_checks, "pass": True},
        "direct_source_checks": {"checks": [{**row, "segment": 0} for row in primitive], "all_repeated_segments": [],
                                 "source_distance_thresholds_changed": False, "pass": True},
        "duplicate_review": {"all_repeated_segments": [], "bound_allowances": [], "certified_same_owner_retraces": [],
            "unproved_or_cross_owner_duplicates": [], "historical_handles_reused_as_current_handles": False, "pass": True},
        "current_attached_stage": {"checks": stage_checks, "pass": True, "stage_execution": deepcopy(attached["stage_execution"]),
                                   "adopted_object_ids": [], "candidate_failures_not_promoted": True},
        "checks": {key: True for key in GATE_CHECKS}, "pass": True,
        "historical_DXF_read_for_proof_validation": True, "old_DXF_entities_used_to_construct_output": False,
        "old_attached_result_reused": False, "new_upstream_fits": 0, "new_OCR_calls": 0,
        "fresh_legacy_audit_rewritten": False, "uncached_recomputation_preservation_claimed": False}
    manifest.update(schema="source-stage-checkpoint-pre-attached-v2", excluded_historical_stage_object_ids=[],
        historical_DXF_read_for_proof_validation=True, old_DXF_entities_used_to_construct_output=False,
        source_proof_reviewer_sha256=sha256(REPO / "cad_photo_to_dxf/app/native_objects/source_proof_continuation.py"))
    manifest.pop("old_DXF_read")
    manifest["downstream_required"].append("saved_source_proof_continuation")
    continuation.update(schema="source-stage-continuation-execution-v2",
        historical_DXF_read_for_proof_validation=True, old_DXF_entities_used_to_construct_output=False)
    continuation.pop("old_DXF_read")
    x["request"]["source_stage_checkpoint"]["schema"] = "captured-source-stage-checkpoint-v2"
    x["request"]["algorithm"]["files"]["app/native_objects/source_proof_continuation.py"] = manifest["source_proof_reviewer_sha256"]
    x["request"]["algorithm"]["sha256"] = digest(x["request"]["algorithm"]["files"])
    x.update(manifest_path=manifest_path, manifest=manifest, continuation_path=continuation_path,
        continuation=continuation, old_request=old_request, old_cold=old_cold, old_dxf=old_dxf, old_meta=old_meta,
        fresh=fresh, gate=gate, primitive=primitive, upstream=upstream)
    _seal(x)
    return x


def _seal(x):
    """Rebind changed receipt bytes so negative tests exercise deeper gates."""
    root, manifest = x["manifest_path"].parent, x["manifest"]
    stored = root / "origin/saved_proof"
    old_cold_path = stored / "cold_audit.json"
    _write(old_cold_path, x["old_cold"])
    old_worker_path = stored / "publication_manifest.json"
    _write(old_worker_path, {"identity": {"source_sha256": x["old_request"]["source_sha256"],
        "algorithm_sha256": x["old_request"]["algorithm"]["sha256"]},
        "files": {name: {"sha256": sha256(path), "bytes": path.stat().st_size} for name, path in
                  (("result.dxf", x["old_dxf"]), ("result.objects.json", x["old_meta"]), ("evidence/cold_audit.json", old_cold_path))}})
    evidence_rows = [_record(path, root) for path in sorted((root / "evidence").rglob("*")) if path.is_file()]
    old_export_path = stored / "export.json"
    _write(old_export_path, {"source_sha256": x["old_request"]["source_sha256"], "algorithm": x["old_request"]["algorithm"],
        "DXF_sha256": sha256(x["old_dxf"]), "files": x["portable_resource_hashes"], "evidence_files": {
            **{row["path"]: row["sha256"] for row in evidence_rows}, "result.dxf": sha256(x["old_dxf"]),
            "result.objects.json": sha256(x["old_meta"]), "evidence/cold_audit.json": sha256(old_cold_path),
            "publication_manifest.json": sha256(old_worker_path)}})
    kept = x["old_cold"]["source_checks"][:-1]
    capsule = {"schema": "historical-complete-source-proof-capsule-v1", "artifacts": {
        key: _record(path, root) for key, path in (("saved_dxf", x["old_dxf"]), ("sidecar", x["old_meta"]),
            ("cold_audit", old_cold_path), ("export_manifest", old_export_path), ("publication_manifest", old_worker_path))},
        "source_sha256": x["request"]["source_sha256"], "parameters": x["request"]["parameters"],
        "upstream_state_sha256": manifest["upstream_state_sha256"], "historical_upstream_check_projection_sha256": _digest(kept),
        "historical_DXF_read_for_proof_validation": True, "old_DXF_entities_used_to_construct_output": False}
    manifest["historical_saved_proof"] = capsule
    manifest["artifacts"] = [_record(path, root) for path in sorted(root.rglob("*")) if path.is_file() and path != x["manifest_path"]]
    _write(x["manifest_path"], manifest)
    x["request"]["source_stage_checkpoint"]["manifest_sha256"] = sha256(x["manifest_path"])
    x["request"]["source_stage_checkpoint"]["downstream_required"] = manifest["downstream_required"]
    _publish(x)
    evidence = x["dxf"].with_suffix(".native") / "evidence"
    for row in evidence_rows:
        target = evidence / row["path"][len("evidence/"):]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / row["path"]).read_bytes())
    fresh_path = evidence / "cold_audit.json"
    x["fresh"]["dxf_sha256"] = sha256(x["dxf"])
    _write(fresh_path, x["fresh"])
    gate = x["gate"]
    gate.update(checkpoint_manifest_sha256=sha256(x["manifest_path"]), historical_saved_proof=capsule,
        fresh_cold_audit={"path": "cold_audit.json", "sha256": sha256(fresh_path), "source_gate_pass": x["fresh"]["source_gate_pass"],
            "failed_source_check_count": sum(row.get("pass") is not True for row in x["fresh"]["source_checks"]),
            "exact_duplicate_segment_count": len(x["fresh"]["exact_duplicate_segments"])},
        current_saved={"dxf_sha256": sha256(x["dxf"]), "sidecar_sha256": sha256(x["metadata_path"]),
            "source_sha256": x["request"]["source_sha256"], "roi": x["request"]["parameters"]["roi"], "dpi": x["request"]["parameters"]["dpi"]},
        upstream_proof_projection={"source_check_count": len(kept), "source_checks_sha256": _digest(kept),
            "covered_object_ids": sorted(row["id"] for row in x["upstream"]), "excluded_stage_object_ids": [],
            "excluded_check_count": 1, "all_upstream_checks_passed": True,
            "complete_check_type_counts": dict(Counter(row["type"] for row in kept)),
            "whole_historical_source_gate_boolean_used": False, "source_checks": kept},
        restored_evidence={"members": [{"path": row["path"][len("evidence/"):], "sha256": row["sha256"], "bytes": row["bytes"], "pass": True}
                                      for row in evidence_rows], "pass": True})
    gate["current_attached_stage"].update(plan_sha256=sha256(x["plan_path"]), adoption_sha256=sha256(x["adoption_path"]))
    normalized_direct = [{key: value for key, value in row.items() if key != "segment"} for row in gate["direct_source_checks"]["checks"]]
    gate["fresh_source_check_inventory"] = {"expected": _inventory_digests(
        [row for row in kept if row.get("type") not in {"LINE", "LWPOLYLINE", "ARC", "CIRCLE"}]
        + normalized_direct + x["fresh"]["attached_stroke_source_checks"]["checks"]),
        "actual": _inventory_digests(x["fresh"]["source_checks"]), "pass": True, "independent_primitive_rows_exact": True}
    gate.pop("effective_cold_audit", None)
    effective = {key: deepcopy(x["fresh"][key]) for key in ("dxf_sha256", "dxf_unchanged", "ezdxf_errors", "ezdxf_in_memory_fixes",
        "formal_modelspace_types", "expanded_formal_types", "texts", "room_block_definitions_are_unique", "snapshot")}
    effective.update(schema="source-proof-continuation-effective-audit-v1", source_gate_mode=MODE,
        checkpoint_manifest_sha256=gate["checkpoint_manifest_sha256"], fresh_cold_audit_sha256=sha256(fresh_path),
        complete_proof_gate_sha256=_digest(gate), source_checks=[{**row, "continued_source_proof": True,
            "historical_check_sha256": _digest(row)} for row in kept] + gate["direct_source_checks"]["checks"] + x["fresh"]["attached_stroke_source_checks"]["checks"],
        source_gate_pass=True, source_geometry_gate_pass=True, local_retrace_certificate_gate_pass=True,
        exact_duplicate_segments=[], all_repeated_segments=gate["duplicate_review"]["all_repeated_segments"],
        certified_same_owner_retraces=gate["duplicate_review"]["certified_same_owner_retraces"], source_distance_thresholds_changed=False)
    gate["effective_cold_audit"] = effective
    gate_path = evidence / "source_proof_continuation_audit.json"
    _write(gate_path, gate)
    continuation = x["continuation"]
    continuation["checkpoint_manifest_sha256"] = sha256(x["manifest_path"])
    for name in ("attached_ink", "all_prior_contacts", "joint_numerical_contract"):
        continuation["downstream"][name].update(plan_sha256=sha256(x["plan_path"]), adoption_sha256=sha256(x["adoption_path"]))
    continuation["downstream"]["native_save"]["dxf_sha256"] = sha256(x["dxf"])
    continuation["downstream"]["saved_source_cold_read"].update(source_gate_pass=x["fresh"]["source_gate_pass"], receipt_sha256=sha256(fresh_path))
    continuation["downstream"]["saved_source_proof_continuation"] = {"status": "EXECUTED", "mode": MODE,
        "receipt": "source_proof_continuation_audit.json", "receipt_sha256": sha256(gate_path),
        "fresh_source_gate_pass": x["fresh"]["source_gate_pass"], "pass": True}
    _write(x["continuation_path"], continuation)
    companion = evidence.parent
    _write(companion / "result.report.json", {"source_gate_mode": MODE, "source_proof_audit_sha256": sha256(gate_path)})
    _write(companion / "publication_manifest.json", {"identity": {"source_sha256": x["request"]["source_sha256"],
        "algorithm_sha256": x["request"]["algorithm"]["sha256"]},
        "gates": {"source_gate_mode": MODE, "source_proof_audit_sha256": sha256(gate_path)}})
    publication = json.loads(x["publication_path"].read_text())
    publication["evidence_files"].update({path.relative_to(companion).as_posix(): sha256(path)
        for path in companion.rglob("*") if path.is_file()})
    publication.update(source_gate_mode=MODE, source_proof_audit_sha256=sha256(gate_path))
    _write(x["publication_path"], publication)


def test_v2_binds_complete_proof_and_keeps_fresh_failure_separate(tmp_path):
    x = _v2_fixture(tmp_path)
    result = _stage(x)
    assert result["status"] == "PASS", json.dumps(result.get("source_stage_checkpoint_binding", result), indent=2)
    proof = result["source_stage_checkpoint_binding"]["source_proof_continuation_binding"]
    assert proof["status"] == "PASS"
    assert proof["fresh_legacy_source_gate_pass"] is False
    assert proof["historical_global_source_PASS_consumed"] is False
    assert proof["new_candidate_source_authorized"] is False


@pytest.mark.parametrize("mutation", ["unknown_check", "hard_pixels", "metadata_responsibility", "complete_member",
    "historical_failed_proof", "stage_not_run", "missing_stage_check", "bad_effective_mode", "wrong_capsule_schema",
    "unbound_allowance", "cross_owner_duplicate", "legacy_failure_rewritten", "false_saved_detail", "wrong_worker_mode",
    "portable_resource_bytes", "stale_written_handle", "wrong_written_members", "missing_written_row", "sidecar_font_record",
    "sidecar_serialization", "prior_detail_false", "numeric_contract_missing", "candidate_count_stale"])
def test_v2_deep_counterexamples_cannot_be_hidden_by_outer_pass(tmp_path, mutation):
    x = _v2_fixture(tmp_path)
    if mutation == "unknown_check":
        x["fresh"]["source_checks"].append({"id": "old", "type": "UNKNOWN_SOURCE_CHECK", "pass": False})
    elif mutation == "hard_pixels":
        x["fresh"]["source_checks"][0].update({"source_fraction": 0., "maximum_gap_px": 9., "pass": False})
        x["gate"]["direct_source_checks"]["checks"][0].update({"source_fraction": 0., "maximum_gap_px": 9., "pass": False})
    elif mutation == "metadata_responsibility":
        x["metadata"]["objects"][0]["source_evidence"] = {"responsibility_changed": True}
    elif mutation == "complete_member":
        doc = ezdxf.readfile(x["dxf"])
        doc.blocks["leaf"][0].dxf.end = (3.0000000000000004, 0, 0)
        doc.saveas(x["dxf"])
    elif mutation == "historical_failed_proof":
        x["old_cold"]["source_checks"][0]["pass"] = False
    elif mutation == "stage_not_run":
        x["fresh"]["attached_stroke_source_checks"]["stage_execution"]["status"] = "NOT_RUN"
    elif mutation == "missing_stage_check":
        x["fresh"]["attached_stroke_source_checks"]["checks"] = []
    elif mutation == "unbound_allowance":
        x["gate"]["duplicate_review"]["bound_allowances"] = [{"id": "old", "handle": "X", "segment_indices": [0, 1],
            "source_edge": [[0, 0], [1, 0]], "pass": True, "complete_current_native_path_exact": True, "original_adjacent_ink_rechecked": True}]
    elif mutation == "cross_owner_duplicate":
        row = {"objects": ["old", "old-block"], "actual_handles": ["A", "B"], "segment_indices": [0, 1], "expanded_member_indices": [0, 0]}
        x["fresh"]["all_repeated_segments"] = [row]
        x["gate"]["direct_source_checks"]["all_repeated_segments"] = [row]
        x["gate"]["duplicate_review"]["all_repeated_segments"] = [row]
    elif mutation == "legacy_failure_rewritten":
        x["gate"]["fresh_legacy_audit_rewritten"] = True
    elif mutation == "false_saved_detail":
        x["gate"]["saved_content"]["object_checks"][0]["pass"] = False
    elif mutation == "portable_resource_bytes":
        (tmp_path / "fixture-font.lff").write_bytes(b"changed resource")
    elif mutation == "stale_written_handle":
        x["metadata"]["written"][0]["handle"] = "STALE"
    elif mutation == "wrong_written_members":
        x["metadata"]["written"][1]["block_members"] = ["TEXT"]
    elif mutation == "missing_written_row":
        x["metadata"]["written"].pop()
    elif mutation == "sidecar_font_record":
        x["metadata"]["fonts"][0]["file"] = "substituted.ttf"
    elif mutation == "sidecar_serialization":
        x["metadata"]["serialization"]["format"] = "changed"
    elif mutation == "prior_detail_false":
        x["fresh"]["attached_stroke_source_checks"]["prior_object_checks"][0]["actual_saved_geometry_and_all_members_match"] = False
    elif mutation == "numeric_contract_missing":
        del x["plan"]["numerical_contract"]
    elif mutation == "candidate_count_stale":
        x["fresh"]["attached_stroke_source_checks"]["stage_execution"]["candidate_path_count"] = 0
    _seal(x)
    if mutation in ("bad_effective_mode", "wrong_capsule_schema", "wrong_worker_mode"):
        # Keep publication hashes current while changing the selected contract.
        companion = x["dxf"].with_suffix(".native")
        path = companion / ("publication_manifest.json" if mutation == "wrong_worker_mode" else "evidence/source_proof_continuation_audit.json")
        value = json.loads(path.read_text())
        if mutation == "bad_effective_mode":
            value["effective_cold_audit"]["source_gate_mode"] = "FRESH"
        elif mutation == "wrong_capsule_schema":
            value["historical_saved_proof"]["schema"] = "UNKNOWN"
        else:
            value["gates"]["source_gate_mode"] = "FRESH"
        _write(path, value)
        publication = json.loads(x["publication_path"].read_text())
        publication["evidence_files"][path.relative_to(companion).as_posix()] = sha256(path)
        _write(x["publication_path"], publication)
    result = _stage(x)
    assert result["status"] == "FAIL", mutation


@pytest.mark.parametrize("mutation", [None, "pass_only", "missing_replay_field", "nested_failed_check", "empty_stage_checks"])
def test_historical_complete_proof_body_is_required_beyond_global_pass(tmp_path, mutation):
    x = _v2_fixture(tmp_path)
    row = {"id": "old", "type": "SAVED_CARRIER_SOURCE_AND_RETIREMENT", "pass": True,
        "checks": {"declared_fixture_relationship": True}, "errors": [], "actual_same_source_residues": [],
        "source_replay": {"pass": True, "checks": {"declared_fixture_source": True}, "replacement_ids": ["old"], "retired_ids": []}}
    if mutation == "pass_only":
        row["source_replay"] = {"pass": True}
    elif mutation == "missing_replay_field":
        del row["source_replay"]["replacement_ids"]
    elif mutation == "nested_failed_check":
        row["source_replay"]["checks"]["declared_fixture_source"] = False
    elif mutation == "empty_stage_checks":
        row["stage_context_checks"] = {}
    x["old_cold"]["source_checks"].insert(-1, row)
    x["fresh"]["source_checks"].insert(-1, {"id": "old", "type": row["type"], "pass": False,
                                         "reason": "declared legacy replay failure retained"})
    _seal(x)
    result = _stage(x)
    assert result["status"] == ("PASS" if mutation is None else "FAIL"), json.dumps(result, indent=2)


def test_portable_font_provenance_path_can_relocate_without_changing_font_identity(tmp_path):
    x = _v2_fixture(tmp_path)
    x["metadata"]["font"]["source"] = "relocated-same-bytes"
    x["metadata"]["fonts"][0]["source"] = "relocated-same-bytes"
    _seal(x)
    assert _stage(x)["status"] == "PASS"


def test_v1_capture_cannot_select_v2_gate(tmp_path):
    x = _v2_fixture(tmp_path)
    x["request"]["source_stage_checkpoint"]["schema"] = "captured-source-stage-checkpoint-v1"
    _write(x["request_path"], x["request"])
    result = _stage(x)
    assert result["status"] == "FAIL"
    assert result["source_stage_checkpoint_binding"]["checks"]["v1_cannot_select_source_proof_gate"] is False


@pytest.mark.parametrize("selection", ["orientation", "page_number", "frame_number", "multiframe"])
def test_independent_proof_rejects_unimplemented_raster_selection_explicitly(tmp_path, selection):
    x = _v2_fixture(tmp_path)
    if selection == "multiframe":
        with Image.open(x["source"]) as original:
            first = original.convert("L")
        first.save(x["source"], save_all=True, append_images=[Image.new("L", first.size, 0)])
    else:
        x["request"]["parameters"][selection] = 90 if selection == "orientation" else 1
    result = audit_source_proof_binding(dxf_path=x["dxf"], metadata_path=x["metadata_path"], source_path=x["source"],
        manifest_path=x["manifest_path"], manifest=x["manifest"], continuation=x["continuation"],
        publication=json.loads(x["publication_path"].read_text()), request=x["request"],
        source_root=REPO / "cad_photo_to_dxf", plan=x["plan"], adoption=x["adoption"])
    assert result["status"] == "FAIL"
    assert result["errors"][0]["message"].startswith("UNSUPPORTED_INDEPENDENT_PROOF_")


@pytest.mark.parametrize("tamper", [False, True])
def test_v2_manifest_relocation_keeps_exact_captured_identity(tmp_path, tamper):
    x = _v2_fixture(tmp_path)
    moved = tmp_path / "relocated"
    shutil.copytree(x["manifest_path"].parent, moved)
    x["manifest_path"].parent.rename(tmp_path / "original-unavailable")
    manifest = moved / "manifest.json"
    if tamper:
        manifest.write_text(manifest.read_text() + " ", encoding="utf-8")
    result = audit_stage_binding(dxf_path=x["dxf"], metadata_path=x["metadata_path"], source_path=x["source"],
        roi=[0, 0, 64, 64], dpi=25.4, execution_request_path=x["request_path"], source_stage_manifest_path=manifest)
    assert result["status"] == ("FAIL" if tamper else "PASS")


def test_common_v2_reports_preservation_and_retained_fresh_failure_separately(tmp_path):
    x = _v2_fixture(tmp_path)
    _, _, _, numerical_path, _ = _numerical_fixture(x, tmp_path)
    out = tmp_path / "common-v2"
    command = [sys.executable, str(COMMON), "--source", str(x["source"]), "--baseline", str(x["baseline"]),
        "--dxf", str(x["dxf"]), "--metadata", str(x["metadata_path"]), "--source-roi", "0", "0", "64", "64",
        "--audit-roi", "0", "0", "64", "64", "--dpi", "25.4", "--execution-request", str(x["request_path"]),
        "--numerical-replay-receipt", str(numerical_path), "--out", str(out)]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads((out / "COMMON_ACCEPTANCE.json").read_text())
    assert result["status"] == "PASS_ZERO_ADOPTED_PRESERVED_BASELINE"
    continued = result["upstream_source_proof_continuation"]
    assert continued["binding_status"] == "PASS" and continued["mode"] == MODE
    assert continued["fresh_legacy_source_replay"]["status"] == "FAIL_RETAINED"
    assert result["candidate_source_responsibility"]["status"] == "SOURCE_UNRESOLVED"
    assert result["original_pixel_source_responsibility"]["status"] == "NOT_APPLICABLE_ZERO_ADOPTED"
