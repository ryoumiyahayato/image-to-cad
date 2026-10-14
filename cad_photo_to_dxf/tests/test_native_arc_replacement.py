"""Artificial PDF contract/transaction fixtures and named real negative probes."""

from dataclasses import replace

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytest

from app.core.image_loader import load_image
from app.core.structure import FinalStructure
from app.core.trace_types import TracePath
from app.geometry.line_detect import LineSegment
from app.geometry.native_arc_replacement import (
    apply_pdf_arc_evidence,
    commit_arc_replacement,
    plan_arc_replacement,
)
from app.geometry.pdf_arc_evidence import fit_cubic_arc
from app.geometry.raster_trace import trace_binary


@pytest.fixture
def contract_page(tmp_path):
    doc = pdfium.PdfDocument.new()
    page = doc.new_page(160, 160)
    raw = pdfium.raw
    path = raw.FPDFPageObj_CreateNewPath(82, 50)
    k = 32 * 0.5522847498307936
    assert raw.FPDFPath_BezierTo(path, 82, 50 + k, 50 + k, 82, 50, 82)
    assert raw.FPDFPageObj_SetStrokeWidth(path, 1.5)
    assert raw.FPDFPageObj_SetStrokeColor(path, 0, 0, 0, 255)
    assert raw.FPDFPath_SetDrawMode(path, 0, 1)
    page.insert_obj(pdfium.PdfObject(path))
    page.gen_content()
    file = tmp_path / "artificial-contract.pdf"
    doc.save(file)
    page.close()
    doc.close()
    context = []
    image = load_image(file, pdf_dpi=72, grayscale=True, pdf_geometry_sink=context)
    assert len(context[0].candidates) == 1, context[0].rejections
    binary = np.where(image < 254, 0, 255).astype(np.uint8)
    contours = tuple(trace_binary(binary))
    assert len(contours) == 1
    return image, context[0], FinalStructure((160, 160), binary, contours)


def test_atomic_replacement_and_repeat(contract_page):
    image, evidence, base = contract_page
    (candidate,) = evidence.candidates
    plan = plan_arc_replacement(base, candidate)
    final = commit_arc_replacement(base, plan)
    assert len(base.contours) == 1 and base.arcs == ()
    assert final.contours == () and len(final.arcs) == 1
    assert not np.any(final.contour_binary == 0)
    assert commit_arc_replacement(final, plan) is final
    first = apply_pdf_arc_evidence(base, image, evidence)
    assert apply_pdf_arc_evidence(first, image, evidence) is first


def test_nonwhite_antialias_pixels_do_not_become_foreign_ink(contract_page):
    image, evidence, base = contract_page
    binary = np.where(image < 255, 0, 255).astype(np.uint8)
    full_foreground = replace(
        base, contour_binary=binary, contours=tuple(trace_binary(binary))
    )
    (candidate,) = evidence.candidates
    assert np.any(candidate.native_gray == 254), "fixture must exercise gray 254"
    final = apply_pdf_arc_evidence(full_foreground, image, evidence)
    assert len(final.arcs) == 1 and final.contours == ()
    assert not np.any(final.contour_binary == 0)


def test_upstream_foreground_claim_and_uncommitted_arc_fail_closed(contract_page):
    image, evidence, base = contract_page
    (candidate,) = evidence.candidates
    x0, y0, x1, y1 = candidate.box
    yy, xx = np.nonzero(candidate.native_gray < 64)
    middle = len(xx) // 2
    binary = base.contour_binary.copy()
    binary[y0 + yy[middle], x0 + xx[middle]] = 255
    disputed = replace(base, contour_binary=binary, preview_binary=base.contour_binary)
    final = apply_pdf_arc_evidence(disputed, image, evidence)
    assert final.arcs == () and final.contours == disputed.contours
    assert (
        final.observations[-1]["decisions"][-1]["reason"]
        == "INTERIOR_STROKE_ALREADY_CLAIMED"
    )
    uncommitted = replace(
        base, arcs=(candidate.accepted_member((), "artificial uncommitted member"),)
    )
    final = apply_pdf_arc_evidence(uncommitted, image, evidence)
    assert final.arcs == uncommitted.arcs and final.contours == base.contours
    assert (
        final.observations[-1]["decisions"][-1]["reason"] == "ARC_ID_ALREADY_OCCUPIED"
    )


def test_partial_member_and_missing_member_keep_original(contract_page):
    image, evidence, base = contract_page
    (candidate,) = evidence.candidates
    plan = plan_arc_replacement(base, candidate)
    with pytest.raises(ValueError, match="MEMBER"):
        commit_arc_replacement(replace(base, contours=()), plan)
    # A branch belongs to the same root contour. It cannot be dropped with ARC.
    binary = base.contour_binary.copy()
    cv2.line(binary, (73, 87), (130, 87), 0, 2)
    mixed = replace(base, contour_binary=binary, contours=tuple(trace_binary(binary)))
    final = apply_pdf_arc_evidence(mixed, image, evidence)
    assert final.arcs == ()
    assert final.contours == mixed.contours
    assert np.array_equal(final.contour_binary, mixed.contour_binary)


def test_protection_and_stale_render_keep_all_members(contract_page):
    image, evidence, base = contract_page
    protected = np.zeros_like(image)
    protected[base.contour_binary == 0] = 255
    s = replace(base, editable_text_source_mask=protected)
    final = apply_pdf_arc_evidence(s, image, evidence)
    assert final.arcs == () and final.contours == s.contours
    assert final.observations[-1]["decisions"][-1]["reason"] == "TEXT_SOURCE_PROTECTION"
    changed = image.copy()
    c = evidence.candidates[0]
    changed[c.box[1], c.box[0]] = 0
    final = apply_pdf_arc_evidence(base, changed, evidence)
    assert final.arcs == () and final.contours == base.contours
    assert final.observations[-1]["decisions"][-1]["reason"] == "STALE_RENDER_EVIDENCE"


def test_independent_line_and_hierarchy_rebinding(contract_page):
    image, evidence, base = contract_page
    other = TracePath(((120, 110), (145, 110), (145, 140), (120, 140)), None, 0, 1)
    hole = TracePath(((128, 120), (135, 120), (135, 130), (128, 130)), 1, 1, 1)
    line = LineSegment(120, 25, 145, 25, source_ids=("contract:independent",))
    s = replace(base, contours=(*base.contours, other, hole), straight_lines=(line,))
    final = apply_pdf_arc_evidence(s, image, evidence)
    assert len(final.arcs) == 1
    assert final.straight_lines == (line,)
    assert final.contours[0].points == other.points
    assert final.contours[1].points == hole.points
    assert final.contours[1].parent == final.contours[1].root == 0
    # Reversed member order still replaces only the matching geometry.
    reverse = replace(
        base, contours=(replace(other, root=0), replace(base.contours[0], root=1))
    )
    output = apply_pdf_arc_evidence(reverse, image, evidence)
    assert output.arcs[0].center == final.arcs[0].center
    assert output.contours[0].points == other.points


def test_duplicate_id_conflict_and_interior_line_claim(contract_page):
    image, evidence, base = contract_page
    (candidate,) = evidence.candidates
    plan = plan_arc_replacement(base, candidate)
    s = replace(base, arcs=(replace(plan.arc, radius=31),))
    with pytest.raises(ValueError, match="OCCUPIED"):
        commit_arc_replacement(s, plan)
    line = LineSegment(69, 81, 75, 88, width=2)
    s = replace(base, straight_lines=(line,))
    final = apply_pdf_arc_evidence(s, image, evidence)
    assert final.arcs == () and final.straight_lines == (line,)
    assert final.contours == s.contours


def test_nonuniform_shape_and_real_southern_cubic_are_not_circles():
    k = 32 * 0.5522847498307936
    p = np.array([[82, 50], [82, 50 - k], [50 + k, 18], [50, 18]])
    with pytest.raises(ValueError):
        fit_cubic_arc(p * np.array([2, 1]), 1.5)
    # Real native local coordinates preserved by P9 investigation, no CAD answer.
    southern = (
        np.array([[0, 0], [0.127, 8.636], [3.948, 13.082], [11.251, 13.082]]) * 240 / 72
    )
    with pytest.raises(ValueError):
        fit_cubic_arc(southern, 0.2 * 240 / 72)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_actual_loader_rotation_crop_and_scale(contract_page, tmp_path, rotation):
    source = tmp_path / "artificial-contract.pdf"
    doc = pdfium.PdfDocument(str(source))
    page = doc[0]
    page.set_cropbox(10, 20, 150, 140)
    page.set_rotation(rotation)
    mapped = tmp_path / f"mapped-{rotation}.pdf"
    doc.save(mapped)
    page.close()
    doc.close()
    context = []
    image = load_image(mapped, pdf_dpi=144, grayscale=True, pdf_geometry_sink=context)
    (evidence,) = context
    (candidate,) = evidence.candidates
    binary = np.where(image < 254, 0, 255).astype(np.uint8)
    base = FinalStructure(image.shape[::-1], binary, tuple(trace_binary(binary)))
    final = apply_pdf_arc_evidence(base, image, evidence)
    assert len(final.arcs) == 1 and final.contours == ()
    assert final.arcs[0].radius == pytest.approx(64, abs=1e-5)
    assert abs(final.arcs[0].sweep_angle_deg) == pytest.approx(90, abs=1e-5)
    a, b, c, d, e, f = evidence.page_to_pixel
    assert final.arcs[0].center == pytest.approx(
        (a * 50 + c * 50 + e, b * 50 + d * 50 + f), abs=1e-5
    )


def test_exact_shared_cad_node_is_not_reinterpreted_as_a_nearby_source_node(
    contract_page,
):
    image, evidence, base = contract_page
    x, y = base.contours[0].points[0]
    line = LineSegment(x, y, x - 25, y, source_ids=("contract:independent-node",))
    s = replace(base, straight_lines=(line,))
    final = apply_pdf_arc_evidence(s, image, evidence)
    assert (
        final.arcs == ()
        and final.contours == s.contours
        and final.straight_lines == s.straight_lines
    )
    assert (
        final.observations[-1]["decisions"][-1]["reason"]
        == "EXACT_CAD_NODE_WOULD_CHANGE"
    )


def test_candidate_parameters_cannot_be_changed_without_curve_proof(contract_page):
    _, evidence, _ = contract_page
    c = evidence.candidates[0]
    with pytest.raises(ValueError, match="PARAMETERS"):
        replace(c, parameters=dict(c.parameters, radius=c.parameters["radius"] + 0.05))


def test_plain_raster_has_no_pdf_evidence(tmp_path):
    from PIL import Image

    file = tmp_path / "plain.png"
    Image.fromarray(np.full((32, 32), 255, np.uint8)).save(file)
    context = []
    load_image(file, pdf_geometry_sink=context)
    assert context == []


def test_image_only_pdf_has_empty_optional_evidence(tmp_path):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (160, 160), "white")
    ImageDraw.Draw(im).line((20, 20, 140, 140), fill="black", width=2)
    file = tmp_path / "scan.pdf"
    im.save(file, "PDF")
    context = []
    image = load_image(file, pdf_dpi=72, grayscale=True, pdf_geometry_sink=context)
    assert context[0].candidates == ()
    binary = np.where(image < 128, 0, 255).astype(np.uint8)
    s = FinalStructure(
        (image.shape[1], image.shape[0]), binary, tuple(trace_binary(binary))
    )
    assert apply_pdf_arc_evidence(s, image, context[0]) is s
