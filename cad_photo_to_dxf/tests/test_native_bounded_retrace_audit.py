"""Per-window raw proofs keep parent CAD coordinates and all source gates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects.cad_io import cold_audit, export_objects, mark
from app.native_objects.connections import extract_connections


ROI = (0, 0, 500, 200)
DPI = 200


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path, data):
    Path(path).write_text(json.dumps(data, indent=2))


@pytest.fixture(scope="module")
def bounded_template(tmp_path_factory, native_geometry_export_context):
    folder = tmp_path_factory.mktemp("two-discovery-scopes")
    ink = np.zeros((200, 500), np.uint8)
    for offset in ((10, 20), (260, 20)):
        ox, oy = offset
        for x, y in ((25, 90), (195, 90)):
            cv2.circle(ink, (x + ox, y + oy), 12, 1, 1)
        for points in (
            [(37, 90), (65, 69), (90, 63), (109, 60)],
            [(111, 60), (130, 63), (155, 69), (183, 90)],
        ):
            cv2.polylines(
                ink, [np.asarray(points, np.int32) + offset], False, 1, 1
            )
        cv2.rectangle(ink, (109 + ox, 59 + oy), (111 + ox, 61 + oy), 1, 1)
    gray = np.where(ink, 0, 255).astype(np.uint8)
    objects, scopes = [], []
    for index, roi in enumerate(([10, 20, 230, 180], [260, 20, 480, 180])):
        relative = Path(f"connections/scopes/{index:03d}/discovery")
        out = folder / "evidence" / relative
        result = extract_connections(gray, roi, [], out)
        assert len(result["objects"]) == 1
        objects.extend(result["objects"])
        scopes.append(
            {
                "roi_xyxy_px": roi,
                "graph_path": (relative / "source_graph.json").as_posix(),
                "graph_sha256": _sha(out / "source_graph.json"),
                "discovery_path": (relative / "connections.json").as_posix(),
                "discovery_sha256": _sha(out / "connections.json"),
                "object_ids": [obj["id"] for obj in result["objects"]],
            }
        )
    with native_geometry_export_context(objects):
        export_objects(
            objects, folder / "result.dxf", ROI, DPI,
            hashlib.sha256(gray.tobytes()).hexdigest(),
        )
    metadata = json.loads((folder / "result.objects.json").read_text())
    metadata["connection_discovery_scopes"] = scopes
    _save(folder / "result.objects.json", metadata)
    return folder, gray


@pytest.fixture
def bounded_case(bounded_template, tmp_path):
    folder, gray = bounded_template
    shutil.copytree(folder, tmp_path, dirs_exist_ok=True)
    return tmp_path, gray.copy()


def _audit(case):
    folder, gray = case
    return cold_audit(
        folder / "result.dxf", gray, ROI, DPI, folder / "evidence/cold_audit.json"
    )


def test_two_graph_namespaces_use_parent_cad_coordinates_and_actual_local_proofs(
    bounded_case,
):
    folder, gray = bounded_case
    before = gray.copy()
    metadata = json.loads((folder / "result.objects.json").read_text())
    first, second = metadata["objects"]
    # Local numeric IDs repeat, while the real paths occupy different ink.
    assert set(first["source_evidence"]["source_graph_edge_ids"]) & set(
        second["source_evidence"]["source_graph_edge_ids"]
    )
    report = _audit(bounded_case)
    assert report["source_gate_pass"]
    assert not report["exact_duplicate_segments"]
    assert len(report["certified_same_owner_retraces"]) == 8
    proof = report["same_owner_retrace_cold_proof"]
    assert proof["evidence_status"] == "COMPLETE_COLD_PROOF"
    assert proof["CAD_parent_roi_xyxy_px"] == list(ROI)
    assert {r["discovery_scope_index"] for r in proof["object_checks"]} == {0, 1}
    assert all(r["pass"] for r in proof["object_checks"])
    assert np.array_equal(gray, before)
    assert not (folder / "evidence/connections/discovery/source_graph.json").exists()


@pytest.mark.parametrize("change", ["missing_owner", "duplicate_owner", "wrong_roi", "wrong_hash", "path_escape"])
def test_scope_mapping_is_not_a_retrace_allowlist(bounded_case, change):
    folder, _ = bounded_case
    path = folder / "result.objects.json"
    meta = json.loads(path.read_text())
    scopes = meta["connection_discovery_scopes"]
    if change == "missing_owner":
        scopes[0]["object_ids"] = []
    elif change == "duplicate_owner":
        scopes[1]["object_ids"].append(scopes[0]["object_ids"][0])
    elif change == "wrong_roi":
        scopes[0]["roi_xyxy_px"] = list(ROI)
    elif change == "wrong_hash":
        scopes[0]["discovery_sha256"] = "0" * 64
    else:
        scopes[0]["graph_path"] = "../outside.json"
    _save(path, meta)
    report = _audit(bounded_case)
    assert not report["source_gate_pass"]
    assert report["exact_duplicate_segments"]
    proof = report["same_owner_retrace_cold_proof"]
    assert any(not row["pass"] for row in proof["object_checks"])
    assert not any(
        row["id"] == meta["objects"][0]["id"] for row in proof["allowances"]
    )


def test_bound_per_window_graph_still_checks_current_original_pixels(bounded_case):
    folder, gray = bounded_case
    graph = folder / "evidence/connections/scopes/000/discovery/source_graph.json"
    original = graph.read_bytes()
    gray[15, 15] = 0  # In this raw crop, away from the actual path geometry.
    report = _audit(bounded_case)
    assert not report["source_gate_pass"]
    proof = report["same_owner_retrace_cold_proof"]
    assert "RAW_SOURCE_GRAPH_CURRENT_IMAGE_BINDING_MISMATCH" in str(proof)
    assert graph.read_bytes() == original


def test_cross_scope_source_ownership_uses_real_adjacencies_not_local_ids(bounded_case):
    folder, _ = bounded_case
    path = folder / "result.objects.json"
    meta = json.loads(path.read_text())
    other = deepcopy(meta["objects"][0])
    other["id"] = "another-formal-source-owner"
    other["source_evidence"]["crossing_evidence"] = []
    # A retained path need not have a current discovery scope. Its observed
    # source ownership must still prevent this cell receiving a second owner.
    other["source_evidence"]["source_graph_edge_ids"] = [999999]
    meta["objects"].append(other)
    dxf_path = folder / "result.dxf"
    doc = ezdxf.readfile(dxf_path)
    original = next(e for e in doc.modelspace() if e.dxf.handle == meta["written"][0]["handle"])
    copied = original.copy()
    doc.modelspace().add_entity(copied)
    mark(copied, other)
    doc.saveas(dxf_path)
    meta["dxf_sha256"] = _sha(dxf_path)
    meta["written"].append(
        {**meta["written"][0], "id": other["id"], "handle": copied.dxf.handle}
    )
    _save(path, meta)
    report = _audit(bounded_case)
    assert not report["source_gate_pass"]
    proof = report["same_owner_retrace_cold_proof"]
    assert "SOURCE_GRAPH_ADJACENCY_HAS_ANOTHER_FORMAL_PATH_OWNER" in str(proof)
    assert not any(row["id"] == meta["objects"][0]["id"] for row in proof["allowances"])
