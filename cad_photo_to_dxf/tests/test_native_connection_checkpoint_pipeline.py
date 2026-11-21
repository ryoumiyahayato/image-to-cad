"""Actual bounded dispatch, source fit, DXF export, render and publication gates.

Only the forbidden OCR call is intercepted. The source, fonts, checkpoint
capture, path algorithm, preserved entities and saved-file review are real.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import cv2
import ezdxf
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from app.core.native_objects_entry import dispatch_native_objects
from app.core.native_worker import _saved_candidate_gates
from app.native_objects import cad_io, pipeline
from app.native_objects.connection_checkpoint_inputs import capture_checkpoint
from app.native_objects.contracts import save_json
from app.native_objects.review_binding import file_sha256, verify_saved_review


ROI = [0, 0, 220, 180]
DPI = 200
CONTEXT = [10, 20, 190, 150]


def _asset(path):
    return {"path": str(path), "sha256": file_sha256(path)}


def _captured_case(tmp_path, incomplete_old_line):
    original = tmp_path / "author-originals"
    original.mkdir()
    # Use the same legitimate deployed font and license as the production
    # exporter. Missing resources must fail this integration gate, not skip it.
    font_resource = cad_io._font(original)
    font = ImageFont.truetype(str(original / font_resource["font"]), 14)
    text_bounds = font.getbbox("KEEP", anchor="ls")
    image = Image.new("L", (ROI[2], ROI[3]), 255)
    ImageDraw.Draw(image).text((20, 40), "KEEP", font=font, fill=0, anchor="ls")
    gray = np.array(image)
    cv2.polylines(
        gray,
        [np.asarray([[30, 80], [75, 80], [105, 60], [135, 60], [170, 80]], np.int32)],
        False,
        0,
        1,
    )
    gray[140, 20:206] = 0  # A correct neighbor extends beyond the local context.
    source = original / "source.png"
    Image.fromarray(gray).save(source, dpi=(DPI, DPI))
    source_sha = file_sha256(source)
    glyph_box = [20 + text_bounds[0], 40 + text_bounds[1],
                 20 + text_bounds[2], 40 + text_bounds[3]]
    old_objects = [
        {
            "id": "correct-neighbor-line", "kind": "LINE", "layer": "GEOMETRY",
            "geometry": {"start": [20, 140], "end": [205, 140]},
            "source_evidence": {"method": "synthetic_known_source_stroke"},
        },
        {
            "id": "correct-neighbor-text", "kind": "TEXT", "layer": "ANNOTATION",
            "geometry": {
                "text": "KEEP", "x": 20, "y": 40,
                "width_px": text_bounds[2] - text_bounds[0],
                "height_px": text_bounds[3] - text_bounds[1],
                "rotation_deg_image": 0,
            },
            "source_evidence": {
                "method": "synthetic_known_source_literal",
                "text_group_id": "known-text-group",
                "bbox_xyxy_px": glyph_box,
            },
        },
    ]
    if incomplete_old_line:
        old_objects.append({
            "id": "incomplete-old-line", "kind": "LINE", "layer": "GEOMETRY",
            "geometry": {"start": [40, 80], "end": [70, 80]},
            "source_evidence": {"method": "synthetic_partial_source_stroke"},
        })
    baseline = original / "baseline.dxf"
    cad_io.export_objects(old_objects, baseline, ROI, DPI, source_sha)
    texts_path = original / "text-observations.json"
    save_json(texts_path, {
        "schema": "native_text_regions_v2", "schema_version": 2,
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [ROI[2], ROI[3]], "roi_xyxy_px": ROI,
        "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
        "regions": [{"id": "known-text-region", "text": "KEEP",
                     "bbox_xyxy_px": glyph_box, "accepted": True, "words": []}],
        "groups": [{"id": "known-text-group", "text": "KEEP",
                    "bbox_xyxy_px": glyph_box, "complete": True}],
        "uncertainties": [], "source_pixels_modified": False,
    })
    manifest_path = original / "checkpoint.json"
    save_json(manifest_path, {
        "schema": "native-connection-checkpoint-v1",
        "source_sha256": source_sha, "roi_xyxy_px": ROI, "dpi": DPI,
        "baseline_dxf": _asset(baseline),
        "baseline_ownership": _asset(baseline.with_suffix(".objects.json")),
        "text_observations": _asset(texts_path),
        "windows": [{"id": "synthetic-source-window",
                     "target_roi": [20, 50, 180, 90], "context_roi": CONTEXT}],
    })
    job = tmp_path / "job"
    (job / "inputs").mkdir(parents=True)
    captured_source = job / "inputs/source.png"
    shutil.copyfile(source, captured_source)
    parameters = {
        "roi": ROI, "dpi": DPI, "orientation": 0,
        "page_number": None, "frame_number": None, "language": "eng",
    }
    binding = capture_checkpoint(manifest_path, job, source_sha, parameters)
    old_doc = ezdxf.readfile(baseline)
    expected = {
        cad_io.identity(entity)["id"]: {
            "data": cad_io.entity_data(entity),
            "handle": entity.dxf.handle,
            "source_tags": list(entity.get_xdata(cad_io.APPID)),
        }
        for entity in old_doc.modelspace()
        if entity.dxf.layer != "REVIEW"
    }
    # The actual dispatch must work from captured files, without a surviving
    # author directory, external observation cache or prior approval list.
    shutil.rmtree(original)
    return job, captured_source, binding, expected


@pytest.mark.parametrize("incomplete_old_line", [False, True], ids=["new-path", "replace-incomplete-line"])
def test_bounded_dispatch_produces_complete_editable_path_and_preserves_neighbors(
    tmp_path, monkeypatch, incomplete_old_line
):
    def forbidden_ocr(*_args, **_kwargs):
        pytest.fail("Bounded checkpoint dispatch called the full OCR stage")

    monkeypatch.setattr(pipeline, "extract_text_regions", forbidden_ocr)
    job, source, binding, expected = _captured_case(tmp_path, incomplete_old_line)
    clean_cwd = tmp_path / "clean-working-directory"
    clean_cwd.mkdir()
    monkeypatch.chdir(clean_cwd)
    staging = job / "attempts/0001/staging"
    result = dispatch_native_objects(
        source, staging / "result.dxf", ROI, dpi=DPI,
        evidence_dir=staging / "evidence", connection_checkpoint=binding,
    )
    assert result["pipeline_module"] == "app.native_objects.connection_checkpoint"
    assert result["new_OCR_calls"] == result["full_region_conversion_runs"] == 0
    assert len(result["new_complete_path_ids"]) == 1
    assert result["retired_whole_line_ids"] == (
        ["incomplete-old-line"] if incomplete_old_line else []
    )
    assert set(result["preserved_old_object_ids"]) == {
        "correct-neighbor-line", "correct-neighbor-text"
    }
    output = staging / "result.dxf"
    cold_doc = ezdxf.readfile(output)
    actual = {cad_io.identity(entity)["id"]: entity for entity in cold_doc.modelspace()}
    assert len(actual) == 3
    assert len(cold_doc.modelspace().query("LWPOLYLINE")) == 1
    for oid in result["preserved_old_object_ids"]:
        assert cad_io.entity_data(actual[oid]) == expected[oid]["data"]
        assert actual[oid].dxf.handle == expected[oid]["handle"]
        assert list(actual[oid].get_xdata(cad_io.APPID)) == expected[oid]["source_tags"]
    assert actual["correct-neighbor-text"].dxf.text == "KEEP"
    new = next(row for row in result["objects"] if row["kind"] == "CONNECTION_PATH")
    assert {tuple(p) for p in (new["geometry"]["points"][0], new["geometry"]["points"][-1])} == {
        (30.0, 80.0), (170.0, 80.0)
    }
    assert new["source_evidence"]["whole_simple_source_chain"]["pass"]
    assert new["source_evidence"]["whole_simple_source_chain_fit"]["pass"]
    assert "incomplete-old-line" not in actual
    assert file_sha256(source) == binding["source_sha256"]
    assert file_sha256(binding["baseline_dxf"]["path"]) == binding["baseline_dxf"]["sha256"]

    evidence = staging / "evidence"
    imported = json.loads((evidence / "import_manifest.json").read_text())
    quality = json.loads((evidence / "quality_review.json").read_text())
    assert imported["connection_checkpoint"]["context_rois"] == [CONTEXT]
    assert quality["review_scope"]["full_parent_region_review_performed"] is False
    assert quality["summary"]["safe_artifact_structure"]
    assert quality["summary"]["source_geometry_gate_pass"]
    assert quality["text_style_and_font_dependencies"]
    assert all(row["pass"] for row in quality["text_style_and_font_dependencies"])
    assert verify_saved_review(
        evidence / "quality_review.json", output, result["objects"], imported
    )["valid"]
    gates = _saved_candidate_gates(staging, {"input_path": str(source)})
    assert gates["review_binding"]["valid"]
    assert gates["formal_entities"] == {"LINE": 1, "TEXT": 1, "LWPOLYLINE": 1}
    assert gates["source_geometry_checks"] >= 2
    with Image.open(result["preview_path"]) as preview:
        assert preview.format == "PNG" and preview.size == (ROI[2], ROI[3])
    entry = json.loads(Path(result["entry_trace_path"]).read_text())
    assert entry["status"] == "COMPLETED"
    assert entry["legacy_processing_called"] is False
    assert "app.native_objects.pipeline.run_native_objects" in entry["call_chain"]
    assert result["status"] == "LOCAL_NO_GO"
    assert result["CAD_GUI"] == "NOT_RUN_BY_PIPELINE"
