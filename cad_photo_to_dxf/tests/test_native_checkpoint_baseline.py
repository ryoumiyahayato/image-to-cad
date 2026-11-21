"""Saved native deltas compose without losing old objects or source proofs."""

from copy import deepcopy
import json
from pathlib import Path
import shutil

import cv2
import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects import cad_io
from app.native_objects.checkpoint_baseline import (
    capture_baseline_evidence,
    compose_checkpoint_baseline,
    verify_baseline_evidence,
)
from app.native_objects.connection_checkpoint import adopt_checkpoint_paths
from app.native_objects.connection_checkpoint_cad import _entity, write_checkpoint_dxf
from app.native_objects.connections import extract_connections
from app.native_objects.contracts import save_json
from app.native_objects.execution import file_sha


ROI = [0, 0, 240, 220]
CONTEXT = [5, 5, 225, 200]
DPI = 200


def _asset(path):
    return {"path": str(path), "sha256": file_sha(path)}


def _pair(directory, cycle=False):
    directory.mkdir()
    gray = np.full((ROI[3], ROI[2]), 255, np.uint8)
    gray[190, 15:231] = 0
    objects = [{"id": "old-correct-neighbor", "kind": "LINE", "layer": "GEOMETRY",
                "geometry": {"start": [15, 190], "end": [230, 190]},
                "source_evidence": {"method": "known_original_stroke"}}]
    if cycle:
        for x in (25, 195):
            cv2.circle(gray, (x, 90), 12, 0, 1)
        for points in ([[37, 90], [65, 69], [90, 63], [109, 60]],
                       [[111, 60], [130, 63], [155, 69], [183, 90]]):
            cv2.polylines(gray, [np.asarray(points, np.int32)], False, 0, 1)
        cv2.rectangle(gray, (109, 59), (111, 61), 0, 1)
    else:
        cv2.polylines(gray, [np.asarray([[30, 80], [75, 80], [105, 60], [135, 60], [170, 80]], np.int32)], False, 0, 1)
        objects.append({"id": "old-incomplete-line", "kind": "LINE", "layer": "GEOMETRY",
                        "geometry": {"start": [40, 80], "end": [70, 80]},
                        "source_evidence": {"method": "known_partial_original_stroke"}})
    source = directory / "source.png"
    Image.fromarray(gray).save(source, dpi=(DPI, DPI))
    primary = directory / "primary.dxf"
    meta = cad_io.export_objects(objects, primary, ROI, DPI, file_sha(source))
    evidence = directory / "evidence"
    local = evidence / "connections/scopes/000/discovery"
    discovery = extract_connections(gray, CONTEXT, objects, local)
    adopted = adopt_checkpoint_paths(gray, discovery["objects"], objects)
    assert len(adopted["objects"]) == 1
    retained = {row["id"] for row in objects} - set(adopted["retired_ids"])
    delta = directory / "delta.dxf"
    delta_meta = write_checkpoint_dxf(primary, meta, retained, adopted["objects"],
                                      delta, ROI, DPI, file_sha(source), evidence_directory=evidence)
    delta_meta["connection_discovery_scopes"] = [{
        "roi_xyxy_px": CONTEXT, "object_ids": [o["id"] for o in adopted["objects"]],
        "graph_path": "connections/scopes/000/discovery/source_graph.json",
        "graph_sha256": file_sha(local / "source_graph.json"),
        "discovery_path": "connections/scopes/000/discovery/connections.json",
        "discovery_sha256": file_sha(local / "connections.json"),
    }]
    save_json(delta.with_suffix(".objects.json"), delta_meta)
    report = directory / "delta.report.json"
    save_json(report, {"source_sha256": file_sha(source), "render": {"DXF_sha256": file_sha(delta)},
                       "new_complete_path_ids": [o["id"] for o in adopted["objects"]],
                       "preserved_old_object_ids": sorted(retained),
                       "retired_whole_line_ids": adopted["retired_ids"]})
    return {"primary_dxf": primary, "primary_ownership": primary.with_suffix(".objects.json"),
            "delta_dxf": delta, "delta_ownership": delta.with_suffix(".objects.json"),
            "delta_report": report, "delta_evidence_directory": evidence, "source_path": source}


@pytest.fixture
def saved_pair(tmp_path):
    return _pair(tmp_path / "author")


def _compose(pair, tmp_path):
    return compose_checkpoint_baseline(**pair, output_path=tmp_path / "composed/result.dxf")


def _verify(receipt, pair):
    return verify_baseline_evidence(
        receipt["baseline_evidence"], receipt["baseline_dxf"]["path"],
        json.loads(Path(receipt["baseline_ownership"]["path"]).read_text()),
        pair["source_path"], file_sha(pair["source_path"]),
        {"roi": ROI, "dpi": DPI, "orientation": 0},
    )


@pytest.mark.parametrize("cycle", [False, True], ids=["whole-line-replacement", "local-cycle-retrace"])
def test_actual_saved_delta_retains_old_entities_and_reproves_source(tmp_path, cycle):
    pair = _pair(tmp_path / "author", cycle)
    before = {key: file_sha(value) for key, value in pair.items() if Path(value).is_file()}
    receipt = _compose(pair, tmp_path)
    assert receipt["composed_objects"] == 2
    assert receipt["retired_object_ids"] == ([] if cycle else ["old-incomplete-line"])
    assert receipt["OCR_calls"] == receipt["full_region_conversion_runs"] == 0
    assert before == {key: file_sha(pair[key]) for key in before}
    old = next(e for e in ezdxf.readfile(pair["primary_dxf"]).modelspace() if cad_io.identity(e)["id"] == "old-correct-neighbor")
    new = next(e for e in ezdxf.readfile(receipt["baseline_dxf"]["path"]).modelspace() if cad_io.identity(e)["id"] == "old-correct-neighbor")
    assert _entity(old) == _entity(new)
    proof = _verify(receipt, pair)
    if cycle:
        assert proof["cold_retrace_proof"]["evidence_status"] == "COMPLETE_COLD_PROOF"
        assert all(r["pass"] for r in proof["cold_retrace_proof"]["object_checks"])


@pytest.mark.parametrize("damage", ["missing-retirement-report", "missing-whole-certificate", "changed-shared-entity"])
def test_delta_cannot_retire_without_proof_or_change_a_shared_old_object(saved_pair, tmp_path, damage):
    pair = saved_pair
    meta = json.loads(pair["delta_ownership"].read_text())
    report = json.loads(pair["delta_report"].read_text())
    if damage == "missing-retirement-report":
        report["retired_whole_line_ids"] = []
    elif damage == "missing-whole-certificate":
        next(o for o in meta["objects"] if o["kind"] == "CONNECTION_PATH")["source_evidence"].pop("checkpoint_responsibility_resolution")
    else:
        doc = ezdxf.readfile(pair["delta_dxf"])
        next(e for e in doc.modelspace() if cad_io.identity(e)["id"] == "old-correct-neighbor").dxf.color = 3
        doc.saveas(pair["delta_dxf"])
        meta["dxf_sha256"] = report["render"]["DXF_sha256"] = file_sha(pair["delta_dxf"])
    save_json(pair["delta_ownership"], meta)
    save_json(pair["delta_report"], report)
    with pytest.raises(ValueError, match="COMMON_OLD_ENTITY_CHANGED|WHOLE_REPLACEMENT_RECORD_MISSING|RETIRED_IDS_LACK"):
        _compose(pair, tmp_path)


def test_captured_evidence_survives_deleting_the_author_directory(saved_pair, tmp_path):
    receipt = _compose(saved_pair, tmp_path)
    captured = capture_baseline_evidence(receipt["baseline_evidence"], tmp_path / "captured")
    assert captured["sha256"] == receipt["baseline_evidence"]["sha256"]
    source = tmp_path / "captured-source.png"
    shutil.copyfile(saved_pair["source_path"], source)
    shutil.rmtree(tmp_path / "author")
    shutil.rmtree(Path(receipt["baseline_evidence"]["path"]).parent / "parents")
    modified = deepcopy(receipt)
    modified["baseline_evidence"] = captured
    assert _verify(modified, {"source_path": source})["protected_object_ids"] == receipt["protected_object_ids"]


@pytest.mark.parametrize("damage", ["bytes", "crop-hash", "missing-file", "escape", "windows-path"])
def test_original_graph_binding_and_portable_containment_remain_strict(saved_pair, tmp_path, damage):
    receipt = _compose(saved_pair, tmp_path)
    manifest = Path(receipt["baseline_evidence"]["path"])
    data = json.loads(manifest.read_text())
    graph = data["discovery_scopes"][0]["graph"]
    path = manifest.parent / graph["path"]
    if damage == "bytes":
        path.write_text(path.read_text() + " ")
    elif damage == "missing-file":
        path.unlink()
    elif damage == "crop-hash":
        raw = json.loads(path.read_text())
        raw["source_crop_array_sha256"] = "0" * 64
        save_json(path, raw)
        graph["sha256"] = file_sha(path)
        discovery = data["discovery_scopes"][0]["discovery"]
        dp = manifest.parent / discovery["path"]
        value = json.loads(dp.read_text())
        value["source_graph"]["sha256"] = graph["sha256"]
        save_json(dp, value)
        discovery["sha256"] = file_sha(dp)
    else:
        graph["path"] = "../outside.json" if damage == "escape" else "C:\\author\\graph.json"
    save_json(manifest, data)
    receipt["baseline_evidence"] = _asset(manifest)
    with pytest.raises(ValueError, match="BASELINE_CONTINUATION_(ASSET_|RAW_GRAPH_|PORTABLE_)"):
        _verify(receipt, saved_pair)


def test_changed_non_target_entity_in_composed_file_is_rejected(saved_pair, tmp_path):
    receipt = _compose(saved_pair, tmp_path)
    dxf = Path(receipt["baseline_dxf"]["path"])
    doc = ezdxf.readfile(dxf)
    next(e for e in doc.modelspace() if cad_io.identity(e)["id"] == "old-correct-neighbor").dxf.color = 2
    doc.saveas(dxf)
    meta_path = Path(receipt["baseline_ownership"]["path"])
    meta = json.loads(meta_path.read_text())
    meta["dxf_sha256"] = file_sha(dxf)
    save_json(meta_path, meta)
    manifest = Path(receipt["baseline_evidence"]["path"])
    data = json.loads(manifest.read_text())
    data["baseline_dxf_sha256"] = file_sha(dxf)
    save_json(manifest, data)
    receipt["baseline_evidence"] = _asset(manifest)
    with pytest.raises(ValueError, match="PRESERVATION_CHANGED"):
        _verify(receipt, saved_pair)
