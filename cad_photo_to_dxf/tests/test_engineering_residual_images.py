from dataclasses import replace


import ezdxf
import numpy as np
from PIL import Image
import pytest

from app.core.structure_build import build_final_structure
from app.export.engineering_residual_images import has_native_recovery, residual_image_tiles
from app.export.trace_single_export import export_final_structure_dxf
from app.export.trace_document_export import export_trace_document_streaming
from app.export.document_export import DocumentPage
from app.ocr.logo_detection import LogoRegion


def source_region():
    alpha = np.zeros((21, 23), np.uint8)
    alpha[9, 1] = 255
    alpha[10, 1] = 191
    alpha[18, 5] = 255
    alpha[20, 12:15] = (191, 255, 255)
    return LogoRegion((8, 7, 23, 21), alpha, .99, 0, 3, visual_kind='engineering_graphic')


def record(region):
    return dict(engineering_graphic_replacements=[dict(
        source_bbox=region.bbox, authority='ACCEPTED_NATIVE_MEMBER_SOURCE_ONLY',
        retired_source_pixels=135, remaining_source_pixels=6)])


def reconstruct(original, parts):
    out = np.zeros_like(original.mask)
    count = np.zeros_like(original.mask)
    ox,oy,_,_=original.bbox
    for p in parts:
        x,y,w,h=p.bbox
        assert np.all(p.mask > 0)
        count[y-oy:y-oy+h,x-ox:x-ox+w] += 1
        out[y-oy:y-oy+h,x-ox:x-ox+w] = p.mask
    assert count.max() == 1
    return out


def test_exact_alpha_and_no_transparent_pick_area():
    r=source_region()
    parts=residual_image_tiles(r,eligible=True)
    assert len(parts)==3
    assert np.array_equal(reconstruct(r,parts),r.mask)
    assert sum(p.bbox[2]*p.bbox[3] for p in parts)==6
    assert not any(x <= 20 <= x+w and y <= 17 <= y+h for x,y,w,h in (p.bbox for p in parts))


@pytest.mark.parametrize('eligible,kind', [(False,'engineering_graphic'),(True,'graphic_mark'),(True,'wordmark')])
def test_no_unproved_split_or_logo_change(eligible,kind):
    r=replace(source_region(),visual_kind=kind)
    assert residual_image_tiles(r,eligible=eligible)==(r,)


def test_requires_replacement_authority_not_only_overlap():
    r=source_region()
    rec=record(r)
    assert has_native_recovery(r.bbox,[rec])
    assert not has_native_recovery((9,7,23,21),[rec])
    rec['engineering_graphic_replacements'][0]['authority']='UNKNOWN'
    assert not has_native_recovery(r.bbox,[rec])


def test_representation_budget_preserves_everything():
    r=source_region()
    assert residual_image_tiles(r,eligible=True,max_tiles=2)==(r,)


@pytest.mark.parametrize('seed',range(12))
def test_random_alpha_runs_are_lossless(seed):
    rng=np.random.default_rng(seed)
    a=rng.choice(np.array([0,0,0,1,64,191,255],np.uint8),size=(14,19))
    r=replace(source_region(),bbox=(5,9,19,14),mask=a)
    assert np.array_equal(reconstruct(r,residual_image_tiles(r,eligible=True,max_tiles=300)),a)


@pytest.mark.parametrize('multipage',[False,True])
def test_real_export_readback_retains_alpha_placement_and_metadata(tmp_path,multipage):
    r=source_region()
    shape=(44,52)
    source=np.full(shape,255,np.uint8)
    x,y,w,h=r.bbox
    source[y:y+h,x:x+w]=255-r.mask
    structure=build_final_structure(source_size_px=shape[::-1],
        contour_binary=np.full(shape,255,np.uint8),contours=(),logos=(r,),preview_binary=source,
        provenance={'engineering_enclosures':(record(r),)})
    out=tmp_path/'tiled.dxf'
    if multipage:
        export_trace_document_streaming((DocumentPage(1,None,shape[::-1],final_structure=structure),),out,total_pages=1)
    else:
        export_final_structure_dxf(structure,out)
    d=ezdxf.readfile(out)
    images=list(d.modelspace().query('IMAGE'))
    assert len(images)==3
    actual=np.zeros_like(r.mask)
    for e in images:
        tags=[tag.value for tag in e.get_xdata('ENGINEERING_GRAPHIC_SOURCE')]
        assert tags[2]==','.join(map(str,r.bbox))
        assert tags[-2]=='RESIDUAL_ALPHA_TILE_V1'
        px,py,pw,ph=map(int,tags[-1].split(','))
        rgba=np.asarray(Image.open(out.parent/e.image_def.dxf.filename).convert('RGBA'))
        assert rgba.shape==(ph,pw,4)
        assert np.all(rgba[:,:,3]>0)
        assert e.dxf.insert.x == pytest.approx(px)
        assert e.dxf.insert.y == pytest.approx(shape[0]-py-ph)
        assert e.dxf.u_pixel.x == pytest.approx(1)
        assert e.dxf.v_pixel.y == pytest.approx(1)
        actual[py-y:py-y+ph,px-x:px-x+pw]=rgba[:,:,3]
    assert np.array_equal(actual,r.mask)
    d.saveas(tmp_path/'resaved.dxf')
    reopened=ezdxf.readfile(tmp_path/'resaved.dxf')
    assert len(reopened.modelspace().query('IMAGE'))==3
    assert not reopened.audit().has_errors
