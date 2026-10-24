"""v1: geometry-only near-horizontal native rectangle crop policy.

No labels, OCR values, image identities, source coordinates or object IDs enter
the decision. Callbacks are optional metadata observers, not selection inputs.
"""
import math
VERSION='goal12-near-horizontal-rectangle-v1'
PARAMS={'maximum_horizontal_edge_degrees':5.0,'minimum_width_height_ratio':1.0,'integer_bounds':'floor/ceil','padding':0,'fallback':'original get_rotate_crop_image'}
def install(observer=None):
    import numpy as np
    import rapidocr.main as module
    original=module.get_rotate_crop_image
    def crop(image,points):
        q=np.asarray(points);reason='ORIGINAL_FALLBACK';rect=None;angles=None
        if q.shape==(4,2) and np.isfinite(q).all():
            top=q[1]-q[0];bottom=q[2]-q[3]
            angles=[abs(math.degrees(math.atan2(float(e[1]),float(e[0])))) for e in (top,bottom)]
            a=np.floor(q.min(axis=0)).astype(int);b=np.ceil(q.max(axis=0)).astype(int)
            x0,y0=map(int,a);x1,y1=map(int,b)
            if (max(angles)<=PARAMS['maximum_horizontal_edge_degrees'] and x1-x0>=y1-y0 and 0<=x0<x1<=image.shape[1] and 0<=y0<y1<=image.shape[0]):
                value=image[y0:y1,x0:x1].copy();reason='NATIVE_NEAR_HORIZONTAL_RECTANGLE';rect=[x0,y0,x1,y1]
            else:value=original(image,points)
        else:value=original(image,points)
        if observer is not None:observer({'quad':q.copy(),'image_shape':list(image.shape),'choice':reason,'rect':rect,'edge_degrees':angles,'crop_shape':list(value.shape)})
        return value
    module.get_rotate_crop_image=crop
    return original
