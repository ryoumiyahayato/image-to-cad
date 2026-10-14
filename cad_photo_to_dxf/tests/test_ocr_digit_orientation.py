"""Local OCR-to-DXF regressions for real warehouse drawing digits."""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.image_loader import load_image
from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.ocr import ocr_recognition
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_fast import _offset_candidate, prepare_safe_candidate
from app.ocr.ocr_pipeline import _prepare_native_ocr_tile


@lru_cache(maxsize=3)
def _page(page, dpi):
    return load_image(
        Path(__file__).parent / 'real_regression/assets/sources/warehouse-electrical-vector.pdf',
        page_index=page, pdf_dpi=dpi, grayscale=True,
    )


@pytest.mark.parametrize('page,dpi,bbox,old,expected', [
    (0, 240, (1618, 1117, 21, 42), '7', '1'),
    (1, 136, (4520, 2649, 14, 26), '7', '1'),
    (2, 110, (4563, 2141, 15, 24), '7', '1'),
    (1, 136, (897, 2612, 16, 23), '7', '7'),
])
def test_source_digit_through_recognition_dxf_and_default_preview(
    page, dpi, bbox, old, expected, monkeypatch, tmp_path,
):
    from rapidocr.utils.process_img import get_rotate_crop_image

    monkeypatch.setattr(ocr_recognition, '_RAPID_OCR_ENGINE', None)
    engine = ocr_recognition._get_rapidocr_engine()
    source = _page(page, dpi)
    offset = max(0, source.shape[1] - 4096)
    working = cv2.cvtColor(_prepare_native_ocr_tile(source[:, offset:]), cv2.COLOR_GRAY2BGR)
    x, y, w, h = bbox
    quad = np.array([[x-offset, y], [x-offset+w, y],
                     [x-offset+w, y+h], [x-offset, y+h]], dtype=np.float32)
    raw = engine.recognize_txt([get_rotate_crop_image(working, quad)])
    assert raw.txts == (old,)

    class SavedDetection:
        calls = 0
        recognize_txt = engine.recognize_txt

        def __call__(self, _image, **_kwargs):
            self.calls += 1
            return SimpleNamespace(boxes=[quad], txts=raw.txts, scores=raw.scores)

    replay = SavedDetection()
    monkeypatch.setattr(ocr_recognition, '_RAPID_OCR_ENGINE', replay)
    corrected = ocr_recognition._recognize_rapidocr_pass(working, rotation=0)[0]
    assert replay.calls == 1
    assert corrected.text == expected
    assert corrected.bbox == (x-offset, y, w, h)
    assert not corrected.reviewed
    absolute = _offset_candidate(corrected, offset_x=offset, offset_y=0, source=corrected.source)
    safe = prepare_safe_candidate(source, absolute)
    assert safe.replacement_safe
    # Export a local source region through the unchanged production TEXT writer.
    local = _offset_candidate(safe, offset_x=20-x, offset_y=20-y, source=safe.source)
    blank = np.full((h+40, w+40), 255, np.uint8)
    structure = build_final_structure(source_size_px=blank.shape[::-1],
        contour_binary=blank, contours=(), texts=(local,), preview_binary=blank)
    result = export_final_structure_dxf(structure, tmp_path/'digit.dxf')
    doc = ezdxf.readfile(result.path)
    native = list(doc.modelspace().query('TEXT'))
    assert len(native) == 1 and native[0].dxf.text == expected
    assert 0 < native[0].dxf.height < h+2
    assert 10 < native[0].dxf.insert.x < w+30
    assert 10 < native[0].dxf.insert.y < h+30
    assert native[0].get_xdata('OCR_TEXT_LINE')[1].value == expected
    actual = render_emitted_dxf_preview(doc, tmp_path, structure.source_size_px)
    default = render_final_structure_preview(structure)
    assert np.array_equal(actual, default)
    if old != expected:
        old_preview = render_final_structure_preview(replace(structure, texts=(replace(local, text=old),)))
        assert not np.array_equal(default, old_preview)


def _digit(text='7', bbox=(10, 10, 14, 26), angle=0):
    x, y, w, h = bbox
    return TextCandidate(text, bbox, .96241, 'dimension_text_candidate', rotation_deg=angle,
        quad=((x,y),(x+w,y),(x+w,y+h),(x,y+h)))


@pytest.mark.parametrize('answers,scores', [
    (('1','7'), (.99,.99)),
    (('1','1'), (.99,.89)),
    (('I','I'), (.99,.99)),
])
def test_orientation_disagreement_or_weak_evidence_keeps_original(answers, scores):
    engine = SimpleNamespace(recognize_txt=lambda _crops: SimpleNamespace(txts=answers, scores=scores))
    original = [_digit()]
    result = ocr_recognition._review_single_digit_orientation(np.full((60,60,3),255,np.uint8), original, engine)
    assert result == original


def test_review_is_batched_and_leaves_other_text_and_orientation_unchanged():
    original = [_digit(), _digit('3'), _digit('中文'), _digit('A'),
                _digit('17'), _digit('7', (10,10,30,26)), _digit('7', angle=90),
                _digit('7', (10,10,50,120))]
    calls = []

    def recognize(crops):
        calls.append(crops)
        return SimpleNamespace(txts=('1','1','3','3'), scores=(.95,.99,.99,.99))

    result = ocr_recognition._review_single_digit_orientation(
        np.full((160,160,3),255,np.uint8), original, SimpleNamespace(recognize_txt=recognize))
    assert len(calls) == 1 and len(calls[0]) == 4
    assert result[0].text == '1' and result[0].confidence == .95
    assert result[0].bbox == original[0].bbox and result[0].quad == original[0].quad
    assert result[1:] == original[1:]
