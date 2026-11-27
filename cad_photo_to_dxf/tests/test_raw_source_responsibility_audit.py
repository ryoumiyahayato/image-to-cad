"""Authored source/geometry counterexamples for the independent raw audit."""

from copy import deepcopy

import numpy as np
import pytest

from app.native_objects.raw_source_responsibility_audit import (
    POLICY,
    audit_raw_source_responsibility,
)


def _line(object_id, start, end):
    return {"object_id": object_id, "kind": "LINE", "points": [list(start), list(end)],
            "bulges": [0, 0], "closed": False, "handle": object_id}


def _capsules(geometries, *, shape=(120, 160), radius=2):
    ys, xs = np.indices(shape)
    points = np.column_stack((xs.ravel(), ys.ravel()))
    gray = np.full(shape, 255, np.uint8)
    mask = np.zeros(len(points), bool)
    for row in geometries:
        for a, b in zip(row["points"], row["points"][1:]):
            a, b = np.asarray(a, float), np.asarray(b, float)
            delta = b - a
            fractions = np.clip((points - a) @ delta / (delta @ delta), 0, 1)
            mask |= np.linalg.norm(points - a - fractions[:, None] * delta, axis=1) <= radius
    gray.ravel()[mask] = 0
    return gray


def _audit(gray, geometries, **kwargs):
    return audit_raw_source_responsibility(gray, geometries,
                                           roi_xyxy=[0, 0, gray.shape[1], gray.shape[0]], **kwargs)


def _end(report, object_id, end):
    return next(row for row in report["endpoints"] if row["object_id"] == object_id and row["end"] == end)


def test_normal_cap_short_boundary_competition_and_observable_extension_differ():
    geometry = _line("guest", (25, 50), (80, 50))
    normal = _capsules([geometry])
    short = normal.copy()
    short[50, 83:85] = 0
    extended = normal.copy()
    extended[50, 83:92] = 0
    reports = [_audit(source, [geometry]) for source in (normal, short, extended)]
    assert [_end(report, "guest", 1)["observation"] for report in reports] == [
        "CAP_OR_JUNCTION_COMPATIBLE", "SOURCE_BOUNDARY_COMPETITION",
        "OBSERVABLE_UNASSIGNED_CONTINUATION"]
    assert len({report["source_binding"]["evaluation_ink_sha256"] for report in reports}) == 3
    assert len({report["geometry_input_sha256"] for report in reports}) == 1
    assert all(not report["summary"]["may_adopt_objects_from_this_report_alone"] for report in reports)


def test_cap_assessment_is_invariant_to_source_origin_translation():
    geometry = _line("guest", (25, 50), (80, 50))
    gray = _capsules([geometry])
    local = _audit(gray, [geometry])
    shifted = deepcopy(geometry)
    shifted["points"] = [[x + 1000, y + 2000] for x, y in geometry["points"]]
    translated = audit_raw_source_responsibility(gray, [shifted],
        roi_xyxy=[1000, 2000, 1160, 2120], source_origin_xy=(1000, 2000))
    assert local["summary"] == translated["summary"]
    assert [_end(local, "guest", i)["maximum_forward_source_center_extent_px"] for i in (0, 1)] == [
        _end(translated, "guest", i)["maximum_forward_source_center_extent_px"] for i in (0, 1)]


def test_normal_finite_t_junction_is_compatible_without_reading_declarations():
    guest = _line("guest", (60, 20), (60, 60))
    host = _line("host", (20, 60), (110, 60))
    gray = _capsules([guest, host])
    report = _audit(gray, [guest, host], target_object_ids=["guest"])
    assert _end(report, "guest", 1)["observation"] == "CAP_OR_JUNCTION_COMPATIBLE"
    assert report["pair_contacts"][0]["point_px"] == [60, 60]
    assert report["pair_contacts"][0]["status"] == "ORIGINAL_INK_POINT_CONTACT"
    assert len(report["endpoints"]) == 2
    assert report["attachment_declaration_checks"] == []


def test_declared_host_or_fake_anchor_does_not_create_an_actual_contact():
    guest = _line("guest", (60, 20), (60, 57))
    host = _line("host", (20, 60), (110, 60))
    gray = _capsules([guest, host])
    report = _audit(gray, [guest, host], target_object_ids=["guest"],
        attachment_declarations=[{"guest": "guest", "end": 1, "host": "host", "anchor": [60, 60],
                                  "producer_pass": True}])
    assert report["pair_contacts"] == []
    declaration = report["attachment_declaration_checks"][0]
    assert declaration["used_as_truth"] is False
    assert declaration["status"] == "SOURCE_UNRESOLVED_DECLARED_CONTACT_NOT_EXACTLY_OBSERVED"


def test_true_white_gap_has_positive_length_and_is_hard_rejected():
    line = _line("line", (25, 50), (80, 50))
    gray = _capsules([line])
    gray[:, 51:54] = 255
    report = _audit(gray, [line])
    assert report["summary"]["status"] == "HARD_REJECT"
    assert report["geometry_support"][0]["uncovered_positive_length_px"] == pytest.approx(3)
    assert report["geometry_support"][0]["white_interior_cells"] == [[51, 50], [52, 50], [53, 50]]


def test_white_corner_is_not_a_positive_length_white_gap():
    line = _line("diagonal", (20, 20), (80, 80))
    gray = np.full((120, 160), 255, np.uint8)
    gray[np.arange(20, 81), np.arange(20, 81)] = 0
    report = _audit(gray, [line])
    support = report["geometry_support"][0]
    assert support["uncovered_positive_length_px"] == 0
    assert support["zero_length_white_cells"]
    assert support["closed_cell_all_black"] is False
    assert report["summary"]["status"] != "HARD_REJECT"


def test_white_boundary_aligned_interval_is_supported_by_adjacent_black_cell():
    line = _line("boundary", (20, 40.5), (80, 40.5))
    gray = np.full((120, 160), 255, np.uint8)
    gray[40, 20:81] = 0
    report = _audit(gray, [line])
    support = report["geometry_support"][0]
    assert support["white_boundary_cells"]
    assert support["uncovered_positive_length_px"] == 0
    assert support["closed_cell_all_black"] is False


def test_intersection_in_original_white_is_an_unsupported_point_contact():
    first = _line("first", (25, 50), (95, 50))
    second = _line("second", (60, 20), (60, 90))
    gray = _capsules([first, second])
    gray[49:52, 59:62] = 255
    report = _audit(gray, [first, second])
    assert report["pair_contacts"][0]["status"] == "HARD_REJECT_UNSUPPORTED_POINT_CONTACT"
    assert report["summary"]["status"] == "HARD_REJECT"


def test_reversed_partial_positive_duplicate_is_rejected():
    first = _line("first", (25, 50), (95, 50))
    second = _line("second", (75, 50), (40, 50))
    report = _audit(_capsules([first]), [first, second])
    assert len(report["positive_length_overlaps"]) == 1
    assert report["positive_length_overlaps"][0]["length_px"] == 35
    assert report["summary"]["status"] == "HARD_REJECT"


def test_exact_geometry_near_miss_is_not_snapped_to_contact():
    first = _line("first", (25, 50), (60, 50))
    second = _line("second", (60 + 1e-10, 20), (60 + 1e-10, 90))
    report = _audit(_capsules([first, second]), [first, second])
    assert report["pair_contacts"] == []
    assert report["positive_length_overlaps"] == []


def test_real_white_hole_is_reported_without_converting_black_core_to_hole():
    line = _line("line", (25, 50), (95, 50))
    gray = _capsules([line])
    gray[65:71, 80:86] = 0
    gray[67:69, 82:84] = 255
    report = _audit(gray, [line])
    assert len(report["white_holes"]) == 1
    assert report["white_holes"][0]["pixel_count"] == 4
    assert report["summary"]["status"] != "HARD_REJECT"


def test_disconnected_ink_after_real_white_gap_is_not_a_cap_extension():
    line = _line("line", (25, 50), (80, 50))
    gray = _capsules([line])
    gray[50, 85:91] = 0
    report = _audit(gray, [line])
    endpoint = _end(report, "line", 1)
    assert endpoint["observation"] == "CAP_OR_JUNCTION_COMPATIBLE"
    assert endpoint["disconnected_nearby_ink_pixels"]
    assert endpoint["unassigned_source_groups"] == []


def test_relevant_curve_is_unresolved_but_remote_curve_does_not_poison_target():
    line = _line("line", (25, 50), (80, 50))
    gray = _capsules([line])
    remote = {"object_id": "remote", "kind": "ARC", "bbox_xyxy": [130, 100, 150, 110],
              "coverage_valid": True}
    near = {"object_id": "near", "kind": "ARC", "bbox_xyxy": [80, 48, 85, 52],
            "coverage_valid": True}
    first = _audit(gray, [line, remote], target_object_ids=["line"])
    second = _audit(gray, [line, near], target_object_ids=["line"])
    assert first["summary"]["status"] == "COMPATIBLE_UNDER_LIMITED_RAW_MODEL"
    assert second["summary"]["status"] == "SOURCE_UNRESOLVED"
    assert _end(second, "line", 1)["relevant_unsupported_geometries"][0]["object_id"] == "near"


def test_untrusted_or_absent_context_bbox_cannot_prove_irrelevance():
    line = _line("line", (25, 50), (80, 50))
    gray = _capsules([line])
    for extra in ({"bbox_xyxy": [130, 100, 150, 110], "coverage_valid": False},
                  {"bbox_unavailable": True}):
        unknown = {"object_id": "unknown", "kind": "TEXT", **extra}
        report = _audit(gray, [line, unknown], target_object_ids=["line"])
        endpoint = _end(report, "line", 1)
        assert endpoint["status"] == "SOURCE_UNRESOLVED_LIMITED_CONTEXT"
        assert endpoint["observation"] == "CAP_OR_JUNCTION_COMPATIBLE"
        assert endpoint["relevant_unsupported_geometries"][0]["extent_status"] == "UNKNOWN_EXTENT_UNSUPPORTED_CONTEXT"


def test_nonzero_bulge_is_never_audited_as_its_straight_chord():
    curve = _line("curve", (25, 50), (80, 50))
    curve.update(kind="LWPOLYLINE", bulges=[0.5, 0])
    report = _audit(_capsules([curve]), [curve])
    assert report["geometry_support"][0]["status"] == "SOURCE_UNRESOLVED_UNSUPPORTED_GEOMETRY"
    assert report["endpoints"] == []


def test_clipped_or_too_short_width_evidence_cannot_be_cap_acceptance():
    short = _line("short", (25, 50), (28, 50))
    report = _audit(_capsules([short]), [short])
    assert report["summary"]["status"] == "SOURCE_UNRESOLVED"
    assert all(row["status"] == "SOURCE_UNRESOLVED_INSUFFICIENT_ISOLATED_WIDTH"
               for row in report["endpoints"])


def test_source_geometry_policy_and_inputs_are_not_mutated_and_order_is_stable():
    guest = _line("guest", (60, 20), (60, 60))
    host = _line("host", (20, 60), (110, 60))
    gray = _capsules([guest, host])
    old_gray, old_rows, old_policy = gray.copy(), deepcopy([guest, host]), deepcopy(POLICY)
    first = _audit(gray, [guest, host])
    second = _audit(gray, [host, guest])
    assert first == second
    assert np.array_equal(gray, old_gray)
    assert [guest, host] == old_rows
    assert POLICY == old_policy


def test_duplicate_object_ids_or_unknown_target_ids_are_not_silently_reduced():
    line = _line("line", (25, 50), (80, 50))
    gray = _capsules([line])
    with pytest.raises(ValueError, match="DUPLICATE_OBJECT_ID"):
        _audit(gray, [line, line])
    with pytest.raises(ValueError, match="UNKNOWN_TARGET_OBJECT_ID"):
        _audit(gray, [line], target_object_ids=["missing"])
