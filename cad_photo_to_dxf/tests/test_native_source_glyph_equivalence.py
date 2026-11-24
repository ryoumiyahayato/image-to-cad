"""Sampling-scale features cannot replace original ink or invent closed loops."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.native_objects import source_glyph_equivalence as glyphs
from app.native_objects import text_regions


def _component(mask, x=10):
    yy, xx = np.nonzero(mask)
    mask = mask[yy.min():yy.max()+1, xx.min():xx.max()+1].copy()
    return {
        "bbox_xyxy_px": [x, 10, x+mask.shape[1], 10+mask.shape[0]],
        "source_area_px": int(mask.sum()), "source_role": "FULL_HEIGHT_GLYPH",
        "source_runs_y_x0_x1": text_regions._rle(mask, [x, 10]),
        "source_white_gaps_not_filled": True,
    }


def _letter(letter):
    mask = np.zeros((40, 40), np.uint8)
    cv2.putText(mask, letter, (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, 1, 1, cv2.LINE_8)
    yy, xx = np.nonzero(mask)
    return mask[yy.min():yy.max()+1, xx.min():xx.max()+1].copy()


def _one_sample_break(mask):
    result = mask.copy()
    y = result.shape[0]//2
    xs = np.flatnonzero(result[y])
    assert len(xs) == 1
    result[y, xs[0]] = 0
    assert glyphs._topology(result)["foreground_components"] == 2
    return result


def _conflict(parts, candidate, competing):
    rows = [{"view_index": index, "text": text, "component_characters": list(text)}
            for index, text in enumerate((candidate, competing))]
    model = [{"view_index": 0, "text": candidate, "component_characters": list(candidate)}]
    return glyphs.verify_raw_character_conflicts({"components": parts}, candidate, rows, model)


def test_half_cell_sampling_twin_retains_original_fragment_and_unchanged_limits():
    mask = _letter("2")
    broken = _one_sample_break(mask)
    extended = np.pad(broken, ((0, 0), (1, 0)))
    extended[-1, 0] = 1
    left, right = _component(extended), _component(mask, 50)
    before = deepcopy((left, right))
    proof = glyphs.compare_original_glyphs(left, right)
    assert proof["pass"], proof
    assert proof["comparison_path"] == "SAMPLING_UNCERTAINTY_CANDIDATE_SUPPORT"
    assert not proof["strict_zero_registration_comparison"]["pass"]
    sampling = proof["sampling_uncertainty_comparison"]
    assert len(sampling["registrations"]) == 9
    assert sampling["selected_registration"]["translation_source_px"] != [0, 0]
    assert sampling["distance_limits_changed"] is False
    assert sampling["original_points_used_in_every_distance_check"] is True
    assert sampling["feature_mask_written_to_source_or_geometry"] is False
    assert (left, right) == before
    reverse = glyphs.compare_original_glyphs(right, left)
    assert reverse["pass"] == proof["pass"]
    assert reverse["sampling_uncertainty_comparison"]["selected_registration"]["metrics"] == pytest.approx(
        sampling["selected_registration"]["metrics"])


def test_sampling_twin_also_needs_a_frozen_competing_macro_structure():
    source = _letter("2")
    parts = [_component(_one_sample_break(source)), _component(_letter("P"), 50),
             _component(source, 90)]
    before = deepcopy(parts)
    proof = _conflict(parts, "2P2", "PP2")
    assert proof["pass"], proof
    char = proof["conflicts"][0]["characters"][0]
    assert char["resolution_path"] == "SAMPLING_UNCERTAINTY_AND_FROZEN_COMPETING_SOURCE_CONTRADICTION"
    counter = char["competing_character_macro_contradictions"][0]
    assert counter["anchor"]["component_index"] == 1
    assert counter["distance_failure_alone_used_as_exclusion"] is False
    assert parts == before
    # The same shape support cannot ignore a different raw literal for which
    # this original row provides no independent competing-character witness.
    assert not _conflict(parts, "2P2", "ZP2")["pass"]


def test_competing_distance_failure_without_macro_contradiction_is_not_exclusion():
    source = _letter("2")
    parts = [_component(_one_sample_break(source)), _component(_letter("Z"), 50),
             _component(source, 90)]
    proof = _conflict(parts, "2Z2", "ZZ2")
    assert not proof["pass"]
    char = proof["conflicts"][0]["characters"][0]
    assert char["matching_anchors"]
    assert not char["competing_character_macro_contradictions"]


def _ring():
    mask = np.zeros((27, 17), np.uint8)
    mask[[0, -1], :] = 1
    mask[:, [0, -1]] = 1
    return mask


def test_real_one_pixel_open_ring_is_unknown_after_offset_not_a_closed_original_hole():
    closed = _ring()
    opened = closed.copy()
    opened[13, -1] = 0  # a real one-source-pixel white opening
    two_holes = closed.copy()
    two_holes[13, :] = 1
    parts = [_component(opened), _component(closed, 50), _component(two_holes, 90)]
    before = deepcopy(parts)
    feature = glyphs._half_cell_stable_topology(opened)
    assert glyphs._topology(opened)["background_holes"] == 0
    assert feature["known"] is False
    assert feature["background_holes"] is None
    assert feature["new_holes_from_original_exterior"] == 1
    pair = glyphs.compare_original_glyphs(parts[0], parts[1])
    assert not pair["pass"]
    assert "SOURCE_TWIN_STABLE_TOPOLOGY_UNKNOWN" in pair["reasons"]
    proof = _conflict(parts, "OOB", "BOB")
    assert not proof["pass"]
    assert not proof["conflicts"][0]["characters"][0]["competing_character_macro_contradictions"]
    assert parts == before and opened[13, -1] == 0


def test_ambiguous_letter_o_and_zero_source_twins_do_not_force_a_choice():
    mask = _ring()
    parts = [_component(mask), _component(mask, 50), _component(mask, 90)]
    proof = _conflict(parts, "OO0", "0O0")
    assert not proof["pass"]
    assert proof["conflicts"][0]["characters"][0]["other_character_equivalents"]


def test_a_disappearing_micro_hole_is_recorded_without_filling_the_source():
    mask = np.ones((9, 9), np.uint8)
    punctured = mask.copy()
    punctured[4, 4] = 0
    left, right = _component(punctured), _component(mask, 50)
    before = deepcopy(left)
    proof = glyphs.compare_original_glyphs(left, right)
    assert proof["pass"]
    feature = proof["sampling_uncertainty_comparison"]["left_stable_topology"]
    assert feature["known"] and feature["background_holes"] == 0
    assert feature["disappeared_original_hole_count"] == 1
    assert proof["left_topology"]["background_holes"] == 1
    assert left == before and glyphs.component_samples(left)[0][4, 4] == 0


@pytest.mark.parametrize("difference", ["persistent_hole", "long_white_gap", "short_branch"])
def test_real_holes_gaps_and_branches_cannot_be_removed_by_sampling_features(difference):
    if difference == "persistent_hole":
        base = np.ones((27, 17), np.uint8)
        other = base.copy()
        other[10:17, 5:12] = 0
    else:
        base = np.zeros((27, 17), np.uint8)
        base[:, 0] = 1
        base[-1, :] = 1
        other = base.copy()
        if difference == "long_white_gap":
            other[11:14, 0] = 0
        else:
            other[12, 1:5] = 1
    left, right = _component(base), _component(other, 50)
    before = deepcopy((left, right))
    proof = glyphs.compare_original_glyphs(left, right)
    assert not proof["pass"]
    if difference == "short_branch":
        assert "SOURCE_TWIN_NO_QUANTIZATION_BOUNDED_REGISTRATION" in proof["reasons"]
    else:
        assert "SOURCE_TWIN_TOPOLOGY_DIFFERS" in proof["reasons"]
    assert (left, right) == before
