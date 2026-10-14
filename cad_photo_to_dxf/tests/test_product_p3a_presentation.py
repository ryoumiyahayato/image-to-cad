"""Source ownership/presentation regressions; OCR values are frozen, not corrected."""

from dataclasses import replace
from pathlib import Path
import json

import cv2
import ezdxf
import numpy as np
import pytest

from app.geometry.source_presentation import (
    source_orientation_graphics,
    stroke_presentation,
    source_fill_records,
)
from app.core.trace_types import TracePath
from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.line_detect import LineSegment
from app.core.structure_build import build_final_structure
from app.core.preview import render_final_structure_preview, render_emitted_dxf_preview
from app.core.cache import save_trace_cache, load_trace_cache
from app.geometry.raster_trace import RasterTraceResult
from app.geometry.optimized_trace import trace_image_optimized
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_document_export import export_trace_document_streaming
from app.export.document_export import DocumentPage
from app.ocr.signature_overlay import source_ink_region
from app.core.image_loader import load_image


def bar(width=7):
    gray = np.full((100, 180), 255, np.uint8)
    gray[50 - width // 2 : 51 + width // 2, 20:161] = 0
    return gray


def model(gray, lines, dpi=300, *, merge=True):
    lines, metadata = stroke_presentation(gray, lines, dpi, allow_merge=merge)
    return build_final_structure(
        source_size_px=gray.shape[::-1],
        contour_binary=np.full_like(gray, 255),
        contours=(),
        straight_lines=lines,
        preview_binary=gray,
        provenance={"stroke_presentation": metadata},
    )


def test_single_thick_stroke_two_detected_edges_emit_one_native_line_and_weight(
    tmp_path,
):
    gray = bar()
    structure = model(
        gray, (LineSegment(20, 47, 160, 47), LineSegment(20, 53, 160, 53))
    )
    assert len(structure.straight_lines) == 1
    record = structure.provenance["stroke_presentation"]["line_records"][0]
    assert record["source_width_px"] == 7
    assert record["cad_lineweight"] == 50
    result = export_final_structure_dxf(structure, tmp_path / "thick.dxf")
    doc = ezdxf.readfile(result.path)
    entities = list(doc.modelspace().query("LINE"))
    assert len(entities) == 1 and entities[0].dxf.lineweight == 50
    assert entities[0].dxf.start.y == 50 and not doc.audit().has_errors
    assert doc.header["$LWDISPLAY"]


def test_full_production_thick_stroke_has_no_residual_fake_boundaries(tmp_path):
    gray = np.full((200, 500), 255, np.uint8)
    cv2.line(gray, (60, 100), (440, 100), 0, 5)
    structure = trace_image_optimized(
        gray, enable_ocr=False, source_dpi=300
    ).final_structure
    assert len(structure.straight_lines) == 1 and not structure.contours
    record = structure.provenance["stroke_presentation"]["line_records"][0]
    assert record["source_width_px"] == 7
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "native.dxf").path
    )
    assert len(list(doc.modelspace())) == 1
    assert doc.modelspace().query("LINE")[0].dxf.lineweight == 50


@pytest.mark.parametrize("fill", [255, 170, 50, 10])
def test_parallel_wall_and_grey_hatch_fill_are_not_single_dark_stroke(fill):
    gray = np.full((100, 180), 255, np.uint8)
    gray[47:54, 20:161] = fill
    gray[47, 20:161] = gray[53, 20:161] = 0
    lines = (LineSegment(20, 47, 160, 47), LineSegment(20, 53, 160, 53))
    structure = model(gray, lines)
    assert structure.straight_lines == lines
    assert all(
        r["source_width_px"] == 1
        for r in structure.provenance["stroke_presentation"]["line_records"]
    )


def test_broad_filled_region_is_not_collapsed_to_an_invented_centerline():
    gray = np.full((100, 180), 255, np.uint8)
    gray[35:66, 20:161] = 0
    lines = (LineSegment(20, 35, 160, 35), LineSegment(20, 65, 160, 65))
    assert model(gray, lines).straight_lines == lines


def test_solid_connected_junctions_veto_boundary_collapse():
    gray = bar()
    cv2.line(gray, (20, 47), (20, 20), 0, 1)
    lines = (
        LineSegment(20, 47, 160, 47),
        LineSegment(20, 53, 160, 53),
        LineSegment(20, 20, 20, 47),
    )
    assert model(gray, lines).straight_lines == lines


def test_double_line_shaft_enclosure_and_open_door_survive_native_reopen(tmp_path):
    gray = np.full((200, 240), 255, np.uint8)
    # Two independent enclosure boundaries, with a door opening on the right.
    # The 6-pixel paper interval is geometry, not a width prescription.
    lines = []
    for left, top, right, bottom in ((20, 20, 220, 180), (26, 26, 214, 174)):
        points = (
            (left, top, right, top),
            (left, bottom, right, bottom),
            (left, top, left, bottom),
            (right, top, right, 80),
            (right, 105, right, bottom),
        )
        for x1, y1, x2, y2 in points:
            cv2.line(gray, (x1, y1), (x2, y2), 0, 1)
            lines.append(LineSegment(x1, y1, x2, y2))
    structure = model(gray, tuple(lines))
    assert structure.straight_lines == tuple(lines)
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "shaft.dxf").path
    )
    assert len(doc.modelspace().query("LINE")) == 10
    assert not doc.audit().has_errors
    assert np.all(render_final_structure_preview(structure)[87:98, 210:225] == 255)


def test_protected_source_ownership_vetoes_even_solid_duplicate_edges():
    gray = bar()
    protected = np.zeros_like(gray)
    protected[50, 80] = 255
    lines = (LineSegment(20, 47, 160, 47), LineSegment(20, 53, 160, 53))
    output, metadata = stroke_presentation(gray, lines, 300, protected_mask=protected)
    assert output == lines and not metadata["false_parallel_decisions"]


def test_dimension_and_frame_widths_remain_metadata_with_exact_table_nodes(tmp_path):
    gray = np.full((200, 240), 255, np.uint8)
    cv2.line(gray, (20, 20), (220, 20), 0, 5)
    cv2.line(gray, (20, 100), (220, 100), 0, 1)
    cv2.line(gray, (20, 20), (20, 100), 0, 1)
    lines = (
        LineSegment(20, 20, 220, 20),
        LineSegment(20, 100, 220, 100),
        LineSegment(20, 20, 20, 100),
    )
    structure = model(gray, lines)
    assert structure.straight_lines == lines
    records = structure.provenance["stroke_presentation"]["line_records"]
    assert records[0]["cad_lineweight"] > records[1]["cad_lineweight"]
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "table.dxf").path
    )
    actual = list(doc.modelspace().query("LINE"))
    assert actual[0].dxf.start == actual[2].dxf.start
    assert actual[1].dxf.start == actual[2].dxf.end


def test_stroke_mapping_uses_source_physical_scale_and_only_four_widths():
    small = model(bar(3), (LineSegment(20, 50, 160, 50),), 150)
    large = model(bar(7), (LineSegment(20, 50, 160, 50),), 300)
    assert (
        small.provenance["stroke_presentation"]["line_records"][0]["cad_lineweight"]
        == large.provenance["stroke_presentation"]["line_records"][0]["cad_lineweight"]
    )
    assert len(large.provenance["stroke_presentation"]["vocabulary"]) == 4


def test_thickness_preview_is_actual_dxf_metadata_and_cache_identity(tmp_path):
    gray = bar()
    structure = model(gray, (LineSegment(20, 50, 160, 50),))
    thin = replace(structure, provenance={})
    assert structure.structure_id != thin.structure_id
    assert (
        np.count_nonzero(render_final_structure_preview(structure) < 128)
        > np.count_nonzero(render_final_structure_preview(thin) < 128) * 3
    )
    result = RasterTraceResult(
        structure.contour_binary, {}, (), 128, 0, 0, final_structure=structure
    )
    save_trace_cache(tmp_path / "stroke.npz", result)
    reopened = load_trace_cache(tmp_path / "stroke.npz").final_structure
    assert reopened.structure_id == structure.structure_id
    exported = export_final_structure_dxf(reopened, tmp_path / "parity.dxf")
    assert np.array_equal(
        render_final_structure_preview(structure),
        render_emitted_dxf_preview(
            ezdxf.readfile(exported.path), tmp_path, gray.shape[::-1]
        ),
    )


def test_document_export_preserves_same_lineweight_model(tmp_path):
    gray = bar()
    structure = model(gray, (LineSegment(20, 50, 160, 50),))
    page = DocumentPage(1, None, (180, 100), final_structure=structure)
    doc = ezdxf.readfile(
        export_trace_document_streaming(
            [page], tmp_path / "doc.dxf", total_pages=1
        ).path
    )
    assert doc.modelspace().query("LINE")[0].dxf.lineweight == 50


def orientation_source():
    gray = np.full((320, 320), 255, np.uint8)
    cv2.circle(gray, (160, 160), 55, 0, 1)
    cv2.fillPoly(gray, [np.array([(160, 110), (151, 194), (176, 177)], np.int32)], 0)
    cv2.putText(gray, "N", (148, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
    return gray


def test_orientation_is_one_source_rgba_image_with_editable_object_operations(tmp_path):
    gray = orientation_source()
    objects = source_orientation_graphics(gray)
    assert len(objects) == 1
    obj = source_ink_region(objects[0], gray)
    structure = build_final_structure(
        source_size_px=gray.shape[::-1],
        contour_binary=np.full_like(gray, 255),
        contours=(),
        logos=(obj,),
    )
    result = export_final_structure_dxf(structure, tmp_path / "north.dxf")
    doc = ezdxf.readfile(result.path)
    image = doc.modelspace().query("IMAGE")[0]
    assert image.get_xdata("IMAGE_TO_CAD")[0].value == "GRAPHIC"
    assert len(list(doc.modelspace())) == 1
    asset = tmp_path / image.image_def.dxf.filename
    rgba = cv2.imdecode(np.fromfile(asset, np.uint8), cv2.IMREAD_UNCHANGED)
    assert rgba.shape[:2] == obj.mask.shape and np.any(rgba[:, :, 3] == 0)
    image.translate(5, 9, 0)
    image.scale_uniform(2)
    expected = image.dxf.insert
    doc.saveas(tmp_path / "edited.dxf")
    reopened = ezdxf.readfile(tmp_path / "edited.dxf")
    assert reopened.modelspace().query("IMAGE")[0].dxf.insert == expected
    assert not reopened.audit().has_errors
    reopened.modelspace().delete_entity(reopened.modelspace().query("IMAGE")[0])
    reopened.saveas(tmp_path / "deleted.dxf")
    assert not ezdxf.readfile(tmp_path / "deleted.dxf").modelspace().query("IMAGE")


def test_orientation_morphology_generalizes_translation_scale_and_rotation():
    gray = orientation_source()
    moved = cv2.warpAffine(
        gray, cv2.getRotationMatrix2D((160, 160), 36, 0.8), (400, 360), borderValue=255
    )
    assert len(source_orientation_graphics(moved)) == 1


def test_full_production_orientation_has_graphic_ownership_without_topology(tmp_path):
    structure = trace_image_optimized(
        orientation_source(), enable_ocr=False
    ).final_structure
    assert not structure.straight_lines and not structure.contours
    assert len(structure.logos) == 1
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "graphic.dxf").path
    )
    assert len(list(doc.modelspace())) == 1
    assert (
        doc.modelspace().query("IMAGE")[0].get_xdata("IMAGE_TO_CAD")[0].value
        == "GRAPHIC"
    )


@pytest.mark.parametrize("label", ["M", "SL", "2"])
def test_simple_circle_text_and_box_text_stay_editable(label):
    gray = np.full((320, 320), 255, np.uint8)
    cv2.circle(gray, (160, 160), 55, 0, 1)
    cv2.putText(gray, label, (145, 165), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
    assert not source_orientation_graphics(gray)
    cv2.rectangle(gray, (100, 100), (220, 220), 0, 1)
    assert not source_orientation_graphics(gray)


def test_connected_structural_context_vetoes_graphic_claim():
    gray = orientation_source()
    cv2.line(gray, (215, 160), (310, 160), 0, 1)
    assert not source_orientation_graphics(gray)


def test_real_w03_north_morphology_and_true_parallel_door_regression():
    here = Path(__file__).parent
    gray = load_image(
        here / "real_regression/assets/sources/warehouse-electrical-vector.pdf",
        page_index=2,
        pdf_dpi=110,
        grayscale=True,
    )
    objects = source_orientation_graphics(gray)
    assert len(objects) == 1
    x, y, w, h = objects[0].bbox
    assert x <= 3753 and y <= 164 and x + w >= 3876 and y + h >= 332
    fixture = json.loads((here / "fixtures/product-p1-source-lines.json").read_text())
    lines = tuple(
        LineSegment(
            **{
                **r,
                "source_ids": tuple(r["source_ids"]),
                "history": tuple(r["history"]),
                "classification_reasons": tuple(r["classification_reasons"]),
            }
        )
        for r in fixture["W03"]
    )
    assert stroke_presentation(gray, lines, 110)[0] == lines


def test_uniform_source_fill_emits_native_hatch_not_a_structural_centerline(tmp_path):
    gray = np.full((500, 600), 255, np.uint8)
    gray[30:46, 30:46] = 90
    path = TracePath(((30, 30), (45, 30), (45, 45), (30, 45)), None, 0, 0)
    fills = source_fill_records(gray, (path,))
    assert fills["0"]["source_gray"] == 90
    structure = build_final_structure(
        source_size_px=gray.shape[::-1],
        contour_binary=gray,
        contours=(path,),
        provenance={"stroke_presentation": {"fill_records": fills}},
    )
    doc = ezdxf.readfile(
        export_final_structure_dxf(structure, tmp_path / "fill.dxf").path
    )
    assert not doc.modelspace().query("LINE")
    hatch = doc.modelspace().query("HATCH")[0]
    assert hatch.rgb == (90, 90, 90) and not doc.audit().has_errors
    assert render_final_structure_preview(structure)[37, 37] == 90


def test_hatching_text_and_long_table_rules_are_not_promoted_to_uniform_fill():
    gray = np.full((500, 600), 255, np.uint8)
    path = TracePath(((30, 30), (45, 30), (45, 45), (30, 45)), None, 0, 0)
    gray[30:46:3, 30:46] = 0
    assert not source_fill_records(gray, (path,))
    gray[30:46, 30:46] = 0
    text = TextCandidate("unchanged", (30, 30, 16, 16), 0.9, "dimension_text_candidate")
    assert not source_fill_records(gray, (path,), (text,))
    rule = TracePath(((30, 30), (450, 30), (450, 35), (30, 35)), None, 0, 0)
    assert not source_fill_records(gray, (rule,))
