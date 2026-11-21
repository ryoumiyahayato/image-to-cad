"""Synthetic source-shape regressions; no private drawing or OCR fixtures."""

import copy
import json
import math

import numpy as np
import pytest

from app.native_objects.text_glyph_adjudication import (
    bitmap_sha256,
    propose_glyph_identity,
)


def tight(mask):
    yy, xx = np.where(mask)
    return mask[yy.min() : yy.max() + 1, xx.min() : xx.max() + 1].copy()


def glyph(shoulder=True, variant=0):
    mask = np.zeros((30, 20), dtype=bool)
    mask[:, 10:12] = True
    if shoulder:
        for x in range(3, 11):
            y = 10 - x
            mask[y, x] = True
            if y + 1 < 30:
                mask[y + 1, x] = True
    if variant:
        y = (12, 19, 25, 15, 22)[(variant - 1) % 5]
        x = 9 if variant % 2 else 12
        mask[y, x] = True
    return tight(mask)


def references():
    return [
        {
            "character": char,
            "bitmap": glyph(shoulder, variant),
            "reliable": True,
            "reference_id": f"synthetic-{char}-{variant}",
        }
        for char, shoulder in (("1", True), ("I", False))
        for variant in range(4)
    ]


def context_for(target):
    h, w = target.shape
    top = math.ceil(h / 3)
    context = np.zeros((h + top + 2, w + 4), dtype=bool)
    context[top : top + h, 2 : 2 + w] = target
    return {
        "context_bitmap": context,
        "target_bbox_in_context": [2, top, 2 + w, top + h],
        "source_evidence": {
            "source_hash_verified": True,
            "ownership_verified": True,
            "no_shared_source": True,
            "source_sha256": "a" * 64,
            "context_sha256": bitmap_sha256(context),
        },
    }


def propose(target, refs=None, **kwargs):
    args = context_for(target)
    args.update(kwargs)
    return propose_glyph_identity(
        target, references() if refs is None else refs, ["1", "I", "i"], **args
    )


def test_positive_shoulder_is_source_supported_without_expected_word():
    target = glyph()
    refs = references()
    original = target.copy()
    reference_copies = [r["bitmap"].copy() for r in refs]
    report = propose(target, refs)
    assert report["accepted"] and report["character"] == "1"
    assert report["metrics"]["ascending_path_rise_px"] > 0
    assert report["calibration"]["missing_or_insufficient_alternative_classes"] == ["i"]
    assert any("No sufficiently sampled" in item for item in report["limitations"])
    assert np.array_equal(target, original)
    assert all(np.array_equal(r["bitmap"], saved) for r, saved in zip(refs, reference_copies))
    assert not report["source_pixels_modified"] and not report["ocr_called"]
    json.dumps(report, allow_nan=False)


def test_thresholds_are_reference_calibrated_and_do_not_depend_on_target():
    first = propose(glyph())
    altered = glyph(variant=4)
    second = propose(altered)
    a = first["calibration"]["classes"]["1"]["shoulder_calibration"]
    b = second["calibration"]["classes"]["1"]["shoulder_calibration"]
    for metric in a:
        assert a[metric]["threshold"] == b[metric]["threshold"]
        assert a[metric]["threshold"] == (a[metric]["positive_min"] + a[metric]["negative_max"]) / 2


def test_leave_one_reference_out_retains_class_separation():
    refs = references()
    for held_out in refs:
        remaining = [r for r in refs if r is not held_out]
        report = propose(held_out["bitmap"], remaining)
        if held_out["character"] == "1":
            assert report["preferred_character"] == "1"
        else:
            assert not report["accepted"]
        own = report["calibration"]["classes"][held_out["character"]]
        other = report["calibration"]["classes"]["I" if held_out["character"] == "1" else "1"]
        assert own["nearest_target_distance"] < other["nearest_target_distance"]


def test_missing_context_keeps_preference_without_adoption():
    report = propose_glyph_identity(glyph(), references(), ["1", "i"])
    assert not report["accepted"] and report["preferred_character"] == "1"
    assert "verified_source_context_missing" in report["reasons"]


@pytest.mark.parametrize("flag", ["source_hash_verified", "ownership_verified", "no_shared_source"])
def test_unverified_source_or_ownership_blocks_adoption(flag):
    target = glyph()
    args = context_for(target)
    args["source_evidence"][flag] = False
    report = propose(target, **args)
    assert not report["accepted"] and flag + "_missing" in report["reasons"]


def test_context_digest_and_pixels_are_bound_to_original():
    target = glyph()
    args = context_for(target)
    args["context_bitmap"][args["target_bbox_in_context"][1] + 10, -3] = False
    report = propose(target, **args)
    assert not report["accepted"]
    assert "context_hash_not_verified" in report["reasons"]
    assert "context_target_pixels_differ" in report["reasons"]


def test_detached_upper_dot_in_original_context_is_not_discarded():
    target = glyph()
    args = context_for(target)
    args["context_bitmap"][2:4, -4:-2] = True
    args["source_evidence"]["context_sha256"] = bitmap_sha256(args["context_bitmap"])
    report = propose(target, **args)
    assert not report["accepted"]
    assert "additional_source_ink_or_detached_dot" in report["reasons"]


def test_real_dot_and_stem_are_not_collapsed_into_one_component():
    target = np.zeros((30, 5), dtype=bool)
    target[:3, 1:4] = True
    target[7:, 2:4] = True
    target = tight(target)
    report = propose(target)
    assert not report["accepted"]
    assert report["metrics"]["component_count"] == 2


def test_disconnected_upper_i_remains_a_negative_not_a_lowercase_vote():
    target = glyph(False)
    target[19, :] = False
    report = propose(target)
    assert not report["accepted"]
    assert "target_support_fragmented_or_multiple_components" in report["reasons"]


def test_known_fragmented_negative_reference_is_retained():
    refs = references()
    broken = glyph(False)
    broken[20, :] = False
    refs.append({"character": "I", "bitmap": broken, "reliable": True, "reference_id": "broken-negative"})
    report = propose(glyph(), refs)
    negative = report["calibration"]["classes"]["I"]
    assert "broken-negative" in negative["reference_ids"]
    assert any(m["component_count"] == 2 for m in negative["reference_metrics"])


def test_damaged_i_and_horizontal_serif_do_not_supply_an_ascending_shoulder():
    damaged = np.zeros((30, 15), dtype=bool)
    damaged[:, 10:12] = True
    damaged[3, 2:12] = True
    report = propose(tight(damaged))
    assert not report["accepted"]
    assert report["preferred_character"] is None


@pytest.mark.parametrize("clipped", [glyph()[9:, :], glyph()[:-9, :]])
def test_truncated_one_is_not_promoted_from_remaining_strokes(clipped):
    report = propose(tight(clipped))
    assert not report["accepted"]


def test_explicit_incomplete_source_is_never_adopted():
    report = propose(glyph(), source_complete=False)
    assert not report["accepted"]
    assert "source_incomplete_or_clipped" in report["reasons"]


def test_separate_neighbor_line_is_not_removed_to_fit_a_reference():
    target = np.pad(glyph(), ((0, 0), (4, 0)))
    target[:, 0] = True
    report = propose(target)
    assert not report["accepted"] and report["metrics"]["component_count"] == 2


def test_connected_neighbor_line_fails_shape_or_pixel_envelope():
    target = np.pad(glyph(), ((0, 0), (4, 0)))
    target[:, 0] = True
    target[15, :] = True
    report = propose(target)
    assert not report["accepted"]


def test_reference_aliases_do_not_create_independent_votes():
    refs = references()
    positives = [copy.deepcopy(refs[0]) for _ in range(4)]
    for i, ref in enumerate(positives):
        ref["reference_id"] = f"renamed-alias-{i}"
    report = propose(glyph(), positives + [r for r in refs if r["character"] == "I"])
    assert not report["accepted"]
    assert report["calibration"]["reference_counts"]["1"] == 1


def test_one_known_counterexample_is_not_ignored_for_small_class_size():
    refs = references()
    ref = {"character": "i", "bitmap": glyph(variant=5), "reliable": True, "reference_id": "known-joined-i"}
    report = propose(glyph(), refs + [ref])
    assert not report["accepted"]
    assert "i" in report["calibration"]["classes"]


def test_identical_pixels_with_conflicting_labels_remain_a_conflict():
    refs = references()
    ref = {"character": "i", "bitmap": glyph(), "reliable": True, "reference_id": "same-pixels-other-label"}
    report = propose(glyph(), refs + [ref])
    assert not report["accepted"]
    assert "contradictory_reference_label_or_source_alias" in report["reasons"]


def test_shape_classes_that_overlap_are_not_separated_by_labels():
    refs = references()
    for ref in refs:
        if ref["character"] == "I":
            ref["bitmap"] = glyph(True, int(ref["reference_id"].split("-")[-1]) + 2)
    assert not propose(glyph(), refs)["accepted"]


def test_grayscale_polarity_is_not_guessed():
    report = propose_glyph_identity((~glyph()).astype(np.uint8) * 255, references(), ["1", "i"])
    assert not report["accepted"] and report["reason"] == "invalid_target_bitmap"
