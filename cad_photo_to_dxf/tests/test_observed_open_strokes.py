from __future__ import annotations
import copy
from pathlib import Path
import cv2
import ezdxf
import numpy as np
import pytest

from app.geometry.observed_open_strokes import recover_observed_open_strokes, _ordered_path, _fit
from app.export.observed_open_stroke_entities import add_observed_open_stroke, BACKUP_LAYER, VISIBLE_LAYER, APPID


def source(points=((20,70),(45,45),(80,35),(120,40),(150,55)),width=1.5,size=(180,110)):
    scale=8
    a=np.full((size[1]*scale,size[0]*scale),255,np.uint8)
    cv2.polylines(a,[np.rint(np.array(points)*scale).astype(np.int32)],False,0,
                  round(width*scale),cv2.LINE_AA)
    return cv2.resize(a,size,interpolation=cv2.INTER_AREA)


def run(gray,protected=None,visible=None,dpi=100.):
    binary=np.where(gray<254,0,255).astype(np.uint8)
    visible=binary if visible is None else visible
    return recover_observed_open_strokes(gray,binary,visible,
              protected_masks=(() if protected is None else (protected,)),dpi=dpi)


@pytest.mark.parametrize('angle',[0,20,45,70,90,135,180,225,270,315])
def test_straight_strokes_rotation(angle):
    center=np.array([100.,100.]);u=np.array([np.cos(np.radians(angle)),np.sin(np.radians(angle))])
    gray=source((center-u*70,center+u*70),width=1.8,size=(200,200))
    output,paths,records,review=run(gray)
    assert review['accepted']==1
    r=records[0]
    assert len(r['points_px'])>=2
    assert r['creates_connection'] is False
    assert r['source_to_pen_error_px']<=1 and r['pen_to_source_error_px']<=1
    assert not np.any(output==0)


@pytest.mark.parametrize('offset',[(0,0),(5,8),(20,30)])
def test_isolated_curve_translation_and_complete_source_backup(offset):
    points=np.array(((20,70),(45,45),(80,35),(120,40),(150,55)))+offset
    gray=source(points,width=1.8,size=(220,170));original=gray.copy()
    binary=np.where(gray<254,0,255).astype(np.uint8);before=binary.copy()
    output,paths,records,review=recover_observed_open_strokes(gray,binary,binary,dpi=100.)
    assert np.array_equal(gray,original) and np.array_equal(binary,before)
    assert len(records)==1
    recovered=np.zeros_like(gray,bool)
    for y,x0,x1 in records[0]['source_runs_y_x0_x1']:recovered[y,x0:x1]=True
    assert np.array_equal(recovered,gray<254)
    assert not np.any(output==0)
    assert records[0]['original_boundary_paths_px']


@pytest.mark.parametrize('kind',['branch','cross','arrow','loop','thick_lobe','sharp_corner'])
def test_non_simple_or_variable_objects_not_accepted(kind):
    g=np.full((180,220),255,np.uint8)
    if kind=='loop':cv2.circle(g,(100,80),50,0,2)
    elif kind=='sharp_corner':cv2.polylines(g,[np.array([[30,120],[30,40],[170,40]])],False,0,2)
    else:
        cv2.line(g,(20,90),(180,90),0,2)
        if kind=='branch':cv2.line(g,(100,90),(100,45),0,2)
        if kind=='cross':cv2.line(g,(100,40),(100,140),0,2)
        if kind=='arrow':cv2.polylines(g,[np.array([[155,70],[180,90],[155,110]])],False,0,2)
        if kind=='thick_lobe':cv2.circle(g,(100,90),10,0,-1)
    output,paths,records,review=run(g)
    assert not records
    assert np.array_equal(output,np.where(g<254,0,255).astype(np.uint8))


@pytest.mark.parametrize('protection',['text','signature','line','shared'])
def test_any_protected_member_vetoes_the_whole_component(protection):
    gray=source(width=1.8);p=np.zeros_like(gray);y,x=np.argwhere(gray<254)[len(np.argwhere(gray<254))//2];p[y,x]=255
    output,paths,records,review=run(gray,protected=p)
    assert not records
    assert review['decisions'][0]['reason']=='PROTECTED_OR_SHARED_SOURCE'


def test_prior_source_claim_and_preprocess_loss_do_not_authorize_partial_replacement():
    gray=source(width=1.8);b=np.where(gray<254,0,255).astype(np.uint8)
    y,x=np.argwhere(gray<254)[0];changed=b.copy();changed[y,x]=255
    _,_,r,v=recover_observed_open_strokes(gray,b,changed)
    assert not r and v['decisions'][0]['reason']=='SOURCE_ALREADY_CLAIMED'
    _,_,r,v=recover_observed_open_strokes(gray,changed,b)
    assert not r and v['decisions'][0]['reason']=='SOURCE_NOT_IN_CURRENT_FOREGROUND'


def test_two_disconnected_strokes_are_never_joined():
    g=np.full((100,220),255,np.uint8);cv2.line(g,(15,50),(90,50),0,1);cv2.line(g,(110,50),(200,50),0,1)
    _,_,records,review=run(g)
    assert review['accepted']==2
    ranges=[(min(p[0] for p in r['points_px']),max(p[0] for p in r['points_px'])) for r in records]
    assert ranges[0][1]<100<ranges[1][0]


def test_parallel_lines_remain_separate():
    g=np.full((100,220),255,np.uint8);cv2.line(g,(15,40),(200,40),0,1);cv2.line(g,(15,55),(200,55),0,1)
    _,_,records,review=run(g)
    assert review['accepted']==2
    assert records[0]['bbox']!=records[1]['bbox']


@pytest.mark.parametrize('dpi',[0.,-1.,float('nan'),float('inf')])
def test_invalid_dpi_no_change(dpi):
    g=source();b=np.where(g<254,0,255).astype(np.uint8)
    out,_,records,review=recover_observed_open_strokes(g,b,b,dpi=dpi)
    assert out is b and not records and review['status']=='SKIPPED_INPUT_CONTRACT'


def test_clipped_component_is_not_completed():
    g=np.full((90,170),255,np.uint8);cv2.line(g,(0,40),(150,40),0,1)
    out,_,records,review=run(g)
    assert not records and review['decisions'][0]['reason']=='PAGE_EDGE_COMPONENT'


def test_tiny_marks_are_preserved():
    g=np.full((90,170),255,np.uint8);g[40,40]=0;g[50,40:42]=0
    out,_,records,_=run(g)
    assert not records and (out==0).sum()==3


def test_pen_and_source_roundtrip(tmp_path):
    _,_,records,_=run(source(width=1.8))
    r=records[0];doc=ezdxf.new('R2007');msp=doc.modelspace()
    entity,pts=add_observed_open_stroke(doc,msp,r,center_transform=lambda x,y:(x*.254,(110-y)*.254))
    assert entity.dxftype()=='LWPOLYLINE' and not entity.closed
    assert entity.dxf.lineweight==r['lineweight_hundredth_mm']
    assert all(p[2]==0 and p[3]==0 for p in entity.get_points())
    layer=doc.layers.get(BACKUP_LAYER)
    assert layer.is_off() and layer.is_frozen() and layer.is_locked()
    out=tmp_path/'saved.dxf';doc.saveas(out);loaded=ezdxf.readfile(out)
    e=next(iter(loaded.modelspace().query(f'LWPOLYLINE[layer=="{VISIBLE_LAYER}"]')))
    assert e.dxf.lineweight==entity.dxf.lineweight and not e.closed
    assert len(loaded.modelspace().query(f'LWPOLYLINE[layer=="{BACKUP_LAYER}"]'))==len(r['original_boundary_paths_px'])


@pytest.mark.parametrize('field,value',[
    ('width_space','model_mm'),('lineweight_hundredth_mm',17),('lineweight_hundredth_mm',True),
    ('creates_connection',True),('source_to_pen_error_px',1.1),('pen_to_source_error_px',float('nan')),
    ('maximum_measured_pen_edge_shift_px',1.),('dpi',0.),('width_px',float('inf')),
    ('source_pixels',0),('original_boundary_paths_px',()),('points_px',((1.,1.),(1.,1.)))])
def test_invalid_export_proof_rejected(field,value):
    _,_,records,_=run(source(width=1.8));r=copy.deepcopy(records[0]);r[field]=value
    doc=ezdxf.new()
    with pytest.raises(ValueError):add_observed_open_stroke(doc,doc.modelspace(),r,center_transform=lambda x,y:(x,y))
