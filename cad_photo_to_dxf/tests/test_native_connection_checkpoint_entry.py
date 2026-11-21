"""Bounded connection tasks keep the ordinary managed publication boundary."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path

import ezdxf
from PIL import Image
import pytest

from main import build_parser, run_headless


def test_cli_sends_checkpoint_to_managed_task(tmp_path, monkeypatch):
    from app.core import native_job_manager

    manifest = tmp_path / "source-checkpoint.json"
    seen = []

    class ReachedManager(Exception):
        pass

    class Manager:
        def __init__(self, jobs_root):
            self.jobs_root = jobs_root

        def create(self, request):
            seen.append(request)
            raise ReachedManager

    monkeypatch.setattr(native_job_manager, "NativeJobManager", Manager)
    args = build_parser().parse_args(
        [
            "--headless", "--input", str(tmp_path / "source.png"),
            "--roi", "0", "0", "40", "30", "--dpi", "200",
            "--output", str(tmp_path / "local.dxf"),
            "--connection-checkpoint", str(manifest),
        ]
    )
    with pytest.raises(ReachedManager):
        run_headless(args)
    assert seen[0]["connection_checkpoint"] == manifest
    assert "cache_dir" not in seen[0]
    assert "validation_controls" not in seen[0]


def test_checkpoint_option_is_rejected_by_legacy_entry():
    args = build_parser().parse_args(
        [
            "--headless", "--mode", "legacy", "--input", "unopened.png",
            "--connection-checkpoint", "unopened.json",
        ]
    )
    with pytest.raises(ValueError, match="require --mode native-objects"):
        run_headless(args)


@pytest.mark.parametrize("binding", [None, {"schema": "routing-test-only"}])
def test_service_dispatch_preserves_saved_output_gate(tmp_path, monkeypatch, binding):
    from app.core.processing import ProductionProcessingService
    from app.native_objects import pipeline

    source = tmp_path / "source.png"
    Image.new("L", (40, 30), 255).save(source)
    output = tmp_path / "local.dxf"
    seen = []

    def incomplete_pipeline(input_path, output_path, roi, **kwargs):
        seen.append(kwargs)
        assert Path(input_path) == source
        assert Path(output_path) == output
        assert tuple(roi) == (0, 0, 40, 30)
        assert kwargs["prepared_source"].manifest["source_sha256"]
        # A successful return without saved artifacts must never be accepted.
        return {"objects": []}

    monkeypatch.setattr(pipeline, "run_native_objects", incomplete_pipeline)
    options = {} if binding is None else {"connection_checkpoint": binding}
    with pytest.raises(ValueError, match="Native pipeline returned no dxf_path"):
        ProductionProcessingService.process_native_objects(
            source, output, (0, 0, 40, 30), dpi=200, **options
        )
    if binding is None:
        assert "connection_checkpoint" not in seen[0]
    else:
        assert seen[0]["connection_checkpoint"] is binding
    assert not output.exists()
    trace = json.loads(output.with_suffix(".entry_trace.json").read_text())
    assert trace["status"] == "FAILED_NO_LEGACY_FALLBACK"
    assert trace["legacy_processing_called"] is False
    assert trace.get("connection_checkpoint") == binding


def _checkpoint_inputs(directory):
    """A small real source and empty old DXF, used for boundary tests only."""
    directory.mkdir()
    image = Image.new("L", (40, 30), 255)
    source = directory / "source.png"
    image.save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    roi = [0, 0, 40, 30]
    baseline = directory / "baseline.dxf"
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.saveas(baseline)

    def asset(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def write(name, value):
        path = directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    ownership = write("ownership.json", {
        "source_sha256": source_sha, "dxf_sha256": asset(baseline)["sha256"],
        "roi_xyxy_px": roi, "dpi": 200, "unit": "paper_mm",
        "objects": [], "written": [],
    })
    texts = write("texts.json", {
        "schema": "native_text_regions_v2", "schema_version": 2,
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [40, 30], "roi_xyxy_px": roi,
        "source_array_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "regions": [], "groups": [], "uncertainties": [],
        "source_pixels_modified": False,
    })
    manifest = write("request.json", {
        "schema": "native-connection-checkpoint-v1",
        "source_sha256": source_sha, "roi_xyxy_px": roi, "dpi": 200,
        "baseline_dxf": asset(baseline),
        "baseline_ownership": asset(ownership), "text_observations": asset(texts),
        "windows": [{"id": "boundary-test", "target_roi": [2, 2, 18, 18],
                     "context_roi": [0, 0, 20, 20]}],
    })
    return source, manifest


@pytest.fixture
def managed_checkpoint(tmp_path, monkeypatch):
    from app.core import native_job_manager
    from app.native_objects.observation_cache import ENVIRONMENT_VARIABLE

    source, manifest = _checkpoint_inputs(tmp_path / "original")
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(
        native_job_manager, "algorithm_fingerprint", lambda: {"sha256": "d" * 64}
    )
    manager = native_job_manager.NativeJobManager(tmp_path / "jobs")
    state = manager.create({
        "input_path": source, "roi": [0, 0, 40, 30], "dpi": 200,
        "job_id": "bounded-connection", "connection_checkpoint": manifest,
    })

    def stop_before_process(*args, **kwargs):
        raise OSError("test inspects request before launching any worker")

    monkeypatch.setattr(native_job_manager.subprocess, "Popen", stop_before_process)
    with pytest.raises(OSError, match="test inspects request"):
        manager.start(state["job_id"])
    job = manager.jobs_root / state["job_id"]
    path = job / "attempts/0001/request.json"
    request = json.loads(path.read_text())
    # The same validator is exercised inside this pytest process, not a child.
    request["parent_pid"] = os.getppid()
    path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, request["raw_observation_cache"]["root"])
    return state, request, path


def test_manager_captures_and_worker_verifies_real_inputs(managed_checkpoint):
    from app.core.native_worker import _validate_request

    state, request, path = managed_checkpoint
    binding = state["connection_checkpoint"]
    assert request["connection_checkpoint"] == binding
    assert Path(binding["manifest"]["path"]).is_file()
    assert Path(request["job_directory"]) in Path(binding["manifest"]["path"]).parents
    assert _validate_request(path)["connection_checkpoint"] == binding
    assert request["external_cache_or_review_list_supplied"] is False


@pytest.mark.parametrize("asset", ["manifest", "baseline_dxf", "text_observations"])
def test_worker_rejects_checkpoint_changed_after_capture(managed_checkpoint, asset):
    from app.core.native_worker import _validate_request

    _, request, path = managed_checkpoint
    captured = Path(request["connection_checkpoint"][asset]["path"])
    captured.write_bytes(captured.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CONNECTION_CHECKPOINT_ASSET_HASH_MISMATCH"):
        _validate_request(path)


def test_empty_checkpoint_binding_does_not_skip_verification(managed_checkpoint):
    from app.core.native_worker import _validate_request

    _, request, path = managed_checkpoint
    request["connection_checkpoint"] = {}
    path.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(ValueError, match="CONNECTION_CHECKPOINT_CAPTURE_BINDING_INVALID"):
        _validate_request(path)


def test_worker_routes_checkpoint_but_keeps_source_publication_gate(
    managed_checkpoint, monkeypatch
):
    from app.core.native_worker import worker_run
    from app.core.processing import ProductionProcessingService

    _, request, path = managed_checkpoint
    seen = []

    def unreviewed_candidate(*args, **kwargs):
        seen.append(kwargs["connection_checkpoint"])
        evidence = Path(kwargs["evidence_dir"])
        evidence.mkdir()
        (evidence / "cold_audit.json").write_text(
            json.dumps({"source_gate_pass": False}), encoding="utf-8"
        )
        return {"objects": []}

    monkeypatch.setattr(
        ProductionProcessingService, "process_native_objects", unreviewed_candidate
    )
    assert worker_run(path) == 1
    assert seen == [request["connection_checkpoint"]]
    outcome = json.loads((path.parent / "outcome.json").read_text())
    assert outcome["status"] == "FAILED"
    assert "SAVED_SOURCE_OR_DXF_GATE_REJECTED" in outcome["error"]["message"]
    assert not (Path(request["job_directory"]) / "results").exists()
