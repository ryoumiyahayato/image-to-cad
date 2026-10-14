from __future__ import annotations

from dataclasses import replace

import ezdxf
import numpy as np
from PySide6.QtGui import QTransform

from app.ocr.auxiliary_recognition import TextCandidate
from app.export.document_export import DocumentPage
from app.core.structure_build import build_final_structure
from app.ocr.librecad_lff import librecad_text_path
from app.export.ocr_outline_export import NativeTextPlacement, add_ocr_outline_blocks, native_text_placement
from app.diagnostics.visual_acceptance import render_visual_acceptance
from app.export.trace_document_export import export_trace_document_streaming
from app.export.trace_single_export import export_final_structure_dxf


_PIXEL_ENVELOPE_TOLERANCE = 3.0


def _candidate(
    text: str,
    bbox: tuple[int, int, int, int],
    *,
    quad: tuple[tuple[float, float], ...] | None = None,
) -> TextCandidate:
    return TextCandidate(
        text=text,
        bbox=bbox,
        confidence=0.99,
        kind="text_candidate",
        quad=quad,
        source="text-vqa-parity-test",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )


def _structure(*texts: TextCandidate):
    height, width = 150, 190
    return build_final_structure(
        source_size_px=(width, height),
        contour_binary=np.full((height, width), 255, dtype=np.uint8),
        contours=(),
        texts=tuple(texts),
    )


def _native_geometry(candidate: TextCandidate) -> tuple[object, ...]:
    doc = ezdxf.new("R2010", setup=True)
    count, entities, _bounds = add_ocr_outline_blocks(
        doc,
        doc.modelspace(),
        (candidate,),
        transform=lambda x, y: (x, 150.0 - y),
    )
    assert count == 1
    entity = entities[0]
    return (
        float(entity.dxf.insert.x),
        float(entity.dxf.insert.y),
        float(entity.dxf.height),
        float(entity.dxf.width),
        float(entity.dxf.rotation),
    )


def _visible_source_bounds(
    placement: NativeTextPlacement,
    *,
    image_height: int,
) -> np.ndarray:
    geometry = placement.geometry
    metrics = placement.metrics
    scale_y = geometry.character_height / metrics.em_height
    scale_x = scale_y * geometry.width_factor
    transform = QTransform()
    transform.translate(geometry.insert[0], image_height - geometry.insert[1])
    transform.rotate(-geometry.rotation)
    transform.scale(scale_x, scale_y)
    bounds = transform.map(librecad_text_path(placement.content)).boundingRect()
    return np.asarray(
        (bounds.left(), bounds.top(), bounds.right(), bounds.bottom())
    )


def _assert_raster_envelope_matches_placement(
    candidate: TextCandidate,
) -> None:
    source = np.full((150, 190), 255, dtype=np.uint8)
    rendered = render_visual_acceptance(
        source,
        _structure(candidate),
    ).reconstructed
    placement = native_text_placement(
        candidate,
        transform=lambda x, y: (x, 150.0 - y),
    )
    assert placement is not None
    expected_bounds = _visible_source_bounds(placement, image_height=150)
    actual_y, actual_x = np.nonzero(np.any(rendered < 245, axis=2))
    assert actual_x.size > 0
    actual_bounds = np.asarray(
        (actual_x.min(), actual_y.min(), actual_x.max(), actual_y.max()),
        dtype=float,
    )
    assert np.all(
        np.abs(actual_bounds - expected_bounds) <= _PIXEL_ENVELOPE_TOLERANCE
    )


def test_vqa_final_placement_changes_with_the_native_text_quad() -> None:
    axis = _candidate(
        "中文 ABC",
        (20, 20, 140, 70),
        quad=((20.0, 20.0), (160.0, 20.0), (160.0, 90.0), (20.0, 90.0)),
    )
    rotated = replace(
        axis,
        quad=((30.0, 30.0), (150.0, 60.0), (143.0, 88.0), (23.0, 58.0)),
    )

    assert _native_geometry(axis) != _native_geometry(rotated)
    source = np.full((150, 190), 255, dtype=np.uint8)
    axis_vqa = render_visual_acceptance(source, _structure(axis)).reconstructed
    rotated_vqa = render_visual_acceptance(source, _structure(rotated)).reconstructed

    assert not np.array_equal(axis_vqa, rotated_vqa)


def test_vqa_raster_envelope_tracks_axis_rotated_and_reversed_placement() -> None:
    base = _candidate("中文 ABC", (20, 20, 140, 70))
    candidates = (
        replace(
            base,
            quad=((20.0, 20.0), (160.0, 20.0), (160.0, 90.0), (20.0, 90.0)),
        ),
        replace(
            base,
            quad=((30.0, 30.0), (150.0, 60.0), (143.0, 88.0), (23.0, 58.0)),
        ),
        replace(
            base,
            quad=((160.0, 90.0), (20.0, 90.0), (20.0, 20.0), (160.0, 20.0)),
        ),
    )

    for candidate in candidates:
        placement = native_text_placement(
            candidate,
            transform=lambda x, y: (x, 150.0 - y),
        )
        assert placement is not None
        native = _native_geometry(candidate)
        assert np.allclose(
            native[:2],
            placement.geometry.insert,
            rtol=0.0,
            atol=1e-12,
        )
        assert np.allclose(
            native[2:],
            (
                placement.geometry.character_height,
                placement.geometry.width_factor,
                placement.geometry.rotation,
            ),
            rtol=0.0,
            atol=1e-12,
        )
        _assert_raster_envelope_matches_placement(candidate)


def test_vqa_final_text_set_matches_native_text_eligibility() -> None:
    accepted = _candidate("ACCEPT", (10, 10, 120, 22))
    pending = replace(
        _candidate("PENDING", (10, 50, 120, 22)),
        approved=False,
        reviewed=False,
    )
    wrong_kind = replace(
        _candidate("WRONGKIND", (10, 90, 140, 22)),
        kind="drawing_text",
    )
    source = np.full((150, 190), 255, dtype=np.uint8)

    rendered = render_visual_acceptance(
        source,
        _structure(accepted, pending, wrong_kind),
    ).reconstructed
    doc = ezdxf.new("R2010", setup=True)
    count, entities, _bounds = add_ocr_outline_blocks(
        doc,
        doc.modelspace(),
        (accepted, pending, wrong_kind),
        transform=lambda x, y: (x, 150.0 - y),
    )

    assert count == 1
    assert [entity.dxf.text for entity in entities] == ["ACCEPT"]
    assert np.any(rendered[10:32, 10:130] < 245)
    assert np.all(rendered[50:72, 10:130] == 255)
    assert np.all(rendered[90:112, 10:150] == 255)


def _exported_text_summary(entity) -> tuple[object, ...]:
    return (
        entity.dxf.text,
        (float(entity.dxf.insert.x), float(entity.dxf.insert.y)),
        float(entity.dxf.height),
        float(entity.dxf.width),
        float(entity.dxf.rotation),
        float(entity.dxf.oblique),
        entity.dxf.style,
        tuple((tag.code, tag.value) for tag in entity.get_xdata("OCR_TEXT_LINE")),
        tuple(
            (tag.code, tag.value)
            for tag in entity.get_xdata("TEXT_OUTPUT_CONTRACT")
        ),
        tuple(
            (tag.code, tag.value)
            for tag in entity.get_xdata("OCR_TEXT_GEOMETRY")
        ),
    )


def test_single_and_document_export_keep_native_text_semantics_and_filtering(
    tmp_path,
) -> None:
    accepted = _candidate(
        "中文 EDIT",
        (20, 20, 140, 70),
        quad=((30.0, 30.0), (150.0, 60.0), (143.0, 88.0), (23.0, 58.0)),
    )
    pending = replace(_candidate("PENDING", (10, 100, 80, 20)), approved=False)
    wrong_kind = replace(
        _candidate("WRONGKIND", (100, 105, 80, 20)),
        kind="drawing_text",
    )
    structure = _structure(accepted, pending, wrong_kind)
    single_result = export_final_structure_dxf(
        structure,
        tmp_path / "single.dxf",
    )
    page = DocumentPage(
        page_number=1,
        raster=None,
        page_size_mm=(190.0, 150.0),
        vector_size_px=(190, 150),
        final_structure=structure,
    )
    document_result = export_trace_document_streaming(
        (page,),
        tmp_path / "document.dxf",
        total_pages=1,
    )

    single_doc = ezdxf.readfile(single_result.path)
    document_doc = ezdxf.readfile(document_result.path)
    single_texts = list(single_doc.modelspace().query("TEXT"))
    document_texts = list(document_doc.modelspace().query("TEXT"))
    assert single_result.text_count == document_result.text_count == 1
    assert len(single_texts) == len(document_texts) == 1
    assert _exported_text_summary(single_texts[0]) == _exported_text_summary(
        document_texts[0]
    )
    assert single_texts[0].dxf.layer == "OCR_TEXT"
    assert document_texts[0].dxf.layer == "PAGE_001_OCR_TEXT"
    assert not single_doc.audit().errors
    assert not document_doc.audit().errors
