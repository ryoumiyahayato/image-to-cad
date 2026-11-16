"""Source-component and layout contracts; synthetic ink, no file/page answers."""
from dataclasses import replace
from types import SimpleNamespace
import json
import cv2
import numpy as np
import pytest
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.dimension_chain_review import (
    observe_chain, review_dimension_chains, _isolated_label_view,
    preserve_disjoint_dimension_members,
)
from app.ocr.ocr_fast import prepare_safe_candidate
from app.geometry.content_ownership import _candidate_region_mask


def fixture(dx=0,dy=0,foreign='ruler'):
    image=np.full((180+dy,420+dx),255,np.uint8)
    cv2.line(image,(30+dx,110+dy),(360+dx,110+dy),0,1)
    for x in [50,100,210,270,340]:cv2.line(image,(x+dx,65+dy),(x+dx,116+dy),0,1)
    for x in [67,139,235,285]:
        cv2.putText(image,'5',(x+dx,94+dy),cv2.FONT_HERSHEY_SIMPLEX,.65,0,1,cv2.LINE_8)
        image[80+dy:85+dy,x+15+dx:x+17+dx]=0
        image[80+dy:85+dy,x+20+dx:x+22+dx]=0
    if foreign!='none':
        cv2.line(image,(85+dx,91+dy),(96+dx,91+dy),0,1)
    if foreign in {'ruler','touch'}:
        cv2.line(image,(96+dx,91+dy),(96+dx,110+dy),0,1)
    if foreign=='touch':
        cv2.line(image,(75+dx,91+dy),(96+dx,91+dy),0,1)
    t=TextCandidate('5? 5? 5? 5?',(29+dx,55+dy,335,65),.61,'text_candidate',source='rapidocr-overview')
    return image,t


def reader(token='5"'):
    def read(images):
        values=['5' if im.shape[1]<im.shape[0] else token for im in images]
        return SimpleNamespace(txts=values,scores=[.99]*len(images))
    return read


def test_foreign_ruler_in_bounding_rectangle_is_not_character_overlap():
    im,t=fixture();obs=observe_chain(im,t)
    assert obs is not None and len(obs.labels)==4
    box,comps=obs.labels[0],obs.components[0]
    view,removed=_isolated_label_view(im,box,comps)
    assert removed>0
    x,y,w,h=box
    assert np.all((view==im[y:y+h,x:x+w]) | (view==255))
    for a,b,c,d in comps:
        assert np.array_equal(view[b-y:b-y+d,a-x:a-x+c],im[b:b+d,a:a+c])


def test_unknown_foreign_component_is_not_erased_from_observation():
    im,t=fixture(foreign='unknown');obs=observe_chain(im,t)
    assert obs is not None
    output,records=review_dimension_chains(im,[t],recognize=reader())
    assert all(q.bbox[0]>100 for q in output)
    assert records[0]['labels'][0]['reason']!='independent_glyphs_and_unit_marks'


def test_genuinely_connected_character_is_not_cut_away():
    im,t=fixture(foreign='touch');obs=observe_chain(im,t)
    assert obs is not None
    output,records=review_dimension_chains(im,[t],recognize=reader())
    assert all(q.bbox[0]>100 for q in output)
    assert records[0]['labels'][0]['reason']!='independent_glyphs_and_unit_marks'


@pytest.mark.parametrize('dx,dy',[(0,0),(17,11),(60,30)])
def test_translated_rectangular_overlap_same_outcome(dx,dy):
    im,t=fixture(dx,dy);before=im.copy()
    out,records=review_dimension_chains(im,[t],recognize=reader())
    assert len(out)==4 and all(q.text=='5"' for q in out)
    assert np.array_equal(im,before)
    assert records[0]['labels'][0]['observation_excluded_neighbor_core_pixels']>0


def test_isolated_high_confidence_token_contradiction_not_ignored():
    im,t=fixture();out,records=review_dimension_chains(im,[t],recognize=reader('8"'))
    assert out==[t] and not records


def test_isolation_is_only_observation_not_pixel_edit():
    im,t=fixture();copy=im.copy();obs=observe_chain(im,t)
    for box,comp in zip(obs.labels,obs.components):_isolated_label_view(im,box,comp)
    assert np.array_equal(im,copy)


def test_layout_does_not_reacquire_ruler():
    im,t=fixture();out,_=review_dimension_chains(im,[t],recognize=reader())
    observed=out[0];raw=prepare_safe_candidate(im,observed)
    result=preserve_disjoint_dimension_members(im,observed,raw)
    assert result.text==observed.text and result.bbox==observed.bbox
    assert result.character_boxes==observed.character_boxes
    assert not result.replacement_safe
    source_mask=_candidate_region_mask(result,im.shape)
    assert source_mask[91,87]==0
    assert np.all(source_mask[im<160]<=255)
    assert json.loads(result.review_note)['source_deletion_authority']=='normal_pipeline_only'


@pytest.mark.parametrize('change',[
 {'source':'manual'}, {'reviewed':True}, {'approved':False}, {'character_boxes':()},
 {'character_boxes':((0,0,3,3),)}, {'character_boxes':((67,80,50,30),)},
])
def test_unverified_or_mutated_observation_cannot_override_layout(change):
    im,t=fixture();out,_=review_dimension_chains(im,[t],recognize=reader());q=out[0]
    raw=prepare_safe_candidate(im,q)
    assert preserve_disjoint_dimension_members(im,replace(q,**change),raw)==raw


def test_other_content_cannot_borrow_component_record():
    im,t=fixture();out,_=review_dimension_chains(im,[t],recognize=reader());q=out[0]
    raw=replace(prepare_safe_candidate(im,q),text='8"')
    assert preserve_disjoint_dimension_members(im,q,raw)==raw


@pytest.mark.parametrize('gray',[None,np.zeros((3,3,3),np.uint8),np.zeros((3,3),float)])
def test_invalid_source_cannot_override(gray):
    im,t=fixture();out,_=review_dimension_chains(im,[t],recognize=reader());q=out[0]
    raw=prepare_safe_candidate(im,q)
    assert preserve_disjoint_dimension_members(gray,q,raw)==raw


def test_clean_existing_dimension_layout_unchanged():
    im,t=fixture(foreign='none');out,_=review_dimension_chains(im,[t],recognize=reader())
    for q in out:
        raw=prepare_safe_candidate(im,q)
        assert preserve_disjoint_dimension_members(im,q,raw)==raw


@pytest.mark.parametrize('box',[(-1,10,10,10),(0,0,0,10),(10,10,-5,10),(999,10,20,20),(0,0,400,400)])
def test_invalid_observed_box_no_override(box):
    im,t=fixture();out,_=review_dimension_chains(im,[t],recognize=reader());q=replace(out[0],bbox=box)
    assert preserve_disjoint_dimension_members(im,q,q)==q
