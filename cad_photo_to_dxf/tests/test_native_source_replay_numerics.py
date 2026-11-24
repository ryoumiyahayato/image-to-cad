"""Only derived round-fit statistics admit bounded machine roundoff."""

from copy import deepcopy
import hashlib
import json
import math

import ezdxf
import numpy as np
import pytest

from app.native_objects.text_contact_adoption import complete_text_contact_paths
from app.native_objects.text_contact_audit import (
    SOURCE_REPLAY_NUMERICS,
    cold_text_contact_bindings,
    compare_contact_source_replay,
    verify_contact_plan_source_replay,
)
from app.native_objects.text_contact_geometry import (
    plan_text_contact_geometry,
    verify_text_contact_geometry_plan,
)
from tests.test_native_text_contact_adoption import _resave, _save
from tests.test_native_text_contact_geometry import ROI, SEED, _contact_source


def _plan():
    return {
        "schema": "source-text-contact-path-plan-v1",
        "original_source_pixels_modified": False,
        "original_source_crop_array_sha256": "a" * 64,
        "round_observations": [{
            "id": "ROUND-0000", "center": [40.0, 30.0],
            "inner_boundary_radius_px": 18.25,
            "radial_p95_px": 0.25, "radial_max_px": 0.5,
            "area_ratio": 0.99, "contour_index": 3, "contour_point_count": 100,
            "class": "OBSERVED_ROUND_INNER_BOUNDARY_SEMANTICS_UNKNOWN",
        }],
        "paths": [{
            "source_path_px": [[58.0, 30.0], [59.0, 30.0], [60.0, 30.0]],
            "source_graph_edge_ids": [3],
            "representation": {"points": [[58.0, 30.0], [60.0, 30.0]], "bulges": [0.0, 0.0], "closed": False},
            "line_runs": [[30, 58, 61]], "shared_contact_runs": [],
            "source_support": {"pass": True, "radial_max_px": 0.5},
            "endpoint_evidence": [
                {"kind": "OBSERVED_ROUND_BOUNDARY_CONTACT", "round_id": "ROUND-0000", "radial_contact_residual_px": 0.01},
                {"kind": "OBSERVED_FREE_SOURCE_ENDPOINT"},
            ],
        }],
    }


def _partition(plan):
    return {
        "schema": "complete-single-source-row-partition-v1",
        "components": [{"source_role": "FULL_HEIGHT_GLYPH", "source_support_runs_y_x0_x1": [[10, 10, 12]]}],
        "source_support_runs_y_x0_x1": [[10, 10, 12]],
        "text_contact_separation": {
            "geometry_plan": deepcopy(plan),
            "independent_round_observations": deepcopy(plan["round_observations"]),
        },
    }


def _last_bits(plan):
    # Saved JSON has no Python object alias between an adopted endpoint and
    # an unselected pending terminal. Perturb only the named allowed fields.
    result = json.loads(json.dumps(plan))
    for row in result["round_observations"]:
        for key in ("inner_boundary_radius_px", "radial_p95_px", "radial_max_px", "area_ratio"):
            row[key] = math.nextafter(row[key], math.inf)
    for path in result["paths"]:
        for endpoint in path["endpoint_evidence"]:
            if "radial_contact_residual_px" in endpoint:
                endpoint["radial_contact_residual_px"] = math.nextafter(endpoint["radial_contact_residual_px"], math.inf)
    return result


def _set(record, path, value):
    for key in path[:-1]:
        record = record[key]
    record[path[-1]] = value


@pytest.mark.parametrize("scope", ["plan", "partition"])
def test_one_ulp_derived_statistics_have_an_explicit_receipt_and_do_not_mutate(scope):
    old, new = _plan(), _last_bits(_plan())
    if scope == "partition":
        old, new = _partition(old), _partition(new)
    original_old, original_new = deepcopy(old), deepcopy(new)
    exact = compare_contact_source_replay(old, deepcopy(old), scope=scope)
    assert exact["pass"] and exact["bit_exact"] and exact["numeric_equivalent"]
    result = compare_contact_source_replay(old, new, scope=scope)
    assert result["pass"] and not result["bit_exact"] and result["numeric_equivalent"]
    assert len(result["differences"]) == (5 if scope == "plan" else 9)
    assert all(row["accepted"] and 0 < row["absolute_difference"] <= row["allowed_absolute_difference"] for row in result["differences"])
    assert all(row["bound"]["round_id"] == "ROUND-0000" for row in result["differences"])
    assert old == original_old and new == original_new
    assert not result["original_records_modified"]


def test_cancellation_uses_radius_error_propagation_not_residual_relative_tolerance():
    old, new = _plan(), _plan()
    radius = old["round_observations"][0]["inner_boundary_radius_px"]
    residual = old["paths"][0]["endpoint_evidence"][0]["radial_contact_residual_px"]
    new["paths"][0]["endpoint_evidence"][0]["radial_contact_residual_px"] += math.ulp(radius)
    result = compare_contact_source_replay(old, new, scope="plan")
    assert result["pass"]
    row = result["differences"][0]
    assert row["absolute_difference"] > 100 * math.ulp(residual)
    assert row["bound"]["radius_bound_px"] == SOURCE_REPLAY_NUMERICS["radius_ulps"] * math.ulp(radius)


@pytest.mark.parametrize("path,value", [
    (("round_observations", 0, "center", 0), math.nextafter(40.0, math.inf)),
    (("round_observations", 0, "contour_index"), 4),
    (("round_observations", 0, "contour_point_count"), 99),
    (("paths", 0, "source_path_px", 0, 0), math.nextafter(58.0, math.inf)),
    (("paths", 0, "representation", "points", 0, 0), math.nextafter(58.0, math.inf)),
    (("paths", 0, "representation", "bulges", 0), math.nextafter(0.0, math.inf)),
    (("paths", 0, "line_runs", 0, 1), 59),
    (("paths", 0, "source_graph_edge_ids", 0), 4),
    (("paths", 0, "source_support", "pass"), 1),
    (("paths", 0, "source_support", "radial_max_px"), math.nextafter(0.5, math.inf)),
    (("paths", 0, "endpoint_evidence", 0, "round_id"), "ROUND-0001"),
    (("original_source_pixels_modified",), True),
    (("original_source_crop_array_sha256",), "b" * 64),
])
def test_source_coordinates_pixels_assignment_flags_and_names_remain_exact(path, value):
    old, new = _plan(), _plan()
    _set(new, path, value)
    result = compare_contact_source_replay(old, new, scope="plan")
    assert not result["pass"] and not result["numeric_equivalent"]
    assert any(not row["accepted"] for row in result["differences"])


@pytest.mark.parametrize("key,increment", [
    ("inner_boundary_radius_px", 1e-9),
    ("radial_p95_px", 1e-9),
    ("radial_max_px", 1e-9),
    ("area_ratio", 1e-9),
])
def test_real_fit_statistic_changes_are_not_roundoff(key, increment):
    old, new = _plan(), _plan()
    new["round_observations"][0][key] += increment
    result = compare_contact_source_replay(old, new, scope="plan")
    assert not result["pass"]
    assert result["differences"][0]["absolute_difference"] > result["differences"][0]["allowed_absolute_difference"]


def test_fifth_radius_ulp_is_already_outside_the_fixed_four_ulp_bound():
    old, new = _plan(), _plan()
    key = "inner_boundary_radius_px"
    for _ in range(5):
        new["round_observations"][0][key] = math.nextafter(new["round_observations"][0][key], math.inf)
    assert not compare_contact_source_replay(old, new, scope="plan")["pass"]


def test_endpoint_residual_needs_the_same_bound_round_and_no_real_change():
    old, new = _plan(), _plan()
    new["paths"][0]["endpoint_evidence"][0]["radial_contact_residual_px"] += 1e-9
    assert not compare_contact_source_replay(old, new, scope="plan")["pass"]
    old["round_observations"] = []
    new = _last_bits(old)
    assert not compare_contact_source_replay(old, new, scope="plan")["pass"]


def test_unselected_pending_terminal_is_not_an_extra_roundoff_whitelist():
    old = _plan()
    old["pending"] = [{"forward": {"terminal": deepcopy(old["paths"][0]["endpoint_evidence"][0])}}]
    new = deepcopy(old)
    terminal = new["pending"][0]["forward"]["terminal"]
    terminal["radial_contact_residual_px"] = math.nextafter(terminal["radial_contact_residual_px"], math.inf)
    assert not compare_contact_source_replay(old, new, scope="plan")["pass"]


@pytest.mark.parametrize("damage", ["extra-field", "missing-field", "round-count", "nan", "infinite"])
def test_field_sets_counts_and_finite_numbers_are_strict(damage):
    old, new = _plan(), _plan()
    if damage == "extra-field":
        new["round_observations"][0]["unverified"] = 0.0
    elif damage == "missing-field":
        new["round_observations"][0].pop("radial_max_px")
    elif damage == "round-count":
        new["round_observations"].append(deepcopy(new["round_observations"][0]))
    else:
        new["round_observations"][0]["radial_max_px"] = float("nan" if damage == "nan" else "inf")
    assert not compare_contact_source_replay(old, new, scope="plan")["pass"]


@pytest.mark.parametrize("damage", ["pixel", "component-role", "unbound-round-copy"])
def test_partition_pixels_and_independent_round_binding_are_not_approximated(damage):
    old = _partition(_plan())
    new = deepcopy(old)
    if damage == "pixel":
        new["source_support_runs_y_x0_x1"][0][1] += 1
    elif damage == "component-role":
        new["components"][0]["source_role"] = "RETAINED_PUNCTUATION"
    else:
        row = new["text_contact_separation"]["independent_round_observations"][0]
        row["inner_boundary_radius_px"] = math.nextafter(row["inner_boundary_radius_px"], math.inf)
    assert not compare_contact_source_replay(old, new, scope="partition")["pass"]


def test_real_plan_replay_keeps_old_exact_failure_visible_but_accepts_only_statistics():
    gray = _contact_source()
    exact = plan_text_contact_geometry(gray, ROI, SEED)
    original = gray.copy()
    report = verify_contact_plan_source_replay(gray, ROI, exact)
    assert report["pass"] and report["source_replay_comparison"]["bit_exact"], report
    rounded = _last_bits(exact)
    assert not verify_text_contact_geometry_plan(gray, ROI, rounded)["pass"]
    report = verify_contact_plan_source_replay(gray, ROI, rounded)
    assert report["pass"] and not report["bit_exact_replay"]["pass"]
    assert not report["source_replay_comparison"]["bit_exact"]
    assert report["source_replay_comparison"]["numeric_equivalent"]
    assert np.array_equal(gray, original)
    altered = deepcopy(rounded)
    altered["paths"][0]["source_path_px"][0][0] += 1
    assert not verify_contact_plan_source_replay(gray, ROI, altered)["pass"]
    altered = deepcopy(rounded)
    altered["producer_sha256"] = "0" * 64
    assert not verify_contact_plan_source_replay(gray, ROI, altered)["pass"]
    altered_source = gray.copy()
    altered_source[0, 0] = 0
    assert not verify_contact_plan_source_replay(altered_source, ROI, rounded)["pass"]


def test_saved_contact_geometry_still_inspected_after_bounded_statistic_replay(tmp_path):
    gray = _contact_source()
    rounded = _last_bits(plan_text_contact_geometry(gray, ROI, SEED))
    result = complete_text_contact_paths(
        gray, ROI, hashlib.sha256(gray.tobytes()).hexdigest(), [], [rounded],
        tmp_path / "evidence/text_contact",
    )
    assert len(result["objects"]) == 1
    path, report = _save(tmp_path, gray, ROI, result)
    assert report["pass"], report
    replay = next(row for row in report["checks"] if row["type"] == "SAVED_TEXT_CONTACT_PATH_SOURCE")["original_source_plan_replay"]
    assert replay["source_replay_comparison"]["numeric_equivalent"]
    assert not replay["bit_exact_replay"]["pass"]
    doc = ezdxf.readfile(path)
    line = next(entity for entity in doc.modelspace() if entity.dxftype() == "LWPOLYLINE")
    vertices = list(line.get_points("xyseb"))
    vertices[1] = (vertices[1][0] + 0.1, *vertices[1][1:])
    line.set_points(vertices, format="xyseb")
    _resave(path, doc)
    assert not cold_text_contact_bindings(path, ezdxf.readfile(path), gray, ROI, 200, tmp_path / "evidence")["pass"]
