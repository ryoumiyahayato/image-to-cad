"""Actual saved TEXT tamper cases; OCR replay is isolated here, not claimed.

Real raw-observation replay and ordinary EXE inputs are tested by the recovery
module and smoke path. This suite exercises the independent saved representation.
"""

from __future__ import annotations

from copy import deepcopy
import json
import sys
from types import ModuleType

import ezdxf
from ezdxf.fonts import fonts
import numpy as np
import pytest

from app.native_objects import cad_io
from app.native_objects.single_line_text_audit import cold_native_text_bindings

ROI = [0, 0, 320, 200]
DPI = 200
MM = 25.4 / DPI


def _object(recovered=True):
    obj = {
        "id": "test-complete-label",
        "kind": "TEXT",
        "layer": "ANNOTATION",
        "geometry": {
            "text": "BETA-27,3",
            "x": 23.0,
            "y": 84.0,
            "width_px": 178.0,
            "height_px": 23.0,
            "rotation_deg_image": 0.0,
        },
    }
    if recovered:
        obj["source_evidence"] = {
            "single_line_recovery": {
                "schema": "native-single-line-label-evidence-v1",
                "test_only": "raw replay mocked exclusively to isolate saved layout checks",
            }
        }
    return obj


@pytest.fixture
def isolated_replay(monkeypatch):
    module = ModuleType("app.native_objects.single_line_labels")
    result = {
        "pass": True,
        "text": "BETA-27,3",
        "bbox_xyxy_px": [23.0, 61.0, 201.0, 84.0],
        "new_OCR_calls": 0,
        "new_model_calls": 0,
    }
    module.verify_single_line_label_evidence = lambda *args, **kwargs: deepcopy(result)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return result


def _export(tmp_path, recovered=True):
    path = tmp_path / "result.dxf"
    cad_io.export_objects([_object(recovered)], path, ROI, DPI, "test-input")
    return path


def _entity(doc):
    return next(e for e in doc.modelspace() if e.dxf.layer != "REVIEW")


def _metadata(path):
    return json.loads(path.with_suffix(".objects.json").read_text())


def _save_metadata(path, data):
    data["dxf_sha256"] = cad_io.sha(path)
    path.with_suffix(".objects.json").write_text(json.dumps(data))


def _cold(path):
    return cad_io.cold_audit(
        path,
        np.full((200, 320), 255, np.uint8),
        ROI,
        DPI,
        path.parent / "evidence/cold.json",
    )


def test_whole_string_ink_box_includes_comma_descender_and_binding(
    tmp_path, isolated_replay
):
    path = _export(tmp_path)
    doc = ezdxf.readfile(path)
    text = _entity(doc)
    font = fonts.sideload_ttf(tmp_path / "DejaVuSans.ttf", 1.0)
    box = font.text_path(text.dxf.text).bbox()
    assert box.extmin.y < 0  # This catches cap-height-only placement.
    origin = np.asarray(list(text.dxf.insert)[:2])
    lower = origin + np.array(
        [
            box.extmin.x * text.dxf.height * text.dxf.width,
            box.extmin.y * text.dxf.height,
        ]
    )
    upper = origin + np.array(
        [
            box.extmax.x * text.dxf.height * text.dxf.width,
            box.extmax.y * text.dxf.height,
        ]
    )
    assert lower == pytest.approx([23 * MM, (200 - 84) * MM])
    assert upper == pytest.approx([201 * MM, (200 - 61) * MM])
    report = _cold(path)
    assert report["source_gate_pass"]
    assert len(report["native_text_candidate_checks"]) == 1
    assert report["native_text_candidate_checks"][0]["pass"]
    assert (
        report["single_line_text_source_checks"][0]["type"]
        == "SINGLE_LINE_TEXT_SOURCE_BINDING"
    )
    assert report["single_line_text_source_checks"][0]["pass"]


@pytest.mark.parametrize(
    "mutation",
    [
        "suffix",
        "comma",
        "position",
        "height",
        "rotation",
        "width",
        "alignment",
        "extrusion",
        "style",
        "style_width",
        "missing_entity",
        "missing_flag",
        "missing_proof",
        "missing_receipt",
        "missing_binding",
        "candidate_string",
        "candidate_bbox",
        "font_bytes",
        "review_layer",
        "duplicate_entity",
    ],
)
def test_saved_or_sidecar_tamper_cannot_pass_by_rebinding_file_hash(
    tmp_path, isolated_replay, mutation
):
    path = _export(tmp_path)
    doc = ezdxf.readfile(path)
    entity = _entity(doc)
    metadata = _metadata(path)
    if mutation == "suffix":
        entity.dxf.text = "BETA-27"
    elif mutation == "comma":
        entity.dxf.text = "BETA-27.3"
    elif mutation == "position":
        entity.dxf.insert = entity.dxf.insert + (1, 0, 0)
    elif mutation == "height":
        entity.dxf.height *= 1.1
    elif mutation == "rotation":
        entity.dxf.rotation = 4
    elif mutation == "width":
        entity.dxf.width *= 1.03
    elif mutation == "alignment":
        entity.dxf.halign = 1
        entity.dxf.align_point = entity.dxf.insert
    elif mutation == "extrusion":
        entity.dxf.extrusion = (0, 0, -1)
    elif mutation == "style":
        entity.dxf.style = "Standard"
    elif mutation == "style_width":
        doc.styles.get(entity.dxf.style).dxf.width = 1.03
    elif mutation == "missing_entity":
        doc.modelspace().delete_entity(entity)
    elif mutation == "missing_flag":
        ident = cad_io.identity(entity)
        ident.pop("single_line_recovery")
        entity.set_xdata(cad_io.APPID, [(1000, json.dumps(ident))])
    elif mutation == "missing_proof":
        metadata["objects"][0]["source_evidence"].pop("single_line_recovery")
    elif mutation == "missing_receipt":
        metadata["written"] = []
    elif mutation == "missing_binding":
        metadata["written"][0].pop("text_geometry_binding")
    elif mutation == "candidate_string":
        metadata["objects"][0]["geometry"]["text"] = "BETA-27.3"
    elif mutation == "candidate_bbox":
        metadata["objects"][0]["geometry"]["width_px"] += 1
    elif mutation == "font_bytes":
        with (tmp_path / "DejaVuSans.ttf").open("ab") as output:
            output.write(b"changed byte identity")
    elif mutation == "review_layer":
        entity.dxf.layer = "REVIEW"
    elif mutation == "duplicate_entity":
        doc.modelspace().add_entity(entity.copy())
    doc.saveas(path)
    _save_metadata(path, metadata)
    report = _cold(path)
    assert not report["source_gate_pass"]
    assert any(not row["pass"] for row in report["native_text_candidate_checks"])
    assert any(not row["pass"] for row in report["single_line_text_source_checks"])


@pytest.mark.parametrize("change", ["pass", "text", "bbox_xyxy_px"])
def test_raw_replay_result_must_match_saved_candidate(
    tmp_path, isolated_replay, change
):
    path = _export(tmp_path)
    isolated_replay[change] = {
        "pass": False,
        "text": "BETA-27,8",
        "bbox_xyxy_px": [23, 61, 202, 84],
    }[change]
    report = _cold(path)
    assert report["native_text_candidate_checks"][0]["pass"]
    assert not report["single_line_text_source_checks"][0]["pass"]
    assert not report["source_gate_pass"]


def test_deleted_entire_xdata_still_has_explicit_failed_text_binding(
    tmp_path, isolated_replay
):
    path = _export(tmp_path)
    doc = ezdxf.readfile(path)
    _entity(doc).discard_xdata(cad_io.APPID)
    doc.saveas(path)
    metadata = _metadata(path)
    _save_metadata(path, metadata)
    candidates, sources = cold_native_text_bindings(
        path,
        ezdxf.readfile(path),
        np.full((200, 320), 255, np.uint8),
        ROI,
        DPI,
        tmp_path,
    )
    assert len(candidates) >= 1 and any(not c["pass"] for c in candidates)
    assert len(sources) == 1 and not sources[0]["pass"]
    report = _cold(path)
    assert not report["source_gate_pass"]
    assert report["geometry_audit"] == "NOT_RUN_INVALID_NATIVE_IDENTITIES"
    assert report["identity_failures"]


def test_legacy_text_keeps_previous_attributes_and_does_not_claim_new_replay(
    tmp_path, isolated_replay
):
    baseline = tmp_path / "legacy/result.dxf"
    current = tmp_path / "mixed/result.dxf"
    old = _object(False)
    cad_io.export_objects([old], baseline, ROI, DPI, "test-input")
    recovered = _object(True)
    recovered["id"] = "new-label"
    cad_io.export_objects([old, recovered], current, ROI, DPI, "test-input")
    a = _entity(ezdxf.readfile(baseline))
    b = _entity(ezdxf.readfile(current))
    assert cad_io.entity_data(a) == cad_io.entity_data(b)
    assert list(a.get_xdata(cad_io.APPID)) == list(b.get_xdata(cad_io.APPID))
    assert tuple(b.dxf.insert) == pytest.approx((23 * MM, 116 * MM, 0))
    assert b.dxf.height == pytest.approx(23 * MM)
    assert cad_io.text_size(b).width == pytest.approx(178 * MM)
    report = _cold(current)
    assert all(r["pass"] for r in report["native_text_candidate_checks"])
    assert len(report["native_text_candidate_checks"]) == 2
    assert len(report["single_line_text_source_checks"]) == 1
    assert report["single_line_text_source_checks"][0]["id"] == "new-label"


def test_missing_entire_candidate_metadata_fails_saved_text(tmp_path, isolated_replay):
    path = _export(tmp_path)
    path.with_suffix(".objects.json").unlink()
    report = _cold(path)
    assert not report["source_gate_pass"]
    assert (
        report["native_text_candidate_checks"]
        and not report["native_text_candidate_checks"][0]["pass"]
    )
    assert (
        report["single_line_text_source_checks"]
        and not report["single_line_text_source_checks"][0]["pass"]
    )
