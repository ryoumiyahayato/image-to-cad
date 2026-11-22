"""Saved-file checker tests, separate from actual ordinary recognition evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import ezdxf
from ezdxf.fonts import fonts
from PIL import Image, ImageDraw, ImageFont
import pytest

from scripts.windows_native_smoke import (
    SINGLE_LINE_LABEL_FIXTURE,
    SINGLE_LINE_NEIGHBOR_FIXTURE,
    SINGLE_LINE_PP_OCR_VIEWS,
    SINGLE_LINE_TESSERACT_VIEWS,
    create_single_line_fixture,
    inspect_single_line_character_payloads,
    inspect_single_line_members,
)


FONT = Path(__file__).resolve().parents[1] / "resources/fonts/DejaVuSans.ttf"


@pytest.fixture(scope="module")
def checker_font():
    """Use actual available bytes; Windows prepares its pinned resource first.

    A clean Linux checkout uses the same installed DejaVu deployment fallback
    as native export. This affects unit fixtures only. The real Windows smoke
    still receives its explicit verified packaged font and the frozen input.
    """
    candidates = (FONT, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        pytest.fail("Prepare the verified native font or install the native Linux DejaVu resource")
    fonts.sideload_ttf(path, 1.0)  # Strict file parse, with no font-name fallback.
    return path


def _saved_checker_fixture(tmp_path, font_path):
    """Synthetic post-save checker input; never sent to production recognition."""
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new("I2CAD_NATIVE_V2")
    doc.styles.new("I2CAD_TEXT", dxfattribs={"font": "DejaVuSans.ttf"})
    mm = 25.4 / 200
    raster_font = ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC)
    vector_font = fonts.sideload_ttf(font_path, 1.0)
    rows, checks, layout_checks, source_checks = [], [], [], []

    def mark(entity, oid, kind):
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": oid, "kind": kind}))])

    for index, (content, point) in enumerate((*SINGLE_LINE_LABEL_FIXTURE, ("STORE", (460, 64)))):
        raster = Image.new("L", (640, 480), 0)
        ImageDraw.Draw(raster).text(point, content, font=raster_font, fill=255)
        x0, y0, x1, y1 = raster.getbbox()
        oid = "checker-label-" + str(index)
        geometry = {"text": content, "x": x0, "y": y1, "width_px": x1 - x0, "height_px": y1 - y0}
        row = {"id": oid, "kind": "TEXT", "geometry": geometry}
        if index == 1:
            # One new-recovery TEXT is enough to prove harness coverage. This
            # hand-written certificate is ONLY a unit-test object, not a claim
            # of source replay or successful optical recognition.
            row["source_evidence"] = {"single_line_recovery": {"schema": "native-single-line-label-evidence-v1", "checker_test_only": True}}
            lower, upper = vector_font.text_path(content).bbox()
            sx = (x1 - x0) * mm / (upper.x - lower.x)
            sy = (y1 - y0) * mm / (upper.y - lower.y)
            attrs = {"height": sy, "width": sx / sy,
                     "insert": (x0 * mm - lower.x * sx, (480 - y1) * mm - lower.y * sy)}
            checks.append({"id": oid, "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True, "checker_test_only": True})
        else:
            height = (y1 - y0) * mm
            width = (x1 - x0) * mm / fonts.sideload_ttf(font_path, height).text_width(content)
            attrs = {"height": height, "width": width, "insert": (x0 * mm, (480 - y1) * mm)}
        entity = doc.modelspace().add_text(content, dxfattribs={**attrs, "style": "I2CAD_TEXT"})
        mark(entity, oid, "TEXT")
        rows.append(row)
        layout_checks.append({"id": oid, "type": "NATIVE_TEXT_CANDIDATE_BINDING", "pass": True, "checker_test_only": True})
    for index, (start, end) in enumerate(SINGLE_LINE_NEIGHBOR_FIXTURE):
        oid = "checker-neighbor-" + str(index)
        entity = doc.modelspace().add_line((start[0] * mm, (480 - start[1]) * mm), (end[0] * mm, (480 - end[1]) * mm))
        mark(entity, oid, "LINE")
        rows.append({"id": oid, "kind": "LINE"})
        source_checks.append({"id": oid, "type": "LINE", "pass": True, "source_fraction": 1.0, "maximum_gap_px": 0.0, "max_distance_px": 0.0})
    path = tmp_path / "checker-only.dxf"
    doc.saveas(path)
    return ezdxf.readfile(path), {"objects": rows}, {
        "single_line_text_source_checks": checks,
        "native_text_candidate_checks": layout_checks,
        "source_checks": source_checks,
    }


def test_fixed_single_line_fixture_keeps_three_complete_strings_and_real_neighbors(tmp_path, checker_font):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    create_single_line_fixture(first, checker_font)
    create_single_line_fixture(second, checker_font)
    assert first.read_bytes() == second.read_bytes()
    assert set(tmp_path.iterdir()) == {first, second}
    with Image.open(first) as image:
        assert image.size == (640, 480)
        assert image.mode == "L"
        assert all(image.getpixel((x, 202)) == 0 for x in range(50, 406))
        assert all(image.getpixel((x, 308)) == 0 for x in range(460, 481))
        assert image.getpixel((459, 308)) == image.getpixel((481, 308)) == 255
        assert image.getpixel((310, 275)) == image.getpixel((310, 338)) == 0
        assert image.crop((80, 182, 225, 201)).getextrema() == (0, 255)
    assert len(SINGLE_LINE_LABEL_FIXTURE) == 3
    assert all("-" in text and any(character.isdigit() for character in text) for text, _ in SINGLE_LINE_LABEL_FIXTURE)
    assert sum("," in text for text, _ in SINGLE_LINE_LABEL_FIXTURE) == 2


def test_single_line_checker_reads_whole_saved_TEXT_and_all_neighbor_entities(tmp_path, checker_font):
    doc, objects, cold = _saved_checker_fixture(tmp_path, checker_font)
    result = inspect_single_line_members(doc, objects, cold, checker_font)
    assert result["complete_label_count"] == 3
    assert result["new_recovery_label_ids"] == ["checker-label-1"]
    assert len(result["TEXT_checks"]) == 4
    assert len(result["independent_neighbor_line_checks"]) == 4
    assert result["ordinary_text_control_preserved"] is True
    assert result["fixture_expectations_sent_to_recognizer"] is False


@pytest.mark.parametrize("damage", [
    "numeric-suffix", "hyphen", "comma", "half-label", "split-label", "MTEXT", "extra-glyph-fragment",
    "missing-text", "ordinary-control", "position", "height", "width", "rotation", "font", "mirrored",
    "candidate-content", "candidate-binding-missing", "candidate-binding-failed", "no-new-recovery",
    "source-check-missing", "source-check-failed", "wrong-source-type", "extra-source-check",
    "wrong-proof-schema", "missing-short-stroke", "duplicate-line", "fragmented-line",
    "neighbor-displaced", "neighbor-source-failed",
])
def test_single_line_checker_rejects_actual_saved_content_layout_and_protection_damage(tmp_path, damage, checker_font):
    doc, objects, cold = _saved_checker_fixture(tmp_path, checker_font)
    texts = list(doc.modelspace().query("TEXT"))
    lines = list(doc.modelspace().query("LINE"))
    if damage == "numeric-suffix":
        texts[0].dxf.text = "AHU-27B, Z"
    elif damage == "hyphen":
        texts[1].dxf.text = "PANEL08A"
    elif damage == "comma":
        texts[2].dxf.text = "CIRCUIT-315 B2"
    elif damage == "half-label":
        texts[0].dxf.text = "AHU"
    elif damage == "split-label":
        texts[0].dxf.text = "AHU-27B,"
        doc.modelspace().add_text("Z4", dxfattribs={"height": 2})
    elif damage == "MTEXT":
        doc.modelspace().add_mtext(texts[0].dxf.text)
        doc.modelspace().delete_entity(texts[0])
    elif damage == "extra-glyph-fragment":
        doc.modelspace().add_line((10, 10), (11, 12))
    elif damage == "missing-text":
        doc.modelspace().delete_entity(texts[1])
    elif damage == "ordinary-control":
        texts[3].dxf.text = "ST0RE"
    elif damage == "position":
        texts[1].dxf.insert = texts[1].dxf.insert + (4, 0, 0)
    elif damage == "height":
        texts[1].dxf.height *= 1.5
    elif damage == "width":
        texts[1].dxf.width *= 1.5
    elif damage == "rotation":
        texts[1].dxf.rotation = 5
    elif damage == "font":
        doc.styles.get("I2CAD_TEXT").dxf.font = "unrelated.ttf"
    elif damage == "mirrored":
        texts[1].dxf.text_generation_flag = 2
    elif damage == "candidate-content":
        objects["objects"][1]["geometry"]["text"] = "PANEL-08"
    elif damage == "candidate-binding-missing":
        cold["native_text_candidate_checks"].pop()
    elif damage == "candidate-binding-failed":
        cold["native_text_candidate_checks"][1]["pass"] = False
    elif damage == "no-new-recovery":
        objects["objects"][1].pop("source_evidence")
        cold["single_line_text_source_checks"] = []
    elif damage == "source-check-missing":
        cold["single_line_text_source_checks"] = []
    elif damage == "source-check-failed":
        cold["single_line_text_source_checks"][0]["pass"] = False
    elif damage == "wrong-source-type":
        cold["single_line_text_source_checks"][0]["type"] = "CANDIDATE_ONLY"
    elif damage == "extra-source-check":
        cold["single_line_text_source_checks"].append({"id": "unwritten", "pass": True})
    elif damage == "wrong-proof-schema":
        objects["objects"][1]["source_evidence"]["single_line_recovery"]["schema"] = "unverified"
    elif damage == "missing-short-stroke":
        doc.modelspace().delete_entity(lines[-1])
    elif damage == "duplicate-line":
        doc.modelspace().add_entity(lines[0].copy())
    elif damage == "fragmented-line":
        middle = (lines[0].dxf.start + lines[0].dxf.end) / 2
        doc.modelspace().add_line(middle, lines[0].dxf.end)
        lines[0].dxf.end = middle
    elif damage == "neighbor-displaced":
        lines[-1].dxf.end = lines[-1].dxf.end + (4, 0, 0)
    else:
        cold["source_checks"][-1]["pass"] = False
    path = tmp_path / "damaged-actual-save.dxf"
    doc.saveas(path)
    with pytest.raises(AssertionError):
        inspect_single_line_members(ezdxf.readfile(path), objects, cold, checker_font)


def _raw_checker_fixture(tmp_path):
    """Artificial receipt graph for checker tests, never a recognition result."""
    stage = tmp_path / "single_line_labels"
    stage.mkdir()

    def record(name, data):
        path = stage / name
        path.write_bytes(data)
        return {"path": path.relative_to(tmp_path).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}

    image = stage / "view.png"
    Image.new("L", (12, 12), 255).save(image)
    png = image.read_bytes()
    view_image = record("view.png", png)
    tsv_bytes = b"checker-only raw receipt transport; never optical recognition"
    tsv = record("view.tsv", tsv_bytes)
    metadata = record("view.json", json.dumps({
        "status": "COMPLETED", "return_code": 0,
        "tsv_sha256": hashlib.sha256(tsv_bytes).hexdigest(),
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "command_executed_for_this_request": True,
    }).encode())
    prediction = {
        "raw_text": "PANEL-08A", "input_array_sha256": hashlib.sha256(bytes([255]) * 144).hexdigest(),
        "raw_transcription_rewritten": False, "source_geometry_modified": False,
        "checker_test_only": True,
    }
    prediction_record = record("prediction.json", json.dumps(prediction).encode())
    normalization = {"text": "PANEL-08A", "reasons": [], "normalizations": [], "word_spaces": []}
    common_view = {"source_bbox_xyxy_px": [0, 0, 12, 12], "input_array_sha256": prediction["input_array_sha256"], "original_source_pixels_modified": False}
    evidence = {
        "schema": "native-single-line-label-evidence-v1", "checker_test_only": True,
        "decision": {"accepted": True, "text": "PANEL-08A", "source_text_normalization": normalization, "Tesseract_canonical_word_texts": ["PANEL-08A"]},
        "policy": {"Tesseract_views": list(SINGLE_LINE_TESSERACT_VIEWS), "PP_OCR_views": list(SINGLE_LINE_PP_OCR_VIEWS), "maximum_views_per_engine": 2},
        "source_bbox_xyxy_px": [0, 0, 12, 12],
        "original_source": record("original.png", png),
        "model_identity": record("model_identity.json", json.dumps({"providers": ["CPUExecutionProvider"], "checker_test_only": True}).encode()),
        "tesseract_views": [{"view_index": 0, "normalization": {**common_view, **SINGLE_LINE_TESSERACT_VIEWS[0]}, "raw_tsv": tsv, "metadata": metadata, "recognition_image": view_image, "command_executed_for_this_request": True}],
        "ppocr_views": [{"view_index": 0, "normalization": {**common_view, **SINGLE_LINE_PP_OCR_VIEWS[0]}, "prediction_file": prediction_record, "recognition_image": view_image, "prediction": prediction, "model_inference_executed_for_this_request": True, "observation_receipt": {"model_inference_executed_for_this_request": True}}],
        "new_Tesseract_calls": 1, "new_model_calls": 1,
    }
    objects = {"objects": [{"id": "checker-label", "kind": "TEXT", "geometry": {"text": "PANEL-08A"}, "source_evidence": {"single_line_recovery": evidence}}]}
    cold = {"single_line_text_source_checks": [{"id": "checker-label", "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True, "source_replay": {"pass": True, "checker_test_only": True, "new_OCR_calls": 0, "new_model_calls": 0, "source_text_normalization": normalization, "Tesseract_canonical_word_texts": ["PANEL-08A"]}}]}
    summary = {"new_Tesseract_calls": 1, "new_model_calls": 1, "checker_test_only": True}
    (stage / "summary.json").write_text(json.dumps(summary))
    return objects, cold, {"single_line_label_recovery": summary}


def test_single_line_raw_reader_reopens_all_named_payloads_and_counts_actual_receipts(tmp_path):
    objects, cold, report = _raw_checker_fixture(tmp_path)
    result = inspect_single_line_character_payloads(objects, cold, tmp_path, report)
    assert result["accepted_label_raw_files_read_and_hashed"] == 6
    assert result["accepted_label_new_Tesseract_calls"] == 1
    assert result["accepted_label_new_model_calls"] == 1
    assert result["inspection_executed_recognition"] is False


@pytest.mark.parametrize("damage", [
    "source-replay", "missing-source", "changed-source", "changed-tsv", "new-tsv-hash-only",
    "prediction-content", "prediction-image", "tesseract-receipt", "model-receipt", "counter",
    "too-many-views", "model-provider", "decision", "no-new-accepted-calls", "global-summary-only",
    "cold-reran-ocr", "changed-normalization-ledger", "missing-normalization-ledger", "changed-view-policy",
    "changed-view-psm", "changed-model-padding", "source-view-modified", "view-input-hash",
])
def test_single_line_raw_reader_rejects_missing_changed_or_unexecuted_receipts(tmp_path, damage):
    objects, cold, report = _raw_checker_fixture(tmp_path)
    evidence = objects["objects"][0]["source_evidence"]["single_line_recovery"]
    t_view, p_view = evidence["tesseract_views"][0], evidence["ppocr_views"][0]

    def rewrite(record, data):
        (tmp_path / record["path"]).write_bytes(data)
        record["sha256"] = hashlib.sha256(data).hexdigest()

    if damage == "source-replay":
        cold["single_line_text_source_checks"][0]["source_replay"]["pass"] = False
    elif damage == "missing-source":
        (tmp_path / evidence["original_source"]["path"]).unlink()
    elif damage == "changed-source":
        (tmp_path / evidence["original_source"]["path"]).write_bytes(b"changed")
    elif damage == "changed-tsv":
        (tmp_path / t_view["raw_tsv"]["path"]).write_bytes(b"changed")
    elif damage == "new-tsv-hash-only":
        rewrite(t_view["raw_tsv"], b"changed")
    elif damage == "prediction-content":
        changed = {**p_view["prediction"], "raw_text": "PANEL-08"}
        rewrite(p_view["prediction_file"], json.dumps(changed).encode())
    elif damage == "prediction-image":
        path = tmp_path / p_view["recognition_image"]["path"]
        Image.new("L", (12, 12), 0).save(path)
        rewrite(p_view["recognition_image"], path.read_bytes())
    elif damage == "tesseract-receipt":
        t_view["command_executed_for_this_request"] = False
    elif damage == "model-receipt":
        p_view["observation_receipt"]["model_inference_executed_for_this_request"] = False
    elif damage == "counter":
        evidence["new_model_calls"] = 2
    elif damage == "too-many-views":
        evidence["tesseract_views"] *= 3
        evidence["ppocr_views"] *= 3
    elif damage == "model-provider":
        rewrite(evidence["model_identity"], json.dumps({"providers": ["unrecorded"]}).encode())
    elif damage == "decision":
        evidence["decision"]["text"] = "PANEL-08"
    elif damage == "no-new-accepted-calls":
        t_view["command_executed_for_this_request"] = False
        metadata = json.loads((tmp_path / t_view["metadata"]["path"]).read_text())
        metadata["command_executed_for_this_request"] = False
        rewrite(t_view["metadata"], json.dumps(metadata).encode())
        p_view["model_inference_executed_for_this_request"] = False
        p_view["observation_receipt"]["model_inference_executed_for_this_request"] = False
        evidence.update(new_Tesseract_calls=0, new_model_calls=0)
    elif damage == "cold-reran-ocr":
        cold["single_line_text_source_checks"][0]["source_replay"]["new_OCR_calls"] = 1
    elif damage == "changed-normalization-ledger":
        cold["single_line_text_source_checks"][0]["source_replay"]["source_text_normalization"] = {"text": "PANEL-08A", "normalizations": [{"invented": True}]}
    elif damage == "missing-normalization-ledger":
        evidence["decision"].pop("source_text_normalization")
    elif damage == "changed-view-policy":
        evidence["policy"]["maximum_views_per_engine"] = 10
    elif damage == "changed-view-psm":
        t_view["normalization"]["psm"] = 6
    elif damage == "changed-model-padding":
        p_view["normalization"]["padding"] = 40
    elif damage == "source-view-modified":
        p_view["normalization"]["original_source_pixels_modified"] = True
    elif damage == "view-input-hash":
        t_view["normalization"]["input_array_sha256"] = "0" * 64
    else:
        report = {"cross_engine_text": {"actual_model_calls": 99}}
    with pytest.raises(AssertionError):
        inspect_single_line_character_payloads(objects, cold, tmp_path, report)


def test_raw_checker_preserves_raw_unicode_when_source_canonicalization_is_replayed(tmp_path):
    """This tests receipt/ledger binding, not the artificial quote's source proof."""
    objects, cold, report = _raw_checker_fixture(tmp_path)
    obj = objects["objects"][0]
    evidence = obj["source_evidence"]["single_line_recovery"]
    final_text, raw_text = 'PANEL-08A "B2"', "PANEL-08A “B2”"
    obj["geometry"]["text"] = final_text
    evidence["decision"]["text"] = final_text
    normalization = {"text": final_text, "reasons": [], "word_spaces": [{"character_index": 9, "left_component": 7, "right_component": 8, "original_white_gap_px": 12}], "normalizations": [{"character_index": 9, "raw_character": "“", "canonical_character": '"', "source_component_indices": [8, 9], "rule": "TWO_ORIGINAL_UPPER_QUOTE_STROKES"}]}
    evidence["decision"]["source_text_normalization"] = normalization
    cold["single_line_text_source_checks"][0]["source_replay"]["source_text_normalization"] = normalization
    view = evidence["ppocr_views"][0]
    view["prediction"]["raw_text"] = raw_text
    payload = json.dumps(view["prediction"]).encode()
    reference = view["prediction_file"]
    (tmp_path / reference["path"]).write_bytes(payload)
    reference["sha256"] = hashlib.sha256(payload).hexdigest()
    result = inspect_single_line_character_payloads(objects, cold, tmp_path, report)
    assert result["verified_saved_recovery_TEXT"][0]["text"] == final_text
    assert json.loads((tmp_path / reference["path"]).read_text())["raw_text"] == raw_text
