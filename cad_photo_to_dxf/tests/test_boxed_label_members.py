from dataclasses import replace
import cv2
import numpy as np
import pytest
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.boxed_label_members import observe_boxed_members, refine_boxed_label_members


def fixture(dx=0,dy=0,scale=1,text='234'):
    im=np.full((170+dy,300+dx),255,np.uint8)
    x,y,w,h=60+dx,40+dy,96*scale,38*scale
    cv2.rectangle(im,(x,y),(x+w,y+h),0,scale)
    for j,char in enumerate(text):
        cv2.putText(im,char,(x+(17+20*j)*scale,y+27*scale),cv2.FONT_HERSHEY_SIMPLEX,
                    .65*scale,0,scale,cv2.LINE_AA)
    b=(x-3*scale,y-3*scale,w+6*scale,h+6*scale)
    bx,by,bw,bh=b
    c=TextCandidate(text,b,.99,'text_candidate',quad=((bx,by),(bx+bw,by),(bx+bw,by+bh),(bx,by+bh)),
                    source='rapidocr-overview',replacement_safe=False)
    return im,c


@pytest.mark.parametrize('text',['234','578','ABC','R23','111','000'])
def test_complete_source_members_without_content_guess(text):
    im,c=fixture(text=text);before=im.copy();proofs=[]
    result,records=refine_boxed_label_members(im,(c,),verified_sources=proofs)
    assert len(records)==1
    t=result[0];assert t.text==c.text and t.confidence==c.confidence
    assert t.reviewed==c.reviewed and t.approved==c.approved and t.source==c.source
    assert t.bbox[3]<c.bbox[3] and len(t.character_boxes)==len(text)
    assert t.pre_cell_observation.bbox==c.bbox
    assert t.replacement_safe and len(proofs)==1
    assert np.array_equal(before,im)
    p=proofs[0]; lx,ly,rx,ry=p.bounds
    assert np.all(im[ly:ry,lx:rx][p.mask>0]<254)
    assert not np.any(p.mask[40-ly,:])


@pytest.mark.parametrize('dx,dy',[(0,0),(17,11),(51,23),(73,41)])
def test_translation_preserves_members(dx,dy):
    im,c=fixture();a=observe_boxed_members(im,c)
    im,t=fixture(dx,dy);b=observe_boxed_members(im,t)
    assert a and b
    assert tuple((x-dx,y-dy,w,h) for x,y,w,h in b['character_boxes'])==a['character_boxes']


@pytest.mark.parametrize('kind',['open','dot','touch','extra','cropped','white','counter','skew'])
def test_unproved_context_is_not_removed(kind):
    im,c=fixture()
    if kind=='open':im[38:44,100:106]=255
    if kind=='dot':im[47,70]=0
    if kind=='touch':cv2.line(im,(60,55),(80,55),0,1)
    if kind=='extra':cv2.putText(im,'7',(140,65),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    if kind=='cropped':im=im[:,150:];c=replace(c,bbox=(0,37,100,44),quad=((0,37),(100,37),(100,81),(0,81)))
    if kind=='white':im[:]=255
    if kind=='counter':im[:]=255;cv2.putText(im,'00',(65,75),cv2.FONT_HERSHEY_SIMPLEX,1,0,1)
    if kind=='skew':c=replace(c,quad=((57,37),(159,39),(159,83),(57,81)))
    result,records=refine_boxed_label_members(im,(c,))
    assert not records and result==(c,)


@pytest.mark.parametrize('kwargs',[
 {'reviewed':True},{'display_quad':((1,1),(2,1),(2,2),(1,2))},
 {'rotation_deg':90.},{'rotation_deg':.2},{'text':'A B'},{'text':'-3'},
 {'text':'三百'},{'text':'Z'},{'text':'123456789'}, {'source':'manual'},
 {'confidence':.01},{'approved':False},
])
def test_not_eligible_unchanged(kwargs):
    im,c=fixture();c=replace(c,**kwargs)
    result,records=refine_boxed_label_members(im,(c,))
    assert not records and result==(c,)


@pytest.mark.parametrize('axis',[0,1])
def test_protected_frame_stops_claim(axis):
    im,c=fixture();protected=np.zeros_like(im)
    protected[50,80] =255
    masks=(protected,None) if axis==0 else (None,protected)
    result,records=refine_boxed_label_members(im,(c,),protected_masks=masks)
    assert not records and result==(c,)


def test_two_candidates_cannot_share_frame():
    im,c=fixture();other=replace(c,text='789')
    out,records=refine_boxed_label_members(im,(c,other))
    assert not records and out==(c,other)


def test_idempotent_no_shrinking_loop():
    im,c=fixture();out,recs=refine_boxed_label_members(im,(c,))
    assert recs
    twice,recs2=refine_boxed_label_members(im,out)
    assert twice==out and not recs2


def test_source_identity_is_not_inferred():
    im,c=fixture();wrong=replace(c,text='999')
    out,recs=refine_boxed_label_members(im,(wrong,))
    # A source-member proof changes layout/ownership, not content identity.
    assert out[0].text=='999' and out[0].confidence==wrong.confidence


@pytest.mark.parametrize("text", ["ABC", "R23"])
def test_antialias_touching_letters_are_not_split(text):
    im,c=fixture(text=text)
    im[43:78,63:156]=255
    cv2.putText(im,text,(77,67),cv2.FONT_HERSHEY_SIMPLEX,.65,0,1,cv2.LINE_AA)
    out,recs=refine_boxed_label_members(im,(c,))
    assert out==(c,) and not recs


@pytest.mark.parametrize("side", ["left", "right", "top", "bottom"])
def test_frame_connected_to_external_geometry_is_not_a_label_frame(side):
    im,c=fixture()
    joins={"left":((30,59),(60,59)), "right":((156,59),(180,59)),
           "top":((110,10),(110,40)), "bottom":((110,78),(110,110))}
    cv2.line(im,*joins[side],0,1)
    out,recs=refine_boxed_label_members(im,(c,))
    assert out==(c,) and not recs


def test_complete_frame_is_required_even_when_crop_contains_glyphs():
    im,c=fixture()
    # Ring's upper border is exactly at the input edge; completeness cannot
    # be established from this crop even though all interior glyphs survive.
    im=im[40:,:]
    c=replace(c,bbox=(57,0,102,41),quad=((57,0),(159,0),(159,41),(57,41)))
    out,recs=refine_boxed_label_members(im,(c,))
    assert out==(c,) and not recs
