"""Saved-file checker tests, separate from actual ordinary recognition evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

import ezdxf
from ezdxf.fonts import fonts
import numpy as np
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
    inspect_bounded_single_line_members,
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


def _saved_checker_fixture(tmp_path, font_path, recovery_indices=(1,)):
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
        if index in recovery_indices:
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
    evidence["source_array_sha256"] = prediction["input_array_sha256"]
    evidence["preexisting_raw_view_inventory"] = record("preexisting_raw_view_inventory.json", json.dumps({
        "schema": "single-line-preexisting-raw-view-inventory-v1",
        "source_array_sha256": evidence["source_array_sha256"], "source_bbox_xyxy_px": evidence["source_bbox_xyxy_px"],
        "recorded_before_any_recognition_or_adoption": True, "missing_views_do_not_request_recognition": True,
        "views": [{"engine": family, "view_index": index, "normalization": specs[index],
                   "input_array_sha256": prediction["input_array_sha256"], "availability": "ABSENT", "raw_observation_cache": None}
                  for index in range(2) for family, specs in (("Tesseract", SINGLE_LINE_TESSERACT_VIEWS), ("PP-OCR", SINGLE_LINE_PP_OCR_VIEWS))],
    }).encode())
    objects = {"objects": [{"id": "checker-label", "kind": "TEXT", "geometry": {"text": "PANEL-08A"}, "source_evidence": {"single_line_recovery": evidence}}]}
    cold = {"single_line_text_source_checks": [{"id": "checker-label", "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True, "source_replay": {"pass": True, "checker_test_only": True, "new_OCR_calls": 0, "new_model_calls": 0, "source_text_normalization": normalization, "Tesseract_canonical_word_texts": ["PANEL-08A"]}}]}
    summary = {"new_Tesseract_calls": 1, "new_model_calls": 1, "checker_test_only": True}
    (stage / "summary.json").write_text(json.dumps(summary))
    return objects, cold, {"single_line_label_recovery": summary}


def test_single_line_raw_reader_reopens_all_named_payloads_and_counts_actual_receipts(tmp_path):
    objects, cold, report = _raw_checker_fixture(tmp_path)
    result = inspect_single_line_character_payloads(objects, cold, tmp_path, report)
    assert result["accepted_label_raw_files_read_and_hashed"] == 7
    assert result["accepted_label_new_Tesseract_calls"] == 1
    assert result["accepted_label_new_model_calls"] == 1
    assert result["inspection_executed_recognition"] is False


def _asymmetric_known_raw_fixture(tmp_path, availability="OUTPUT_CHECKPOINT"):
    """An artificial 2+1 transport graph, never an optical agreement claim."""
    objects, cold, report = _raw_checker_fixture(tmp_path)
    evidence = objects["objects"][0]["source_evidence"]["single_line_recovery"]
    evidence["recognition_dpi"] = 200

    def record(name, data):
        path = tmp_path / "single_line_labels" / name
        path.write_bytes(data)
        return {"path": path.relative_to(tmp_path).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}

    raw = b"known second Tesseract view; checker-only transport fixture"
    view = deepcopy(evidence["tesseract_views"][0])
    view.update(view_index=1, command_executed_for_this_request=False)
    view["normalization"].update(SINGLE_LINE_TESSERACT_VIEWS[1])
    view["raw_tsv"] = record("known-consumed.tsv", raw)
    metadata = json.loads((tmp_path / evidence["tesseract_views"][0]["metadata"]["path"]).read_text())
    metadata.update(command_executed_for_this_request=False, tsv_sha256=hashlib.sha256(raw).hexdigest())
    reference = evidence["preexisting_raw_view_inventory"]
    inventory = json.loads((tmp_path / reference["path"]).read_text())
    slot = inventory["views"][2]
    slot.update(availability=availability, raw_payload=record("known-original.raw", raw))
    if availability == "OUTPUT_CHECKPOINT":
        slot["checkpoint_metadata"] = record("known-original-metadata.json", json.dumps({**metadata, "command_executed_for_this_request": True}).encode())
    else:
        engine = {"name": "tesseract", "version": "checker-only", "language": "eng", "oem": 1, "CPU_threads": 1,
                  "executable_sha256": "0" * 64, "traineddata_sha256": "1" * 64}
        specification = {"schema": "native-raw-observation-cache-v1", "kind": "tesseract-tsv",
                         "recognition_input": {"sha256": view["normalization"]["input_array_sha256"]},
                         "external_white_padding_px": 16, "psm": 13, "recognition_dpi": 400,
                         "source_pixels_modified": False, "engine": engine}
        key = hashlib.sha256(json.dumps(specification, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        producer = {"checker_test_only": True}
        cache = {"schema": "native-raw-observation-cache-v1", "key": key, "specification": specification,
                 "producer": producer, "payload_sha256": hashlib.sha256(raw).hexdigest(), "payload_bytes": len(raw)}
        slot["cache_record"] = record("known-cache-record.json", json.dumps(cache).encode())
        receipt = {"kind": specification["kind"], "key": key, "producer": producer,
                   "payload_sha256": cache["payload_sha256"], "record_sha256": slot["cache_record"]["sha256"],
                   "same_observation_no_extra_vote": True}
        slot["raw_observation_cache"] = receipt
        metadata.update(raw_observation_cache=receipt, consumer_installed_engine_identity=engine)
    view["metadata"] = record("known-consumed-metadata.json", json.dumps(metadata).encode())
    evidence["tesseract_views"].append(view)
    replacement = record("preexisting_raw_view_inventory.json", json.dumps(inventory).encode())
    reference.update(replacement)
    return objects, cold, report


@pytest.mark.parametrize("availability", ["OUTPUT_CHECKPOINT", "RAW_CACHE"])
def test_raw_reader_accepts_two_Tesseract_one_model_with_every_known_view(availability, tmp_path):
    objects, cold, report = _asymmetric_known_raw_fixture(tmp_path, availability)
    result = inspect_single_line_character_payloads(objects, cold, tmp_path, report)
    label = result["verified_saved_recovery_TEXT"][0]
    assert (label["Tesseract_views"], label["PP_OCR_views"]) == (2, 1)
    assert (label["new_Tesseract_calls"], label["new_model_calls"]) == (1, 1)
    assert label["preexisting_raw_view_inventory"]["known_view_count"] == 1
    assert label["preexisting_raw_view_inventory"]["all_preexisting_views_replayed"] is True


@pytest.mark.parametrize("damage", [
    "known-second-omitted", "view-index-reordered", "duplicate-view-index", "view-index-outside-plan",
    "inventory-missing", "inventory-slot-omitted", "inventory-slot-reordered", "inventory-slot-duplicate",
    "inventory-source-changed", "inventory-input-changed", "inventory-config-changed", "known-original-changed",
    "known-metadata-omitted", "known-view-counted-new", "absent-with-hidden-raw",
])
def test_raw_reader_rejects_hidden_or_changed_preexisting_views(tmp_path, damage):
    objects, cold, report = _asymmetric_known_raw_fixture(tmp_path)
    evidence = objects["objects"][0]["source_evidence"]["single_line_recovery"]
    reference = evidence["preexisting_raw_view_inventory"]
    inventory = json.loads((tmp_path / reference["path"]).read_text())
    slot = inventory["views"][2]
    if damage == "known-second-omitted":
        evidence["tesseract_views"].pop()
    elif damage == "view-index-reordered":
        evidence["tesseract_views"].reverse()
    elif damage == "duplicate-view-index":
        evidence["tesseract_views"][1]["view_index"] = 0
    elif damage == "view-index-outside-plan":
        evidence["tesseract_views"][1]["view_index"] = 2
    elif damage == "inventory-missing":
        evidence.pop("preexisting_raw_view_inventory")
    elif damage == "inventory-slot-omitted":
        inventory["views"].pop()
    elif damage == "inventory-slot-reordered":
        inventory["views"].reverse()
    elif damage == "inventory-slot-duplicate":
        inventory["views"][3] = deepcopy(slot)
    elif damage == "inventory-source-changed":
        inventory["source_array_sha256"] = "2" * 64
    elif damage == "inventory-input-changed":
        slot["input_array_sha256"] = "3" * 64
    elif damage == "inventory-config-changed":
        slot["normalization"]["psm"] = 6
    elif damage == "known-original-changed":
        path = tmp_path / slot["raw_payload"]["path"]
        path.write_bytes(b"altered known original")
        slot["raw_payload"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage == "known-metadata-omitted":
        slot.pop("checkpoint_metadata")
    elif damage == "known-view-counted-new":
        evidence["tesseract_views"][1]["command_executed_for_this_request"] = True
        evidence["new_Tesseract_calls"] = 2
    elif damage == "absent-with-hidden-raw":
        slot["availability"] = "ABSENT"
    payload = json.dumps(inventory).encode()
    (tmp_path / reference["path"]).write_bytes(payload)
    reference["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(AssertionError):
        inspect_single_line_character_payloads(objects, cold, tmp_path, report)


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


def _bounded_checker_fixture(tmp_path, font_path):
    """Synthetic rejected receipts and source bytes, with no claimed OCR run."""
    doc, objects, cold = _saved_checker_fixture(tmp_path, font_path)
    doc.modelspace().delete_entity(next(e for e in doc.modelspace().query("TEXT") if e.dxf.text == SINGLE_LINE_LABEL_FIXTURE[0][0]))
    objects["objects"] = [r for r in objects["objects"] if r["id"] != "checker-label-0"]
    cold["native_text_candidate_checks"] = [r for r in cold["native_text_candidate_checks"] if r["id"] != "checker-label-0"]
    target = tmp_path / "bounded-checker-only.dxf"
    doc.saveas(target)
    objects["dxf_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    source_path = tmp_path / "controlled-source.png"
    create_single_line_fixture(source_path, font_path)
    source = np.asarray(Image.open(source_path))
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_array_sha = hashlib.sha256(source.tobytes()).hexdigest()
    rendered = Image.new("L", (640, 480), 0)
    content, point = SINGLE_LINE_LABEL_FIXTURE[0]
    ImageDraw.Draw(rendered).text(point, content, font=ImageFont.truetype(str(font_path), 26, layout_engine=ImageFont.Layout.BASIC), fill=255)
    box = list(rendered.getbbox())
    x0, y0, x1, y1 = box
    original = np.ascontiguousarray(source[y0:y1, x0:x1])
    evidence_root = tmp_path / "pending-evidence"
    label_dir = evidence_root / "single_line_labels/labels/checker-pending"
    label_dir.mkdir(parents=True)
    manifest = []

    def record(name, payload):
        path = label_dir / name
        path.write_bytes(payload)
        row = {"path": path.relative_to(evidence_root).as_posix(), "sha256": hashlib.sha256(payload).hexdigest()}
        manifest.append(row)
        return row

    def png(array):
        stream = BytesIO()
        Image.fromarray(array).save(stream, format="PNG")
        return stream.getvalue()

    def normalized(spec):
        array = np.pad(np.repeat(np.repeat(original, spec["scale"], axis=0), spec["scale"], axis=1), spec["padding"], constant_values=255)
        return array, {**spec, "source_bbox_xyxy_px": box,
                       "input_array_sha256": hashlib.sha256(array.tobytes()).hexdigest(), "original_source_pixels_modified": False}

    ta, tn = normalized(SINGLE_LINE_TESSERACT_VIEWS[0])
    t_png = png(ta)
    t_bytes = b"synthetic rejected raw receipt; never actual optical recognition"
    t_image = record("t-view.png", t_png)
    tsv = record("t-view.tsv", t_bytes)
    metadata = record("t-view.json", json.dumps({"status": "COMPLETED", "return_code": 0, "command_executed_for_this_request": True,
                                                 "tsv_sha256": hashlib.sha256(t_bytes).hexdigest(), "image_sha256": hashlib.sha256(t_png).hexdigest()}).encode())
    pa, pn = normalized(SINGLE_LINE_PP_OCR_VIEWS[0])
    prediction = {"raw_text": content, "input_array_sha256": pn["input_array_sha256"], "raw_transcription_rewritten": False,
                  "source_geometry_modified": False, "checker_test_only": True}
    prediction_file = record("p-view.json", json.dumps(prediction).encode())
    p_image = record("p-view.png", png(pa))
    mask = original < 192
    runs = []
    for y, row in enumerate(mask):
        delta = np.diff(np.r_[False, row, False].astype("int8"))
        runs.extend([[y + y0, int(a + x0), int(b + x0)] for a, b in zip(np.flatnonzero(delta == 1), np.flatnonzero(delta == -1))])
    reasons = ["SYNTHETIC_UNRESOLVED_FULL_LABEL_FOR_CHECKER_TEST_ONLY"]
    evidence = {
        "schema": "native-single-line-label-evidence-v1", "checker_test_only": True,
        "source_bbox_xyxy_px": box, "original_source": record("original_source.png", png(original)),
        "source_partition": {"bbox_xyxy_px": box, "source_support_runs_y_x0_x1": runs, "all_label_ink_assigned": True,
                             "recognition_excluded_graphic_runs_y_x0_x1": [], "original_source_pixels_modified": False},
        "model_identity": record("model_identity.json", json.dumps({"providers": ["CPUExecutionProvider"], "checker_test_only": True}).encode()),
        "decision": {"accepted": False, "text": None, "reasons": reasons},
        "policy": {"Tesseract_views": list(SINGLE_LINE_TESSERACT_VIEWS), "PP_OCR_views": list(SINGLE_LINE_PP_OCR_VIEWS), "maximum_views_per_engine": 2},
        "expected_answers_provided": False, "original_source_pixels_modified": False, "raw_transcription_rewritten": False,
        "tesseract_views": [{"view_index": 0, "normalization": tn, "raw_tsv": tsv, "metadata": metadata, "recognition_image": t_image, "command_executed_for_this_request": True}],
        "ppocr_views": [{"view_index": 0, "normalization": pn, "prediction_file": prediction_file, "recognition_image": p_image, "prediction": prediction,
                         "model_inference_executed_for_this_request": True, "observation_receipt": {"model_inference_executed_for_this_request": True}}],
        "new_Tesseract_calls": 1, "new_model_calls": 1,
    }
    evidence["source_array_sha256"] = source_array_sha
    evidence["preexisting_raw_view_inventory"] = record("preexisting_raw_view_inventory.json", json.dumps({
        "schema": "single-line-preexisting-raw-view-inventory-v1", "source_array_sha256": source_array_sha,
        "source_bbox_xyxy_px": box, "recorded_before_any_recognition_or_adoption": True,
        "missing_views_do_not_request_recognition": True,
        "views": [{"engine": family, "view_index": index, "normalization": specs[index],
                   "input_array_sha256": (tn if family == "Tesseract" else pn)["input_array_sha256"],
                   "availability": "ABSENT", "raw_observation_cache": None}
                  for index in range(2) for family, specs in (("Tesseract", SINGLE_LINE_TESSERACT_VIEWS), ("PP-OCR", SINGLE_LINE_PP_OCR_VIEWS))],
    }).encode())
    result = {"accepted": False, "text": None, "geometry": None, "bbox_xyxy_px": box, "reasons": reasons,
              "evidence": evidence, "new_Tesseract_calls": 1, "new_model_calls": 1}
    record("label_result.json", json.dumps(result).encode())
    attempt = {"id": "checker-pending", "region_ids": ["pending-region"], "accepted": False, "text": None,
               "bbox_xyxy_px": box, "reasons": reasons, "new_Tesseract_calls": 1, "new_model_calls": 1}
    summary = {"source_sha256": source_sha, "source_array_sha256": source_array_sha, "attempts": [attempt],
               "pending_labels": 1, "new_Tesseract_calls": 1, "new_model_calls": 1, "raw_evidence_files": manifest}
    group = {"id": "pending-group", "region_ids": ["pending-region"], "bbox_xyxy_px": box, "text": "UNRESOLVED RAW OBSERVATION", "complete": False, "unresolved_reasons": reasons}
    completed = {"source_array_sha256": source_array_sha, "regions": [{"id": "pending-region", "complete": False, "unresolved_reasons": reasons}], "groups": [group]}
    uncertainty = {"id": "pending-group", "bbox_xyxy_px": box, "reason": reasons}
    issue = {"id": "pending-issue", "bbox_xyxy_px": box, "status": "PENDING_SOURCE_REPAIR",
             "source_support": {"uncertainty_record_index": 0, "details_file": "quality_uncertainties.json"},
             "binding": {"source_file_sha256": source_sha, "saved_DXF_sha256": objects["dxf_sha256"]}}
    for path, value in (("single_line_labels/summary.json", summary), ("single_line_labels/completed_text.json", completed),
                        ("quality_uncertainties.json", [uncertainty]), ("quality_issues.json", {"issues": [issue]})):
        (evidence_root / path).write_text(json.dumps(value))
    return doc, objects, cold, evidence_root, source_path, {"single_line_label_recovery": summary}


def test_bounded_capability_reports_two_complete_one_pending_and_preserves_strict_failure(tmp_path, checker_font):
    doc, objects, cold, evidence, source, report = _bounded_checker_fixture(tmp_path, checker_font)
    result = inspect_bounded_single_line_members(doc, objects, cold, checker_font, evidence, source, report)
    assert result["supported_capability_pass"]
    assert result["complete_count"] == 2 and result["pending_count"] == 1 and result["new_recovery_count"] == 1
    assert result["strict_three_complete_status"] == "FAIL" and result["strict_three_complete_inspector_executed"]
    assert result["strict_three_complete_failure"] == "Single-line fixture did not save one complete literal TEXT per label/control"
    assert not result["all_labels_are_single_top_level_TEXT"]
    assert result["pending_labels"][0]["counted_as_complete"] is False
    with pytest.raises(AssertionError, match="complete literal TEXT per label"):
        inspect_single_line_members(doc, objects, cold, checker_font)


def test_bounded_contract_still_allows_three_complete_source_bound_labels(tmp_path, checker_font):
    doc, objects, cold = _saved_checker_fixture(tmp_path, checker_font, recovery_indices=(0, 1))
    result = inspect_bounded_single_line_members(doc, objects, cold, checker_font, tmp_path, tmp_path / "unused.png", {})
    assert result["strict_three_complete_status"] == "PASS"
    assert result["complete_count"] == 3 and result["pending_count"] == 0 and result["new_recovery_count"] == 2
    assert result["strict_three_complete_failure"] is None


@pytest.mark.parametrize("damage", ["wrong-letter", "prefix", "extra-glyph", "missing-required-label", "ordinary-control",
                                   "lost-short-stroke", "neighbor-displaced", "no-PANEL-recovery", "failed-PANEL-source",
                                   "missing-pending-attempt", "pending-reason-empty", "pending-group-disappeared", "pending-marked-complete",
                                   "pending-quality-issue-disappeared", "pending-quality-wrong-DXF", "pending-raw-missing", "pending-raw-modified",
                                   "pending-original-modified", "pending-source-support-truncated", "pending-no-real-call"])
def test_bounded_contract_rejects_false_completion_disappearing_pending_and_damaged_neighbors(tmp_path, checker_font, damage):
    doc, objects, cold, evidence, source, report = _bounded_checker_fixture(tmp_path, checker_font)
    texts, lines = list(doc.modelspace().query("TEXT")), list(doc.modelspace().query("LINE"))
    summary = report["single_line_label_recovery"]

    def change_json(name, change):
        path = evidence / name
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def change_pending(change):
        name = "single_line_labels/labels/checker-pending/label_result.json"
        change_json(name, change)
        for row in summary["raw_evidence_files"]:
            if row["path"] == name:
                row["sha256"] = hashlib.sha256((evidence / name).read_bytes()).hexdigest()

    if damage in ("wrong-letter", "prefix"):
        doc.modelspace().add_text("AHU-27B, 24" if damage == "wrong-letter" else "AHU-27B,", dxfattribs={"height": 2})
    elif damage == "extra-glyph":
        doc.modelspace().add_line((10, 10), (10, 12))
    elif damage == "missing-required-label":
        doc.modelspace().delete_entity(texts[0])
    elif damage == "ordinary-control":
        next(e for e in texts if e.dxf.text == "STORE").dxf.text = "ST0RE"
    elif damage == "lost-short-stroke":
        doc.modelspace().delete_entity(lines[-1])
    elif damage == "neighbor-displaced":
        lines[-1].dxf.end = lines[-1].dxf.end + (4, 0, 0)
    elif damage == "no-PANEL-recovery":
        next(r for r in objects["objects"] if r["id"] == "checker-label-1").pop("source_evidence")
        cold["single_line_text_source_checks"] = []
    elif damage == "failed-PANEL-source":
        cold["single_line_text_source_checks"][0]["pass"] = False
    elif damage == "missing-pending-attempt":
        summary["attempts"] = []
    elif damage == "pending-reason-empty":
        summary["attempts"][0]["reasons"] = []
    elif damage == "pending-group-disappeared":
        change_json("single_line_labels/completed_text.json", lambda value: value.update(groups=[]))
    elif damage == "pending-marked-complete":
        change_json("single_line_labels/completed_text.json", lambda value: value["groups"][0].update(complete=True))
    elif damage == "pending-quality-issue-disappeared":
        change_json("quality_issues.json", lambda value: value.update(issues=[]))
    elif damage == "pending-quality-wrong-DXF":
        change_json("quality_issues.json", lambda value: value["issues"][0]["binding"].update(saved_DXF_sha256="stale"))
    elif damage == "pending-raw-missing":
        (evidence / "single_line_labels/labels/checker-pending/t-view.tsv").unlink()
    elif damage == "pending-raw-modified":
        (evidence / "single_line_labels/labels/checker-pending/t-view.tsv").write_text("tampered")
    elif damage == "pending-original-modified":
        path = evidence / "single_line_labels/labels/checker-pending/original_source.png"
        image = Image.open(path)
        image.putpixel((1, 1), 255 - image.getpixel((1, 1)))
        image.save(path)
        new_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        change_pending(lambda value: value["evidence"]["original_source"].update(sha256=new_sha))
        next(row for row in summary["raw_evidence_files"] if row["path"].endswith("/original_source.png"))["sha256"] = new_sha
    elif damage == "pending-source-support-truncated":
        change_pending(lambda value: value["evidence"]["source_partition"]["source_support_runs_y_x0_x1"].pop())
    else:
        change_pending(lambda value: value["evidence"]["tesseract_views"][0].update(command_executed_for_this_request=False))
    (evidence / "single_line_labels/summary.json").write_text(json.dumps(summary))
    path = tmp_path / "bounded-damage.dxf"
    doc.saveas(path)
    with pytest.raises(AssertionError):
        inspect_bounded_single_line_members(ezdxf.readfile(path), objects, cold, checker_font, evidence, source, report)
