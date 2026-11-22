"""Finite-view recognition decisions and raw-evidence replay integrity.

The raw engine records here are controlled synthetic fixtures.  They exercise
source binding, decision rules and orchestration, not OCR accuracy.  Real-sheet
recognition and the Windows packaged-engine smoke remain separate evidence.
"""

from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
from PIL import Image
import pytest

from app.native_objects import cad_io
from app.native_objects import circle_character_recognition as character
from app.native_objects import independent_recognizer as independent
from app.native_objects import text_regions as base
from app.native_objects.circular_markers import discover_circular_markers


BOX = [70, 65, 84, 87]


def _tview(text="F", confidence=96.0, box=BOX):
    return {
        "words": [{"text": text, "confidence": confidence, "bbox_xyxy_px": list(box)}]
    }


def _prediction(text="F", score=0.999):
    tokens = [
        {
            "time_step": index + 1,
            "token_index": 40 + index,
            "character": value,
            "score": score,
        }
        for index, value in enumerate(text)
    ]
    return {
        "raw_text": text,
        "raw_CTC_tokens": tokens,
        "model_mean_confidence": score if tokens else None,
        "minimum_emitted_character_confidence": score if tokens else None,
    }


def _pview(text="F", score=0.999):
    return {"prediction": _prediction(text, score)}


def test_complete_original_glyph_requires_two_independent_raw_engines():
    accepted = character._decision([_tview()], [_pview()], BOX)
    assert accepted["accepted"] and accepted["text"] == "F"
    for t_views, p_views in [([_tview()], []), ([], [_pview()])]:
        assert not character._decision(t_views, p_views, BOX)["accepted"]


def test_second_view_can_recover_only_with_the_same_complete_source_character():
    result = character._decision(
        [_tview("F", 84.29), _tview("F", 96)],
        [_pview("F", 0.96), _pview("F", 0.999)],
        BOX,
    )
    assert result["accepted"] and result["text"] == "F"


@pytest.mark.parametrize(
    "conflict", ["other-character", "multichar", "multiple-words", "model"]
)
def test_any_reliable_conflicting_view_keeps_the_character_unresolved(conflict):
    t_views, p_views = [_tview()], [_pview()]
    if conflict == "other-character":
        t_views.append(_tview("J"))
    elif conflict == "multichar":
        t_views.append(_tview("Ff"))
    elif conflict == "multiple-words":
        t_views.append({"words": _tview()["words"] + _tview("J")["words"]})
    else:
        p_views.append(_pview("C"))
    result = character._decision(t_views, p_views, BOX)
    assert not result["accepted"] and result["text"] is None
    assert "HIGH_CONFIDENCE_RAW_OBSERVATIONS_CONFLICT" in result["reasons"]


@pytest.mark.parametrize("text", ["Ff", " F", "F ", "-", "é"])
def test_raw_strings_are_not_trimmed_or_rewritten_to_an_expected_character(text):
    result = character._decision([_tview(text)], [_pview(text)], BOX)
    assert not result["accepted"] and result["text"] is None


@pytest.mark.parametrize("text", ["I", "l", "1", "O", "0"])
def test_unresolved_similar_character_classes_stay_unresolved(text):
    result = character._decision([_tview(text, 99)], [_pview(text)], BOX)
    assert not result["accepted"]
    assert "CHARACTER_CLASS_NEEDS_ADDITIONAL_SOURCE_DISCRIMINATION" in result["reasons"]


@pytest.mark.parametrize(
    "text,score,accepted",
    [("F", 84.99, False), ("F", 85, True), ("7", 94.99, False), ("7", 95, True)],
)
def test_word_and_numeric_thresholds_are_preserved(text, score, accepted):
    result = character._decision([_tview(text, score)], [_pview(text)], BOX)
    assert result["accepted"] is accepted


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), -1, 101, 500, True])
def test_malformed_tesseract_view_blocks_an_otherwise_good_pair(bad_score):
    result = character._decision(
        [_tview(), _tview(confidence=bad_score)], [_pview()], BOX
    )
    assert not result["accepted"]
    assert "TESSERACT_RAW_SCORE_NONFINITE_OR_OUT_OF_RANGE" in result["reasons"]


@pytest.mark.parametrize(
    "damage",
    ["low-raw-token", "mean", "minimum", "nan", "infinity", "out-of-range", "raw-text"],
)
def test_ctc_tokens_and_summary_must_be_internally_consistent(damage):
    bad = _pview()
    record = bad["prediction"]
    if damage == "low-raw-token":
        record["raw_CTC_tokens"][0]["score"] = 0.1
    elif damage == "mean":
        record["model_mean_confidence"] = 0.99
    elif damage == "minimum":
        record["minimum_emitted_character_confidence"] = 0.99
    elif damage == "raw-text":
        record["raw_text"] = "J"
    else:
        value = {"nan": float("nan"), "infinity": float("inf"), "out-of-range": 1.1}[
            damage
        ]
        record["raw_CTC_tokens"][0]["score"] = value
        record["model_mean_confidence"] = value
        record["minimum_emitted_character_confidence"] = value
    result = character._decision([_tview()], [_pview(), bad], BOX)
    assert not result["accepted"]
    assert "MODEL_RAW_CHARACTER_SCORE_OR_TOKEN_INCONSISTENCY" in result["reasons"]


def test_tesseract_cannot_confirm_only_the_interior_of_a_complete_glyph():
    result = character._decision([_tview(box=[73, 68, 81, 85])], [_pview()], BOX)
    assert not result["accepted"]
    assert "TESSERACT_NO_CONFIDENT_COMPLETE_SOURCE_CHARACTER" in result["reasons"]


def test_nearest_neighbor_view_preserves_original_samples_and_maps_source_coordinates():
    crop = np.array([[0, 52, 255], [177, 0, 240]], dtype=np.uint8)
    original = crop.copy()
    normalized, padded = character._view_input(crop, 2, 4)
    assert normalized.shape == (4, 6) and padded.shape == (12, 14)
    assert np.array_equal(normalized[::2, ::2], crop)
    assert np.array_equal(normalized[1::2, 1::2], crop)
    assert np.array_equal(padded[4:-4, 4:-4], normalized)
    assert np.all(padded[:4] == 255) and np.all(padded[:, :4] == 255)
    assert np.array_equal(crop, original)
    local = _tview(box=[0, 0, 28, 44])["words"]
    mapped = character._map_tesseract_words(local, BOX, 2)
    assert mapped[0]["bbox_xyxy_px"] == BOX
    assert local[0]["bbox_xyxy_px"] == [0, 0, 28, 44]


def _source_row():
    image = np.full((160, 180), 255, np.uint8)
    cv2.circle(image, (80, 80), 20, 0, 3)
    cv2.line(image, (75, 72), (75, 88), 0, 2)
    cv2.line(image, (75, 72), (85, 72), 0, 2)
    cv2.line(image, (75, 80), (82, 80), 0, 2)
    cv2.line(image, (100, 80), (135, 71), 0, 2)
    roi = [0, 0, image.shape[1], image.shape[0]]
    rows = [
        row
        for row in discover_circular_markers(image, roi)["rows"]
        if row["geometry_accepted"]
    ]
    assert len(rows) == 1
    return image, roi, rows[0]


def _hash(data):
    return hashlib.sha256(data).hexdigest()


class _RawModelFixture:
    """Controlled raw records; never used to claim actual model accuracy."""

    def __init__(self, observations):
        self.observations = observations
        self.calls = []
        self.identity = {
            "model_sha256": independent.MODEL_SHA256,
            "policy": deepcopy(independent.POLICY),
        }

    def recognize(self, image):
        text, confidence = self.observations[len(self.calls)]
        self.calls.append(image.copy())
        original, tensor = independent.prepare_model_input(image)
        record = _prediction(text, confidence)
        record.update(
            {
                "input_array_sha256": _hash(original.tobytes()),
                "input_shape_px": list(original.shape),
                "model_tensor_sha256": _hash(tensor.tobytes()),
                "model_tensor_shape": list(tensor.shape),
                "source_geometry_modified": False,
                "raw_transcription_rewritten": False,
            }
        )
        self.last_observation = {"model_inference_executed_for_this_request": True}
        return record


def _recognized_fixture(tmp_path, monkeypatch, *, t_words=None, p_words=None):
    gray, roi, row = _source_row()
    original = gray.copy()
    t_words = t_words or [("F", 96)]
    model = _RawModelFixture(p_words or [("F", 0.999)])
    tess_calls = []

    def raw_ocr(image, box, psm, directory, name, progress, padding_px=0, *, dpi=200):
        text, confidence = t_words[len(tess_calls)]
        tess_calls.append(
            {"box": list(box), "psm": psm, "padding": padding_px, "dpi": dpi}
        )
        x0, y0, x1, y1 = box
        crop = np.ascontiguousarray(image[y0:y1, x0:x1])
        actual = np.pad(crop, padding_px, constant_values=255)
        png, tsv, meta = (
            directory / (name + suffix) for suffix in (".png", ".tsv", ".json")
        )
        Image.fromarray(actual).save(png)
        raw = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            f"5\t1\t1\t1\t1\t1\t{padding_px}\t{padding_px}\t{x1 - x0}\t{y1 - y0}\t{confidence}\t{text}\n"
        )
        tsv.write_text(raw, encoding="utf-8")
        metadata = {
            "status": "COMPLETED",
            "return_code": 0,
            "tsv_sha256": _hash(tsv.read_bytes()),
            "image_sha256": _hash(png.read_bytes()),
            "command_executed_for_this_request": True,
            "specification": {
                "crop_xyxy_px": list(box),
                "crop_array_sha256": base.source_array_sha256(crop),
                "psm": psm,
                "external_white_padding_px": padding_px,
                "language": "eng",
                "source_pixels_modified": False,
                "recognition_dpi": dpi,
            },
        }
        meta.write_text(json.dumps(metadata), encoding="utf-8")
        origin = [x0 - padding_px, y0 - padding_px, x1 + padding_px, y1 + padding_px]
        return base._parse_tsv(raw, origin, name, psm), metadata

    monkeypatch.setattr(base, "_ocr", raw_ocr)
    monkeypatch.setattr(
        base, "_resolve_tesseract", lambda *args: {"fixture_only": True}
    )
    result = character.recognize_circle_character(
        gray,
        roi,
        row,
        tmp_path,
        recognizer=model,
        evidence_root=tmp_path,
    )
    assert np.array_equal(gray, original)
    obj = {
        "id": row["id"],
        "kind": "CIRCULAR_MARKER",
        "layer": "CIRCULAR_MARKERS",
        "geometry": {
            "circle_geometry": row["geometry"],
            "text_geometry": result["text_geometry"],
        },
        "source_evidence": {
            **deepcopy(row["source_evidence"]),
            "components_complete": True,
            "character_evidence": result["evidence"],
        },
    }
    return gray, roi, obj, result, tess_calls, model


def test_initial_consensus_stops_after_one_pair_and_cold_reads_without_any_recognition(
    tmp_path, monkeypatch
):
    gray, roi, obj, result, t_calls, model = _recognized_fixture(tmp_path, monkeypatch)
    assert result["accepted"] and len(t_calls) == len(model.calls) == 1
    assert result["new_Tesseract_calls"] == result["new_model_calls"] == 1

    def forbidden(*args, **kwargs):
        pytest.fail("Cold evidence verification must never execute recognition")

    monkeypatch.setattr(base, "_ocr", forbidden)
    monkeypatch.setattr(independent, "IndependentRecognizer", forbidden)
    audited = character.verify_circle_character_evidence(gray, roi, obj, tmp_path)
    assert audited["pass"], audited
    assert audited["new_OCR_calls"] == audited["new_model_calls"] == 0
    assert audited["Tesseract_views_replayed"] == audited["PP_OCR_views_replayed"] == 1
    assert audited["all_raw_artifacts_read_and_hashed"]
    assert audited["original_glyph_pixels_and_model_tensors_rechecked"]


def test_fallback_runs_only_two_bounded_views_and_cold_replays_normalization(
    tmp_path, monkeypatch
):
    gray, roi, obj, result, t_calls, model = _recognized_fixture(
        tmp_path,
        monkeypatch,
        t_words=[("F", 84.29), ("F", 96)],
        p_words=[("F", 0.96), ("F", 0.999)],
    )
    assert result["accepted"] and len(t_calls) == len(model.calls) == 2
    assert t_calls[1]["padding"] == 16 and t_calls[1]["dpi"] == 400
    box = result["evidence"]["source_bbox_xyxy_px"]
    assert t_calls[1]["box"] == [0, 0, 2 * (box[2] - box[0]), 2 * (box[3] - box[1])]
    assert model.calls[0].shape == (box[3] - box[1] + 8, box[2] - box[0] + 8)
    assert model.calls[1].shape == (box[3] - box[1], box[2] - box[0])
    audited = character.verify_circle_character_evidence(gray, roi, obj, tmp_path)
    assert audited["pass"], audited
    assert audited["Tesseract_views_replayed"] == audited["PP_OCR_views_replayed"] == 2


def test_saved_native_marker_cold_gate_includes_actual_ring_and_raw_character_proof(
    tmp_path, monkeypatch
):
    gray, roi, obj, result, _, _ = _recognized_fixture(tmp_path, monkeypatch)
    assert result["accepted"]
    path = tmp_path / "marker.dxf"
    cad_io.export_objects([obj], path, roi, 200, _hash(gray.tobytes()))
    report = cad_io.cold_audit(path, gray, roi, 200, tmp_path / "cold.json")
    assert report["source_gate_pass"], report["source_checks"]
    assert report["formal_modelspace_types"] == {"INSERT": 1}
    assert report["expanded_formal_types"] == {"CIRCLE": 1, "TEXT": 1}
    assert report["exact_duplicate_segments"] == []
    (binding,) = report["circular_marker_source_checks"]
    assert binding["pass"] and binding["ring_source"]["pass"]
    assert binding["character_source"]["pass"]
    assert all(binding["saved_candidate_checks"].values())
    ring = next(row for row in report["source_checks"] if row["type"] == "CIRCLE")
    assert ring["pass"] and ring["sampled_sweep_deg"] == 360
    raw = result["evidence"]["ppocr_views"][0]["prediction_file"]["path"]
    (tmp_path / raw).unlink()
    missing = cad_io.cold_audit(path, gray, roi, 200, tmp_path / "missing.json")
    assert not missing["source_gate_pass"]
    assert missing["circular_marker_source_checks"][0]["ring_source"]["pass"]
    assert not missing["circular_marker_source_checks"][0]["character_source"]["pass"]


def test_ambiguous_class_does_not_trigger_redundant_fallback_recognition(
    tmp_path, monkeypatch
):
    _, _, _, result, t_calls, model = _recognized_fixture(
        tmp_path,
        monkeypatch,
        t_words=[("O", 99)],
        p_words=[("O", 0.999)],
    )
    assert not result["accepted"] and result["text_geometry"] is None
    assert len(t_calls) == len(model.calls) == 1


def test_malformed_raw_tsv_score_cannot_disappear_in_generic_word_parser(
    tmp_path, monkeypatch
):
    # The ordinary TSV parser omits nonfinite words.  A later valid view must
    # not make malformed original raw evidence look like an ordinary blank.
    _, _, _, result, _, _ = _recognized_fixture(
        tmp_path,
        monkeypatch,
        t_words=[("F", float("nan")), ("F", 96)],
        p_words=[("F", 0.999), ("F", 0.999)],
    )
    assert not result["accepted"] and result["text_geometry"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("left", "not-an-integer"), ("top", "nan"),
        ("width", "0"), ("height", "-1"),
        ("width", "inf"), ("height", "1.5"),
        ("left", "-1"), ("top", "-1"),
        ("word_num", "not-an-integer"), ("level", "05"),
        ("text", " J"), ("text", "J "),
    ],
)
def test_nonempty_raw_word_cannot_be_hidden_by_malformed_fields(field, value):
    columns = [
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    ]
    good = ["5", "1", "1", "1", "1", "1", "0", "0", "14", "22", "96", "F"]
    bad = ["5", "1", "1", "1", "1", "2", "0", "0", "14", "22", "99", "J"]
    bad[columns.index(field)] = value
    raw = ("\t".join(columns) + "\n" + "\t".join(good)
           + "\n" + "\t".join(bad) + "\n").encode("utf-8")
    original = bytes(raw)
    integrity = character._raw_tsv_integrity(raw)
    assert not integrity
    # Even if the shared permissive parser retained only the valid F, the
    # untouched raw record must prevent that manufactured single-word vote.
    view = {**_tview(), "raw_tsv_integrity": integrity}
    decision = character._decision([view], [_pview()], BOX)
    assert not decision["accepted"] and decision["text"] is None
    assert raw == original


def test_cold_rejects_rehashed_raw_word_discarded_by_shared_parser(tmp_path, monkeypatch):
    gray, roi, obj, result, _, _ = _recognized_fixture(tmp_path, monkeypatch)
    assert result["accepted"]
    view = obj["source_evidence"]["character_evidence"]["tesseract_views"][0]
    raw_path = tmp_path / view["raw_tsv"]["path"]
    # The shared parser drops a zero-width high-confidence J. Update both
    # hashes so the source gate must inspect the record, not just its digest.
    malformed = b"5\t1\t1\t1\t1\t2\t4\t4\t0\t17\t99\tJ\n"
    raw_path.write_bytes(raw_path.read_bytes() + malformed)
    view["raw_tsv"]["sha256"] = _hash(raw_path.read_bytes())
    metadata_path = tmp_path / view["metadata"]["path"]
    metadata = json.loads(metadata_path.read_bytes())
    metadata["tsv_sha256"] = view["raw_tsv"]["sha256"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    view["metadata"]["sha256"] = _hash(metadata_path.read_bytes())

    def forbidden(*args, **kwargs):
        pytest.fail("Cold raw validation must not execute recognition")

    monkeypatch.setattr(base, "_ocr", forbidden)
    monkeypatch.setattr(independent, "IndependentRecognizer", forbidden)
    audited = character.verify_circle_character_evidence(gray, roi, obj, tmp_path)
    assert not audited["pass"], audited
    assert audited["reason"] == "CHARACTER_TESSERACT_RAW_TSV_INVALID_WORD_SCORE_OR_STRUCTURE"
    assert audited["new_OCR_calls"] == audited["new_model_calls"] == 0
    assert raw_path.read_bytes().endswith(malformed)


@pytest.mark.parametrize(
    "damage",
    [
        "source-pixel",
        "source-hash",
        "raw-tsv",
        "rehash-png",
        "rehash-model-tensor",
        "rehash-model-input",
        "rehash-model-token",
        "rehash-model-identity",
        "text-content",
        "text-geometry",
        "missing-file",
        "third-view",
    ],
)
def test_cold_rejects_changed_raw_source_normalization_or_saved_character(
    tmp_path, monkeypatch, damage
):
    gray, roi, obj, result, _, _ = _recognized_fixture(tmp_path, monkeypatch)
    assert result["accepted"]
    evidence = obj["source_evidence"]["character_evidence"]

    def replace_json(record, mutate):
        path = tmp_path / record["path"]
        content = json.loads(path.read_bytes())
        mutate(content)
        path.write_text(json.dumps(content), encoding="utf-8")
        record["sha256"] = _hash(path.read_bytes())

    if damage == "source-pixel":
        x, y = evidence["source_bbox_xyxy_px"][:2]
        gray[y, x] = 255 - gray[y, x]
    elif damage == "source-hash":
        evidence["source_crop_array_sha256"] = "0" * 64
    elif damage == "raw-tsv":
        path = tmp_path / evidence["tesseract_views"][0]["raw_tsv"]["path"]
        path.write_text(path.read_text().replace("\tF\n", "\tJ\n"))
    elif damage == "rehash-png":
        view = evidence["tesseract_views"][0]
        path = tmp_path / view["recognition_image"]["path"]
        pixels = np.array(Image.open(path))
        pixels[0, 0] = 0
        Image.fromarray(pixels).save(path)
        view["recognition_image"]["sha256"] = _hash(path.read_bytes())
        replace_json(
            view["metadata"],
            lambda value: value.update({"image_sha256": _hash(path.read_bytes())}),
        )
    elif damage.startswith("rehash-model-") and damage != "rehash-model-identity":

        def mutate(value):
            if damage == "rehash-model-token":
                value["raw_CTC_tokens"][0]["score"] = 0.1
            else:
                key = (
                    "model_tensor_sha256"
                    if damage == "rehash-model-tensor"
                    else "input_array_sha256"
                )
                value[key] = "0" * 64

        replace_json(evidence["ppocr_views"][0]["prediction_file"], mutate)
    elif damage == "rehash-model-identity":
        replace_json(
            evidence["model_identity"],
            lambda value: value.update({"model_sha256": "0" * 64}),
        )
    elif damage == "text-content":
        obj["geometry"]["text_geometry"]["text"] = "J"
    elif damage == "text-geometry":
        obj["geometry"]["text_geometry"]["width_px"] += 2
    elif damage == "missing-file":
        (tmp_path / evidence["ppocr_views"][0]["prediction_file"]["path"]).unlink()
    else:
        evidence["tesseract_views"] *= 3
        evidence["ppocr_views"] *= 3
    audited = character.verify_circle_character_evidence(gray, roi, obj, tmp_path)
    assert not audited["pass"], audited
    assert audited["new_OCR_calls"] == audited["new_model_calls"] == 0


@pytest.mark.parametrize(
    "path", ["../outside.json", "/outside.json", "nested\\outside.json"]
)
def test_raw_evidence_paths_cannot_leave_job_root(tmp_path, path):
    with pytest.raises(ValueError, match="CHARACTER_RAW_EVIDENCE"):
        character._read_record(tmp_path, {"path": path, "sha256": "0" * 64})


def test_raw_evidence_symlink_cannot_substitute_outside_file(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    root = tmp_path / "job"
    root.mkdir()
    try:
        (root / "linked.json").symlink_to(outside)
    except OSError:
        pytest.skip("Creating a symlink requires unavailable platform privileges")
    with pytest.raises(ValueError, match="CHARACTER_RAW_EVIDENCE"):
        character._read_record(
            root, {"path": "linked.json", "sha256": _hash(outside.read_bytes())}
        )
