from dataclasses import replace
from types import SimpleNamespace
import json
import cv2
import numpy as np
import pytest
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.dimension_chain_review import (
    observe_chain, review_dimension_chains, read_label, _raised_marks,
)


def chain_fixture(dx=0, dy=0):
    image = np.full((180+dy, 420+dx), 255, np.uint8)
    # One observed ruler and short intersecting witnesses, not a closed table.
    cv2.line(image,(30+dx,110+dy),(360+dx,110+dy),0,1)
    for x in [50,100,210,270,340]:
        cv2.line(image,(x+dx,65+dy),(x+dx,116+dy),0,1)
    # Four detached numeral/quote labels in different intervals.
    for x in [67,139,235,285]:
        cv2.putText(image, '5', (x+dx,94+dy), cv2.FONT_HERSHEY_SIMPLEX, .65, 0, 1, cv2.LINE_8)
        image[80+dy:85+dy,x+15+dx:x+17+dx] = 0
        image[80+dy:85+dy,x+20+dx:x+22+dx] = 0
    candidate=TextCandidate('5? 5? 5? 5?', (29+dx,55+dy,335,65), .61,'text_candidate',source='rapidocr-overview')
    return image,candidate


def reader(digit='5', token='5"', score=.99):
    def recognize(images):
        # Digit observations are taller than wide; whole dimensions are wider.
        values=[digit if a.shape[1] < a.shape[0] else token for a in images]
        return SimpleNamespace(txts=values,scores=[score]*len(images))
    return recognize


def test_observed_chain_requires_source_ruling_and_components():
    image,t=chain_fixture();o=observe_chain(image,t)
    assert o is not None and len(o.witnesses)==5 and len(o.labels)==4
    assert o.baseline==110


def test_pixels_and_parent_unchanged_by_review():
    image,t=chain_fixture();copy=image.copy()
    output,records=review_dimension_chains(image,[t],recognize=reader())
    assert np.array_equal(copy,image) and t.text=='5? 5? 5? 5?'
    assert records and len(output)==4
    assert all(c.text=='5"' and not c.reviewed and not c.replacement_safe for c in output)
    assert all(json.loads(c.review_note)['source_deletion_authority']=='normal_pipeline_only' for c in output)


@pytest.mark.parametrize('dx,dy',[(13,7),(50,40),(100,0)])
def test_translation_invariant(dx,dy):
    a,t=chain_fixture();b,u=chain_fixture(dx,dy)
    x=observe_chain(a,t);y=observe_chain(b,u)
    assert x and y
    assert y.labels==tuple((p+dx,q+dy,w,h) for p,q,w,h in x.labels)
    assert y.baseline==x.baseline+dy


@pytest.mark.parametrize('change',[
    {'approved':False},{'reviewed':True},{'confidence':.99},{'confidence':float('nan')},
    {'rotation_deg':90.0},{'rotation_deg':float('inf')},{'source':'manual'},
    {'text':'TABLE WOOD PANEL'},{'text':'plain'},{'bbox':(29,55,80,65)},
])
def test_ineligible_unchanged(change):
    image,t=chain_fixture();t=replace(t,**change)
    result,records=review_dimension_chains(image,[t],recognize=lambda _:pytest.fail('unexpected OCR'))
    assert result==[t] and not records


def test_no_baseline_is_not_a_chain():
    image,t=chain_fixture();image[108:113,:]=255
    assert observe_chain(image,t) is None


def test_only_three_witnesses_rejected():
    image,t=chain_fixture();image[65:118,49:52]=255;image[65:118,99:102]=255
    assert observe_chain(image,t) is None


def test_geometry_does_not_invent_crossing_gap():
    image,t=chain_fixture();image[108:113,140:190]=255
    assert observe_chain(image,t) is None


def test_does_not_supersede_reviewed_overlapping_text():
    image,t=chain_fixture();reviewed=replace(t,reviewed=True,bbox=(130,75,30,20),text='checked')
    out,records=review_dimension_chains(image,[t,reviewed],recognize=reader())
    assert out==[t,reviewed] and records==[]


@pytest.mark.parametrize('digit',['0','1','I','O','A','55',''])
def test_non_numeric_or_identity_ambiguity_not_guessed(digit):
    image,t=chain_fixture();out,records=review_dimension_chains(image,[t],recognize=reader(digit=digit))
    assert out==[t] and records==[]


@pytest.mark.parametrize('score',[.89,-.1,1.1,float('nan')])
def test_low_invalid_scores_no_authority(score):
    image,t=chain_fixture();out,records=review_dimension_chains(image,[t],recognize=reader(score=score))
    assert out==[t] and records==[]


def test_confident_whole_token_contradiction_vetoes():
    image,t=chain_fixture();out,records=review_dimension_chains(image,[t],recognize=reader(token='8"'))
    assert out==[t] and records==[]


def test_recognition_exception_preserves_parent():
    image,t=chain_fixture()
    def fail(_):raise RuntimeError('unavailable')
    out,records=review_dimension_chains(image,[t],recognize=fail)
    assert out==[t] and records==[]


def test_cancel_propagates():
    image,t=chain_fixture()
    def stop():raise InterruptedError('cancelled')
    with pytest.raises(InterruptedError):review_dimension_chains(image,[t],recognize=reader(),checkpoint=stop)


def test_absent_punctuation_not_inferred_from_numeric_context():
    image,t=chain_fixture()
    for x in [67,139,235,285]:image[80:85,x+15:x+22]=255
    out,records=review_dimension_chains(image,[t],recognize=reader())
    assert out==[t] and records==[]


def test_single_blob_does_not_become_two_quotes():
    gray=np.full((40,40),255,np.uint8);gray[10:12,10:15]=0
    assert _raised_marks(gray,[(10,10,5,2)],10,12) is None


def test_two_observed_upper_lobes_can_support_double_mark():
    gray=np.full((40,40),255,np.uint8);gray[10,10:14]=[80,80,200,80];gray[11,10:14]=80
    assert _raised_marks(gray,[(10,10,4,2)],10,12)==2


def test_low_position_short_strokes_not_unit_marks():
    gray=np.zeros((40,40),np.uint8)
    assert _raised_marks(gray,[(10,18,1,3)],10,12) is None


def test_large_upper_number_not_unit_mark():
    gray=np.zeros((40,40),np.uint8)
    assert _raised_marks(gray,[(10,10,5,9)],10,12) is None


@pytest.mark.parametrize('image',[None,np.zeros((1,1,3),np.uint8),np.zeros((5,5),float)])
def test_invalid_image_safe(image):
    _,t=chain_fixture();out,records=review_dimension_chains(image,[t],recognize=reader())
    assert out==[t] and records==[]
