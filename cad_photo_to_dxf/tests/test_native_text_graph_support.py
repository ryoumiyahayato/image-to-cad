"""Bound candidate roles preserve raw ink, text negatives and complete paths."""

import copy
import hashlib

import cv2
import numpy as np
import pytest

from app.native_objects.connections import extract_connections
from app.native_objects.contracts import validate_text_regions


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def fixture(*, raw_words=("NO", "Nvv"), left=True, right=True):
    ink = np.zeros((260, 380), np.uint8)
    main = np.array([[150, 90], [168, 97], [187, 108], [204, 120], [225, 138]], np.int32)
    candidate = np.zeros_like(ink)
    cv2.polylines(candidate, [main], False, 1, 1)
    ink |= candidate
    if left:
        cv2.polylines(ink, [np.array([[65, 64], [85, 68], [110, 73], [126, 79]], np.int32)], False, 1, 1)
    if right:
        cv2.polylines(ink, [np.array([[249, 161], [267, 185], [284, 212]], np.int32)], False, 1, 1)
    # A retained formal text reference with actual compact source ink.
    for x in [90, 105, 120]:
        ink[35:55, x] = 1
        ink[35, x:x + 10] = 1
        ink[45, x:x + 8] = 1
        ink[54, x:x + 10] = 1
    gray = np.where(ink, 0, 255).astype(np.uint8)
    yy, xx = np.nonzero(candidate)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    region = {"id": "unconfirmed-row", "bbox_xyxy_px": box,
              "text": raw_words[0], "accepted": False, "complete": False,
              "compact_source_ink_mask": {"runs_y_x0_x1": [[int(y), int(x), int(x + 1)] for y, x in zip(yy, xx)]},
              "unresolved_reasons": ["word_missing_two_confident_contexts_with_current_local_OCR"]}
    observations, alternatives = [], []
    for index, text in enumerate(raw_words):
        pad = 2 + 2 * index
        crop = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]
        psm = 7 if index == 0 else 13
        word = {"text": text, "confidence": 40.0, "bbox_xyxy_px": box}
        spec = {"crop_xyxy_px": crop, "crop_array_sha256": digest(gray[crop[1]:crop[3], crop[0]:crop[2]]), "psm": psm}
        observations.append({"region_id": region["id"], "key": f"verified-raw-{index}",
                             "specification": spec, "words": [word],
                             "raw_tsv_sha256": hashlib.sha256(text.encode()).hexdigest(),
                             "metadata_sha256": hashlib.sha256(str(spec).encode()).hexdigest(),
                             "input_png_sha256": hashlib.sha256(gray[crop[1]:crop[3], crop[0]:crop[2]].tobytes()).hexdigest()})
        alternatives.append({"context_id": f"different-import-wrapper-{index}", "crop_xyxy_px": crop,
                             "psm": psm, "words": [copy.deepcopy(word)]})
    region["words"] = copy.deepcopy(alternatives[0]["words"])
    region["completeness_evidence"] = {"alternatives": alternatives}
    roi = [0, 0, gray.shape[1], gray.shape[0]]
    data = {"coordinate_system": "source_pixels_top_left", "source_size_px": [gray.shape[1], gray.shape[0]],
            "roi_xyxy_px": roi, "source_array_sha256": digest(gray), "regions": [region], "groups": []}
    token = {"validated": True, "source_array_sha256": digest(gray), "source_sha256": "a" * 64,
             "observations": observations}
    formal = [{"id": "reference-label", "kind": "TEXT", "geometry": {"text": "EEE", "x": 90,
                "y": 55, "height_px": 20, "width_px": 40}, "source_evidence": {"region_ids": ["retained-label"]}}]
    return gray, roi, data, token, formal, box


def extract(item, output, *, verified=True):
    gray, roi, data, token, formal, _ = item
    original, raw = gray.copy(), copy.deepcopy(data)
    result = extract_connections(gray, roi, formal, output, text_regions=data,
                                 verified_text_observations=token if verified else None)
    assert np.array_equal(gray, original)
    assert data == raw
    return result


def target_paths(result, box):
    return [obj for obj in result["objects"] if all(
        box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]
        for point in obj["geometry"]["points"])]


def test_verified_two_sided_graphic_support_recovers_one_whole_path_without_bridging_gaps(tmp_path):
    item = fixture()
    result = extract(item, tmp_path)
    target = target_paths(result, item[-1])
    assert len(target) == 1
    evidence = target[0]["source_evidence"]
    relation = evidence["text_graphic_support"]
    assert relation["decision"] == "SOURCE_SUPPORTED_GRAPHIC"
    assert relation["positive_evidence_kind"] == "TWO_SIDED_SEPARATE_SOURCE_STROKE_CONTINUATION"
    assert evidence["whole_simple_source_chain"]["pass"]
    assert evidence["whole_simple_source_chain_fit"]["pass"]
    assert evidence["source_support"]["pass"]
    assert not relation["raw_candidate_masks_modified"]
    assert not relation["source_pixels_uniquely_partitioned"]
    assert not evidence["source_morphological_gap_closing"]
    assert target[0]["geometry"]["points"][0] == [150.0, 90.0]
    assert target[0]["geometry"]["points"][-1] == [225.0, 138.0]


def test_raw_reference_json_alone_does_not_authorize_releasing_old_glyph_veto(tmp_path):
    item = fixture()
    item[2]["validated"] = True  # Input JSON cannot supply the runtime token.
    result = extract(item, tmp_path, verified=False)
    assert not target_paths(result, item[-1])
    assert any(row["reason"] == "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT" for row in result["uncertainties"])


@pytest.mark.parametrize("raw_words", [("1", "I"), ("/", "/"), ("(", "("), ("-", "-"), ("+", "+")])
def test_single_character_and_punctuation_remain_protected_even_with_graphic_like_context(tmp_path, raw_words):
    item = fixture(raw_words=raw_words)
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])
    assert any("SINGLE_CHARACTER_OR_PUNCTUATION_INTERPRETATION_RETAINED" in str(row)
               for row in result["uncertainties"])


@pytest.mark.parametrize("change", ["complete", "source_review", "group_complete", "reliable_word", "source_hash", "crop_hash", "parsed_words"])
def test_real_text_or_invalid_observation_binding_cannot_be_overruled(tmp_path, change):
    item = fixture()
    region, token = item[2]["regions"][0], item[3]
    if change == "complete":
        region["complete"] = True
    elif change == "source_review":
        region["source_review"] = {"accepted": True}
    elif change == "group_complete":
        item[2]["groups"] = [{"id": "complete-group", "region_ids": [region["id"]], "complete": True}]
    elif change == "reliable_word":
        token["observations"][0]["words"][0]["confidence"] = 98
        region["completeness_evidence"]["alternatives"][0]["words"][0]["confidence"] = 98
    elif change == "source_hash":
        token["source_array_sha256"] = "0" * 64
    elif change == "crop_hash":
        token["observations"][0]["specification"]["crop_array_sha256"] = "0" * 64
    else:
        token["observations"][0]["words"][0]["text"] = "DIFFERENT"
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])


@pytest.mark.parametrize("missing", ["left", "right"])
def test_one_sided_neighbor_does_not_turn_an_unresolved_curve_into_a_confirmed_graphic(tmp_path, missing):
    item = fixture(**{missing: False})
    result = extract(item, tmp_path)
    assert not target_paths(result, item[-1])


def test_contract_preserves_candidate_mask_and_reports_group_role_separately():
    gray, roi, data, _, _, _ = fixture()
    data["groups"] = [{"id": "reviewed", "region_ids": ["unconfirmed-row"], "source_review": {"accepted": True}}]
    box = validate_text_regions(data, gray.shape, roi)[0]
    assert not box["confirmed"]
    assert box["support_role"]["groups"][0]["source_review_accepted"]
    assert box["glyph_source_runs"] == data["regions"][0]["compact_source_ink_mask"]["runs_y_x0_x1"]
