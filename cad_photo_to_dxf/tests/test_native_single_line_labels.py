"""Source ownership and cold replay; synthetic engine records, not OCR accuracy."""

from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
from PIL import Image
import pytest

from app.native_objects import independent_recognizer as independent
from app.native_objects import single_line_labels as labels
from app.native_objects import text_regions as base
from app.native_objects.contracts import COORDINATES, validate_text_regions


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _drawing(text="AB-12,3"):
    gray = np.full((190, 500), 255, np.uint8)
    cv2.putText(gray, text, (35, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.85, 0, 1, cv2.LINE_8)
    yy, xx = np.where(gray < 192)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    roi = [0, 0, 500, 190]
    part, error = labels._partition(gray, roi, box)
    assert not error, error
    return gray, roi, box, part


def _contract(gray, roi, box, complete=False):
    return {
        "coordinate_system": COORDINATES,
        "source_size_px": [gray.shape[1], gray.shape[0]],
        "roi_xyxy_px": roi,
        "source_array_sha256": base.source_array_sha256(gray),
        "regions": [
            {
                "id": "R1",
                "bbox_xyxy_px": box,
                "discovery_bbox_xyxy_px": box,
                "text": "UNKNOWN",
                "complete": complete,
                "enclosure": None,
                "words": [],
            }
        ],
        "groups": [
            {
                "id": "G1",
                "geometry_type": "TEXT",
                "region_ids": ["R1"],
                "complete": complete,
                "text": "UNKNOWN",
            }
        ],
    }


def _prediction(text, score=0.999, space_score=None):
    tokens = [
        {
            "time_step": i + 1,
            "token_index": 50 + i,
            "character": c,
            "score": space_score if c == " " and space_score is not None else score,
        }
        for i, c in enumerate(text)
    ]
    return {
        "raw_text": text,
        "raw_CTC_tokens": tokens,
        "model_mean_confidence": sum(t["score"] for t in tokens) / len(tokens),
        "minimum_emitted_character_confidence": min(t["score"] for t in tokens),
    }


def _tview(text, part, confidence=96):
    return {
        "words": [
            {
                "text": text,
                "confidence": confidence,
                "bbox_xyxy_px": part["bbox_xyxy_px"],
            }
        ],
        "raw_tsv_integrity": True,
    }


def test_complete_source_order_covers_every_glyph_and_punctuation():
    gray, roi, box, part = _drawing()
    assert (
        part["full_height_component_count"] == 5
        and part["punctuation_component_count"] == 2
    )
    assert labels._source_canonical_text("AB-12,3", part)["text"] == "AB-12,3"
    for wrong in ["AB-12", "AB12,3", "AB-123", "AB-12,", "AB-12,34", "AB 12,3"]:
        assert labels._source_canonical_text(wrong, part)["reasons"], wrong
    normalized, padded = labels._view(gray, part, 2, 16)
    assert np.array_equal(normalized[::2, ::2], gray[box[1] : box[3], box[0] : box[2]])
    assert np.all(padded[:16] == 255)


def test_low_space_confidence_uses_true_gap_and_unicode_quote_uses_two_strokes():
    _, _, _, part = _drawing('TAG "B2"')
    t = _tview('TAG "B2”', part)
    p = {"prediction": _prediction('TAG "B2"', space_score=0.2)}
    result = labels._decision([t], [p], part)
    assert result["accepted"], result
    assert result["text"] == 'TAG "B2"'
    assert len(result["source_text_normalization"]["normalizations"]) == 1
    assert (
        result["source_text_normalization"]["word_spaces"][0]["original_white_gap_px"]
        > 0
    )
    assert (
        t["words"][0]["text"] == 'TAG "B2”'
        and p["prediction"]["raw_text"] == 'TAG "B2"'
    )


@pytest.mark.parametrize("character", ["B", "2", '"'])
def test_low_real_character_cannot_use_the_whitespace_exception(character):
    _, _, _, part = _drawing('TAG "B2"')
    p = _prediction('TAG "B2"', space_score=0.2)
    for token in p["raw_CTC_tokens"]:
        if token["character"] == character:
            token["score"] = 0.70
    scores = [t["score"] for t in p["raw_CTC_tokens"]]
    p["model_mean_confidence"] = sum(scores) / len(scores)
    p["minimum_emitted_character_confidence"] = min(scores)
    assert not labels._decision([_tview('TAG "B2”', part)], [{"prediction": p}], part)[
        "accepted"
    ]


def test_space_single_quote_and_missing_punctuation_are_not_invented():
    _, _, _, part = _drawing("ABC12")
    assert (
        "RAW_SPACE_HAS_NO_SOURCE_WORD_GAP"
        in labels._source_canonical_text("ABC 12", part)["reasons"]
    )
    _, _, _, part = _drawing("TAG 'B2'")
    assert labels._source_canonical_text('TAG "B2"', part)["reasons"]
    _, _, _, part = _drawing('TAG "B2"')
    assert labels._source_canonical_text("TAG B2", part)["reasons"]


def test_unicode_dash_requires_original_horizontal_midline_component():
    _, _, _, part = _drawing()
    assert labels._source_canonical_text("AB–12,3", part)["text"] == "AB-12,3"
    bad = deepcopy(part)
    dash = next(
        c for c in bad["components"] if c["source_role"] == "RETAINED_PUNCTUATION"
    )
    b = dash["bbox_xyxy_px"]
    dash["bbox_xyxy_px"] = [b[0], b[1] - 12, b[0] + 2, b[3] + 4]
    assert (
        "DASH_LACKS_ONE_ORIGINAL_MIDLINE_STROKE"
        in labels._source_canonical_text("AB–12,3", bad)["reasons"]
    )


def test_word_score_is_advisory_but_unresolved_character_conflict_stays_pending():
    _, _, _, part = _drawing()
    p = {"prediction": _prediction("AB-12,3")}
    assert labels._decision([_tview("AB-12,3", part, 84.99)], [p], part)["accepted"]
    result = labels._decision(
        [_tview("AB-12,3", part), _tview("AB-12,8", part)], [p], part
    )
    assert (
        not result["accepted"]
        and "UNRESOLVED_COMPLETE_RAW_CHARACTER_CONFLICT" in result["reasons"]
    )


@pytest.mark.parametrize("wrong", ["Z", "P"])
def test_conflicting_first_character_needs_an_independently_anchored_source_twin(wrong):
    _, _, _, part = _drawing("2AB-24")
    t = [_tview("2AB~24", part, 20), _tview(wrong + "AB-24", part, 80)]
    p = [{"prediction": _prediction("2AB-24")}]
    result = labels._decision(t, p, part)
    assert result["accepted"] and result["text"] == "2AB-24"
    proof = result["raw_character_conflict_evidence"]
    assert proof["pass"] and len(proof["conflicts"]) == 1
    character = proof["conflicts"][0]["characters"][0]
    assert character["component_index"] == 0
    assert character["matching_anchors"][0]["anchor"]["component_index"] == 4
    assert t[1]["words"][0]["text"] == wrong + "AB-24"
    # A true different first source shape must not borrow a later numeral.
    _, _, _, different = _drawing(wrong + "AB-24")
    bad = labels._decision(
        [_tview("2AB-24", different, 20), _tview(wrong + "AB-24", different, 80)],
        p, different,
    )
    assert not bad["accepted"]
    assert "UNRESOLVED_COMPLETE_RAW_CHARACTER_CONFLICT" in bad["reasons"]


def test_source_twins_cannot_create_an_unread_complete_string_or_anchor_each_other():
    _, _, _, part = _drawing("2AB-24")
    p = [{"prediction": _prediction("2AB-24")}]
    assert not labels._decision([_tview("ZAB-24", part)], p, part)["accepted"]
    result = labels._decision(
        [_tview("2AB-24", part), _tview("ZAB-Z4", part)], p, part
    )
    assert not result["accepted"]
    assert not any(a["component_index"] in (0, 4) for a in result["raw_character_conflict_evidence"]["anchors"])


def test_source_twin_requires_original_topology_and_unchanged_samples():
    from app.native_objects.source_glyph_equivalence import compare_original_glyphs

    _, _, _, part = _drawing("0AB-00")
    a, b = deepcopy(part["components"][0]), part["components"][4]
    assert compare_original_glyphs(a, b)["pass"]
    a["source_area_px"] += 1
    assert not compare_original_glyphs(a, b)["pass"]
    _, _, _, unlike = _drawing("CAB-00")
    result = compare_original_glyphs(unlike["components"][0], unlike["components"][4])
    assert not result["pass"] and "SOURCE_TWIN_TOPOLOGY_DIFFERS" in result["reasons"]


def test_flat_original_stroke_can_explain_raw_wave_symbol_but_a_real_wave_cannot():
    _, _, _, part = _drawing("AB-12")
    assert labels._source_canonical_text("AB~12", part)["text"] == "AB-12"
    wave = deepcopy(part)
    c = wave["components"][2]
    x0, y0, x1, _ = c["bbox_xyxy_px"]
    width = x1 - x0
    shape = np.zeros((5, width), np.uint8)
    points = np.array([[0, 2], [width//4, 0], [width//2, 2], [3*width//4, 4], [width-1, 2]])
    cv2.polylines(shape, [points], False, 1, 1)
    c.update(
        bbox_xyxy_px=[x0, y0-2, x1, y0+3],
        source_area_px=int(shape.sum()),
        source_runs_y_x0_x1=base._rle(shape, [x0, y0-2]),
    )
    assert labels._source_canonical_text("AB~12", wave)["text"] == "AB~12"
    assert not labels._decision(
        [_tview("AB~12", wave)], [{"prediction": _prediction("AB-12")}], wave
    )["accepted"]


def test_complete_ordinary_row_keeps_extra_prefix_comma_suffix_and_two_dashes():
    _, _, _, part = _drawing("AB-12,3")
    for raw in ["ZAB-12,3", "AB-123", "AB-12", "AB-12,"]:
        assert not labels._decision([_tview(raw, part)], [{"prediction": _prediction(raw)}], part)["accepted"]
    _, _, _, two = _drawing("AB--12")
    assert labels._source_canonical_text("AB--12", two)["text"] == "AB--12"
    assert labels._source_canonical_text("AB-12", two)["reasons"]


def test_short_dash_at_one_pixel_gap_does_not_merge_into_complete_glyph():
    # A full source letter with a short separate midline stroke. Both OCRs
    # dropping the stroke must not turn it into an apparently complete letter.
    rows = [
        {
            "label": 1,
            "labels": [1],
            "bbox": [20, 20, 32, 40],
            "width": 12,
            "height": 20,
            "area": 65,
        },
        {
            "label": 2,
            "labels": [2],
            "bbox": [33, 29, 39, 31],
            "width": 6,
            "height": 2,
            "area": 12,
        },
    ]
    units = labels._glyph_units(rows, 20, 40)
    assert len(units) == 2 and all(len(r["labels"]) == 1 for r in units)


def test_attached_neighbor_is_not_cut_and_fragment_white_gap_is_not_filled():
    gray, roi, box, _ = _drawing()
    original = gray.copy()
    cv2.line(gray, (box[2] - 2, box[1] + 5), (box[2] + 60, box[1] - 20), 0, 1)
    part, error = labels._partition(gray, roi, box)
    assert part is None and error
    gray = original.copy()
    gray[box[1] + 4, box[0] : box[0] + 15] = 255
    original = gray.copy()
    part, error = labels._partition(gray, roi, box)
    assert not error, error
    normalized, _ = labels._view(gray, part, 2, 0)
    b = part["bbox_xyxy_px"]
    assert np.array_equal(
        normalized[::2, ::2], gray[b[1] : b[3], b[0] : b[2]]
    ) and np.array_equal(gray, original)


def test_complete_enclosed_and_true_multiline_regions_are_protected():
    gray, roi, box, _ = _drawing()
    d = _contract(gray, roi, box, True)
    assert not labels.plan_single_line_labels(gray, d, roi)["plans"]
    d = _contract(gray, roi, box)
    d["regions"][0]["enclosure"] = {"bbox": box}
    assert not labels.plan_single_line_labels(gray, d, roi)["plans"]
    d = _contract(gray, roi, box)
    r = deepcopy(d["regions"][0])
    r.update(id="R2", bbox_xyxy_px=[40, 110, 150, 133])
    d["regions"].append(r)
    d["groups"][0].update(geometry_type="MTEXT", region_ids=["R1", "R2"])
    assert not labels.plan_single_line_labels(gray, d, roi)["plans"]


def test_pending_same_baseline_regions_can_form_one_complete_source_row():
    gray, roi, box, _ = _drawing("ABC12")
    d = _contract(gray, roi, box)
    mid = (box[0] + box[2]) // 2
    d["regions"][0].update(
        bbox_xyxy_px=[box[0], box[1], mid, box[3]],
        discovery_bbox_xyxy_px=[box[0], box[1], mid, box[3]],
    )
    r = deepcopy(d["regions"][0])
    r.update(
        id="R2",
        bbox_xyxy_px=[mid, box[1], box[2], box[3]],
        discovery_bbox_xyxy_px=[mid, box[1], box[2], box[3]],
    )
    d["regions"].append(r)
    d["groups"][0].update(geometry_type="MTEXT", region_ids=["R1", "R2"])
    plan = labels.plan_single_line_labels(gray, d, roi)
    assert not plan["protected_region_ids"] and len(plan["plans"]) == 1
    assert plan["plans"][0]["source_partition"]["bbox_xyxy_px"] == box


class _RawModel:
    def __init__(self, observations):
        self.observations = observations
        self.calls = []
        self.identity = {
            "model_sha256": independent.MODEL_SHA256,
            "policy": deepcopy(independent.POLICY),
        }

    def recognize(self, image):
        text, score = self.observations[len(self.calls)]
        self.calls.append(image.copy())
        original, tensor = independent.prepare_model_input(image)
        record = _prediction(text, score)
        record.update(
            input_array_sha256=_hash(original.tobytes()),
            input_shape_px=list(original.shape),
            model_tensor_sha256=_hash(tensor.tobytes()),
            model_tensor_shape=list(tensor.shape),
            source_geometry_modified=False,
            raw_transcription_rewritten=False,
        )
        self.last_observation = {"model_inference_executed_for_this_request": True}
        return record


def _engines(monkeypatch, observations=None):
    observations = observations or [("AB-12,3", 96)]
    calls = []

    def raw_ocr(image, box, psm, directory, name, progress, padding_px=0, *, dpi=200):
        text, confidence = observations[len(calls)]
        calls.append((psm, padding_px, dpi))
        crop = np.ascontiguousarray(image[box[1] : box[3], box[0] : box[2]])
        actual = np.pad(crop, padding_px, constant_values=255)
        png, tsv, meta = (
            directory / (name + suffix) for suffix in (".png", ".tsv", ".json")
        )
        Image.fromarray(actual).save(png)
        raw = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            f"5\t1\t1\t1\t1\t1\t{padding_px}\t{padding_px}\t{crop.shape[1]}\t{crop.shape[0]}\t{confidence}\t{text}\n"
        )
        tsv.write_text(raw, encoding="utf-8")
        metadata = {
            "status": "COMPLETED",
            "return_code": 0,
            "tsv_sha256": _hash(tsv.read_bytes()),
            "image_sha256": _hash(png.read_bytes()),
            "command_executed_for_this_request": True,
            "engine_version": "tesseract controlled-fixture",
            "command": [
                "fixture",
                "--psm",
                str(psm),
                "--dpi",
                str(dpi),
                "-l",
                "eng",
                "--oem",
                "1",
            ],
            "specification": {
                "crop_xyxy_px": box,
                "crop_array_sha256": base.source_array_sha256(crop),
                "psm": psm,
                "external_white_padding_px": padding_px,
                "language": "eng",
                "source_pixels_modified": False,
                "recognition_dpi": dpi,
                "pixel_scale": [1, 1],
                "padding_replaces_source_pixels": False,
            },
        }
        meta.write_text(json.dumps(metadata), encoding="utf-8")
        return base._parse_tsv(
            raw,
            [
                -padding_px,
                -padding_px,
                actual.shape[1] - padding_px,
                actual.shape[0] - padding_px,
            ],
            name,
            psm,
        ), metadata

    monkeypatch.setattr(base, "_ocr", raw_ocr)
    monkeypatch.setattr(
        base, "_resolve_tesseract", lambda *args: {"fixture_only": True}
    )
    return calls


def _recognized(tmp_path, monkeypatch, fallback=False):
    gray, roi, box, part = _drawing()
    original = gray.copy()
    calls = _engines(
        monkeypatch, [("AB-12", 80), ("AB-12,3", 96)] if fallback else None
    )
    model = _RawModel([("AB-12,3", 0.999)] * (2 if fallback else 1))
    result = labels.recognize_single_line_label(
        gray,
        roi,
        {"source_partition": part},
        tmp_path,
        recognizer=model,
        evidence_root=tmp_path,
    )
    assert result["accepted"], result["evidence"]["decision"]
    assert np.array_equal(gray, original)
    return gray, roi, box, result, calls, model


@pytest.mark.parametrize("fallback", [False, True])
def test_bounded_recognition_then_all_raw_files_replayed_with_zero_new_calls(
    tmp_path, monkeypatch, fallback
):
    gray, roi, _, result, calls, model = _recognized(tmp_path, monkeypatch, fallback)
    assert len(calls) == len(model.calls) == (2 if fallback else 1)
    if fallback:
        assert calls == [(7, 16, 400), (13, 16, 400)]

    def forbidden(*args, **kwargs):
        pytest.fail("cold replay must not recognize")

    monkeypatch.setattr(base, "_ocr", forbidden)
    monkeypatch.setattr(independent, "IndependentRecognizer", forbidden)
    check = labels.verify_single_line_label_evidence(
        gray, roi, result["evidence"], tmp_path
    )
    assert check["pass"], check
    assert (
        check["text"] == "AB-12,3"
        and check["new_OCR_calls"] == check["new_model_calls"] == 0
    )
    assert (
        check["source_text_normalization"]
        == result["evidence"]["decision"]["source_text_normalization"]
    )
    assert check["all_raw_artifacts_read_and_hashed"]


@pytest.mark.parametrize(
    "damage",
    [
        "source",
        "roi",
        "original-image",
        "raw-tsv",
        "model-file",
        "derived-image",
        "policy",
        "layout",
        "decision",
        "saved-words",
        "partition",
        "normalization",
        "path",
        "receipt",
        "counts",
    ],
)
def test_cold_replay_fails_closed_on_source_raw_and_layout_bindings(
    tmp_path, monkeypatch, damage
):
    gray, roi, box, result, _, _ = _recognized(tmp_path, monkeypatch)
    e = deepcopy(result["evidence"])
    if damage == "source":
        gray[0, 0] = 0
    elif damage == "roi":
        roi = [1, 0, 500, 190]
    elif damage in {"original-image", "raw-tsv", "model-file", "derived-image"}:
        ref = {
            "original-image": e["original_source"],
            "raw-tsv": e["tesseract_views"][0]["raw_tsv"],
            "model-file": e["ppocr_views"][0]["prediction_file"],
            "derived-image": e["tesseract_views"][0]["recognition_image"],
        }[damage]
        (tmp_path / ref["path"]).write_bytes(b"changed actual raw file")
    elif damage == "policy":
        e["policy"]["Tesseract_word_confidence"] = 1
    elif damage == "layout":
        e["text_geometry"]["height_px"] += 1
    elif damage == "decision":
        e["decision"]["text"] = "AB-12,8"
    elif damage == "saved-words":
        e["tesseract_views"][0]["words"][0]["text"] = "AB-12,8"
    elif damage == "partition":
        e["source_partition"]["components"].pop()
    elif damage == "normalization":
        e["tesseract_views"][0]["normalization"]["scale"] = 3
    elif damage == "path":
        e["original_source"]["path"] = "../outside.png"
    elif damage == "receipt":
        e["ppocr_views"][0]["observation_receipt"][
            "model_inference_executed_for_this_request"
        ] = False
    elif damage == "counts":
        e["new_model_calls"] += 1
    assert not labels.verify_single_line_label_evidence(gray, roi, e, tmp_path)[
        "pass"
    ], damage


def test_cold_rejects_an_internal_symlink_directory(tmp_path, monkeypatch):
    gray, roi, _, result, _, _ = _recognized(tmp_path, monkeypatch)
    try:
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("This account cannot create a directory symlink")
    e = deepcopy(result["evidence"])
    e["original_source"]["path"] = "alias/" + e["original_source"]["path"]
    assert not labels.verify_single_line_label_evidence(gray, roi, e, tmp_path)["pass"]


def test_refine_updates_normal_contract_without_fabricating_old_raw_provenance(
    tmp_path, monkeypatch
):
    gray, roi, box, _ = _drawing()
    before = _contract(gray, roi, box)
    _engines(monkeypatch)
    before["source_text_ownership"] = {"old": True}
    model = _RawModel([("AB-12,3", 0.999)])
    result = labels.refine_single_line_labels(
        gray,
        before,
        tmp_path / "single_line_labels",
        roi=roi,
        source_sha256="a" * 64,
        recognizer=model,
        evidence_root=tmp_path,
    )
    assert result["regions"][0] == before["regions"][0]
    assert len(result["regions"]) == 2 and len(result["groups"]) == 1
    assert (
        result["groups"][0]["geometry_type"] == "TEXT"
        and result["groups"][0]["text"] == "AB-12,3"
    )
    assert "source_text_ownership" not in result and result[
        "prior_source_text_ownership"
    ] == {"old": True}
    validate_text_regions(result, gray.shape, roi)
    summary = result["single_line_label_recovery"]
    assert summary["accepted_labels"] == 1 and summary["superseded_pending_groups"] == 1
    for record in summary["raw_evidence_files"]:
        assert _hash((tmp_path / record["path"]).read_bytes()) == record["sha256"]
    new = next(r for r in result["regions"] if r.get("single_line_recovery"))
    assert not any(w.get("observation_provenance") for w in new["words"])
    assert labels.verify_single_line_label_evidence(
        gray, roi, new["single_line_recovery"], tmp_path
    )["pass"]


def test_two_engines_cannot_adopt_a_prefix_of_a_wider_observed_label():
    _, _, _, part = _drawing()
    t = _tview("AB-12,3", part)
    p = {"prediction": _prediction("AB-12,3")}
    assert labels._decision([t], [p], part)["accepted"]
    box = part["bbox_xyxy_px"]
    observed = {
        "raw_text": "AB-12,34",
        "bbox_xyxy_px": [box[0], box[1], box[2] + 18, box[3]],
        "original_ink_past_candidate_px": 24,
    }
    result = labels._decision([t], [p], part, [observed])
    assert not result["accepted"] and result["text"] is None
    assert result["reasons"] == ["NARROW_PREFIX_OMITS_OBSERVED_ALPHANUMERIC_SUFFIX"]
    assert result["original_observation_prefix_conflicts"] == [observed]
    assert t["words"][0]["text"] == p["prediction"]["raw_text"] == "AB-12,3"


@pytest.mark.parametrize("change", ["same", "different", "punctuation", "white", "same_box"])
def test_suffix_veto_requires_literal_extra_character_and_original_extent(change):
    _, _, _, part = _drawing()
    box = part["bbox_xyxy_px"]
    observed = {
        "raw_text": "AB-12,34",
        "bbox_xyxy_px": [box[0], box[1], box[2] + 18, box[3]],
        "original_ink_past_candidate_px": 24,
    }
    if change == "same":
        observed["raw_text"] = "AB-12,3"
    elif change == "different":
        observed["raw_text"] = "A8-12,34"
    elif change == "punctuation":
        observed["raw_text"] = "AB-12,3 \\"
    elif change == "white":
        observed["original_ink_past_candidate_px"] = 0
    else:
        observed["bbox_xyxy_px"] = box
    assert labels._decision(
        [_tview("AB-12,3", part)], [{"prediction": _prediction("AB-12,3")}],
        part, [observed],
    )["accepted"]


@pytest.mark.parametrize("damage", ["binding", "ids", "snapshot"])
def test_formal_label_replay_requires_actual_upstream_observation_file(
    tmp_path, monkeypatch, damage
):
    gray, roi, box, _ = _drawing()
    before = _contract(gray, roi, box)
    _engines(monkeypatch)
    result = labels.refine_single_line_labels(
        gray, before, tmp_path / "single_line_labels", roi=roi,
        recognizer=_RawModel([("AB-12,3", 0.999)]), evidence_root=tmp_path,
    )
    evidence = deepcopy(result["groups"][0]["single_line_recovery"])
    assert evidence["planned_region_ids"] == ["R1"]
    assert labels.verify_single_line_label_evidence(gray, roi, evidence, tmp_path)["pass"]
    if damage == "binding":
        evidence["upstream_observations"] = None
    elif damage == "ids":
        evidence["upstream_observations"]["region_ids"] = ["absent"]
    else:
        record = evidence["upstream_observations"]["snapshot"]
        (tmp_path / record["path"]).write_text("{}", encoding="utf-8")
    assert not labels.verify_single_line_label_evidence(gray, roi, evidence, tmp_path)["pass"]


@pytest.mark.parametrize("damage", [None, "raw_file", "no_evidence_root"])
def test_verified_complete_row_keeps_its_punctuation_ownership(
    tmp_path, monkeypatch, damage
):
    from app.native_objects import source_text_ownership as ownership
    from app.native_objects.pipeline import _reclassify_source_fitted_lines

    gray, roi, box, observation, _, _ = _recognized(tmp_path, monkeypatch)
    proof = observation["evidence"]
    part = proof["source_partition"]
    data = _contract(gray, roi, box, complete=True)
    row = data["regions"][0]
    row.update(
        text=observation["text"], single_line_recovery=proof,
        words=[{"text": observation["text"], "confidence": 20.0, "bbox_xyxy_px": box}],
        compact_source_ink_mask={"runs_y_x0_x1": part["source_support_runs_y_x0_x1"]},
    )
    data["groups"][0]["text"] = observation["text"]
    dash = next(c for c in part["components"] if c["source_role"] == "RETAINED_PUNCTUATION")
    points = np.array([[x, y] for y, a, b in dash["source_runs_y_x0_x1"] for x in range(a, b)])
    geometry = {"start": [float(points[:,0].min()), float(points[:,1].mean())],
                "end": [float(points[:,0].max()), float(points[:,1].mean())]}
    proposal = {"id": "source-mark", "geometry": geometry,
                "source_component_area": len(points), "decision": "DEFER_TEXT_OWNERSHIP"}
    candidates = {"objects": [], "short_source_components": [proposal],
                  "uncertainties": [{**deepcopy(proposal), "reason": "DEFER_TEXT_OWNERSHIP"}]}
    if damage == "raw_file":
        (tmp_path/proof["tesseract_views"][0]["raw_tsv"]["path"]).write_text("damaged")
    fixed, audit = ownership.reconcile_source_text_ownership(
        data, gray, roi, candidates,
        evidence_root=None if damage == "no_evidence_root" else tmp_path,
    )
    event = next(e for e in audit["events"] if e["cached_source_candidate_ids"] == ["source-mark"])
    protected = damage is None
    assert bool(event["verified_complete_row_component_witnesses"]) == protected
    assert event["checks"]["no_verified_complete_row_component_ownership"] != protected
    if protected:
        assert event["decision"] == "RETAIN_TEXT_OR_UNKNOWN_OWNERSHIP"
        assert fixed["regions"][0]["compact_source_ink_mask"] == row["compact_source_ink_mask"]
        reclassified = _reclassify_source_fitted_lines(
            candidates, fixed, gray.shape, roi, original_dictionary_sha256="a"*64
        )
        assert not reclassified["objects"]
    assert fixed["groups"] == data["groups"]


def test_malformed_earlier_raw_observation_cannot_be_hidden_by_later_success():
    _, _, _, part = _drawing()
    good = _tview("AB-12,3", part)
    bad = deepcopy(good)
    bad["raw_tsv_integrity"] = False
    assert not labels._decision(
        [bad, good], [{"prediction": _prediction("AB-12,3")}], part
    )["accepted"]
    raw = _prediction("AB-12,3")
    raw["minimum_emitted_character_confidence"] = 0.5
    assert not labels._decision(
        [good], [{"prediction": raw}, {"prediction": _prediction("AB-12,3")}], part
    )["accepted"]


def _touching_baseline_source():
    gray, roi, box, _ = _drawing("PANEL-08A")
    top = box[3]
    strip = [10, top, 460, top + 3]
    gray[top : top + 3, 10:460] = 0
    return gray, roi, box, strip


def test_certified_baseline_strip_retains_complete_original_body_and_independent_line():
    gray, roi, box, strip = _touching_baseline_source()
    original = gray.copy()
    assert labels._partition_original_row(gray, roi, box)[0] is None
    part, reason = labels._partition(gray, roi, box)
    assert not reason, reason
    proof = part["baseline_line_separation"]
    assert proof["bbox_xyxy_px"] == strip
    assert part["bbox_xyxy_px"] == box
    assert part["full_height_component_count"] == 8
    assert part["punctuation_component_count"] == 1
    assert labels._source_canonical_text("PANEL-08A", part)["text"] == "PANEL-08A"
    assert part["source_components_cut"] is True
    assert proof["glyph_to_line_contacts"]
    assert proof["source_erasure_authorized"] is False
    assert proof["line_remains_independent_source_responsibility"] is True
    assert np.array_equal(gray, original)
    normalized, _ = labels._view(gray, part, 2, 0)
    assert np.array_equal(
        normalized[::2, ::2], original[box[1] : box[3], box[0] : box[2]]
    )
    assert all(
        run[0] < strip[1]
        for c in part["components"]
        for run in c["source_runs_y_x0_x1"]
    )
    assert all(c["source_component_labels"] for c in part["components"])
    assert any(
        c["derived_partition_component_labels"] != c["source_component_labels"]
        for c in part["components"]
    )


@pytest.mark.parametrize(
    "damage",
    [
        "white-pixel-gap",
        "descending-comma",
        "lower-branch",
        "upper-branch",
        "curve",
        "true-bottom-stroke",
        "one-end-missing",
    ],
)
def test_baseline_separator_does_not_hide_gaps_marks_branches_curves_or_bottom_ink(
    damage,
):
    gray, roi, box, strip = _touching_baseline_source()
    top = strip[1]
    if damage == "white-pixel-gap":
        gray[top + 1, box[0] + 10] = 255
    elif damage == "descending-comma":
        gray[top - 2 : top + 7, box[2] + 6 : box[2] + 8] = 0
    elif damage == "lower-branch":
        gray[top + 3 : top + 10, box[2] + 30] = 0
    elif damage == "upper-branch":
        gray[top - 9 : top, box[2] + 30] = 0
    elif damage == "curve":
        cv2.ellipse(gray, (box[2] + 30, top), (13, 9), 0, 0, 180, 0, 1)
    elif damage == "true-bottom-stroke":
        gray[top : top + 3, strip[0] : strip[2]] = 255
        gray[top - 4 : top - 1, strip[0] : strip[2]] = 0
    elif damage == "one-end-missing":
        gray[top : top + 3, strip[0] : box[0]] = 255
    original = gray.copy()
    part, reason = labels._partition(gray, roi, box)
    assert part is None, (damage, part)
    assert reason
    assert np.array_equal(gray, original)


def test_clipped_discovery_box_cannot_clip_certified_full_source_body():
    gray, roi, box, _ = _touching_baseline_source()
    seed = [box[0] + 1, box[1], box[2] - 1, box[3]]
    part, reason = labels._partition(gray, roi, seed)
    assert not reason, reason
    assert part["bbox_xyxy_px"] == box


def test_baseline_line_requires_full_blank_lower_context_inside_requested_source():
    gray, roi, box, strip = _touching_baseline_source()
    roi = [roi[0], roi[1], roi[2], strip[3] + 1]
    part, reason = labels._partition(gray, roi, box)
    assert part is None and reason


def test_component_bboxes_abut_but_a_real_detached_dash_stays_independent():
    rows = [
        {
            "label": 1,
            "labels": [1],
            "bbox": [20, 20, 32, 40],
            "width": 12,
            "height": 20,
            "area": 65,
        },
        {
            "label": 2,
            "labels": [2],
            "bbox": [32, 29, 38, 31],
            "width": 6,
            "height": 2,
            "area": 12,
        },
    ]
    assert len(labels._glyph_units(rows, 20, 40)) == 2


def test_cold_replays_baseline_partition_and_rejects_changed_certificate(
    tmp_path, monkeypatch
):
    gray, roi, box, _ = _touching_baseline_source()
    part, reason = labels._partition(gray, roi, box)
    assert not reason
    _engines(monkeypatch, [("PANEL-08A", 96)])
    model = _RawModel([("PANEL-08A", 0.999)])
    result = labels.recognize_single_line_label(
        gray,
        roi,
        {"source_partition": part},
        tmp_path,
        recognizer=model,
        evidence_root=tmp_path,
    )
    assert result["accepted"]
    assert labels.verify_single_line_label_evidence(
        gray, roi, result["evidence"], tmp_path
    )["pass"]
    damaged = deepcopy(result["evidence"])
    damaged["source_partition"]["baseline_line_separation"]["actual_end_extensions_px"][
        0
    ] += 1
    assert not labels.verify_single_line_label_evidence(gray, roi, damaged, tmp_path)[
        "pass"
    ]


def test_fragmented_upper_bowl_is_not_mistaken_for_a_detached_midline_dash():
    # The stem/top fragment is already tall. A tiny upper gap and its bowl
    # fragment may still belong to that glyph, unlike a separate short dash.
    rows = [
        {
            "label": 1,
            "labels": [1],
            "bbox": [20, 20, 31, 46],
            "width": 11,
            "height": 26,
            "area": 80,
        },
        {
            "label": 2,
            "labels": [2],
            "bbox": [31, 21, 32, 22],
            "width": 1,
            "height": 1,
            "area": 1,
        },
        {
            "label": 3,
            "labels": [3],
            "bbox": [32, 21, 39, 34],
            "width": 7,
            "height": 13,
            "area": 25,
        },
    ]
    units = labels._glyph_units(rows, 26, 46)
    assert len(units) == 1 and units[0]["labels"] == [1, 2, 3]
