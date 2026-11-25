"""Ordinary stage identities, assembly receipts and mixed-graph saved audits.

All sources are small public synthetic images. Recognition is stubbed only at
the existing stage seam; geometry discovery, export and cold proofs are real.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.native_objects import pipeline, revision_resume, single_line_labels
from app.native_objects.cad_io import cold_audit, export_objects, render_saved
from app.native_objects.connections import extract_connections
from app.native_objects.contracts import save_json
from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.text_contact_geometry import plan_text_contact_geometry
from tests.test_native_single_line_pipeline import _stage
from tests.test_native_text_contact_geometry import _contact_source, ROI, SEED


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _producer(name):
    return _sha(Path(pipeline.__file__).with_name(name + ".py"))


@pytest.fixture
def mixed_saved(tmp_path):
    """One old single-cycle cover plus an independent contact curve."""
    gray = np.full((240, 600), 255, np.uint8)
    roi = [0, 0, 600, 240]
    for center in ((25, 90), (195, 90)):
        cv2.circle(gray, center, 12, 0, 1)
    for points in (
        [(37, 90), (65, 69), (90, 63), (109, 60)],
        [(111, 60), (130, 63), (155, 69), (183, 90)],
    ):
        cv2.polylines(gray, [np.asarray(points, np.int32)], False, 0, 1)
    cv2.rectangle(gray, (109, 59), (111, 61), 0, 1)
    cv2.polylines(
        gray,
        [np.asarray([[270, 140], [335, 140], [385, 180], [570, 180]], np.int32)],
        False, 0, 1,
    )
    cv2.line(gray, (440, 160), (440, 180), 0, 1)
    root = tmp_path / "evidence"
    old = extract_connections(gray, roi, [], root / "connections/discovery")
    assert len(old["objects"]) == 1
    plan = plan_text_contact_geometry(gray, roi, [415, 155, 465, 185])
    result = complete_text_contact_paths(
        gray, roi, hashlib.sha256(gray.tobytes()).hexdigest(), old["objects"],
        [plan], root / "text_contact",
    )
    assert len(result["objects"]) == 1 and not result["retired_ids"]
    assert result["objects"][0]["kind"] == "CONNECTION_PATH"
    objects = old["objects"] + result["objects"]
    path = tmp_path / "result.dxf"
    export_objects(objects, path, roi, 200, result["source_sha256"])
    return path, gray, roi, result, old["objects"][0]


def _whole_audit(case, root=None):
    path, gray, roi, _, _ = case
    root = path.parent / "evidence" if root is None else root
    return cold_audit(path, gray, roi, 200, root / "cold_audit.json")


def test_whole_saved_audit_proves_legacy_and_contact_graphs_independently(mixed_saved):
    path, _, roi, result, _ = mixed_saved
    assert "source_graph_edge_ids" not in result["objects"][0]["source_evidence"]
    report = _whole_audit(mixed_saved)
    assert report["source_gate_pass"], report
    assert report["text_contact_source_checks"]["pass"]
    assert report["same_owner_retrace_cold_proof"]["evidence_status"] == "COMPLETE_COLD_PROOF"
    assert all(row["pass"] for row in report["same_owner_retrace_cold_proof"]["object_checks"])
    assert len(report["certified_same_owner_retraces"]) == 4
    assert not report["exact_duplicate_segments"]
    assert not report["ezdxf_errors"] and not report["ezdxf_in_memory_fixes"]
    preview = path.with_suffix(".png")
    rendered = render_saved(path, preview, roi)
    assert rendered["DXF_sha256"] == _sha(path)
    pixels = cv2.imread(str(preview), cv2.IMREAD_GRAYSCALE)
    assert pixels.shape == (240, 600)
    assert np.count_nonzero(pixels[45:105, 35:185] < 192) > 100
    assert np.count_nonzero(pixels[135:185, 265:575] < 192) > 200


@pytest.mark.parametrize("many_vertices", [False, True])
def test_late_contact_paths_receive_circle_relations_and_keep_the_original_plan(tmp_path, many_vertices):
    from app.native_objects.circular_markers import discover_circular_markers
    from app.native_objects.circle_endpoint_contacts import restore_circle_endpoint_contacts

    gray = _contact_source()
    if many_vertices:
        gray = np.full((240, 420), 255, np.uint8)
        for center in ((60, 170), (360, 170)):
            cv2.circle(gray, center, 13, 0, 2)
        xs = np.arange(72, 349)
        ys = 85 + 80 * ((xs - 210) / 138) ** 2
        outside_text = ((xs > 84) & (xs < 140)) | ((xs > 270) & (xs < 336))
        ys += np.where(outside_text, 5 * np.sin((xs - 84) * 2 * np.pi / 12), 0)
        cv2.polylines(gray, [np.rint(np.column_stack((xs, ys))).astype(np.int32)], False, 0, 2)
        cv2.putText(gray, "AX7", (160, 107), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2, cv2.LINE_8)
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    markers = [{
        "id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
        "geometry": deepcopy(row["geometry"]), "bbox_xyxy_px": row["bbox_xyxy_px"],
        "source_evidence": {**deepcopy(row["source_evidence"]), "components_complete": False},
        "status": "PARTIAL_BOUNDARY_ONLY_CHARACTER_PENDING",
    } for row in discover_circular_markers(gray, ROI)["rows"] if row["geometry_accepted"]]
    assert len(markers) == 2
    assert not restore_circle_endpoint_contacts(gray, ROI, markers)["replacements"]
    root = tmp_path / "evidence"
    plan = plan_text_contact_geometry(gray, ROI, SEED)
    contact = complete_text_contact_paths(gray, ROI, source_sha, markers, [plan], root / "text_contact")
    original_plan = deepcopy(contact)
    assert len(contact["objects"]) == 1
    if many_vertices:
        assert len(contact["objects"][0]["geometry"]["points"]) > 48
        unproved = deepcopy(contact["objects"][0])
        unproved["source_evidence"].pop("text_contact_path")
        refused = restore_circle_endpoint_contacts(gray, ROI, markers + [unproved])
        assert not refused["replacements"]
        assert any(row["reason"] == "EXISTING_NATIVE_VERTEX_BUDGET_MUST_REMAIN_UNCHANGED"
                   for row in refused["decisions"])
    completion = {"objects": markers, "uncertainties": [], "decisions": [], "summary": {}}
    objects, reviewed = pipeline._finalize_circle_relations(
        gray, ROI, markers + contact["objects"], completion, root / "circular_markers",
    )
    assert reviewed["external_endpoint_contacts"]["summary"]["restored_external_endpoints"] == 2
    assert contact == original_plan
    second, repeated = pipeline._finalize_circle_relations(
        gray, ROI, objects, reviewed, root / "circular_markers",
    )
    assert second == objects and repeated == reviewed
    path = tmp_path / "late-contacts.dxf"
    export_objects(objects, path, ROI, 200, source_sha)
    report = cold_audit(path, gray, ROI, 200, root / "cold_audit.json")
    assert report["source_gate_pass"], report["source_checks"]
    assert report["text_contact_source_checks"]["pass"]
    assert all(row["pass"] for row in report["circle_endpoint_contact_checks"])
    assert not report["exact_duplicate_segments"]


def test_assembly_receipt_restoration_recovers_same_actual_cold_proof(mixed_saved):
    path, _, _, result, _ = mixed_saved
    root = path.parent / "evidence"
    receipt = root / "text_contact/adoption.json"
    bound = deepcopy(result)
    receipt.unlink()
    missing = _whole_audit(mixed_saved)
    assert not missing["source_gate_pass"]
    assert not missing["text_contact_source_checks"]["pass"]
    pipeline._restore_text_contact_evidence(root, bound)
    assert json.loads(receipt.read_text()) == bound
    restored = _whole_audit(mixed_saved)
    assert restored["source_gate_pass"], restored
    assert restored["text_contact_source_checks"]["pass"]
    pipeline._restore_text_contact_evidence(root, bound)
    different = deepcopy(bound)
    different["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="RECEIPT_ALREADY_DIFFERS"):
        pipeline._restore_text_contact_evidence(root, different)
    assert json.loads(receipt.read_text()) == bound


def test_foreign_numeric_edge_ids_never_override_actual_source_adjacencies(mixed_saved):
    path, _, _, result, old = mixed_saved
    metadata_path = path.with_suffix(".objects.json")
    receipt_path = path.parent / "evidence/text_contact/adoption.json"
    oid = result["objects"][0]["id"]
    # An earlier producer serialized its local edge IDs at this legacy-looking
    # field. Its complete, independently replayed contact proof still binds
    # another source path; the unscoped legacy graph may reuse every integer.
    for bound_path in (metadata_path, receipt_path):
        bound = json.loads(bound_path.read_text())
        other = next(row for row in bound["objects"] if row["id"] == oid)
        other["source_evidence"]["source_graph_edge_ids"] = deepcopy(
            old["source_evidence"]["source_graph_edge_ids"]
        )
        save_json(bound_path, bound)
    report = _whole_audit(mixed_saved)
    assert report["source_gate_pass"], report
    assert report["text_contact_source_checks"]["pass"]
    assert report["same_owner_retrace_cold_proof"]["evidence_status"] == "COMPLETE_COLD_PROOF"
    assert not report["exact_duplicate_segments"]


def test_legacy_owner_must_still_bind_its_own_numeric_ids_to_its_raw_graph(mixed_saved):
    path, _, _, _, old = mixed_saved
    metadata_path = path.with_suffix(".objects.json")
    metadata = json.loads(metadata_path.read_text())
    owner = next(row for row in metadata["objects"] if row["id"] == old["id"])
    owner["source_evidence"]["source_graph_edge_ids"] = [999999]
    save_json(metadata_path, metadata)
    report = _whole_audit(mixed_saved)
    assert not report["source_gate_pass"]
    proof = report["same_owner_retrace_cold_proof"]
    assert not proof["allowances"]
    assert any(not row["pass"] for row in proof["object_checks"])


def test_empty_contact_stage_creates_no_receipt_and_bad_schema_is_rejected(tmp_path):
    pipeline._restore_text_contact_evidence(tmp_path, {})
    assert not (tmp_path / "text_contact/adoption.json").exists()
    with pytest.raises(ValueError, match="RECEIPT_SCHEMA_CHANGED"):
        pipeline._restore_text_contact_evidence(tmp_path, {"schema": "changed"})


@pytest.mark.parametrize("mode", ["missing", "empty", "white_gap", "same_source_other_graph"])
def test_legacy_retrace_cannot_ignore_unknown_or_reowned_source_in_another_graph(
    mixed_saved, mode
):
    path, _, _, result, old = mixed_saved
    metadata_path = path.with_suffix(".objects.json")
    metadata = json.loads(metadata_path.read_text())
    other = next(row for row in metadata["objects"] if row["id"] == result["objects"][0]["id"])
    source = other["source_evidence"]
    if mode == "missing":
        source.pop("source_path_points")
    elif mode == "empty":
        source["source_path_points"] = []
    elif mode == "white_gap":
        source["source_path_points"] = [[270, 140], [272, 140]]
    else:
        source["source_path_points"] = deepcopy(old["source_evidence"]["source_path_points"])
        # These deliberately unrelated IDs cannot hide real shared source.
        source["source_graph_edge_ids"] = [999999]
    save_json(metadata_path, metadata)
    report = _whole_audit(mixed_saved)
    assert not report["source_gate_pass"]
    proof = report["same_owner_retrace_cold_proof"]
    assert not proof["allowances"]
    assert any(not row["pass"] for row in proof["object_checks"])
    if mode == "same_source_other_graph":
        assert "SOURCE_GRAPH_ADJACENCY_HAS_ANOTHER_FORMAL_PATH_OWNER" in str(proof)


def test_contact_stage_keeps_plans_and_binds_all_reused_implementation_dependencies(
    tmp_path, monkeypatch
):
    gray, roi, texts, _ = _stage(tmp_path)
    sentinel = {"schema": "integration-plan-sentinel", "source_unchanged": True}
    calls = []

    def refine(source, observations, output_dir, **kwargs):
        calls.append(kwargs)
        assert np.array_equal(source, gray)
        result = deepcopy(observations)
        result["text_contact_geometry_plans"] = [sentinel]
        return result

    monkeypatch.setattr(single_line_labels, "refine_single_line_labels", refine)
    monkeypatch.setattr(pipeline, "checkpoint_artifact", lambda *_: None)
    result = pipeline._complete_single_line_stage(
        gray, texts, tmp_path, "a" * 64, roi, 200, lambda *_: None
    )
    manifest_path = tmp_path / "completed_stages.json"
    manifest = json.loads(manifest_path.read_text())
    dependencies = manifest["text"]["dependency_producers"]
    required = (
        "text_contact_geometry", "text_contact_partition", "connections",
        "connection_core_routes", "text_graph_support",
        "single_line_neighbor_clearance", "single_line_text_audit", "circular_markers",
    )
    for name in required:
        assert dependencies["app.native_objects." + name] == _producer(name)
    restored, binding = pipeline._completed_text_checkpoint(
        tmp_path, "a" * 64, roi, gray.shape, texts["source_array_sha256"]
    )
    assert restored == result and restored["text_contact_geometry_plans"] == [sentinel]
    assert binding["new_OCR_calls"] == 0
    pipeline._complete_single_line_stage(
        gray, restored, tmp_path, "a" * 64, roi, 200, lambda *_: None
    )
    assert len(calls) == 1
    for name in required:
        changed = deepcopy(manifest)
        changed["text"]["dependency_producers"]["app.native_objects." + name] = "0" * 64
        save_json(manifest_path, changed)
        with pytest.raises(ValueError, match="COMPLETED_TEXT_DEPENDENCY_CHANGED"):
            pipeline._completed_text_checkpoint(
                tmp_path, "a" * 64, roi, gray.shape, texts["source_array_sha256"]
            )
    save_json(manifest_path, manifest)
    names = revision_resume._revision_producer_names(manifest["text"])
    assert set(revision_resume._TEXT_CONTACT_PRODUCERS) <= set(names)
    producers = {"app.native_objects." + name: _producer(name) for name in names}
    revision_resume._producer_checks(producers)


def test_revision_contact_pair_is_complete_source_bound_and_optional_for_old_stages():
    row = {
        "producer_module": "app.native_objects.single_line_labels",
        "dependency_producers": {},
    }
    old_names = revision_resume._revision_producer_names(row)
    assert not set(revision_resume._TEXT_CONTACT_PRODUCERS) & set(old_names)
    old = {"app.native_objects." + name: _producer(name) for name in old_names}
    revision_resume._producer_checks(old)
    contact = {
        "app.native_objects." + name: _producer(name)
        for name in revision_resume._TEXT_CONTACT_PRODUCERS
    }
    revision_resume._producer_checks({**old, **contact})
    for name in contact:
        incomplete = {**old, **contact}
        incomplete.pop(name)
        with pytest.raises(ValueError, match="TEXT_CONTACT_PRODUCER_SET_INCOMPLETE"):
            revision_resume._producer_checks(incomplete)
        changed = {**old, **contact, name: "0" * 64}
        with pytest.raises(ValueError):
            revision_resume._producer_checks(changed)

