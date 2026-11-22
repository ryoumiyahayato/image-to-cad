"""Source-component responsibility, with synthetic already-confirmed OCR records.

These tests do not claim recognition accuracy or run a recognizer. Their small
bitmap glyphs exercise source order, preserved grayscale, and independent lines.
"""

from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
import pytest

from app.native_objects import source_text_ownership as ownership
from app.native_objects import text_regions as base
from app.native_objects.contracts import COORDINATES
from app.native_objects.pipeline import _reclassify_source_fitted_lines


PATTERNS = {
    "C": ["11111", "10000", "10000", "10000", "10000", "10000", "11111"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "0": ["11111", "10001", "10001", "10001", "10001", "10001", "11111"],
    "O": ["11111", "10001", "10001", "10001", "10001", "10001", "11111"],
    "7": ["11111", "00001", "00001", "00010", "00100", "01000", "10000"],
    "2": ["11111", "00001", "00001", "11111", "10000", "10000", "11111"],
}


def _refresh(item):
    image, data, boxes, dense = item
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        (image < 192).astype("uint8"), 8
    )
    _, core_labels, core_stats, _ = cv2.connectedComponentsWithStats(
        (image < 128).astype("uint8"), 8
    )
    region = data["regions"][0]
    mask = np.zeros(image.shape, dtype=bool)
    excluded = {
        int(labels[(b[1] + b[3]) // 2, (b[0] + b[2]) // 2])
        for c, b in boxes
        if c in "I-,."
    }
    excluded |= {int(labels[y, x]) for x, y in dense}
    b = region["bbox_xyxy_px"]
    for label in np.unique(labels[b[1] : b[3], b[0] : b[2]]):
        if label and label not in excluded:
            mask |= labels == label
    region["compact_source_ink_mask"] = {
        "component_labels": [int(lab) for lab in np.unique(labels[mask])],
        "runs_y_x0_x1": base._rle(mask, [0, 0]),
        "source_erasure_authorized": False,
    }
    data["source_array_sha256"] = base.source_array_sha256(image)
    for observation in region["completeness_evidence"]["alternatives"]:
        spec = observation["observation_provenance"]["specification"]
        x0, y0, x1, y1 = spec["crop_xyxy_px"]
        spec["crop_array_sha256"] = base.source_array_sha256(image[y0:y1, x0:x1])
    proposals, objects = [], []
    for number, (x, y) in enumerate(dense):
        label = int(core_labels[y, x])
        assert label
        xx, yy, width, height, area = map(int, core_stats[label])
        geometry = {
            "start": [xx + (width - 1) / 2, float(yy)],
            "end": [xx + (width - 1) / 2, float(yy + height - 1)],
        }
        proposals.append(
            {
                "id": f"candidate-{number}",
                "geometry": geometry,
                "source_component_area": area,
                "decision": "RETAIN_GEOMETRY_WITH_TEXT_CONTACT",
            }
        )
        objects.append(
            {
                "id": f"candidate-{number}",
                "kind": "LINE",
                "layer": "SHORT_STROKE",
                "geometry": deepcopy(geometry),
                "source_evidence": {},
            }
        )
    for number, (a, b) in enumerate(
        (
            ([10, 90], [200, 90]),
            ([220, 20], [220, 100]),
            ([225, 120], [245, 120]),
            ([20, 140], [180, 140]),
        )
    ):
        objects.append(
            {
                "id": f"independent-{number}",
                "kind": "LINE",
                "layer": "GEOMETRY",
                "geometry": {"start": a, "end": b},
                "source_evidence": {},
            }
        )
    return {
        "objects": objects,
        "short_source_components": proposals,
        "uncertainties": [],
    }


def sample(text="CI-07, B2"):
    image = np.full((180, 280), 255, dtype=np.uint8)
    x, top, boxes, dense = 20, 40, [], []
    for c in text:
        if c == " ":
            x += 16
            continue
        if c == "I":
            image[top : top + 21, x : x + 3] = 0
            image[top : top + 21, x] = 160
            b = [x, top, x + 3, top + 21]
            dense.append((x + 1, top + 10))
        elif c == "-":
            image[top + 11 : top + 14, x : x + 9] = 0
            b = [x, top + 11, x + 9, top + 14]
        elif c == ",":
            image[top + 18 : top + 24, x : x + 3] = 0
            b = [x, top + 18, x + 3, top + 24]
        else:
            glyph = np.kron(
                np.array([[v == "1" for v in row] for row in PATTERNS[c]]),
                np.ones((3, 3), bool),
            )
            image[top : top + 21, x : x + 15][glyph] = 0
            b = [x, top, x + 15, top + 21]
        boxes.append((c, b))
        x = b[2] + 4
    for a, b in (
        ([10, 90], [200, 90]),
        ([220, 20], [220, 100]),
        ([225, 120], [245, 120]),
        ([20, 140], [180, 140]),
    ):
        cv2.line(image, tuple(a), tuple(b), 0, 1, cv2.LINE_8)
    bounds = [20, top, x - 4, max(b[3] for _, b in boxes)]
    words, offset = [], 0
    for index, word in enumerate(text.split(" ")):
        members = boxes[offset : offset + len(word)]
        offset += len(word)
        words.append(
            {
                "id": f"word-{index}",
                "text": word,
                "confidence": 98.0,
                "required_confidence": 95.0 if word.isdigit() else 85.0,
                "bbox_xyxy_px": [
                    min(b[0] for _, b in members),
                    min(b[1] for _, b in members),
                    max(b[2] for _, b in members),
                    max(b[3] for _, b in members),
                ],
                "raw_text_unchanged": True,
                "agreement_pass": True,
                "independent_agreement_observation_keys": [
                    "raw-source-a",
                    "raw-source-b",
                ],
            }
        )
    alternatives = []
    for key, margin in (("raw-source-a", 3), ("raw-source-b", 5)):
        alternatives.append(
            {
                "observation_key": key,
                "status": "COMPLETED",
                "words": deepcopy(words),
                "observation_provenance": {
                    "specification": {
                        "crop_xyxy_px": [
                            bounds[0] - margin,
                            bounds[1] - margin,
                            bounds[2] + margin,
                            bounds[3] + margin,
                        ],
                        "source_pixels_modified": False,
                        "psm": 7,
                    },
                    "engine_identity": {"name": "synthetic-already-executed-engine"},
                    "raw_tsv_sha256": hashlib.sha256(key.encode()).hexdigest(),
                },
            }
        )
    data = {
        "coordinate_system": COORDINATES,
        "source_size_px": [280, 180],
        "roi_xyxy_px": [0, 0, 280, 180],
        "regions": [
            {
                "id": "region",
                "text": text,
                "complete": True,
                "unresolved_reasons": [],
                "bbox_xyxy_px": bounds,
                "words": words,
                "completeness_evidence": {"alternatives": alternatives},
            }
        ],
        "groups": [
            {
                "id": "group",
                "kind": "single_line",
                "geometry_type": "TEXT",
                "complete": True,
                "region_ids": ["region"],
                "text": text,
            }
        ],
    }
    item = image, data, boxes, dense
    geometry = _refresh(item)
    return item, geometry


def run(item, geometry):
    image, data, _, _ = item
    result, audit = ownership.reconcile_source_text_ownership(
        data, image, data["roi_xyxy_px"], geometry
    )
    classified = _reclassify_source_fitted_lines(
        geometry,
        result,
        image.shape,
        data["roi_xyxy_px"],
        original_dictionary_sha256=ownership._digest(geometry),
    )
    return result, audit, classified


def test_dense_I_has_complete_source_order_and_retires_only_its_duplicate_line():
    item, geometry = sample()
    before, gray = deepcopy(item[1]), item[0].copy()
    result, audit, classified = run(item, geometry)
    assert len(audit["added_complete_glyph_component_labels"]) == 1
    assert audit["added_unique_complete_glyph_source_pixels"] == 63
    assert [o["id"] for o in classified["objects"]] == [
        f"independent-{i}" for i in range(4)
    ]
    proof = audit["complete_line_glyph_events"][0]
    assert (
        all(proof["checks"].values())
        and len(proof["independent_word_source_component_witnesses"]) == 2
    )
    added = proof["added_components"][0]
    assert added["character"] == "I" and added["character_index"] == 1
    assert sum(hi - lo for _, lo, hi in added["geometry_core_runs_y_x0_x1"]) == 42
    assert added["source_gray_fringe_preserved"]
    assert (
        result["groups"] == before["groups"]
        and result["regions"][0]["words"] == before["regions"][0]["words"]
    )
    assert item[1] == before and np.array_equal(item[0], gray)
    assert (
        audit["OCR_calls"]
        == audit["source_fits"]
        == audit["source_pixels_removed"]
        == 0
    )
    assert not audit["released_component_labels"]
    json.dumps(audit, allow_nan=False)
    again, a2 = ownership.reconcile_source_text_ownership(
        result, item[0], item[1]["roi_xyxy_px"], geometry
    )
    assert again == result and a2["already_reconciled_no_second_release"]


@pytest.mark.parametrize(
    "mutation",
    [
        "pending",
        "low_confidence",
        "same_context_alias",
        "no_raw_source_binding",
        "wrong_literal",
        "extra_component",
        "black_branch",
        "gray_branch",
        "vertical_extension",
        "wrong_punctuation",
        "old_mask_incomplete_anchor",
    ],
)
def test_source_counterexamples_do_not_expand_glyph_ownership(mutation):
    item, geometry = sample()
    image, data, boxes, _ = item
    region = data["regions"][0]
    ib = next(b for c, b in boxes if c == "I")
    if mutation == "pending":
        region["complete"] = False
    elif mutation == "low_confidence":
        region["words"][0]["confidence"] = 84.99
    elif mutation == "same_context_alias":
        a, b = region["completeness_evidence"]["alternatives"]
        b["observation_provenance"] = deepcopy(a["observation_provenance"])
    elif mutation == "no_raw_source_binding":
        region["completeness_evidence"]["alternatives"][0]["observation_provenance"][
            "specification"
        ]["crop_array_sha256"] = "stale"
    elif mutation == "wrong_literal":
        region["text"] = region["text"].replace("I", "0")
        data["groups"][0]["text"] = region["text"]
        region["words"][0]["text"] = region["words"][0]["text"].replace("I", "0")
    elif mutation in {"black_branch", "gray_branch"}:
        image[50, ib[2] : ib[2] + 3] = 0 if mutation == "black_branch" else 160
        geometry = _refresh(item)
    elif mutation == "vertical_extension":
        image[30:40, ib[0] : ib[2]] = 0
        geometry = _refresh(item)
    elif mutation == "extra_component":
        # A real extra source dot in the gap must not be discarded to get a match.
        image[48:50, ib[2] + 1 : ib[2] + 3] = 0
        geometry = _refresh(item)
    elif mutation == "wrong_punctuation":
        dash = next(b for c, b in boxes if c == "-")
        image[dash[1] : dash[3], dash[0] : dash[2]] = 255
        image[40:49, dash[0] : dash[0] + 3] = 0
        geometry = _refresh(item)
    else:
        region["compact_source_ink_mask"]["runs_y_x0_x1"] = []
    before = deepcopy(data)
    result, audit, classified = run(item, geometry)
    assert not audit["added_complete_glyph_component_labels"]
    assert (
        result["regions"][0]["compact_source_ink_mask"]
        == before["regions"][0]["compact_source_ink_mask"]
    )
    assert {o["id"] for o in classified["objects"]} == {
        o["id"] for o in geometry["objects"]
    }


def test_word_gap_stroke_cannot_replace_an_I_merged_with_the_preceding_character():
    item, _ = sample("CI B2")
    image, data, boxes, dense = item
    first, ib = boxes[0][1], boxes[1][1]
    image[50, first[0] + 2 : ib[0] + 1] = 0
    gap_x = ib[2] + 7
    image[40:61, gap_x : gap_x + 3] = 0
    dense[:] = [(gap_x + 1, 50)]
    # The old heuristic owns the merged C/I source. Global counts still match.
    boxes[1] = ("C", ib)
    geometry = _refresh(item)
    result, audit, classified = run(item, geometry)
    checks = audit["complete_line_glyph_events"][0]["checks"]
    assert checks["complete_source_components_match_full_literal_character_count"]
    assert not checks["each_literal_word_has_independent_complete_component_order"]
    assert not audit["added_complete_glyph_component_labels"]
    assert len(classified["objects"]) == 5 and result["groups"] == data["groups"]


def test_short_preowned_I_cannot_validate_another_missing_I():
    item, _ = sample("CII-07, B2")
    image, data, boxes, dense = item
    other = [b for c, b in boxes if c == "I"][1]
    image[40:55, other[0] : other[2]] = 255
    dense[:] = dense[:1]
    index = next(i for i, (_, b) in enumerate(boxes) if b == other)
    boxes[index] = ("C", [other[0], 55, other[2], other[3]])
    geometry = _refresh(item)
    _, audit, _ = run(item, geometry)
    assert not audit["added_complete_glyph_component_labels"]
    assert not audit["complete_line_glyph_events"][0]["checks"][
        "every_literal_I_has_full_height_source_including_preowned_I"
    ]


def test_O_zero_punctuation_and_all_source_whites_remain_unmodified():
    item, geometry = sample("CI-00, O0")
    old, gray = deepcopy(item[1]), item[0].copy()
    result, audit, _ = run(item, geometry)
    assert len(audit["added_complete_glyph_component_labels"]) == 1
    added = audit["complete_line_glyph_events"][0]["added_components"]
    assert {c["character"] for c in added} == {"I"}
    assert result["regions"][0]["text"] == old["regions"][0]["text"]
    assert np.array_equal(item[0], gray)


def test_source_binding_mismatch_is_fatal():
    item, geometry = sample()
    item[0][10, 10] = 0
    with pytest.raises(
        ValueError, match="SOURCE_TEXT_OWNERSHIP_ARRAY_BINDING_MISMATCH"
    ):
        run(item, geometry)


def test_source_crop_clipping_the_comma_does_not_prove_a_complete_word():
    item, geometry = sample()
    region = item[1]["regions"][0]
    a = region["completeness_evidence"]["alternatives"][0]
    spec = a["observation_provenance"]["specification"]
    spec["crop_xyxy_px"][3] = region["bbox_xyxy_px"][3] - 1
    x0, y0, x1, y1 = spec["crop_xyxy_px"]
    spec["crop_array_sha256"] = base.source_array_sha256(item[0][y0:y1, x0:x1])
    _, audit, _ = run(item, geometry)
    assert not audit["added_complete_glyph_component_labels"]
    assert (
        len(
            audit["complete_line_glyph_events"][0][
                "independent_word_source_component_witnesses"
            ]
        )
        == 1
    )


def test_existing_release_of_unowned_real_short_line_still_works():
    item, geometry = sample()
    image, data, _, _ = item
    region = data["regions"][0]
    region.update(complete=False, bbox_xyxy_px=[15, 35, 250, 150])
    region["words"] = [
        {
            "id": "uncertain",
            "text": "?",
            "confidence": 20,
            "bbox_xyxy_px": [223, 110, 248, 139],
            "agreement_pass": False,
        }
    ]
    data["groups"][0]["complete"] = False
    _, labels, _, _ = cv2.connectedComponentsWithStats((image < 192).astype("uint8"), 8)
    lab = int(labels[120, 230])
    mask = region["compact_source_ink_mask"]
    mask["component_labels"].append(lab)
    mask["runs_y_x0_x1"].append([120, 225, 246])
    line = next(o for o in geometry["objects"] if o["id"] == "independent-2")
    geometry["objects"].remove(line)
    proposal = {
        "id": line["id"],
        "geometry": line["geometry"],
        "source_component_area": 21,
        "decision": "DEFER_TEXT_OWNERSHIP",
    }
    geometry["short_source_components"].append(proposal)
    geometry["uncertainties"].append(deepcopy(proposal))
    result, audit, classified = run(item, geometry)
    assert audit["released_component_labels"] == [lab]
    assert audit["released_unique_source_pixels"] == 21
    assert not audit["added_complete_glyph_component_labels"]
    assert any(
        o["id"] == line["id"] and o["geometry"] == line["geometry"]
        for o in classified["objects"]
    )
    assert not any(
        y == 120 and lo <= 230 < hi
        for y, lo, hi in result["regions"][0]["compact_source_ink_mask"]["runs_y_x0_x1"]
    )


def test_existing_low_confidence_glyph_row_veto_still_protects_its_ink():
    item, geometry = sample()
    image, data, boxes, _ = item
    region = data["regions"][0]
    region["complete"] = data["groups"][0]["complete"] = False
    region["words"][0].update(confidence=20, agreement_pass=False)
    box = next(b for c, b in boxes if c == "I")
    # Existing release policy intentionally requires the 128/192 whole component
    # to match. Here the source is truly black, isolating the layout veto.
    image[box[1] : box[3], box[0] : box[2]] = 0
    geometry = _refresh(item)
    _, labels, _, _ = cv2.connectedComponentsWithStats((image < 192).astype("uint8"), 8)
    lab = int(labels[50, box[0] + 1])
    region["compact_source_ink_mask"]["component_labels"].append(lab)
    region["compact_source_ink_mask"]["runs_y_x0_x1"].extend(
        base._rle(labels == lab, [0, 0])
    )
    geometry["short_source_components"][0]["decision"] = "DEFER_TEXT_OWNERSHIP"
    _, audit, _ = run(item, geometry)
    assert (
        not audit["released_component_labels"]
        and not audit["added_complete_glyph_component_labels"]
    )
    event = next(e for e in audit["events"] if e["source_component_label"] == lab)
    assert event["checks"]["whole_source_component_matches_geometry_threshold"]
    assert not event["checks"]["no_source_layout_character_witness"]
