"""Artificial budget/visibility fixtures; real probes are labeled separately."""

from dataclasses import replace

import ezdxf
import numpy as np
import pypdfium2 as pdfium
import pytest

from app.core.cache import load_trace_cache, save_trace_cache
from app.core.image_loader import load_image
from app.core.processing import (
    ProductionProcessingConfig,
    build_processing_cache_key,
    cache_key_matches,
)
from app.core.structure import FinalStructure
from app.geometry import pdf_arc_evidence as evidence_module
from app.geometry.native_arc_replacement import apply_pdf_arc_evidence
from app.geometry.raster_trace import RasterTraceResult, trace_binary
from app.export.trace_single_export import export_final_structure_dxf


def _stroke(page, x=50, y=50):
    raw = pdfium.raw
    r, k = 32, 32 * 0.5522847498307936
    path = raw.FPDFPageObj_CreateNewPath(x + r, y)
    assert raw.FPDFPath_BezierTo(path, x + r, y + k, x + k, y + r, x, y + r)
    assert raw.FPDFPageObj_SetStrokeWidth(path, 1.5)
    assert raw.FPDFPageObj_SetStrokeColor(path, 0, 0, 0, 255)
    assert raw.FPDFPath_SetDrawMode(path, 0, 1)
    page.insert_obj(pdfium.PdfObject(path))


def _line(page):
    raw = pdfium.raw
    path = raw.FPDFPageObj_CreateNewPath(10, 12)
    assert raw.FPDFPath_LineTo(path, 200, 12)
    assert raw.FPDFPageObj_SetStrokeWidth(path, 1)
    assert raw.FPDFPageObj_SetStrokeColor(path, 0, 0, 0, 255)
    assert raw.FPDFPath_SetDrawMode(path, 0, 1)
    page.insert_obj(pdfium.PdfObject(path))


def _fixture(tmp_path, noise=0, before=True, two=False, tail=None):
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(220, 200)
    if before:
        _stroke(page)
    for _ in range(noise):
        _line(page)
    if not before:
        _stroke(page)
    if two:
        _stroke(page, 140, 115)
    if tail == "white":
        raw = pdfium.raw
        rect = raw.FPDFPageObj_CreateNewRect(45, 45, 43, 43)
        assert raw.FPDFPageObj_SetFillColor(rect, 255, 255, 255, 255)
        assert raw.FPDFPath_SetDrawMode(rect, 2, 0)
        page.insert_obj(pdfium.PdfObject(rect))
    elif tail == "branch":
        raw = pdfium.raw
        p = raw.FPDFPageObj_CreateNewPath(72.6, 72.6)
        assert raw.FPDFPath_LineTo(p, 115, 72.6)
        assert raw.FPDFPageObj_SetStrokeWidth(p, 2)
        assert raw.FPDFPageObj_SetStrokeColor(p, 0, 0, 0, 255)
        assert raw.FPDFPath_SetDrawMode(p, 0, 1)
        page.insert_obj(pdfium.PdfObject(p))
    file = tmp_path / "artificial-budget.pdf"
    page.gen_content()
    doc.save(file)
    page.close()
    doc.close()
    return file


def _load(file):
    sink = []
    image = load_image(file, pdf_dpi=72, grayscale=True, pdf_geometry_sink=sink)
    binary = np.where(image < 254, 0, 255).astype(np.uint8)
    return (
        image,
        sink[0],
        FinalStructure(image.shape[::-1], binary, tuple(trace_binary(binary))),
    )


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


def _key(binding):
    # Required existing cache-contract dummy value; no source fingerprinting.
    return build_processing_cache_key(
        input_content_sha256="a" * 64,
        page_index=0,
        config=ProductionProcessingConfig(source_dpi=72, enable_ocr=False),
        pdf_geometry_binding=binding,
    )


def test_candidates_on_both_sides_of_old_limit_with_many_non_candidates(tmp_path):
    image, ev, base = _load(_fixture(tmp_path, noise=4200, two=True))
    assert [c.source.object_index for c in ev.candidates] == [0, 4201]
    counts = ev.analysis["counts"]
    assert counts["objects_visited"] == 4202 and counts["geometry_checks"] == 2
    assert counts["local_renders"] == counts["visibility_checks"] == 2
    assert ev.analysis["traversal_complete"] and ev.analysis["review_complete"]
    assert np.array_equal(
        image,
        load_image(tmp_path / "artificial-budget.pdf", pdf_dpi=72, grayscale=True),
    )
    first = apply_pdf_arc_evidence(base, image, ev)
    reverse = apply_pdf_arc_evidence(
        base, image, replace(ev, candidates=tuple(reversed(ev.candidates)))
    )
    assert first.arcs == reverse.arcs and first.contours == reverse.contours
    assert apply_pdf_arc_evidence(first, image, ev) is first


@pytest.mark.parametrize("before", [True, False])
def test_late_white_fill_is_seen_across_old_limit(tmp_path, before):
    image, ev, base = _load(_fixture(tmp_path, noise=4200, before=before, tail="white"))
    assert ev.candidates == ()
    assert any(
        r["reason"] == "VISIBLE_STROKE_OCCLUDED_OR_CHANGED" for r in ev.rejections
    )
    assert ev.analysis["counts"]["visibility_checks"] == 1
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    assert np.array_equal(final.contour_binary, base.contour_binary)


def test_late_independent_branch_keeps_entire_mixed_member(tmp_path):
    image, ev, base = _load(_fixture(tmp_path, noise=4200, tail="branch"))
    assert len(ev.candidates) == 1
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    assert np.array_equal(final.contour_binary, base.contour_binary)
    assert final.observations[-1]["decisions"][-1]["reason"] in {
        "MIXED_MEMBER_EXTENT",
        "FOREIGN_MEMBER_INK",
    }
    assert final.observations[-1]["decisions"][-1]["category"] == "membership"


def test_incomplete_traversal_never_isolates_a_prefix(tmp_path, monkeypatch):
    file = _fixture(tmp_path, noise=50, tail="white")
    monkeypatch.setattr(evidence_module, "MAX_PAGE_OBJECTS", 32)
    image, ev, base = _load(file)
    assert ev.candidates == () and not ev.analysis["traversal_complete"]
    assert ev.analysis["counts"]["objects_visited"] == 33
    assert (
        ev.analysis["counts"]["geometry_checks"]
        == ev.analysis["counts"]["local_renders"]
        == 0
    )
    assert ev.rejections[0]["reason"] == "PAGE_TRAVERSAL_OBJECT_BUDGET"
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.contours == base.contours and final.arcs == ()


@pytest.mark.parametrize(
    "limit,reason",
    [
        ("MAX_SUPPORT_CHECKS", "SUPPORT_CHECK_BUDGET"),
        ("MAX_GEOMETRY_CHECKS", "GEOMETRY_CHECK_BUDGET"),
        ("MAX_ARCS", "ARC_PROPOSAL_BUDGET"),
        ("MAX_LOCAL_RENDERS", "LOCAL_RENDER_BUDGET"),
        ("MAX_LOCAL_PIXELS", "LOCAL_PIXEL_BUDGET"),
        ("MAX_TOTAL_LOCAL_PIXELS", "LOCAL_PIXEL_BUDGET"),
    ],
)
def test_candidate_budget_is_unassessed_and_preserves_old_members(
    tmp_path, monkeypatch, limit, reason
):
    file = _fixture(tmp_path)
    monkeypatch.setattr(evidence_module, limit, 0)
    image, ev, base = _load(file)
    assert ev.candidates == () and ev.analysis["traversal_complete"]
    row = next(r for r in ev.rejections if r["reason"] == reason)
    assert row["decision"] == "NOT_EVALUATED" and row["category"] == "resource"
    assert not ev.analysis["review_complete"]
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    assert np.array_equal(final.contour_binary, base.contour_binary)


def test_long_path_skips_segment_walk_but_remains_visibility_context(tmp_path):
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(220, 200)
    _stroke(page)
    raw = pdfium.raw
    p = raw.FPDFPageObj_CreateNewPath(10, 12)
    for i in range(300):
        assert raw.FPDFPath_LineTo(p, 10 + (i % 190), 10 + (i % 3))
    assert raw.FPDFPageObj_SetStrokeWidth(p, 1)
    assert raw.FPDFPageObj_SetStrokeColor(p, 0, 0, 0, 255)
    assert raw.FPDFPath_SetDrawMode(p, 0, 1)
    page.insert_obj(pdfium.PdfObject(p))
    page.gen_content()
    file = tmp_path / "artificial-long-path.pdf"
    doc.save(file)
    page.close()
    doc.close()
    image, ev, base = _load(file)
    assert len(ev.candidates) == 1 and ev.analysis["traversal_complete"]
    assert any(
        r["reason"] == "PATH_SEGMENT_BUDGET" and r["category"] == "resource"
        for r in ev.rejections
    )
    final = apply_pdf_arc_evidence(base, image, ev)
    assert len(final.arcs) == 1 and len(final.contours) == len(base.contours) - 1
    assert np.array_equal(image, load_image(file, pdf_dpi=72, grayscale=True))


def test_deep_form_context_fails_closed(tmp_path, monkeypatch):
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(220, 200)
    _stroke(page)
    page.gen_content()
    page.close()
    for _ in range(3):
        dest = pdfium.PdfDocument.new()
        page = dest.new_page(220, 200)
        xobject = doc.page_as_xobject(0, dest)
        page.insert_obj(xobject.as_pageobject())
        page.gen_content()
        page.close()
        xobject.close()
        doc.close()
        doc = dest
    file = tmp_path / "artificial-deep-form.pdf"
    doc.save(file)
    doc.close()
    monkeypatch.setattr(evidence_module, "MAX_FORM_DEPTH", 2)
    image, ev, base = _load(file)
    assert ev.candidates == () and not ev.analysis["traversal_complete"]
    assert any(r["reason"] == "FORM_DEPTH_BUDGET" for r in ev.rejections)
    assert ev.analysis["counts"]["local_renders"] == 0
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours


def test_work_selection_and_partial_coverage_are_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_module, "MAX_GEOMETRY_CHECKS", 1)
    records = [{"object_index": i} for i in [12, 4, 8]]
    assert evidence_module._geometry_work(records) == evidence_module._geometry_work(
        records[::-1]
    )
    image, ev, base = _load(_fixture(tmp_path, two=True))
    assert [c.source.object_index for c in ev.candidates] == [0]
    assert any(
        r["object_index"] == 1 and r["reason"] == "GEOMETRY_CHECK_BUDGET"
        for r in ev.rejections
    )
    final = apply_pdf_arc_evidence(base, image, ev)
    assert len(final.arcs) == 1 and len(final.contours) == len(base.contours) - 1
    assert apply_pdf_arc_evidence(final, image, ev) is final


def test_deadline_keeps_completed_candidate_but_cache_is_not_complete(
    tmp_path, monkeypatch
):
    file = _fixture(tmp_path, two=True)
    clock = [0.0]
    local_calls = [0]
    original = pdfium.PdfPage.render
    monkeypatch.setattr(evidence_module, "perf_counter", lambda: clock[0])

    def render(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if kwargs.get("crop"):
            local_calls[0] += 1
            if local_calls[0] == 2:
                clock[0] = 10.0
        return result

    monkeypatch.setattr(pdfium.PdfPage, "render", render)
    image, ev, base = _load(file)
    assert len(ev.candidates) == 1 and ev.analysis["traversal_complete"]
    assert ev.analysis["cache_reusable"] is False and not ev.analysis["review_complete"]
    final = apply_pdf_arc_evidence(base, image, ev)
    assert len(final.arcs) == 1 and len(final.contours) == len(base.contours) - 1
    key = _key(ev.binding)
    stored = load_trace_cache(
        save_trace_cache(
            tmp_path / "partial.npz", _trace(final), cache_key=key.payload()
        )
    )
    assert stored.cache_key is None and not cache_key_matches(stored.cache_key, key)
    assert stored.arcs == final.arcs and stored.paths == final.contours
    export_final_structure_dxf(stored.final_structure, tmp_path / "partial.dxf")
    assert len(ezdxf.readfile(tmp_path / "partial.dxf").modelspace().query("ARC")) == 1
    assert np.array_equal(image, load_image(file, pdf_dpi=72, grayscale=True))


def test_policy_budget_change_invalidates_old_empty_cache_identity(monkeypatch):
    binding = evidence_module.pdf_geometry_binding("artificial.pdf", 0, 72)
    old = dict(binding, policy="pdf-simple-arc-evidence-v1")
    old.pop("budgets")
    assert _key(binding) != _key(old)
    monkeypatch.setattr(evidence_module, "MAX_GEOMETRY_CHECKS", 65)
    assert _key(binding) != _key(
        evidence_module.pdf_geometry_binding("artificial.pdf", 0, 72)
    )


@pytest.mark.parametrize("tail", [None, "white"])
def test_proposal_budget_keeps_only_complete_proofs_with_full_late_context(
    tmp_path, monkeypatch, tail
):
    monkeypatch.setattr(evidence_module, "MAX_ARCS", 1)
    image, ev, base = _load(_fixture(tmp_path, two=True, tail=tail))
    assert ev.analysis["counts"]["geometry_checks"] == 1
    assert any(
        r["reason"] == "ARC_PROPOSAL_BUDGET" and r["object_index"] == 1
        for r in ev.rejections
    )
    assert len(ev.candidates) == (1 if tail is None else 0)
    final = apply_pdf_arc_evidence(base, image, ev)
    assert len(final.arcs) == (1 if tail is None else 0)
    assert len(final.contours) == len(base.contours) - len(final.arcs)


@pytest.mark.parametrize("failure", ["none", "deadline", "state-write"])
def test_live_page_states_are_restored_even_on_interruption(
    tmp_path, monkeypatch, failure
):
    file = _fixture(tmp_path, noise=12, two=True, tail="branch")
    clock = [0.0]
    render_calls = [0]
    monkeypatch.setattr(evidence_module, "perf_counter", lambda: clock[0])
    original_render, original_set = (
        pdfium.PdfPage.render,
        pdfium.raw.FPDFPageObj_SetIsActive,
    )

    def render(self, *args, **kw):
        bitmap = original_render(self, *args, **kw)
        if kw.get("crop"):
            render_calls[0] += 1
            if failure == "deadline" and render_calls[0] == 2:
                clock[0] = 10.0
        return bitmap

    failed = [False]

    def set_state(obj, value):
        result = original_set(obj, value)
        if failure == "state-write" and value == 0 and not failed[0]:
            failed[0] = True
            return 0
        return result

    monkeypatch.setattr(pdfium.PdfPage, "render", render)
    monkeypatch.setattr(pdfium.raw, "FPDFPageObj_SetIsActive", set_state)
    doc = pdfium.PdfDocument(str(file))
    page = doc[0]
    bitmap = page.render(scale=1, grayscale=True)
    try:
        before = np.array(bitmap.to_pil().convert("L"))
        ev = evidence_module.extract_pdf_arc_evidence(
            file, 0, page, bitmap, before, 1, 72
        )
        after_bitmap = page.render(scale=1, grayscale=True)
        try:
            assert np.array_equal(before, np.array(after_bitmap.to_pil().convert("L")))
        finally:
            after_bitmap.close()
        if failure == "state-write":
            assert ev.candidates == () and ev.analysis["cache_reusable"] is False
            assert any(
                r["reason"] == "VISIBILITY_ISOLATION_UNAVAILABLE" for r in ev.rejections
            )
    finally:
        bitmap.close()
        page.close()
        doc.close()


def test_traversal_timeout_is_not_a_complete_empty_result(tmp_path, monkeypatch):
    file = _fixture(tmp_path, noise=10)
    monkeypatch.setattr(evidence_module, "MAX_EVIDENCE_SECONDS", 0.0)
    image, ev, base = _load(file)
    assert not ev.analysis["traversal_complete"] and not ev.analysis["cache_reusable"]
    assert ev.candidates == () and ev.analysis["counts"]["local_renders"] == 0
    final = apply_pdf_arc_evidence(base, image, ev)
    assert final.arcs == () and final.contours == base.contours
    stored = load_trace_cache(
        save_trace_cache(
            tmp_path / "timed-out.npz",
            _trace(final),
            cache_key=_key(ev.binding).payload(),
        )
    )
    assert stored.cache_key is None and stored.paths == base.contours
