"""Complete source chains are geometry, not a raster-length heuristic.

All pixels below are public-safe synthetic inputs. Tests retain true gaps,
branches and glyph responsibility while checking complete curved objects.
"""

import math

import cv2
import numpy as np
import pytest

from app.native_objects.connections import (
    _dense_geometry,
    _simple_chain_fit_certificate,
    extract_connections,
)


ROI = (0, 0, 180, 180)


def curved_chain(angle=0):
    curve = np.array(
        [[-58, 12], [-40, -5], [-20, -18], [0, -23], [20, -18], [40, -5], [58, 12]],
        dtype=float,
    )
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    points = np.rint(curve @ rotation.T + [90, 90]).astype(np.int32)
    ink = np.zeros((180, 180), dtype=np.uint8)
    cv2.polylines(ink, [points], False, 1, 1)
    return ink


def extract(ink, out, *, text_regions=None, prior_objects=()):
    gray = np.where(ink, 0, 255).astype(np.uint8)
    original = gray.copy()
    result = extract_connections(gray, ROI, list(prior_objects), out, text_regions=text_regions)
    assert np.array_equal(gray, original)
    return result


@pytest.mark.parametrize("angle", [0, 23, 67, 121])
def test_complete_curves_survive_orientation_and_curvature_without_chord_ratio_gate(tmp_path, angle):
    ink = curved_chain(angle)
    result = extract(ink, tmp_path)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    ev = obj["source_evidence"]
    assert ev["raster_path_length_to_chord_ratio_diagnostic_only"] > 1.06
    assert ev["whole_simple_source_chain"]["pass"]
    assert ev["whole_simple_source_chain_fit"]["pass"]
    assert ev["whole_simple_source_chain"]["owned_source_pixels"] == int(ink.sum())
    assert len(obj["geometry"]["points"]) <= 48
    assert obj["kind"] == "CONNECTION_PATH"
    assert not obj["geometry"]["closed"]
    assert not ev["source_pixels_modified"]


def test_current_glyph_responsibility_still_blocks_a_complete_curved_chain(tmp_path):
    ink = curved_chain()
    runs = [[int(y), int(x), int(x + 1)] for y, x in zip(*np.nonzero(ink))]
    text = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [180, 180],
        "roi_xyxy_px": list(ROI),
        "regions": [{"id": "synthetic-glyph", "bbox_xyxy_px": [20, 50, 160, 120],
                     "compact_source_ink_mask": {"runs_y_x0_x1": runs}}],
    }
    result = extract(ink, tmp_path, text_regions=text)
    assert not result["objects"]
    assert any(row["reason"] == "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT" for row in result["uncertainties"])


def test_real_branch_is_neither_pruned_nor_hidden_by_whole_chain_certificate(tmp_path):
    ink = curved_chain()
    ink[61:68, 90] = 1
    result = extract(ink, tmp_path)
    assert not result["objects"]
    assert result["source_array_unchanged"]
    assert any("BRANCH" in row["reason"] or "PORT" in row["reason"] for row in result["uncertainties"])
    assert int(ink[61:68, 90].sum()) == 7


def test_white_gap_keeps_independent_complete_strokes_and_no_bridge(tmp_path):
    ink = curved_chain()
    ink[:, 87:94] = 0
    result = extract(ink, tmp_path)
    assert len(result["objects"]) == 2
    assert len({obj["source_evidence"]["source_connected_group_id"] for obj in result["objects"]}) == 2
    for obj in result["objects"]:
        x = _dense_geometry(obj["geometry"])[:, 0]
        assert x.max() <= 86 or x.min() >= 94
        assert obj["source_evidence"]["whole_simple_source_chain_fit"]["pass"]


def test_two_way_fit_rejects_a_chord_that_drops_a_real_bend():
    raw = np.array([[0, 0], [2, 2], [4, 3], [6, 2], [8, 0]], dtype=float)
    chord = {"points": [[0, 0], [8, 0]], "bulges": [0, 0], "closed": False}
    result = _simple_chain_fit_certificate(raw, chord)
    assert not result["pass"]
    assert result["source_to_native_maximum_distance_px"] == 3
    assert not result["checks"]["native_to_source_within_existing_fit_tolerance"]


def test_fitting_cannot_hide_source_traversal_by_reordering_vertices():
    raw = np.array([[0, 0], [2, 2], [4, 3], [6, 2], [8, 0]], dtype=float)
    reordered = {"points": raw[[0, 3, 1, 2, 4]].tolist(), "bulges": [0] * 5, "closed": False}
    result = _simple_chain_fit_certificate(raw, reordered)
    assert not result["pass"]
    assert not result["checks"]["source_traversal_order_preserved"]


def test_existing_line_overlap_remains_explicit_and_is_not_silently_retired(tmp_path):
    ink = curved_chain()
    prior = {"id": "synthetic-old-line", "kind": "LINE", "layer": "GEOMETRY",
             "geometry": {"start": [32, 102], "end": [50, 85]}}
    result = extract(ink, tmp_path, prior_objects=[prior])
    assert len(result["objects"]) == 1
    proposals = result["objects"][0]["source_evidence"]["retirement_proposals"]
    assert proposals and proposals[0]["prior_object_id"] == prior["id"]
    assert proposals[0]["proposal_only_requires_independent_remainder_and_ownership_audit"]
    assert prior["geometry"] == {"start": [32, 102], "end": [50, 85]}


def mixed_boundary_curve(*, reflect=False, branch=False, gap=False):
    ink = np.zeros((180, 180), dtype=np.uint8)
    cv2.circle(ink, (145, 80), 12, 1, 1)
    points = np.array([[25, 110], [45, 90], [70, 78], [100, 74], [133, 80]], np.int32)
    cv2.polylines(ink, [points], False, 1, 1)
    if branch:
        ink[65:75, 100] = 1
    if gap:
        ink[:, 125:130] = 0
    return ink[:, ::-1].copy() if reflect else ink


@pytest.mark.parametrize("reflect", [False, True])
def test_circle_contact_and_natural_end_form_a_complete_geometry_without_semantic_role_match(tmp_path, reflect):
    result = extract(mixed_boundary_curve(reflect=reflect), tmp_path)
    assert len(result["objects"]) == 1
    obj = result["objects"][0]
    evidence = obj["source_evidence"]
    assert evidence["whole_path_class"] == "OBSERVED_ROUND_BOUNDARY_TO_NATURAL_ENDPOINT"
    assert evidence["complete_mixed_observed_endpoint_chain"]["pass"]
    assert evidence["mixed_observed_endpoint_chain_fit"]["pass"]
    assert not evidence["complete_mixed_observed_endpoint_chain"]["round_boundary_geometry_owned"]
    assert not evidence["observed_round_boundary_ownership_checks"]["conflicts"]
    assert all(check["pass"] for check in evidence["original_source_endpoint_cap_checks"])
    native = _dense_geometry(obj["geometry"])
    assert native[:, 0].min() >= 24 if not reflect else native[:, 0].max() <= 155
    assert native[:, 0].max() <= 134 if not reflect else native[:, 0].min() >= 45


def test_mixed_endpoint_rule_does_not_hide_a_real_internal_branch(tmp_path):
    result = extract(mixed_boundary_curve(branch=True), tmp_path)
    assert not result["objects"]
    assert any("BRANCH" in row["reason"] for row in result["uncertainties"])


def test_mixed_endpoint_rule_does_not_bridge_a_real_gap_to_the_circle(tmp_path):
    result = extract(mixed_boundary_curve(gap=True), tmp_path)
    for obj in result["objects"]:
        native = _dense_geometry(obj["geometry"])
        assert native[:, 0].max() <= 124 or native[:, 0].min() >= 130
        assert not obj["source_evidence"]["source_morphological_gap_closing"]


def test_mixed_endpoint_rule_cannot_override_current_glyph_ownership(tmp_path):
    ink = mixed_boundary_curve()
    text = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [180, 180],
        "roi_xyxy_px": list(ROI),
        "regions": [{"id": "synthetic-unresolved-glyph", "accepted": False,
                     "bbox_xyxy_px": [20, 60, 125, 120],
                     "compact_source_ink_mask": {"runs_y_x0_x1": [
                         [int(y), int(x), int(x + 1)] for y, x in zip(*np.nonzero(ink)) if x < 125
                     ]}}],
    }
    result = extract(ink, tmp_path, text_regions=text)
    assert not result["objects"]
    assert any(row["reason"] == "CURRENT_SOURCE_GLYPH_OWNERSHIP_CONTACT" for row in result["uncertainties"])
