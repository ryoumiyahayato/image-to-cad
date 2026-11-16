"""Measured, independent label frames, never inferred closure or topology.

An upstream boxed-label observation locates a candidate only. This module
rechecks the complete source component and its still-visible ownership, fits
all four sides, and preserves the original boundary in the returned record.
"""
from __future__ import annotations
import math
import cv2
import numpy as np
from app.core.trace_types import TracePath
from app.geometry.raster_trace import trace_binary

VERSION = 'observed-label-frame-geometry-v2-pen-persistence'
MAX_CHECKS = 128
MAX_LOCAL_PIXELS = 65536
MAX_TOTAL_PIXELS = 1048576
MAX_CENTER_ERROR = .75
MAX_BOUNDARY_ERROR = 1.0


def _runs(mask):
    result = []
    for y, row in enumerate(mask):
        d = np.diff(np.r_[False, row, False].astype(np.int8))
        result.extend((int(y), int(a), int(b)) for a,b in zip(
            np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
    return result


def _fit_side(mask, gray, axis, far, trim):
    normal_size, length = mask.shape[axis], mask.shape[1-axis]
    positions = np.arange(trim, length-trim, dtype=float)
    if len(positions) < 5:
        return None
    centers, widths = [], []
    side = (np.arange(normal_size) > normal_size*2/3 if far
            else np.arange(normal_size) < normal_size/3)
    for k in positions.astype(int):
        row = mask[:,k] if axis == 0 else mask[k,:]
        tones = gray[:,k] if axis == 0 else gray[k,:]
        hits = np.flatnonzero(row & side)
        if (not len(hits) or hits[-1]-hits[0]+1 != len(hits)
                or len(hits) > max(4, normal_size*.16)):
            return None
        mass = (255.-tones[hits])/255.
        if mass.sum() <= 0:
            return None
        # A grey antialias pixel is not a missing station. Topology is checked
        # on the original observed component; tones locate its ink centroid.
        centers.append(float(np.dot(hits,mass)/mass.sum()))
        widths.append(float(mass.sum()))
    slope, intercept = np.polyfit(positions,centers,1)
    residual = np.asarray(centers) - (slope*positions+intercept)
    intercept += (residual.max()+residual.min())/2
    error = float(np.abs(np.asarray(centers)-(slope*positions+intercept)).max())
    if (abs(slope) > math.tan(math.radians(4)) or error > MAX_CENTER_ERROR
            or np.ptp(widths) > 1.5 or np.median(widths) < .5):
        return None
    return dict(slope=float(slope), intercept=float(intercept),
                width_px=float(np.median(widths)), max_center_error_px=error,
                stations=len(positions), minimum_source_ink_mass=float(min(widths)))


def _corner(horizontal, vertical):
    a,b = horizontal['slope'],horizontal['intercept']
    c,d = vertical['slope'],vertical['intercept']
    x = (c*b+d)/(1-a*c)
    return np.array((x,a*x+b),dtype=float)


def stroke_rings(corners, widths):
    """Exact mitered polygon of the four constant-width polyline segments."""
    edges = np.roll(corners,-1,axis=0)-corners
    lens = np.linalg.norm(edges,axis=1)
    normals = np.column_stack((-edges[:,1],edges[:,0]))/lens[:,None]
    values = np.sum(normals*corners,axis=1)
    result = []
    for sign in (-1,1):
        offsets = values + sign*np.asarray(widths)/2
        result.append(np.array([np.linalg.solve(
            np.array([normals[(i-1)%4],normals[i]]),
            [offsets[(i-1)%4],offsets[i]]) for i in range(4)]))
    return tuple(result)


def _support_errors(mask, corners, widths):
    outer, inner = stroke_rings(corners,widths)
    yy,xx = np.nonzero(mask)
    source = np.column_stack((xx,yy)).astype(float)
    oc,ic = outer.astype(np.float32),inner.astype(np.float32)
    forward = 0.
    for p in source:
        od = cv2.pointPolygonTest(oc,tuple(p),True)
        ind = cv2.pointPolygonTest(ic,tuple(p),True)
        forward = max(forward, -od if od < 0 else (ind if ind > 0 else 0.))
    reverse = 0.
    for ring in (outer,inner,corners):
        for p,q in zip(ring,np.roll(ring,-1,axis=0)):
            samples = np.linspace(p,q,max(3,int(math.ceil(np.linalg.norm(q-p)*4))+1))
            # Distance to an observed raster CELL, not to a clipped image index.
            delta = np.maximum(np.abs(samples[:,None,:]-source[None,:,:])-.5,0)
            reverse = max(reverse,float(np.sqrt(np.square(delta).sum(axis=2).min(axis=1)).max()))
    return forward, reverse


# DXF group 370 is a paper-space pen width in hundredths of a millimetre.
# It is not the geometric per-vertex width (40/41) that LibreCAD 2.2.1.5 drops.
# This mode may approximate small scan-induced width differences only after
# rechecking the unchanged source-support and foreign-owner contracts.
PEN_WIDTHS_HUNDREDTH_MM = (5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53,
                          60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
MAX_PEN_EDGE_SHIFT_PX = .25
PEN_PROFILE = 'librecad_paper_pen'


def _segment_distances(points, corners):
    points = np.asarray(points, float)
    a = np.asarray(corners, float)
    edges = np.roll(a, -1, axis=0) - a
    denom = np.einsum('ij,ij->i', edges, edges)
    if np.any(denom <= 0):
        raise ValueError('Degenerate source frame')
    delta = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum('nki,ki->nk', delta, edges) / denom, 0., 1.)
    nearest = a[None, :, :] + t[:, :, None] * edges[None, :, :]
    return np.linalg.norm(points[:, None, :] - nearest, axis=2).min(axis=1)


def _round_pen_errors(mask, corners, width):
    # Conservative companion check for pen renderers using round line caps
    # and joins. Both miter and round support must pass; neither is inferred.
    yy, xx = np.nonzero(mask)
    source = np.column_stack((xx, yy)).astype(float)
    radius = float(width) / 2.
    forward = float(np.maximum(_segment_distances(source, corners)-radius, 0.).max())
    probes = []
    for a,b in zip(corners, np.roll(corners,-1,axis=0)):
        edge = b-a
        length = np.linalg.norm(edge)
        normal = np.array([-edge[1], edge[0]])/length
        samples = np.linspace(a,b,max(3,int(np.ceil(length*4))+1))
        probes.extend((samples+normal*radius, samples-normal*radius, samples))
    angles = np.linspace(0., 2.*np.pi, 65)
    disk = radius * np.column_stack((np.cos(angles), np.sin(angles)))
    probes.extend(c+disk for c in corners)
    points = np.concatenate(probes)
    reverse = 0.
    for offset in range(0,len(points),512):
        delta = np.maximum(np.abs(points[offset:offset+512,None,:]-source[None,:,:])-.5,0.)
        reverse = max(reverse, float(np.sqrt(np.square(delta).sum(axis=2).min(axis=1)).max()))
    return forward, reverse


def choose_verified_paper_pen(component, corners, measured_widths, foreign_points, dpi):
    """Return a verified common pen or None; never changes source pixels.

    One common paper pen is acceptable only if every edge moves <= .25 source
    pixels from its measured band AND the original <=1px bidirectional source
    bounds still pass for miter AND round joins. Foreign-owner clearance is
    checked on both stroke models. Incompatible objects retain source contours.
    """
    measured = np.asarray(measured_widths,float)
    if (not np.isfinite(dpi) or dpi<=0 or measured.shape!=(4,)
            or not np.isfinite(measured).all() or np.any(measured<.5)):
        return None
    candidates = sorted(PEN_WIDTHS_HUNDREDTH_MM, key=lambda code: (
        float(np.abs(measured-code*dpi/2540.).max()),
        float(np.square(measured-code*dpi/2540.).sum()), code))
    for code in candidates:
        width = code*dpi/2540.
        shift = float(np.abs(measured-width).max()/2.)
        if shift > MAX_PEN_EDGE_SHIFT_PX+1e-12:
            continue
        widths = np.full(4,width)
        fm, rm = _support_errors(component,corners,widths)
        fr, rr = _round_pen_errors(component,corners,width)
        if max(fm,rm,fr,rr)>MAX_BOUNDARY_ERROR+1e-9:
            continue
        clearance = float('inf')
        if len(foreign_points):
            outer,inner = stroke_rings(corners,widths)
            oc,ic = outer.astype(np.float32),inner.astype(np.float32)
            for p in np.asarray(foreign_points,float):
                point = tuple(map(float,p))
                od=cv2.pointPolygonTest(oc,point,True)
                ind=cv2.pointPolygonTest(ic,point,True)
                clearance=min(clearance, -od if od<0 else (ind if ind>0 else 0.))
            clearance=min(clearance,float((_segment_distances(foreign_points,corners)-width/2.).min()))
        if clearance <= math.sqrt(.5):
            continue
        return dict(profile=PEN_PROFILE, lineweight_hundredth_mm=code,
                    width_space='paper_mm', width_px=float(width),
                    measured_side_widths_px=tuple(map(float,measured)),
                    maximum_measured_band_edge_shift_px=shift,
                    source_to_pen_error_px=max(fm,fr),pen_to_source_error_px=max(rm,rr),
                    miter_errors_px=(fm,rm),round_errors_px=(fr,rr),
                    minimum_foreign_pixel_clearance_px=clearance if math.isfinite(clearance) else None)
    return None


def recover_observed_label_frames(gray, binary, visible_binary, proofs, *, protected_masks=(), dpi=100., stroke_profile="geometric"):
    if stroke_profile not in ('geometric', PEN_PROFILE):
        raise ValueError('Unsupported observed-frame stroke profile')
    review = dict(version=VERSION, stroke_profile=stroke_profile, accepted=0, source_pixels=0, decisions=[])
    if (gray.ndim != 2 or gray.dtype != np.uint8 or binary.shape != gray.shape
            or visible_binary.shape != gray.shape or not math.isfinite(dpi) or dpi <= 0):
        review['status']='SKIPPED_INPUT_CONTRACT'
        return visible_binary,(),(),review
    output=visible_binary
    paths=[]
    records=[]
    seen=set()
    budget=MAX_TOTAL_PIXELS
    for proof in tuple(proofs)[:MAX_CHECKS]:
        box=tuple(map(int,proof.get('frame_component_bbox',())))
        if len(box)!=4 or box in seen:
            continue
        seen.add(box)
        x,y,w,h=box
        item=dict(bbox=box,decision='REJECTED')
        review['decisions'].append(item)
        def reject(reason): item['reason']=reason
        size=(w+4)*(h+4)
        if (min(w,h)<10 or size>MAX_LOCAL_PIXELS or budget<size
                or x<2 or y<2 or x+w+2>gray.shape[1] or y+h+2>gray.shape[0]):
            reject('BUDGET_OR_PAGE_EDGE')
            continue
        budget-=size
        crop=gray[y-2:y+h+2,x-2:x+w+2]
        _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(crop<254),connectivity=8)
        ids=[i for i in range(1,len(stats)) if tuple(map(int,stats[i,:4]))==(2,2,w,h)]
        if len(ids)!=1:
            reject('INCOMPLETE_OR_ATTACHED_COMPONENT')
            continue
        component=labels[2:-2,2:-2]==ids[0]
        if int(component.sum())!=int(proof.get('frame_component_pixels',-1)):
            reject('SOURCE_OBSERVATION_MISMATCH')
            continue
        contours,hierarchy=cv2.findContours(np.uint8(component),cv2.RETR_TREE,cv2.CHAIN_APPROX_NONE)
        if hierarchy is None or len(contours)!=2 or sorted(map(int,hierarchy[0,:,3]))!=[-1,0]:
            reject('NOT_A_COMPLETE_SINGLE_HOLE_RING')
            continue
        if np.any(component & (binary[y:y+h,x:x+w]>=128)):
            reject('SOURCE_NOT_IN_CURRENT_FOREGROUND')
            continue
        if np.any(component & (visible_binary[y:y+h,x:x+w]>=128)):
            reject('SOURCE_ALREADY_CLAIMED')
            continue
        if any(m is not None and np.any(component & (m[y:y+h,x:x+w]>0)) for m in protected_masks):
            reject('PROTECTED_OR_SHARED_SOURCE')
            continue
        trim=max(3,int(math.ceil(min(w,h)*.12)))
        sides=[_fit_side(component,gray[y:y+h,x:x+w],a,f,trim)
               for a,f in ((0,False),(1,True),(0,True),(1,False))]
        if any(s is None for s in sides):
            reject('INCOMPLETE_VARIABLE_OR_NONLINEAR_SIDE')
            continue
        top,right,bottom,left=sides
        corners=np.array([_corner(top,left),_corner(top,right),_corner(bottom,right),_corner(bottom,left)])
        widths=[s['width_px'] for s in sides]
        if (not np.isfinite(corners).all() or np.any(corners<-.5)
                or np.any(corners>np.array((w-.5,h-.5)))):
            reject('CORNER_OUTSIDE_SOURCE')
            continue
        forward,reverse=_support_errors(component,corners,widths)
        if max(forward,reverse)>MAX_BOUNDARY_ERROR+1e-9:
            reject('BIDIRECTIONAL_SUPPORT_FAILED')
            continue
        # A good fit to the frame alone is insufficient: the new filled band
        # must not touch an unrelated source pixel or another owner's claim.
        # Check the complete surrounding crop, not just the frame bbox.
        outer,inner=stroke_rings(corners+2,widths)
        oc,ic=outer.astype(np.float32),inner.astype(np.float32)
        full_component=labels==ids[0]
        foreign=(crop<254)&~full_component
        for owner in protected_masks:
            if owner is not None:
                foreign |= (owner[y-2:y+h+2,x-2:x+w+2]>0)&~full_component
        clearance=float('inf')
        for fy,fx in zip(*np.nonzero(foreign)):
            point=(float(fx),float(fy))
            od=cv2.pointPolygonTest(oc,point,True)
            ind=cv2.pointPolygonTest(ic,point,True)
            distance=(-od if od<0 else (ind if ind>0 else 0.))
            clearance=min(clearance,distance)
        if clearance <= math.sqrt(.5):
            reject('FITTED_STROKE_ENTERS_OTHER_SOURCE_OR_OWNER')
            continue
        pen = None
        if stroke_profile == PEN_PROFILE:
            fy,fx = np.nonzero(foreign)
            foreign_points = np.column_stack((fx-2,fy-2)).astype(float)
            pen = choose_verified_paper_pen(component,corners,widths,foreign_points,dpi)
            if pen is None:
                reject('NO_SOURCE_FAITHFUL_PERSISTENT_PEN')
                continue
        absolute=corners+(x,y)
        oldpaths=trace_binary(np.where(component,0,255).astype(np.uint8))
        backup=tuple(tuple((px+x,py+y) for px,py in p.points) for p in oldpaths)
        record=dict(kind='source_frame',bbox=box,ring_replaced=True,native_scan=False,
                    native_source_frame=True,dpi=float(dpi),side_widths_px=tuple(widths),
                    corners_px=tuple(map(tuple,absolute)),original_boundary_paths_px=backup,
                    source_runs_y_x0_x1=tuple((ry+y,a+x,b+x) for ry,a,b in _runs(component)),
                    source_pixels=int(component.sum()),side_checks=tuple(sides),
                    source_to_geometry_error_px=forward,geometry_to_source_error_px=reverse,
                    upstream_text_index=int(proof.get('index',-1)),
                    classification='OBSERVED_RECTILINEAR_FRAME',creates_connection=False,
                    historical_identity='NOT_PROVEN',
                    minimum_foreign_pixel_clearance_px=(clearance if math.isfinite(clearance) else None))
        if pen is not None:
            record['persistent_pen'] = pen
            item['persistent_pen'] = pen
        paths.append(TracePath(tuple(map(tuple,absolute)),None,0,len(paths)))
        records.append(record)
        if output is visible_binary:
            output=visible_binary.copy()
        output[y:y+h,x:x+w][component]=255
        item.update(decision='ACCEPTED',reason='COMPLETE_UNCONTESTED_SOURCE_RING',
                    source_pixels=record['source_pixels'],source_to_geometry_error_px=forward,
                    geometry_to_source_error_px=reverse)
        review['accepted']+=1
        review['source_pixels']+=record['source_pixels']
    return output,tuple(paths),tuple(records),review
