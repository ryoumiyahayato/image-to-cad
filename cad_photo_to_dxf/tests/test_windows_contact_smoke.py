"""Saved checker regressions; synthetic receipts are never recognition proof."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import ezdxf
from ezdxf.fonts import fonts
from PIL import Image, ImageDraw, ImageFont
import pytest

from scripts.windows_native_smoke import (
    CONTACT_LABEL_FIXTURE,
    CONTACT_NEIGHBOR_FIXTURE,
    _contact_curve_points,
    _json_digest,
    create_contact_fixture,
    inspect_contact_edit_isolation,
    inspect_contact_members,
)


@pytest.fixture(scope="module")
def checker_font():
    root = Path(__file__).resolve().parents[1]
    path = next((p for p in (root / "resources/fonts/DejaVuSans.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")) if p.is_file()), None)
    assert path is not None, "Prepare the native portable font or its Linux fallback"
    fonts.sideload_ttf(path, 1.0)
    return path


def saved_checker_fixture(tmp_path, font_path):
    """Artificial post-save transport fixture; not an OCR or source-pass claim."""
    document = ezdxf.new("R2013")
    document.units = 4
    document.appids.new("I2CAD_NATIVE_V2")
    document.styles.new("I2CAD_TEXT", dxfattribs={"font": "DejaVuSans.ttf"})
    mm = 25.4 / 200
    rows, text_checks, line_checks = [], [], []

    def mark(entity, oid, kind, **extra):
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": oid, "kind": kind, **extra}))])

    for index, (text, point) in enumerate((*CONTACT_LABEL_FIXTURE, ("STORE", (460, 64)))):
        font = ImageFont.truetype(str(font_path), 32 if index == 0 else 26, layout_engine=ImageFont.Layout.BASIC)
        raster = Image.new("L", (640, 480), 0)
        ImageDraw.Draw(raster).text(point, text, font=font, fill=255)
        x0, y0, x1, y1 = raster.getbbox()
        geometry = {"text": text, "x": x0, "y": y1, "width_px": x1 - x0, "height_px": y1 - y0}
        if index == 0:
            low, high = fonts.sideload_ttf(font_path, 1.0).text_path(text).bbox()
            sx, sy = (x1 - x0) * mm / (high.x - low.x), (y1 - y0) * mm / (high.y - low.y)
            attrs = {"insert": (x0 * mm - low.x * sx, (480 - y1) * mm - low.y * sy), "height": sy, "width": sx / sy}
        else:
            height = (y1 - y0) * mm
            attrs = {"insert": (x0 * mm, (480 - y1) * mm), "height": height,
                     "width": (x1 - x0) * mm / fonts.sideload_ttf(font_path, height).text_width(text)}
        entity = document.modelspace().add_text(text, dxfattribs={**attrs, "style": "I2CAD_TEXT"})
        oid = "label" if index == 0 else "control"
        mark(entity, oid, "TEXT")
        rows.append({"id": oid, "kind": "TEXT", "geometry": geometry})
        text_checks.append({"id": oid, "type": "NATIVE_TEXT_CANDIDATE_BINDING", "pass": True, "checker_test_only": True})
    for index, (start, end) in enumerate(CONTACT_NEIGHBOR_FIXTURE):
        oid = "neighbor-" + str(index)
        entity = document.modelspace().add_line((start[0] * mm, (480 - start[1]) * mm), (end[0] * mm, (480 - end[1]) * mm))
        mark(entity, oid, "LINE")
        rows.append({"id": oid, "kind": "LINE"})
        line_checks.append({"id": oid, "type": "LINE", "pass": True, "source_fraction": 1.0, "maximum_gap_px": 0.0, "max_distance_px": 0.0})
    points = [list(point) for point in _contact_curve_points()[::10]]
    geometry = {"points": points, "bulges": [0.0] * len(points), "closed": False}
    entity = document.modelspace().add_lwpolyline([(x * mm, (480 - y) * mm) for x, y in points])
    mark(entity, "curve", "CONNECTION_PATH", text_contact_path=True)
    selected = {"representation": deepcopy(geometry), "contact_continuations": [{"checker_test_only": True}],
                "shared_contact_runs": [[188, 230, 231]], "line_and_text_may_share_source_pixels": True}
    plan = {"paths": [selected], "original_source_pixels_modified": False, "transcription_supplied": False}
    separation = {"schema": "complete-original-contact-row-separation-v1", "source_erasure_authorized": False,
                  "source_pixels_added": 0, "real_source_white_gaps_filled": False,
                  "independent_graphics_require_separate_adoption": True,
                  "shared_original_contact_runs": [[188, 230, 231]], "recognition_excluded_source_runs": [[90, 190, 192]],
                  "geometry_plan": plan}
    rows[0]["source_evidence"] = {"single_line_recovery": {
        "schema": "native-single-line-label-evidence-v1", "checker_test_only": True,
        "source_partition": {"text_contact_separation": separation},
    }}
    rows.append({"id": "curve", "kind": "CONNECTION_PATH", "geometry": geometry,
                 "source_evidence": {"text_contact_path": {
                     "schema": "source-text-contact-native-path-v1", "source_sha256": "checker-source",
                     "plan_sha256": _json_digest(plan), "path_index": 0,
                     "path_sha256": _json_digest(selected), "path": deepcopy(selected),
                 }}})
    contact_checks = [
        {"id": "TEXT_CONTACT_MANIFEST", "type": "TEXT_CONTACT_MANIFEST_BINDING", "pass": True, "checks": {"checker_test_only": True}},
        {"id": "curve", "type": "SAVED_TEXT_CONTACT_PATH_SOURCE", "pass": True,
         "checks": {key: True for key in ("three_way_object_binding", "actual_identity_and_flag", "actual_vertices", "original_source_plan_replayed", "original_source_geometry_supported", "whole_native_representation_from_source_plan")},
         "original_source_plan_replay": {"pass": True, "checks": {"checker_test_only": True}},
         "actual_source_geometry": {"pass": True, "checks": {"checker_test_only": True}}},
        {"id": "TEXT_CONTACT_RETIREMENT", "type": "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT", "pass": True, "checks": {"checker_test_only": True}},
        {"id": "TEXT_CONTACT_NEIGHBORS", "type": "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION", "pass": True, "protected_count": 4,
         "objects": [{"id": row["id"], "pass": True, "checks": {"checker_test_only": True}} for row in rows[:-1]]},
        {"id": "TEXT_CONTACT_DUPLICATES", "type": "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES", "pass": True, "conflicts": []},
    ]
    cold = {"native_text_candidate_checks": text_checks, "source_checks": line_checks,
            "single_line_text_source_checks": [{"id": "label", "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True, "checker_test_only": True}],
            "text_contact_source_checks": {"schema": "saved-text-contact-source-audit-v1", "target_ids": ["curve"], "checks": contact_checks,
                                           "pass": True, "duplicate_conflicts": [], "source_or_DXF_geometry_modified": False}}
    path = tmp_path / "checker-only.dxf"
    document.saveas(path)
    return path, ezdxf.readfile(path), {"objects": rows, "source_sha256": "checker-source"}, cold


def test_contact_fixture_really_crosses_middle_glyph_and_keeps_complete_endpoints(tmp_path, checker_font):
    path = tmp_path / "source.png"
    create_contact_fixture(path, checker_font)
    first = path.read_bytes()
    create_contact_fixture(path, checker_font)
    assert path.read_bytes() == first
    with Image.open(path) as image:
        assert image.mode == "L" and image.size == (640, 480)
        assert image.getpixel((230, 188)) == 0
        for endpoint in (_contact_curve_points()[0], _contact_curve_points()[-1]):
            assert image.getpixel(endpoint) == 0
            assert 3 < endpoint[0] < 637 and 3 < endpoint[1] < 477
        for start, end in CONTACT_NEIGHBOR_FIXTURE:
            assert image.getpixel(start) == image.getpixel(end) == 0
        assert image.getpixel((479, 300)) == image.getpixel((501, 300)) == 255


def test_contact_checker_requires_complete_saved_pair_and_checks_edit_isolation(tmp_path, checker_font):
    path, document, objects, cold = saved_checker_fixture(tmp_path, checker_font)
    result = inspect_contact_members(document, objects, cold, checker_font)
    assert result["complete_location_count"] == 1
    assert result["new_complete_TEXT_count"] == result["new_complete_independent_path_count"] == 1
    assert result["empty_contact_audit_can_pass"] is False
    assert result["graphic_inside_original_text_rectangle_is_allowed"] is True
    edits = inspect_contact_edit_isolation(path, tmp_path / "edits", "label", "curve")
    assert edits["pass"] and len(edits["checks"]) == 5
    assert edits["GUI_operations_claimed"] is False
    assert all(row["unchanged_other_formal_objects"] == 4 for row in edits["checks"])


@pytest.mark.parametrize("damage", [
    "prefix-only", "wrong-suffix", "wrong-position", "wrong-height", "text-fragment", "missing-underline",
    "missing-short-stroke", "duplicate-curve", "fragmented-curve", "wrong-endpoint", "glyph-branch",
    "no-contact-text-proof", "no-shared-source", "modified-source", "wrong-plan-digest", "wrong-source",
    "no-contact-flag", "empty-contact-targets", "empty-contact-audit", "candidate-only-audit",
    "source-replay-failed", "source-replay-omitted", "geometry-check-omitted", "neighbor-check-omitted",
    "neighbor-failed", "duplicate-conflict", "source-text-check-omitted",
])
def test_contact_checker_rejects_incomplete_or_unchecked_saved_results(tmp_path, checker_font, damage):
    _, document, objects, cold = saved_checker_fixture(tmp_path, checker_font)
    text = document.modelspace().query("TEXT")[0]
    curve = document.modelspace().query("LWPOLYLINE")[0]
    lines = list(document.modelspace().query("LINE"))
    contact = cold["text_contact_source_checks"]
    separation = objects["objects"][0]["source_evidence"]["single_line_recovery"]["source_partition"]["text_contact_separation"]
    proof = objects["objects"][-1]["source_evidence"]["text_contact_path"]
    if damage == "prefix-only":
        text.dxf.text = "STORAGE"
    elif damage == "wrong-suffix":
        text.dxf.text = "STORAGE4Z"
    elif damage == "wrong-position":
        text.translate(4, 0, 0)
    elif damage == "wrong-height":
        text.dxf.height *= 1.4
    elif damage == "text-fragment":
        document.modelspace().add_line((20, 20), (21, 22))
    elif damage.startswith("missing"):
        document.modelspace().delete_entity(lines[0 if damage == "missing-underline" else 1])
    elif damage == "duplicate-curve":
        document.modelspace().add_entity(curve.copy())
    elif damage == "fragmented-curve":
        points = list(curve.get_points())
        curve.set_points(points[:10])
        document.modelspace().add_lwpolyline(points[9:])
    elif damage in ("wrong-endpoint", "glyph-branch"):
        points = list(curve.get_points())
        index = 0 if damage == "wrong-endpoint" else len(points) // 2
        points[index] = (points[index][0] + 5, *points[index][1:])
        curve.set_points(points)
    elif damage == "no-contact-text-proof":
        objects["objects"][0]["source_evidence"]["single_line_recovery"]["source_partition"].clear()
    elif damage == "no-shared-source":
        separation["shared_original_contact_runs"] = []
    elif damage == "modified-source":
        separation["real_source_white_gaps_filled"] = True
    elif damage == "wrong-plan-digest":
        proof["plan_sha256"] = "wrong"
    elif damage == "wrong-source":
        proof["source_sha256"] = "different-source"
    elif damage == "no-contact-flag":
        curve.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": "curve", "kind": "CONNECTION_PATH"}))])
    elif damage == "empty-contact-targets":
        contact["target_ids"] = []
    elif damage == "empty-contact-audit":
        contact["checks"] = []
    elif damage == "candidate-only-audit":
        contact["checks"][1]["type"] = "CANDIDATE_ONLY"
    elif damage == "source-replay-failed":
        contact["checks"][1]["original_source_plan_replay"]["pass"] = False
    elif damage == "source-replay-omitted":
        del contact["checks"][1]["original_source_plan_replay"]
    elif damage == "geometry-check-omitted":
        del contact["checks"][1]["checks"]["actual_vertices"]
    elif damage == "neighbor-check-omitted":
        contact["checks"][3]["objects"].pop()
    elif damage == "neighbor-failed":
        contact["checks"][3]["objects"][0]["pass"] = False
    elif damage == "duplicate-conflict":
        contact["duplicate_conflicts"] = ["same-curve"]
    elif damage == "source-text-check-omitted":
        cold["single_line_text_source_checks"] = []
    document.saveas(tmp_path / "damaged.dxf")
    with pytest.raises(AssertionError):
        inspect_contact_members(ezdxf.readfile(tmp_path / "damaged.dxf"), objects, cold, checker_font)
