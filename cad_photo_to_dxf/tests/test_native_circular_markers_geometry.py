"""Native circular-boundary source contracts, not real-drawing success claims."""

from copy import deepcopy
import hashlib

import cv2
import numpy as np
import pytest

from app.native_objects.circular_markers import (
    _closed_source_enclosure,
    discover_circular_markers,
    verify_circle_source_evidence,
)


def _drawing(*, center=(80, 80), glyph=True, contacts=True, size=(180, 180)):
    image = np.full(size, 255, np.uint8)
    cv2.circle(image, center, 20, 0, 3)
    cx, cy = center
    if glyph:
        # An original angular ink shape, never a supplied OCR answer.
        cv2.line(image, (cx - 5, cy - 8), (cx - 5, cy + 8), 0, 2)
        cv2.line(image, (cx - 5, cy - 8), (cx + 5, cy - 8), 0, 2)
        cv2.line(image, (cx - 5, cy), (cx + 2, cy), 0, 2)
    if contacts:
        cv2.line(image, (cx + 20, cy), (cx + 55, cy - 9), 0, 2)
        cv2.line(image, (cx, cy + 20), (cx - 6, cy + 55), 0, 2)
    return image


def _accepted(gray, *, roi=None, **kwargs):
    roi = roi or [0, 0, gray.shape[1], gray.shape[0]]
    report = discover_circular_markers(gray, roi, **kwargs)
    return [row for row in report["rows"] if row["geometry_accepted"]], report


def test_ring_character_and_external_ports_have_separate_original_support():
    gray = _drawing()
    original = gray.copy()
    (row,), report = _accepted(gray)
    evidence = row["source_evidence"]
    assert row["geometry"]["center"] == pytest.approx([80, 80], abs=0.3)
    assert row["geometry"]["radius_px"] == pytest.approx(20, abs=0.6)
    assert evidence["interior_is_complete_separate_components"]
    assert evidence["interior_source_pixels"] > 0
    assert evidence["closed_source_enclosure"]["pass"]
    assert len(evidence["contact_ports"]) == 2
    assert all(not port["external_connection_owned"] for port in evidence["contact_ports"])
    assert evidence["text_content"] is None
    assert report["summary"]["recognized_characters"] == 0
    assert report["summary"]["retired_old_objects"] == 0
    assert verify_circle_source_evidence(gray, [0, 0, 180, 180], row)["pass"]
    np.testing.assert_array_equal(gray, original)


@pytest.mark.parametrize("translation", [(0, 0), (37, 11), (11, 47)])
def test_geometry_is_translation_invariant_and_has_no_case_selector(translation):
    dx, dy = translation
    gray = _drawing(center=(80 + dx, 80 + dy), size=(240, 240))
    (row,), _ = _accepted(gray)
    assert row["geometry"]["center"] == pytest.approx([80 + dx, 80 + dy], abs=0.3)
    assert verify_circle_source_evidence(gray, [0, 0, 240, 240], row)["pass"]


@pytest.mark.parametrize("gap_width", [1, 2, 4])
def test_real_white_gap_is_not_closed_even_with_a_previous_round_observation(gap_width):
    gray = _drawing(contacts=False)
    (original,), _ = _accepted(gray)
    # A real white cut from the interior through every ring pixel, not merely
    # a white centreline sample next to the scanner's staircase edge.
    gray[80:80 + gap_width, 95:106] = 255
    accepted, _ = _accepted(gray, observed_rounds=[original["seed_observation"]])
    assert accepted == []
    assert not verify_circle_source_evidence(gray, [0, 0, 180, 180], original)["pass"]


def test_white_diagonal_route_is_open_not_hidden_by_four_connectivity():
    ring = np.zeros((41, 41), np.uint8)
    cv2.circle(ring, (20, 20), 12, 1, 3)
    # A diagonal white walk remains an actual open source route.
    for offset in range(7, 12):
        ring[20 + offset, 20 + offset] = 0
    closure = _closed_source_enclosure(ring.astype(bool), [20, 20], 12, 4)
    assert not closure["pass"]
    assert closure["white_connectivity"] == 8


def test_internal_closed_pocket_cannot_hide_another_interior_route_to_real_ring_gap():
    ring_and_branch = np.zeros((121, 121), np.uint8)
    cv2.circle(ring_and_branch, (60, 60), 30, 1, 3)
    # This source branch creates a large enclosed left pocket, while a real
    # gap on the opposite side leaves the right interior connected outside.
    cv2.line(ring_and_branch, (60, 30), (60, 90), 1, 3)
    ring_and_branch[59:62, 87:96] = 0
    closure = _closed_source_enclosure(ring_and_branch.astype(bool), [60, 60], 30, 4)
    assert closure["enclosed_white_pixels"] >= closure["minimum_enclosed_white_pixels"]
    assert closure["interior_white_components_connected_to_exterior"]
    assert not closure["pass"]


def test_open_door_arc_and_radial_leaf_are_not_a_closed_marker():
    gray = np.full((180, 180), 255, np.uint8)
    cv2.ellipse(gray, (80, 80), (20, 20), 0, 0, 90, 0, 3)
    cv2.line(gray, (80, 80), (100, 80), 0, 3)
    cv2.line(gray, (80, 80), (80, 100), 0, 3)
    accepted, _ = _accepted(gray, observed_rounds=[{
        "center": [80, 80], "inner_boundary_radius_px": 18,
    }])
    assert accepted == []


@pytest.mark.parametrize("text", ["O", "0", "ROOM 10"])
def test_ordinary_text_holes_are_not_independent_circular_markers(text):
    gray = np.full((120, 380), 255, np.uint8)
    cv2.putText(gray, text, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 3)
    accepted, _ = _accepted(gray)
    assert accepted == []


def test_isolated_empty_round_loop_requires_context_before_marker_adoption():
    gray = _drawing(glyph=False, contacts=False)
    accepted, report = _accepted(gray)
    assert accepted == []
    assert any("EMPTY_UNCONNECTED_LOOP_COULD_BE_ORDINARY_O_OR_ZERO" in row["reasons"] for row in report["rows"])


def test_source_proved_empty_attached_ring_does_not_invent_a_character():
    gray = _drawing(glyph=False)
    (row,), _ = _accepted(gray)
    assert row["glyph_bbox_xyxy_px"] is None
    assert row["source_evidence"]["interior_support_runs_y_x0_x1"] == []
    assert row["composition_status"] == "BOUNDARY_ONLY_CHARACTER_NOT_YET_RECOGNIZED"
    assert row["source_evidence"]["text_content"] is None


def test_protected_formal_glyph_blocks_its_round_outline_but_candidate_box_does_not_erase_context():
    gray = _drawing()
    protected = [{"region_id": "formal-source", "bbox_xyxy_px": [56, 56, 104, 104], "confirmed": True}]
    accepted, report = _accepted(gray, protected_text_boxes=protected)
    assert accepted == []
    assert any("RING_OVERLAPS_PROTECTED_FORMAL_GLYPH" in row["reasons"] for row in report["rows"])
    protected[0]["confirmed"] = False
    assert len(_accepted(gray, protected_text_boxes=protected)[0]) == 1


def test_protected_internal_character_is_not_mistaken_for_ring_ownership():
    gray = _drawing()
    protected = [{"region_id": "actual-interior-glyph", "bbox_xyxy_px": [73, 69, 87, 91], "confirmed": True}]
    assert len(_accepted(gray, protected_text_boxes=protected)[0]) == 1


@pytest.mark.parametrize("damage", ["radius", "center", "crop-hash", "missing-runs", "reassigned-runs", "contacts", "policy", "missing-evidence"])
def test_cold_source_checker_rejects_changed_saved_evidence(damage):
    gray = _drawing()
    (row,), _ = _accepted(gray)
    row = deepcopy(row)
    evidence = row["source_evidence"]
    if damage == "radius":
        row["geometry"]["radius_px"] += 1
    elif damage == "center":
        row["geometry"]["center"][0] += 1
    elif damage == "crop-hash":
        evidence["crop_sha256"] = "0" * 64
    elif damage == "missing-runs":
        evidence["ring_support_runs_y_x0_x1"] = []
    elif damage == "reassigned-runs":
        evidence["ring_support_runs_y_x0_x1"] = evidence["ring_support_runs_y_x0_x1"][1:]
    elif damage == "contacts":
        evidence["contact_ports"] = []
    elif damage == "policy":
        evidence["policy"]["maximum_centerline_source_distance_px"] = 100
    else:
        row.pop("source_evidence")
    assert not verify_circle_source_evidence(gray, [0, 0, 180, 180], row)["pass"]


def test_replacing_a_white_gap_and_rehashing_source_cannot_keep_closed_circle_approval():
    gray = _drawing(contacts=False)
    (row,), _ = _accepted(gray)
    gray[80, 95:106] = 255
    a, b, c, d = row["source_evidence"]["crop_bbox_xyxy_px"]
    row["source_evidence"]["crop_sha256"] = hashlib.sha256(gray[b:d, a:c].copy().tobytes()).hexdigest()
    result = verify_circle_source_evidence(gray, [0, 0, 180, 180], row)
    assert not result["pass"]


def test_roi_does_not_authorize_truncating_circle_or_switching_coordinate_frame():
    gray = _drawing()
    accepted, report = _accepted(gray, roi=[80, 0, 180, 180], observed_rounds=[{
        "center": [80, 80], "inner_boundary_radius_px": 18,
    }])
    assert accepted == []
    assert any("COMPLETE_CIRCLE_EXTENDS_OUTSIDE_REQUESTED_ROI" in row["reasons"] for row in report["rows"])
    with pytest.raises(ValueError, match="FULL_WORKING_RASTER"):
        discover_circular_markers(gray, [1400, 1000, 1580, 1180])


def test_two_original_markers_are_independent_and_repeated_observation_is_not_a_third_circle():
    gray = _drawing(center=(80, 80), size=(180, 380))
    second = _drawing(center=(260, 80), size=(180, 380))
    gray = np.minimum(gray, second)
    accepted, _ = _accepted(gray, observed_rounds=[{
        "center": [81.1, 80], "inner_boundary_radius_px": 17.7,
    }])
    assert len(accepted) == 2
    assert len({row["id"] for row in accepted}) == 2
    assert sorted(round(row["geometry"]["center"][0]) for row in accepted) == [80, 260]
    assert all(verify_circle_source_evidence(gray, [0, 0, 380, 180], row)["pass"] for row in accepted)
