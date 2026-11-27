"""Integrity and boundary controls for explicit complete-source continuation.

Tiny source packets exercise corruption handling. Expensive installed resource
discovery is isolated here; real legacy resources and ordinary output are
validated separately by the Issue 61 execution.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.native_objects import source_stage_checkpoint as checkpoint


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def pipeline_text(*, selector=False, gray="prepared.gray", dpi="200.0", downstream="old_downstream"):
    arg = ", source_stage_checkpoint=None" if selector else ""
    guard = ('        if source_stage_checkpoint is not None:\n'
             '            raise ValueError("SELECT_ONE_EXPLICIT_SOURCE_CHECKPOINT_MODE")\n') if selector else ""
    return f'''from pathlib import Path
CONSTANT = 17
def helper(x):
    return x + 1
def run_native_objects(source, target, roi, *, dpi={dpi}, connection_checkpoint=None{arg}):
    gray = {gray}
    roi = prepared.working_roi
    if connection_checkpoint is not None:
{guard}        return previous_connection()
    identity = {{"roi": roi, "dpi": dpi}}
    try:
        if restored_assembly:
            restore()
        else:
            texts = extract_text_regions(gray)
            doors = retire_door_fragments(texts)
            walls = assemble_walls(doors)
            short_contact_completion = complete_short_contact_text(walls)
            objects += short_contact_completion["objects"]
            text_objects += short_contact_completion["objects"]
            {downstream}()
    except ValueError:
        raise
'''


def test_pipeline_projection_accepts_only_explicit_dispatch_and_downstream_change(tmp_path):
    old, new = tmp_path / "old.py", tmp_path / "new.py"
    old.write_text(pipeline_text())
    new.write_text(pipeline_text(selector=True, downstream="new_joint_downstream"))
    assert checkpoint.pipeline_projection(old) == checkpoint.pipeline_projection(new)


@pytest.mark.parametrize("change", ["gray", "roi", "dpi", "sequence", "helper", "default"])
def test_pipeline_projection_binds_preamble_defaults_and_entire_upstream(tmp_path, change):
    old, new = tmp_path / "old.py", tmp_path / "new.py"
    original = pipeline_text()
    replacements = {
        "gray": ("gray = prepared.gray", "gray = prepared.gray.copy()"),
        "roi": ("roi = prepared.working_roi", "roi = source_roi"),
        "dpi": ('"dpi": dpi', '"dpi": dpi + 1'),
        "sequence": ("doors = retire_door_fragments(texts)", "doors = retire_door_fragments(list(reversed(texts)))"),
        "helper": ("return x + 1", "return x + 2"),
        "default": ("dpi=200.0", "dpi=201.0"),
    }
    old.write_text(original)
    new.write_text(original.replace(*replacements[change]))
    assert checkpoint.pipeline_projection(old) != checkpoint.pipeline_projection(new)


def test_pipeline_projection_refuses_missing_boundary_append(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text(pipeline_text().replace('            text_objects += short_contact_completion["objects"]\n', ""))
    with pytest.raises(ValueError, match="SHORT_TEXT_BOUNDARY_CHANGED"):
        checkpoint.pipeline_projection(path)


def source_state():
    line = {"id": "LINE-fixture", "kind": "LINE", "layer": "LINE",
            "geometry": {"start": [1.25, 2.5], "end": [9.5, 12.0]}, "source_evidence": {}}
    door = {"id": "DOOR-fixture", "kind": "DOOR_SINGLE", "layer": "DOOR",
            "geometry": {"anchor": [3.0, 4.0], "native_members": [
                {"kind": "LINE", "geometry": {"start": [3.0, 4.0], "end": [3.0, 5.125]},
                 "source_interval": [0.011, 0.97]}]}, "source_evidence": {}}
    state = {name: {} for name in checkpoint._REQUIRED_STATE}
    state.update(objects=[line, door], issues=[], text_objects=[])
    state["texts"] = {"raw_evidence_files": [{"path": "text/raw.tsv", "sha256": "FILLED_BY_FIXTURE"}]}
    bindings = [checkpoint._object_binding(o) for o in sorted(state["objects"], key=lambda obj: obj["id"])]
    path = {"stroke_id": "STROKE-fixture", "representation": {"kind": "LINE", "start": [5.0, 4.0], "end": [6.0, 8.0]}}
    plan = {"schema": "historical-fixture", "paths": [path], "prior_object_bindings": bindings,
            "prior_object_bindings_sha256": checkpoint.digest_legacy(bindings)}
    added = {"id": path["stroke_id"], "kind": "LINE", "layer": "SHORT_STROKE", "geometry": path["representation"],
             "source_evidence": {"attached_stroke_graph": {"path": path, "plan_sha256": checkpoint.digest_legacy(plan)}}}
    adoption = {"plan": plan, "objects": [added], "retired_ids": [], "prior_object_bindings": bindings}
    assembly = {**deepcopy(state), "objects": deepcopy(state["objects"]) + [added], "attached_stroke_completion": adoption}
    return state, assembly, plan, adoption


def test_projection_retains_complete_finite_door_and_source_intervals():
    state, assembly, plan, adoption = source_state()
    projected, removed = checkpoint.project_upstream(assembly, plan, adoption)
    assert projected == state
    assert removed == ["STROKE-fixture"]
    assert projected["objects"][1]["geometry"]["native_members"][0]["source_interval"] == [0.011, 0.97]
    assert "attached_stroke_completion" not in projected


@pytest.mark.parametrize("change", ["endpoint", "interval", "retirement", "prior_missing", "added_object_changed"])
def test_projection_refuses_changed_finite_member_or_incomplete_stage_boundary(change):
    _, assembly, plan, adoption = source_state()
    if change == "endpoint":
        assembly["objects"][1]["geometry"]["native_members"][0]["geometry"]["end"][1] += 1e-12
    elif change == "interval":
        assembly["objects"][1]["geometry"]["native_members"][0]["source_interval"][0] += 1e-12
    elif change == "retirement":
        adoption["retired_ids"] = ["LINE-fixture"]
    elif change == "prior_missing":
        plan["prior_object_bindings"].pop()
    else:
        assembly["objects"][-1] = deepcopy(assembly["objects"][-1])
        assembly["objects"][-1]["geometry"]["start"] = [6.0, 4.0]
    with pytest.raises(ValueError):
        checkpoint.project_upstream(assembly, plan, adoption)


@pytest.fixture
def packet(tmp_path, monkeypatch):
    from app.native_objects import source_proof_continuation
    origin, previous_source = tmp_path / "legacy/evidence", tmp_path / "legacy/code"
    source = tmp_path / "source.bin"
    source.write_bytes(b"unaltered synthetic source samples")
    raw = origin / "text/raw.tsv"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"independent original observation\n")
    for name in ("import_preview.png", "job_config.json", "raw_observation_usage.json", "runtime_privacy.json"):
        (origin / name).write_bytes(b"previous task metadata must not be restored")
    _, assembly, plan, adoption = source_state()
    assembly["texts"]["raw_evidence_files"][0]["sha256"] = checkpoint.file_sha(raw)
    write(origin / "completed_assembly.json", assembly)
    write(origin / "attached_strokes/plan.json", plan)
    write(origin / "attached_strokes/adoption.json", adoption)
    algorithm = {"files": {}, "sha256": "synthetic-worker-algorithm"}
    for name in ("app/native_objects/geometry.py", *checkpoint._SUPPLEMENTAL):
        path = previous_source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# frozen synthetic producer\n")
        algorithm["files"][name] = checkpoint.file_sha(path)
    parameters = {"roi": [0, 0, 20, 20], "dpi": 200, "page_number": None, "frame_number": None, "orientation": 0, "language": "eng"}
    request = write(tmp_path / "legacy/request.json", {"source_sha256": checkpoint.file_sha(source), "algorithm": algorithm, "parameters": parameters})
    write(origin / "completed_stages.json", {"assembly": {"path": "completed_assembly.json",
          "sha256": checkpoint.file_sha(origin / "completed_assembly.json"), "algorithm_fingerprint": algorithm},
          "text": {"path": "text/raw.tsv", "sha256": checkpoint.file_sha(raw)}})
    environment = write(tmp_path / "legacy/environment.json", {"runtime": "synthetic-runtime-v1"})
    resources = write(tmp_path / "legacy/resources.json", {"font": "synthetic-font-v1"})
    closure = {"native": "synthetic-reused-code-closure-v1"}
    monkeypatch.setattr(checkpoint, "producer_closure", lambda *args, **kwargs: deepcopy(closure))
    monkeypatch.setattr(checkpoint, "dependency_identity", lambda e, r, *args, **kwargs: {"environment": e, "resources": r})
    monkeypatch.setattr(checkpoint, "_source_identity", lambda s, p, *args, **kwargs: {
        "source_sha256": checkpoint.file_sha(s), "working_array_sha256": checkpoint.file_sha(s),
        "cache_identity": {"source_sha256": checkpoint.file_sha(s)}, "parameters": p,
        "unit": "paper_mm", "scale_evidence": {"engineering_scale": "UNVERIFIED"}, "working_roi_xyxy_px": p["roi"]})
    # Capsule semantics have their own real-DXF tests. This fixture isolates
    # capture integrity from installed runtime and historical publication.
    monkeypatch.setattr(source_proof_continuation, "create_historical_capsule", lambda *a, **k: {"artifacts": {}})
    monkeypatch.setattr(source_proof_continuation, "validate_historical_capsule", lambda *a, **k: None)
    output = tmp_path / "packet"
    manifest = checkpoint.build_checkpoint(evidence=origin, request=request, previous_source=previous_source,
                                           environment=environment, resources=resources, source=source, output=output)
    return SimpleNamespace(manifest=manifest, root=output, source=source, parameters=parameters, closure=closure)


def test_complete_packet_capture_and_restore_keep_upstream_objects_only(packet, tmp_path):
    verified = checkpoint.verify_checkpoint(packet.manifest, source=packet.source, parameters=packet.parameters)
    job = tmp_path / "new-job"
    (job / "inputs").mkdir(parents=True)
    (job / "inputs/source.bin").write_bytes(packet.source.read_bytes())
    binding = checkpoint.capture_checkpoint(packet.manifest, job, checkpoint.file_sha(packet.source), packet.parameters)
    assert checkpoint.verify_captured_checkpoint(binding, job, checkpoint.file_sha(packet.source), packet.parameters) == verified
    out = job / "result/evidence"
    out.mkdir(parents=True)
    # Real prepare_source has already written these for this new task.
    for name in ("import_preview.png", "job_config.json"):
        (out / name).write_bytes(b"new task source import")
    prepared = SimpleNamespace(source_sha256=verified["source"]["source_sha256"],
                               manifest={"cache_identity": verified["source"]["cache_identity"]}, working_roi=packet.parameters["roi"])
    state = checkpoint.restore_for_pipeline(binding, SimpleNamespace(input_path=job / "inputs/source.bin"), prepared, out)
    assert [obj["id"] for obj in state["objects"]] == ["LINE-fixture", "DOOR-fixture"]
    assert not (out / "attached_strokes").exists()
    assert (out / "import_preview.png").read_bytes() == b"new task source import"
    assert (out / "job_config.json").read_bytes() == b"new task source import"
    assert not (out / "raw_observation_usage.json").exists()
    assert not (out / "runtime_privacy.json").exists()
    receipt = checkpoint.read_json(out / "source_stage_continuation.json")
    assert receipt["status"] == "UPSTREAM_RESTORED_DOWNSTREAM_NOT_RUN"
    assert set(receipt["downstream"].values()) == {"NOT_RUN"}
    assert receipt["old_attached_result_reused"] is False
    checkpoint.update_execution(out, fresh_source_graph="EXECUTED", attached_ink={"status": "EXECUTED", "adopted_count": 0})
    receipt = checkpoint.read_json(out / "source_stage_continuation.json")
    assert receipt["downstream"]["attached_ink"]["adopted_count"] == 0
    assert receipt["downstream"]["native_save"] == "NOT_RUN"


@pytest.mark.parametrize("change", ["source", "roi", "dpi", "orientation", "unit", "finite_state", "missing_raw", "old_producer", "runtime", "executor"])
def test_checkpoint_invalidates_changed_inputs_producers_dependencies_or_members(packet, monkeypatch, change):
    parameters = deepcopy(packet.parameters)
    if change == "source":
        packet.source.write_bytes(b"changed original samples")
    elif change == "roi":
        parameters["roi"][0] += 1
    elif change in ("dpi", "orientation"):
        parameters[change] += 1
    elif change == "unit":
        value = checkpoint.read_json(packet.manifest)
        value["source"]["unit"] = "engineering_mm"
        write(packet.manifest, value)
    elif change == "finite_state":
        path = packet.root / "upstream_state.json"
        value = checkpoint.read_json(path)
        value["objects"][1]["geometry"]["native_members"][0]["source_interval"][0] += 1e-12
        write(path, value)
    elif change == "missing_raw":
        (packet.root / "evidence/text/raw.tsv").unlink()
    elif change == "old_producer":
        packet.closure["native"] = "changed-current-upstream-code"
    elif change == "runtime":
        monkeypatch.setattr(checkpoint, "dependency_identity", lambda *a, **k: {"runtime": "changed-binary"})
    else:
        monkeypatch.setattr(checkpoint, "executor_identity", lambda *a, **k: {"pipeline": "changed-recovery-branch"})
    with pytest.raises(ValueError):
        checkpoint.verify_checkpoint(packet.manifest, source=packet.source, parameters=parameters)


def test_failed_capture_keeps_machine_readable_rejection(packet, tmp_path):
    (packet.root / "evidence/text/raw.tsv").unlink()
    job = tmp_path / "rejected-job"
    (job / "inputs").mkdir(parents=True)
    (job / "inputs/source.bin").write_bytes(packet.source.read_bytes())
    with pytest.raises(ValueError):
        checkpoint.capture_checkpoint(packet.manifest, job, checkpoint.file_sha(packet.source), packet.parameters)
    report = checkpoint.read_json(job / "source_stage_checkpoint_capture_failure.json")
    assert report["status"] == "REJECTED"
    assert report["fresh_fit_fallback_attempted"] is False
    assert not (job / "source_stage_checkpoint_capture.json").exists()


def test_post_capture_tamper_cannot_become_zero_adoption(packet, tmp_path):
    job = tmp_path / "captured-job"
    (job / "inputs").mkdir(parents=True)
    (job / "inputs/source.bin").write_bytes(packet.source.read_bytes())
    binding = checkpoint.capture_checkpoint(packet.manifest, job, checkpoint.file_sha(packet.source), packet.parameters)
    (job / "imports/source-stage-checkpoint/evidence/text/raw.tsv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="ARTIFACT_CHANGED"):
        checkpoint.verify_captured_checkpoint(binding, job, checkpoint.file_sha(packet.source), packet.parameters)


def test_same_version_distribution_source_change_invalidates_checkpoint(packet, tmp_path, monkeypatch):
    package = tmp_path / "installed-synthetic-package"
    package.mkdir()
    (package / "source.py").write_text("VALUE = 1\n")
    (package / "native.so").write_bytes(b"synthetic native byte identity")
    (package / "unused.pyc").write_bytes(b"untrusted interpreter cache")
    dist = SimpleNamespace(version="1.0", files=[Path("source.py"), Path("native.so"), Path("unused.pyc")],
                           locate_file=lambda relative: package / relative)
    monkeypatch.setattr(checkpoint.importlib.metadata, "distribution", lambda name: dist)
    pins = {"synthetic-package": "1.0"}
    identity = checkpoint.locked_distribution_identity(pins, pins)
    assert set(identity["current_distribution_code_sha256"]) == {
        "synthetic-package:source.py", "synthetic-package:native.so"}
    manifest = checkpoint.read_json(packet.manifest)
    manifest["runtime_and_resources"] = identity
    write(packet.manifest, manifest)
    monkeypatch.setattr(checkpoint, "dependency_identity",
                        lambda *args, **kwargs: checkpoint.locked_distribution_identity(pins, pins))
    checkpoint.verify_checkpoint(packet.manifest, source=packet.source, parameters=packet.parameters)
    (package / "source.py").write_text("VALUE = 2\n")
    assert dist.version == "1.0"
    with pytest.raises(ValueError, match="RUNTIME_OR_RESOURCE_BYTES_CHANGED"):
        checkpoint.verify_checkpoint(packet.manifest, source=packet.source, parameters=packet.parameters)


def test_manager_captures_the_explicit_source_stage_option(tmp_path, monkeypatch):
    from PIL import Image
    from app.core.native_job_manager import NativeJobManager

    source = tmp_path / "source.png"
    Image.new("L", (30, 30), 255).save(source)
    calls = []

    def capture(path, directory, sha, parameters):
        calls.append((Path(path), Path(directory), sha, parameters))
        return {"schema": checkpoint.CAPTURE_SCHEMA, "manifest_sha256": "synthetic-captured-manifest"}

    monkeypatch.setattr(checkpoint, "capture_checkpoint", capture)
    manager = NativeJobManager(tmp_path / "jobs")
    state = manager.create(input_path=source, roi=[0, 0, 30, 30], dpi=200, source_stage_checkpoint=tmp_path / "manifest.json")
    assert len(calls) == 1 and calls[0][3]["roi"] == [0, 0, 30, 30]
    assert state["source_stage_checkpoint"]["manifest_sha256"] == "synthetic-captured-manifest"
