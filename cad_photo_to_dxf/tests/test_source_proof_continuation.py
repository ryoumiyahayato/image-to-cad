"""Saved-proof continuation boundaries using actual tiny DXF/source files.

These fixtures isolate the saved proof seam. They do not claim to be an OCR
conversion. Full source-checkpoint code/dependency integrity has separate tests.
"""
import hashlib
import json
import shutil
from types import SimpleNamespace

import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects import attached_stroke_graph as graph
from app.native_objects import source_stage_checkpoint as checkpoint
from app.native_objects import source_proof_continuation as proof
from app.native_objects.contracts import save_json
from app.native_objects.execution import file_sha, read_json
from app.native_objects.independent_saved_geometry_audit import APPID, _index, _snapshot_doc


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, value)
    return path


def _record(path, root):
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": file_sha(path)}


def _mark(entity, oid, kind):
    entity.set_xdata(APPID, [(1000, json.dumps({"id": oid, "kind": kind}))])


@pytest.fixture
def packet(tmp_path, monkeypatch):
    roi, dpi = [0, 0, 24, 24], 200
    gray = np.full((24, 24), 255, dtype=np.uint8)
    gray[10, 2:16] = 0
    source = tmp_path / "source.png"
    Image.fromarray(gray).save(source)
    old = tmp_path / "historical.native"
    evidence = old / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "raw.tsv").write_bytes(b"original independent observation\n")
    doc = ezdxf.new("R2010")
    doc.appids.new(APPID)
    mm = 25.4 / dpi
    line = doc.modelspace().add_line((2 * mm, 14 * mm), (15 * mm, 14 * mm))
    _mark(line, "old-line", "LINE")
    doc.saveas(old / "result.dxf")
    doc = ezdxf.readfile(old / "result.dxf")
    line = _index(doc)[0]["old-line"]
    obj = {"id": "old-line", "kind": "LINE", "layer": "0", "geometry": {"start": [2, 10], "end": [15, 10]},
           "source_evidence": {"source_path_points": [[2, 10], [15, 10]]}}
    state = {"objects": [obj]}
    font_bytes = b"synthetic non-text fixture resource bytes\n"
    font = {"font": "fixture.ttf", "sha256": hashlib.sha256(font_bytes).hexdigest(), "source": "historical/source/font"}
    (old / "fixture.ttf").write_bytes(font_bytes)
    meta = {"dxf_sha256": file_sha(old / "result.dxf"), "source_sha256": file_sha(source), "roi_xyxy_px": roi,
            "dpi": dpi, "unit": "paper_mm", "objects": [obj], "font": font, "fonts": [font],
            "repair_regions": [], "native_schema": "tiny-saved-proof-test", "serialization": {},
            "written": [{"id": "old-line", "kind": "LINE", "type": "LINE", "handle": line.dxf.handle, "block_members": []}]}
    _write(old / "result.objects.json", meta)
    direct = proof.sample_current_geometry(doc, gray, roi, dpi)
    primitive = [{k: v for k, v in row.items() if k != "segment"} for row in direct["checks"]]
    old_stage = {"id": "old-stage", "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": True}
    old_cold = {"dxf_sha256": file_sha(old / "result.dxf"), "dxf_unchanged": True,
                "source_gate_pass": True, "ezdxf_errors": [], "ezdxf_in_memory_fixes": [],
                "source_checks": primitive + [old_stage], "exact_duplicate_segments": [],
                "attached_stroke_source_checks": {"checks": [old_stage]},
                "same_owner_retrace_cold_proof": {"allowances": []}, "text_contact_source_checks": {"allowances": []}}
    _write(evidence / "cold_audit.json", old_cold)
    parameters = {"roi": roi, "dpi": dpi, "orientation": 0, "page_number": None, "frame_number": None}
    request = {"source_sha256": file_sha(source), "algorithm": {"sha256": "synthetic-old-algorithm", "files": {}}, "parameters": parameters}
    publication = {"identity": {"source_sha256": file_sha(source), "algorithm_sha256": request["algorithm"]["sha256"]},
                   "files": {name: {"sha256": file_sha(old / name)} for name in ("result.dxf", "result.objects.json", "evidence/cold_audit.json")}}
    _write(old / "publication_manifest.json", publication)
    export = {"source_sha256": file_sha(source), "algorithm": request["algorithm"], "DXF_sha256": meta["dxf_sha256"],
              "files": {"fixture.ttf": file_sha(old / "fixture.ttf")},
              "evidence_files": {p.relative_to(old).as_posix(): file_sha(p) for p in old.rglob("*") if p.is_file()}}
    export_path = _write(old / "historical.export.json", export)
    root = tmp_path / "source-checkpoint"
    root.mkdir()
    _write(root / "origin/request.json", request)
    _write(root / "upstream_state.json", state)
    capsule = proof.create_historical_capsule(evidence, request, state, [], root, export_path)
    (root / "evidence").mkdir()
    shutil.copyfile(evidence / "raw.tsv", root / "evidence/raw.tsv")
    manifest = {"schema": checkpoint.SCHEMA, "historical_saved_proof": capsule,
                "source": {"source_sha256": file_sha(source), "working_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                           "working_roi_xyxy_px": roi, "parameters": parameters},
                "artifacts": [_record(root / "evidence/raw.tsv", root)], "excluded_historical_stage_object_ids": []}
    _write(root / "manifest.json", manifest)
    binding = {"schema": checkpoint.CAPTURE_SCHEMA, "manifest_path": str(root / "manifest.json"),
               "manifest_sha256": file_sha(root / "manifest.json"), "parameters": parameters}
    # Integrity of the complete production checkpoint is exercised in its own
    # packet tests; this seam has real source pixels, old/current DXFs and proof.
    def checked(path, **kwargs):
        assert file_sha(path) == kwargs["expected_sha256"]
        assert kwargs["parameters"] == parameters
        return manifest
    monkeypatch.setattr(checkpoint, "verify_checkpoint", checked)
    staging = tmp_path / "attempt/staging"
    (staging / "evidence/attached_strokes").mkdir(parents=True)
    for name in ("result.dxf", "result.objects.json", "fixture.ttf"):
        shutil.copyfile(old / name, staging / name)
    shutil.copyfile(evidence / "raw.tsv", staging / "evidence/raw.tsv")
    additional = {"attached_stroke_ink.py": graph.attached_ink.producer_sha256(),
                  "attached_stroke_contacts.py": graph.prior_contacts.producer_sha256(),
                  "attached_stroke_numeric.py": graph.numerical.contract_identity()["module_sha256"]}
    prior = [graph.object_binding(obj)]
    plan = {"schema": graph.SCHEMA, "producer_sha256": file_sha(graph.__file__),
            "additional_producer_sha256": additional, "joint_contract": graph.numerical.joint_contract_identity(),
            "numerical_contract": graph.numerical.contract_identity(), "roi_xyxy_px": roi,
            "prior_object_bindings": prior, "paths": [], "components": []}
    stage = {"stage": "complete_attached_strokes", "status": "EXECUTED", "source_graph_input": "REBUILT_FROM_ORIGINAL",
             "adopted_path_count": 0, "candidate_path_count": 0, "producer_sha256": plan["producer_sha256"],
             "additional_producer_sha256": additional, "joint_contract": plan["joint_contract"]}
    adoption = {"schema": "source-attached-stroke-joint-adoption-v3", "plan": plan, "objects": [], "retired_ids": [],
                "source_sha256": file_sha(source), "roi_xyxy_px": roi, "stage_execution": stage, "prior_object_bindings": prior}
    _write(staging / "evidence/attached_strokes/plan.json", plan)
    _write(staging / "evidence/attached_strokes/adoption.json", adoption)
    stage_row = {"id": "current-stage", "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": True}
    attached = {"stage_execution": stage, "pass": True, "checks": [stage_row], "targets": [],
                "prior_object_checks": [{"id": obj["id"], "pass": True, "sidecar_matches_prior_source_and_geometry": True,
                                         "actual_saved_geometry_and_all_members_match": True}],
                "plan_replay": {"saved_plan_sha256": graph._digest(plan), "pass": True, "checks": {"schema": True}},
                "complete_path_replay": {"pass": True, "strict_or_outside_interval_changes": []}}
    fresh = {"dxf_sha256": meta["dxf_sha256"], "dxf_unchanged": True, "ezdxf_errors": [], "ezdxf_in_memory_fixes": [],
             "source_gate_pass": False, "source_checks": primitive + [stage_row], "exact_duplicate_segments": [],
             "all_repeated_segments": [], "attached_stroke_source_checks": attached,
             "formal_modelspace_types": {"LINE": 1}, "expanded_formal_types": {"LINE": 1}, "texts": [],
             "room_block_definitions_are_unique": True, "snapshot": _snapshot_doc(doc)}
    _write(staging / "evidence/cold_audit.json", fresh)
    return SimpleNamespace(root=root, manifest=manifest, binding=binding, state=state, staging=staging,
                           source=source, gray=gray, roi=roi, dpi=dpi)


def _review(x, path=None):
    return proof.audit_source_proof_continuation(path or x.staging / "result.dxf", x.gray, x.roi, x.dpi,
                                               x.staging / "evidence", x.binding, x.source)


def test_complete_proof_is_independent_of_historical_global_boolean_and_retains_fresh_fail(packet):
    original_fresh = (packet.staging / "evidence/cold_audit.json").read_bytes()
    report = _review(packet)
    assert report["pass"] and all(report["checks"].values())
    assert report["fresh_cold_audit"]["source_gate_pass"] is False
    assert report["upstream_proof_projection"]["whole_historical_source_gate_boolean_used"] is False
    assert (packet.staging / "evidence/cold_audit.json").read_bytes() == original_fresh
    assert report["current_attached_stage"]["adopted_object_ids"] == []
    assert report["current_attached_stage"]["candidate_failures_not_promoted"] is True


def test_gate_replays_after_staging_publication_and_changed_dxf_basename(packet, monkeypatch):
    from app.core.native_worker import _saved_candidate_gates
    from app.native_objects import review_binding
    _review(packet)
    _write(packet.staging / "evidence/import_manifest.json", {"synthetic": True})
    _write(packet.staging / "evidence/quality_review.json", {"summary": {
        "safe_artifact_structure": True, "source_geometry_gate_pass": True}})
    monkeypatch.setattr(review_binding, "verify_saved_review", lambda *a, **k: {"valid": True})
    request = {"input_path": str(packet.source), "source_stage_checkpoint": packet.binding}
    assert _saved_candidate_gates(packet.staging, request)["source_gate_mode"] == proof.MODE
    published = packet.staging.parent.parent / "results/0001"
    published.parent.mkdir()
    packet.staging.rename(published)
    assert _saved_candidate_gates(published, request)["source_gate_mode"] == proof.MODE
    renamed = published / "reviewed-drawing.dxf"
    (published / "result.dxf").rename(renamed)
    (published / "result.objects.json").rename(renamed.with_suffix(".objects.json"))
    assert proof.verify_saved_continuation_gate(renamed, published / "evidence", packet.binding, packet.source)["pass"]
    saved = read_json(published / "evidence" / proof.AUDIT_NAME)
    saved["direct_source_checks"]["checks"][0]["pass"] = False
    _write(published / "evidence" / proof.AUDIT_NAME, saved)
    with pytest.raises(ValueError, match="SAVED_CONTINUATION_GATE_DOES_NOT_REPLAY"):
        proof.verify_saved_continuation_gate(renamed, published / "evidence", packet.binding, packet.source)


@pytest.mark.parametrize("damage,expected", [
    ("raw", "SOURCE_STAGE_ARTIFACT_CHANGED"), ("font", "CURRENT_PORTABLE_RESOURCE_BYTES_CHANGED"),
    ("written_handle", "CURRENT_RECURSIVE_NATIVE_CONTENT_OR_RESOURCES_CHANGED"),
    ("geometry", "CURRENT_RECURSIVE_NATIVE_CONTENT_OR_RESOURCES_CHANGED"),
    ("unknown_fresh_check", "CURRENT_FRESH_SOURCE_RESPONSIBILITY_INVENTORY_CHANGED"),
    ("primitive_failure", "CURRENT_DIRECT_SAMPLES_DIFFER_FROM_COMPLETE_FRESH_COLD"),
    ("not_run", "CURRENT_ATTACHED_SOURCE_CONTACT_OR_NUMERICAL_STAGE_FAILED"),
    ("empty_plan_checks", "CURRENT_ATTACHED_SOURCE_CONTACT_OR_NUMERICAL_STAGE_FAILED"),
    ("prior_inner_failure", "CURRENT_ATTACHED_SOURCE_CONTACT_OR_NUMERICAL_STAGE_FAILED"),
    ("v1_capture", "EXPLICIT_CAPTURED_V2_SOURCE_CHECKPOINT_REQUIRED"),
])
def test_rejects_changed_actual_sources_resources_responsibilities_and_inner_proof(packet, damage, expected):
    fresh_path = packet.staging / "evidence/cold_audit.json"
    fresh = read_json(fresh_path)
    if damage == "raw":
        (packet.staging / "evidence/raw.tsv").write_bytes(b"changed observation")
    elif damage == "font":
        (packet.staging / "fixture.ttf").write_bytes(b"same filename different font")
    elif damage in {"geometry", "written_handle"}:
        path = packet.staging / "result.dxf"
        meta = read_json(path.with_suffix(".objects.json"))
        if damage == "geometry":
            doc = ezdxf.readfile(path)
            line = _index(doc)[0]["old-line"]
            line.dxf.end = (line.dxf.end.x + 1e-9, line.dxf.end.y, 0)
            doc.saveas(path)
            meta["dxf_sha256"] = fresh["dxf_sha256"] = file_sha(path)
        else:
            meta["written"][0]["handle"] = "NOT_THE_ACTUAL_HANDLE"
        _write(path.with_suffix(".objects.json"), meta)
    elif damage == "unknown_fresh_check":
        fresh["source_checks"].append({"id": "old-line", "type": "UNKNOWN_HARD_FAILURE", "pass": False})
    elif damage == "primitive_failure":
        fresh["source_checks"][0]["pass"] = False
    elif damage == "not_run":
        fresh["attached_stroke_source_checks"]["stage_execution"]["status"] = "NOT_RUN"
    elif damage == "empty_plan_checks":
        fresh["attached_stroke_source_checks"]["plan_replay"]["checks"] = {}
    elif damage == "prior_inner_failure":
        fresh["attached_stroke_source_checks"]["prior_object_checks"][0]["actual_saved_geometry_and_all_members_match"] = False
    elif damage == "v1_capture":
        packet.binding["schema"] = "captured-source-stage-checkpoint-v1"
    _write(fresh_path, fresh)
    with pytest.raises(ValueError, match=expected):
        _review(packet)


def test_additional_producer_change_cannot_be_hidden_by_rehashing_current_plan(packet):
    folder = packet.staging / "evidence/attached_strokes"
    plan, adoption = read_json(folder / "plan.json"), read_json(folder / "adoption.json")
    plan["additional_producer_sha256"]["attached_stroke_numeric.py"] = "different bytes"
    adoption["plan"] = plan
    adoption["stage_execution"]["additional_producer_sha256"] = plan["additional_producer_sha256"]
    fresh = read_json(packet.staging / "evidence/cold_audit.json")
    fresh["attached_stroke_source_checks"]["plan_replay"]["saved_plan_sha256"] = graph._digest(plan)
    fresh["attached_stroke_source_checks"]["stage_execution"] = adoption["stage_execution"]
    _write(folder / "plan.json", plan)
    _write(folder / "adoption.json", adoption)
    _write(packet.staging / "evidence/cold_audit.json", fresh)
    with pytest.raises(ValueError, match="CURRENT_ATTACHED_SOURCE_CONTACT_OR_NUMERICAL_STAGE_FAILED"):
        _review(packet)


@pytest.mark.parametrize("inner", [{}, {"pass": True}, {"pass": False, "proof": "present"}])
def test_historical_outer_pass_does_not_accept_empty_or_failed_inner_proof(inner):
    row = {"id": "circle", "type": "CIRCULAR_SOURCE_BINDING", "pass": True,
           "saved_candidate_checks": {"exact_ring": True}, "ring_source": inner}
    with pytest.raises(ValueError, match="HISTORICAL_UPSTREAM_CHECK_DETAIL_FAILED"):
        proof._validate_historical_check(row)


def test_historical_projection_excludes_only_complete_declared_stage_multiset():
    primitive = {"id": "prior", "type": "LINE", "member": 0, "max_distance_px": 0.,
                 "source_fraction": 1., "maximum_gap_px": 0., "samples": 2, "pass": True}
    attached = {"id": "stage", "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": True}
    cold = {"source_checks": [primitive, attached], "attached_stroke_source_checks": {"checks": [attached]}}
    assert proof.project_historical_checks(cold, [])[0] == [primitive]
    cold["source_checks"].append({"id": "removed", "type": "UNKNOWN_PROOF", "pass": True})
    with pytest.raises(ValueError, match="UNPROJECTABLE_PROOF"):
        proof.project_historical_checks(cold, ["removed"])
    cold["source_checks"].pop()
    cold["attached_stroke_source_checks"]["checks"].append(attached)
    with pytest.raises(ValueError, match="NOT_IN_COMPLETE_COLD_PROOF"):
        proof.project_historical_checks(cold, [])


def test_current_geometry_is_sampled_from_original_pixels(packet):
    doc = ezdxf.readfile(packet.staging / "result.dxf")
    assert proof.sample_current_geometry(doc, packet.gray, packet.roi, packet.dpi)["pass"]
    assert not proof.sample_current_geometry(doc, np.full_like(packet.gray, 255), packet.roi, packet.dpi)["pass"]


@pytest.mark.parametrize("damage", [None, "cross_owner", "source_edge", "finite_segment"])
def test_same_owner_allowance_rebinds_actual_handle_and_complete_finite_source_edge(damage):
    gray = np.full((8, 8), 255, dtype=np.uint8)
    gray[3, 2:4] = 0
    roi, dpi = [0, 0, 8, 8], 25.4
    old, current = ezdxf.new(), ezdxf.new()
    for doc in (old, current):
        doc.appids.new(APPID)
    current.modelspace().add_point((99, 99), dxfattribs={"layer": "REVIEW"})
    oldline = old.modelspace().add_lwpolyline([(2, 5), (3, 5), (2, 5)])
    line = current.modelspace().add_lwpolyline([(2, 5), (3, 5), (2, 5)])
    _mark(oldline, "retraced", "LWPOLYLINE")
    _mark(line, "retraced", "LWPOLYLINE")
    assert oldline.dxf.handle != line.dxf.handle
    allowance = {"id": "retraced", "handle": oldline.dxf.handle, "segment_indices": [0, 1], "source_edge": [[2, 3], [3, 3]]}
    cold = {"same_owner_retrace_cold_proof": {"allowances": [allowance]}, "text_contact_source_checks": {"allowances": []}}
    repeated = proof.sample_current_geometry(current, gray, roi, dpi)["all_repeated_segments"]
    objects = {"retraced": {"source_evidence": {"source_path_points": [[2, 3], [3, 3], [2, 3]]}}}
    if damage == "cross_owner":
        repeated[0]["objects"][1] = "some-other-owner"
    elif damage == "source_edge":
        allowance["source_edge"][1] = [4, 3]
    elif damage == "finite_segment":
        line.set_points([(2, 5), (3, 5), (2, 5.000000000001)])
    if damage in {"source_edge", "finite_segment"}:
        with pytest.raises(ValueError, match="RETRACE_"):
            proof.rebind_retrace_allowances(old, current, cold, objects, set(objects), repeated, gray, roi, dpi)
    else:
        result = proof.rebind_retrace_allowances(old, current, cold, objects, set(objects), repeated, gray, roi, dpi)
        assert result["pass"] is (damage is None)
        if damage is None:
            assert result["bound_allowances"][0]["handle"] == line.dxf.handle
            assert len(result["certified_same_owner_retraces"]) == 1
