"""Managed optional raw evidence and old paths stay bound through publication."""

import hashlib
import json
import os
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import pytest

from app.core import native_job_manager
from app.core.native_objects_entry import dispatch_native_objects
from app.core.native_worker import _saved_candidate_gates, _validate_request
from app.native_objects import connection_checkpoint, pipeline
from app.native_objects.checkpoint_baseline import compose_checkpoint_baseline
from app.native_objects.checkpoint_text_observations import BoundObservations, SCHEMA
from app.native_objects.contracts import save_json
from app.native_objects.execution import file_sha
from app.native_objects.observation_cache import ENVIRONMENT_VARIABLE
from app.native_objects.review_binding import verify_saved_review
from tests.test_native_checkpoint_baseline import DPI, ROI, _pair


LOCAL_CONTEXT = [10, 180, 235, 210]


def _asset(path):
    return {"path": str(path), "sha256": file_sha(path)}


def _managed(tmp_path, monkeypatch, cycle=False):
    pair = _pair(tmp_path / "author", cycle)
    composed = compose_checkpoint_baseline(**pair, output_path=tmp_path / "composed/baseline.dxf")
    with Image.open(pair["source_path"]) as image:
        gray = np.array(image.convert("L"))
    texts = tmp_path / "author/texts.json"
    save_json(texts, {"schema": "native_text_regions_v2", "schema_version": 2,
                      "coordinate_system": "source_pixels_top_left", "source_size_px": ROI[2:],
                      "roi_xyxy_px": ROI, "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                      "regions": [], "groups": [], "uncertainties": []})
    crop_box = [10, 10, 40, 35]
    crop = gray[10:35, 10:40]
    raw = tmp_path / "author/empty-observation.tsv"
    raw.write_text("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
    Image.fromarray(crop).save(raw.with_suffix(".png"))
    save_json(raw.with_suffix(".json"), {
        "status": "COMPLETED", "return_code": 0,
        "specification": {"crop_xyxy_px": crop_box, "crop_array_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
                          "psm": 7, "pixel_scale": [1, 1], "source_pixels_modified": False,
                          "language": "eng", "recognition_dpi": DPI, "external_white_padding_px": 0,
                          "padding_replaces_source_pixels": False},
        "tsv_sha256": file_sha(raw), "image_sha256": file_sha(raw.with_suffix(".png")),
        "engine_version": "tesseract historical-test",
        "command": ["tesseract", "unchanged-crop.png", "stdout", "--psm", "7", "--dpi", str(DPI), "-l", "eng", "--oem", "1", "tsv"],
    })
    observations = tmp_path / "author/raw-manifest.json"
    save_json(observations, {"schema": SCHEMA, "source_sha256": file_sha(pair["source_path"]),
                            "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                            "roi_xyxy_px": ROI, "dpi": DPI, "observations": [{
                                "region_id": "empty-control", **{
                                    key: {"path": raw.with_suffix(suffix).name, "sha256": file_sha(raw.with_suffix(suffix))}
                                    for key, suffix in (("tsv", ".tsv"), ("meta", ".json"), ("png", ".png"))}}]})
    manifest = tmp_path / "author/checkpoint.json"
    save_json(manifest, {"schema": "native-connection-checkpoint-v1",
                        "source_sha256": file_sha(pair["source_path"]), "roi_xyxy_px": ROI, "dpi": DPI,
                        **{key: composed[key] for key in ("baseline_dxf", "baseline_ownership", "baseline_evidence")},
                        "text_observations": _asset(texts), "source_observations": _asset(observations),
                        "windows": [{"id": "new-local-scope", "target_roi": [20, 185, 220, 195], "context_roi": LOCAL_CONTEXT}]})
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    manager = native_job_manager.NativeJobManager(tmp_path / "jobs")
    state = manager.create(input_path=pair["source_path"], roi=ROI, dpi=DPI,
                           job_id="continued", connection_checkpoint=manifest)

    def no_process(*args, **kwargs):
        raise OSError("request inspection before process launch")

    monkeypatch.setattr(native_job_manager.subprocess, "Popen", no_process)
    with pytest.raises(OSError, match="request inspection"):
        manager.start(state["job_id"])
    request_path = tmp_path / "jobs/continued/attempts/0001/request.json"
    request = json.loads(request_path.read_text())
    request["parent_pid"] = os.getppid()
    save_json(request_path, request)
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, request["raw_observation_cache"]["root"])
    shutil.rmtree(tmp_path / "author")
    shutil.rmtree(tmp_path / "composed")
    assert not (tmp_path / "author").exists() and not (tmp_path / "composed").exists()
    return request_path, composed


@pytest.mark.parametrize("cycle", [False, True], ids=["preserve-complete-path", "reprove-local-cycle"])
def test_formal_dispatch_preserves_prior_path_outside_new_scope_without_ocr(tmp_path, monkeypatch, cycle):
    request_path, composed = _managed(tmp_path, monkeypatch, cycle)
    request = _validate_request(request_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Continuation must not call OCR or scan old author directories")

    monkeypatch.setattr(pipeline, "extract_text_regions", forbidden)
    for method in ("request", "request_model", "scan"):
        monkeypatch.setattr(BoundObservations, method, forbidden)
    calls = []
    original = connection_checkpoint.extract_connections

    def observed_extract(*args, **kwargs):
        calls.append(list(args[1]))
        assert kwargs["verified_text_observations"]["validated"] is True
        assert kwargs["verified_text_observations"]["observations"][0]["words"] == []
        return original(*args, **kwargs)

    monkeypatch.setattr(connection_checkpoint, "extract_connections", observed_extract)
    staging = Path(request["staging_directory"])
    result = dispatch_native_objects(request["input_path"], staging / "result.dxf", ROI, dpi=DPI,
                                     evidence_dir=staging / "evidence",
                                     connection_checkpoint=request["connection_checkpoint"])
    assert calls == [LOCAL_CONTEXT]
    assert result["new_complete_path_ids"] == []
    assert result["preserved_prior_delta_path_ids"] == composed["protected_object_ids"]
    assert result["verified_raw_text_observations"] == 1
    assert result["new_OCR_calls"] == result["full_region_conversion_runs"] == 0
    gates = _saved_candidate_gates(staging, request)
    assert gates["formal_entities"] == {"LINE": 1, "LWPOLYLINE": 1}
    quality = json.loads((staging / "evidence/quality_review.json").read_text())
    assert quality["review_scope"]["context_rois"] == [LOCAL_CONTEXT]
    assert quality["review_scope"]["full_parent_region_review_performed"] is False
    if cycle:
        cold = json.loads((staging / "evidence/cold_audit.json").read_text())
        assert cold["same_owner_retrace_cold_proof"]["evidence_status"] == "COMPLETE_COLD_PROOF"
    # Raw evidence is part of this saved review, including after capture and
    # after the entire author directory has been removed.
    copied_raw = next((staging / "evidence/source_observations").glob("*.tsv"))
    copied_raw.write_bytes(copied_raw.read_bytes() + b"\n")
    meta = json.loads((staging / "result.objects.json").read_text())
    imported = json.loads((staging / "evidence/import_manifest.json").read_text())
    assert not verify_saved_review(staging / "evidence/quality_review.json", staging / "result.dxf",
                                   meta["objects"], imported, source_path=request["input_path"])["valid"]


@pytest.mark.parametrize("damage", ["raw-tsv", "old-graph", "retirement-report", "missing-optional-binding"])
def test_worker_rejects_changed_captured_optional_evidence(tmp_path, monkeypatch, damage):
    request_path, _ = _managed(tmp_path, monkeypatch)
    request = json.loads(request_path.read_text())
    binding = request["connection_checkpoint"]
    if damage == "missing-optional-binding":
        binding.pop("source_observations")
        save_json(request_path, request)
    else:
        name = "source_observations" if damage == "raw-tsv" else "baseline_evidence"
        asset = binding[name]
        root = Path(asset["path"]).parent
        manifest = json.loads(Path(asset["path"]).read_text())
        if damage == "raw-tsv":
            target = root / manifest["observations"][0]["tsv"]["path"]
        elif damage == "old-graph":
            target = root / manifest["discovery_scopes"][0]["graph"]["path"]
        else:
            target = root / manifest["parents"]["delta_report"]["path"]
        target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="HASH_MISMATCH|OPTIONAL_CAPTURE_ASSET_SET_MISMATCH"):
        _validate_request(request_path)
