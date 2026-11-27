"""Real circle algebra, independent radial observations and saved identity."""
from copy import deepcopy
from fractions import Fraction as F
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.native_objects.circular_markers import discover_circular_markers
from app.native_objects.finite_circle_source import (
    _cell_distance_bounds, circle_cell_intersects, circle_geometry,
    circle_point_strictly_outside, circle_source_geometry_row,
    certify_finite_circle_source,
)
from app.native_objects.finite_component_saved_reader import APPID, saved_source_geometries


def _source_circle():
    source = np.full((180, 180), 255, np.uint8)
    cv2.circle(source, (80, 80), 20, 0, 3)
    cv2.line(source, (75, 72), (75, 88), 0, 2)
    cv2.line(source, (75, 72), (85, 72), 0, 2)
    observed = discover_circular_markers(source, [0, 0, 180, 180],
        observed_rounds=[{"center": [80, 80], "inner_boundary_radius_px": 18.}])
    obj = next(r for r in observed["rows"] if r["geometry_accepted"])
    obj["kind"] = "CIRCLE"
    return source, obj


def test_circle_exact_queries_distinguish_arc_from_chord_and_strict_boundary():
    row = {"kind": "CIRCLE", "circle_center_exact": [[0, 1], [0, 1]], "circle_radius_exact": [5, 1]}
    assert circle_cell_intersects(row, (3, 4), 0)
    assert not circle_cell_intersects(row, (0, 0), 1)
    assert not circle_point_strictly_outside(row, (0, 6), 1)
    assert circle_point_strictly_outside(row, (0, F(6) + F(1, 10 ** 40)), 1)
    assert not circle_point_strictly_outside(row, (0, F(6) - F(1, 10 ** 40)), 1)
    with pytest.raises(ValueError, match="NEGATIVE"):
        circle_cell_intersects(row, (3, 4), -1)
    lo, hi = _cell_distance_bounds(row, (8, 2), maximum=False)
    assert lo <= hi and hi - lo < F(1, 10 ** 30)


def test_finite_circle_positive_retains_legacy_and_new_exact_claims_separately():
    source, obj = _source_circle()
    row = circle_source_geometry_row(obj)
    result = certify_finite_circle_source(source, row, obj, [48, 62, 66, 99], roi=[0, 0, 180, 180], dpi=25.4)
    assert result["pass"], result["failures"]
    assert result["source_identity_binding"]["legacy_sampled_contract_replay"]["pass"]
    assert result["exact_finite_arc_centerline_support_pass"]
    assert result["width"]["independent_section_count"] >= 2
    assert not result["whole_circle_exact_source_approval"]
    assert not result["circle_replaced_by_chords"]
    assert result["independent_union_model_required"]
    assert any(section["constraint_eligible"] for section in result["width"]["sections"])


@pytest.mark.parametrize("change", ["center", "radius", "source_gap", "port"])
def test_finite_circle_changed_geometry_gap_or_contact_cannot_reuse_pass(change):
    source, obj = _source_circle()
    row = circle_source_geometry_row(obj)
    if change == "center":
        row["circle_center_exact"][0]["numerator"] = str(int(row["circle_center_exact"][0]["numerator"]) + 1)
    elif change == "radius":
        row["circle_radius_exact"]["numerator"] = str(int(row["circle_radius_exact"]["numerator"]) + 1)
    elif change == "source_gap":
        source[80, 56:65] = 255
    else:
        obj = deepcopy(obj)
        obj["source_evidence"]["contact_ports"] = [{"forged": True}]
    result = certify_finite_circle_source(source, row, obj, [48, 62, 66, 99], roi=[0, 0, 180, 180], dpi=25.4)
    assert not result["pass"] and result["failures"]


def test_saved_circle_reader_preserves_curve_and_transform_exactly(tmp_path):
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    block = doc.blocks.new("circle-block")
    block.add_circle((0., 0.), 2.5)
    insert = doc.modelspace().add_blockref("circle-block", (10., 20.), dxfattribs={"rotation": 17.})
    insert.set_xdata(APPID, [(1000, json.dumps({"id": "old-circle", "PASS": True}))])
    path = tmp_path / "circle.dxf"
    doc.saveas(path)
    reader = saved_source_geometries(path, [0, 0, 180, 180], 25.4, source_model="v2")
    (row,) = reader["geometries"]
    assert circle_geometry(row) == ((F(10), F(160)), F(5, 2))
    assert row["actual_insert_transform_chain"][0]["rotation_degrees_exact"] == [17, 1]
    assert row["curve_geometry_supported"] and not row["geometry_supported"]
    assert not row["curve_replaced_by_chords"]


def test_actual_saved_circle_is_remeasured_and_source_coordinate_forgery_fails(tmp_path):
    source, obj = _source_circle()
    center, radius = obj["geometry"]["center"], obj["geometry"]["radius_px"]
    scale = 25.4 / 200
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.appids.new(APPID)
    entity = doc.modelspace().add_circle(((center[0]) * scale, (180 - center[1]) * scale), radius * scale)
    entity.set_xdata(APPID, [(1000, json.dumps({"id": obj["id"]}))])
    path = tmp_path / "actual-bound-circle.dxf"
    doc.saveas(path)
    row = saved_source_geometries(path, [0, 0, 180, 180], 200, source_model="v2")["geometries"][0]
    result = certify_finite_circle_source(source, row, obj, [48, 62, 66, 99], roi=[0, 0, 180, 180], dpi=200)
    assert result["pass"], result["failures"]
    forged = deepcopy(row)
    forged["circle_center_exact"][0][0] += 1
    result = certify_finite_circle_source(source, forged, obj, [48, 62, 66, 99], roi=[0, 0, 180, 180], dpi=200)
    assert not result["pass"]
    assert "ACTUAL_CIRCLE_SOURCE_COORDINATES_DO_NOT_MATCH_MM_TRANSFORM" in result["failures"]
