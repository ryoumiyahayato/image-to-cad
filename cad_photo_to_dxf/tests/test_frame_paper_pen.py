"""Production pen profile, independent of target-GUI acceptance.

The legacy geometric API remains separately tested and is NOT labelled as
LibreCAD-compatible. These checks do not emulate the entire LibreCAD engine.
"""
from copy import deepcopy

from pathlib import Path
import cv2
import ezdxf
import numpy as np
import pytest

from app.geometry.observed_label_frames import (
    PEN_PROFILE, PEN_WIDTHS_HUNDREDTH_MM, recover_observed_label_frames,
    choose_verified_paper_pen, MAX_PEN_EDGE_SHIFT_PX,
)
from app.export.observed_frame_entities import add_observed_frame, BACKUP_LAYER


def source(thickness=1):
    g=np.full((110,160),255,np.uint8)
    cv2.rectangle(g,(25,25),(125,75),0,thickness)
    cv2.putText(g,'A',(65,58),cv2.FONT_HERSHEY_SIMPLEX,.7,0,1)
    _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(g<254),8)
    idx=int(labels[25,25])
    x,y,w,h,n=map(int,stats[idx])
    return g,np.where(g<254,0,255).astype(np.uint8),dict(
        frame_component_bbox=(x,y,w,h),frame_component_pixels=n,index=0),labels==idx


def recover(dpi=100.):
    g,b,p,m=source()
    return g,b,m,recover_observed_label_frames(g,b,b.copy(),(p,),dpi=dpi,stroke_profile=PEN_PROFILE)


@pytest.mark.parametrize('dpi',[72.,100.,150.,200.,300.,600.])
def test_verified_pen_retains_source_and_bounds(dpi):
    g,b,m,(out,paths,recs,review)=recover(dpi)
    assert len(recs)==1 and len(paths)==1
    assert np.all(out[m]==255) and np.array_equal(out[~m],b[~m])
    pen=recs[0]['persistent_pen']
    assert pen['lineweight_hundredth_mm'] in PEN_WIDTHS_HUNDREDTH_MM
    assert pen['maximum_measured_band_edge_shift_px']<=MAX_PEN_EDGE_SHIFT_PX+1e-12
    assert max(*pen['miter_errors_px'],*pen['round_errors_px'])<=1+1e-9
    assert np.allclose(recs[0]['side_widths_px'],pen['measured_side_widths_px'])
    assert review['stroke_profile']==PEN_PROFILE


@pytest.mark.parametrize('scale',[(.254,.254),(1.,1.),(.3,.2)])
@pytest.mark.parametrize('version',['R2007','R2010','R2013'])
def test_native_pen_serializes_without_unsupported_geometric_width(tmp_path,scale,version):
    g,b,m,(_,_,recs,_)=recover()
    doc=ezdxf.new(version)
    doc.layers.new('ENGINEERING_SYMBOL')
    e,_=add_observed_frame(doc,doc.modelspace(),recs[0],
        center_transform=lambda x,y:((x+.5)*scale[0],(g.shape[0]-y-.5)*scale[1]),
        layer='ENGINEERING_SYMBOL')
    assert e.closed and len(e)==4 and e.dxf.lineweight>0
    assert not e.has_width
    assert all(p[2]==p[3]==0 for p in e)
    assert e.dxf.get('const_width',0)==0
    # Pen is physical paper width, not a quantity multiplied by model scale.
    assert e.dxf.lineweight==recs[0]['persistent_pen']['lineweight_hundredth_mm']
    backups=list(doc.modelspace().query(f'LWPOLYLINE[layer=="{BACKUP_LAYER}"]'))
    assert len(backups)==2 and doc.layers.get(BACKUP_LAYER).is_frozen()
    f=tmp_path/'pen.dxf'
    doc.saveas(f)
    fresh=ezdxf.readfile(f)
    e2=list(fresh.modelspace().query('LWPOLYLINE[layer=="ENGINEERING_SYMBOL"]'))[0]
    assert np.array_equal(np.asarray(list(e2)),np.asarray(list(e))) and e2.dxf.lineweight==e.dxf.lineweight
    assert not fresh.audit().errors


@pytest.mark.parametrize('bad',[0,-1,24,999,True,float('nan')])
def test_invalid_pen_code_is_not_written(bad):
    _,_,_,(_,_,recs,_)=recover()
    r=deepcopy(recs[0])
    r['persistent_pen']['lineweight_hundredth_mm']=bad
    doc=ezdxf.new()
    doc.layers.new('ENGINEERING_SYMBOL')
    with pytest.raises((ValueError,TypeError)):
        add_observed_frame(doc,doc.modelspace(),r,center_transform=lambda x,y:(x,y),layer='ENGINEERING_SYMBOL')
    assert len(doc.modelspace())==0


@pytest.mark.parametrize('key,value',[
    ('profile','unverified'),('width_space','model_mm'),('width_px',8.),
    ('measured_side_widths_px',(1,1,1,2)),('maximum_measured_band_edge_shift_px',float('nan')),
    ('source_to_pen_error_px',2.),('pen_to_source_error_px',float('inf')),
    ('lineweight_hundredth_mm',211),
])
def test_changed_pen_proof_is_rejected(key,value):
    _,_,_,(_,_,recs,_)=recover()
    r=deepcopy(recs[0])
    r['persistent_pen'][key]=value
    doc=ezdxf.new()
    doc.layers.new('ENGINEERING_SYMBOL')
    with pytest.raises(ValueError):
        add_observed_frame(doc,doc.modelspace(),r,center_transform=lambda x,y:(x,y),layer='ENGINEERING_SYMBOL')
    assert len(doc.modelspace())==0


@pytest.mark.parametrize('widths',[(1.,1.,3.,1.),(.1,4.,.1,4.),(.01,.01,.01,.01)])
def test_no_uniform_pen_does_not_authorize_approximation(widths):
    g,b,p,m=source()
    yy,xx=np.nonzero(m)
    local=m[25:76,25:126]
    assert choose_verified_paper_pen(local,np.array([[0.,0.],[100.,0.],[100.,50.],[0.,50.]]),
        widths,np.zeros((0,2)),100.) is None


@pytest.mark.parametrize('foreign',[[(50.,.1)],[(50.,.9)],[(0.,0.)]])
def test_pen_never_covers_foreign_content(foreign):
    g,b,p,m=source()
    mask=m[25:76,25:126]
    assert choose_verified_paper_pen(mask,np.array([[0.,0.],[100.,0.],[100.,50.],[0.,50.]]),
        (1,1,1,1),np.asarray(foreign),100.) is None


@pytest.mark.parametrize('kind',['gap','branch','claimed','protected'])
def test_source_rejection_also_applies_to_pen_profile(kind):
    g,b,p,m=source()
    visible=b.copy()
    protect=np.zeros_like(g)
    if kind=='gap':
        g[25,50:53]=255
        b=np.where(g<254,0,255).astype('uint8')
        visible=b.copy()
    if kind=='branch':
        cv2.line(g,(125,40),(140,40),0,1)
        b=np.where(g<254,0,255).astype('uint8')
        visible=b.copy()
    if kind=='claimed':
        visible[25,60]=255
    if kind=='protected':
        protect[25,60]=255
    old=visible.copy()
    out,paths,records,_=recover_observed_label_frames(g,b,visible,(p,),
        protected_masks=(protect,),stroke_profile=PEN_PROFILE)
    assert not records and not paths and np.array_equal(old,out)


def test_production_recovery_explicitly_uses_persistent_pen():
    sourcefile=Path(__file__).parents[1]/'app/geometry/optimized_trace.py'
    assert 'stroke_profile="librecad_paper_pen"' in sourcefile.read_text(encoding="utf-8")


def test_unsupported_profile_rejects_before_mutation():
    g,b,p,m=source()
    with pytest.raises(ValueError):
        recover_observed_label_frames(g,b,b,(p,),stroke_profile='guess')
