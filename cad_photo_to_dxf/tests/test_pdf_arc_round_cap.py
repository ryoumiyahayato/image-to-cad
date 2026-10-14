"""Artificial round-cap/mapping contracts; not real-source repair evidence."""

from dataclasses import replace

import cv2
import ezdxf
import numpy as np
import pypdfium2 as pdfium
import pytest

from app.core.arc_types import ArcSegment
from app.core.cache import load_trace_cache, save_trace_cache
from app.core.image_loader import load_image
from app.core.preview import render_emitted_dxf_preview
from app.core.processing import ProductionProcessingConfig, build_processing_cache_key
from app.core.scale_calibrator import ScaleCalibration
from app.core.structure import FinalStructure
from app.geometry import pdf_arc_evidence as module
from app.geometry.line_detect import LineSegment
from app.geometry.native_arc_replacement import apply_pdf_arc_evidence
from app.geometry.raster_trace import RasterTraceResult, trace_binary
from app.export.trace_single_export import export_final_structure_dxf
from app.export.document_export import DocumentPage
from app.export.trace_document_export import export_trace_document_streaming


def _page(
    tmp_path, *, size=(160.0, 160.0), cap=1, transform=None, tail=None, rotation=0
):
    raw = pdfium.raw
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(*size)
    p = raw.FPDFPageObj_CreateNewPath(82, 50)
    k = 32 * 0.5522847498307936
    assert raw.FPDFPath_BezierTo(p, 82, 50 + k, 50 + k, 82, 50, 82)
    assert raw.FPDFPageObj_SetStrokeWidth(p, 1.5)
    assert raw.FPDFPageObj_SetStrokeColor(p, 0, 0, 0, 255)
    assert raw.FPDFPageObj_SetLineCap(p, cap)
    assert raw.FPDFPath_SetDrawMode(p, 0, 1)
    if transform:
        raw.FPDFPageObj_Transform(p, *transform)
    page.insert_obj(pdfium.PdfObject(p))
    if tail == "shared":
        q = raw.FPDFPageObj_CreateNewPath(82, 50)
        assert raw.FPDFPath_LineTo(q, 105, 50)
        assert raw.FPDFPageObj_SetStrokeWidth(q, 1)
        assert raw.FPDFPageObj_SetStrokeColor(q, 0, 0, 0, 255)
        assert raw.FPDFPath_SetDrawMode(q, 0, 1)
        page.insert_obj(pdfium.PdfObject(q))
    elif tail == "white":
        q = raw.FPDFPageObj_CreateNewRect(77, 45, 10, 12)
        assert raw.FPDFPageObj_SetFillColor(q, 255, 255, 255, 255)
        assert raw.FPDFPath_SetDrawMode(q, 2, 0)
        page.insert_obj(pdfium.PdfObject(q))
    page.set_rotation(rotation)
    page.gen_content()
    file = tmp_path / "round-contract.pdf"
    doc.save(file)
    page.close()
    doc.close()
    return file


def _load(file, dpi=72):
    sink = []
    image = load_image(file, pdf_dpi=dpi, grayscale=True, pdf_geometry_sink=sink)
    binary = np.where(image < 254, 0, 255).astype(np.uint8)
    base = FinalStructure(
        image.shape[::-1], binary, tuple(trace_binary(binary)), preview_binary=binary
    )
    return image, sink[0], base


def _trace(s):
    return RasterTraceResult(
        s.contour_binary,
        {},
        s.contours,
        s.threshold,
        int((s.contour_binary < 128).sum()),
        sum(len(p.points) for p in s.contours),
        final_structure=s,
        arcs=s.arcs,
    )


def test_isolated_round_cap_formal_replacement_save_export_and_display(tmp_path):
    image, ev, base = _load(_page(tmp_path))
    cv2.imwrite(str(tmp_path / "source.png"), image)
    export_final_structure_dxf(base, tmp_path / "before.dxf")
    (c,) = ev.candidates
    assert (
        c.stroke_cap == "round"
        and c.numeric_evidence["round_caps"]["other_cap_ink_pixels"] == 0
    )
    assert ev.analysis["counts"]["local_renders"] == 2
    final = apply_pdf_arc_evidence(base, image, ev)
    (a,) = final.arcs
    assert a.stroke_cap == "round" and final.contours == ()
    assert np.all(final.contour_binary == 255)
    assert a.lineweight == 53 and a.round_stroke_error_px() < 0.5
    assert apply_pdf_arc_evidence(final, image, ev) is final
    stored = load_trace_cache(save_trace_cache(tmp_path / "round.npz", _trace(final)))
    assert stored.final_structure.structure_id == final.structure_id
    assert stored.arcs == final.arcs
    output = export_final_structure_dxf(stored.final_structure, tmp_path / "round.dxf")
    doc = ezdxf.readfile(output.path)
    (entity,) = doc.modelspace().query("ARC")
    assert len(doc.modelspace()) == 1 and entity.dxf.lineweight == a.lineweight
    tags = entity.get_xdata("P9_ARC")
    assert tags[3].value == "round"
    assert tags[4].value == pytest.approx(25.4 / a.source_dpi)
    preview = render_emitted_dxf_preview(doc, tmp_path, final.source_size_px)
    cv2.imwrite(str(tmp_path / "saved-dxf-preview.png"), preview)
    x0, y0, x1, y1 = c.box
    local = preview[y0:y1, x0:x1]
    assert np.any((local < 254) & c.cap_neighborhood())
    entity.set_xdata("P9_ARC", list(tags[:3]))
    butt_preview = render_emitted_dxf_preview(doc, tmp_path, final.source_size_px)
    entity.set_xdata("P9_ARC", list(tags))
    assert np.any((local < butt_preview[y0:y1, x0:x1]) & c.cap_neighborhood())
    # Check the actual round ends beyond the centerline, not just its midpoint.
    for x, y in (a.point_at(0), a.point_at(1)):
        assert (
            preview[round(y) - 1 : round(y) + 2, round(x) - 1 : round(x) + 2].min()
            < 128
        )
    assert not doc.audit().has_errors
    entity.dxf.radius += 0.25
    doc.saveas(tmp_path / "round-edited.dxf")
    (edited,) = ezdxf.readfile(tmp_path / "round-edited.dxf").modelspace().query("ARC")
    assert edited.dxf.radius == pytest.approx(a.radius + 0.25)


@pytest.mark.parametrize(
    "tail,reason",
    [
        ("shared", "ROUND_CAP_SHARED_SOURCE_INK"),
        ("white", "VISIBLE_STROKE_OCCLUDED_OR_CHANGED"),
    ],
)
def test_shared_or_occluded_round_cap_keeps_old_members(tmp_path, tail, reason):
    file = _page(tmp_path, tail=tail)
    image, ev, base = _load(file)
    assert not ev.candidates
    assert any(r["reason"] == reason for r in ev.rejections)
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    assert np.array_equal(final.contour_binary, base.contour_binary)
    assert np.array_equal(image, load_image(file, pdf_dpi=72, grayscale=True))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_verified_integer_canvas_uses_actual_final_curve_not_mean_scale(
    tmp_path, rotation
):
    image, ev, base = _load(
        _page(tmp_path, size=(160.15, 160.16), rotation=rotation), 240
    )
    assert ev.analysis["mapping"]["integer_canvas_verified"]
    (c,) = ev.candidates
    assert c.numeric_evidence["transform"]["mapping_basis"].startswith(
        "verified integer canvas"
    )
    assert (
        c.numeric_evidence["radial_upper_bound_px"]
        <= c.numeric_evidence["tolerance_px"]
    )
    assert c.numeric_evidence["endpoint_displacement_px"] < 0.01
    final = apply_pdf_arc_evidence(base, image, ev)
    assert len(final.arcs) == 1, final.observations[-1]
    (a,) = final.arcs
    assert np.linalg.norm(np.asarray(a.point_at(0)) - c.pixel_points[0]) < 0.01
    assert np.linalg.norm(np.asarray(a.point_at(1)) - c.pixel_points[3]) < 0.01


@pytest.mark.parametrize("transform", [(1.02, 0, 0, 1, 0, 0), (1, 0, 0.01, 1, 0, 0)])
def test_true_native_anisotropy_or_shear_stays_rejected(tmp_path, transform):
    image, ev, base = _load(_page(tmp_path, transform=transform))
    assert ev.candidates == ()
    assert any(r["reason"] == "ANISOTROPIC_PATH_TRANSFORM" for r in ev.rejections)
    assert ev.analysis["counts"]["geometry_checks"] == 0
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.contours == base.contours and final.arcs == ()


def test_integer_canvas_permission_still_rejects_excessive_final_error(tmp_path):
    _, ev, _ = _load(_page(tmp_path, size=(160.01, 160.99)), dpi=72)
    assert ev.analysis["mapping"]["integer_canvas_verified"]
    assert ev.candidates == ()
    assert ev.analysis["counts"]["geometry_checks"] == 1
    assert ev.rejections[0]["reason"] in (
        "ENDPOINT_RADII_OR_SCALE",
        "NONCIRCULAR_CUBIC",
    )


def test_untracked_canvas_is_not_an_anisotropy_exception():
    inverse = np.diag([1.001, -1.002])
    assert not module._bitmap_rounding_mapping((160, 160), (161, 161), 1, inverse)[
        "integer_canvas_verified"
    ]


def test_round_mirror_preserves_locus_and_reverses_traversal(tmp_path):
    image, ev, base = _load(_page(tmp_path, transform=(-1, 0, 0, 1, 160, 0)))
    final = apply_pdf_arc_evidence(base, image, ev)
    (a,) = final.arcs
    assert a.center == pytest.approx((110, 110))
    assert a.sweep_angle_deg == pytest.approx(-90)
    assert a.point_at(0) == pytest.approx((78, 110))
    assert a.point_at(1) == pytest.approx((110, 78))
    output = export_final_structure_dxf(final, tmp_path / "mirrored.dxf")
    (e,) = ezdxf.readfile(output.path).modelspace().query("ARC")
    assert e.dxf.start_angle == pytest.approx(90)
    assert e.dxf.end_angle == pytest.approx(180)


def test_known_local_translation_keeps_round_context_and_proof(tmp_path):
    image, ev, _ = _load(_page(tmp_path))
    local = image[30:145, 20:140]
    binary = np.where(local < 254, 0, 255).astype(np.uint8)
    base = FinalStructure(
        local.shape[::-1], binary, tuple(trace_binary(binary)), preview_binary=binary
    )
    cropped = ev.for_crop((20, 30, 140, 145))
    final = apply_pdf_arc_evidence(base, local, cropped)
    (a,) = final.arcs
    assert a.stroke_cap == "round" and a.center == pytest.approx((30, 80))
    assert final.contours == ()


def test_round_cap_requires_context_and_exportable_stroke(tmp_path):
    _, ev, _ = _load(_page(tmp_path))
    (c,) = ev.candidates
    with pytest.raises(ValueError, match="CONTEXT"):
        replace(c, other_gray=None)
    with pytest.raises(ValueError, match="DISPLAY_ERROR"):
        replace(c.accepted_member((), "contract"), lineweight=211)
    with pytest.raises(ValueError, match="mapped stroke"):
        replace(c.accepted_member((), "contract"), stroke_width_bounds_px=None)


def test_round_arc_actual_paper_scale_and_document_export(tmp_path):
    image, ev, base = _load(_page(tmp_path))
    final = apply_pdf_arc_evidence(base, image, ev)
    scale = 25.4 / 72
    calibration = ScaleCalibration((0, 0), (100, 0), 100 * scale)
    single = export_final_structure_dxf(final, tmp_path / "paper.dxf", calibration)
    page = DocumentPage(1, None, (160 * scale, 160 * scale), final_structure=final)
    document = export_trace_document_streaming(
        (page,), tmp_path / "document.dxf", total_pages=1
    )
    for path in (single.path, document.path):
        (e,) = ezdxf.readfile(path).modelspace().query("ARC")
        assert e.dxf.radius == pytest.approx(32 * scale)
        assert e.get_xdata("P9_ARC")[4].value == pytest.approx(scale)
    with pytest.raises(ValueError, match="DISPLAY_ERROR"):
        export_final_structure_dxf(
            final,
            tmp_path / "unsafe-scale.dxf",
            ScaleCalibration((0, 0), (100, 0), 1000),
        )
    assert not (tmp_path / "unsafe-scale.dxf").exists()


def test_round_cap_foreground_claim_and_retained_line_veto(tmp_path):
    image, ev, base = _load(_page(tmp_path))
    (c,) = ev.candidates
    x0, y0, x1, y1 = c.box
    cap = c.cap_neighborhood() & (base.contour_binary[y0:y1, x0:x1] < 128)
    yy, xx = np.nonzero(cap)
    binary = base.contour_binary.copy()
    binary[y0 + yy[0], x0 + xx[0]] = 255
    disputed = replace(base, contour_binary=binary)
    final = apply_pdf_arc_evidence(disputed, image, ev)
    assert final.arcs == () and final.contours == disputed.contours
    assert (
        final.observations[-1]["decisions"][-1]["reason"]
        == "ROUND_CAP_SOURCE_NOT_OWNED"
    )
    line = LineSegment(82, 110, 110, 110)
    shared = replace(base, straight_lines=(line,))
    final = apply_pdf_arc_evidence(shared, image, ev)
    assert (
        final.arcs == ()
        and final.straight_lines == (line,)
        and final.contours == shared.contours
    )
    assert (
        final.observations[-1]["decisions"][-1]["reason"]
        == "ROUND_CAP_SHARED_LINE_CLAIM"
    )


def test_round_context_render_counts_against_existing_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_LOCAL_RENDERS", 1)
    image, ev, base = _load(_page(tmp_path))
    assert ev.candidates == () and ev.analysis["counts"]["local_renders"] == 0
    assert ev.rejections[0]["reason"] == "LOCAL_RENDER_BUDGET"
    assert ev.rejections[0]["decision"] == "NOT_EVALUATED"
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.contours == base.contours and final.arcs == ()


@pytest.mark.parametrize("failure", ["deadline", "state-write"])
def test_round_context_interruption_restores_source_and_keeps_old_members(
    tmp_path, monkeypatch, failure
):
    file = _page(tmp_path)
    clock = [0.0]
    calls = [0]
    original_render, original_set = (
        pdfium.PdfPage.render,
        pdfium.raw.FPDFPageObj_SetIsActive,
    )
    monkeypatch.setattr(module, "perf_counter", lambda: clock[0])

    def render(self, *args, **kwargs):
        bitmap = original_render(self, *args, **kwargs)
        if kwargs.get("crop"):
            calls[0] += 1
            if calls[0] == 2 and failure == "deadline":
                clock[0] = 10.0
        return bitmap

    failed = [False]

    def set_active(obj, value):
        result = original_set(obj, value)
        if calls[0] == 2 and not failed[0] and failure == "state-write":
            failed[0] = True
            return 0
        return result

    monkeypatch.setattr(pdfium.PdfPage, "render", render)
    monkeypatch.setattr(pdfium.raw, "FPDFPageObj_SetIsActive", set_active)
    image, ev, base = _load(file)
    assert ev.candidates == () and not ev.analysis["cache_reusable"]
    if failure == "deadline":
        assert any(
            r["object_index"] == 0
            and r["reason"] == "VISIBILITY_NOT_EVALUATED"
            and r["decision"] == "NOT_EVALUATED"
            for r in ev.rejections
            if "object_index" in r
        )
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    assert np.array_equal(final.contour_binary, base.contour_binary)
    assert np.array_equal(image, load_image(file, pdf_dpi=72, grayscale=True))


def test_round_policy_invalidates_previous_cap_rejection_and_butt_payload_stays_compatible():
    args = dict(
        input_content_sha256="a" * 64, page_index=0, config=ProductionProcessingConfig()
    )
    current = module.pdf_geometry_binding("contract.pdf", 0, 240)
    old = dict(current, policy="pdf-simple-arc-evidence-v2-layered")
    assert build_processing_cache_key(
        **args, pdf_geometry_binding=current
    ) != build_processing_cache_key(**args, pdf_geometry_binding=old)
    a = ArcSegment("old-arc", (80, 80), 32, 0, 90)
    assert "stroke_cap" not in a.payload()
    assert ArcSegment.from_payload(a.payload()) == a
