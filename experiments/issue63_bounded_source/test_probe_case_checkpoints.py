"""Lightweight checkpoint plumbing tests; no source model or DXF audit is run.

The completed-reference fixture contains explicitly authored receipt stubs.
It exercises integrity and lifecycle gates, never physical source acceptance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_probes as runner  # noqa: E402


def _replace_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runner.plain(value), indent=2) + "\n", encoding="utf-8")


def _refresh_manifests(root):
    for path in root.rglob("FILE_MANIFEST.json"):
        path.unlink()
    _replace_json(root / "baseline/FILE_MANIFEST.json", {"files": runner.case_files(root / "baseline")})
    _replace_json(root / "FILE_MANIFEST.json", {"files": runner.file_manifest(root)})


@pytest.fixture(scope="module")
def prepared():
    from tests.test_attached_stroke_graph import _source

    baseline = _source()
    output = []
    for variant in runner.variants():
        gray = _source(variant=variant["fixture_variant"]) if "fixture_variant" in variant else baseline.copy()
        for x, y in variant["pixels"]:
            gray[y, x] = 0
        output.append((variant, gray))
    return output


def test_single_case_selection_still_checks_every_actual_authored_array(prepared):
    selected = runner.select_prepared_variants(prepared, "baseline")
    assert [row[0]["name"] for row in selected] == ["baseline"]
    assert len(runner.select_prepared_variants(prepared, None)) == 8
    changed = [(row, array.copy()) for row, array in prepared]
    changed[-1][1][0, 0] = 0
    with pytest.raises(ValueError, match="ALL_EIGHT_ORIGINAL_SOURCE_ARRAYS"):
        runner.select_prepared_variants(changed, "baseline")


@pytest.fixture
def reference(tmp_path, prepared):
    from PIL import Image

    root, repo = tmp_path / "reference", tmp_path / "repo"
    case = root / "baseline"
    case.mkdir(parents=True)
    native = repo / "cad_photo_to_dxf/app/native_objects"
    native.mkdir(parents=True)
    for name in (*runner.EXPECTED_ADDITIONAL_PRODUCERS, "attached_stroke_graph.py"):
        (native / name).write_text("# authored identity fixture: " + name + "\n", encoding="utf-8")
    attached = SimpleNamespace(__file__=str(native / "attached_stroke_graph.py"),
        SCHEMA=runner.EXPECTED_PLAN_SCHEMA, POLICY={"version": "CHECKPOINT_PLUMBING_ONLY"})
    entry_rel = "experiments/issue63_bounded_source/run_probes.py"
    entry_path = repo / entry_rel
    entry_path.parent.mkdir(parents=True)
    entry_path.write_bytes(Path(runner.__file__).read_bytes())
    snapshot = "executed_entrypoints/run_probes.py"
    (root / snapshot).parent.mkdir()
    (root / snapshot).write_bytes(entry_path.read_bytes())
    source_files = {str(path.relative_to(repo)): runner.file_sha(path) for path in repo.rglob("*.py")}
    git = {"head": "a" * 40, "head_tree": "b" * 40, "worktree_dirty": False,
        "uncommitted_execution_is_bound_by_exact_source_file_hashes": True}
    baseline = prepared[0][1]
    roi = [0, 0, baseline.shape[1], baseline.shape[0]]
    Image.fromarray(baseline).save(case / "source.png")
    paths = [{"stroke_id": "fixture-" + str(index), "representation": [[index, 0], [index, 1]],
              "endpoint_evidence": [{"host_path_index": 0}] if index else []} for index in range(4)]
    plan = {"schema": runner.EXPECTED_PLAN_SCHEMA,
        "producer_sha256": runner.file_sha(attached.__file__),
        "additional_producer_sha256": {name: runner.file_sha(native / name) for name in runner.EXPECTED_ADDITIONAL_PRODUCERS},
        "original_source_crop_xyxy_px": roi, "original_source_crop_array_sha256": runner.array_sha(baseline),
        "paths": paths, "components": [{"component_id": "fixture", "candidate_paths": paths,
            "finite_component_responsibility": {"schema": runner.EXPECTED_COMPONENT_SCHEMA,
                "pass": True, "status": "AUTHORED_RECEIPT_STUB_NOT_PHYSICAL_EVIDENCE"}}]}
    _replace_json(case / "evidence/attached_strokes/plan.json", plan)
    responsibility = runner.plain(runner.responsibility_summary(plan, baseline, []))
    _replace_json(case / "responsibility_summary.json", responsibility)
    graph = {"schema": "issue63-fresh-synthetic-source-graph-v1", "roi": roi, "crop_bbox": roi,
        "crop_array_sha256": runner.array_sha(baseline), "skeleton_points_px": [[1, 2]], "nodes": [], "edges": []}
    _replace_json(case / "fresh_graph.json", graph)
    branches = {"witness_count": 0}
    _replace_json(case / "FRESH_BRANCH_RESPONSIBILITY.json", branches)
    for name in ("actual_adopted.dxf", "prior.dxf"):
        (case / name).write_text("Authored file-identity stub; this is not a DXF.\n", encoding="utf-8")
    saved = {"adopted_count": 4, "actual_adopted_dxf_sha256": runner.file_sha(case / "actual_adopted.dxf"),
        "prior_dxf_sha256": runner.file_sha(case / "prior.dxf")}
    _replace_json(case / "saved_files.json", saved)
    strict = {"pass": True, "fresh_source_graph_requested": True, "checks": {"authored_stub": True},
        "plan_file_sha256": runner.file_sha(case / "evidence/attached_strokes/plan.json"),
        "source_files_sha256": source_files, "implementation": runner.implementation_identity(attached, plan),
        "actual_saved_plan_fields": sorted(plan), "actually_compared_fields": sorted(plan),
        "verification": {"pass": True, "checks": dict.fromkeys(plan, True)},
        "saved_dxf": {"pass": True, "adopted_count": 4, "actual_dxf_sha256": saved["actual_adopted_dxf_sha256"],
            "actual_saved_source_audit": {"acceptance_pass": True}}}
    _replace_json(case / "strict_replay.json", strict)
    result = {"name": "baseline", "status": "ADOPTED_COMPONENT", "adopted_count": 4, "strict_replay_exit_code": 0,
        "strict_source_and_saved_replay_pass": True, "evidence_integrity_pass": True,
        "source_array_sha256": runner.EXPECTED_SOURCE_HASHES["baseline"], "implementation": runner.implementation_identity(attached, plan)}
    result["current_control_gate"] = runner.current_control_gate(runner.variants()[0], result, responsibility, branches, strict)
    _replace_json(case / "result.json", result)
    _replace_json(case / "input_identity.json", {"name": "baseline", "roi": roi, "dpi": runner.DPI,
        "source_array_sha256": runner.EXPECTED_SOURCE_HASHES["baseline"], "source_png_sha256": runner.file_sha(case / "source.png"),
        "added_original_black_pixels_px": [], "removed_original_black_pixels_px": []})
    common = {"schema": runner.SCHEMA, "script_version": runner.SCRIPT_VERSION, "original_variant_count": 8,
        "planned_variant_count": 1, "execution_variants": ["baseline"], "execution_scope": "SINGLE_ORIGINAL_CASE",
        "implementation": runner.implementation_identity(attached)}
    _replace_json(root / "FROZEN_VARIANTS.json", {**common, "variants": runner.variants(),
        "variant_array_sha256": runner.EXPECTED_SOURCE_HASHES, "original_variant_array_sha256": runner.EXPECTED_SOURCE_HASHES,
        "all_original_source_hashes_match": True, "source_files_sha256": source_files, "source_git": git})
    _replace_json(root / "ORIGINAL_SOURCE_HASH_CHECK.json", {"pass": True,
        "all_original_sources_built_before_selection": True, "original_variant_count": 8,
        "actual_source_array_sha256": runner.EXPECTED_SOURCE_HASHES, "expected_source_array_sha256": runner.EXPECTED_SOURCE_HASHES})
    _replace_json(root / "SUMMARY.json", {**common, "run_completed": True, "pass": True, "results": [result],
        "source_files_sha256_before": source_files, "source_files_sha256_after": source_files,
        "source_git_before": git, "source_git_after": git, "source_files_unchanged": True, "source_git_unchanged": True,
        "all_strict_source_and_saved_replays_pass": True, "all_input_and_graph_integrity_checks_pass": True,
        "all_current_control_gates_pass": True, "script_sha256": runner.file_sha(runner.__file__)})
    _replace_json(root / "EXECUTION_ENTRY.json", {"git": git, "arguments": {"case": "baseline", "baseline_reference": None},
        "entries": [{"source": entry_rel, "snapshot": snapshot, "sha256": runner.file_sha(entry_path)}]})
    _refresh_manifests(root)
    return root, repo, attached, source_files, git, baseline, roi


def test_completed_reference_returns_only_comparison_diagnostics(reference):
    comparisons, receipt = runner.load_baseline_reference(*reference)
    assert set(comparisons) == {"graph", "graph_record", "geometry", "proofs"}
    assert comparisons["graph"] == {(1, 2)}
    assert len(comparisons["geometry"]) == 4
    assert receipt["comparison_only"] is True
    assert receipt["used_as_source_graph_owner_plan_or_adoption_input"] is False
    assert receipt["root_manifest_sha256"] == runner.file_sha(reference[0] / "FILE_MANIFEST.json")


@pytest.mark.parametrize("change", ["missing_file", "changed_bytes", "unlisted_file", "changed_nested_manifest"])
def test_reference_manifest_cannot_hide_missing_extra_or_modified_bytes(reference, change):
    root = reference[0]
    if change == "missing_file":
        (root / "baseline/fresh_graph.json").unlink()
    elif change == "changed_bytes":
        (root / "baseline/actual_adopted.dxf").write_text("changed endpoint", encoding="utf-8")
    elif change == "unlisted_file":
        (root / "baseline/unlisted.json").write_text("{}", encoding="utf-8")
    else:
        _replace_json(root / "baseline/FILE_MANIFEST.json", {"files": []})
    with pytest.raises(ValueError, match="BASELINE_REFERENCE_MANIFEST"):
        runner.load_baseline_reference(*reference)


@pytest.mark.parametrize(("file", "key", "value", "failed_gate"), [
    ("SUMMARY.json", "run_completed", False, "completed_successful_reference"),
    ("SUMMARY.json", "execution_variants", ["one_pixel_cap"], "single_baseline_execution_scope"),
    ("SUMMARY.json", "source_files_sha256_after", {}, "same_complete_source_file_hashes"),
    ("baseline/strict_replay.json", "pass", False, "strict_fresh_source_and_saved_acceptance"),
    ("baseline/result.json", "adopted_count", 0, "one_complete_baseline_result"),
    ("baseline/input_identity.json", "source_array_sha256", "0" * 64, "complete_baseline_input_bytes"),
    ("baseline/evidence/attached_strokes/plan.json", "additional_producer_sha256", {}, "current_exact_producer_maps"),
])
def test_refreshed_manifest_does_not_authorize_incomplete_or_wrong_identity_reference(reference, file, key, value, failed_gate):
    root = reference[0]
    path = root / file
    record = json.loads(path.read_text(encoding="utf-8"))
    record[key] = value
    _replace_json(path, record)
    _refresh_manifests(root)
    with pytest.raises(ValueError, match=failed_gate):
        runner.load_baseline_reference(*reference)


def test_reference_from_another_tree_is_refused(reference):
    root, repo, attached, hashes, git, baseline, roi = reference
    changed_git = {**git, "head_tree": "c" * 40}
    with pytest.raises(ValueError, match="same_current_clean_git_identity"):
        runner.load_baseline_reference(root, repo, attached, hashes, changed_git, baseline, roi)
