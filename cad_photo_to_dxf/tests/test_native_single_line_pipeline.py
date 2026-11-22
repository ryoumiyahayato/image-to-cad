"""Ordinary-stage integration and immutable raw-source checkpoint ownership."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import ezdxf
import pytest

from app.native_objects import pipeline, source_text_completion
from app.native_objects.contracts import save_json


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stage(tmp_path):
    gray = np.full((80, 160), 255, dtype=np.uint8)
    gray[12:28, 12:48] = 0
    gray[12:28, 72:145] = 0
    roi = [0, 0, 160, 80]
    texts = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [160, 80],
        "roi_xyxy_px": roi,
        "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
        "regions": [{
            "id": "old-row",
            "bbox_xyxy_px": [12, 12, 48, 28],
            "text": "STORE",
            "complete": True,
            "words": [{"text": "STORE", "bbox_xyxy_px": [12, 12, 48, 28]}],
            "completeness_evidence": {
                "alternatives": [{"raw_tsv": "original.tsv"}],
            },
        }],
        "groups": [{
            "id": "old-group", "region_ids": ["old-row"],
            "bbox_xyxy_px": [12, 12, 48, 28],
            "text": "STORE", "complete": True,
        }],
    }
    upstream = tmp_path / "source_text_completion/completed_text.json"
    save_json(upstream, texts)
    (upstream.parent / "original.tsv").write_text("immutable original observation\n")
    manifest = {
        "source_sha256": "a" * 64,
        "roi_xyxy_px": roi,
        "text": {
            "path": "source_text_completion/completed_text.json",
            "sha256": _sha(upstream),
            "producer_module": "app.native_objects.source_text_completion",
            "producer_sha256": _sha(source_text_completion.__file__),
            "dependency_producers": {},
        },
    }
    save_json(tmp_path / "completed_stages.json", manifest)
    return gray, roi, texts, upstream


def test_ordinary_single_line_stage_rebases_raw_paths_and_resumes_without_ocr(
    tmp_path, monkeypatch
):
    from app.native_objects import single_line_labels

    gray, roi, texts, upstream = _stage(tmp_path)
    old_bytes = upstream.read_bytes()
    calls = []
    checkpoints = []

    def refine(source, observations, output_dir, **kwargs):
        # This seam tests pipeline ownership, not OCR recognition. Actual
        # source/recognizer proof belongs to the single-line module's tests.
        calls.append(kwargs)
        assert np.array_equal(source, gray)
        assert observations == texts
        assert kwargs["evidence_root"] == tmp_path
        assert kwargs["roi"] == roi
        assert kwargs["source_sha256"] == "a" * 64
        result = deepcopy(observations)
        proof = {"schema": "native-single-line-label-evidence-v1"}
        result["regions"].append({
            "id": "new-row", "bbox_xyxy_px": [72, 12, 145, 28],
            "text": "AHU-27B, Z4", "complete": True,
            "single_line_recovery": proof,
            "words": [{
                "text": "AHU-27B, Z4", "bbox_xyxy_px": [72, 12, 145, 28],
            }],
        })
        result["groups"].append({
            "id": "new-group", "region_ids": ["new-row"],
            "bbox_xyxy_px": [72, 12, 145, 28],
            "text": "AHU-27B, Z4", "complete": True,
            "single_line_recovery": proof,
        })
        return result

    monkeypatch.setattr(single_line_labels, "refine_single_line_labels", refine)
    monkeypatch.setattr(
        pipeline, "checkpoint_artifact", lambda *args: checkpoints.append(args)
    )
    result = pipeline._complete_single_line_stage(
        gray, texts, tmp_path, "a" * 64, roi, 200, lambda *_: None
    )
    assert len(calls) == 1
    assert upstream.read_bytes() == old_bytes
    assert result["regions"][0] == texts["regions"][0]
    root = tmp_path / "single_line_labels"
    original = root / result["region_evidence_roots"]["old-row"] / "original.tsv"
    assert original.resolve() == upstream.parent / "original.tsv"
    assert result["region_evidence_roots"]["new-row"] == "."
    manifest = json.loads((tmp_path / "completed_stages.json").read_text())
    assert manifest["text"]["producer_module"] == "app.native_objects.single_line_labels"
    assert manifest["text"]["upstream_sha256"] == _sha(upstream)
    snapshot = tmp_path / manifest["text"]["upstream_path"]
    assert snapshot.read_bytes() == old_bytes
    assert manifest["text"]["upstream_original_path"] == "source_text_completion/completed_text.json"
    assert manifest["text"]["upstream_producer"]["sha256"] == _sha(upstream)
    assert checkpoints[-1][0] == "completed_single_line_labels"
    restored, binding = pipeline._completed_text_checkpoint(
        tmp_path, "a" * 64, roi, gray.shape, texts["source_array_sha256"]
    )
    assert restored == result and binding["new_OCR_calls"] == 0
    repeated = pipeline._complete_single_line_stage(
        gray, restored, tmp_path, "a" * 64, roi, 200, lambda *_: None
    )
    assert repeated == result and len(calls) == 1
    # A subsequent ordinary ownership stage may overwrite its original path;
    # the recovered stage still has an immutable, independently hashed input.
    upstream.write_text("later ownership destination contents\n")
    assert snapshot.read_bytes() == old_bytes


def test_new_single_line_proof_and_whole_literal_enter_one_native_text(tmp_path):
    gray, _, texts, _ = _stage(tmp_path)
    proof = {"schema": "native-single-line-label-evidence-v1", "text": "R-105, C2"}
    row = deepcopy(texts["regions"][0])
    row.update(text="R-105, C2", single_line_recovery=proof)
    group = deepcopy(texts["groups"][0])
    group.update(text="R-105, C2", single_line_recovery=proof)
    data = {**texts, "regions": [row], "groups": [group]}
    objects, issues = pipeline._text_objects(data, set(), set(), gray)
    assert issues == [] and len(objects) == 1
    assert objects[0]["kind"] == "TEXT"
    assert objects[0]["geometry"] == {
        "text": "R-105, C2", "x": 12, "y": 28,
        "height_px": 16, "width_px": 36,
    }
    assert objects[0]["source_evidence"]["single_line_recovery"] == proof
    assert objects[0]["source_evidence"]["text_layout"]["bbox_xyxy_px"] == [12, 12, 48, 28]


def test_existing_complete_text_keeps_ordinary_layout_path(tmp_path, monkeypatch):
    from app.native_objects import source_text_layout

    gray, _, texts, _ = _stage(tmp_path)
    seen = []

    def old_layout(region, source, **kwargs):
        seen.append(region["id"])
        return {"bbox_xyxy_px": [12, 12, 48, 28], "status": "existing"}

    monkeypatch.setattr(source_text_layout, "choose_source_text_layout", old_layout)
    objects, issues = pipeline._text_objects(texts, set(), set(), gray)
    assert issues == [] and seen == ["old-row"]
    assert objects[0]["geometry"]["text"] == "STORE"
    assert "single_line_recovery" not in objects[0]["source_evidence"]


def test_completed_assembly_restores_bound_new_text_artifacts(tmp_path):
    source, destination = tmp_path / "old", tmp_path / "new"
    raw = source / "single_line_labels/row/original.tsv"
    raw.parent.mkdir(parents=True)
    raw.write_text("immutable raw glyph observation\n")
    summary = {
        "raw_evidence_files": [{
            "path": "single_line_labels/row/original.tsv", "sha256": _sha(raw),
        }],
    }
    pipeline._restore_single_line_label_evidence(
        source, destination, {"single_line_label_recovery": summary}
    )
    restored = destination / "single_line_labels/row/original.tsv"
    assert restored.read_bytes() == raw.read_bytes()
    assert json.loads((destination / "single_line_labels/summary.json").read_text()) == summary
    raw.write_text("changed prior observation\n")
    with pytest.raises(ValueError, match="RAW_SOURCE_CHANGED"):
        pipeline._restore_single_line_label_evidence(
            source, tmp_path / "third", {"single_line_label_recovery": summary}
        )
    assert restored.read_text() == "immutable raw glyph observation\n"


def test_quality_review_checks_actual_single_line_ink_layout(tmp_path):
    from app.native_objects.cad_io import export_objects
    from app.native_objects.quality_review import _candidate_geometry_checks

    roi, dpi = [0, 0, 300, 100], 200
    obj = {
        "id": "single-line-layout", "kind": "TEXT", "layer": "ANNOTATION",
        "geometry": {
            "text": "AHU-27B, Z4", "x": 20, "y": 50,
            "height_px": 24, "width_px": 180,
        },
        "source_evidence": {
            "single_line_recovery": {"schema": "native-single-line-label-evidence-v1"},
        },
    }
    path = tmp_path / "actual.dxf"
    export_objects([obj], path, roi, dpi, "a" * 64)
    doc = ezdxf.readfile(path)
    entity = next(e for e in doc.modelspace().query("TEXT") if e.dxf.layer != "REVIEW")
    mm = 25.4 / dpi

    def checks():
        return _candidate_geometry_checks(
            entity, obj, [entity],
            lambda point: np.array([point[0] / mm, 100 - point[1] / mm]), mm,
            source_roi=roi, text_font_path=tmp_path / "DejaVuSans.ttf",
        )

    # This is a real exported/reopened native TEXT, not a source-recognition
    # test. Its new cap height/baseline differ intentionally from the ink box.
    assert all(value is True for value in checks().values())
    assert entity.dxf.height != 24 * mm
    entity.dxf.width *= 1.1
    assert checks()["width_matches_source_ink_layout"] is False
