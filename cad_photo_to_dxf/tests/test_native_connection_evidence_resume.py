"""Resume keeps source graph bytes, while every saved retrace is audited anew."""

import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.native_objects import connections
from app.native_objects.cad_io import cold_audit, export_objects
from app.native_objects.completion_stages import (
    complete_connections_without_unresolved_retirement,
    restore_connection_discovery_evidence,
    text_context_sha,
)


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def completed_connections(tmp_path):
    ink = np.zeros((160, 220), np.uint8)
    for center in ((25, 90), (195, 90)):
        cv2.circle(ink, center, 12, 1, 1)
    for points in (
        [(37, 90), (65, 69), (90, 63), (109, 60)],
        [(111, 60), (130, 63), (155, 69), (183, 90)],
    ):
        cv2.polylines(ink, [np.asarray(points, np.int32)], False, 1, 1)
    cv2.rectangle(ink, (109, 59), (111, 61), 1, 1)
    gray = np.where(ink, 0, 255).astype(np.uint8)
    roi = [0, 0, 220, 160]
    source_sha = hashlib.sha256(gray.tobytes()).hexdigest()
    old = tmp_path / "original/evidence"
    result = complete_connections_without_unresolved_retirement(
        gray, roi, source_sha, [], old / "connections"
    )
    assert len(result["objects"]) == 1
    assert result["raw_discovery_evidence"] is not None
    raw = json.loads((old / "connections/discovery/connections.json").read_text())
    _save(old / "cold_audit.json", {"old_approval_must_not_be_imported": True})
    return old, gray, roi, source_sha, raw, result


def _cold_resume(
    tmp_path, gray, roi, source_sha, objects, evidence, native_geometry_export_context
):
    dxf = tmp_path / "result.dxf"
    with native_geometry_export_context(objects):
        export_objects(objects, dxf, roi, 200, source_sha)
    audit = cold_audit(dxf, gray, roi, 200, evidence / "cold_audit.json")
    assert audit["source_gate_pass"]
    assert not audit["exact_duplicate_segments"]
    assert audit["certified_same_owner_retraces"]
    assert "old_approval_must_not_be_imported" not in audit


def test_assembly_resume_restores_bound_raw_graph_and_reaudits_saved_entity(
    tmp_path, completed_connections, native_geometry_export_context
):
    old, gray, roi, source_sha, _, result = completed_connections
    evidence = tmp_path / "assembly-resume/evidence"
    bound = restore_connection_discovery_evidence(
        old,
        evidence / "connections",
        gray,
        binding=result["raw_discovery_evidence"],
        objects=result["objects"],
    )
    assert bound == result["raw_discovery_evidence"]
    for name in bound["files"]:
        assert (evidence / name).read_bytes() == (old / name).read_bytes()
    assert not (evidence / "cold_audit.json").exists()
    _cold_resume(
        tmp_path / "assembly-resume",
        gray,
        roi,
        source_sha,
        result["objects"],
        evidence,
        native_geometry_export_context,
    )


@pytest.mark.parametrize("mode", ["revision", "completed-stage"])
def test_proposal_resume_carries_graph_into_current_adoption_and_cold_audit(
    tmp_path, completed_connections, native_geometry_export_context, mode
):
    old, gray, roi, source_sha, raw, result = completed_connections
    identity = {
        "source_sha256": source_sha,
        "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "roi_xyxy_px": roi,
    }
    payload = {
        "discovery": raw,
        "raw_discovery_evidence": result["raw_discovery_evidence"],
    }
    producer = {
        "producer_module": connections.__name__,
        "producer_sha256": _sha(connections.__file__),
    }
    if mode == "revision":
        _save(
            old / "revision_connection_proposals.json",
            {**identity, **producer, **payload},
        )
    else:
        cache = old / "connection_payload.json"
        _save(cache, payload)
        _save(
            old / "native_completion_stages.json",
            {
                **identity,
                "stages": {
                    "connections": {
                        **producer,
                        "path": cache.name,
                        "sha256": _sha(cache),
                        "text_context_sha256": text_context_sha([]),
                    }
                },
            },
        )
    evidence = tmp_path / mode / "evidence"
    resumed = complete_connections_without_unresolved_retirement(
        gray, roi, source_sha, [], evidence / "connections", cache_dir=old
    )
    assert resumed["objects"] == result["objects"]
    assert resumed["raw_discovery_evidence"] == result["raw_discovery_evidence"]
    assert resumed["replay"]["old_fitting_repeated"] is False
    if mode == "revision":
        assert resumed["replay"]["old_adoption_or_responsibility_reused"] is False
    assert not (evidence / "cold_audit.json").exists()
    _cold_resume(
        tmp_path / mode,
        gray,
        roi,
        source_sha,
        resumed["objects"],
        evidence,
        native_geometry_export_context,
    )


@pytest.mark.parametrize(
    "damage, error",
    [
        ("missing-graph", "RAW_EVIDENCE_MISSING_OR_OUTSIDE"),
        ("missing-discovery", "RAW_EVIDENCE_MISSING_OR_OUTSIDE"),
        ("changed-graph", "RAW_GRAPH_HASH_CHANGED"),
        ("changed-discovery", "RAW_EVIDENCE_BINDING_CHANGED"),
        ("changed-source", "RAW_GRAPH_CURRENT_SOURCE_CHANGED"),
        ("missing-binding", "RAW_EVIDENCE_BINDING_MISSING"),
        ("changed-binding", "RAW_EVIDENCE_BINDING_CHANGED"),
    ],
)
def test_retrace_resume_requires_original_graph_bytes_source_and_binding(
    tmp_path, completed_connections, damage, error
):
    old, gray, _, _, _, result = completed_connections
    graph = old / "connections/discovery/source_graph.json"
    discovery = old / "connections/discovery/connections.json"
    binding = copy.deepcopy(result["raw_discovery_evidence"])
    if damage == "missing-graph":
        graph.unlink()
    elif damage == "missing-discovery":
        discovery.unlink()
    elif damage == "changed-graph":
        graph.write_bytes(graph.read_bytes() + b" ")
    elif damage == "changed-discovery":
        discovery.write_bytes(discovery.read_bytes() + b" ")
    elif damage == "changed-source":
        gray[60, 110] = 0  # Fill the actual one-pixel white hole.
    elif damage == "missing-binding":
        binding = None
    elif damage == "changed-binding":
        binding["files"]["connections/discovery/source_graph.json"]["sha256"] = "0" * 64
    destination = tmp_path / "bad-resume/evidence/connections"
    with pytest.raises(ValueError, match=error):
        restore_connection_discovery_evidence(
            old, destination, gray, binding=binding, objects=result["objects"]
        )
    assert not destination.exists()


def test_published_graph_verification_can_be_read_only(completed_connections):
    old, gray, _, _, raw, result = completed_connections
    before = {p.relative_to(old): p.read_bytes() for p in old.rglob("*") if p.is_file()}
    bound = restore_connection_discovery_evidence(old, None, gray, discovery=raw)
    assert bound == result["raw_discovery_evidence"]
    assert before == {
        p.relative_to(old): p.read_bytes() for p in old.rglob("*") if p.is_file()
    }


def test_objects_without_local_retraces_need_no_new_cold_certificate_assets(tmp_path):
    assert (
        restore_connection_discovery_evidence(
            tmp_path / "absent",
            tmp_path / "new",
            np.full((3, 3), 255, np.uint8),
            objects=[],
        )
        is None
    )


def test_geometry_font_context_restores_the_production_missing_resource_gate(
    tmp_path, monkeypatch, native_geometry_export_context
):
    from app.native_objects import cad_io

    original = cad_io._font
    with native_geometry_export_context([{"kind": "CONNECTION_PATH"}]):
        metadata = cad_io._font(tmp_path)
        assert (
            metadata["font_resource"] == metadata["license_resource"] == "NOT_EXERCISED"
        )
        assert metadata["text_metrics_and_rendering"] == "NOT_RUN"
        assert not list(tmp_path.iterdir())
    assert cad_io._font is original
    with monkeypatch.context() as no_resources:
        no_resources.setattr(Path, "is_file", lambda _path: False)
        with pytest.raises(
            FileNotFoundError, match="NATIVE_EXPORT_FONT_OR_LICENSE_MISSING"
        ):
            cad_io._font(tmp_path)
