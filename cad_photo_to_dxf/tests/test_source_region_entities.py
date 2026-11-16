"""Public synthetic cells: exact holes, official frames, persistence and failure."""
from __future__ import annotations

import json
from types import MappingProxyType

import ezdxf
import numpy as np
import pytest

from app.core.scale_calibrator import RasterToCad, ScaleCalibration, raster_to_cad
from app.export.source_region_entities import (
    APPID, AUTHORITY, CLASSIFICATION, CONTRACT_SHA256, DICTIONARY_KEY, VERSION,
    emit_source_region_plan, preflight_source_region, preflight_source_region_document,
)
from app.geometry.source_region_selection import source_region_selection_digest


def runs(mask):
    result = []
    for y, row in enumerate(mask):
        delta = np.diff(np.r_[False, row, False].astype(np.int8))
        result.extend([y, int(a), int(b)] for a, b in
                      zip(np.flatnonzero(delta == 1), np.flatnonzero(delta == -1)))
    return result


def source_record():
    """A hollow parent, an island in its hole, an isolated cell, and one M."""
    parent = np.zeros((24, 28), bool)
    parent[2:12, 2:12] = True
    parent[4:10, 4:10] = False
    parent[6:8, 6:8] = True
    parent[20, 20] = True
    member = np.zeros_like(parent)
    member[14:17, 3:10] = True
    member[14, 8:10] = False
    parent |= member
    foreign = np.zeros_like(parent)
    foreign[18:20, 4:8] = True
    working = parent.reshape(12, 2, 14, 2).any(axis=(1, 3))
    manifest = {
        "version": "explicit-native-source-region-selection-v1",
        "input": {"pixels_sha256": "1" * 64, "shape_yx": [64, 64], "dtype": "uint8", "dpi": 100.},
        "original": {"pixels_sha256": "2" * 64, "shape_yx": [128, 128], "dtype": "uint8", "dpi": 200.},
        "crop_work_px": [0, 0, 64, 64], "native_scale": 2,
        "prepared_window": {"origin_work_px": [5, 6], "shape_yx": [12, 14],
                            "pixels_sha256": "3" * 64, "dtype": "uint8"},
        "selection": {"id": "public-holes-toy", "working_parent_runs_y_x0_x1": runs(working),
                      "native_member_runs_y_x0_x1": runs(member)},
    }
    identity = {
        "input_pixels_sha256": "1" * 64, "input_shape": [64, 64], "input_dtype": "uint8",
        "original_pixels_sha256": "2" * 64, "original_shape": [128, 128], "original_dtype": "uint8",
        "working_dpi": 100., "original_dpi": 200., "native_scale": 2,
        "source_crop": [0, 0, 64, 64], "trace_window_pixels_sha256": "4" * 64,
        "prepared_window_pixels_sha256": "3" * 64,
        "mapping": "full_native_edge=(trace_work_edge+crop_origin)*native_scale",
    }
    return {
        "version": VERSION, "contract_sha256": CONTRACT_SHA256,
        "native_source_region_partition": True, "kind": "explicit_native_source_region",
        "classification": CLASSIFICATION, "selection_authority": AUTHORITY,
        "automatic_selection": False, "complete_native_component": True,
        "full_object_movable": False, "creates_connection": False,
        "historical_identity": "NOT_PROVEN", "electrical_semantics": "NOT_INFERRED",
        "source_shape": [12, 14], "native_shape": [24, 28], "origin_work_px": [5, 6],
        "bbox": [6, 7, 10, 10],
        "native_scale": 2, "dpi": 100., "native_dpi": 200.,
        "source_runs_y_x0_x1": runs(working), "native_source_runs_y_x0_x1": runs(parent),
        "native_member_runs_y_x0_x1": runs(member), "native_residual_runs_y_x0_x1": runs(parent & ~member),
        "native_foreign_runs_y_x0_x1": runs(foreign), "source_pixels": int(working.sum()),
        "native_source_pixels": int(parent.sum()), "native_member_pixels": int(member.sum()),
        "native_residual_pixels": int((parent & ~member).sum()), "native_foreign_pixels": int(foreign.sum()),
        "selection_id": manifest["selection"]["id"], "selection_manifest": manifest,
        "manifest_sha256": source_region_selection_digest(manifest), "source_identity": identity,
        **{f"whole_parent_{key}_pixels": 0 for key in
           ("protected_source", "previously_claimed_source", "noncurrent_source", "foreign_source")},
    }


def document():
    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.header["$FILLMODE"] = 1
    doc.modelspace().add_text("UNRELATED TEXT", dxfattribs={"height": 2.})
    return doc


def manifest_in(doc):
    dictionary = doc.rootdict[DICTIONARY_KEY]
    entries = list(dictionary.items())
    assert len(entries) == 1
    return json.loads("".join(tag.value for tag in entries[0][1].tags))


def fill_from_hatch(hatch, frame, record):
    """Independent center ray crossings against actual saved HATCH vertices."""
    mask = np.zeros(record["native_shape"], bool)
    ox, oy = record["origin_work_px"]
    scale = record["native_scale"]
    for y, x in np.ndindex(mask.shape):
        xx, yy = frame.edge(ox + (x + .5) / scale, oy + (y + .5) / scale)
        inside = False
        for path in hatch.paths:
            points = [(px, py) for px, py, bulge in path.vertices]
            assert all(bulge == 0 for _, _, bulge in path.vertices)
            for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
                if (ay > yy) != (by > yy) and xx < ax + (yy - ay) * (bx - ax) / (by - ay):
                    inside = not inside
        mask[y, x] = inside
    return runs(mask)


@pytest.mark.parametrize("frame", [
    RasterToCad(.254, .310, 3.25, 80., True),
    raster_to_cad((64, 64), None),
    raster_to_cad((64, 64), ScaleCalibration.for_paper((64, 64), (210., 297.), corners_at_centers=True)),
    raster_to_cad((64, 64), ScaleCalibration.for_paper((100, 100), (210., 297.)), crop=(5, 7, 69, 71), origin_y=-500.),
])
def test_actual_saved_hatches_preserve_every_cell_hole_and_official_edge_frame(tmp_path, frame):
    record = source_record()
    plan = preflight_source_region(record, edge_transform=frame.edge)
    assert len(plan.residual) == 4  # outer, hole, hole island, isolated cell
    assert len(plan.backup) == 5
    doc = document()
    member, residual, backup, _ = emit_source_region_plan(doc, doc.modelspace(), plan)
    assert all(e.dxftype() == "HATCH" for e in (member, residual, backup))
    path = tmp_path / "exact-regions.dxf"
    doc.saveas(path)
    read = ezdxf.readfile(path)
    assert not read.audit().errors
    metadata = manifest_in(read)
    assert metadata["record_sha256"] == plan.record_sha256
    assert len(read.modelspace().query("TEXT")) == 1
    assert len(read.modelspace().query("HATCH")) == 3
    roles = {entity.get_xdata(APPID)[2].value: entity for entity in read.modelspace().query("HATCH")}
    for role, field in (("member", "member"), ("residual", "residual"), ("backup", "source")):
        hatch = roles[role]
        assert fill_from_hatch(hatch, frame, record) == record[f"native_{field}_runs_y_x0_x1"]
        expected = getattr(plan, role)
        assert [tuple((x, y) for x, y, _ in p.vertices) for p in hatch.paths] == [r.coordinates for r in expected]
        layer = read.layers.get(hatch.dxf.layer)
        assert layer.is_off() == layer.is_frozen() == (role == "backup")
        assert layer.is_locked() == (role != "member")
        assert hatch.dxf.color == 256 and hatch.dxf.get("invisible", 0) == 0


@pytest.mark.parametrize("invalid", ["version", "selector", "guard", "count", "foreign_count", "manifest", "identity", "scale_bool", "runs", "budget", "bbox", "unknown_field"])
def test_inconsistent_record_rejected_without_document_mutation(invalid):
    record = source_record()
    if invalid == "version":
        record["version"] = "observed-compound-parts-v1"
    elif invalid == "selector":
        record["native_source_open_stroke"] = True
    elif invalid == "guard":
        record["whole_parent_previously_claimed_source_pixels"] = 1
    elif invalid == "count":
        record["native_residual_pixels"] -= 1
    elif invalid == "foreign_count":
        record["native_foreign_pixels"] += 1
    elif invalid == "manifest":
        record["selection_manifest"]["selection"]["native_member_runs_y_x0_x1"][0][2] += 1
        record["manifest_sha256"] = source_region_selection_digest(record["selection_manifest"])
    elif invalid == "identity":
        record["source_identity"]["original_pixels_sha256"] = "f" * 64
    elif invalid == "scale_bool":
        record["native_scale"] = True
    elif invalid == "runs":
        record["native_residual_runs_y_x0_x1"].reverse()
    elif invalid == "budget":
        record["native_shape"] = [2_000_000, 2_000_000]
    elif invalid == "bbox":
        record["bbox"][0] += 1
    else:
        record["claims_CAD_validation_passed"] = True
    doc = document()
    before = set(doc.entitydb)
    with pytest.raises(ValueError):
        preflight_source_region(record, edge_transform=RasterToCad(1., 1., 0., 100., False).edge)
    assert set(doc.entitydb) == before


@pytest.mark.parametrize("transform", [
    lambda x, y: (x + .1 * y, -y),
    lambda x, y: (x, y),
    lambda x, y: (x + (1. if x > 2 else 0.), -y),
    RasterToCad(.01, .01, 1.e20, 1.e20, True).edge,
    lambda x, y: (float("nan"), -y),
])
def test_invalid_or_collapsed_frame_rejected(transform):
    with pytest.raises(ValueError):
        preflight_source_region(source_record(), edge_transform=transform)


@pytest.mark.parametrize("failure_after_creation", [False, True])
def test_document_preflight_is_early_and_emit_failure_rolls_back(monkeypatch, failure_after_creation):
    plan = preflight_source_region(source_record(), edge_transform=lambda x, y: (x, -y))
    doc = document()
    doc.appids.new(APPID)  # Existing legitimate APPID is allowed.
    before_entities = set(doc.entitydb)
    before_layers = set(layer.dxf.name for layer in doc.layers)
    before_objects = [entity.dxf.handle for entity in doc.objects]
    msp = doc.modelspace()
    original = msp.add_hatch
    calls = [0]

    def failing(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            if failure_after_creation:
                original(*args, **kwargs)
            raise RuntimeError("injected second-HATCH failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(msp, "add_hatch", failing)
    with pytest.raises(RuntimeError, match="injected"):
        emit_source_region_plan(doc, msp, plan)
    assert set(e.dxf.handle for e in doc.entitydb.values() if e.is_alive) == before_entities
    assert set(layer.dxf.name for layer in doc.layers) == before_layers
    assert [e.dxf.handle for e in doc.objects if e.is_alive] == before_objects
    assert DICTIONARY_KEY not in doc.rootdict and APPID in doc.appids
    assert len(msp) == 1


def test_document_rejects_repeated_selection_and_disabled_fill_before_mutation():
    plan = preflight_source_region(source_record(), edge_transform=lambda x, y: (x, -y))
    doc = document()
    doc.header["$FILLMODE"] = 0
    before = set(doc.entitydb)
    with pytest.raises(ValueError, match="fill"):
        preflight_source_region_document(doc, (plan,))
    assert set(doc.entitydb) == before
    doc.header["$FILLMODE"] = 1
    emit_source_region_plan(doc, doc.modelspace(), plan)
    before = set(doc.entitydb)
    with pytest.raises(ValueError, match="already exists"):
        preflight_source_region_document(doc, (plan,))
    assert set(doc.entitydb) == before


def test_real_final_structure_cache_roundtrip_exports_frozen_region_record(tmp_path):
    from app.core.cache import load_trace_cache, save_trace_cache
    from app.core.structure import FinalStructure
    from app.core.trace_types import TracePath
    from app.export.trace_single_export import export_final_structure_dxf
    from app.geometry.raster_trace import RasterTraceResult

    record = source_record()
    record["contour_index"] = 0
    binary = np.full((64, 64), 255, np.uint8)
    path = TracePath(((6., 7.), (16., 7.), (16., 17.), (6., 17.)), None, 0, 0)
    structure = FinalStructure((64, 64), binary, (path,), provenance={"engineering_enclosures": [record]})
    frozen = structure.provenance["engineering_enclosures"][0]
    assert isinstance(frozen, MappingProxyType)
    plan = preflight_source_region(frozen, edge_transform=RasterToCad(1., 1., 0., 64., False).edge)
    result = RasterTraceResult(binary, {}, (path,), 128, 0, 4, final_structure=structure)
    cache_path = save_trace_cache(tmp_path / "source-regions.npz", result)
    restored = load_trace_cache(cache_path).final_structure
    assert restored is not None and restored.structure_id == structure.structure_id
    assert isinstance(restored.provenance["engineering_enclosures"][0], MappingProxyType)
    output = tmp_path / "from-frozen-cache.dxf"
    export_final_structure_dxf(restored, output)
    read = ezdxf.readfile(output)
    assert len(read.modelspace().query("HATCH")) == 3
    assert len(read.modelspace().query("LWPOLYLINE")) == 0
    assert manifest_in(read)["record_sha256"] == plan.record_sha256
