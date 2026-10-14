"""Reading-basis regression using the Southern Farmhouse source crop."""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
from app.core.structure_build import build_final_structure
from app.export.trace_single_export import export_final_structure_dxf
from app.ocr import ocr_recognition
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_fast import prepare_safe_candidate


@lru_cache(maxsize=1)
def _engine():
    return ocr_recognition._get_rapidocr_engine()


def _candidate(text='14\'-0" [4200]'):
    return TextCandidate(text, (66, 64, 23, 108), .97705, 'text_candidate',
                         quad=((66, 64), (89, 64), (89, 172), (66, 172)))


@pytest.mark.parametrize('reverse,tilt,expected_rotation', [
    (False, 0, 90), (True, 0, 270), (False, 3, 93),
])
def test_source_reading_basis_reaches_native_text_and_preview(
    reverse, tilt, expected_rotation, monkeypatch, tmp_path,
):
    source = cv2.imread(str(Path(__file__).parent / 'real_regression/assets/regions/'
                           'southern-farmhouse-dimension-p5-240dpi.png'))
    points = np.asarray(_candidate().quad, dtype=np.float32)
    if reverse:
        source = cv2.rotate(source, cv2.ROTATE_180)
        points = np.asarray([(source.shape[1]-1-x, source.shape[0]-1-y)
                             for x, y in points], dtype=np.float32)[[2, 3, 0, 1]]
    if tilt:
        matrix = cv2.getRotationMatrix2D((source.shape[1]/2, source.shape[0]/2), tilt, 1)
        source = cv2.warpAffine(source, matrix, source.shape[1::-1], borderValue=(255,255,255))
        points = cv2.transform(points[None], matrix)[0]
    engine = _engine()

    class SavedDetection:
        calls = 0
        recognize_txt = engine.recognize_txt
        text_cls = engine.text_cls

        def __call__(self, _image, **_kwargs):
            self.calls += 1
            return SimpleNamespace(boxes=[points], txts=(_candidate().text,), scores=(.97705,))

    replay = SavedDetection()
    monkeypatch.setattr(ocr_recognition, '_RAPID_OCR_ENGINE', replay)
    corrected = ocr_recognition._recognize_rapidocr_pass(source, rotation=0)[0]
    original = ocr_recognition._candidate_from_quad(_candidate().text, .97705, points,
        rotation=0, original_shape=source.shape[:2], source='rapidocr-line')
    assert replay.calls == 1
    assert corrected.text == original.text and corrected.confidence == original.confidence
    assert corrected.bbox == original.bbox and set(corrected.quad) == set(original.quad)
    assert corrected.reviewed == original.reviewed
    corrected = prepare_safe_candidate(source, corrected)
    assert not corrected.replacement_safe  # Direction evidence grants no source deletion authority.
    blank = np.full(source.shape[:2], 255, np.uint8)
    structure = build_final_structure(source_size_px=blank.shape[::-1], contour_binary=blank,
        contours=(), texts=(corrected,), preview_binary=blank)
    result = export_final_structure_dxf(structure, tmp_path/'dimension.dxf')
    doc = ezdxf.readfile(result.path)
    entities = list(doc.modelspace().query('TEXT'))
    assert len(entities) == 1
    entity = entities[0]
    assert entity.dxf.text == original.text
    assert entity.dxf.rotation == pytest.approx(expected_rotation, abs=.001)
    assert 15 < entity.dxf.height < 24 and .45 < entity.dxf.width < .65
    assert len(doc.audit().errors) == 0
    assert np.array_equal(render_final_structure_preview(structure),
                          render_emitted_dxf_preview(doc, tmp_path, structure.source_size_px))
    original_height, original_width = entity.dxf.height, entity.dxf.width
    entity.dxf.text += 'A'
    doc.saveas(tmp_path/'edited.dxf')
    edited = ezdxf.readfile(tmp_path/'edited.dxf').entitydb[entity.dxf.handle]
    assert edited.dxf.text == original.text+'A'
    assert edited.dxf.rotation == entity.dxf.rotation
    assert edited.dxf.height == original_height and edited.dxf.width == original_width


@pytest.mark.parametrize('texts,scores,classification', [
    (('20', 'wrong', '14\'-0" [4200]'), (.7,.6,.99), ('180', .89)),
    (('20', 'wrong', 'different'), (.7,.6,.99), ('180', .99)),
    (('20', '14\'-0" [4200]', '14\'-0" [4200]'), (.7,.99,.99), ('180', .99)),
    (('14\'-0" [4200]', 'wrong', '14\'-0" [4200]'), (.99,.6,.99), ('180', .99)),
])
def test_uncertain_direction_keeps_original_source_basis(texts, scores, classification):
    engine = SimpleNamespace(
        recognize_txt=lambda crops: SimpleNamespace(txts=texts, scores=scores),
        text_cls=lambda crops: SimpleNamespace(cls_res=[classification]),
    )
    original = [_candidate()]
    assert ocr_recognition._review_rotated_line_orientation(
        np.full((220,150,3),255,np.uint8), original, engine) == original


def test_upright_single_digit_horizontal_line_and_vertical_cjk_do_not_trigger_review():
    original = [_candidate('1'), _candidate('施工图'),
                replace(_candidate(), reviewed=True),
                replace(_candidate(), bbox=(10,10,108,23),
                        quad=((10,10),(118,10),(118,33),(10,33)))]

    def unexpected(crops):
        pytest.fail('These candidates must not incur orientation review')

    engine = SimpleNamespace(recognize_txt=unexpected, text_cls=unexpected)
    assert ocr_recognition._review_rotated_line_orientation(
        np.full((220,150,3),255,np.uint8), original, engine) == original
