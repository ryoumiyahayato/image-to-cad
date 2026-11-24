"""Whole original paths, bounded shared contacts, gaps and replay integrity."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.native_objects import text_contact_geometry as contact


ROI = [0, 0, 420, 240]
SEED = [155, 80, 225, 112]


def _contact_source():
    gray = np.full((240, 420), 255, np.uint8)
    cv2.circle(gray, (60, 170), 13, 0, 2)
    cv2.circle(gray, (360, 170), 13, 0, 2)
    xs = np.arange(72, 349)
    ys = 85 + 80 * ((xs - 210) / 138) ** 2
    cv2.polylines(
        gray, [np.rint(np.column_stack((xs, ys))).astype(np.int32)], False, 0, 2
    )
    cv2.putText(gray, "AX7", (160, 107), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2, cv2.LINE_8)
    return gray


def _round_to_round(plan):
    return [
        row
        for row in plan["paths"]
        if all(
            end.get("kind") == "OBSERVED_ROUND_BOUNDARY_CONTACT"
            for end in row["endpoint_evidence"]
        )
    ]


def test_shared_glyph_contact_is_one_complete_original_path_with_two_actual_terminals():
    gray = _contact_source()
    original = gray.copy()
    plan = contact.plan_text_contact_geometry(gray, ROI, SEED)
    rows = _round_to_round(plan)
    assert len(rows) == 1
    row = rows[0]
    assert row["contact_continuations"]
    assert row["source_support"]["pass"]
    assert row["representation"]["closed"] is False
    assert row["endpoint_source_points_px"][0][0] < SEED[0] - 50
    assert row["endpoint_source_points_px"][1][0] > SEED[2] + 50
    assert (
        row["endpoint_evidence"][0]["round_id"]
        != row["endpoint_evidence"][1]["round_id"]
    )
    points = np.asarray(row["source_path_px"], int)
    assert np.all(gray[points[:, 1], points[:, 0]] < 128)
    assert np.max(np.linalg.norm(np.diff(points, axis=0), axis=1)) <= np.sqrt(2) + 1e-9
    assert row["line_runs"] and row["shared_contact_runs"]
    assert any(
        item["unselected_branch_source_paths"] for item in row["contact_continuations"]
    )
    assert np.array_equal(gray, original)
    assert row["text_content_decision"] == "NOT_PERFORMED"
    assert plan["transcription_supplied"] is False


def test_bounded_plan_replays_from_original_source_and_rejects_changed_actual_geometry():
    gray = _contact_source()
    graph = contact.build_text_contact_source_graph(gray, ROI)
    plan = contact.plan_text_contact_geometry(gray, ROI, SEED, source_graph=graph)
    report = contact.verify_text_contact_geometry_plan(
        gray, ROI, plan, source_graph=graph
    )
    assert report["pass"]
    assert report["replayed_paths"] == plan["paths"]
    forged = deepcopy(plan)
    forged["paths"][0]["representation"]["points"][1][0] += 5
    checked = contact.verify_text_contact_geometry_plan(
        gray, ROI, forged, source_graph=graph
    )
    assert not checked["pass"]
    assert checked["checks"]["all_complete_paths_replayed"] is False


def test_shared_ink_mask_and_endpoint_evidence_are_replayed_not_trusted():
    gray = _contact_source()
    graph = contact.build_text_contact_source_graph(gray, ROI)
    plan = contact.plan_text_contact_geometry(gray, ROI, SEED, source_graph=graph)
    for field in (
        "line_runs",
        "shared_contact_runs",
        "endpoint_evidence",
        "source_path_px",
    ):
        forged = deepcopy(plan)
        forged["paths"][0][field] = []
        assert not contact.verify_text_contact_geometry_plan(
            gray, ROI, forged, source_graph=graph
        )["pass"]


def test_a_real_source_gap_is_not_bridged_to_make_a_round_to_round_path():
    gray = _contact_source()
    gray[65:150, 260:264] = 255
    plan = contact.plan_text_contact_geometry(gray, ROI, SEED)
    assert not _round_to_round(plan)
    for row in plan["paths"]:
        points = np.asarray(row["source_path_px"])
        assert not (points[:, 0].min() < 260 and points[:, 0].max() >= 264)
    assert np.all(gray[65:150, 260:264] == 255)


def test_crop_boundary_is_not_accepted_as_a_new_source_terminal():
    gray = _contact_source()
    clipped = [130, 40, 270, 160]
    plan = contact.plan_text_contact_geometry(gray, clipped, SEED)
    assert not _round_to_round(plan)
    assert any(
        item.get(direction, {}).get("reason") == "ROI_BOUNDARY_IS_NOT_A_SOURCE_ENDPOINT"
        for item in plan["pending"]
        for direction in ("forward", "reverse")
    )


def test_cached_source_graph_cannot_certify_changed_source_or_roi():
    gray = _contact_source()
    graph = contact.build_text_contact_source_graph(gray, ROI)
    changed = gray.copy()
    changed[85, 210] = 255
    with pytest.raises(ValueError, match="ORIGINAL_SOURCE_OR_ROI_CHANGED"):
        contact.plan_text_contact_geometry(changed, ROI, SEED, source_graph=graph)
    with pytest.raises(ValueError, match="ORIGINAL_SOURCE_OR_ROI_CHANGED"):
        contact.plan_text_contact_geometry(
            gray, [1, 0, 420, 240], SEED, source_graph=graph
        )


def test_original_O_zero_and_closed_round_boundaries_do_not_become_contact_paths():
    gray = np.full((160, 300), 255, np.uint8)
    cv2.putText(gray, "O0", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 2, cv2.LINE_8)
    cv2.circle(gray, (185, 82), 18, 0, 2)
    plan = contact.plan_text_contact_geometry(
        gray, [0, 0, 300, 160], [55, 63, 207, 105]
    )
    assert plan["paths"] == []


def test_symmetric_long_branches_remain_ambiguous_and_original_short_branch_is_retained():
    gray = np.full((180, 360), 255, np.uint8)
    cv2.line(gray, (30, 90), (175, 90), 0, 1)
    cv2.line(gray, (175, 90), (320, 48), 0, 1)
    cv2.line(gray, (175, 90), (320, 132), 0, 1)
    original = gray.copy()
    plan = contact.plan_text_contact_geometry(
        gray, [0, 0, 360, 180], [150, 75, 205, 107]
    )
    assert plan["paths"] == []
    assert np.array_equal(gray, original)


def test_plan_diagnostics_do_not_serialize_internal_graph_pixel_indices():
    plan = contact.plan_text_contact_geometry(_contact_source(), ROI, SEED)
    for row in plan["pending"]:
        for direction in ("forward", "reverse"):
            assert "pixels" not in row.get(direction, {})
            assert "source_path_px" not in row.get(direction, {})


def test_a_certificate_from_another_producer_is_not_relabelled_as_current():
    gray = _contact_source()
    plan = contact.plan_text_contact_geometry(gray, ROI, SEED)
    plan["producer_sha256"] = "0" * 64
    report = contact.verify_text_contact_geometry_plan(gray, ROI, plan)
    assert not report["pass"] and report["checks"]["producer"] is False


def test_multihole_core_uses_one_whole_path_and_covers_all_original_edges_without_filling_white():
    gray = np.full((240, 420), 255, np.uint8)
    cv2.circle(gray, (60, 100), 13, 0, 2)
    cv2.circle(gray, (360, 100), 13, 0, 2)
    cv2.line(gray, (74, 100), (346, 100), 0, 1)
    gray[99:102, 199:206] = 0
    gray[100, 200] = gray[100, 203] = 255
    original = gray.copy()
    plan = contact.plan_text_contact_geometry(gray, ROI, [175, 85, 230, 115])
    rows = _round_to_round(plan)
    assert len(rows) == 1
    row = rows[0]
    covers = [
        cover
        for cover in row["bounded_original_cycle_covers"]
        if cover.get("schema") == "bounded-two-port-original-multicycle-cover-v1"
    ]
    assert covers and row["representation_evidence"]["protected_source_path_intervals"]
    for cover in covers:
        points = cover["source_walk_points"]
        actual = {
            tuple(sorted((tuple(a), tuple(b)))) for a, b in zip(points, points[1:])
        }
        expected = {
            tuple(sorted((tuple(a), tuple(b)))) for a, b in cover["source_core_edges"]
        }
        assert actual == expected
        assert cover["all_core_source_edges_covered"]
        assert cover["all_core_source_pixels_covered"]
        assert all(gray[int(y), int(x)] < 128 for x, y in points)
    assert np.array_equal(gray, original)
    assert gray[100, 200] == gray[100, 203] == 255


def test_a_free_end_inside_the_word_is_not_enough_to_erase_a_character_or_short_branch():
    gray = np.full((190, 500), 255, np.uint8)
    cv2.putText(
        gray, "AB-12,3", (35, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.85, 0, 1, cv2.LINE_8
    )
    yy, xx = np.where(gray < 192)
    box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
    cv2.line(gray, (box[2] - 2, box[1] + 5), (box[2] + 60, box[1] - 20), 0, 1)
    original = gray.copy()
    plan = contact.plan_text_contact_geometry(gray, [0, 0, 500, 190], box)
    assert not plan["paths"]
    assert any(
        row.get("reason")
        == "FREE_SOURCE_ENDPOINT_INSIDE_TEXT_REQUIRES_INDEPENDENT_GRAPHIC_IDENTITY"
        for row in plan["pending"]
    )
    assert np.array_equal(gray, original)
