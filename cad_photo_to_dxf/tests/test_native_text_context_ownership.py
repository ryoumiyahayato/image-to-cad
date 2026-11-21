"""Through-going graphic ownership must not become generic suffix trimming."""

import copy
import json

import numpy as np
import pytest
from scipy.ndimage import find_objects

from app.native_objects import text_context_ownership as context
from app.native_objects import text_regions as base


def sample(
    *, graphic="through", punctuation=True, texts=("ABC-7+", "ABC-7+"), truncated=False
):
    image = np.full((120, 170), 255, np.uint8)
    # Four complete full-height components, separated by real source white.
    for x in (20, 35, 50, 85):
        image[40:60, x] = 0
        image[40:42, x : x + 10] = 0
        image[58:60, x : x + 10] = 0
    if punctuation:
        image[50:52, 65:75] = 0
    if graphic == "through":
        image[15:100, 120:122] = 0
    elif graphic == "touch":
        image[40:100, 120:122] = 0
    elif graphic == "text_plus":
        image[42:59, 120:122] = 0
    image[50:52, 110:140] = 0
    roi = [1, 1, 169, 119]
    _, labels, glyphs = base._component_evidence(image, roi)
    region = {
        "id": "synthetic-pending-row",
        "bbox_xyxy_px": [20, 40, 140, 62],
        "text": "old uncertain observation",
        "complete": False,
        "accepted": False,
        "words": [
            {
                "text": "old uncertain observation",
                "confidence": 20,
                "bbox_xyxy_px": [20, 40, 140, 62],
            }
        ],
        "compact_source_ink_mask": {"runs_y_x0_x1": []},
        "unresolved_reasons": ["source_text_support_crosses_current_crop_boundary"],
    }
    data = {
        "roi_xyxy_px": roi,
        "regions": [region],
        "source_array_sha256": base.source_array_sha256(image),
    }
    records = []
    for i, (text, crop) in enumerate(
        zip(texts, ([18, 38, 142, 64], [16, 36, 144, 66]))
    ):
        crop = list(crop)
        if truncated:
            crop[2] = 90
        x0, y0, x1, y1 = crop
        digest = base.source_array_sha256(image[y0:y1, x0:x1])
        records.append(
            {
                "observation_key": f"synthetic-raw-{i}",
                "region_id": region["id"],
                "context": {"crop_xyxy_px": crop},
                "source_array_sha256": digest,
                "source_pixels_modified": False,
                "raw_model_output": {
                    "raw_text": text,
                    "input_array_sha256": digest,
                    "source_geometry_modified": False,
                    "raw_transcription_rewritten": False,
                    "raw_CTC_tokens": [
                        {"character": c, "score": 0.999, "time_step": 2 * k + 1}
                        for k, c in enumerate(text)
                    ],
                },
            }
        )
    return image, data, records, labels, find_objects(labels), glyphs


def run(item, tesseract=()):
    image, data, records, labels, slices, glyphs = item
    return context.derive_context_ownership(
        image, data, records, tesseract, labels=labels, slices=slices, glyphs=glyphs
    )


def test_complete_source_candidate_keeps_graphic_and_punctuation_pending_independent_text():
    item = sample()
    before = copy.deepcopy(item[1])
    source = item[0].copy()
    result, audit = run(item)
    evidence = result["regions"][0]["source_context_ownership"]
    assert evidence["candidate_text"] == "ABC-7"
    assert evidence["current_missing_evidence"] == [
        "INDEPENDENT_WHOLE_ROW_TRANSCRIPTION_AT_UNCHANGED_TESSERACT_GATE"
    ]
    assert evidence["independent_engine_family_count"] == 1
    assert evidence["same_model_crop_count_is_not_engine_count"] == 2
    assert len(evidence["source_partition"]["ordered_retained_components"]) == 5
    punctuation = [
        c
        for c in evidence["source_partition"]["ordered_retained_components"]
        if "PUNCTUATION" in c["source_role"]
    ]
    assert len(punctuation) == 1 and punctuation[0]["source_area_px"] == 20
    assert (
        evidence["source_partition"]["separate_terminal_graphics"][0][
            "source_rows_above_glyphs"
        ]
        == 20
    )
    assert all(
        o["original_raw_text"] == "ABC-7+"
        for o in evidence["model_prefix_observations"]
    )
    assert all(
        o["graphic_context_tokens_retained_in_original_observation"][0]["character"]
        == "+"
        for o in evidence["model_prefix_observations"]
    )
    for key in (
        "text",
        "complete",
        "accepted",
        "words",
        "bbox_xyxy_px",
        "compact_source_ink_mask",
    ):
        assert result["regions"][0][key] == before["regions"][0][key]
    assert item[1] == before and np.array_equal(item[0], source)
    assert audit["OCR_calls"] == audit["model_calls"] == 0
    json.dumps(audit, allow_nan=False)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"graphic": "text_plus"}, "NO_SEPARATE_THROUGH_GRAPHIC_AT_ROW_END"),
        (
            {"graphic": "touch"},
            "NEIGHBOR_ONLY_TOUCHES_ROW_OR_LACKS_TWO_SIDED_CONTINUATION",
        ),
        ({"punctuation": False}, "SOURCE_COMPONENT_AND_CTC_ORDER_NOT_ONE_TO_ONE"),
        ({"truncated": True}, "TRUE_RETAINED_GLYPH_TRUNCATION_IN_RECOGNITION_CONTEXT"),
        (
            {"texts": ("ABC-1+", "ABC-i+")},
            "SIMILAR_CHARACTER_OR_TRANSCRIPTION_CONFLICT_RETAINED",
        ),
        (
            {"texts": ("ABC17+", "ABC17+")},
            "HORIZONTAL_PUNCTUATION_SOURCE_AND_CTC_TOKEN_DISAGREE",
        ),
    ],
)
def test_real_negative_sources_do_not_become_a_trimmed_text(change, reason):
    item = sample(**change)
    result, audit = run(item)
    assert "source_context_ownership" not in result["regions"][0]
    assert reason in audit["events"][0]["blocked_reasons"]
    assert result["regions"][0]["text"] == "old uncertain observation"
    assert not result["regions"][0]["complete"]


def test_same_source_context_renamed_does_not_supply_a_second_vote():
    item = sample()
    item[2][1] = copy.deepcopy(item[2][0])
    item[2][1]["observation_key"] = "renamed-same-observation"
    result, audit = run(item)
    assert "source_context_ownership" not in result["regions"][0]
    assert (
        "MISSING_TWO_DISTINCT_COMPLETE_SOURCE_CONTEXT_BINDINGS"
        in audit["events"][0]["blocked_reasons"]
    )


def test_raw_observation_source_hash_mismatch_is_fatal():
    item = sample()
    item[2][0]["source_array_sha256"] = "unbound"
    with pytest.raises(ValueError, match="BOUND_MODEL_SOURCE_HASH_MISMATCH"):
        run(item)


def test_low_confidence_retained_character_is_still_pending():
    item = sample()
    item[2][0]["raw_model_output"]["raw_CTC_tokens"][1]["score"] = 0.8
    result, audit = run(item)
    assert "source_context_ownership" not in result["regions"][0]
    assert (
        "RETAINED_CHARACTER_BELOW_UNCHANGED_MODEL_GATE"
        in audit["events"][0]["blocked_reasons"]
    )


def test_already_complete_region_is_byte_equivalent():
    item = sample()
    item[1]["regions"][0]["complete"] = True
    result, audit = run(item)
    assert result == item[1]
    assert audit["events"] == []


def test_current_confirmation_and_historical_failure_are_separate():
    result, _ = run(sample())
    old = {
        "pending_regions": [
            {
                "region_id": "synthetic-pending-row",
                "unchanged_unresolved_reasons": [
                    "source_text_support_crosses_current_crop_boundary"
                ],
            }
        ]
    }
    updated = context.attach_confirmation_context(old, result)
    row = updated["pending_regions"][0]
    assert row["current_source_supported_confirmation"]["candidate_text"] == "ABC-7"
    assert row["unchanged_unresolved_reasons"] == [
        "source_text_support_crosses_current_crop_boundary"
    ]
    assert row["historical_unresolved_reasons_retained_separately"]
