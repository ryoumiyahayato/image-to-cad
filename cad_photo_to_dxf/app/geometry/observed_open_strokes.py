"""Source-supported isolated open strokes; no joining, gap filling, or net inference.

The complete original gray component must still be present and unowned. Thinning
only proposes an ordered path; source/pen and foreign-owner checks authorize it.
Uncertain, branched, looped, variable-width, clipped, or already-owned components
retain their existing representation. Input arrays are never mutated.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np

from app.core.trace_types import TracePath
from app.geometry.raster_trace import trace_binary
from app.geometry.observed_label_frames import PEN_WIDTHS_HUNDREDTH_MM

VERSION = "observed-isolated-open-strokes-v1"
MIN_LENGTH_MM = 10.0
MAX_COMPONENT_PIXELS = 8192
MAX_LOCAL_PIXELS = 100000
MAX_CHECKS = 512
MAX_TOTAL_LOCAL_PIXELS = 4000000
MAX_BOUNDARY_ERROR_PX = 1.0
MAX_PEN_EDGE_SHIFT_PX = .25


def _thin(mask: np.ndarray) -> np.ndarray:
    """Two-subiteration topology-preserving thinning, without branch pruning."""
    a = np.pad(mask.astype(np.uint8), 1)
    for _ in range(max(a.shape)):
        changed = False
        for step in (0, 1):
            c = a[1:-1, 1:-1]
            n = [a[:-2,1:-1], a[:-2,2:], a[1:-1,2:], a[2:,2:],
                 a[2:,1:-1], a[2:,:-2], a[1:-1,:-2], a[:-2,:-2]]
            degree = sum(n)
            transitions = sum((n[i] == 0) & (n[(i+1) % 8] > 0) for i in range(8))
            guard = ((n[0]*n[2]*n[4] == 0) & (n[2]*n[4]*n[6] == 0)
                     if step == 0 else
                     (n[0]*n[2]*n[6] == 0) & (n[0]*n[4]*n[6] == 0))
            delete = (c > 0) & (degree >= 2) & (degree <= 6) & (transitions == 1) & guard
            if delete.any():
                c[delete] = 0
                changed = True
        if not changed:
            return a[1:-1,1:-1].astype(bool)
    raise ValueError("Thinning did not converge within the bounded local component")


def _ordered_path(mask: np.ndarray) -> np.ndarray | None:
    nodes = set(zip(*np.nonzero(_thin(mask))))
    adjacency: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y, x in nodes:
        peers = []
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            p = (y+dy, x+dx)
            if p not in nodes:
                continue
            # Do not turn the corner of a 4-connected stair into a graph cycle.
            if dx and dy and ((y,x+dx) in nodes or (y+dy,x) in nodes):
                continue
            peers.append(p)
        adjacency[y,x] = peers
    ends = sorted(p for p, peers in adjacency.items() if len(peers) == 1)
    if len(ends) != 2 or any(len(p) not in (1,2) for p in adjacency.values()):
        return None
    order, seen = [ends[0]], {ends[0]}
    while order[-1] != ends[1]:
        peers = [p for p in adjacency[order[-1]] if p not in seen]
        if len(peers) != 1:
            return None
        order.append(peers[0]); seen.add(peers[0])
    if len(seen) != len(nodes):
        return None
    return np.array([(x,y) for y,x in order], dtype=float)


def _distances(points: np.ndarray, path: np.ndarray) -> np.ndarray:
    edges = np.diff(path, axis=0)
    denominators = np.einsum("ij,ij->i", edges, edges)
    if np.any(denominators <= 0):
        raise ValueError("Degenerate open path")
    values = []
    for start in range(0, len(points), 512):
        delta = points[start:start+512,None,:] - path[None,:-1,:]
        t = np.clip(np.einsum("nki,ki->nk", delta, edges) / denominators, 0., 1.)
        nearest = path[None,:-1,:] + t[:,:,None] * edges[None,:,:]
        values.append(np.linalg.norm(points[start:start+512,None,:]-nearest, axis=2).min(axis=1))
    return np.concatenate(values) if values else np.empty(0, dtype=float)


def _simplify(raw: np.ndarray) -> np.ndarray:
    smoothed = raw.copy()
    for i in range(1, len(raw)-1):
        k = min(3, i, len(raw)-1-i)
        smoothed[i] = raw[i-k:i+k+1].mean(axis=0)
    return cv2.approxPolyDP(smoothed.astype(np.float32), .3, False).reshape(-1,2).astype(float)


def _gray_center_and_terminals(mask: np.ndarray, gray: np.ndarray, path: np.ndarray) -> np.ndarray:
    """Locate ink centers/end caps in the original gray component.

    Thinning erodes the ends of thick/antialiased strokes. It supplies order,
    not final coordinates. Every proposed subpixel position is subsequently
    subject to the same bidirectional support and no-foreign-contact tests.
    """
    length=float(np.linalg.norm(np.diff(path,axis=0),axis=1).sum())
    mass=float(np.sum((255.-gray[mask])/255.))
    width=max(.5,mass/max(length,1.))
    result=path.copy()
    ink=((255.-gray)/255.*mask).astype(np.float32)
    for i,p in enumerate(path):
        a=path[max(0,i-1)];b=path[min(len(path)-1,i+1)]
        tangent=b-a;norm=float(np.linalg.norm(tangent))
        if norm<=0:continue
        tangent/=norm;normal=np.array((-tangent[1],tangent[0]))
        offsets=np.arange(-max(4.,2.*width+1.),max(4.,2.*width+1.)+.125,.25)
        points=p+offsets[:,None]*normal
        values=cv2.remap(ink,points[:,0].astype(np.float32).reshape(1,-1),
                       points[:,1].astype(np.float32).reshape(1,-1),cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT,borderValue=0).ravel()
        if values.sum()>0:
            shift=float(np.dot(offsets,values)/values.sum())
            if abs(shift)<=1.:result[i]=p+normal*shift
    yy,xx=np.nonzero(mask);source=np.column_stack((xx,yy)).astype(float)
    for i,j in ((0,1),(-1,-2)):
        point=result[i];outward=point-result[j];outward/=np.linalg.norm(outward)
        delta=source-point
        local=np.linalg.norm(delta,axis=1)<=max(4.,3.*width)
        projections=delta[local]@outward
        if len(projections):
            extension=float(projections.max()+.5-width/2.)
            if 0.<extension<=max(3.,2.*width):result[i]=point+outward*extension
    return result


def _fit(mask: np.ndarray, gray: np.ndarray, foreign: np.ndarray, dpi: float
         ) -> tuple[dict[str, Any] | None, str]:
    contours, _ = cv2.findContours(np.uint8(mask), cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if len(contours) != 1:
        return None, "HOLE_OR_DISCONNECTED"
    raw = _ordered_path(mask)
    if raw is None:
        return None, "NOT_SIMPLE_TWO_ENDPOINT_PATH"
    path = _gray_center_and_terminals(mask, gray, _simplify(raw))
    if len(path) < 2 or len(path) > 256:
        return None, "INVALID_PATH_COMPLEXITY"
    length = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
    if length < MIN_LENGTH_MM * dpi / 25.4:
        return None, "SHORT"
    width = float(np.sum((255. - gray[mask]) / 255.) / length)
    if width < .5 or width > 4*dpi/100 or length/width < 20:
        return None, "VARIABLE_OR_THICK"
    source_points = np.column_stack(np.nonzero(mask)[::-1]).astype(float)
    source_distances = _distances(source_points, path)
    if max(0., float(source_distances.max()) - width/2.) > .8:
        return None, "SOURCE_TO_PATH"

    stations, tangents = [], []
    for a, b in zip(path, path[1:]):
        edge = b-a; edge_length = float(np.linalg.norm(edge))
        for t in np.linspace(0., 1., max(2, int(math.ceil(edge_length))+1)):
            point = a + t*edge
            if min(np.linalg.norm(point-path[0]), np.linalg.norm(point-path[-1])) > max(2.,width*2.):
                stations.append(point); tangents.append(edge/edge_length)
    if len(stations) < 12:
        return None, "SHORT_MEASUREMENT_RUN"
    stations = np.asarray(stations); tangents = np.asarray(tangents)
    normals = np.column_stack((-tangents[:,1], tangents[:,0]))
    radius = max(4., width*2.+1.)
    offsets = np.arange(-radius, radius+.125, .25)
    coords = stations[:,None,:] + normals[:,None,:]*offsets[None,:,None]
    ink = ((255.-gray)/255.*mask).astype(np.float32)
    profiles = cv2.remap(ink, coords[:,:,0].astype(np.float32), coords[:,:,1].astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    widths = profiles.sum(axis=1)*.25
    if float(widths.min()) < .5 or float(np.ptp(widths)) > 1.5:
        return None, "WIDTH_VARIATION"
    width = float(np.median(widths))
    if float(np.linalg.norm(path[0]-path[-1])) < max(4.,3.*width):
        return None, "ENDPOINTS_TOO_CLOSE"
    code = min(PEN_WIDTHS_HUNDREDTH_MM, key=lambda c: (abs(c*dpi/2540.-width), c))
    pen_width = code*dpi/2540.
    edge_shift = abs(pen_width-width)/2.
    if edge_shift > MAX_PEN_EDGE_SHIFT_PX:
        return None, "PEN_WIDTH_SHIFT"
    source_error = max(0.,float(source_distances.max())-pen_width/2.)
    if source_error > MAX_BOUNDARY_ERROR_PX:
        return None, "SOURCE_TO_PEN"
    samples = []
    for a,b in zip(path,path[1:]):
        edge = b-a; distance = float(np.linalg.norm(edge))
        normal = np.array((-edge[1],edge[0]))/distance
        points = np.linspace(a,b,max(3,int(math.ceil(distance*4))+1))
        samples.extend((points,points+normal*pen_width/2.,points-normal*pen_width/2.))
    angles = np.linspace(0.,2.*np.pi,33)
    cap = np.column_stack((np.cos(angles),np.sin(angles)))*pen_width/2.
    samples.extend(p+cap for p in path)
    samples = np.concatenate(samples)
    reverse = 0.
    for start in range(0,len(samples),128):
        delta = np.maximum(np.abs(samples[start:start+128,None,:]-source_points[None,:,:])-.5,0.)
        reverse = max(reverse,float(np.sqrt(np.square(delta).sum(axis=2).min(axis=1)).max()))
    if reverse > MAX_BOUNDARY_ERROR_PX:
        return None, "PEN_TO_SOURCE"
    other = np.column_stack(np.nonzero(foreign)[::-1]).astype(float)
    clearance = float("inf") if not len(other) else float(_distances(other,path).min()-pen_width/2.)
    if clearance <= math.sqrt(.5):
        return None, "FOREIGN_CONTACT"
    # A centerline must not cross itself or close a formerly open near-loop.
    from shapely.geometry import LineString
    line = LineString(path)
    if not line.is_simple or len(line.buffer(pen_width/2.,join_style="round").interiors):
        return None, "SELF_INTERSECTION_OR_CLOSED_GAP"
    vectors=np.diff(path,axis=0)
    if len(vectors)>1:
        cosine=np.einsum("ij,ij->i",vectors[:-1],vectors[1:]) / (
            np.linalg.norm(vectors[:-1],axis=1)*np.linalg.norm(vectors[1:],axis=1))
        if np.any(cosine<math.cos(math.radians(45.))):
            return None,"SHARP_JOIN_REQUIRES_OTHER_REPRESENTATION"
    return dict(points_px=path.tolist(), width_px=width, lineweight_hundredth_mm=int(code),
                length_px=length, source_to_pen_error_px=source_error,
                pen_to_source_error_px=reverse, source_pixels=int(mask.sum()),
                minimum_foreign_pixel_clearance_px=clearance if math.isfinite(clearance) else None,
                maximum_measured_pen_edge_shift_px=edge_shift,
                measured_width_range_px=(float(widths.min()),float(widths.max())),
                raw_nodes=len(raw)), "COMPLETE_UNCONTESTED_OPEN_STROKE"


def _runs(mask: np.ndarray) -> tuple[tuple[int,int,int], ...]:
    result = []
    for y,row in enumerate(mask):
        edges = np.diff(np.r_[False,row,False].astype(np.int8))
        result.extend((y,int(a),int(b)) for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))
    return tuple(result)


def recover_observed_open_strokes(gray: np.ndarray, binary: np.ndarray, visible_binary: np.ndarray,
                                  *, protected_masks: Sequence[np.ndarray | None]=(), dpi: float=100.
                                  ) -> tuple[np.ndarray, tuple[TracePath,...], tuple[dict,...], dict]:
    review: dict[str,Any] = dict(version=VERSION, accepted=0, source_pixels=0, decisions=[],
                                creates_connection=False, electrical_semantics="NOT_INFERRED")
    if (not isinstance(gray,np.ndarray) or gray.ndim!=2 or gray.dtype!=np.uint8
            or binary.shape!=gray.shape or visible_binary.shape!=gray.shape
            or not math.isfinite(dpi) or dpi<=0
            or any(p is not None and p.shape!=gray.shape for p in protected_masks)):
        review["status"]="SKIPPED_INPUT_CONTRACT"
        return visible_binary,(),(),review
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(gray<254),connectivity=8)
    output = visible_binary; paths=[]; records=[]; budget=MAX_TOTAL_LOCAL_PIXELS
    pad=max(3,int(math.ceil(4*dpi/100.))+1)
    for label in range(1,count):
        x,y,w,h,area=map(int,stats[label])
        if max(w,h)<MIN_LENGTH_MM*dpi/25.4*.9 or area<MIN_LENGTH_MM*dpi/25.4*.9:
            continue
        size=(w+2*pad)*(h+2*pad)
        if area>MAX_COMPONENT_PIXELS or size>MAX_LOCAL_PIXELS:
            continue
        item=dict(bbox=(x,y,w,h),source_pixels=area,decision="REJECTED")
        review['decisions'].append(item)
        if len(review['decisions'])>MAX_CHECKS or budget<size:
            item['reason']='RESOURCE_BUDGET';break
        budget-=size
        if x<pad or y<pad or x+w+pad>gray.shape[1] or y+h+pad>gray.shape[0]:
            item['reason']='PAGE_EDGE_COMPONENT';continue
        sl=np.s_[y-pad:y+h+pad,x-pad:x+w+pad]
        component=labels[sl]==label
        protected=np.zeros(component.shape,bool)
        for p in protected_masks:
            if p is not None:protected|=p[sl]>0
        if np.any(component & protected):
            item['reason']='PROTECTED_OR_SHARED_SOURCE';continue
        if np.any(component & (binary[sl]>=128)):
            item['reason']='SOURCE_NOT_IN_CURRENT_FOREGROUND';continue
        if np.any(component & (visible_binary[sl]>=128)):
            item['reason']='SOURCE_ALREADY_CLAIMED';continue
        foreign=((gray[sl]<254)&~component)|protected
        fit,reason=_fit(component,gray[sl],foreign,float(dpi))
        item['reason']=reason
        if fit is None:continue
        path=np.asarray(fit['points_px'])+(x-pad,y-pad)
        old_paths=trace_binary(np.where(component,0,255).astype(np.uint8))
        if not old_paths:
            item['reason']='NO_SOURCE_BOUNDARY';continue
        record=dict(fit, kind='open_stroke',bbox=(x,y,w,h),native_scan=False,
                    native_source_open_stroke=True,dpi=float(dpi),points_px=tuple(map(tuple,path)),
                    source_runs_y_x0_x1=tuple((ry+y-pad,a+x-pad,b+x-pad) for ry,a,b in _runs(component)),
                    original_boundary_paths_px=tuple(tuple((px+x-pad,py+y-pad) for px,py in p.points)
                                                     for p in old_paths),
                    classification='OBSERVED_ISOLATED_OPEN_STROKE',creates_connection=False,
                    historical_identity='NOT_PROVEN',width_space='paper_mm')
        paths.append(TracePath(tuple(map(tuple,path)),None,0,len(paths)));records.append(record)
        if output is visible_binary:output=visible_binary.copy()
        output[sl][component]=255
        item.update(decision='ACCEPTED',source_to_pen_error_px=fit['source_to_pen_error_px'],
                    pen_to_source_error_px=fit['pen_to_source_error_px'],
                    lineweight_hundredth_mm=fit['lineweight_hundredth_mm'],vertices=len(path))
        review['accepted']+=1;review['source_pixels']+=area
    return output,tuple(paths),tuple(records),review
