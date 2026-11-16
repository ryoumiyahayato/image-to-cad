"""Emit source-verified open geometry and an exact, protected boundary backup."""
from __future__ import annotations
import math
import numpy as np

APPID = 'OBSERVED_OPEN_STROKE_SOURCE'
BACKUP_LAYER = 'SOURCE_STROKE_OUTLINE'
VISIBLE_LAYER = 'NATIVE_OPEN_STROKE'


def add_observed_open_stroke(doc, layout, record, *, center_transform):
    from app.geometry.observed_label_frames import PEN_WIDTHS_HUNDREDTH_MM
    path=np.asarray(record.get('points_px',()),dtype=float)
    dpi=float(record.get('dpi',float('nan')))
    width=float(record.get('width_px',float('nan')))
    code=record.get('lineweight_hundredth_mm')
    if (path.ndim!=2 or path.shape[1]!=2 or not 2<=len(path)<=256
            or not np.isfinite(path).all() or not math.isfinite(dpi) or dpi<=0
            or not math.isfinite(width) or width<.5 or isinstance(code,bool)
            or code not in PEN_WIDTHS_HUNDREDTH_MM or record.get('width_space')!='paper_mm'
            or record.get('creates_connection') is not False
            or record.get('classification')!='OBSERVED_ISOLATED_OPEN_STROKE'):
        raise ValueError('Open stroke requires a finite source-verified path and paper pen')
    if np.any(np.linalg.norm(np.diff(path,axis=0),axis=1)<=0):
        raise ValueError('Repeated open-stroke vertex')
    shift=abs(code*dpi/2540.-width)/2.
    if (shift>.25+1e-12 or
            not math.isclose(float(record.get('maximum_measured_pen_edge_shift_px',float('nan'))),
                             shift,rel_tol=0.,abs_tol=1e-12) or
            not all(math.isfinite(float(record.get(k,float('nan')))) and
                    0<=float(record[k])<=1. for k in
                    ('source_to_pen_error_px','pen_to_source_error_px'))):
        raise ValueError('Open stroke pen proof is stale or outside the source bounds')
    boundary=record.get('original_boundary_paths_px',())
    if not boundary or int(record.get('source_pixels',0))<=0:
        raise ValueError('Open stroke requires its original source boundary')
    transformed=[center_transform(float(x),float(y)) for x,y in path]
    if not np.isfinite(np.asarray(transformed)).all():
        raise ValueError('Nonfinite transformed open stroke')
    if APPID not in doc.appids:doc.appids.add(APPID)
    if VISIBLE_LAYER not in doc.layers:doc.layers.new(VISIBLE_LAYER,dxfattribs={'color':7})
    if BACKUP_LAYER not in doc.layers:doc.layers.new(BACKUP_LAYER,dxfattribs={'color':7})
    backup=doc.layers.get(BACKUP_LAYER);backup.off();backup.freeze();backup.lock()
    tags=[(1000,'OBSERVED_ISOLATED_OPEN_STROKE'),(1000,','.join(map(str,record['bbox']))),
          (1071,int(record['source_pixels'])),(1070,int(code)),
          (1000,'HISTORICAL_IDENTITY_NOT_PROVEN'),(1000,'NO_NEW_CONNECTION')]
    attrs={'layer':VISIBLE_LAYER,'lineweight':int(code)}
    if len(transformed)==2:entity=layout.add_line(*transformed,dxfattribs=attrs)
    else:entity=layout.add_lwpolyline(transformed,close=False,dxfattribs=attrs)
    entity.set_xdata(APPID,tags)
    for source_path in boundary:
        points=np.asarray(source_path,dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all():
            raise ValueError('Invalid original open-stroke boundary')
        item=layout.add_lwpolyline([center_transform(*p) for p in points],close=True,
                                  dxfattribs={'layer':BACKUP_LAYER,'lineweight':0})
        item.set_xdata(APPID,[*tags,(1000,'ORIGINAL_SOURCE_BOUNDARY')])
    return entity,transformed
