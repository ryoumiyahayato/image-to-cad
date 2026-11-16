
"""Token/glyph source agreement: no expected word, grammar or mask expansion."""
from dataclasses import replace
from types import SimpleNamespace
import json

import cv2
import numpy as np
import pytest

from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.source_token_review import (
    review_source_tokens, _single_glyph, _source_tokens, _eligible, _white_views,
)

def sample():
    im = np.full((20, 110), 255, np.uint8)
    for x in (5, 11, 17, 23):
        im[5:13, x:x+3] = 0
    for x in (50, 56, 62):
        im[4:14, x:x+3] = 0
    # Gray edge observations retained for recognition, not made black or white.
    im[6:12,65]=192
    box=(0,0,110,20)
    item=TextCandidate(
        "BASE 8/A",box,.93,"text_candidate",quad=((0.,0.),(110.,0.),(110.,20.),(0.,20.)),
        source="rapidocr-line",character_boxes=((1,2,3,4),),
        replacement_safe=False,display_quad=((1.,1.),(108.,1.),(108.,18.),(1.,18.)),
    )
    return im,item

class Reader:
    def __init__(self, words=("BASE","BASE","8/4","8/4"), glyph=("4","4"), word_scores=None, glyph_scores=None):
        self.words=words; self.glyph=glyph
        self.word_scores=word_scores or (.99,)*len(words)
        self.glyph_scores=glyph_scores or (.99,)*len(glyph)
        self.calls=[]
    def __call__(self,images):
        self.calls.append([x.copy() for x in images])
        if len(self.calls)==1:
            return SimpleNamespace(txts=self.words,scores=self.word_scores)
        return SimpleNamespace(txts=self.glyph,scores=self.glyph_scores)

def test_source_supported_substitution_preserves_geometry_authority_and_spacing():
    image,item=sample();before=image.copy();r=Reader()
    out,proof=review_source_tokens(image,[item],recognize=r)
    assert out[0].text=="BASE 8/4"
    for name in ("bbox","quad","character_boxes","display_quad","rotation_deg","approved","reviewed","replacement_safe"):
        assert getattr(out[0],name)==getattr(item,name)
    assert out[0].confidence<=item.confidence
    assert np.array_equal(before,image)
    assert proof[0]["before"]==item.text
    assert proof[0]["source_masks_modified"] is False
    assert 192 in r.calls[1][0]
    assert "8/A" in out[0].review_note
    assert item.text=="BASE 8/A"

@pytest.mark.parametrize("words", [
    ("BASE","BASE","8/4","8/9"), # no reading agreement
    ("BASE","BASE","84","84"), # cannot drop source punctuation
    ("BASE","BASE","8/44","8/44"), # cannot add characters
    ("BASE","BASE","8-4","8-4"), # punctuation replacement forbidden
    ("BASE","BASE","9/4","9/4"), # >one substitution within one token
    ("","BASE","8/4","8/4"),
    ("BASE","BASE","中/4","中/4"),
])
def test_word_disagreement_or_invalid_mapping_preserves_old(words):
    im,item=sample();out,records=review_source_tokens(im,[item],recognize=Reader(words=words))
    assert out==[item];assert records==[]

@pytest.mark.parametrize("glyph,scores", [
    (("A","A"),(.99,.99)),
    (("4","A"),(.99,.99)),
    (("4","4"),(.89,.99)),
    (("44","44"),(.99,.99)),
    (("4","4"),(float("nan"),.99)),
    (("4","4"),(1.01,.99)),
    (("",""),(.99,.99)),
])
def test_isolated_glyph_conflict_or_weak_evidence_never_changes_text(glyph,scores):
    im,item=sample();out,rec=review_source_tokens(im,[item],recognize=Reader(glyph=glyph,glyph_scores=scores))
    assert out==[item];assert rec==[]

@pytest.mark.parametrize("scores",[(.99,.99,.89,.99),(.99,.99,float("nan"),.99),(.99,.99,float("inf"),.99)])
def test_word_score_guard(scores):
    im,item=sample();out,rec=review_source_tokens(im,[item],recognize=Reader(word_scores=scores))
    assert out==[item];assert rec==[]

@pytest.mark.parametrize("change",[
    {"reviewed":True},{"approved":False},{"rotation_deg":90},
    {"source":"pdf-native"},{"confidence":float("nan")},
    {"text":"中文 8/A"},{"kind":"signature_candidate"},
])
def test_ineligible_candidates_do_not_invoke_recognition(change):
    im,item=sample();r=Reader()
    c=replace(item,**change);out,rec=review_source_tokens(im,[c],recognize=r)
    assert out==[c] and not rec and not r.calls

def test_bad_results_or_optional_reader_failure_preserve_detection():
    im,item=sample()
    def broken(_):raise RuntimeError("test inference failure")
    assert review_source_tokens(im,[item],recognize=broken)==([item],[])
    assert review_source_tokens(im,[item],recognize=lambda _:SimpleNamespace(txts=["BASE"],scores=[.99]))==([item],[])

def test_touching_observation_edge_rejects_incomplete_geometry():
    im,item=sample();im[0,5]=0;r=Reader()
    assert review_source_tokens(im,[item],recognize=r)==([item],[])
    assert not r.calls

def test_single_character_word_is_not_relabelled_from_context():
    im,item=sample();im[:,50:]=255;im[4:14,50:53]=0
    im[5:13,29:32]=0
    c=replace(item,text="LABEL I")
    r=Reader(words=("LABEL","LABEL","1","1"),glyph=("1","1"))
    out,rec=review_source_tokens(im,[c],recognize=r)
    assert out==[c] and not rec and len(r.calls)==1

def test_extra_source_component_is_not_removed_to_fit_string_length():
    im,item=sample()
    # An extra isolated source pixel in the token invalidates one-character-per-component mapping.
    im[17,64]=0
    out,rec=review_source_tokens(im,[item],recognize=Reader())
    assert out==[item] and not rec

def test_disjoint_glyph_extraction_preserves_gray_not_binary():
    im,item=sample();tokens=_source_tokens(im,item.bbox)
    measured=_single_glyph(im,tokens[1][0],"8/4",2)
    assert measured is not None and 192 in measured[0]

def test_actual_image_and_candidate_order_are_not_target_coordinates():
    im,item=sample();larger=np.pad(im,((7,9),(19,11)),constant_values=255)
    moved=replace(item,bbox=(19,7,110,20),quad=tuple((x+19,y+7) for x,y in item.quad))
    out,rec=review_source_tokens(larger,[moved],recognize=Reader())
    assert out[0].text=="BASE 8/4"
    assert rec[0]["checks"][0]["glyph_bbox"][0] > 19

def test_valid_preexisting_reading_unchanged():
    im,item=sample();r=Reader(words=("BASE","BASE","8/A","8/A"))
    out,rec=review_source_tokens(im,[item],recognize=r)
    assert out==[item] and not rec and len(r.calls)==1

def test_new_version_is_cache_distinct():
    from app.core.processing import ProductionProcessingConfig
    assert "source-token-glyph-review-v1" in ProductionProcessingConfig().algorithm_version

def test_white_views_only_add_white_pixels_and_keep_native_gray():
    im=np.array([[255,192,0],[255,100,255]],np.uint8)
    for view in _white_views(im):
        y=(view.shape[0]-im.shape[0])//2;x=(view.shape[1]-im.shape[1])//2
        assert np.array_equal(view[y:y+2,x:x+3,0],im)
        assert np.all(view[:y]==255)

@pytest.mark.parametrize("old,new", [
    ("O/0","0/0"), ("0/O","O/O"), ("o/0","0/0"),
    ("I/1","1/1"), ("l/1","1/1"), ("1/I","I/I"),
    ("A/b","A/B"), ("a/B","A/B"),
])
def test_confident_same_model_cannot_authorize_identity_ambiguous_substitution(old,new):
    im,item=sample()
    c=replace(item,text="BASE "+old)
    changed=next(b for a,b in zip(old,new) if a!=b)
    r=Reader(words=("BASE","BASE",new,new),glyph=(changed,changed),
             word_scores=(.9999,)*4,glyph_scores=(.9999,.9999))
    out,records=review_source_tokens(im,[c],recognize=r)
    assert out==[c] and not records
    assert len(r.calls)==1
