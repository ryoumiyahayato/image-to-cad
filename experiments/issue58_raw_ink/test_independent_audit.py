"""Failure-oriented checks for the independent raw candidate diagnostics."""
import hashlib

import numpy as np

from experiments.issue58_raw_ink.independent_audit import audit_candidate, audit_plan


def _candidate(points, identity="example"):
    return {"candidate_id": identity, "source_path_px": points,
            "path_points_all_original_ink": True,
            "representation": {"points": points, "closed": False,
                               "bulges": [0.0] * len(points)}}


def test_black_diagonal_centers_do_not_prove_closed_pixel_support():
    gray = np.full((12, 12), 255, np.uint8)
    points = [[x, x] for x in range(3, 8)]
    for x, y in points:
        gray[y, x] = 0
    result = audit_candidate(gray, _candidate(points), [0, 0, 12, 12], 1)
    assert result["checks"]["all_source_points_are_original_black_pixels"]
    assert result["checks"]["all_steps_use_distinct_8_neighbor_pixels"]
    assert not result["checks"]["closed_native_segment_cells_all_original_ink"]
    assert [3, 4] in [list(p) for p in result["white_closed_cells_px"]]


def test_claimed_support_does_not_override_a_real_white_gap():
    gray = np.full((12, 20), 255, np.uint8)
    gray[5:8, 2:8] = 0
    gray[5:8, 11:18] = 0
    points = [[x, 6] for x in range(2, 18)]
    result = audit_candidate(gray, _candidate(points), [0, 0, 20, 12], 3)
    assert not result["checks"]["all_source_points_are_original_black_pixels"]
    assert not result["checks"]["closed_native_segment_cells_all_original_ink"]
    assert not result["independent_object_ownership_proved"]


def test_roi_cut_line_is_not_a_free_cap():
    gray = np.full((14, 20), 255, np.uint8)
    gray[5:8, :] = 0
    candidate = _candidate([[x, 6] for x in range(20)])
    result = audit_candidate(gray, candidate, [0, 0, 20, 14], 3)
    assert result["checks"]["closed_native_segment_cells_all_original_ink"]
    assert not result["checks"]["endpoints_not_on_crop_boundary"]


def test_geometry_changing_the_finite_endpoint_is_detected():
    gray = np.zeros((14, 20), np.uint8)
    candidate = _candidate([[x, 6] for x in range(3, 10)])
    candidate["representation"]["points"] = [[3, 6], [15, 6]]
    result = audit_candidate(gray, candidate, [0, 0, 20, 14], 3)
    assert not result["checks"]["declared_geometry_matches_actual_candidate_trace"]


def test_competing_paths_are_not_simultaneously_approved():
    gray = np.zeros((20, 20), np.uint8)
    first = _candidate([[x, 6] for x in range(3, 10)], "first")
    second = _candidate([[x, 6] for x in range(5, 13)], "second")
    plan = {"roi_xyxy_px": [0, 0, 20, 20], "estimated_ink_width_px": 3,
            "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
            "original_crop_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
            "candidates": [first, second]}
    result = audit_plan(gray, plan)
    assert result["competing_candidates_with_duplicate_geometric_segments"][0][
        "same_geometric_pixel_segments"] == 4
    assert result["no_production_adoption_certificate_was_issued"]
    plan["source_array_sha256"] = "0" * 64
    assert not audit_plan(gray, plan)["all_candidates_rechecked_from_original_pixels"]


def test_outside_or_noninteger_source_path_is_not_indexed_as_valid_ink():
    gray = np.zeros((10, 10), np.uint8)
    outside = audit_candidate(gray, _candidate([[2, 2], [-1, 2]]), [0, 0, 10, 10], 2)
    assert outside["status"] == "SOURCE_OUTSIDE_IMAGE"
    subpixel = audit_candidate(gray, _candidate([[2, 2], [2.5, 3]]), [0, 0, 10, 10], 2)
    assert subpixel["status"] == "INVALID_CANDIDATE_DATA"


def test_resource_withheld_output_is_not_reported_as_zero_error_validation():
    gray = np.zeros((20, 20), np.uint8)
    plan = {"roi_xyxy_px": [0, 0, 20, 20], "estimated_ink_width_px": 3,
            "source_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
            "original_crop_array_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
            "status": "RESOURCE_LIMIT_CANDIDATES_WITHHELD",
            "resources": {"seed_axis_overflow": True}, "candidates": []}
    result = audit_plan(gray, plan)
    assert not result["all_candidates_rechecked_from_original_pixels"]
    assert not result["declared_discovery_budget_completed"]
    assert result["candidate_audit_status"] == "NOT_EVALUATED_RESOURCE_LIMIT"
