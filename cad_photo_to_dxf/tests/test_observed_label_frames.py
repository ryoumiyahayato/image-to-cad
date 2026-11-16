from copy import deepcopy
from pathlib import Path
import cv2
import ezdxf
import numpy as np
import pytest
from app.geometry.observed_label_frames import recover_observed_label_frames, stroke_rings
from app.export.observed_frame_entities import add_observed_frame, BACKUP_LAYER, APPID
from app.geometry.raster_trace import trace_binary


def fixture(*,width=82,height=38,thickness=1,shift=(0,0),tone=0):
    dx,dy=shift;x,y=30+dx,28+dy
    g=np.full((height+80+dy,width+90+dx),255,np.uint8)
    cv2.rectangle(g,(x,y),(x+width,y+height),int(tone),thickness)
    # Independent interior content never contributes to the frame claim.
    cv2.putText(g,'AB',(x+8,y+min(height-4,25)),cv2.FONT_HERSHEY_SIMPLEX,.5,0,1)
    _,lab,st,_=cv2.connectedComponentsWithStats(np.uint8(g<254),connectivity=8)
    v=int(lab[y,x]);xx,yy,ww,hh,area=map(int,st[v])
    proof=dict(frame_component_bbox=(xx,yy,ww,hh),frame_component_pixels=area,index=0)
    mask=lab==v;b=np.where(g<254,0,255).astype(np.uint8)
    return g,b,proof,mask


def recover(g,b,p,**kwargs):
    return recover_observed_label_frames(g,b,b.copy(),(p,),**kwargs)


@pytest.mark.parametrize('w,h',[(40,20),(82,38),(120,50),(180,40)])
@pytest.mark.parametrize('thickness',[1,2])
def test_complete_source_is_one_closed_native_frame(w,h,thickness):
    g,b,p,mask=fixture(width=w,height=h,thickness=thickness)
    original_g=g.copy();original_b=b.copy()
    out,paths,records,review=recover(g,b,p)
    assert len(paths)==len(records)==review['accepted']==1
    assert len(paths[0].points)==4 and records[0]['creates_connection'] is False
    assert np.array_equal(g,original_g) and np.array_equal(b,original_b)
    assert np.array_equal(out[~mask],b[~mask]) and np.all(out[mask]==255)
    assert records[0]['source_pixels']==int(mask.sum())
    assert records[0]['historical_identity']=='NOT_PROVEN'
    restored=np.zeros_like(mask)
    for y,a,z in records[0]['source_runs_y_x0_x1']:restored[y,a:z]=True
    assert np.array_equal(restored,mask)
    old=trace_binary(np.where(mask,0,255).astype(np.uint8))
    assert records[0]['original_boundary_paths_px']==tuple(p.points for p in old)


@pytest.mark.parametrize('shift',[(5,3),(21,17),(75,40)])
def test_translation_changes_only_origin(shift):
    g,b,p,_=fixture();_,paths,recs,_=recover(g,b,p)
    a,c,q,_=fixture(shift=shift);_,path2,rec2,_=recover(a,c,q)
    assert np.allclose(np.asarray(path2[0].points)-shift,paths[0].points)
    assert np.allclose(rec2[0]['side_widths_px'],recs[0]['side_widths_px'])


@pytest.mark.parametrize('kind',['gap','branch','internal_branch','extra_hole','missing_corner','curved','clipped','stale'])
def test_unproved_or_changed_component_is_not_claimed(kind):
    g,b,p,mask=fixture();x,y,w,h=p['frame_component_bbox']
    if kind=='gap':g[y:y+2,x+20:x+23]=255
    if kind=='branch':cv2.line(g,(x+w-1,y+15),(x+w+12,y+15),0,1)
    if kind=='internal_branch':cv2.line(g,(x+15,y),(x+15,y+8),0,1)
    if kind=='extra_hole':cv2.rectangle(g,(x+25,y),(x+35,y+8),0,1)
    if kind=='missing_corner':g[y:y+2,x:x+2]=255
    if kind=='curved':g[y,x+10:x+w-10]=255;cv2.ellipse(g,(x+w//2,y),(w//2-10,7),0,0,180,0,1)
    if kind=='clipped':g=g[:,x+w-5:];b=np.where(g<254,0,255).astype(np.uint8)
    if kind=='stale':p['frame_component_pixels']+=1
    b=np.where(g<254,0,255).astype(np.uint8)
    before=b.copy();out,paths,recs,review=recover(g,b,p)
    assert not paths and not recs and np.array_equal(out,before)


@pytest.mark.parametrize('owner',['line','text','logo','signature','unknown'])
def test_existing_claim_or_protection_is_not_overridden(owner):
    g,b,p,mask=fixture();pro=np.zeros_like(g);point=np.argwhere(mask)[5];pro[tuple(point)]=255
    out,paths,recs,_=recover(g,b,p,protected_masks=(None,pro))
    assert not paths and not recs and np.array_equal(out,b)


def test_partially_retired_source_cannot_be_completed():
    g,b,p,mask=fixture();v=b.copy();v[tuple(np.argwhere(mask)[5])]=255
    out,paths,recs,_=recover_observed_label_frames(g,b,v,(p,))
    assert not paths and not recs and np.array_equal(out,v)


@pytest.mark.parametrize('tone',[96,128])
def test_grey_station_support_is_not_mistaken_for_missing_ink(tone):
    g,b,p,mask=fixture(thickness=2,tone=tone)
    out,paths,recs,_=recover(g,b,p)
    assert len(paths)==1 and np.array_equal(out[~mask],b[~mask])


def test_uniform_very_weak_ring_is_not_promoted():
    g,b,p,_=fixture(tone=240)
    out,paths,recs,_=recover(g,b,p)
    assert not paths and np.array_equal(out,b)


def test_no_candidate_is_noop():
    g,b,p,_=fixture();out,paths,recs,rv=recover_observed_label_frames(g,b,b,())
    assert out is b and not paths and rv['accepted']==0


def test_duplicate_observation_cannot_double_claim():
    g,b,p,_=fixture();out,paths,recs,rv=recover_observed_label_frames(g,b,b,(p,deepcopy(p)))
    assert len(paths)==1 and len(recs)==1 and rv['accepted']==1


@pytest.mark.parametrize('sx,sy',[(.254,.254),(.2,.3),(2.,1.5)])
def test_native_serialization_source_backup_and_save(tmp_path,sx,sy):
    g,b,p,_=fixture(thickness=2);_,paths,recs,_=recover(g,b,p)
    d=ezdxf.new('R2010');d.layers.new('ENGINEERING_SYMBOL')
    transform=lambda x,y:((x+.5)*sx,(g.shape[0]-y-.5)*sy)
    e,bounds=add_observed_frame(d,d.modelspace(),recs[0],center_transform=transform,layer='ENGINEERING_SYMBOL')
    assert e.dxftype()=='LWPOLYLINE' and e.closed and len(e)==4
    assert all(v[2]>0 and v[2]==v[3] for v in e)
    assert e.has_xdata(APPID)
    layer=d.layers.get(BACKUP_LAYER);assert layer.is_off() and layer.is_frozen() and layer.is_locked()
    backups=list(d.modelspace().query(f'LWPOLYLINE[layer=="{BACKUP_LAYER}"]'))
    assert len(backups)==2
    for ent,source in zip(backups,recs[0]['original_boundary_paths_px']):
        assert np.allclose([(v[0],v[1]) for v in ent],[transform(*q) for q in source])
    file=tmp_path/'first.dxf';d.saveas(file);fresh=ezdxf.readfile(file)
    native=[v for v in fresh.modelspace() if v.dxf.layer=='ENGINEERING_SYMBOL'][0]
    assert native.closed and np.allclose(np.array(list(native)),np.array(list(e)))
    assert not fresh.audit().errors


@pytest.mark.parametrize('bad',[0.,-1.,float('nan'),float('inf')])
def test_invalid_width_is_not_serialized(bad):
    g,b,p,_=fixture();_,_,recs,_=recover(g,b,p);r=deepcopy(recs[0]);r['side_widths_px']=(bad,1,1,1)
    d=ezdxf.new();d.layers.new('ENGINEERING_SYMBOL')
    with pytest.raises(ValueError):add_observed_frame(d,d.modelspace(),r,center_transform=lambda x,y:(x,y),layer='ENGINEERING_SYMBOL')
    assert len(d.modelspace())==0


def test_visible_source_permission_is_idempotent():
    g,b,p,_=fixture();out,paths,recs,_=recover(g,b,p)
    twice,p2,r2,_=recover_observed_label_frames(g,b,out,(p,))
    assert not p2 and not r2 and np.array_equal(twice,out)


@pytest.mark.parametrize('size',[(82,38),(120,50),(180,40)])
def test_rounded_thick_caps_do_not_become_unobserved_sharp_miters(size):
    g,b,p,_=fixture(width=size[0],height=size[1],thickness=3)
    out,paths,recs,review=recover(g,b,p)
    assert not paths and not recs and np.array_equal(out,b)
    assert review['decisions'][0]['reason']=='BIDIRECTIONAL_SUPPORT_FAILED'


def test_complete_automatic_upstream_membership_is_required():
    from app.ocr.auxiliary_recognition import TextCandidate
    from app.ocr.boxed_label_members import observe_boxed_members
    g,b,p,mask=fixture(width=96,height=38)
    x,y,w,h=p['frame_component_bbox']
    g[y+1:y+h-1,x+1:x+w-1]=255
    for j,ch in enumerate('234'):
        cv2.putText(g,ch,(x+17+20*j,y+27),cv2.FONT_HERSHEY_SIMPLEX,.65,0,1,cv2.LINE_AA)
    b=np.where(g<254,0,255).astype(np.uint8)
    box=(x-3,y-3,w+6,h+6)
    bx,by,bw,bh=box
    t=TextCandidate('234',box,.99,'text_candidate',
        quad=((bx,by),(bx+bw,by),(bx+bw,by+bh),(bx,by+bh)),source='rapidocr-overview')
    observation=observe_boxed_members(g,t)
    assert observation is not None
    out,paths,recs,_=recover(g,b,observation)
    assert len(paths)==1 and t.text=='234' and np.array_equal(out[~mask],b[~mask])
