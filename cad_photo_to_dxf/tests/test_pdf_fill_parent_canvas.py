"""QA-only native PDF parent-grid and source-role preservation contracts."""

import hashlib

import numpy as np
import pypdfium2 as pdfium
import pytest

from app.core.image_loader import load_image


def make_fractional_parent(tmp_path, rotation=0, shifted_crop=False):
    """A six-vertex opaque area, not any real drawing/filename selector."""
    raw = pdfium.raw
    path = tmp_path / f"qa-parent-{rotation}-{shifted_crop}.pdf"
    with pdfium.PdfDocument.new() as document:
        page = document.new_page(842, 595)
        if shifted_crop:
            page.set_mediabox(-10, -20, 832, 575)
            page.set_cropbox(2, 3, 820, 560)
        page.set_rotation(rotation)
        vertices = ((1500, 1400), (3500, 1400), (3500, 1800),
                    (2700, 1800), (2700, 2600), (1500, 2600))
        shape = raw.FPDFPageObj_CreateNewPath(*vertices[0])
        assert shape
        for point in vertices[1:]:
            assert raw.FPDFPath_LineTo(shape, *point)
        assert raw.FPDFPath_Close(shape)
        assert raw.FPDFPageObj_SetFillColor(shape, 241, 243, 245, 255)
        assert raw.FPDFPath_SetDrawMode(shape, raw.FPDF_FILLMODE_ALTERNATE, 0)
        raw.FPDFPageObj_Transform(shape, .06, 0, 0, -.06, 13, 580)
        raw.FPDFPage_InsertObject(page, shape)
        assert raw.FPDFPage_GenerateContent(page)
        document.save(path)
        page.close()
    return path


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("shifted_crop", [False, True])
def test_reference_keeps_original_physical_parent_and_rotation(
    tmp_path, rotation, shifted_crop
):
    path = make_fractional_parent(tmp_path, rotation, shifted_crop)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = []
    image = load_image(path, pdf_dpi=240, grayscale=True, pdf_geometry_sink=evidence)
    assert len(evidence[0].native_fills) == 1, evidence[0].fill_analysis
    fill = evidence[0].native_fills[0]
    assert fill.version == 2 and fill.rgb == (241, 243, 245)
    assert evidence[0].fill_analysis["restored_and_reread"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    reread = load_image(path, pdf_dpi=240, grayscale=True)
    assert np.array_equal(image, reread)


def area_evidence(*fills):
    from app.core.arc_types import PdfPathReference
    from app.core.native_fill import NativeFill
    from app.geometry.pdf_arc_evidence import PdfGeometryEvidence
    if not fills:
        fills = (NativeFill(PdfPathReference("QA_TEST_ONLY.pdf", 1, 3),
                            ((10, 10), (70, 10), (70, 70), (10, 70)),
                            (192, 192, 192), (1, 0, 0, 1, 0, 0), 72),)
    return PdfGeometryEvidence(
        {"document": "QA_TEST_ONLY.pdf", "page_number": 1},
        (100, 100), (1, 0, 0, 1, 0, 0), native_fills=fills,
    )


def qualify(evidence=None, **kwargs):
    from app.geometry.pdf_fill_ownership import qualify_pdf_fill_ownership
    return qualify_pdf_fill_ownership(
        area_evidence() if evidence is None else evidence,
        texts=kwargs.pop("texts", ()),
        protected_masks=kwargs.pop("protected_masks", (np.zeros((100, 100), np.uint8),) * 3),
        **kwargs,
    )


@pytest.mark.parametrize("kind", ["bbox", "quad", "display_quad"])
def test_all_source_candidates_veto_entire_area_even_if_no_vertices_touch(kind):
    from types import SimpleNamespace
    text = SimpleNamespace(bbox=(30, 30, 10, 10), quad=None, display_quad=None,
                           confidence=.01, replacement_safe=False)
    if kind != "bbox":
        text.bbox = (80, 80, 10, 10)
        setattr(text, kind, ((30, 30), (40, 30), (40, 40), (30, 40)))
    evidence = area_evidence()
    result = qualify(evidence, texts=(text,))
    assert result.native_fills == () and len(evidence.native_fills) == 1
    assert result.binding is evidence.binding
    assert not result.fill_analysis["ownership_qualification"]["pre-retirement"]["source_deletion_authority"]


@pytest.mark.parametrize("index", range(3))
def test_source_mask_including_hidden_or_uncertain_ink_vetoes_fill(index):
    masks = [np.zeros((100, 100), np.uint8) for _ in range(3)]
    masks[index][35, 35] = 255
    before = [mask.copy() for mask in masks]
    assert qualify(protected_masks=masks).native_fills == ()
    assert all(np.array_equal(a, b) for a, b in zip(masks, before))


@pytest.mark.parametrize("bad", [None, np.zeros((99, 100), np.uint8),
                                  np.full((100, 100), np.nan)])
def test_unknown_masks_fail_closed_even_without_known_text(bad):
    assert not qualify(protected_masks=(bad,)).native_fills


def test_background_bbox_and_malformed_quad_fail_closed():
    from types import SimpleNamespace
    region = SimpleNamespace(bbox=(30, 30, 10, 10))
    assert not qualify(protected_regions=(region,)).native_fills
    region.bbox = (np.nan, 30, 10, 10)
    assert not qualify(protected_regions=(region,)).native_fills
    text = SimpleNamespace(bbox=(80, 80, 10, 10), quad=((np.nan, 30),) * 4)
    assert not qualify(texts=(text,)).native_fills


@pytest.mark.parametrize("different_color", [False, True])
def test_overlapping_new_areas_abstain_without_claiming_equivalence(different_color):
    from dataclasses import replace
    from app.core.arc_types import PdfPathReference
    evidence = area_evidence()
    smaller = replace(evidence.native_fills[0], source=PdfPathReference("QA_TEST_ONLY.pdf", 1, 9),
                      points=((20, 20), (30, 20), (30, 30), (20, 30)),
                      rgb=(241, 243, 245) if different_color else (192, 192, 192))
    evidence = replace(evidence, native_fills=(*evidence.native_fills, smaller))
    result = qualify(evidence)
    assert len(result.native_fills) == 1 and len(evidence.native_fills) == 2
    rows = result.fill_analysis["ownership_qualification"]["pre-retirement"]["abstained"]
    assert rows == [{"object_id": smaller.object_id, "reason": "FILL_OVERLAPPING_NATIVE_AREA"}]


def test_clear_area_keeps_original_source_indexes_and_crop_binding():
    from types import SimpleNamespace
    evidence = area_evidence()
    text = SimpleNamespace(bbox=(80, 80, 10, 10), quad=None, display_quad=None)
    result = qualify(evidence, texts=(text,))
    assert result.native_fills == evidence.native_fills
    assert result.native_fills[0].source.object_index == 3
    assert result.page_to_pixel == evidence.page_to_pixel
    cropped = evidence.for_crop((5, 5, 95, 95))
    result = qualify(cropped, protected_masks=(np.zeros((90, 90), np.uint8),))
    assert result.native_fills == cropped.native_fills
    assert result.native_fills[0].page_to_pixel == result.page_to_pixel


def test_final_existing_source_fill_veto_is_nondestructive():
    from app.core.structure_build import build_final_structure
    from app.geometry.raster_trace import TracePath
    from app.geometry.pdf_fill_evidence import apply_pdf_fill_evidence
    path = TracePath(((20, 20), (30, 20), (30, 30), (20, 30)), None, 0, 0)
    masks = np.zeros((100, 100), np.uint8)
    structure = build_final_structure(
        source_size_px=(100, 100), contour_binary=np.full((100, 100), 255, np.uint8),
        contours=(path,), editable_text_source_mask=masks,
        source_text_outline_mask=masks, uncertain_text_outline_mask=masks,
        provenance={"stroke_presentation": {"fill_records": {"0": {"kind": "SOURCE_FILL"}}}},
    )
    assert apply_pdf_fill_evidence(structure, area_evidence()) is structure


def test_existing_native_areas_are_fixed_and_repeated_application_is_idempotent():
    from dataclasses import replace
    from app.core.arc_types import PdfPathReference
    from app.core.structure_build import build_final_structure
    from app.geometry.pdf_fill_evidence import apply_pdf_fill_evidence
    evidence = area_evidence()
    old = evidence.native_fills[0]
    masks = np.zeros((100, 100), np.uint8)
    structure = build_final_structure(
        source_size_px=(100, 100), contour_binary=np.full((100, 100), 255, np.uint8),
        contours=(), native_fills=(old,), editable_text_source_mask=masks,
        source_text_outline_mask=masks, uncertain_text_outline_mask=masks,
    )
    assert apply_pdf_fill_evidence(structure, evidence) is structure
    new = replace(old, source=PdfPathReference("QA_TEST_ONLY.pdf", 1, 4),
                  points=((20, 20), (30, 20), (30, 30), (20, 30)), rgb=(241, 243, 245))
    assert apply_pdf_fill_evidence(structure, replace(evidence, native_fills=(new,))) is structure
    with pytest.raises(ValueError, match="FILL_SOURCE_CHANGED"):
        apply_pdf_fill_evidence(structure, replace(evidence, native_fills=(replace(old, rgb=(200, 200, 200)),)))


def test_page_object_cap_remains_bounded_and_forms_abstain(monkeypatch):
    from types import SimpleNamespace
    from app.geometry import pdf_fill_evidence as module
    bitmap = SimpleNamespace(width=100, height=100,
                             get_posconv=lambda page: SimpleNamespace(to_page=lambda x, y: (x, y)))
    monkeypatch.setattr(module, "MAX_PAGE_OBJECTS", 2)
    page = SimpleNamespace(get_objects=lambda **kwargs: iter([SimpleNamespace(type=2)] * 3))
    assert module.extract_pdf_fills("QA.pdf", 0, page, bitmap, 1, 72)[1]["accepted"] == 0
    page = SimpleNamespace(get_objects=lambda **kwargs: iter([SimpleNamespace(type=5)]))
    assert module.extract_pdf_fills("QA.pdf", 0, page, bitmap, 1, 72)[1]["accepted"] == 0
