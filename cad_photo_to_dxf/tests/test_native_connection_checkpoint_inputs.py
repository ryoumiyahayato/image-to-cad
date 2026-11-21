"""Real captured files protect bounded jobs from stale or mutable inputs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import ezdxf
import numpy as np
from PIL import Image, ImageDraw
import pytest

from app.native_objects.connection_checkpoint_inputs import (
    capture_checkpoint,
    load_captured_checkpoint,
    verify_captured_checkpoint,
)


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _asset(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checkpoint_fixture(tmp_path):
    """One actual source stroke, one marked old LINE, and no OCR observations."""
    original = tmp_path / "original"
    original.mkdir()
    source_path = original / "source.png"
    image = Image.new("L", (40, 30), 255)
    ImageDraw.Draw(image).line([(8, 8), (24, 13)], fill=0, width=1)
    image.save(source_path)
    source_sha = _asset(source_path)["sha256"]
    array_sha = hashlib.sha256(np.asarray(image).tobytes()).hexdigest()
    roi = [0, 0, 40, 30]
    parameters = {
        "roi": roi, "dpi": 200, "orientation": 0,
        "page_number": None, "frame_number": None, "language": "eng",
    }
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.layers.new("GEOMETRY")
    doc.appids.new("I2CAD_NATIVE_V2")
    old = {
        "id": "old-line", "kind": "LINE", "layer": "GEOMETRY",
        "geometry": {"start": [8, 8], "end": [24, 13]},
        "source_evidence": {"method": "synthetic_fixture_source_stroke"},
    }
    entity = doc.modelspace().add_line(
        (8 * 0.127, 22 * 0.127), (24 * 0.127, 17 * 0.127),
        dxfattribs={"layer": "GEOMETRY"},
    )
    entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": old["id"], "kind": old["kind"]}))])
    dxf_path = original / "old.dxf"
    doc.saveas(dxf_path)
    ownership = {
        "source_sha256": source_sha,
        "dxf_sha256": _asset(dxf_path)["sha256"],
        "roi_xyxy_px": roi, "dpi": 200, "unit": "paper_mm",
        "objects": [old],
        "written": [{"id": old["id"], "kind": old["kind"], "type": "LINE", "handle": entity.dxf.handle, "block_members": []}],
    }
    ownership_path = original / "ownership.json"
    _write_json(ownership_path, ownership)
    texts = {
        "schema": "native_text_regions_v2", "schema_version": 2,
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [40, 30], "roi_xyxy_px": roi,
        "source_array_sha256": array_sha, "regions": [], "groups": [],
        "uncertainties": [], "source_pixels_modified": False,
    }
    texts_path = original / "texts.json"
    _write_json(texts_path, texts)
    manifest = {
        "schema": "native-connection-checkpoint-v1",
        "source_sha256": source_sha, "roi_xyxy_px": roi, "dpi": 200,
        "baseline_dxf": _asset(dxf_path),
        "baseline_ownership": _asset(ownership_path),
        "text_observations": _asset(texts_path),
        "windows": [{"id": "report-label", "target_roi": [6, 5, 29, 20], "context_roi": [2, 2, 32, 26]}],
    }
    manifest_path = original / "request.json"
    _write_json(manifest_path, manifest)
    job = tmp_path / "job"
    (job / "inputs").mkdir(parents=True)
    shutil.copyfile(source_path, job / "inputs" / "source.png")
    return manifest_path, job, source_sha, parameters


def test_capture_survives_original_removal_without_overwriting_prior_capture(tmp_path):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    binding = capture_checkpoint(request, job, source_sha, parameters)
    second = capture_checkpoint(request, job, source_sha, parameters)
    assert binding["capture_directory"] != second["capture_directory"]
    shutil.rmtree(request.parent)
    manifest, ownership, texts, dxf = load_captured_checkpoint(binding)
    assert dxf.is_file() and str(dxf).startswith(str(job / "inputs" / "connection_checkpoint"))
    assert manifest["windows"][0]["id"] == "report-label"
    assert ownership["objects"][0]["id"] == "old-line"
    assert texts["source_array_sha256"] == binding["source_array_sha256"]
    assert verify_captured_checkpoint(binding, job, source_sha, parameters) is binding


@pytest.mark.parametrize("asset_name", ["manifest", "original_manifest", "baseline_dxf", "baseline_ownership", "text_observations"])
def test_changed_captured_file_is_rejected(tmp_path, asset_name):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    binding = capture_checkpoint(request, job, source_sha, parameters)
    path = Path(binding[asset_name]["path"])
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="ASSET_HASH_MISMATCH"):
        verify_captured_checkpoint(binding, job, source_sha, parameters)


def test_same_bytes_outside_task_and_modified_parameters_are_rejected(tmp_path):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    binding = capture_checkpoint(request, job, source_sha, parameters)
    outside = tmp_path / "outside.dxf"
    shutil.copyfile(binding["baseline_dxf"]["path"], outside)
    escaped = deepcopy(binding)
    escaped["baseline_dxf"]["path"] = str(outside)
    with pytest.raises(ValueError, match="PATH_OUTSIDE_CAPTURE"):
        load_captured_checkpoint(escaped)
    changed_parameters = {**parameters, "orientation": 90}
    with pytest.raises(ValueError, match="CAPTURE_PARAMETERS_MISMATCH"):
        verify_captured_checkpoint(binding, job, source_sha, changed_parameters)
    with pytest.raises(ValueError, match="ONLY_UNROTATED_SOURCE_FRAME_SUPPORTED"):
        capture_checkpoint(request, job, source_sha, changed_parameters)


@pytest.mark.parametrize("invalid", ["outside", "union_full_region", "unknown_ocr_option"])
def test_input_scope_cannot_expand_to_full_conversion(tmp_path, invalid):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    manifest = json.loads(request.read_text())
    if invalid == "outside":
        manifest["windows"][0]["target_roi"] = [0, 0, 40, 30]
    elif invalid == "union_full_region":
        manifest["windows"] = [
            {"id": "left", "target_roi": [0, 0, 20, 30], "context_roi": [0, 0, 20, 30]},
            {"id": "right", "target_roi": [20, 0, 40, 30], "context_roi": [20, 0, 40, 30]},
        ]
    else:
        manifest["auto_ocr"] = True
    _write_json(request, manifest)
    with pytest.raises(ValueError, match="CONNECTION_CHECKPOINT_"):
        capture_checkpoint(request, job, source_sha, parameters)


@pytest.mark.parametrize("invalid", ["duplicate_id", "wrong_kind", "missing_geometry", "wrong_text_source", "wrong_text_size"])
def test_matching_file_hashes_do_not_replace_source_and_entity_validation(tmp_path, invalid):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    manifest = json.loads(request.read_text())
    name = "text_observations" if invalid.startswith("wrong_text") else "baseline_ownership"
    path = Path(manifest[name]["path"])
    payload = json.loads(path.read_text())
    if invalid == "duplicate_id":
        payload["objects"].append(deepcopy(payload["objects"][0]))
    elif invalid == "wrong_kind":
        payload["objects"][0]["kind"] = "TEXT"
        payload["written"][0]["kind"] = "TEXT"
    elif invalid == "missing_geometry":
        del payload["objects"][0]["geometry"]
    elif invalid == "wrong_text_source":
        payload["source_array_sha256"] = "a" * 64
    else:
        payload["source_size_px"] = [400, 300]
    _write_json(path, payload)
    manifest[name] = _asset(path)
    _write_json(request, manifest)
    with pytest.raises(ValueError, match="CONNECTION_CHECKPOINT_|TEXT_REGION_"):
        capture_checkpoint(request, job, source_sha, parameters)


def test_changed_source_file_is_rejected_even_with_intact_checkpoint(tmp_path):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    binding = capture_checkpoint(request, job, source_sha, parameters)
    Image.new("L", (40, 30), 128).save(job / "inputs" / "source.png")
    with pytest.raises(ValueError, match="CAPTURED_SOURCE_HASH_MISMATCH"):
        load_captured_checkpoint(binding)


def test_capture_directory_symlink_cannot_move_inputs_outside_job(tmp_path):
    request, job, source_sha, parameters = checkpoint_fixture(tmp_path)
    binding = capture_checkpoint(request, job, source_sha, parameters)
    original = job / "inputs" / "connection_checkpoint"
    moved = tmp_path / "moved-checkpoint"
    original.rename(moved)
    try:
        original.symlink_to(moved, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable in this test environment")
    with pytest.raises(ValueError, match="PATH_OUTSIDE_CAPTURE"):
        verify_captured_checkpoint(binding, job, source_sha, parameters)
