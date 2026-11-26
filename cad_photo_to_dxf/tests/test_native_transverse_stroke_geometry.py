"""Independent complete strokes sharing real four-port contact evidence."""

from copy import deepcopy
import hashlib

import cv2
import numpy as np
import pytest

from app.native_objects import structure_contact_geometry as structure
from app.native_objects import text_contact_geometry as contact
from app.native_objects import transverse_stroke_geometry as strokes
from app.native_objects.circular_markers import discover_circular_markers


ROI = [0, 0, 400, 280]


def _source(*, vertical=False):
    gray = np.full((280, 400), 255, np.uint8)
    cv2.circle(gray, (55, 90), 15, 0, 2)
    join_y = 70 if vertical else 90
    cv2.line(gray, (70, 90), (180, join_y), 0, 2)
    cv2.line(gray, (180, join_y), (260, 105), 0, 2)
    cv2.line(gray, (260, 105), (260, 225), 0, 2)
    cv2.putText(gray, "S", (242, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 2)
    cv2.line(gray, (180, 225), (370, 225), 0, 2)
    for x in (110, 130, 150):
        offset = 0 if vertical else 4
        cv2.line(gray, (x + offset, 50), (x - offset, 105), 0, 2)
    return gray


def _structure_stage(gray):
    circles = [
        {
            "id": row["id"],
            "kind": "CIRCLE",
            "layer": "CIRCULAR_MARKERS",
            "geometry": row["geometry"],
            "source_evidence": row["source_evidence"],
        }
        for row in discover_circular_markers(gray, ROI)["rows"]
        if row["geometry_accepted"]
    ]
    carrier = {
        "id": "finite-carrier",
        "kind": "LINE",
        "layer": "GEOMETRY",
        "geometry": {"start": [180, 225], "end": [370, 225]},
    }
    context = contact.build_text_contact_source_graph(gray, ROI)
    plan = structure.plan_structure_contact_geometry(
        gray, ROI, [carrier] + circles, source_graph=context
    )
    return context, [carrier, *circles], plan


def _prior(gray):
    context, initial, plan = _structure_stage(gray)
    targets = [row for row in plan["paths"] if row["path_role"] == "ROUND_TO_CARRIER"]
    assert len(targets) == 1
    target = targets[0]
    owner = {
        "id": "complete-shared-contact-owner",
        "kind": "CONNECTION_PATH",
        "layer": "CONNECTIONS",
        "geometry": deepcopy(target["representation"]),
        "source_evidence": {
            "source_path_points": deepcopy(target["source_path_px"]),
            "original_source_crop_xyxy_px": context.crop_bbox,
            "original_source_crop_array_sha256": context.source_crop_hash,
            "source_pixels_modified": False,
            "text_contact_path": {
                "schema": "source-text-contact-native-path-v1",
                "source_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                "plan_sha256": strokes._digest(plan),
                "path_index": 0,
                "path_sha256": strokes._digest(target),
                "path": deepcopy(target),
                "geometry_plan_schema": structure.SCHEMA,
            },
        },
    }
    return context, [*initial, owner]


def _plan(gray=None):
    gray = _source() if gray is None else gray
    context, prior = _prior(gray)
    return (
        gray,
        context,
        prior,
        strokes.plan_transverse_stroke_geometry(gray, ROI, prior, source_graph=context),
    )


def test_three_complete_crossing_strokes_become_independent_source_supported_lines():
    gray, context, prior, plan = _plan()
    frozen_gray, frozen_prior = gray.copy(), deepcopy(prior)
    assert len(plan["paths"]) == 3
    for row, x in zip(plan["paths"], (110, 130, 150)):
        assert row["path_role"] == "TRANSVERSE_STROKE"
        assert len(row["representation"]["points"]) == 2
        assert row["representation"]["bulges"] == [0.0, 0.0]
        assert (
            np.linalg.norm(np.asarray(row["representation"]["points"][0]) - [x + 4, 50])
            < 2.5
        )
        assert (
            np.linalg.norm(
                np.asarray(row["representation"]["points"][-1]) - [x - 4, 105]
            )
            < 2.5
        )
        assert all(
            e["kind"] == "OBSERVED_FREE_SOURCE_ENDPOINT"
            for e in row["endpoint_evidence"]
        )
        assert row["representation_evidence"]["closed_pixel_cells_all_original_ink"]
        assert row["reverse_source_path_agreement"]["pass"]
        assert row["required_crossing_path_id"] == prior[-1]["id"]
        assert not row["existing_objects_may_be_retired"]
        assert row["parallel_stroke_group_evidence"]["complete_companions"]
    assert strokes.verify_transverse_stroke_geometry_plan(
        gray, ROI, plan, source_graph=context
    )["pass"]
    assert np.array_equal(gray, frozen_gray)
    assert prior == frozen_prior


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "NO_COMPLETE_SHARED_CONTACT_ADOPTION_RECEIPT"),
        ("receipt", "COMPLETE_SHARED_CONTACT_ADOPTION_RECEIPT_INVALID"),
        ("raw_path", "COMPLETE_SHARED_CONTACT_ADOPTION_RECEIPT_INVALID"),
        ("crop", "CROSSING_OWNER_ORIGINAL_SOURCE_BINDING_CHANGED"),
        ("native", "CROSSING_OWNER_NATIVE_GEOMETRY_NO_LONGER_FOLLOWS_SOURCE"),
    ],
)
def test_legacy_or_changed_owner_cannot_license_new_shared_source_strokes(
    mutation, reason
):
    gray = _source()
    context, prior = _prior(gray)
    evidence = prior[-1]["source_evidence"]
    if mutation == "missing":
        del evidence["text_contact_path"]
    elif mutation == "receipt":
        evidence["text_contact_path"]["path_sha256"] = "0" * 64
    elif mutation == "raw_path":
        evidence["source_path_points"][10][0] += 1
    elif mutation == "crop":
        evidence["original_source_crop_array_sha256"] = "0" * 64
    else:
        prior[-1]["geometry"]["points"] = [[20, 230], [350, 230]]
        prior[-1]["geometry"]["bulges"] = [0.0, 0.0]
    plan = strokes.plan_transverse_stroke_geometry(
        gray, ROI, prior, source_graph=context
    )
    assert not plan["paths"]
    assert any(row["reason"] == reason for row in plan["owner_witness_refusals"])


def test_receipt_digest_alone_does_not_prove_the_original_shared_crossing_core():
    gray = _source()
    context, prior = _prior(gray)
    receipt = prior[-1]["source_evidence"]["text_contact_path"]
    for row in receipt["path"]["contact_continuations"]:
        if row.get("source_core_pixels"):
            row["source_core_pixels"][0][0] += 4
    receipt["path_sha256"] = strokes._digest(receipt["path"])
    plan = strokes.plan_transverse_stroke_geometry(
        gray, ROI, prior, source_graph=context
    )
    assert not plan["paths"]


def test_true_gap_cannot_be_crossed_to_join_two_short_fragments():
    gray = _source()
    gray[65:70, 106:115] = 255
    _, _, _, plan = _plan(gray)
    assert len(plan["paths"]) == 2
    assert all(row["representation"]["points"][0][0] > 120 for row in plan["paths"])


def test_forked_short_arm_remains_pending_with_all_competition_present():
    gray = _source()
    cv2.line(gray, (112, 60), (98, 46), 0, 2)
    _, _, _, plan = _plan(gray)
    assert len(plan["paths"]) == 2
    assert all(row["representation"]["points"][0][0] > 120 for row in plan["paths"])
    assert any("NONUNIQUE" in row["reason"] for row in plan["pending"])


def test_formal_text_stems_are_not_reclassified_by_parallel_repetition():
    gray = _source()
    context, prior = _prior(gray)
    prior.append(
        {
            "id": "existing-text",
            "kind": "TEXT",
            "layer": "TEXT",
            "geometry": {
                "text": "III",
                "x": 105,
                "y": 108,
                "height_px": 60,
                "width_px": 50,
            },
        }
    )
    plan = strokes.plan_transverse_stroke_geometry(
        gray, ROI, prior, source_graph=context
    )
    assert not plan["paths"]
    assert any(
        row["reason"] == "EXISTING_NATIVE_TEXT_HAS_SOURCE_RESPONSIBILITY"
        for row in plan["pending"]
    )


def test_untranscribed_contact_character_side_paths_are_retained_and_not_adopted():
    _, _, _, plan = _plan()
    assert len(plan["paths"]) == 3
    assert all(
        max(point[0] for point in row["source_path_px"]) < 180 for row in plan["paths"]
    )
    assert all(row["original_branches_retained"] for row in plan["paths"])
    assert all(row["text_content_decision"] == "NOT_PERFORMED" for row in plan["paths"])


def test_duplicate_native_owner_is_ambiguous_even_with_identical_valid_source_receipt():
    gray = _source()
    context, prior = _prior(gray)
    duplicate = deepcopy(prior[-1])
    duplicate["id"] = "second-native-owner"
    prior.append(duplicate)
    assert not strokes.plan_transverse_stroke_geometry(
        gray, ROI, prior, source_graph=context
    )["paths"]


def test_actual_native_positive_length_overlap_still_prevents_adoption(tmp_path):
    from app.native_objects.text_contact_adoption import complete_text_contact_paths

    # In this deliberately adverse raster the main path's preserved crossing
    # core contains a vertical run coincident with a proposed vertical LINE.
    # Sharing original source evidence must not waive the native duplicate gate.
    gray, _, prior, plan = _plan(_source(vertical=True))
    assert len(plan["paths"]) == 3
    adopted = complete_text_contact_paths(
        gray, ROI, hashlib.sha256(gray.tobytes()).hexdigest(), prior, [plan], tmp_path
    )
    blocked = [
        row
        for row in adopted["decisions"]
        if "SOURCE_GROUP_HAS_DUPLICATE_NATIVE_SEGMENTS" in row.get("reasons", [])
    ]
    assert blocked
    assert all(not row["adopted"] for row in blocked)


@pytest.mark.parametrize("field", ["paths", "producer_sha256", "prior_object_bindings"])
def test_cold_replay_rejects_changed_adopted_line_or_owner_binding(field):
    gray, context, _, plan = _plan()
    altered = deepcopy(plan)
    if field == "paths":
        altered["paths"][0]["representation"]["points"][-1][1] -= 8
    elif field == "producer_sha256":
        altered[field] = "0" * 64
    else:
        altered[field][-1]["id"] += "-altered"
    assert not strokes.verify_transverse_stroke_geometry_plan(
        gray, ROI, altered, source_graph=context
    )["pass"]
