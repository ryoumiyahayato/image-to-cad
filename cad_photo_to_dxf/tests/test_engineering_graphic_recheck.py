"""Only source-backed accepted members may replace protected engineering ink."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import cv2
import pytest
from PySide6.QtWidgets import QApplication
from app.ocr.logo_detection import LogoRegion
from app.ocr.auxiliary_recognition import TextCandidate
from app.geometry.optimized_trace import _remaining_graphic_members, _rejected_enclosure_text_permissions
from app.ocr.scanned_circular_symbols import recover_circular_symbols
APP=QApplication.instance() or QApplication([])

def region(kind='engineering_graphic'):
    m=np.array([[0,64,0],[128,255,192],[0,255,0]],np.uint8)
    return LogoRegion((5,6,3,3),m,.95,1,2,visual_kind=kind)

def test_partial_retirement_preserves_bbox_alpha_and_original():
    r=region();original=r.mask.copy();accepted=np.zeros((20,20),bool);accepted[7,6]=True
    out,log=_remaining_graphic_members((r,),accepted)
    expected=original.copy();expected[1,1]=0
    assert len(out)==1 and out[0].bbox==r.bbox
    assert np.array_equal(out[0].mask,expected) and np.array_equal(r.mask,original)
    assert log[0]['retired_source_pixels']==1 and log[0]['remaining_source_pixels']==4

@pytest.mark.parametrize('kind',['graphic_mark','wordmark','signature','stamp'])
def test_other_classes_are_untouched(kind):
    r=region(kind);out,log=_remaining_graphic_members((r,),np.ones((20,20),bool))
    assert out[0] is r and not log

def test_full_acceptance_retires_only_its_graphic():
    r=region();other=region('graphic_mark');out,log=_remaining_graphic_members((r,other),np.ones((20,20),bool))
    assert out==(other,) and log[0]['retired_source_pixels']==5 and log[0]['remaining_source_pixels']==0

def test_unaccepted_graphic_is_identical():
    r=region();out,log=_remaining_graphic_members((r,),np.zeros((20,20),bool))
    assert out[0] is r and not log

def test_invalid_coordinates_do_not_authorize_deletion():
    r=replace(region(),bbox=(-1,6,3,3));out,log=_remaining_graphic_members((r,),np.ones((20,20),bool))
    assert out[0] is r and not log

def fixture():
    g=np.full((30,40),255,np.uint8);g[10:15,10:15]=192
    s=SimpleNamespace(editable_source=np.zeros_like(g),source_outline=np.zeros_like(g),uncertain_outline=np.where(g<255,255,0).astype(np.uint8))
    c=TextCandidate('Q',(9,9,7,7),.51,'text_candidate',replacement_safe=False)
    f=np.zeros_like(g,dtype=bool);f[12,12]=True
    return g,s,c,f

def test_permission_does_not_invent_source_or_mutate_masks():
    g,s,c,f=fixture();old=s.uncertain_outline.copy();mask=_rejected_enclosure_text_permissions(g,(c,),f,s)
    assert mask.sum()==25 and not np.any(mask&(g==255)) and np.array_equal(s.uncertain_outline,old)

@pytest.mark.parametrize('change',[{'confidence':.99},{'reviewed':True}])
def test_trusted_or_reviewed_carrier_stays_protected(change):
    g,s,c,f=fixture();assert not _rejected_enclosure_text_permissions(g,(replace(c,**change),),f,s).any()

def test_editable_and_backup_ownership_is_not_released():
    g,s,c,f=fixture();s.editable_source[12,12]=255;s.source_outline[12,12]=255
    mask=_rejected_enclosure_text_permissions(g,(c,),f,s);assert mask.sum()==24 and not mask[12,12]

def test_disjoint_candidate_cannot_release_pixels():
    g,s,c,f=fixture();f[:]=False;f[25,25]=True
    assert not _rejected_enclosure_text_permissions(g,(c,),f,s).any()

def test_retry_search_scope_does_not_nominate_other_objects(monkeypatch):
    from app.ocr import scanned_circular_symbols as sc
    monkeypatch.setattr(sc,'_glyph',lambda *a,**k:None)
    binary=np.full((160,260),255,np.uint8)
    for x in (65,195):cv2.circle(binary,(x,80),20,0,3);cv2.line(binary,(x,72),(x,88),0,2)
    z=np.zeros_like(binary,dtype=bool)
    out=recover_circular_symbols(binary,(),protected=z,text_owned=z,dpi=200,search_regions=((40,50,50,60),))
    assert out[2] and all(40<=r['center_px'][0]<90 for r in out[2])
    empty=recover_circular_symbols(binary,(),protected=z,text_owned=z,dpi=200,search_regions=())
    assert not empty[2] and not empty[3].any()
