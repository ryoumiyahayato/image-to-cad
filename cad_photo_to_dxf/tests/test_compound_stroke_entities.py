from __future__ import annotations

import copy
from hashlib import sha256
import json

import cv2
import ezdxf
import numpy as np
import pytest
from shapely.geometry import LineString, box

from app.export.compound_stroke_entities import (
    APPID, BACKUP_LAYER, CLASSIFICATION, RESIDUAL_LAYER, VISIBLE_LAYER,
    LONG_CONTRACT, LONG_CONTRACT_SHA256, LONG_CONTRACT_VERSION,
    SHORT_CONTRACT_SHA256, SHORT_CONTRACT_VERSION,
    add_compound_stroke_entities,
    validate_compound_stroke_record, _cells, _continuous_region_relation,
    _native_pen_mask, _native_raster_relation, _topology,
)
from app.geometry.raster_trace import trace_binary


def runs(mask):
    result = []
    for y, row in enumerate(mask):
        d = np.diff(np.r_[False, row, False].astype(np.int8))
        result.extend((y, int(a), int(b)) for a, b in
                      zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
    return tuple(result)


def native_runs(mask):
    return runs(np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1))


def compound_record():
    """A known 1 px cross, with four 78 px paths and retained source collars."""
    source = np.zeros((181, 181), np.uint8)
    cv2.line(source, (10, 90), (170, 90), 1, 1)
    cv2.line(source, (90, 10), (90, 170), 1, 1)
    source = source.astype(bool)
    residual = source.copy()
    parts = []
    for identifier, points in enumerate((
            ((90., 10.), (90., 88.)), ((10., 90.), (88., 90.)),
            ((92., 90.), (170., 90.)), ((90., 92.), (90., 170.))), 1):
        support = np.zeros_like(source, dtype=np.uint8)
        cv2.line(support, tuple(map(int, points[0])), tuple(map(int, points[1])), 1, 1)
        support = support.astype(bool)
        yy, xx = np.nonzero(support)
        coords = np.column_stack((xx, yy)).astype(float)
        distance = np.minimum(np.linalg.norm(coords-points[0], axis=1),
                              np.linalg.norm(coords-points[1], axis=1))
        retired = support.copy()
        retired[yy[distance <= 2.], xx[distance <= 2.]] = False
        collar = support & ~retired
        residual[retired] = False
        parts.append({"part_id": identifier, "points_px": points,
            "lineweight_hundredth_mm": 25, "width_px": 1.,
            "maximum_measured_pen_edge_shift_px": abs(25*100/2540.-1.)/2.,
            "source_to_pen_error_px": 0., "pen_to_source_error_px": 0.,
            "creates_connection": False, "full_object_movable": False,
            "electrical_semantics": "NOT_INFERRED",
            "native_supporting_source_runs_y_x0_x1": native_runs(support),
            "native_retired_source_runs_y_x0_x1": native_runs(retired),
            "native_retained_interface_runs_y_x0_x1": native_runs(collar)})
    return {"version": LONG_CONTRACT_VERSION, "contract_sha256": LONG_CONTRACT_SHA256,
        "classification": CLASSIFICATION, "native_source_compound_strokes": True,
        "creates_connection": False, "full_object_movable": False,
        "electrical_semantics": "NOT_INFERRED", "dpi": 100., "native_scale": 2,
        "origin_work_px": (0., 0.), "parts": parts,
        "native_source_runs_y_x0_x1": native_runs(source),
        "native_residual_runs_y_x0_x1": native_runs(residual),
        "native_foreign_runs_y_x0_x1": (),
        "original_boundary_paths_px": tuple(path.points for path in
            trace_binary(np.where(source, 0, 255).astype(np.uint8)))}


def document():
    doc = ezdxf.new("R2007")
    doc.units = ezdxf.units.MM
    doc.header["$LWDISPLAY"] = 1
    doc.header["$FILLMODE"] = 1
    doc.modelspace().add_text("keep 01", dxfattribs={"height": 2.})
    return doc


def transform(x, y):
    return x*.254, (181-y)*.254


def test_long_export_contract_is_explicitly_frozen():
    canonical = json.dumps(LONG_CONTRACT, sort_keys=True, separators=(",", ":")).encode()
    assert sha256(canonical).hexdigest() == LONG_CONTRACT_SHA256
    assert LONG_CONTRACT["version"] == LONG_CONTRACT_VERSION


@pytest.mark.parametrize("damage", [
    "missing_version", "missing_hash", "unknown_version", "unknown_version_valid_short_hash",
    "old_prototype_version", "nonstr_version", "wrong_long_hash", "wrong_short_hash",
    "mixed_short_and_long_contract", "unknown_proposal", "unknown_proposal_id",
    "proposal_hash_only", "proposal_version_only", "null_proposal", "proposal_alias",
])
def test_long_geometry_cannot_bypass_unknown_or_incomplete_contract(damage):
    record = compound_record()
    # All four members are 19.812 mm. The previous unknown-version fallback
    # silently accepted these records through the >= 10 mm long branch.
    assert all(np.linalg.norm(np.subtract(p["points_px"][1], p["points_px"][0]))*.254 > 10.
               for p in record["parts"])
    if damage == "missing_version":
        record.pop("version")
    elif damage == "missing_hash":
        record.pop("contract_sha256")
    elif damage == "unknown_version":
        record.update(version="short-straight-compound-parts-v999", contract_sha256="bad")
    elif damage == "unknown_version_valid_short_hash":
        record.update(version=SHORT_CONTRACT_VERSION+"-typo", contract_sha256=SHORT_CONTRACT_SHA256)
    elif damage == "old_prototype_version":
        record["version"] = "compound-exclusive-part-research-v2-collar"
    elif damage == "nonstr_version":
        record["version"] = [LONG_CONTRACT_VERSION]
    elif damage == "wrong_long_hash":
        record["contract_sha256"] = "0"*64
    elif damage == "wrong_short_hash":
        record.update(version=SHORT_CONTRACT_VERSION, contract_sha256="0"*64)
    elif damage == "mixed_short_and_long_contract":
        record["contract_sha256"] = SHORT_CONTRACT_SHA256
    elif damage == "unknown_proposal":
        record.update(proposal_version="unregistered-native-grid", proposal_contract_sha256="0"*64)
    elif damage == "unknown_proposal_id":
        record["proposal_id"] = "native-lattice-native-cell-margin-v1"
    elif damage == "proposal_hash_only":
        record["proposal_contract_sha256"] = "0"*64
    elif damage == "proposal_version_only":
        record["proposal_version"] = "unregistered-native-grid"
    elif damage == "null_proposal":
        record.update(proposal_version=None, proposal_contract_sha256=None)
    elif damage == "proposal_alias":
        record["proposal"] = {"version": "unregistered-native-grid"}
    with pytest.raises(ValueError, match="Unregistered compound"):
        validate_compound_stroke_record(record, center_transform=transform)
    doc = document()
    before = (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace()))
    with pytest.raises(ValueError, match="Unregistered compound"):
        add_compound_stroke_entities(doc, doc.modelspace(), record, center_transform=transform)
    assert (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace())) == before
    assert doc.modelspace().query("TEXT")[0].dxf.text == "keep 01"


def test_actual_native_parts_residual_backup_and_roundtrip(tmp_path):
    doc = document()
    native, residual, bounds = add_compound_stroke_entities(
        doc, doc.modelspace(), compound_record(), center_transform=transform)
    assert len(native) == 4 and all(e.dxftype() == "LINE" for e in native)
    assert len(residual) == 5 and all(e.dxftype() == "HATCH" for e in residual)
    assert bounds and all(e.dxf.lineweight == 25 for e in native)
    backup = doc.layers.get(BACKUP_LAYER)
    assert backup.is_off() and backup.is_frozen() and backup.is_locked()
    path = tmp_path/"compound.dxf"
    doc.saveas(path)
    loaded = ezdxf.readfile(path)
    assert not loaded.audit().errors
    assert loaded.modelspace().query("TEXT")[0].dxf.text == "keep 01"
    parts = loaded.modelspace().query(f'LINE[layer=="{VISIBLE_LAYER}"]')
    assert len(parts) == 4
    assert len(loaded.modelspace().query(f'HATCH[layer=="{RESIDUAL_LAYER}"]')) == 5
    assert [p.get_xdata(APPID)[2].value for p in parts] == [1, 2, 3, 4]
    assert all(p.get_xdata(APPID)[3].value == 100. for p in parts)
    assert all(p.dxf.lineweight == 25 for p in parts)
    loaded.saveas(tmp_path/"reopened.dxf")
    reopened = ezdxf.readfile(tmp_path/"reopened.dxf")
    assert [(tuple(e.dxf.start), tuple(e.dxf.end), e.dxf.lineweight) for e in
            reopened.modelspace().query(f'LINE[layer=="{VISIBLE_LAYER}"]')] == [
        (tuple(e.dxf.start), tuple(e.dxf.end), e.dxf.lineweight) for e in parts]


@pytest.mark.parametrize("damage", ["missing_retirement", "source_overlap", "unsupported_path",
                                    "stale_pen", "invalid_last_backup", "complete_object_claim"])
def test_invalid_record_fails_before_any_dxf_mutation(damage):
    record = copy.deepcopy(compound_record())
    if damage == "missing_retirement":
        record["parts"][0]["native_retired_source_runs_y_x0_x1"] = record["parts"][0]["native_retired_source_runs_y_x0_x1"][1:]
    elif damage == "source_overlap":
        record["native_foreign_runs_y_x0_x1"] = record["native_source_runs_y_x0_x1"][:1]
    elif damage == "unsupported_path":
        record["parts"][0]["points_px"] = ((92., 10.), (92., 88.))
    elif damage == "stale_pen":
        record["parts"][0]["lineweight_hundredth_mm"] = 35
    elif damage == "invalid_last_backup":
        record["original_boundary_paths_px"] += (((0., 0.), (float("nan"), 1.)),)
    elif damage == "complete_object_claim":
        record["full_object_movable"] = True
    doc = document()
    before = (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace()))
    with pytest.raises(ValueError):
        add_compound_stroke_entities(doc, doc.modelspace(), record, center_transform=transform)
    assert (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace())) == before
    assert doc.modelspace().query("TEXT")[0].dxf.text == "keep 01"


def test_unproved_scaled_or_nonlinear_coordinate_transform_is_rejected():
    for callback in (lambda x, y: (x*.5, -y*.254), lambda x, y: (x*x*.254, -y*.254)):
        doc = document()
        before = len(doc.entitydb)
        with pytest.raises(ValueError):
            add_compound_stroke_entities(doc, doc.modelspace(), compound_record(), center_transform=callback)
        assert len(doc.entitydb) == before


def test_hidden_fill_or_pen_cannot_silently_hide_a_valid_source_seam():
    for header in ("$FILLMODE", "$LWDISPLAY"):
        doc = document()
        doc.header[header] = 0
        before = len(doc.entitydb)
        with pytest.raises(ValueError):
            add_compound_stroke_entities(doc, doc.modelspace(), compound_record(), center_transform=transform)
        assert len(doc.entitydb) == before


def test_open_partial_polyline_remains_open_after_save(tmp_path):
    record = compound_record()
    record["parts"][0]["points_px"] = ((90., 10.), (90., 49.), (90., 88.))
    doc = document()
    native, _, _ = add_compound_stroke_entities(doc, doc.modelspace(), record, center_transform=transform)
    assert native[0].dxftype() == "LWPOLYLINE" and not native[0].closed
    destination = tmp_path/"open-part.dxf"
    doc.saveas(destination)
    loaded = ezdxf.readfile(destination)
    part = loaded.modelspace().query(f'LWPOLYLINE[layer=="{VISIBLE_LAYER}"]')[0]
    assert not part.closed and len(part) == 3 and part.dxf.lineweight == 25
    assert all(start == end == bulge == 0 for _, _, start, end, bulge in part.get_points())


def test_removed_source_collar_cannot_be_hidden_by_a_valid_partition():
    record = compound_record()
    # Keep a formally exact source partition while retiring every pen-support
    # cell; this reproduces the real subpixel gap at a standard paper pen cap.
    source = np.zeros((362, 362), bool)
    for y, a, b in record["native_source_runs_y_x0_x1"]:
        source[y, a:b] = True
    residual = source.copy()
    for part in record["parts"]:
        part["native_retired_source_runs_y_x0_x1"] = part["native_supporting_source_runs_y_x0_x1"]
        part["native_retained_interface_runs_y_x0_x1"] = ()
        for y, a, b in part["native_retired_source_runs_y_x0_x1"]:
            residual[y, a:b] = False
    record["native_residual_runs_y_x0_x1"] = runs(residual)
    doc = document()
    before = len(doc.entitydb)
    with pytest.raises(ValueError):
        add_compound_stroke_entities(doc, doc.modelspace(), record, center_transform=transform)
    assert len(doc.entitydb) == before


def test_native_white_hole_can_disappear_while_continuous_hole_count_stays_equal():
    """A real pixel-center gate must catch a subpixel surviving white sliver."""
    source = np.zeros((40, 50), bool)
    source[4:27, 4:47] = True
    source[15, 25] = False
    points = ((5., 14.5), (45., 14.5))
    radius = 25.*200./5080.  # A standard 0.25 mm paper pen at 200 DPI.
    source_cells = _cells(runs(source), 1)
    for cap in ("round", "flat", "square"):
        output = source | _native_pen_mask(points, radius, 1, source.shape, cap)
        continuous = source_cells.union(LineString(points).buffer(radius, cap_style=cap))
        assert _topology(source_cells) == _topology(continuous) == (1, 1)
        proof = _native_raster_relation(source, output)
        assert proof["source_holes"] == 1 and proof["output_holes"] == 0
        assert not proof["paper_overlap_bijection"] and not proof["passed"]


def test_native_equal_component_totals_do_not_hide_merge_and_new_island():
    source = np.zeros((16, 18), bool)
    source[2:5, 2:5] = True
    source[2:5, 10:13] = True
    output = source.copy()
    output[3, 4:11] = True
    output[9, 7] = True
    proof = _native_raster_relation(source, output)
    assert proof["source_ink_components"] == proof["output_ink_components"] == 2
    assert proof["source_holes"] == proof["output_holes"] == 0
    assert not proof["ink_overlap_bijection"] and not proof["passed"]


def test_continuous_old_hole_opening_is_not_cancelled_by_an_unrelated_new_hole():
    """Global Euler/component counts concealed the rejected real HABS case."""
    source = box(2, 2, 18, 18).difference(box(8, 8, 10, 10))
    output = source.difference(box(9, 0, 9.5, 8.5)).difference(box(13, 13, 14, 14))
    assert _topology(source) == _topology(output) == (1, 1)
    proof = _continuous_region_relation(source, output, box(0, 0, 20, 20))
    assert proof["source_paper_regions"] == proof["output_paper_regions"] == 2
    assert not proof["paper_overlap_bijection"] and not proof["passed"]


def test_white_forbidden_cell_is_checked_without_inventing_source_ink():
    record = compound_record()
    part = record["parts"][1]
    part["points_px"] = ((10.25, 90.), (87.75, 90.))
    part["lineweight_hundredth_mm"] = 35
    part["maximum_measured_pen_edge_shift_px"] = abs(35*100/2540.-1.)/2.
    # The wider standard pen remains valid here until an independent protected
    # white cell, rather than fabricated foreign black ink, forbids its edge.
    validate_compound_stroke_record(record, center_transform=transform)
    record["native_forbidden_runs_y_x0_x1"] = ((178, 130, 132), (179, 130, 132))
    doc = document()
    before = (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace()))
    with pytest.raises(ValueError, match="foreign contact"):
        add_compound_stroke_entities(doc, doc.modelspace(), record, center_transform=transform)
    assert (len(doc.entitydb), len(doc.layers), len(doc.appids), len(doc.modelspace())) == before
