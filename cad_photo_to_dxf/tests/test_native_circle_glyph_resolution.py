"""Finite source-reference competition; fixtures supply pixels, never case IDs."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.native_objects import circle_glyph_resolution as resolution
from app.native_objects import source_glyph_equivalence as twins
from app.native_objects import text_regions


def _component(letter, x, y=10):
    mask = np.zeros((52, 52), np.uint8)
    cv2.putText(mask, letter, (3, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 1, 2, cv2.LINE_8)
    yy, xx = np.nonzero(mask)
    mask = mask[yy.min():yy.max() + 1, xx.min():xx.max() + 1]
    return {"source_role": "FULL_HEIGHT_GLYPH", "bbox_xyxy_px": [x, y, x + mask.shape[1], y + mask.shape[0]],
            "source_runs_y_x0_x1": text_regions._rle(mask, [x, y]), "source_area_px": int(mask.sum()),
            "source_white_gaps_not_filled": True}


def _reference(character, x, *, drawing=None, y=10):
    return {"reference_key": str((character, x, y)), "character": character,
            "source_component": _component(drawing or character, x, y),
            "bound_original_evidence_sha256": str((character, x, y))}


def _raw(*readings, strong=None):
    return {"decision": {"accepted": False, "Tesseract_raw_texts": list(readings[:1]),
                         "PP_OCR_raw_texts": list(readings[1:]),
                         "high_confidence_raw_strings": list(strong or [])},
            "complete_source_raw_characters": sorted(set(readings))}


def test_raw_disagreement_requires_two_frozen_twins_and_real_competing_class():
    target = _component("D", 10)
    references = [_reference("D", 60), _reference("D", 110), _reference("0", 160), _reference("O", 210)]
    raw = _raw("D", "0", strong=["0"])
    before = deepcopy((target, references, raw))
    result = resolution.decide_source_reference_character(target, raw, references)
    assert result["accepted"] and result["text"] == "D", result
    assert result["original_high_confidence_strings"] == ["0"]
    assert result["all_available_reference_classes"] == ["0", "D", "O"]
    assert len(result["positive_reference_keys_by_character"]["D"]) == 2
    assert all(r["geometric_competing_reading_excluded"] for r in result["comparisons"] if r["character"] != "D")
    assert (target, references, raw) == before


@pytest.mark.parametrize("bad", ["missing", "same_source_twice", "equivalent_competitor", "strong_multichar", "weak_non_ascii"])
def test_competition_or_independence_missing_never_becomes_a_positive_vote(bad):
    target = _component("D", 10)
    refs = [_reference("D", 60), _reference("D", 110), _reference("0", 160)]
    raw = _raw("D", "0", strong=["0"])
    if bad == "missing":
        refs = refs[:-1]
    elif bad == "same_source_twice":
        refs[1] = deepcopy(refs[0])
        refs[1]["reference_key"] = "second_view_of_the_same_original_glyph"
    elif bad == "equivalent_competitor":
        refs[-1] = _reference("0", 160, drawing="D")
    elif bad == "strong_multichar":
        raw["decision"]["high_confidence_raw_strings"].append("DO")
    else:
        raw["decision"]["Tesseract_raw_texts"].append("£")
    result = resolution.decide_source_reference_character(target, raw, refs)
    assert not result["accepted"] and result["text"] is None


def test_missing_lower_bar_discriminates_f_from_e_with_complete_foreground():
    target = _component("E", 10)
    refs = [_reference("E", 60), _reference("E", 110), _reference("F", 160)]
    result = resolution.decide_source_reference_character(target, _raw("E", "E"), refs)
    assert result["accepted"] and result["text"] == "E"
    competitor = next(row for row in result["comparisons"] if row["character"] == "F")
    assert competitor["comparison"]["metrics"]["symmetric_maximum_source_px"] > 5
    assert competitor["geometric_competing_reading_excluded"]


def test_circle_cross_row_positions_preserve_default_row_constraint_and_reject_same_pixels():
    left, right = _component("E", 10), _component("E", 10, y=70)
    assert not twins.compare_original_glyphs(left, right)["pass"]
    assert twins.compare_original_glyphs(left, right, require_distinct_row_positions=False)["pass"]
    assert not twins.compare_original_glyphs(left, deepcopy(left), require_distinct_row_positions=False)["pass"]
    refs = [_reference("E", 10), _reference("E", 10, y=70), _reference("F", 100)]
    result = resolution.decide_source_reference_character(left, _raw("E", "E"), refs)
    assert not result["accepted"]


def test_conflicting_labels_for_overlapping_original_reference_fail_closed():
    refs = [_reference("D", 60), _reference("0", 60, drawing="D")]
    with pytest.raises(ValueError, match="CONTRADICTORY"):
        resolution.decide_source_reference_character(_component("D", 10), _raw("D", "0"), refs)


def test_verified_row_keeps_complete_zero_when_another_glyph_bbox_has_foreign_ink(monkeypatch):
    from app.native_objects import single_line_labels

    parts = [_component("D", 10), _component("0", 60)]
    gray = np.full((70, 120), 255, np.uint8)
    for component in parts:
        for y, x0, x1 in component["source_runs_y_x0_x1"]:
            gray[y, x0:x1] = 0
    x0, y0, x1, y1 = parts[0]["bbox_xyxy_px"]
    # A graphic pixel in the first glyph's white counter is not included in
    # that already partitioned glyph's support. The separate 0 is unchanged.
    yy, xx = np.nonzero(gray[y0:y1, x0:x1] == 255)
    gray[y0 + yy[len(yy) // 2], x0 + xx[len(xx) // 2]] = 0
    proof = {"source_partition": {"components": parts}, "decision": {
        "raw_character_conflict_evidence": {"anchors": [
            {"component_index": i, "literal_character": letter,
             "Tesseract_view_indices": [0], "strict_PP_view_indices": [0]}
            for i, letter in enumerate(("D", "0"))
        ]}}}
    # This focused test supplies the whole-row replay contract; real raw
    # files/source replay are exercised by ordinary generated/real inputs.
    monkeypatch.setattr(single_line_labels, "verify_single_line_label_evidence", lambda *args: {
        "pass": True, "source_text_normalization": {"component_characters": ["D", "0"]},
    })
    exclusions = []
    refs = resolution._line_references(gray, [0, 0, 120, 70], proof, None, component_exclusions=exclusions)
    assert [row["character"] for row in refs] == ["0"]
    assert len(exclusions) == 1 and exclusions[0]["component_index"] == 0
    assert exclusions[0]["bbox_xyxy_px"] == parts[0]["bbox_xyxy_px"]
    assert exclusions[0]["whole_line_raw_and_source_replay_passed"] is True
    monkeypatch.setattr(single_line_labels, "verify_single_line_label_evidence", lambda *args: {"pass": False})
    with pytest.raises(ValueError, match="WHOLE|SINGLE_LINE_RAW_AND_SOURCE_REPLAY_FAILED"):
        resolution._line_references(gray, [0, 0, 120, 70], proof, None)
