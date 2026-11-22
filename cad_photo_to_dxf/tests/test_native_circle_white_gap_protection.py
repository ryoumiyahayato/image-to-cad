"""Keep a real independent source line when legacy fitting crosses a gap."""

from copy import deepcopy
import hashlib
import json

import ezdxf
import numpy as np
from PIL import Image, ImageDraw
import pytest

from app.native_objects import cad_io
from app.native_objects import circle_white_gap_protection as protection
from app.native_objects.circle_endpoint_contacts import restore_circle_endpoint_contacts
from app.native_objects.circular_markers import discover_circular_markers
from app.native_objects.circular_marker_adoption import complete_circular_markers
from app.native_objects.geometry import extract_lines


ROI = (0, 0, 260, 180)
DPI = 200


def _source(*, joined=False, left_circle=False):
    image = Image.new("L", (260, 180), 255)
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((154, 64, 206, 116), outline=0, width=3)
    drawing.line((206, 90, 240, 90), fill=0, width=3)
    drawing.line((50 if left_circle else 60, 90, 154 if joined else 151, 90), fill=0, width=3)
    if left_circle:
        drawing.ellipse((10, 70, 50, 110), outline=0, width=3)
    return np.asarray(image).copy()


def _circles(gray, roi=ROI):
    return [{"id": row["id"], "kind": "CIRCLE", "layer": "CIRCULAR_MARKERS",
             "geometry": row["geometry"], "bbox_xyxy_px": row["bbox_xyxy_px"],
             "source_evidence": {**row["source_evidence"], "components_complete": False}}
            for row in discover_circular_markers(gray, roi)["rows"] if row["geometry_accepted"]]


def _line(*, start=(60, 90), end=(157, 90)):
    return {"id": "independent-line", "kind": "LINE", "layer": "GEOMETRY",
            "geometry": {"start": list(start), "end": list(end)},
            "source_evidence": {"method": protection.POLICY["eligible_source_method"],
                                "source_width_px": 3.0, "source_observations": 2,
                                "support": {"maximum_white_gap_px": 0.0}}}


def _apply(gray, objects):
    result = protection.protect_circle_white_gaps(gray, ROI, objects)
    changes = {obj["id"]: obj for obj in result["replacements"]}
    return result, [changes.get(obj["id"], obj) for obj in objects]


def _export(tmp_path, objects, name="protected.dxf"):
    path = tmp_path / name
    cad_io.export_objects(objects, path, ROI, DPI, "synthetic-source-no-OCR")
    return path


def test_real_geometry_extractor_crosses_gap_then_ordinary_circle_stage_preserves_it(tmp_path):
    gray = _source()
    texts = {"coordinate_system": "source_pixels_top_left", "source_size_px": [260, 180],
             "roi_xyxy_px": list(ROI), "regions": []}
    original = extract_lines(gray, ROI, texts, tmp_path / "geometry")["objects"]
    line = next(obj for obj in original if obj["kind"] == "LINE" and obj["geometry"]["start"][0] < 100
                and obj["geometry"]["end"][0] > 154)
    before = deepcopy(line)
    result = complete_circular_markers(gray, ROI, hashlib.sha256(gray.tobytes()).hexdigest(),
                                      original, tmp_path / "circles", dpi=DPI)
    fixes = result["source_white_gap_protection"]["replacements"]
    assert len(fixes) == 1 and fixes[0]["id"] == line["id"]
    assert fixes[0]["geometry"]["end"][0] == pytest.approx(151, abs=0.001)
    assert line == before
    assert result["external_endpoint_contacts"]["replacements"] == []
    circle = result["objects"][0]
    review = circle["source_evidence"]["external_endpoint_contact_review"]
    assert review["pending_contacts"] == []
    assert len(review["protected_source_white_gaps"]) == 1
    assert result["summary"]["new_partial_boundaries"] == 1
    assert result["summary"]["pending_positions"] == 1  # missing character only


@pytest.mark.parametrize("reverse", [False, True])
def test_source_line_is_retained_with_original_identity_and_raw_records(reverse):
    gray = _source()
    line = _line()
    if reverse:
        line["geometry"]["start"], line["geometry"]["end"] = line["geometry"]["end"], line["geometry"]["start"]
    objects = _circles(gray) + [line]
    before = deepcopy(objects)
    result, restored = _apply(gray, objects)
    assert result["summary"]["corrected_independent_lines"] == 1
    assert result["summary"]["new_formal_objects"] == result["summary"]["retired_objects"] == 0
    assert objects == before
    corrected = restored[-1]
    cert = corrected["source_evidence"][protection.FIELD]
    assert corrected["id"] == line["id"]
    assert cert["original_geometry"] == line["geometry"]
    old_evidence = deepcopy(corrected["source_evidence"])
    old_evidence.pop(protection.FIELD)
    assert old_evidence == line["source_evidence"]
    assert cert["ends"][0]["complete_white_strip_width_px"] == 2
    assert protection.verify_white_gap_protection(gray, ROI, corrected, restored, corrected["geometry"])["pass"]
    assert restored[:-1] == objects[:-1]
    assert np.all(gray[88:93, 152:154] == 255)
    assert not restore_circle_endpoint_contacts(gray, ROI, restored)["replacements"]


def test_actual_source_contact_and_existing_supported_overlap_are_kept():
    gray = _source(joined=True)
    objects = _circles(gray) + [_line()]
    result, restored = _apply(gray, objects)
    assert not result["replacements"]
    assert restored == objects


@pytest.mark.parametrize("quarter_turns", [1, 2, 3])
def test_source_separation_proof_is_independent_of_axis_and_drawing_position(quarter_turns):
    gray = np.rot90(_source(), quarter_turns).copy()
    roi = (0, 0, gray.shape[1], gray.shape[0])
    line = _line()

    def rotated(point):
        x, y = point
        width, height = 260, 180
        for _ in range(quarter_turns):
            x, y = y, width - 1 - x
            width, height = height, width
        return [x, y]

    for key in ("start", "end"):
        line["geometry"][key] = rotated(line["geometry"][key])
    objects = _circles(gray, roi) + [line]
    result = protection.protect_circle_white_gaps(gray, roi, objects)
    assert result["summary"]["corrected_independent_lines"] == 1
    fixed = result["replacements"][0]
    assert fixed["geometry"]["start"] == line["geometry"]["start"]
    assert fixed["geometry"]["end"] == pytest.approx(rotated([151, 90]))
    final = objects[:-1] + [fixed]
    assert protection.verify_white_gap_protection(gray, roi, fixed, final, fixed["geometry"])["pass"]


def test_diagonal_source_corner_contact_is_not_relabelled_as_a_full_white_strip():
    gray = _source()
    # Add an 8-connected diagonal route while retaining neighbouring white
    # pixels. There is no proved separating white strip to authorize a trim.
    gray[90, 152] = 0
    gray[91, 153] = 0
    objects = _circles(gray) + [_line()]
    result, restored = _apply(gray, objects)
    assert not result["replacements"]
    assert restored == objects
    assert result["summary"]["pending_terminal_relations"] == 1
    assert result["pending_relations"][0]["reason"] == "LOCAL_CONTACT_IS_DIAGONAL_ONLY_NO_WHITE_STRIP_TRIM_AUTHORITY"


def test_extra_short_source_branch_in_gap_blocks_reassignment_and_is_preserved():
    gray = _source()
    gray[92, 152] = 0
    gray[92, 153] = 0
    branch = {"id": "neighbor-short-branch", "kind": "LINE", "layer": "SHORT_STROKE",
              "geometry": {"start": [152, 92], "end": [153, 92]}, "source_evidence": {}}
    objects = _circles(gray) + [_line(), branch]
    before = deepcopy(objects)
    result, restored = _apply(gray, objects)
    assert result["replacements"] == []
    assert restored == before and objects == before


def test_block_member_and_nearby_nonintersecting_line_are_not_modified():
    gray = _source()
    block = {"id": "existing-block", "kind": "WALL_SEGMENT", "layer": "WALL_SEGMENTS",
             "geometry": {"members": [{"kind": "LINE", "geometry": _line()["geometry"]}]},
             "source_evidence": {}}
    objects = _circles(gray) + [block, _line(end=(151, 90))]
    result, restored = _apply(gray, objects)
    assert not result["replacements"] and restored == objects


def test_same_line_can_keep_a_source_gap_at_one_end_and_extend_other_end(tmp_path):
    gray = _source(left_circle=True)
    objects = _circles(gray) + [_line(start=(52, 90))]
    assert len(objects) == 3
    _, protected = _apply(gray, objects)
    extensions = restore_circle_endpoint_contacts(gray, ROI, protected)
    assert extensions["summary"]["restored_external_endpoints"] == 1
    final = protected[:-1] + extensions["replacements"]
    line = final[-1]
    assert protection.FIELD in line["source_evidence"]
    assert "circle_endpoint_contacts" in line["source_evidence"]
    assert line["geometry"]["end"][0] == 151
    assert line["geometry"]["start"][0] < 50
    path = _export(tmp_path, final)
    cold = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "cold.json")
    assert cold["source_gate_pass"], cold["source_checks"]
    assert cold["circle_endpoint_contact_checks"][0]["pass"]
    assert cold["circle_white_gap_protection_checks"][0]["pass"]
    assert not protection.protect_circle_white_gaps(gray, ROI, final)["replacements"]


def test_uncorrected_actual_saved_line_fails_even_without_any_certificate(tmp_path):
    gray = _source()
    path = _export(tmp_path, _circles(gray) + [_line()], "original-bad.dxf")
    report = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "bad-cold.json")
    assert not report["source_gate_pass"]
    assert any(row.get("failure") == "SAVED_LINE_STILL_BRIDGES_PROVED_ORIGINAL_WHITE_GAP"
               for row in report["circle_white_gap_protection_checks"])


@pytest.mark.parametrize("mutation", [None, "old_overrun", "other_end", "missing_flag", "missing_proof", "raw_source_record", "circle", "gap_ink"])
def test_actual_saved_line_and_full_gap_proof_are_rechecked(tmp_path, mutation):
    gray = _source()
    _, objects = _apply(gray, _circles(gray) + [_line()])
    path = _export(tmp_path, objects)
    doc = ezdxf.readfile(path)
    line = next(e for e in doc.modelspace() if e.dxftype() == "LINE")
    circle = next(e for e in doc.modelspace() if e.dxftype() == "CIRCLE")
    if mutation == "old_overrun":
        line.dxf.end = (157 * 25.4 / DPI, (ROI[3] - 90) * 25.4 / DPI, 0)
    elif mutation == "other_end":
        line.dxf.start = (62 * 25.4 / DPI, (ROI[3] - 90) * 25.4 / DPI, 0)
    elif mutation == "missing_flag":
        cad_io.mark(line, {"id": objects[-1]["id"], "kind": "LINE"})
    elif mutation == "circle":
        circle.dxf.radius += 0.1
    elif mutation == "gap_ink":
        gray[90, 152:154] = 0
    if mutation in ("old_overrun", "other_end", "missing_flag", "circle"):
        doc.saveas(path)
    sidecar = path.with_suffix(".objects.json")
    meta = json.loads(sidecar.read_text())
    meta["dxf_sha256"] = cad_io.sha(path)
    obj = next(o for o in meta["objects"] if o["kind"] == "LINE")
    if mutation == "missing_proof":
        obj["source_evidence"].pop(protection.FIELD)
    elif mutation == "raw_source_record":
        obj["source_evidence"]["source_observations"] += 1
    sidecar.write_text(json.dumps(meta))
    report = cad_io.cold_audit(path, gray, ROI, DPI, tmp_path / "cold.json")
    assert report["source_gate_pass"] is (mutation is None), report["source_checks"]
    assert all(row["pass"] for row in report["circle_white_gap_protection_checks"]) is (mutation is None)
