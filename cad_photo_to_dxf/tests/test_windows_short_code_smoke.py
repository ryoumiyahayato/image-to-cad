"""Fifth saved-output checker tests; fabricated receipts are never OCR proof."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

import ezdxf
from ezdxf.fonts import fonts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from app.native_objects.single_line_labels import _partition
from app.native_objects.single_line_neighbor_clearance import check_text_round_white_gaps
from app.native_objects.single_line_source_layout import fit_source_glyph_layout, verify_source_glyph_layout
from app.native_objects.single_line_text_audit import source_ink_text_layout
from app.native_objects.source_row_font_registry import FONT_SPEC, SOURCE_ROW_FONT
from scripts.windows_native_smoke import (
    SHORT_CODE_LABEL_FIXTURE,
    SHORT_CODE_NEIGHBOR_FIXTURE,
    _json_digest,
    create_short_code_fixture,
    inspect_contact_edit_isolation,
    inspect_short_code_members,
    read_source_row_font_spec,
)


@pytest.fixture(scope="module")
def fixture_fonts():
    root = Path(__file__).resolve().parents[1]
    legacy = root / "resources/fonts/DejaVuSans.ttf"
    original = root / "resources/fonts" / SOURCE_ROW_FONT["font"]["file"]
    source = root / "resources/fonts" / FONT_SPEC["font"]
    if not legacy.is_file() or not source.is_file() or not original.is_file():
        pytest.skip("Prepare the pinned old and source-row fonts; Windows workflow does this before pytest")
    assert read_source_row_font_spec(root) == FONT_SPEC
    return legacy, original, source


@pytest.fixture(scope="module")
def geometry_only_template(tmp_path_factory, fixture_fonts):
    """Actual zero-OCR fit with external constructor truth, no adopted result."""
    legacy, original, source = fixture_fonts
    path = tmp_path_factory.mktemp("shortcode-original") / "source.png"
    create_short_code_fixture(path, legacy, original)
    gray = np.asarray(Image.open(path).convert("L"))
    glyph = Image.new("L", (640, 480), 0)
    source_font = ImageFont.truetype(str(original), 36, layout_engine=ImageFont.Layout.BASIC)
    text, point = SHORT_CODE_LABEL_FIXTURE[0]
    ImageDraw.Draw(glyph).text(point, text, font=source_font, fill=255)
    ys, xs = np.nonzero(np.asarray(glyph) >= 64)
    seed = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    roi, dpi = [0, 0, 640, 480], 200
    partition, reason = _partition(gray, roi, seed)
    assert partition is not None and reason is None
    box = partition["bbox_xyxy_px"]
    geometry = {"text": text, "x": box[0], "y": box[3], "width_px": box[2] - box[0],
                "height_px": box[3] - box[1], "rotation_deg_image": 0.0}
    old_layout = source_ink_text_layout(geometry, roi, dpi, legacy)
    old_attributes = {"text": text, **{key: old_layout[key] for key in ("insert", "height", "width", "rotation")}}
    default = check_text_round_white_gaps(gray, roi, partition, old_attributes, legacy, dpi)
    fitted = fit_source_glyph_layout(geometry, partition, roi, dpi, source, gray=gray)
    assert default["pass"] is False and fitted["pass"] is True
    attributes = {"text": text, **{key: fitted["selected_layout"][key] for key in ("insert", "height", "width", "rotation")}}
    rounds = check_text_round_white_gaps(gray, roi, partition, attributes, source, dpi)
    actual = verify_source_glyph_layout(geometry, partition, roi, dpi, source, attributes, gray=gray)
    assert rounds["pass"] is True and len(rounds["relations"]) == 1 and actual["pass"] is True
    adoption = {**rounds, "selected_layout": fitted["selected_layout"], "font": fitted["font"],
                "source_fit": fitted["source_fit"], "source_neighbor_clearance": fitted["source_neighbor_clearance"],
                "default_layout_rejection": default,
                "layout_selection": "one_pinned_source_component_fit_after_default_white_gap_failure"}
    return {"geometry": geometry, "partition": partition, "adoption": adoption,
            "actual_attributes": attributes, "rounds": rounds, "actual_components": actual}


def saved_checker_fixture(tmp_path, fixture_fonts, template):
    """Artificial transport records only; no production recognition is claimed."""
    legacy, _, source = fixture_fonts
    value = deepcopy(template)
    document = ezdxf.new("R2013")
    document.units = 4
    document.appids.new("I2CAD_NATIVE_V2")
    document.styles.new("I2CAD_TEXT", dxfattribs={"font": "DejaVuSans.ttf"})
    document.styles.new(FONT_SPEC["style"], dxfattribs={"font": FONT_SPEC["font"]})
    mm = 25.4 / 200

    def mark(entity, oid, kind, **extra):
        entity.set_xdata("I2CAD_NATIVE_V2", [(1000, json.dumps({"id": oid, "kind": kind, **extra}))])

    attrs = {key: value["actual_attributes"][key] for key in ("insert", "height", "width", "rotation")}
    entity = document.modelspace().add_text(value["geometry"]["text"], dxfattribs={**attrs, "style": FONT_SPEC["style"]})
    mark(entity, "label", "TEXT")
    recovery = {"schema": "native-single-line-label-evidence-v1", "checker_test_only": True,
                "decision": {"accepted": True, "text": value["geometry"]["text"]},
                "source_partition": value["partition"], "layout_adoption": value["adoption"]}
    rows = [{"id": "label", "kind": "TEXT", "geometry": value["geometry"], "source_evidence": {"single_line_recovery": recovery}}]
    glyph = Image.new("L", (640, 480), 0)
    font = ImageFont.truetype(str(legacy), 26, layout_engine=ImageFont.Layout.BASIC)
    ImageDraw.Draw(glyph).text((460, 64), "STORE", font=font, fill=255)
    x0, y0, x1, y1 = glyph.getbbox()
    height = (y1 - y0) * mm
    entity = document.modelspace().add_text("STORE", dxfattribs={
        "insert": (x0 * mm, (480 - y1) * mm), "height": height,
        "width": (x1 - x0) * mm / fonts.sideload_ttf(legacy, height).text_width("STORE"), "style": "I2CAD_TEXT",
    })
    mark(entity, "control", "TEXT")
    rows.append({"id": "control", "kind": "TEXT"})
    relation = value["rounds"]["relations"][0]
    circle_id, circle = relation["circle_id"], relation["circle_geometry"]
    entity = document.modelspace().add_circle((circle["center"][0] * mm, (480 - circle["center"][1]) * mm), circle["radius_px"] * mm)
    mark(entity, circle_id, "CIRCLE")
    rows.append({"id": circle_id, "kind": "CIRCLE"})
    line_checks = []
    for index, (start, end) in enumerate(SHORT_CODE_NEIGHBOR_FIXTURE):
        oid = "line-" + str(index)
        entity = document.modelspace().add_line((start[0] * mm, (480 - start[1]) * mm), (end[0] * mm, (480 - end[1]) * mm))
        mark(entity, oid, "LINE")
        rows.append({"id": oid, "kind": "LINE"})
        line_checks.append({"id": oid, "type": "LINE", "pass": True, "source_fraction": 1.0, "maximum_gap_px": 0.0, "max_distance_px": 0.0})
    plan = value["partition"]["text_contact_separation"]["geometry_plan"]
    selected = plan["paths"][0]
    entity = document.modelspace().add_lwpolyline([(x * mm, (480 - y) * mm) for x, y in selected["representation"]["points"]])
    mark(entity, "lead", "CONNECTION_PATH", text_contact_path=True)
    rows.append({"id": "lead", "kind": "CONNECTION_PATH", "geometry": selected["representation"],
                 "source_evidence": {"text_contact_path": {
                     "schema": "source-text-contact-native-path-v1", "source_sha256": "checker-only",
                     "plan_sha256": _json_digest(plan), "path_index": 0, "path": selected, "path_sha256": _json_digest(selected),
                 }}})
    check = {"pass": True, "checks": {"checker_only_not_actual_source_replay": True}}
    source_check = {"id": "label", "type": "SINGLE_LINE_TEXT_SOURCE_BINDING", "pass": True,
                    "source_replay": {"pass": True, "new_OCR_calls": 0, "new_model_calls": 0,
                                      "text": value["geometry"]["text"], "layout_adoption": value["adoption"],
                                      "all_raw_artifacts_read_and_hashed": True, "checker_test_only": True},
                    "actual_saved_source_component_layout": value["actual_components"],
                    "actual_saved_text_round_clearance": value["rounds"]}
    cold = {
        "native_text_candidate_checks": [{"id": oid, "type": "NATIVE_TEXT_CANDIDATE_BINDING", "pass": True} for oid in ("label", "control")],
        "single_line_text_source_checks": [source_check],
        "source_checks": [*line_checks, {"id": circle_id, "type": "CIRCLE", "pass": True, "sampled_sweep_deg": 360.0,
                                         "samples": math.ceil(2 * math.pi * circle["radius_px"] / 0.05)}],
        "circular_marker_source_checks": [{"id": circle_id, "pass": True, "ring_source": {"pass": True}}],
        "text_contact_source_checks": {"schema": "saved-text-contact-source-audit-v1", "pass": True,
                                       "target_ids": ["lead"], "duplicate_conflicts": [], "source_or_DXF_geometry_modified": False, "checks": [
            {"id": "lead", "type": "SAVED_TEXT_CONTACT_PATH_SOURCE", "pass": True,
             "checks": {key: True for key in ("three_way_object_binding", "actual_identity_and_flag", "actual_vertices",
                                              "original_source_plan_replayed", "original_source_geometry_supported", "whole_native_representation_from_source_plan")},
             "original_source_plan_replay": deepcopy(check), "actual_source_geometry": deepcopy(check)},
            {"id": "TEXT_CONTACT_NEIGHBORS", "type": "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION", "pass": True,
             "protected_count": len(rows) - 1, "objects": [{"id": row["id"], **deepcopy(check)} for row in rows[:-1]]},
            {"id": "TEXT_CONTACT_MANIFEST", "type": "TEXT_CONTACT_MANIFEST_BINDING", **deepcopy(check)},
            {"id": "TEXT_CONTACT_RETIREMENT", "type": "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT", **deepcopy(check)},
            {"id": "TEXT_CONTACT_DUPLICATES", "type": "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES", "pass": True, "conflicts": []},
        ]},
    }
    companion = tmp_path / "checker.native"
    companion.mkdir()
    shutil.copyfile(source, companion / FONT_SPEC["font"])
    shutil.copyfile(source.parent / FONT_SPEC["source_license"], companion / FONT_SPEC["bundled_license"])
    shutil.copyfile(source.parent / FONT_SPEC["librecad_font"], companion / FONT_SPEC["librecad_font"])
    objects = {"objects": rows, "source_sha256": "checker-only", "fonts": [{**FONT_SPEC, "source": str(source)}]}
    path = tmp_path / "checker.dxf"
    document.saveas(path)
    reopened = ezdxf.readfile(path)
    saved_text = next(entity for entity in reopened.modelspace().query("TEXT") if entity.dxf.text != "STORE")
    # The real cold checker hashes serialized attributes, including DXF's
    # normalization of a negative zero rotation. Do the same in this fake receipt.
    actual = {"text": saved_text.dxf.text, "insert": [float(v) for v in saved_text.dxf.insert],
              "height": float(saved_text.dxf.height), "width": float(saved_text.dxf.get("width", 1.0)),
              "rotation": float(saved_text.dxf.get("rotation", 0.0))}
    cold["single_line_text_source_checks"][0]["actual_saved_text_round_clearance"]["actual_text_attributes_sha256"] = _json_digest(actual)
    return path, reopened, objects, cold, companion


def test_fifth_input_triggers_actual_new_layout_without_OCR(geometry_only_template):
    value = geometry_only_template
    assert len(value["partition"]["components"]) == len(SHORT_CODE_LABEL_FIXTURE[0][0])
    assert value["adoption"]["default_layout_rejection"]["pass"] is False
    assert value["actual_components"]["actual_attributes_used"] is True
    assert value["rounds"]["relations"][0]["original_white_gap_proved"] is True
    assert value["partition"]["text_contact_separation"]["shared_original_contact_runs"]


def test_fifth_saved_checker_requires_new_layout_and_independent_edits(tmp_path, fixture_fonts, geometry_only_template):
    path, document, objects, cold, companion = saved_checker_fixture(tmp_path, fixture_fonts, geometry_only_template)
    result = inspect_short_code_members(document, objects, cold, FONT_SPEC, companion)
    assert result["complete_label_count"] == 1 and result["all_formal_objects_accounted_for"]
    edits = inspect_contact_edit_isolation(path, tmp_path / "edits", result["text_id"], result["independent_contact_path_id"])
    assert edits["pass"] is True and len(edits["checks"]) == 5
    assert all(row["unchanged_other_formal_objects"] == 5 for row in edits["checks"])
    assert edits["GUI_operations_claimed"] is False


@pytest.mark.parametrize("damage", [
    "prefix", "comma", "font-style", "moved-text", "duplicate-lead", "missing-underline", "missing-circle",
    "font-missing", "license-changed", "LFF-missing", "LFF-changed", "font-ledger-changed", "default-did-not-fail", "layout-missing",
    "no-source-replay", "no-actual-component-check", "actual-attributes-not-used", "glyph-component-omitted",
    "source-fit-failed", "whole-graphic-exemption", "empty-rounds", "changed-actual-attributes", "closed-white-gap",
    "circle-not-source-checked", "no-lead-plan-replay", "no-lead-audit", "neighbor-omitted",
    "lead-vertex-binding-omitted", "subtle-lead-change", "no-retirement-check",
    "LFF-check-missing", "LFF-check-wrong-font", "LFF-advance-changed", "LFF-check-not-read",
])
def test_fifth_checker_rejects_incomplete_or_unchecked_outputs(tmp_path, fixture_fonts, geometry_only_template, damage):
    _, document, objects, cold, companion = saved_checker_fixture(tmp_path, fixture_fonts, geometry_only_template)
    target = next(entity for entity in document.modelspace().query("TEXT") if entity.dxf.text != "STORE")
    source = cold["single_line_text_source_checks"][0]
    adoption = objects["objects"][0]["source_evidence"]["single_line_recovery"]["layout_adoption"]
    if damage == "prefix":
        target.dxf.text = "PX-17"
    elif damage == "comma":
        target.dxf.text = "PX-1729"
    elif damage == "font-style":
        target.dxf.style = "I2CAD_TEXT"
    elif damage == "moved-text":
        target.translate(1, 0, 0)
    elif damage == "duplicate-lead":
        document.modelspace().add_entity(document.modelspace().query("LWPOLYLINE")[0].copy())
    elif damage == "missing-underline":
        document.modelspace().delete_entity(document.modelspace().query("LINE")[0])
    elif damage == "missing-circle":
        document.modelspace().delete_entity(document.modelspace().query("CIRCLE")[0])
    elif damage == "font-missing":
        (companion / FONT_SPEC["font"]).unlink()
    elif damage == "license-changed":
        (companion / FONT_SPEC["bundled_license"]).write_text("incomplete license")
    elif damage == "LFF-missing":
        (companion / FONT_SPEC["librecad_font"]).unlink()
    elif damage == "LFF-changed":
        (companion / FONT_SPEC["librecad_font"]).write_text("changed source-row stroke font")
    elif damage == "font-ledger-changed":
        objects["fonts"][0]["sha256"] = "other-font"
    elif damage == "default-did-not-fail":
        adoption["default_layout_rejection"]["pass"] = True
    elif damage == "layout-missing":
        adoption.pop("selected_layout")
    elif damage == "no-source-replay":
        source.pop("source_replay")
    elif damage == "no-actual-component-check":
        source.pop("actual_saved_source_component_layout")
    elif damage == "actual-attributes-not-used":
        source["actual_saved_source_component_layout"]["actual_attributes_used"] = False
    elif damage == "glyph-component-omitted":
        source["actual_saved_source_component_layout"]["source_fit"]["component_center_errors_px"].pop()
    elif damage == "source-fit-failed":
        source["actual_saved_source_component_layout"]["source_fit"]["checks"]["component_positions_match_source"] = False
    elif damage == "whole-graphic-exemption":
        source["actual_saved_source_component_layout"]["source_neighbor_clearance"]["checks"][0]["whole_graphic_component_exempted"] = True
    elif damage == "empty-rounds":
        source["actual_saved_text_round_clearance"]["relations"] = []
    elif damage == "changed-actual-attributes":
        source["actual_saved_text_round_clearance"]["actual_text_attributes_sha256"] = "candidate-only"
    elif damage == "closed-white-gap":
        source["actual_saved_text_round_clearance"]["relations"][0]["actual_font_touches_original_ring_ink"] = True
    elif damage == "circle-not-source-checked":
        cold["circular_marker_source_checks"] = []
    elif damage == "no-lead-plan-replay":
        cold["text_contact_source_checks"]["checks"][0].pop("original_source_plan_replay")
    elif damage == "no-lead-audit":
        cold["text_contact_source_checks"]["target_ids"] = []
    elif damage == "neighbor-omitted":
        cold["text_contact_source_checks"]["checks"][1]["objects"].pop()
    elif damage == "lead-vertex-binding-omitted":
        cold["text_contact_source_checks"]["checks"][0]["checks"].pop("actual_vertices")
    elif damage == "subtle-lead-change":
        lead = document.modelspace().query("LWPOLYLINE")[0]
        points = list(lead.get_points())
        points[len(points) // 2] = (points[len(points) // 2][0] + 0.01, *points[len(points) // 2][1:])
        lead.set_points(points)
    elif damage == "no-retirement-check":
        cold["text_contact_source_checks"]["checks"] = [row for row in cold["text_contact_source_checks"]["checks"] if row["id"] != "TEXT_CONTACT_RETIREMENT"]
    elif damage == "LFF-check-missing":
        source["actual_saved_source_component_layout"].pop("actual_saved_LFF_literal_equivalence")
    elif damage == "LFF-check-wrong-font":
        source["actual_saved_source_component_layout"]["actual_saved_LFF_literal_equivalence"]["librecad_sha256"] = "another-lff"
    elif damage == "LFF-advance-changed":
        source["actual_saved_source_component_layout"]["actual_saved_LFF_literal_equivalence"]["maximum_accumulated_advance_difference_unit_capheight"] = 0.01
    elif damage == "LFF-check-not-read":
        source["actual_saved_source_component_layout"]["actual_saved_LFF_literal_equivalence"]["actual_LFF_file_read"] = False
    document.saveas(tmp_path / "damaged.dxf")
    with pytest.raises(AssertionError):
        inspect_short_code_members(ezdxf.readfile(tmp_path / "damaged.dxf"), objects, cold, FONT_SPEC, companion)
