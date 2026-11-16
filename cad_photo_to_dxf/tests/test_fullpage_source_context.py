"""General context invariants; no filenames, target coordinates or answers in code."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace,asdict
import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from app.ocr.scanned_circular_symbols import _circular_holes,recover_circular_symbols
from app.ocr.scanned_title_rows import _coalesce_cell_candidates,_measurement_row
from app.ocr.observed_text_display import _source_fit,refine_source_supported_scan_displays
from app.ocr.auxiliary_recognition import TextCandidate,TextObservation
from app.core.structure_build import build_final_structure
APP=QApplication.instance() or QApplication([])

def test_inner_hole_nomination_survives_added_page_frame():
    ink=np.zeros((150,180),np.uint8)
    cv2.circle(ink,(70,75),18,1,3)
    cv2.line(ink,(90,75),(140,75),1,2)
    before=[box for _,_,box in _circular_holes(ink,200,10)]
    cv2.rectangle(ink,(4,4),(175,145),1,2)
    after=[box for _,_,box in _circular_holes(ink,200,10)]
    assert (51,56,39,39) not in before # inner not exterior contour
    assert before
    assert set(before)<=set(after)

def test_empty_ring_has_no_independent_internal_glyph_and_is_not_a_symbol():
    binary=np.full((110,140),255,np.uint8)
    cv2.circle(binary,(60,55),18,0,3)
    cv2.rectangle(binary,(2,2),(137,107),0,1)
    z=np.zeros_like(binary,dtype=bool)
    texts,paths,records,mask,replaced=recover_circular_symbols(binary,(),protected=z,text_owned=z,dpi=200)
    assert not texts and not paths and not records and not mask.any()

def test_near_identical_cell_locators_join_without_transitive_drift():
    cells={(10,20,90,60):(('A',(12,25,50,10)),),
           (10,21,90,60):(('B',(12,35,50,10)),),
           (10,23,90,60):(('C',(12,45,50,10)),),
           (10,61,90,90):(('D',(12,65,50,10)),)}
    groups=_coalesce_cell_candidates(cells)
    assert len(groups)==3
    assert len(groups[(10,20,90,60)])==2
    assert (10,61,90,90) in groups

def test_cell_measurement_reuses_complete_observation_without_moving_bbox():
    original=TextCandidate('A (12)',(10,10,50,20),.99,'text_candidate',source='rapidocr-tile',
      character_boxes=((10,10,5,10),(20,10,5,10),(25,10,5,10),(30,10,5,10),(35,10,5,10)))
    current=replace(original,bbox=(11,10,49,16),character_boxes=original.character_boxes[:4],
      pre_cell_observation=TextObservation.capture(original,0))
    measured=_measurement_row(current)
    assert measured.bbox==current.bbox and measured.quad==current.quad
    assert measured.character_boxes==original.character_boxes
    different=replace(current,text='B (12)')
    assert _measurement_row(different) is different

def sample():
    gray=np.full((100,180),255,np.uint8)
    cv2.putText(gray,'ABC',(28,47),cv2.FONT_HERSHEY_SIMPLEX,.8,0,1,cv2.LINE_8)
    quad=((20.,20.),(100.,20.),(100.,55.),(20.,55.))
    text=TextCandidate('ABC',(20,20,80,35),.99,'text_candidate',quad=quad,source='rapidocr-tile')
    z=np.zeros_like(gray);empty=np.full_like(gray,255)
    s=build_final_structure(source_size_px=gray.shape[::-1],contour_binary=empty,contours=(),texts=(text,),
      editable_text_source_mask=z,source_text_outline_mask=z,uncertain_text_outline_mask=z,preview_binary=gray)
    return gray,s

def test_source_cap_display_only_never_changes_content_or_source_masks():
    gray,s=sample();t=refine_source_supported_scan_displays(gray,s)
    assert t.texts[0].display_quad is not None
    a,b=asdict(s.texts[0]),asdict(t.texts[0]);a.pop('display_quad');b.pop('display_quad');assert a==b
    for n in ('contour_binary','preview_binary','editable_text_source_mask','source_text_outline_mask','uncertain_text_outline_mask'):
      assert np.array_equal(getattr(s,n),getattr(t,n))
    assert t.straight_lines==s.straight_lines and t.contours==s.contours

def test_source_cap_display_abstains_for_manual_review_and_dimensions():
    gray,s=sample()
    for text in (replace(s.texts[0],reviewed=True),replace(s.texts[0],text='123')):
      t=replace(s,texts=(text,)); assert refine_source_supported_scan_displays(gray,t) is t

def test_closed_frame_with_separate_inner_glyphs_not_treated_as_text_body():
    gray,s=sample()
    cv2.rectangle(gray,(23,23),(96,51),0,1)
    with pytest.raises(ValueError,match='ENCLOSURE_CONTAINS_SEPARATE_INK'):
      _source_fit(gray,s.texts[0],reject_enclosing_components=True)

@pytest.mark.parametrize('reading,expected',[(None,False),(('D',.99),False),(('0',.99),True)])
def test_low_grid_glyph_requires_registered_original_agreement(monkeypatch,reading,expected):
    from types import SimpleNamespace
    from app.ocr import scanned_circular_symbols as s
    seen=[]
    monkeypatch.setattr(s,'_recognize',lambda image:(seen.append(image.shape) or reading))
    scan=SimpleNamespace(ratio=2,pixels=np.full((100,120),255,np.uint8))
    text=TextCandidate('0',(10,12,8,12),.99,'text_candidate')
    result=s.confirm_input_glyph_on_registered_original(text,scan)
    assert result['accepted'] is expected and seen==[(24,16)]
    assert result['original_bbox']==(20,24,36,48)
    assert text.text=='0' # a contrary original reading is not a replacement

def test_registered_glyph_confirmation_honors_crop_origin(monkeypatch):
    from types import SimpleNamespace
    from app.ocr import scanned_circular_symbols as s
    monkeypatch.setattr(s,'_recognize',lambda image:('E',.99))
    scan=SimpleNamespace(ratio=2,pixels=np.full((100,120),255,np.uint8))
    text=TextCandidate('E',(10,12,8,12),.99,'text_candidate')
    result=s.confirm_input_glyph_on_registered_original(text,scan,(4,5,80,90))
    assert result['original_bbox']==(28,34,44,58)
    assert result['accepted']
