"""Local source binding and atomic paragraph adoption; no OCR or private data."""

import copy

import numpy as np
import pytest

from app.native_objects import source_glyph_resolution as resolution
from app.native_objects import text_regions as text


def _draw(image, x, y, narrow=False, digit=False):
    if digit:
        image[y:y + 24, x + 6] = 0
        for n in range(7):
            image[y + 6 - n, x + n] = 0
        return [x, y, x + 7, y + 24]
    if narrow:
        image[y:y + 24, x + 1] = 0
        image[y, x:x + 2] = 0
        image[y + 23, x + 1:x + 3] = 0
        return [x, y, x + 3, y + 24]
    image[y:y + 24, x:x + 2] = 0
    image[y:y + 2, x:x + 12] = 0
    image[y + 10:y + 12, x:x + 9] = 0
    return [x, y, x + 12, y + 24]


def _word(raw, box, identifier, complete=True):
    return {"id": identifier, "text": raw, "bbox_xyxy_px": box,
            "confidence": 96.0, "agreement_pass": complete,
            "independent_agreement_observation_keys": [identifier + "-a", identifier + "-b"]}


def _tess(image, row, margin, psm, raw=None, confidence=96):
    b = row["bbox_xyxy_px"]
    crop = [b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin]
    spec = {"crop_xyxy_px": crop,
            "crop_array_sha256": text.source_array_sha256(image[crop[1]:crop[3], crop[0]:crop[2]]),
            "source_pixels_modified": False, "pixel_scale": [1, 1],
            "psm": psm, "language": "eng"}
    words = copy.deepcopy(row["words"])
    if raw:
        for w, token in zip(words, raw.split(" ")):
            w["text"] = token
    for w in words:
        w["confidence"] = confidence
        w["observation_provenance"] = {"specification": spec, "engine_identity": {"name": "saved-test-engine"}}
    return {"engine": "Tesseract", "raw_text": " ".join(w["text"] for w in words),
            "words": words, "crop_xyxy_px": crop, "source_crop_xyxy_px": crop,
            "context_id": f"{row['id']}-{psm}", "psm": psm, "status": "COMPLETED"}


def _model(image, row, margin, raw):
    b = row["bbox_xyxy_px"]
    crop = [b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin]
    return {"engine": "PP-OCR", "raw_text": raw,
            "observation_key": f"saved-model-{margin}", "source_crop_xyxy_px": crop,
            "original_crop_sha256": text.source_array_sha256(image[crop[1]:crop[3], crop[0]:crop[2]]),
            "raw_CTC_tokens": [{"character": c, "score": .999} for c in raw],
            "model_mean_confidence": .999, "minimum_emitted_character_confidence": .999}


def _fixture():
    image = np.full((260, 310), 255, np.uint8)
    regions = []
    for rid, raw, y, complete in [("a", "AB CD", 30, True),
                                  ("b", "EF GH", 70, True),
                                  ("c", "iJ KL", 110, False)]:
        boxes = [_draw(image, x, y, digit=(rid == "c" and n == 0))
                 for n, x in enumerate((40, 58, 90, 108))]
        words = [_word(raw.split()[0], text._box_union(boxes[:2]), rid + "-w1", complete),
                 _word(raw.split()[1], text._box_union(boxes[2:]), rid + "-w2")]
        regions.append({"id": rid, "text": raw, "bbox_xyxy_px": text._box_union(boxes),
                        "words": words, "complete": complete,
                        "unresolved_reasons": [] if complete else ["high_confidence_seed_transcription_conflict_at_same_full_word_box", "word_missing_two_confident_contexts_with_current_local_OCR"]})
    for rid, raw, x in [("ref-digit", "12", 40), ("ref-capital", "IX", 180)]:
        boxes = [_draw(image, x, 185, digit=raw[0] == "1", narrow=raw[0] == "I"),
                 _draw(image, x + 20, 185)]
        box = text._box_union(boxes)
        regions.append({"id": rid, "text": raw, "bbox_xyxy_px": box,
                        "words": [_word(raw, box, rid + "-w")],
                        "complete": True, "unresolved_reasons": []})
    for row in regions:
        row["completeness_evidence"] = {"alternatives": [_tess(image, row, 3, 7), _tess(image, row, 5, 13)]}
    group = {"id": "paragraph", "region_ids": ["a", "b", "c"],
             "bbox_xyxy_px": text._box_union([r["bbox_xyxy_px"] for r in regions[:3]]),
             "text": "\n".join(r["text"] for r in regions[:3]), "complete": False,
             "unresolved_reasons": regions[2]["unresolved_reasons"],
             "lines": [{"region_id": r["id"], "text": r["text"],
                        "bbox_xyxy_px": r["bbox_xyxy_px"], "complete": r["complete"]}
                       for r in regions[:3]]}
    data = {"source_size_px": [image.shape[1], image.shape[0]],
            "source_array_sha256": text.source_array_sha256(image),
            "roi_xyxy_px": [0, 0, image.shape[1], image.shape[0]],
            "regions": regions, "groups": [group]}
    _, _, components = text._component_evidence(image, data["roi_xyxy_px"])
    target = regions[2]
    glyph_records = [{"bbox_xyxy_px": g["bbox_xyxy_px"],
                      "original_crop_sha256": text.source_array_sha256(image[g["bbox_xyxy_px"][1]:g["bbox_xyxy_px"][3], g["bbox_xyxy_px"][0]:g["bbox_xyxy_px"][2]]),
                      "original_source_area_px": g["source_area_px"]}
                     for g in components if text._inside(g["bbox_xyxy_px"], target["bbox_xyxy_px"])]
    entry = {"region_id": "c", "source_bbox_xyxy_px": target["bbox_xyxy_px"],
             "current_unapproved_text": target["text"],
             "character_conflicts": [{"character_index_zero_based": 0,
                                      "alternatives": ["1", "i"], "prefix": "", "suffix": "J KL"}],
             "observed_prefix_suffix_alternatives": [], "adjacent_unassigned_components": [],
             "source_components": glyph_records,
             "same_page_reliable_character_references": {},
             "raw_observations": [_tess(image, target, 3, 7),
                                  _tess(image, target, 5, 13, "4J KL", 70),
                                  _model(image, target, 2, "1J KL"),
                                  _model(image, target, 4, "1J KL")]}
    index = {"source_array_sha256": data["source_array_sha256"],
             "roi_xyxy_px": data["roi_xyxy_px"], "pending_regions": [entry]}
    return image, data, index


@pytest.fixture
def accepted_classifier(monkeypatch):
    calls = []
    def propose(target, references, alternatives, **kwargs):
        assert set(alternatives) == {"1", "i"}
        assert {r["character"] for r in references} == {"1", "I"}
        assert kwargs["source_evidence"]["source_hash_verified"] is True
        assert kwargs["source_evidence"]["no_shared_source"] is True
        assert kwargs["source_evidence"]["context_sha256"] == resolution.bitmap_sha256(kwargs["context_bitmap"])
        calls.append((target.copy(), references, kwargs))
        return {"accepted": True, "character": "1", "limitations": ["synthetic classifier stub; morphology covered separately"]}
    monkeypatch.setattr(resolution, "propose_glyph_identity", propose)
    return calls


def test_whole_group_updates_only_derived_content_and_retains_every_raw_read(accepted_classifier):
    image, data, index = _fixture()
    original, raw, pixels = copy.deepcopy(data), copy.deepcopy(index), image.copy()
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph", source_file_sha256="a" * 64)
    assert receipt["accepted"] and receipt["recognition_calls"] == 0
    assert receipt["ordered_region_ids"] == ["a", "b", "c"]
    assert receipt["resolved_group_text"] == "AB CD\nEF GH\n1J KL"
    assert receipt["receipt_sha256"] == resolution.receipt_digest(receipt)
    assert receipt["source_file_sha256"] != receipt["source_array_sha256"]
    assert len(accepted_classifier) == 1
    assert result["regions"][:2] == original["regions"][:2]
    assert result["regions"][3:] == original["regions"][3:]
    assert result["regions"][2]["words"] == original["regions"][2]["words"]
    assert result["regions"][2]["completeness_evidence"] == original["regions"][2]["completeness_evidence"]
    assert result["regions"][2]["resolved_words"][0]["text"] == "1J"
    assert "4J KL" in [o["raw_text"] for o in receipt["row_checks"][2]["observations"]]
    assert data == original and index == raw and np.array_equal(image, pixels)


def test_complete_ordinary_group_passes_without_calling_classifier(accepted_classifier):
    image, data, index = _fixture()
    row = data["regions"][0]
    data["groups"] = [{"id": "ordinary", "region_ids": [row["id"]],
                       "text": row["text"], "complete": True, "bbox_xyxy_px": row["bbox_xyxy_px"]}]
    result, receipt = resolution.resolve_group_from_source(image, data, index, "ordinary")
    assert receipt["status"] == "PASSTHROUGH_COMPLETE_GROUP"
    assert receipt["accepted"] and not receipt["changed"]
    assert result["regions"] == data["regions"]
    assert not accepted_classifier


def test_missing_suffix_is_not_repaired_by_a_character_decision(accepted_classifier):
    image, data, index = _fixture()
    model = index["pending_regions"][0]["raw_observations"][-1]
    model["raw_text"] = model["raw_text"][:-1]
    model["raw_CTC_tokens"] = model["raw_CTC_tokens"][:-1]
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["NON_CONFLICT_CHARACTERS_OR_SUFFIX_DISAGREE"]
    assert not receipt["accepted"] and result["groups"] == data["groups"]
    assert result["regions"] == data["regions"] and not accepted_classifier


def test_source_hash_and_component_hash_mismatches_stop_before_classification(accepted_classifier):
    for kind in ("source", "component"):
        image, data, index = _fixture()
        if kind == "source":
            index["source_array_sha256"] = "0" * 64
        else:
            index["pending_regions"][0]["source_components"][0]["original_crop_sha256"] = "0" * 64
        result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
        assert not receipt["accepted"]
        assert result["regions"] == data["regions"]
    assert not accepted_classifier


def _rebind_crops(image, data, index):
    data["source_array_sha256"] = index["source_array_sha256"] = text.source_array_sha256(image)
    observations = [a for r in data["regions"] for a in r["completeness_evidence"]["alternatives"]]
    observations += index["pending_regions"][0]["raw_observations"]
    for observation in observations:
        crop = observation["source_crop_xyxy_px"]
        digest = text.source_array_sha256(image[crop[1]:crop[3], crop[0]:crop[2]])
        if observation["engine"] == "PP-OCR":
            observation["original_crop_sha256"] = digest
        else:
            for word in observation["words"]:
                word["observation_provenance"]["specification"]["crop_array_sha256"] = digest


def test_dot_outside_tight_component_but_inside_original_halo_is_not_erased(accepted_classifier):
    image, data, index = _fixture()
    image[105, 46] = 0
    _rebind_crops(image, data, index)
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["DOT_OR_NEIGHBOR_IN_TARGET_GLYPH_HALO"]
    assert result["regions"] == data["regions"] and not accepted_classifier
    assert image[105, 46] == 0


def test_same_model_crop_aliases_do_not_create_required_contexts(accepted_classifier):
    image, data, index = _fixture()
    observations = index["pending_regions"][0]["raw_observations"]
    observations[-1] = copy.deepcopy(observations[-2])
    observations[-1]["observation_key"] = "different-name-same-input"
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["INSUFFICIENT_BOUND_MODEL_SOURCE_CONTEXTS"]
    assert result["groups"] == data["groups"] and not accepted_classifier


def test_true_pixel_clipping_rejects_even_with_updated_hashes_and_complete_flag(accepted_classifier):
    image, data, index = _fixture()
    row = copy.deepcopy(data["regions"][0])
    x0, y0, x1, y1 = row["bbox_xyxy_px"]
    clipped = image[y0:y1, x0:x1].copy()
    row["bbox_xyxy_px"] = [0, 0, x1 - x0, y1 - y0]
    for word in row["words"]:
        b = word["bbox_xyxy_px"]
        word["bbox_xyxy_px"] = [b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0]
    row["completeness_evidence"]["alternatives"] = [_tess(clipped, row, 0, 7), _tess(clipped, row, 0, 13)]
    roi = row["bbox_xyxy_px"]
    data.update(source_size_px=[clipped.shape[1], clipped.shape[0]],
                roi_xyxy_px=roi, source_array_sha256=text.source_array_sha256(clipped),
                regions=[row], groups=[{"id": "cut", "region_ids": [row["id"]],
                                        "text": row["text"], "complete": True}])
    index = {"source_array_sha256": data["source_array_sha256"], "roi_xyxy_px": roi, "pending_regions": []}
    result, receipt = resolution.resolve_group_from_source(clipped, data, index, "cut")
    assert receipt["reasons"] == ["COMPLETE_ROW_LACKS_TWO_BOUND_SOURCE_WITNESSES"]
    assert not receipt["accepted"] and result["regions"] == data["regions"]
    assert not accepted_classifier and (clipped[0] < 192).any()


def test_later_incomplete_row_rolls_back_an_earlier_valid_character_resolution(accepted_classifier):
    image, data, index = _fixture()
    fourth = data["regions"][3]
    fourth.update(complete=False, unresolved_reasons=["UNCONFIRMED_SUFFIX"])
    group = data["groups"][0]
    group["region_ids"].append(fourth["id"])
    group["text"] += "\n" + fourth["text"]
    group["lines"].append({"region_id": fourth["id"], "text": fourth["text"], "complete": False})
    # The classifier's reference assertion is irrelevant to transaction order.
    def accepted(*args, **kwargs):
        accepted_classifier.append("called")
        return {"accepted": True, "character": "1"}
    old = resolution.propose_glyph_identity
    resolution.propose_glyph_identity = accepted
    try:
        result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    finally:
        resolution.propose_glyph_identity = old
    assert accepted_classifier
    assert receipt["reasons"] == ["INCOMPLETE_ROW_MISSING_CONFIRMATION_ENTRY"]
    assert not receipt["accepted"] and result["regions"] == data["regions"]
    assert result["groups"] == data["groups"]


def test_non_glyph_thin_neighbor_crossing_word_still_participates_in_ownership():
    image = np.full((64, 72), 255, np.uint8)
    image[20:40, 16:18] = 0
    image[20:22, 16:21] = 0
    image[20:40, 45:47] = 0
    image[20:22, 45:51] = 0
    image[10:50, 34] = 0  # Real neighbor filtered out by the compact-glyph heuristic.
    original = image.copy()
    with pytest.raises(ValueError, match="RAW_SOURCE_COMPONENT_SHARED_OUTSIDE_WORD"):
        resolution._local_components(image, [16, 20, 51, 40], [0, 0, 72, 64])
    assert np.array_equal(image, original)


def test_declared_model_confidence_cannot_override_actual_token_scores(accepted_classifier):
    image, data, index = _fixture()
    index["pending_regions"][0]["raw_observations"][-1]["raw_CTC_tokens"][0]["score"] = .50
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["MODEL_DECLARED_CONFIDENCE_DIFFERS_FROM_RAW_TOKENS"]
    assert not receipt["accepted"] and result["regions"] == data["regions"]
    assert not accepted_classifier


def test_ambiguous_morphology_saves_counterexample_and_preserves_group(monkeypatch):
    image, data, index = _fixture()
    monkeypatch.setattr(resolution, "propose_glyph_identity", lambda *a, **k: {
        "accepted": False, "character": None, "reason": "SYNTHETIC_TIE", "metrics": {"margin": 0}
    })
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["SOURCE_GLYPH_PROPOSAL_REMAINS_AMBIGUOUS"]
    assert receipt["counterexample"]["glyph_proposal"]["reason"] == "SYNTHETIC_TIE"
    assert result["regions"] == data["regions"] and result["groups"] == data["groups"]


def test_surrounding_frame_bbox_overlap_is_not_source_ink_ownership():
    image = np.full((64, 72), 255, np.uint8)
    image[20:40, 16:18] = 0
    image[20:22, 16:21] = 0
    image[20:40, 45:47] = 0
    image[20:22, 45:51] = 0
    # This connected, compact frame's bounding rectangle contains the word,
    # but none of its original pixels belongs to the word's source domain.
    image[12:49, 8] = image[12:49, 59] = 0
    image[12, 8:60] = image[48, 8:60] = 0
    before = image.copy()
    components = resolution._local_components(image, [16, 20, 51, 40], [0, 0, 72, 64])
    assert [g["bbox_xyxy_px"] for g in components] == [[16, 20, 21, 40], [45, 20, 51, 40]]
    assert np.array_equal(image, before)


def test_complete_internal_thin_neighbor_stays_unassigned_and_blocks_new_adoption(accepted_classifier):
    image, data, index = _fixture()
    image[115:130, 80] = 0  # Entirely inside row, outside the first glyph halo.
    _rebind_crops(image, data, index)
    before = image.copy()
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["UNASSIGNED_NONCOMPACT_SOURCE_IN_RESOLVED_ROW"]
    assert not receipt["accepted"] and result["regions"] == data["regions"]
    assert not accepted_classifier and np.array_equal(image, before)


def test_invalid_indexed_reference_records_the_specific_mismatch(accepted_classifier):
    image, data, index = _fixture()
    index["pending_regions"][0]["same_page_reliable_character_references"] = {
        "1": [{"complete_region_id": "ref-digit", "raw_complete_word": "12",
               "bbox_xyxy_px": [40, 185, 47, 209], "original_crop_sha256": "0" * 64}]
    }
    result, receipt = resolution.resolve_group_from_source(image, data, index, "paragraph")
    assert receipt["reasons"] == ["INDEXED_REFERENCE_NO_LONGER_MATCHES_SOURCE_AND_COMPLETE_WORD"]
    evidence = receipt["counterexample"]
    assert evidence["reference_character"] == "1"
    assert evidence["indexed_reference"]["complete_region_id"] == "ref-digit"
    assert evidence["recomputed_reference"]["original_crop_sha256"] != "0" * 64
    assert result["regions"] == data["regions"] and not accepted_classifier
