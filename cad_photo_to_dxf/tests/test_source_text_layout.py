"""Source-supported Chinese layout, without changing OCR or geometry ownership."""

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.cache import _deserialize_texts, _serialize_texts
from app.core.image_loader import load_image
from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
from app.core.structure_build import build_final_structure
from app.export.ocr_outline_export import native_text_placement
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry.content_ownership import _candidate_region_mask
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_fast import prepare_safe_candidate
from app.ocr.ocr_layout import constrain_texts_to_table_cells


@lru_cache(maxsize=3)
def _source(page, dpi):
    return load_image(
        Path(__file__).parent
        / "real_regression/assets/sources/warehouse-electrical-vector.pdf",
        page_index=page,
        pdf_dpi=dpi,
        grayscale=True,
    )


def _candidate(text, bbox):
    x, y, w, h = bbox
    return TextCandidate(
        text,
        bbox,
        0.999,
        "text_candidate",
        quad=((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
        source="saved-real-OCR",
    )


@pytest.mark.parametrize(
    "page,dpi,text,bbox,expected_quad",
    [
        (
            0,
            240,
            "施工图",
            (1840, 593, 102, 60),
            ((1849, 601), (1933, 601), (1933, 645), (1849, 645)),
        ),
        (
            1,
            136,
            "施工图",
            (4493, 2588, 69, 41),
            ((4500, 2594), (4555, 2594), (4555, 2623), (4500, 2623)),
        ),
        (
            2,
            110,
            "施工图",
            (4543, 2093, 56, 34),
            ((4549, 2098), (4593, 2098), (4593, 2122), (4549, 2122)),
        ),
        (
            1,
            136,
            "3.1 每层按防火分区增加信号阀、水流指示器报警；",
            (2558, 1316, 431, 37),
            ((2562, 1319), (2984, 1319), (2984, 1350), (2562, 1350)),
        ),
    ],
)
def test_real_source_ink_controls_text_geometry_and_export_preview(
    page,
    dpi,
    text,
    bbox,
    expected_quad,
    tmp_path,
):
    source = _source(page, dpi)
    original = _candidate(text, bbox)
    prepared = prepare_safe_candidate(source, original)
    assert prepared.replacement_safe and prepared.quad == expected_quad
    assert prepared.text == text and prepared.bbox == bbox and not prepared.reviewed
    # Original protection/ownership uses the same per-character source regions.
    old = replace(prepared, quad=original.quad)
    assert np.array_equal(
        _candidate_region_mask(old, source.shape),
        _candidate_region_mask(prepared, source.shape),
    )
    assert _deserialize_texts(_serialize_texts((prepared,)))[0] == prepared
    old_geometry = native_text_placement(
        old, transform=lambda x, y: (x, source.shape[0] - y)
    ).geometry
    new_geometry = native_text_placement(
        prepared, transform=lambda x, y: (x, source.shape[0] - y)
    ).geometry
    assert new_geometry.rendered_height < old_geometry.rendered_height
    assert new_geometry.width_factor > old_geometry.width_factor
    assert new_geometry.width_factor != 1.0
    x, y, w, h = bbox
    local = replace(
        prepared,
        bbox=(10, 10, w, h),
        quad=tuple((qx - x + 10, qy - y + 10) for qx, qy in prepared.quad),
        character_boxes=tuple(
            (bx - x + 10, by - y + 10, bw, bh)
            for bx, by, bw, bh in prepared.character_boxes
        ),
    )
    blank = np.full((h + 20, w + 20), 255, np.uint8)
    structure = build_final_structure(
        source_size_px=blank.shape[::-1],
        contour_binary=blank,
        contours=(),
        texts=(local,),
    )
    result = export_final_structure_dxf(structure, tmp_path / "text.dxf")
    doc = ezdxf.readfile(result.path)
    native = doc.modelspace().query("TEXT")
    assert len(native) == 1 and native[0].dxf.text == text
    assert doc.styles.get(native[0].dxf.style).dxf.font == "wqy-unicode.lff"
    assert native[0].dxf.get("halign", 0) == native[0].dxf.get("valign", 0) == 0
    preview = render_final_structure_preview(structure)
    assert np.array_equal(
        preview, render_emitted_dxf_preview(doc, tmp_path, structure.source_size_px)
    )
    ys, xs = np.nonzero(preview < 128)
    assert 10 <= xs.min() < xs.max() <= 10 + w and 10 <= ys.min() < ys.max() <= 10 + h
    # Native string and placement remain editable after CAD save/reopen.
    entity = native[0]
    handle = entity.dxf.handle
    entity.dxf.text += "A"
    entity.translate(1, 2, 0)
    doc.saveas(tmp_path / "edited.dxf")
    edited = ezdxf.readfile(tmp_path / "edited.dxf").entitydb[handle]
    assert edited.dxf.text == text + "A" and edited.dxf.insert == entity.dxf.insert


def test_unsafe_small_chinese_cell_and_revision_digit_keep_original_quad():
    for page, dpi, text, bbox in (
        (1, 136, "专业负责人", (4154, 2278, 102, 25)),
        (2, 110, "1", (4563, 2141, 15, 24)),
    ):
        original = _candidate(text, bbox)
        prepared = prepare_safe_candidate(_source(page, dpi), original)
        assert prepared.quad == original.quad and prepared.text == text


def test_reviewed_and_rotated_text_keep_explicit_placement():
    original = _candidate("施工图", (4543, 2093, 56, 34))
    for item in (replace(original, reviewed=True), replace(original, rotation_deg=3)):
        prepared = prepare_safe_candidate(_source(2, 110), item)
        assert prepared.quad == item.quad and prepared.text == item.text


def test_cell_clipping_preserves_tight_source_quad_and_clips_at_rule():
    binary = np.full((220, 320), 255, np.uint8)
    for x in (40, 160, 280):
        cv2.line(binary, (x, 30), (x, 190), 0, 2)
    for y in (30, 100, 190):
        cv2.line(binary, (40, y), (280, y), 0, 2)
    candidate = replace(
        _candidate("说明文字", (55, 45, 125, 40)),
        quad=((60, 50), (150, 50), (150, 80), (60, 80)),
    )
    clipped = constrain_texts_to_table_cells(binary, (candidate,))[0]
    assert clipped.bbox[2] < candidate.bbox[2] and clipped.quad == candidate.quad
    crossing = replace(candidate, quad=((60, 50), (165, 50), (165, 80), (60, 80)))
    clipped = constrain_texts_to_table_cells(binary, (crossing,))[0]
    assert clipped.quad[1][0] < 160 and clipped.quad[0] == (60, 50)
