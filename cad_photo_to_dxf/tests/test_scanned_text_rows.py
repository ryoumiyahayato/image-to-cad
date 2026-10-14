"""USDA p4 source rows through the existing layout, ownership and DXF path."""
from dataclasses import replace
from pathlib import Path

import cv2
import ezdxf
import numpy as np
import pytest

from app.core.preview import render_emitted_dxf_preview, render_final_structure_preview
from app.core.structure_build import final_structure_from_trace_result
from app.export.ocr_outline_export import add_ocr_outline_blocks, native_text_placement
from app.export.trace_single_export import export_final_structure_dxf
from app.geometry import optimized_trace
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.ocr_fast import prepare_safe_candidate
from app.ocr.ocr_layout import constrain_texts_to_table_cells, offset_candidate


def region():
    # Original USDA 7213 physical p4, 240 DPI, crop [1650:1800, 510:990].
    gray = cv2.imread(str(Path(__file__).parent / 'real_regression/assets/regions/'
                          'usda-foundation-note-p4-240dpi.png'), cv2.IMREAD_GRAYSCALE)
    saved = (
        ('4" CONCRETE SLAB WITH 6X6 IO WW.M.', (532, 1705, 395, 28), .93069,
         .29010273362816563, ((532,1705),(927,1707),(927,1733),(532,1731))),
        ('OVER 6" TAMPED GRAVEL FILL AND VAPOR', (533,1723,407,28), .97923,
         .28154947586019324, ((533,1723),(940,1725),(940,1751),(533,1749))),
        ('BARRIER. OVER ENTIRE AREA', (535,1742,290,26), .95743,
         .3951370425074883, ((535,1742),(825,1744),(825,1768),(535,1765))),
    )
    texts = tuple(offset_candidate(TextCandidate(text, bbox, confidence, 'text_candidate',
        rotation_deg=rotation, quad=quad, source='rapidocr-overview'),
        offset_x=-510, offset_y=-1650) for text,bbox,confidence,rotation,quad in saved)
    return gray, tuple(prepare_safe_candidate(gray, item) for item in texts)


def text_masks(texts, shape, directory):
    masks = []
    for item in texts:
        doc = ezdxf.new()
        doc.layers.add('OCR_TEXT')
        add_ocr_outline_blocks(doc, doc.modelspace(), (item,),
                               transform=lambda x,y: (x, shape[0]-y))
        masks.append(render_emitted_dxf_preview(doc, directory, shape[::-1]) < 128)
    return masks


def test_actual_scanned_rows_fit_source_and_remove_native_glyph_collisions(tmp_path):
    gray, original = region()
    proofs = []
    restored = constrain_texts_to_table_cells(gray, original, verified_sources=proofs)
    assert len(proofs) == 1 and len(proofs[0].row_masks) == 3
    assert all(item.replacement_safe for item in restored)
    assert [(i.text,i.bbox,i.confidence,i.rotation_deg,i.reviewed) for i in restored] == [
        (i.text,i.bbox,i.confidence,i.rotation_deg,i.reviewed) for i in original]
    # Each complete source row, including punctuation, has exactly one owner.
    union = np.stack(proofs[0].row_masks) > 0
    assert not np.any(union.sum(0) > 1)
    assert np.array_equal(union.any(0), proofs[0].mask > 0)
    bounds = [(1712,1727),(1730,1745),(1747,1763)]
    left,top,_,_ = proofs[0].bounds
    for row,(start,end) in zip(proofs[0].row_masks,bounds,strict=True):
        ys,_ = np.nonzero(row)
        assert (top+ys.min()+1650,top+ys.max()+1651) == (start,end)
    reversed_result = constrain_texts_to_table_cells(gray, original[::-1], verified_sources=[])
    assert restored == reversed_result[::-1]
    old_masks,new_masks = text_masks(original,gray.shape,tmp_path),text_masks(restored,gray.shape,tmp_path)
    assert all(np.any(old_masks[a] & old_masks[a+1]) for a in range(2))
    assert not any(np.any(new_masks[a] & new_masks[a+1]) for a in range(2))
    for old,new in zip(original,restored,strict=True):
        before = native_text_placement(old,transform=lambda x,y:(x,gray.shape[0]-y)).geometry
        after = native_text_placement(new,transform=lambda x,y:(x,gray.shape[0]-y)).geometry
        assert after.rotation == pytest.approx(before.rotation)
        assert after.character_height < before.character_height
        assert .7 < after.width_factor < 1.0


@pytest.mark.parametrize('blocker', ['connected-rows','truncated-structure','reviewed','rotated'])
def test_uncertain_source_does_not_get_new_layout_or_replacement_permission(blocker):
    gray,texts = region()
    if blocker == 'connected-rows':
        cv2.line(gray,(70,65),(70,110),0,2)
    elif blocker == 'truncated-structure':
        cv2.line(gray,(0,70),(75,70),0,2)
    elif blocker == 'reviewed':
        texts = tuple(replace(item,reviewed=True) for item in texts)
    else:
        texts = tuple(replace(item,rotation_deg=90) for item in texts)
    proofs = []
    assert constrain_texts_to_table_cells(gray,texts,verified_sources=proofs) == texts
    assert not proofs


def test_saved_real_candidates_reach_product_structure_export_and_edit(monkeypatch,tmp_path):
    gray,texts = region()
    monkeypatch.setattr(optimized_trace,'recognize_text_candidates_optimized',
                        lambda image,**kwargs:(texts,()))
    traced = optimized_trace.trace_image_optimized(gray,enable_ocr=True,source_dpi=240)
    structure = final_structure_from_trace_result(traced)
    assert [item.text for item in structure.texts] == [item.text for item in texts]
    assert all(item.replacement_safe for item in structure.texts)
    result = export_final_structure_dxf(structure,tmp_path/'rows.dxf')
    doc = ezdxf.readfile(result.path)
    assert [item.dxf.text for item in doc.modelspace().query('TEXT')] == [item.text for item in texts]
    assert not doc.audit().has_errors
    assert np.array_equal(render_final_structure_preview(structure),
                          render_emitted_dxf_preview(doc,tmp_path,structure.source_size_px))
    entity = doc.modelspace().query('TEXT')[0]
    handle = entity.dxf.handle
    entity.dxf.text += 'A'
    entity.translate(1,2,0)
    doc.saveas(tmp_path/'edited.dxf')
    reopened = ezdxf.readfile(tmp_path/'edited.dxf')
    assert reopened.entitydb[handle].dxf.text == texts[0].text+'A'
    assert reopened.entitydb[handle].dxf.insert == entity.dxf.insert
    assert not reopened.audit().has_errors
