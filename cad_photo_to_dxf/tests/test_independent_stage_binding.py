"""Actual saved-file counterexamples for joint stage scope and failure receipts."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import ezdxf
from PIL import Image
import pytest

from app.native_objects.independent_saved_geometry_audit import (
    APPID, check_target_binding, compare_saved_dxf, entity_identity, sha256,
)
from app.native_objects.independent_stage_binding import (
    JOINT_ADOPTION, JOINT_CONTRACT, JOINT_NATIVE, JOINT_PLAN, audit_stage_binding, digest,
)

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "experiments/issue60_common_acceptance/run_saved_audit.py"
COMMON = ENTRY.with_name("run_common_acceptance.py")


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _identity(entity, oid, kind):
    entity.set_xdata(APPID, [(1000, json.dumps({"id": oid, "kind": kind}))])


def _fixture(tmp_path, *, candidate=True):
    source = tmp_path / "source.tiff"
    image = Image.new("L", (64, 64), 255)
    for x in range(8, 48):
        image.putpixel((x, 32), 0)
    image.save(source)
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    doc.layers.new("NATIVE")
    doc.layers.new("REVIEW")
    _identity(doc.modelspace().add_line((1, 1), (10, 1), dxfattribs={"layer": "NATIVE"}), "old", "LINE")
    leaf = doc.blocks.new("leaf")
    leaf.add_line((0, 0), (3, 0))
    parent = doc.blocks.new("parent")
    parent.add_blockref("leaf", (1, 1))
    _identity(doc.modelspace().add_blockref("parent", (20, 20)), "old-block", "BLOCK")
    doc.modelspace().add_line((50, 50), (60, 50), dxfattribs={"layer": "REVIEW"})
    baseline, dxf = tmp_path / "baseline.dxf", tmp_path / "current.dxf"
    doc.saveas(baseline)
    doc.saveas(dxf)
    objects = [{"id": "old", "kind": "LINE", "layer": "NATIVE",
                "geometry": {"start": [1., 63.], "end": [10., 63.]}},
               {"id": "old-block", "kind": "BLOCK", "layer": "0", "geometry": {}}]
    prior = deepcopy(objects)
    producer_dir = REPO / "cad_photo_to_dxf/app/native_objects"
    producer_map = {name: sha256(producer_dir / name) for name in (
        "attached_stroke_graph.py", "attached_stroke_ink.py", "attached_stroke_contacts.py", "attached_stroke_numeric.py")}
    plan = {"schema": JOINT_PLAN, "joint_contract": {"version": JOINT_CONTRACT},
        "producer_sha256": producer_map.pop("attached_stroke_graph.py"),
        "additional_producer_sha256": producer_map, "roi_xyxy_px": [0, 0, 64, 64],
        "original_source_crop_xyxy_px": [0, 0, 64, 64],
        "original_source_crop_array_sha256": __import__("hashlib").sha256(image.tobytes()).hexdigest(),
        "prior_object_bindings": prior, "prior_object_bindings_sha256": digest(prior),
        "paths": [], "components": [], "pending": [],
        "source_pixels_modified": False, "original_source_pixels_modified": False}
    if candidate:
        plan["components"] = [{"component_id": "pending-component", "status": "PENDING",
            "candidate_paths": [{"stroke_id": "candidate", "representation": {
                "points": [[8., 32.], [47., 32.]], "bulges": [0., 0.], "closed": False}}],
            "failed_adoption_gates": ["source_responsibility"], "reason": "SOURCE_UNRESOLVED"}]
    adoption = {"schema": JOINT_ADOPTION, "source_sha256": sha256(source),
        "roi_xyxy_px": plan["roi_xyxy_px"], "plan": deepcopy(plan), "objects": [],
        "prior_object_bindings": prior, "decisions": [], "retired_ids": [],
        "stage_execution": {"stage": "complete_attached_strokes", "status": "EXECUTED",
            "source_graph_input": "REBUILT_FROM_ORIGINAL", "adopted_path_count": 0,
            "candidate_path_count": int(candidate), "producer_sha256": plan["producer_sha256"],
            "additional_producer_sha256": producer_map, "joint_contract": plan["joint_contract"]}}
    metadata = {"source_sha256": sha256(source), "dxf_sha256": sha256(dxf), "objects": objects,
        "written": [{"id": row["id"]} for row in objects], "roi_xyxy_px": [0, 0, 64, 64],
        "dpi": 25.4, "unit": "paper_mm"}
    algorithm_files = {"app/native_objects/attached_stroke_graph.py": plan["producer_sha256"],
                       **{"app/native_objects/" + k: v for k, v in producer_map.items()}}
    request = {"source_sha256": sha256(source), "parameters": {"roi": [0, 0, 64, 64], "dpi": 25.4, "orientation": 0},
        "algorithm": {"files": algorithm_files, "sha256": digest(algorithm_files), "git": {"available": False}}}
    payload = {"source": source, "baseline": baseline, "dxf": dxf,
        "metadata_path": dxf.with_suffix(".objects.json"),
        "plan_path": dxf.with_suffix(".native") / "evidence/attached_strokes/plan.json",
        "adoption_path": dxf.with_suffix(".native") / "evidence/attached_strokes/adoption.json",
        "request_path": tmp_path / "request.json", "publication_path": dxf.with_suffix(".export.json"),
        "plan": plan, "adoption": adoption, "metadata": metadata, "request": request}
    _publish(payload)
    return payload


def _publish(x):
    x["adoption"]["plan"] = deepcopy(x["plan"])
    x["metadata"]["dxf_sha256"] = sha256(x["dxf"])
    for key in ("plan", "adoption", "metadata", "request"):
        _write(x[key + "_path"], x[key])
    _write(x["publication_path"], {"job_id": "synthetic-test", "source_sha256": sha256(x["source"]),
        "DXF_sha256": sha256(x["dxf"]), "algorithm": x["request"]["algorithm"],
        "files": {x["metadata_path"].name: sha256(x["metadata_path"])},
        "evidence_files": {"evidence/attached_strokes/plan.json": sha256(x["plan_path"]),
                           "evidence/attached_strokes/adoption.json": sha256(x["adoption_path"])}})


def _stage(x):
    return audit_stage_binding(dxf_path=x["dxf"], metadata_path=x["metadata_path"],
        source_path=x["source"], roi=[0, 0, 64, 64], dpi=25.4,
        execution_request_path=x["request_path"])


def _saved(x, out):
    spec = importlib.util.spec_from_file_location("saved_audit_entry", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out.mkdir()
    args = SimpleNamespace(baseline=x["baseline"], dxf=x["dxf"], metadata=x["metadata_path"],
        source=x["source"], roi=[0, 0, 64, 64], dpi=25.4, output_dir=out,
        stage_plan=None, stage_adoption=None, publication=None, execution_request=x["request_path"], edit_copies=False)
    result = {}
    module.inspect(args, result)
    return result


def test_zero_adoption_preserves_objects_and_keeps_complete_candidate_separate(tmp_path):
    x = _fixture(tmp_path)
    result = _saved(x, tmp_path / "out")
    assert result["status"] == "PASS"
    assert result["unchanged_complete_old_objects"] == 2
    assert result["target_object_ids"] == []
    assert result["unadopted_candidate_path_ids"] == ["candidate"]
    assert result["actual_target_bindings_status"] == "NOT_APPLICABLE_ZERO_ADOPTED"
    assert result["edit_isolation_status"] == "NOT_APPLICABLE_ZERO_ADOPTED"


def test_zero_targets_does_not_hide_unexpected_formal_entity(tmp_path):
    x = _fixture(tmp_path)
    doc = ezdxf.readfile(x["dxf"])
    _identity(doc.modelspace().add_line((3, 5), (8, 5)), "surprise", "LINE")
    doc.saveas(x["dxf"])
    x["metadata"]["objects"].append({"id": "surprise", "kind": "LINE", "layer": "0", "geometry": {}})
    x["metadata"]["written"].append({"id": "surprise"})
    _publish(x)
    result = _saved(x, tmp_path / "out")
    assert result["status"] == "FAIL" and result["target_object_ids"] == []
    assert result["target_and_file_sets"]["unexpected_new_ids"] == ["surprise"]


def test_recursive_block_change_is_attributed_to_complete_parent_object(tmp_path):
    x = _fixture(tmp_path)
    doc = ezdxf.readfile(x["dxf"])
    doc.blocks["leaf"][0].dxf.end = (3.0000000000000004, 0, 0)
    doc.saveas(x["dxf"])
    result = compare_saved_dxf(x["baseline"], x["dxf"])
    assert result["unchanged_top_level_object_count"] == 2
    assert result["unchanged_old_object_count"] == 1
    assert result["changed_complete_old_ids"] == ["old-block"]
    assert result["changed_top_level_old_ids"] == []
    assert result["status"] == "FAIL"


def test_recursive_block_dependency_uses_case_insensitive_symbol_resolution(tmp_path):
    x = _fixture(tmp_path)
    doc = ezdxf.readfile(x["dxf"])
    doc.blocks["parent"][0].dxf.name = "LEAF"
    doc.saveas(x["baseline"])
    doc.saveas(x["dxf"])
    result = compare_saved_dxf(x["baseline"], x["dxf"])
    assert result["status"] == "PASS"
    assert result["unchanged_old_object_count"] == 2


def test_unsupported_insert_target_is_structured_rejection_not_attribute_error(tmp_path):
    x = _fixture(tmp_path)
    doc = ezdxf.readfile(x["dxf"])
    entity = next(e for e in doc.modelspace() if e.has_xdata(APPID) and entity_identity(e)["id"] == "old-block")
    result = check_target_binding(entity, {"id": "old-block", "kind": "BLOCK", "layer": "0", "geometry": {}}, [0, 0, 64, 64], 25.4)
    assert not result["pass"]
    assert result["reason"] == "UNSUPPORTED_DECLARED_TARGET_NATIVE_TYPE"
    assert "thickness_zero" not in result["checks"]


@pytest.mark.parametrize("missing", ["plan_path", "adoption_path", "request_path", "publication_path"])
def test_missing_stage_receipt_never_claims_executed_zero(tmp_path, missing):
    x = _fixture(tmp_path)
    x[missing].unlink()
    result = _stage(x)
    assert result["status"] == "NOT_RUN"
    assert result["stage_execution_status"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("mutation", ["source", "plan_file", "source_frame", "producer", "dependency", "execution", "candidate_count"])
def test_source_producer_dependency_and_stage_mutation_refused(tmp_path, mutation):
    x = _fixture(tmp_path)
    assert _stage(x)["status"] == "PASS"
    if mutation == "source":
        image = Image.open(x["source"]).copy()
        image.putpixel((0, 0), 0)
        image.save(x["source"])
    elif mutation == "plan_file":
        x["plan"]["pending"] = ["changed after publication"]
        _write(x["plan_path"], x["plan"])
    elif mutation == "source_frame":
        x["plan"]["roi_xyxy_px"][0] = 1
        _publish(x)
    elif mutation == "producer":
        x["plan"]["producer_sha256"] = "0" * 64
        _publish(x)
    elif mutation == "dependency":
        name = "attached_stroke_ink.py"
        x["plan"]["additional_producer_sha256"][name] = "0" * 64
        x["request"]["algorithm"]["files"]["app/native_objects/" + name] = "0" * 64
        x["request"]["algorithm"]["sha256"] = digest(x["request"]["algorithm"]["files"])
        _publish(x)
    elif mutation == "execution":
        x["adoption"].pop("stage_execution")
        _publish(x)
    else:
        x["adoption"]["stage_execution"]["candidate_path_count"] = 0
        _publish(x)
    result = _stage(x)
    assert result["status"] == "FAIL"
    assert result["source_complete_responsibility"] == "NOT_ESTABLISHED_BY_STAGE_DECLARATIONS"


def test_common_cli_always_writes_failure_receipt_and_preserves_stage_not_run(tmp_path):
    x = _fixture(tmp_path)
    x["adoption_path"].unlink()
    out = tmp_path / "common"
    command = [sys.executable, str(COMMON), "--source", str(x["source"]), "--baseline", str(x["baseline"]),
        "--dxf", str(x["dxf"]), "--metadata", str(x["metadata_path"]), "--source-roi", "0", "0", "64", "64",
        "--audit-roi", "0", "0", "64", "64", "--dpi", "25.4", "--execution-request", str(x["request_path"]), "--out", str(out)]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    assert process.returncode == 1
    result = json.loads((out / "COMMON_ACCEPTANCE.json").read_text())
    assert result["status"] == "NOT_RUN_STAGE"
    assert result["candidate_source_responsibility"]["status"] == "NOT_RUN_STAGE_UNAVAILABLE"
    assert result["actual_saved_geometry_and_edit_isolation"]["protection"] == "PASS"
    assert result["errors"] == []
    assert "Traceback" not in process.stderr


def test_common_cli_bad_input_still_emits_machine_readable_failure(tmp_path):
    x = _fixture(tmp_path)
    x["metadata_path"].write_text("{invalid json", encoding="utf-8")
    out = tmp_path / "common"
    process = subprocess.run([sys.executable, str(COMMON), "--source", str(x["source"]), "--baseline", str(x["baseline"]),
        "--dxf", str(x["dxf"]), "--metadata", str(x["metadata_path"]), "--source-roi", "0", "0", "64", "64",
        "--audit-roi", "0", "0", "64", "64", "--dpi", "25.4", "--execution-request", str(x["request_path"]), "--out", str(out)],
        capture_output=True, text=True, check=False)
    assert process.returncode == 1 and "Traceback" not in process.stderr
    assert (out / "COMMON_ACCEPTANCE.json").is_file()
    saved = json.loads((out / "saved/SAVED_GEOMETRY_AND_EDITS.json").read_text())
    assert saved["status"] == "FAIL" and saved["baseline_protection_status"] == "PASS"
    assert saved["errors"]


def _numerical_fixture(x, tmp_path):
    """A declared receipt fixture; never reported as an actual source rebuild."""
    stage = _stage(x)
    output = tmp_path / "declared-cold-result.json"
    cold = {"pass": True, "reason": "ATTACHED_GRAPH_JOINT_V3_SOURCE_REPLAY",
            "saved_plan_sha256": stage["plan_canonical_sha256"], "source_graph_rebuilt_from_original": True}
    _write(output, cold)
    receipt = {"schema": "joint-numeric-execution-v3", "command": "verify-plan",
        "status": "PASS_JOINT_V3_SOURCE_PLAN_REPLAY", "pass": True, "plan_schema": JOINT_PLAN,
        "actual_source_sha256": sha256(x["source"]), "expected_source_sha256": sha256(x["source"]),
        "checked_plan_file_sha256": sha256(x["plan_path"]),
        "checked_plan_canonical_sha256": stage["plan_canonical_sha256"],
        "algorithm_identity": x["request"]["algorithm"], "algorithm_identity_after": x["request"]["algorithm"],
        "current_joint_producer_sha256": stage["producer_dependencies"],
        "execution_request_binding": {"sha256": sha256(x["request_path"]), "pass": True, "checks": {"source": True}},
        "independently_rebuilt": True, "source_graph_argument": None,
        "original_inputs_and_source_modules_unchanged": True, "algorithm_identity_unchanged": True,
        "output_path": str(output), "output_sha256": sha256(output)}
    receipt_path = tmp_path / "declared-cold-result.execution.json"
    _write(receipt_path, receipt)
    return stage, output, cold, receipt_path, receipt


@pytest.mark.parametrize("mutation", ["not_rebuilt", "output_bytes", "producer", "source", "plan", "request", "result_false"])
def test_numerical_receipt_must_bind_actual_result_and_same_saved_stage(tmp_path, mutation):
    x = _fixture(tmp_path)
    stage, output, cold, receipt_path, receipt = _numerical_fixture(x, tmp_path)
    spec = importlib.util.spec_from_file_location("common_audit_entry", COMMON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._numerical_receipt(receipt_path, stage, sha256(x["source"]), sha256(x["dxf"]))["status"] == "PASS"
    if mutation == "not_rebuilt":
        receipt["independently_rebuilt"] = False
    elif mutation == "output_bytes":
        cold["pass"] = False
        _write(output, cold)
    elif mutation == "producer":
        receipt["current_joint_producer_sha256"] = {"attached_stroke_graph.py": "0" * 64}
    elif mutation == "source":
        receipt["actual_source_sha256"] = "0" * 64
    elif mutation == "plan":
        receipt["checked_plan_file_sha256"] = "0" * 64
    elif mutation == "request":
        receipt["execution_request_binding"]["sha256"] = "0" * 64
    else:
        cold["pass"] = False
        _write(output, cold)
        receipt["output_sha256"] = sha256(output)
    _write(receipt_path, receipt)
    result = module._numerical_receipt(receipt_path, stage, sha256(x["source"]), sha256(x["dxf"]))
    assert result["status"] == "FAIL"
    assert result["independently_rerun_by_this_entry_point"] is False


def _checkpoint_fixture(x, tmp_path):
    """Tiny declared provenance fixture; no OCR, producer or model is executed."""
    root = REPO / "cad_photo_to_dxf"
    checkpoint = tmp_path / "captured"
    state = {"objects": x["metadata"]["objects"], "fixture_label": "完整有限状态"}
    _write(checkpoint / "upstream_state.json", state)
    _write(checkpoint / "evidence/raw.json", {"observations": "unchanged fixture"})
    stages = ["short_contact_text"]
    downstream = ["fresh_source_graph", "attached_ink", "all_prior_contacts", "joint_numerical_contract",
                  "native_save", "saved_source_cold_read", "current_input_quality_review", "render", "independent_old_content_check"]
    manifest = {"schema": "source-stage-checkpoint-pre-attached-v1", "boundary": "AFTER_SHORT_CONTACT_BEFORE_ATTACHED",
        "source": {"source_sha256": sha256(x["source"]), "parameters": x["request"]["parameters"], "unit": "paper_mm"},
        "producer_closure": {"historical_worker_recorded_native_files": {
            "app/native_objects/contracts.py": sha256(root / "app/native_objects/contracts.py")}},
        "runtime_and_resources": {"declared_fixture_identity": "runtime not independently recreated by this test"},
        "checkpoint_validator_sha256": sha256(root / "app/native_objects/source_stage_checkpoint.py"),
        "continuation_executor_sha256": {"app/native_objects/pipeline.py": sha256(root / "app/native_objects/pipeline.py")},
        "upstream_state_sha256": __import__("hashlib").sha256(json.dumps(state, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "artifacts": [{"path": path.relative_to(checkpoint).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
                      for path in (checkpoint / "upstream_state.json", checkpoint / "evidence/raw.json")],
        "reused_stages": stages, "downstream_required": downstream, "old_DXF_read": False}
    manifest_path = checkpoint / "manifest.json"
    _write(manifest_path, manifest)
    x["request"]["source_stage_checkpoint"] = {
        "schema": "captured-source-stage-checkpoint-v1", "manifest_path": str(manifest_path),
        "manifest_sha256": sha256(manifest_path), "source_sha256": sha256(x["source"]),
        "parameters": x["request"]["parameters"], "execution_mode": "SOURCE_STAGE_CHECKPOINT_CONTINUATION",
        "reused_stages": stages, "downstream_required": downstream}
    _publish(x)
    evidence = x["dxf"].with_suffix(".native") / "evidence"
    _write(evidence / "cold_audit.json", {"source_gate_pass": False})
    _write(evidence / "quality_review.json", {"status": "REVIEW_REQUIRED"})
    current = {"status": "EXECUTED_CURRENT_PLANNER", "plan_sha256": sha256(x["plan_path"]),
        "adoption_sha256": sha256(x["adoption_path"]), "adopted_object_count": 0,
        "candidate_components": len(x["plan"]["components"]), "stage_execution": x["adoption"]["stage_execution"]}
    receipt = {"schema": "source-stage-continuation-execution-v1", "execution_mode": "SOURCE_STAGE_CHECKPOINT_CONTINUATION",
        "checkpoint_manifest_sha256": sha256(manifest_path),
        **{key: deepcopy(manifest[key]) for key in ("source", "producer_closure", "runtime_and_resources", "upstream_state_sha256", "reused_stages")},
        "prior_object_count": 2, "old_attached_result_reused": False, "old_DXF_read": False,
        "new_upstream_fits": 0, "new_OCR_calls": 0, "new_model_inferences": 0,
        "downstream": {"fresh_source_graph": "EXECUTED_REBUILT_FROM_UNCHANGED_PIXELS",
            **{key: deepcopy(current) for key in ("attached_ink", "all_prior_contacts", "joint_numerical_contract")},
            "native_save": {"status": "EXECUTED", "dxf_sha256": sha256(x["dxf"])},
            "saved_source_cold_read": {"status": "EXECUTED", "source_gate_pass": False, "receipt_sha256": sha256(evidence / "cold_audit.json")},
            "current_input_quality_review": {"status": "EXECUTED", "receipt_sha256": sha256(evidence / "quality_review.json")},
            "render": "EXECUTED_CURRENT_SAVED_DXF", "independent_old_content_check": "NOT_RUN"}}
    receipt_path = evidence / "source_stage_continuation.json"
    _write(receipt_path, receipt)
    publication = json.loads(x["publication_path"].read_text())
    publication["evidence_files"].update({"evidence/" + name: sha256(evidence / name)
        for name in ("source_stage_continuation.json", "cold_audit.json", "quality_review.json")})
    _write(x["publication_path"], publication)
    return manifest_path, manifest, receipt_path, receipt, publication


@pytest.mark.parametrize("mutation", [None, "artifact_bytes", "manifest_bytes", "dependency_receipt", "stage_plan",
                                      "saved_dxf", "old_adoption_reuse", "extra_artifact", "cold_receipt"])
def test_checkpoint_binds_actual_members_and_current_published_execution(tmp_path, mutation):
    x = _fixture(tmp_path)
    manifest_path, manifest, receipt_path, receipt, publication = _checkpoint_fixture(x, tmp_path)
    if mutation == "artifact_bytes":
        (manifest_path.parent / "evidence/raw.json").write_text("changed")
    elif mutation == "manifest_bytes":
        manifest["runtime_and_resources"]["declared_fixture_identity"] = "changed"
        _write(manifest_path, manifest)
    elif mutation == "dependency_receipt":
        receipt["runtime_and_resources"]["declared_fixture_identity"] = "changed"
    elif mutation == "stage_plan":
        receipt["downstream"]["attached_ink"]["plan_sha256"] = "0" * 64
    elif mutation == "saved_dxf":
        receipt["downstream"]["native_save"]["dxf_sha256"] = "0" * 64
    elif mutation == "old_adoption_reuse":
        receipt["old_attached_result_reused"] = True
    elif mutation == "extra_artifact":
        (manifest_path.parent / "undeclared.txt").write_text("unbound content")
    elif mutation == "cold_receipt":
        (receipt_path.parent / "cold_audit.json").write_text("{}")
    _write(receipt_path, receipt)
    publication["evidence_files"]["evidence/source_stage_continuation.json"] = sha256(receipt_path)
    _write(x["publication_path"], publication)
    result = _stage(x)
    assert result["status"] == ("PASS" if mutation is None else "FAIL")
    if mutation is None:
        binding = result["source_stage_checkpoint_binding"]
        assert binding["status"] == "PASS" and binding["prior_object_count"] == 2
        assert binding["source_ownership_authorized_by_this_check"] is False
        assert binding["runtime_environment_revalidated_by_this_checker"] is False
        assert binding["checks"]["cold_read_result_recorded_without_promotion"] is True


def test_common_zero_adoption_with_candidates_has_separate_unresolved_source_result(tmp_path):
    x = _fixture(tmp_path)
    _, _, _, receipt_path, _ = _numerical_fixture(x, tmp_path)
    out = tmp_path / "common"
    command = [sys.executable, str(COMMON), "--source", str(x["source"]), "--baseline", str(x["baseline"]),
        "--dxf", str(x["dxf"]), "--metadata", str(x["metadata_path"]), "--source-roi", "0", "0", "64", "64",
        "--audit-roi", "0", "0", "64", "64", "--dpi", "25.4", "--execution-request", str(x["request_path"]),
        "--numerical-replay-receipt", str(receipt_path), "--out", str(out)]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads((out / "COMMON_ACCEPTANCE.json").read_text())
    assert result["status"] == "PASS_ZERO_ADOPTED_PRESERVED_BASELINE"
    assert result["candidate_source_responsibility"]["status"] == "SOURCE_UNRESOLVED"
    assert result["original_pixel_source_responsibility"]["status"] == "NOT_APPLICABLE_ZERO_ADOPTED"
    assert result["source_complete_ownership"] == "SOURCE_UNRESOLVED"
    assert result["combined_adoption_authorized"] is False


def test_common_actual_saved_white_gap_is_not_downgraded_to_unresolved(tmp_path):
    x = _fixture(tmp_path)
    path = {"stroke_id": "declared-white-gap", "representation": {
        "points": [[8., 20.], [47., 20.]], "bulges": [0., 0.], "closed": False}}
    x["plan"]["paths"] = [path]
    x["plan"]["components"][0]["candidate_paths"] = [path]
    obj = {"id": path["stroke_id"], "kind": "LINE", "layer": "NATIVE",
        "geometry": {"start": path["representation"]["points"][0], "end": path["representation"]["points"][1]},
        "source_evidence": {"attached_stroke_graph": {"schema": JOINT_NATIVE,
            "source_sha256": sha256(x["source"]), "path_index": 0,
            "path_sha256": digest(path), "plan_sha256": digest(x["plan"]), "path": path}}}
    doc = ezdxf.readfile(x["dxf"])
    entity = doc.modelspace().add_line((8., 44.), (47., 44.), dxfattribs={"layer": "NATIVE"})
    _identity(entity, obj["id"], obj["kind"])
    doc.saveas(x["dxf"])
    x["metadata"]["objects"].append(obj)
    x["metadata"]["written"].append({"id": obj["id"]})
    x["adoption"]["objects"] = [obj]
    x["adoption"]["decisions"] = [{"id": obj["id"], "adopted": True}]
    x["adoption"]["stage_execution"]["adopted_path_count"] = 1
    _publish(x)
    _, _, _, receipt_path, _ = _numerical_fixture(x, tmp_path)
    out = tmp_path / "common"
    command = [sys.executable, str(COMMON), "--source", str(x["source"]), "--baseline", str(x["baseline"]),
        "--dxf", str(x["dxf"]), "--metadata", str(x["metadata_path"]), "--source-roi", "0", "0", "64", "64",
        "--audit-roi", "0", "0", "64", "64", "--dpi", "25.4", "--execution-request", str(x["request_path"]),
        "--numerical-replay-receipt", str(receipt_path), "--out", str(out)]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    assert process.returncode == 1, process.stderr + process.stdout
    result = json.loads((out / "COMMON_ACCEPTANCE.json").read_text())
    assert result["actual_saved_geometry_and_edit_isolation"]["status"] == "PASS"
    assert result["identity_and_numerical_replay"]["status"] == "PASS"
    assert result["original_pixel_source_responsibility"]["status"] == "HARD_REJECT"
    assert result["status"] == "FAIL_SOURCE_RESPONSIBILITY"
    assert result["source_complete_ownership"] == "HARD_REJECT"
    assert result["combined_adoption_authorized"] is False
