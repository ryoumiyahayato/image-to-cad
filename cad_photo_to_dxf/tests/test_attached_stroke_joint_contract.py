"""Candidate/accepted scopes, exact new ink fields and machine-readable cold binding."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from app.native_objects import attached_stroke_graph as graph
from app.native_objects import attached_stroke_numeric as numeric
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from tests.test_attached_stroke_graph import _source
from tests.test_native_transverse_stroke_geometry import ROI, _structure_stage


@pytest.fixture(scope="module")
def pending_source_plan(tmp_path_factory):
    out = tmp_path_factory.mktemp("joint-candidate-source")
    gray = _source()
    # The frozen six-cell wedge: rebuild source graph and formal owner from
    # these changed original pixels; no old graph or adopted four-path output.
    gray[127, 125:129] = 0
    gray[128, 125:127] = 0
    context, initial, structure = _structure_stage(gray)
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    owner = complete_text_contact_paths(gray, ROI, source_sha, initial, [structure], out / "owner")
    assert len(owner["objects"]) == 1
    prior = [row for row in initial if row["id"] not in owner["retired_ids"]] + owner["objects"]
    plan = graph.plan_attached_stroke_graph(gray, ROI, prior, source_graph=context)
    assert plan["paths"] == []
    assert sum(len(c.get("candidate_paths", [])) for c in plan["components"]) == 4
    return gray, plan


def _component(plan):
    return next(c for c in plan["components"] if c.get("candidate_paths"))


def _compare(a, b):
    return numeric.compare_plans(a, b, expected_schema=numeric.PLAN_SCHEMA,
                                 expected_producer_sha256=a["producer_sha256"])


def test_complete_pending_candidates_receive_only_their_own_diagnostic_scope(pending_source_plan):
    _, plan = pending_source_plan
    before = deepcopy(plan)
    certificate = numeric.build_certificate(plan)
    assert plan == before and plan["paths"] == []
    assert certificate["pass"], certificate["scope_failures"]
    selected = next(scope for scope in certificate["diagnostic_scopes"] if scope["candidate_path_ids"])
    assert selected["scope"] == "CANDIDATE_DIAGNOSTICS_ONLY"
    assert selected["adopted_path_ids"] == []
    assert len(selected["candidate_path_ids"]) == 4
    assert not selected["source_adoption_authorized"]
    assert all(row["path"][0] != "paths" for row in certificate["entries"])
    assert any(row["path"][2:3] == ["candidate_paths"] for row in certificate["entries"])
    assert _compare(plan, deepcopy(plan))["pass"]


@pytest.mark.parametrize("change", ["candidate_list", "one_candidate", "contact_reference", "component_id"])
def test_missing_candidate_or_reference_returns_invalid_receipt_not_keyerror(pending_source_plan, change):
    _, original = pending_source_plan
    plan = deepcopy(original)
    component = _component(plan)
    if change == "candidate_list":
        del component["candidate_paths"]
    elif change == "one_candidate":
        component["candidate_paths"].pop()
    elif change == "contact_reference":
        component["native_contact_check"]["pair_checks"][0]["object_ids"][0] = "MISSING-FINITE-PATH"
    else:
        component["candidate_paths"][0]["component_id"] = "ANOTHER-COMPONENT"
    result = numeric.build_certificate(plan)
    assert not result["pass"]
    assert result["status"] == "INVALID_INPUT"
    assert result["scope_failures"]
    assert not _compare(plan, deepcopy(plan))["pass"]


@pytest.mark.parametrize("change", ["native_coordinate", "stroke_id", "new_ink_width", "numeric_producer", "contract"])
def test_joint_contract_never_tolerates_native_or_new_ink_changes(pending_source_plan, change):
    _, original = pending_source_plan
    plan = deepcopy(original)
    row = _component(plan)["candidate_paths"][0]
    if change == "native_coordinate":
        value = row["representation"]["points"][0][0]
        row["representation"]["points"][0][0] = math.nextafter(value, math.inf)
    elif change == "stroke_id":
        row["stroke_id"] += "-changed"
    elif change == "new_ink_width":
        terminal = next(t for r in _component(plan)["candidate_paths"] for t in r["endpoint_evidence"]
                        if "attached_raw_ink_responsibility" in t)
        proof = terminal["attached_raw_ink_responsibility"]
        interval = proof["independent_width_evidence"]["guest"]["half_width_interval_px"]
        interval[0] = math.nextafter(interval[0], math.inf)
    elif change == "numeric_producer":
        plan["additional_producer_sha256"]["attached_stroke_numeric.py"] = "0" * 64
    else:
        plan["joint_contract"]["candidate_and_adopted_scopes_separate"] = False
    assert not _compare(original, plan)["pass"]


def test_historical_candidate_plan_is_diagnosed_without_joint_relabelling(pending_source_plan):
    _, original = pending_source_plan
    historical = deepcopy(original)
    historical["schema"] = numeric.HISTORICAL_V2_SCHEMA
    before = deepcopy(historical)
    certificate = numeric.build_certificate(historical)
    assert certificate["pass"] and historical == before
    assert certificate["input_plan_schema"] == numeric.HISTORICAL_V2_SCHEMA
    assert certificate["historical_input_not_joint_execution"]
    result = graph.verify_attached_stroke_graph_plan(None, ROI, historical)
    assert not result["pass"]
    assert result["reason"] == "HISTORICAL_OR_UNKNOWN_PLAN_IS_NOT_JOINT_EXECUTION"
    assert not result.get("source_graph_rebuilt_from_original", False)


@pytest.mark.parametrize("change", ["adopted_status", "adopted_ids"])
def test_candidate_only_plan_cannot_claim_formal_adoption(pending_source_plan, change):
    _, original = pending_source_plan
    plan = deepcopy(original)
    component = _component(plan)
    if change == "adopted_status":
        component["status"] = "UNIQUE_COMPLETE_GRAPH_DECOMPOSITION"
    else:
        component["new_complete_path_ids"] = [row["stroke_id"] for row in component["candidate_paths"]]
    result = numeric.build_certificate(plan)
    assert not result["pass"] and result["status"] == "INVALID_INPUT"
    assert any(row["reason"] == "NUMERIC_ADOPTION_DECLARATION_WITHOUT_FORMAL_PATHS"
               for row in result["scope_failures"])
    assert plan["paths"] == []
    assert not _compare(plan, deepcopy(plan))["pass"]


def test_candidate_only_original_source_cold_rebuild_is_bound(pending_source_plan):
    gray, plan = pending_source_plan
    result = graph.verify_attached_stroke_graph_plan(gray, ROI, plan, source_graph=None)
    assert result["pass"], result
    assert result["source_graph_rebuilt_from_original"]
    assert result["replayed_paths"] == []
    assert result["saved_plan_sha256"] == graph._digest(plan)


@pytest.mark.parametrize("change", ["source_hash", "plan_hash", "missing_input", "graph_producer"])
def test_cold_cli_rejects_bound_input_failures_with_receipt_before_claiming_rebuild(tmp_path, pending_source_plan, change):
    gray, original = pending_source_plan
    repo = Path(__file__).resolve().parents[2]
    source, plan_path, output = tmp_path / "source.png", tmp_path / "plan.json", tmp_path / "result.json"
    Image.fromarray(gray).save(source)
    plan = deepcopy(original)
    if change == "graph_producer":
        plan["producer_sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if change == "source_hash":
        source_sha = "0" * 64
    elif change == "plan_hash":
        plan_sha = "0" * 64
    elif change == "missing_input":
        source.unlink()
    command = [sys.executable, str(repo / "experiments/issue61_joint_contract/replay_numerical_contract.py"),
               "verify-plan", "--repo", str(repo), "--plan", str(plan_path), "--expected-plan-sha256", plan_sha,
               "--input", str(source), "--expected-source-sha256", source_sha, "--output", str(output)]
    completed = subprocess.run(command, text=True, capture_output=True)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    execution = json.loads(output.with_suffix(".json.execution.json").read_text(encoding="utf-8"))
    assert report["pass"] is False and execution["pass"] is False
    assert execution["independently_rebuilt"] is False
    assert execution["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert execution["output_path"] == str(output)
