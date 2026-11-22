"""Real native circle serialization and fail-closed saved-source contracts.

Synthetic characters below are exporter inputs, not OCR recognizer answers.
These tests do not fabricate an accepted OCR observation or bypass its gate.
Actual character recognition and real-sheet evidence are tested separately.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import subprocess
import sys

import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.native_objects import cad_io
from app.native_objects.circular_markers import discover_circular_markers
from app.native_objects.quality_review import (
    _candidate_geometry_checks,
    _expanded,
    run_quality_review,
)
from app.native_objects.review_binding import file_sha256


ROI = (0, 0, 180, 110)
DPI = 200
MM = 25.4 / DPI


def _pixel(point):
    return np.array([point[0] / MM, ROI[3] - point[1] / MM])


def _circle(oid="synthetic-circle", center=(50, 50), radius=24):
    return {
        "id": oid,
        "kind": "CIRCLE",
        "layer": "CIRCULAR_MARKERS",
        "geometry": {"center": list(center), "radius_px": radius},
        "source_evidence": {"components_complete": False},
    }


def _marker(oid="synthetic-marker", center=(50, 50), character="K"):
    obj = _circle(oid, center)
    obj["kind"] = "CIRCULAR_MARKER"
    obj["geometry"] = {
        "circle_geometry": obj["geometry"],
        "text_geometry": {
            "text": character,
            "x": center[0] - 6,
            "y": center[1] + 9,
            "height_px": 18,
            "width_px": 12,
            "rotation_deg_image": 0,
        },
    }
    obj["source_evidence"]["components_complete"] = True
    return obj


def _source(*objects):
    yy, xx = np.mgrid[: ROI[3], : ROI[2]]
    gray = np.full(xx.shape, 255, np.uint8)
    for obj in objects:
        g = obj["geometry"]
        g = g.get("circle_geometry", g)
        cx, cy = g["center"]
        gray[np.abs(np.hypot(xx - cx, yy - cy) - g["radius_px"]) <= 1.1] = 0
    return gray


def _export(tmp_path, objects, name="native.dxf"):
    path = tmp_path / name
    cad_io.export_objects(objects, path, ROI, DPI, "synthetic-source-only")
    return path


def _formal(doc):
    return [e for e in doc.modelspace() if e.dxf.layer != "REVIEW"]


def test_native_marker_has_exactly_circle_and_text_in_unique_definitions(tmp_path):
    objects = [_marker(), _marker("second-marker", (130, 50))]
    objects.append(
        {
            "id": "independent-connection",
            "kind": "LINE",
            "layer": "CONNECTIONS",
            "geometry": {"start": [74, 50], "end": [106, 50]},
        }
    )
    path = _export(tmp_path, objects)
    doc = ezdxf.readfile(path)
    first, second, connection = _formal(doc)
    assert first.dxftype() == second.dxftype() == "INSERT"
    assert first.dxf.name != second.dxf.name
    assert [e.dxftype() for e in doc.blocks.get(first.dxf.name)] == ["CIRCLE", "TEXT"]
    assert [e.dxftype() for e in doc.blocks.get(second.dxf.name)] == ["CIRCLE", "TEXT"]
    assert connection.dxftype() == "LINE"
    for entity, obj in zip((first, second), objects):
        checks = _candidate_geometry_checks(entity, obj, _expanded(entity), _pixel, MM)
        assert all(checks.values()), checks


def test_moving_deleting_and_editing_one_block_preserves_other_instance(tmp_path):
    objects = [_marker(), _marker("other-marker", (130, 50))]
    path = _export(tmp_path, objects)
    doc = ezdxf.readfile(path)
    first, other = _formal(doc)
    original_other = cad_io.entity_data(other)
    original_other_members = [
        cad_io.entity_data(e) for e in doc.blocks.get(other.dxf.name)
    ]
    first.translate(6, 4, 0)
    first_block = doc.blocks.get(first.dxf.name)
    next(e for e in first_block if e.dxftype() == "TEXT").dxf.text = "R"
    edited = tmp_path / "edited.dxf"
    doc.saveas(edited)
    cold = ezdxf.readfile(edited)
    moved, unchanged = _formal(cold)
    assert list(moved.dxf.insert)[:2] == pytest.approx(
        [50 * MM + 6, (ROI[3] - 50) * MM + 4]
    )
    assert (
        next(
            e for e in cold.blocks.get(moved.dxf.name) if e.dxftype() == "TEXT"
        ).dxf.text
        == "R"
    )
    assert cad_io.entity_data(unchanged) == original_other
    assert [
        cad_io.entity_data(e) for e in cold.blocks.get(unchanged.dxf.name)
    ] == original_other_members
    cold.modelspace().delete_entity(moved)
    deleted = tmp_path / "deleted.dxf"
    cold.saveas(deleted)
    # A genuinely fresh process sees only the surviving instance; the removed
    # definition can remain unreferenced without leaving visible glyphs.
    code = "import ezdxf,json,sys; d=ezdxf.readfile(sys.argv[1]); e=[e for e in d.modelspace() if e.dxf.layer!='REVIEW']; print(json.dumps({'types':[v.dxftype() for v in e], 'text':[m.dxf.text for v in e for m in v.virtual_entities() if m.dxftype()=='TEXT']}))"
    result = subprocess.run(
        [sys.executable, "-c", code, str(deleted)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"types": ["INSERT"], "text": ["K"]}


def test_circle_cold_audit_samples_all_quadrants_and_rejects_real_white_gap(tmp_path):
    obj = _circle()
    gray = _source(obj)
    path = _export(tmp_path, [obj])
    report = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "cold.json")
    ring = next(row for row in report["source_checks"] if row["type"] == "CIRCLE")
    assert ring["pass"] and ring["sampled_sweep_deg"] == 360
    assert ring["samples"] >= math.ceil(2 * math.pi * 24 / 0.05)
    # This source has no replayable detector evidence, so geometric proximity
    # by itself must not promote the circle to source-approved output.
    assert not report["source_gate_pass"]
    assert report["circular_marker_source_checks"][0]["pass"] is False
    damaged = gray.copy()
    damaged[19:35, 40:61] = 255
    bad = cad_io.cold_audit(path, damaged, ROI, DPI, tmp_path / "gap.json")
    ring = next(row for row in bad["source_checks"] if row["type"] == "CIRCLE")
    assert not ring["pass"] and ring["max_distance_px"] > ring["tolerance_px"]
    assert np.array_equal(gray, _source(obj))


def test_missing_candidate_ledger_is_rejected_even_with_a_visible_source_ring(tmp_path):
    obj = _circle()
    path = _export(tmp_path, [obj])
    path.with_suffix(".objects.json").unlink()
    report = cad_io.cold_audit(path, _source(obj), ROI, DPI, tmp_path / "missing.json")
    assert not report["source_gate_pass"]
    assert "FileNotFoundError" in report["circular_marker_source_checks"][0]["failure"]


def test_recomputed_source_circle_passes_cold_binding_but_stays_partial(tmp_path):
    gray = _source(_circle())
    gray[43:58, 48:51] = 0  # Unrecognized true interior stroke, kept in source.
    discovery = discover_circular_markers(gray, ROI)
    rows = [row for row in discovery["rows"] if row["geometry_accepted"]]
    assert len(rows) == 1
    row = rows[0]
    obj = {
        "id": row["id"],
        "kind": "CIRCLE",
        "layer": "CIRCULAR_MARKERS",
        "geometry": row["geometry"],
        "source_evidence": {**row["source_evidence"], "components_complete": False},
    }
    path = _export(tmp_path, [obj])
    report = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "proved-partial.json")
    assert report["source_gate_pass"], report["source_checks"]
    assert report["formal_modelspace_types"] == {"CIRCLE": 1}
    assert report["texts"] == []
    source_check = report["circular_marker_source_checks"][0]
    assert source_check["ring_source"]["all_source_runs_replayed"]
    assert "character_source" not in source_check
    # Damage limited to the unrecognized interior invalidates the original
    # crop binding. Border rendering cannot approve altered source.
    changed = gray.copy()
    changed[48, 49] = 255
    bad = cad_io.cold_audit(path, changed, ROI, DPI, tmp_path / "changed-source.json")
    assert not bad["source_gate_pass"]
    reasons = bad["circular_marker_source_checks"][0]["ring_source"]["reasons"]
    assert "CIRCULAR_SOURCE_CROP_HASH_MISMATCH" in reasons


@pytest.mark.parametrize("radius", [0, -1, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_circle_is_never_serialized(tmp_path, radius):
    with pytest.raises(ValueError, match="CIRCLE_RADIUS"):
        _export(tmp_path, [_circle(radius=radius)])


@pytest.mark.parametrize(
    "change", ["radius", "text_width", "text_value", "extra_line", "zscale"]
)
def test_actual_saved_member_tampering_is_not_hidden_by_candidate_fields(
    tmp_path, change
):
    obj = _marker()
    path = _export(tmp_path, [obj])
    doc = ezdxf.readfile(path)
    entity = _formal(doc)[0]
    block = doc.blocks.get(entity.dxf.name)
    circle = next(e for e in block if e.dxftype() == "CIRCLE")
    text = next(e for e in block if e.dxftype() == "TEXT")
    if change == "radius":
        circle.dxf.radius += 0.1 * MM  # Still near the real ink, but not the candidate.
    elif change == "text_width":
        text.dxf.width *= 0.95
    elif change == "text_value":
        text.dxf.text = "R"
    elif change == "extra_line":
        block.add_line((0, 0), (5, 0))
    else:
        # ezdxf's Python setter normalizes zero to one; use a real persisted
        # non-unit transform here. Raw LibreCAD zscale=0 remains covered by
        # test_native_cad_compatibility, not silently declared compatible.
        entity.dxf.zscale = 2
    changed = tmp_path / "tampered.dxf"
    doc.saveas(changed)
    actual = _formal(ezdxf.readfile(changed))[0]
    checks = _candidate_geometry_checks(actual, obj, _expanded(actual), _pixel, MM)
    assert not all(checks.values()), (change, checks)


def test_circle_only_cannot_claim_complete_marker_status(tmp_path):
    obj = _circle()
    path = _export(tmp_path, [obj])
    entity = _formal(ezdxf.readfile(path))[0]
    assert all(cad_io.circular_candidate_contract(entity, obj, _pixel, MM).values())
    changed = deepcopy(obj)
    changed["source_evidence"]["components_complete"] = True
    assert not cad_io.circular_candidate_contract(entity, changed, _pixel, MM)[
        "component_status_explicit"
    ]


def test_duplicate_ring_and_retained_same_circle_arc_are_flagged(tmp_path):
    obj = _circle()
    arc = {
        "id": "old-partial-border",
        "kind": "ARC",
        "layer": "GEOMETRY",
        "geometry": {
            **obj["geometry"],
            "start_deg_image": 20,
            "end_deg_image": 95,
            "sweep_deg_image": 75,
        },
    }
    path = _export(tmp_path, [arc, obj])
    report = cad_io.cold_audit(path, _source(obj), ROI, DPI, tmp_path / "overlap.json")
    assert len(report["exact_duplicate_segments"]) == 1
    assert (
        report["exact_duplicate_segments"][0]["duplicate_kind"]
        == "COINCIDENT_CIRCLE_OR_CIRCLE_ARC"
    )
    arc_entity = _formal(ezdxf.readfile(path))[0]
    assert (
        arc_entity.dxf.end_angle - arc_entity.dxf.start_angle
    ) % 360 == pytest.approx(75)


def test_independent_preview_really_draws_circle_not_only_its_metadata(tmp_path):
    obj = _circle()
    path = _export(tmp_path, [obj])
    png = tmp_path / "actual-circle.png"
    result = cad_io.render_saved(path, png, ROI, DPI)
    assert result["renderer"] == "official_ezdxf_to_MuPDF"
    with Image.open(png) as image:
        pixels = np.asarray(image.convert("L"))
    assert pixels.shape == (ROI[3], ROI[2])
    for x, y in [(26, 50), (74, 50), (50, 26), (50, 74)]:
        assert (pixels[y - 2 : y + 3, x - 2 : x + 3] < 128).any()
    assert pixels[50, 50] == 255


def test_quality_review_does_not_count_an_unproved_ring_as_complete(tmp_path):
    obj = _circle()
    gray = _source(obj)
    source = tmp_path / "source.png"
    Image.fromarray(gray).save(source)
    source_hash = hashlib.sha256(gray.tobytes()).hexdigest()
    path = _export(tmp_path, [obj])
    manifest = {
        "source_path": str(source),
        "source_sha256": file_sha256(source),
        "working_array_sha256": source_hash,
        "selection": {"format": "PNG", "source_size_px": [ROI[2], ROI[3]]},
        "coordinates": {"working_ROI_xyxy_px": list(ROI)},
        "job": {
            "recognition_dpi": DPI,
            "roi_source_xyxy_px": list(ROI),
            "orientation_clockwise_degrees": 0,
            "mode": "native-objects",
            "unit": "paper_mm",
        },
    }
    texts = {
        "coordinate_system": "source_pixels_top_left",
        "source_size_px": [ROI[2], ROI[3]],
        "source_array_sha256": source_hash,
        "roi_xyxy_px": list(ROI),
        "regions": [],
        "groups": [],
    }
    report = run_quality_review(
        path, gray, ROI, DPI, [obj], texts, [], manifest, tmp_path / "review"
    )
    assert not report["summary"]["source_geometry_gate_pass"]
    composition = report["summary"]["circular_marker_composition"]
    assert (
        composition["complete_marker_objects"]
        == composition["partial_circle_boundary_objects"]
        == 0
    )
    assert composition["circle_plus_text_is_one_marker_not_two"]
