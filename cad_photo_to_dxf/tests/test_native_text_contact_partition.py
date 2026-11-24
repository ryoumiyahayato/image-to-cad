"""Contact row source protection and raw decisions; no OCR/model execution."""

from copy import deepcopy
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.native_objects import single_line_labels as labels
from app.native_objects import text_contact_partition as contact


def _catalog(gray):
    roi = [0, 0, gray.shape[1], gray.shape[0]]
    label_map, components = labels._catalog(gray, roi)
    return roi, label_map, components


def _ordinary_partition(text="AB-12,3"):
    gray = np.full((150, 400), 255, np.uint8)
    cv2.putText(gray, text, (35, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.85, 0, 1, cv2.LINE_8)
    yy, xx = np.nonzero(gray < 192)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    roi = [0, 0, 400, 150]
    partition, reason = labels._partition_original_row(gray, roi, box)
    assert partition is not None and reason is None
    return gray, roi, box, partition


def _contact_decision_partition(text="AB-12,3"):
    # _decision receives a source partition already reconstructed by the
    # public recognition entry. These fixtures isolate its raw-data gates.
    _, _, _, partition = _ordinary_partition(text)
    partition["text_contact_separation"] = {
        "schema": "complete-original-contact-row-separation-v1"
    }
    return partition


def _prediction(text, score=0.999):
    tokens = [
        {"time_step": i + 1, "token_index": i + 50, "character": c, "score": score}
        for i, c in enumerate(text)
    ]
    return {
        "raw_text": text,
        "raw_CTC_tokens": tokens,
        "model_mean_confidence": score,
        "minimum_emitted_character_confidence": score,
    }


def _word_view(partition, text="AB-12,3", confidence=2.0):
    return {
        "words": [
            {
                "text": text,
                "confidence": confidence,
                "bbox_xyxy_px": partition["bbox_xyxy_px"],
            }
        ],
        "raw_tsv_integrity": True,
    }


def _decision(partition, text="AB-12,3", *, prediction=None, word=None):
    return labels._decision(
        [word or _word_view(partition, text)],
        [{"prediction": prediction or _prediction(text)}],
        partition,
    )


def test_a_broken_baseline_foot_is_associated_without_painting_the_real_gap():
    gray = np.full((60, 70), 255, np.uint8)
    gray[20:40, 20] = 0
    gray[39, 22:31] = 0
    roi, label_map, components = _catalog(gray)
    original = gray.copy()
    rows, joins = contact._join_fragments(components, 20, 40)
    assert len(rows) == 1 and joins[0]["rule"] == "BOTTOM_STEM_FOOT"
    record = labels._component_record(rows[0], label_map, roi, "FULL_HEIGHT_GLYPH")
    assert len(record["source_component_labels"]) == 2
    assert record["source_white_gaps_not_filled"]
    assert all(
        not (y == 39 and x0 <= 21 < x1) for y, x0, x1 in record["source_runs_y_x0_x1"]
    )
    assert np.array_equal(gray, original) and gray[39, 21] == 255


@pytest.mark.parametrize("mark", ["midline_dash", "comma", "upper_quote"])
def test_a_real_dash_comma_or_upper_quote_is_not_a_stem_foot(mark):
    gray = np.full((65, 70), 255, np.uint8)
    gray[20:40, 20] = 0
    if mark == "midline_dash":
        gray[29, 22:31] = 0
    elif mark == "comma":
        cv2.line(gray, (24, 38), (22, 44), 0, 1)
    else:
        gray[15:18, 20] = 0
    _, _, components = _catalog(gray)
    original = gray.copy()
    rows, joins = contact._join_fragments(components, 20, 40)
    assert len(rows) == 2 and joins == []
    assert np.array_equal(gray, original)


def test_two_tiny_parallel_marks_remain_two_marks_across_a_white_gap():
    gray = np.full((65, 70), 255, np.uint8)
    gray[28, 20:31] = 0
    gray[31, 20:31] = 0
    _, _, components = _catalog(gray)
    rows, joins = contact._join_fragments(components, 20, 40)
    assert len(rows) == 2 and joins == []
    assert np.all(gray[29:31, 20:31] == 255)


def test_two_source_stem_fragments_can_form_a_glyph_but_the_gap_stays_white():
    gray = np.full((65, 70), 255, np.uint8)
    gray[20:29, 20] = 0
    gray[31:40, 20] = 0
    _, _, components = _catalog(gray)
    rows, joins = contact._join_fragments(components, 20, 40)
    assert len(rows) == 1 and joins[0]["rule"] == "VERTICAL_FRAGMENT_COLUMN"
    assert joins[0]["source_samples_added"] == 0
    assert np.all(gray[29:31, 20] == 255)


def _split_upper_branch():
    gray = np.full((70, 70), 255, np.uint8)
    cv2.line(gray, (18, 20), (26, 30), 0, 1)
    cv2.line(gray, (34, 20), (26, 30), 0, 1)
    cv2.line(gray, (26, 30), (26, 45), 0, 1)
    erased = np.zeros_like(gray, dtype=bool)
    erased[23:27, 29:34] = gray[23:27, 29:34] < 192
    derived = gray.copy()
    derived[erased] = 255
    roi, original_labels, _ = _catalog(gray)
    _, derived_labels, components = _catalog(derived)
    assert len(components) == 2
    return gray, derived, erased, roi, original_labels, derived_labels, components


def test_upper_branch_needs_original_local_ink_connection_and_certified_erased_samples():
    gray, derived, erased, roi, original_labels, derived_labels, components = (
        _split_upper_branch()
    )
    original = gray.copy()
    rows, joins = contact._associate_contact_fragments(
        components, 26, 46, original_labels, derived_labels, roi, gray, erased, [0, 0]
    )
    assert len(rows) == 1 and len(joins) == 1
    assert joins[0]["original_local_connection_proven"]
    assert joins[0]["source_samples_added"] == 0
    assert np.array_equal(gray, original)
    assert np.all(derived[gray == 255] == 255)


def test_an_independent_upper_quote_cannot_borrow_a_missing_original_connection():
    _, derived, erased, roi, _, derived_labels, components = _split_upper_branch()
    gray = derived.copy()  # The original itself has this real white gap.
    _, original_labels, _ = _catalog(gray)
    rows, joins = contact._associate_contact_fragments(
        components, 26, 46, original_labels, derived_labels, roi, gray, erased, [0, 0]
    )
    assert len(rows) == 2 and joins == []


def test_an_original_connection_without_a_recorded_graphic_cut_is_not_enough():
    gray, _, _, roi, original_labels, derived_labels, components = _split_upper_branch()
    rows, joins = contact._associate_contact_fragments(
        components,
        26,
        46,
        original_labels,
        derived_labels,
        roi,
        gray,
        np.zeros_like(gray, bool),
        [0, 0],
    )
    assert len(rows) == 2 and joins == []


def test_real_round_neighbor_mask_preserves_intact_O_zero_and_original_white_samples():
    gray = np.full((180, 330), 255, np.uint8)
    cv2.putText(gray, "ABO0C", (45, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 1, cv2.LINE_8)
    letters = gray.copy()
    yy, xx = np.nonzero(gray < 192)
    seed = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    cv2.circle(gray, (105, 48), 19, 0, 1)
    cv2.line(gray, (125, 30), (170, 140), 0, 1)
    original = gray.copy()
    partition, reason, plan = contact.partition_text_contact_row(
        gray, [0, 0, 330, 180], seed
    )
    assert partition is not None and reason is None and plan["paths"]
    assert partition["full_height_component_count"] == 5
    cert = partition["text_contact_separation"]
    assert cert["independent_round_observations"]
    # These complete original glyphs lie close enough that the circular
    # outer mask would overlap their ink without the intact-anchor guard.
    protected = np.zeros_like(gray, bool)
    protected[:, 87:124] = letters[:, 87:124] < 192
    yy, xx = np.mgrid[:180, :330]
    circle = cert["independent_round_observations"][0]
    radius = (
        circle["inner_boundary_radius_px"]
        + contact.POLICY["round_source_outer_margin_px"]
    )
    disk = (xx - circle["center"][0]) ** 2 + (
        yy - circle["center"][1]
    ) ** 2 <= radius**2
    assert (disk & protected).any()
    erased = np.zeros_like(gray, bool)
    contact._mark(erased, cert["recognition_excluded_source_runs"], [0, 0])
    assert not (erased & protected).any()
    normalized, _ = labels._view(gray, partition, 2, 0)
    box = partition["bbox_xyxy_px"]
    source_crop = gray[box[1] : box[3], box[0] : box[2]]
    assert np.all(normalized[::2, ::2][source_crop == 255] == 255)
    assert np.array_equal(gray, original)
    assert cert["real_source_white_gaps_filled"] is False
    assert cert["source_pixels_added"] == 0


def test_no_complete_independent_geometry_means_no_contact_partition(monkeypatch):
    gray, roi, seed, _ = _ordinary_partition()
    monkeypatch.setattr(
        contact.graphics,
        "plan_text_contact_geometry",
        lambda *args, **kwargs: {"paths": []},
    )
    partition, reason, _ = contact.partition_text_contact_row(
        gray, roi, seed, context={"source_graph": SimpleNamespace(rounds=[])}
    )
    assert partition is None and reason == "NO_COMPLETE_INDEPENDENT_CONTACT_PATH"


def test_contact_word_aggregate_score_is_advisory_but_raw_literal_agreement_is_required():
    partition = _contact_decision_partition()
    word = _word_view(partition, confidence=1.0)
    raw_before = deepcopy(word)
    result = _decision(partition, word=word)
    assert result["accepted"] and result["text"] == "AB-12,3"
    assert (
        result["contact_Tesseract_aggregate_word_scores"][0][
            "strict_legacy_word_gate_met"
        ]
        is False
    )
    assert word == raw_before
    assert not _decision(partition, word=_word_view(partition, "AB-12,8"))["accepted"]
    legacy = deepcopy(partition)
    del legacy["text_contact_separation"]
    assert not _decision(legacy, word=word)["accepted"]


@pytest.mark.parametrize("character", ["B", "2", "-", ","])
def test_every_actual_contact_character_keeps_the_strict_model_minimum(character):
    partition = _contact_decision_partition()
    prediction = _prediction("AB-12,3")
    for token in prediction["raw_CTC_tokens"]:
        if token["character"] == character:
            token["score"] = 0.94
    scores = [t["score"] for t in prediction["raw_CTC_tokens"]]
    prediction["model_mean_confidence"] = sum(scores) / len(scores)
    prediction["minimum_emitted_character_confidence"] = min(scores)
    assert not _decision(partition, prediction=prediction)["accepted"]


def test_contact_model_mean_gate_is_not_replaced_by_the_word_score_rule():
    partition = _contact_decision_partition()
    assert not _decision(partition, prediction=_prediction("AB-12,3", score=0.97))[
        "accepted"
    ]


@pytest.mark.parametrize("raw", ["AB12,3", "AB-123", "AB-12", "AB-12,34"])
def test_contact_requires_every_source_character_and_punctuation(raw):
    partition = _contact_decision_partition()
    assert not _decision(partition, text=raw)["accepted"]


def test_contact_raw_word_geometry_must_cover_the_whole_source_label():
    partition = _contact_decision_partition()
    view = _word_view(partition)
    box = list(view["words"][0]["bbox_xyxy_px"])
    box[2] -= 15
    view["words"][0]["bbox_xyxy_px"] = box
    decision = _decision(partition, word=view)
    assert not decision["accepted"]
    assert any(
        "RAW_WORD_BOXES_DO_NOT_COVER_COMPLETE_SOURCE_LABEL" in row["reasons"]
        for row in decision["unaccepted_raw_views_retained"]
    )


def test_bad_raw_records_cannot_be_overridden_by_a_second_contact_view():
    partition = _contact_decision_partition()
    good = _word_view(partition)
    bad = deepcopy(good)
    bad["raw_tsv_integrity"] = False
    prediction = _prediction("AB-12,3")
    assert not labels._decision([bad, good], [{"prediction": prediction}], partition)[
        "accepted"
    ]
    broken = deepcopy(prediction)
    broken["raw_text"] = "AB-12,8"
    assert not labels._decision(
        [good], [{"prediction": broken}, {"prediction": prediction}], partition
    )["accepted"]


def test_duplicate_raw_dash_tokens_require_one_actual_continuous_source_stroke():
    partition = _contact_decision_partition()
    result = labels._source_canonical_text("AB--12,3", partition)
    assert result["text"] == "AB-12,3"
    assert result["normalizations"][0]["raw_character"] == "--"
    assert (
        result["normalizations"][0]["rule"]
        == "ONE_ORIGINAL_CONTINUOUS_HORIZONTAL_DASH_COMPONENT"
    )
    broken = deepcopy(partition)
    dash = next(
        c for c in broken["components"] if c["source_role"] == "RETAINED_PUNCTUATION"
    )
    midpoint = (dash["bbox_xyxy_px"][0] + dash["bbox_xyxy_px"][2]) // 2
    runs = []
    for y, x0, x1 in dash["source_runs_y_x0_x1"]:
        if x0 < midpoint:
            runs.append([y, x0, midpoint])
        if midpoint + 2 < x1:
            runs.append([y, midpoint + 2, x1])
    dash["source_runs_y_x0_x1"] = runs
    # The original global component can connect elsewhere through a graphic;
    # its label alone cannot certify this local stroke is continuous.
    assert len(dash["source_component_labels"]) == 1
    assert labels._source_canonical_text("AB--12,3", broken)["reasons"]


def test_two_actual_dashes_with_a_white_gap_are_not_canonicalized_to_one():
    partition = _contact_decision_partition("AB--12,3")
    actual = labels._source_canonical_text("AB--12,3", partition)
    assert actual["text"] == "AB--12,3" and actual["normalizations"] == []
    assert labels._source_canonical_text("AB-12,3", partition)["reasons"]
