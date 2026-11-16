"""Native measured polyline frame plus exact, off/frozen source boundaries."""
from __future__ import annotations
import math
import numpy as np

BACKUP_LAYER='SOURCE_FRAME_OUTLINE'
APPID='OBSERVED_FRAME_SOURCE'


def add_observed_frame(doc,layout,record,*,center_transform,layer):
    source=np.asarray(record['corners_px'],float)
    widths=np.asarray(record['side_widths_px'],float)
    if (source.shape!=(4,2) or widths.shape!=(4,) or not np.isfinite(source).all()
            or not np.isfinite(widths).all() or np.any(widths<=0)):
        raise ValueError('Frame requires four finite measured sides with positive widths')
    points=np.asarray([center_transform(*p) for p in source],float)
    vertices=[]
    for i in range(4):
        edge_px=source[(i+1)%4]-source[i]
        length_px=np.linalg.norm(edge_px)
        edge=points[(i+1)%4]-points[i]
        length=np.linalg.norm(edge)
        if min(length_px,length)<=0:
            raise ValueError('Degenerate frame side')
        normal=np.array([-edge_px[1],edge_px[0]])/length_px
        shifted=np.asarray(center_transform(*(source[i]+widths[i]*normal)))-points[i]
        width=abs(float(edge[0]*shifted[1]-edge[1]*shifted[0]))/length
        if not math.isfinite(width) or width<=0:
            raise ValueError('Invalid transformed frame width')
        vertices.append((*points[i],width,width,0.))
    pen = record.get('persistent_pen')
    pen_code = 0
    if pen is not None:
        from app.geometry.observed_label_frames import PEN_PROFILE, PEN_WIDTHS_HUNDREDTH_MM
        if (pen.get('profile') != PEN_PROFILE or pen.get('width_space') != 'paper_mm'
                or isinstance(pen.get('lineweight_hundredth_mm'), bool)
                or pen.get('lineweight_hundredth_mm') not in PEN_WIDTHS_HUNDREDTH_MM
                or not np.allclose(pen.get('measured_side_widths_px', ()), widths,
                                   atol=1e-12, rtol=0)):
            raise ValueError('Frame pen requires a matching source-verified paper-width proof')
        pen_code = int(pen['lineweight_hundredth_mm'])
        expected_px = pen_code * float(record['dpi']) / 2540.
        edge_shift = float(np.max(np.abs(widths-expected_px))/2.)
        if (not math.isclose(float(pen.get('width_px', float('nan'))),expected_px,
                             rel_tol=0.,abs_tol=1e-12)
                or not math.isclose(float(pen.get('maximum_measured_band_edge_shift_px',float('nan'))),
                                    edge_shift,rel_tol=0.,abs_tol=1e-12)
                or edge_shift>.25+1e-12
                or not all(math.isfinite(float(pen.get(k,float('nan')))) and
                           0.<=float(pen[k])<=1.+1e-9 for k in
                           ('source_to_pen_error_px','pen_to_source_error_px'))):
            raise ValueError('Frame pen proof is stale or outside the source-support bounds')
        # Group 370 remains a physical paper pen under model-space calibration.
        # Do not additionally set group 40/41/43: they are geometric band widths
        # ignored by the target LibreCAD importer and would conceal a mismatch.
        vertices = [(x,y,0.,0.,b) for x,y,_sw,_ew,b in vertices]
    if APPID not in doc.appids:
        doc.appids.add(APPID)
    tags=[(1000,'OBSERVED_CLOSED_FRAME'),(1000,','.join(map(str,record['bbox']))),
          (1071,int(record['source_pixels'])),(1000,'HISTORICAL_IDENTITY_NOT_PROVEN')]
    entity=layout.add_lwpolyline(vertices,format='xyseb',close=True,
                                dxfattribs={'layer':layer,'lineweight':pen_code})
    if pen is not None:
        tags += [(1000,'SOURCE_VERIFIED_PAPER_PEN'),(1070,pen_code),
                 (1000,'MEASURED_WIDTHS_RETAINED_IN_REPORT_NOT_EXACT_WIDTH_IDENTITY')]
    entity.set_xdata(APPID,tags)
    if BACKUP_LAYER not in doc.layers:
        doc.layers.new(BACKUP_LAYER,dxfattribs={'color':7})
    saved_layer=doc.layers.get(BACKUP_LAYER)
    saved_layer.off()
    saved_layer.freeze()
    saved_layer.lock()
    for path in record['original_boundary_paths_px']:
        saved=layout.add_lwpolyline([center_transform(x,y) for x,y in path],close=True,
                                   dxfattribs={'layer':BACKUP_LAYER,'lineweight':0})
        saved.set_xdata(APPID,[*tags,(1000,'ORIGINAL_SOURCE_BOUNDARY')])
    return entity,[tuple(p) for p in points]
