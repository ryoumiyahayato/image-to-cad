"""Bounded additive retention of complete visible PDF strokes on native fills.

A separate policy from P19-E replacement. No raster member is removed. Complete
paths keep butt caps and miter joins as editable constant-width LWPOLYLINEs.
"""
from __future__ import annotations
import ctypes as ct
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
import numpy as np
from app.core.structure import metadata_to_jsonable
from app.geometry.native_source_group import _read_paths, BUDGETS

POLICY = 'pdf-stroke-on-native-fill-v1'
KEY = 'native_stroke_paths_v1'


def _segments(points, closed):
    return tuple(zip(points, (*points[1:], points[0]))) if closed else tuple(zip(points, points[1:]))


def _inside_segment(a, b, polygon):
    """Test every interval split by polygon intersections, not just sample centers."""
    a,b=np.asarray(a),np.asarray(b);v=b-a;cuts=[0.,1.]
    for p,q in zip(polygon,(*polygon[1:],polygon[0])):
        p,q=np.asarray(p),np.asarray(q);w=q-p;den=np.cross(v,w)
        if abs(den)>1e-10:
            t=np.cross(p-a,w)/den;u=np.cross(p-a,v)/den
            if 0<=t<=1 and 0<=u<=1:cuts.append(float(t))
    import cv2
    ring=np.asarray(polygon,dtype=np.float32)
    cuts=sorted(set(cuts))
    return all(cv2.pointPolygonTest(ring,tuple(map(float,a+v*t)),True)>=-1e-5
               for t in [*cuts,*[(x+y)/2 for x,y in zip(cuts,cuts[1:])]])


def _path_points(path):
    values=path['segments']
    if not 2<=len(values)<=BUDGETS['path_segments'] or values[0]['type']!=2 or any(s['type']!=0 for s in values[1:]):
        raise ValueError('UNSUPPORTED_NONLINEAR_OR_MULTIPATH')
    if any(s['close'] for s in values[:-1]):raise ValueError('UNSUPPORTED_EARLY_CLOSE')
    points=tuple(tuple(s['point']) for s in values);closed=bool(values[-1]['close'])
    if closed and points[-1]==points[0]:points=points[:-1]
    if len(points)<(3 if closed else 2) or any(np.linalg.norm(np.asarray(b)-a)<1e-7 for a,b in _segments(points,closed)):
        raise ValueError('DEGENERATE_SOURCE_PATH')
    return points,closed


def _ambiguous_edge(structure, points, closed, width):
    """Unknown nearby raster geometry is retained, never silently transferred."""
    candidates=[]
    for line in structure.straight_lines:candidates.append((line.p1,line.p2))
    for path in structure.contours:candidates.extend(_segments(tuple(path.points),True))
    if not candidates:return None
    starts=np.asarray([x[0] for x in candidates]);ends=np.asarray([x[1] for x in candidates])
    for index,(a,b) in enumerate(_segments(points,closed)):
        a,b=np.asarray(a),np.asarray(b);v=b-a;length=np.linalg.norm(v);u=v/length;n=np.array([-u[1],u[0]])
        distance=np.maximum(abs((starts-a)@n),abs((ends-a)@n));lo=np.minimum((starts-a)@u,(ends-a)@u);hi=np.maximum((starts-a)@u,(ends-a)@u)
        overlap=np.maximum(0,np.minimum(length,hi)-np.maximum(0,lo))
        hits=np.flatnonzero((distance<=width/2)&(overlap>=length-1e-6))
        if len(hits):return dict(edge_index=index,candidate_indices=hits.tolist(),distance_px=[float(distance[i]) for i in hits])
    return None


def validate_records(structure):
    records=structure.provenance.get('stroke_presentation',{}).get(KEY,())
    seen=set();fills={f.object_id:f for f in structure.native_fills}
    for r in records:
        if r['policy']!=POLICY or r['source_id'] in seen:raise ValueError('NATIVE_STROKE_IDENTITY')
        seen.add(r['source_id']);points,closed=_path_points(r['path'])
        if points!=tuple(tuple(p) for p in r['points']) or closed!=r['closed']:raise ValueError('NATIVE_STROKE_PARENT_GEOMETRY')
        if r['fill_id'] not in fills or metadata_to_jsonable(fills[r['fill_id']].payload())!=metadata_to_jsonable(r['fill']):raise ValueError('NATIVE_STROKE_FILL_BINDING')
        if not (np.isfinite(r['width_px']) and 0<r['width_px']<=64):raise ValueError('NATIVE_STROKE_WIDTH')
        if abs(r['width_px']-r['path']['width_pt']*r['source_dpi']/72)>1e-8:raise ValueError('NATIVE_STROKE_WIDTH_BINDING')
        if r['path']['line_cap']!=0 or r['line_join']!=0 or r['path']['dash_count'] or r['path']['transparent']:raise ValueError('NATIVE_STROKE_STYLE')
        if any(not (0<=x<=structure.source_size_px[0] and 0<=y<=structure.source_size_px[1]) for x,y in points):raise ValueError('NATIVE_STROKE_CANVAS')
        if not r['visibility']['reference_equal'] or not r['visibility']['context_composite_equal']:raise ValueError('NATIVE_STROKE_VISIBILITY')
    return records


def _failure_record(exc, step, **context):
    reason = str(exc)
    budget = reason.startswith('NOT_EVALUATED_') or reason in {
        'GROUP_TIME_BUDGET', 'GROUP_PATH_BUDGET', 'GROUP_FORM_OR_OBJECT_BUDGET',
        'NATIVE_STROKE_PAGE_BUDGET', 'NATIVE_STROKE_PDF_BUDGET'}
    rejected = reason.startswith(('DEGENERATE_', 'EXISTING_EDGE_', 'COMMITTED_SOURCE_',
        'REFERENCE_', 'INCOMPLETE_REFERENCE_', 'OCCLUDED_', 'PARENT_GRID_'))
    decision = ('NOT_EVALUATED' if budget else 'UNSUPPORTED' if reason.startswith('UNSUPPORTED_')
                else 'REJECTED' if isinstance(exc, ValueError) and rejected else 'ERROR')
    return dict(context, decision=decision, reason=reason, error_type=type(exc).__name__, step=step)


@dataclass(frozen=True)
class NativeStrokePlan:
    base: object
    records: tuple
    decisions: tuple


def collect_plan(structure, image, evidence):
    import cv2,pypdfium2 as pdfium
    started=perf_counter();records=[];decisions=[]
    if not getattr(evidence,'native_fills',()):return NativeStrokePlan(structure,(),())
    if evidence.source_size_px!=structure.source_size_px:raise ValueError('NATIVE_STROKE_PARENT_SIZE')
    if image.size>BUDGETS['page_pixels']:raise ValueError('NATIVE_STROKE_PAGE_BUDGET')
    source=Path(evidence.binding['document'])
    if source.stat().st_size>BUDGETS['pdf_bytes']:raise ValueError('NATIVE_STROKE_PDF_BUDGET')
    doc=pdfium.PdfDocument(source.read_bytes());page=doc[evidence.binding['page_number']-1];raw=pdfium.raw
    objects=[];states=[];w,h=structure.source_size_px;scale=evidence.binding['requested_dpi']/72;charged=0;renders=0
    def render(box=None,reference=None,gray=False):
        nonlocal charged,renders
        if perf_counter()-started>BUDGETS['seconds']:raise ValueError('NOT_EVALUATED_TIME_BUDGET')
        if box:
            size=(box[2]-box[0])*(box[3]-box[1]);charged+=size;renders+=1
            if size>BUDGETS['local_pixels'] or charged>BUDGETS['total_local_pixels'] or renders>BUDGETS['local_renders']:raise ValueError('NOT_EVALUATED_RENDER_BUDGET')
        crop=(0,0,0,0) if box is None else tuple(max(0,v-1e-5)/scale for v in (box[0],h-box[3],w-box[2],box[1]))
        bm=(reference or page).render(scale=scale,crop=crop,grayscale=gray)
        try:return np.array(bm.to_pil().convert('L' if gray else 'RGB'))
        finally:bm.close()
    def switch(selected=None,without=None):
        for i,(o,state) in enumerate(zip(objects,states)):
            if not raw.FPDFPageObj_SetIsActive(o,state if (selected is None or i in selected) and i!=without else 0):raise ValueError('NATIVE_STROKE_STATE')
    try:
        objects,states,paths,_=_read_paths(page,evidence.page_to_pixel,raw,started+BUDGETS['seconds'])
        if not np.array_equal(render(gray=image.ndim==2),image):raise ValueError('NATIVE_STROKE_SOURCE_RENDER_CHANGED')
        baseline=render();existing=validate_records(structure)
        fill_boxes=[(f,np.asarray(f.points).min(axis=0),np.asarray(f.points).max(axis=0)) for f in evidence.native_fills]
        for path in paths:
            if perf_counter()-started>BUDGETS['seconds']:
                decisions.append(dict(decision='NOT_EVALUATED',reason='TIME_BUDGET',step='candidate_loop',from_object=path['index'],remaining_scope='UNTRAVERSED_TAIL_COUNT_UNKNOWN'));break
            if path['fill'] or not path['stroke']:continue
            step='candidate_geometry'
            try:
                points,closed=_path_points(path);p=np.asarray(points)
                fills=[f for f,lo,hi in fill_boxes if f.source.object_index<path['index']
                       and np.all(p>=lo-1e-6) and np.all(p<=hi+1e-6)
                       and all(_inside_segment(a,b,f.points) for a,b in _segments(points,closed))]
                if not fills:continue
                # Require an actual interior stroke, not solely an area border.
                ring=np.asarray(fills[0].points,dtype=np.float32)
                if not any(cv2.pointPolygonTest(ring,tuple(map(float,(np.asarray(a)+b)/2)),True)>1 for a,b in _segments(points,closed)):continue
                step='style_and_source_binding'
                fill=fills[0];rgba=path['rgba'];join=raw.FPDFPageObj_GetLineJoin(objects[path['index']])
                if not (rgba[0]==rgba[1]==rgba[2] and fill.rgb[0]==fill.rgb[1]==fill.rgb[2] and rgba[0]<fill.rgb[0] and rgba[3]==255):raise ValueError('UNSUPPORTED_NONMONOCHROME_OR_NO_CONTRAST')
                if path['line_cap']!=0 or join!=0 or path['dash_count'] or path['transparent'] or path['clip_count']>0:raise ValueError('UNSUPPORTED_STYLE_OR_CLIP')
                ma,mb,mc,md,_,_=path['matrix']
                if not np.allclose([ma*ma+mb*mb,mc*mc+md*md,ma*mc+mb*md],[1,1,0],atol=1e-6):raise ValueError('UNSUPPORTED_SCALED_PEN')
                width=path['width_pt']*scale
                if not 0<width<=64:raise ValueError('UNSUPPORTED_PEN_WIDTH')
                sid=f"PDF-STROKE:p{evidence.binding['page_number']}:o{path['index']}:v1"
                previous=next((r for r in existing if r['source_id']==sid),None)
                if previous:
                    if metadata_to_jsonable(previous['path'])!=path:raise ValueError('COMMITTED_SOURCE_CHANGED')
                    records.append(metadata_to_jsonable(previous));decisions.append(dict(object_index=path['index'],decision='REUSED'));continue
                ambiguous=_ambiguous_edge(structure,points,closed,width)
                if ambiguous:raise ValueError('EXISTING_EDGE_IDENTITY_UNRESOLVED:'+str(ambiguous))
                pad=int(np.ceil(10*width))+2;lo=np.floor(p.min(axis=0)).astype(int)-pad;hi=np.ceil(p.max(axis=0)).astype(int)+pad;box=tuple(map(int,(*lo,*hi)))
                if lo.min()<0 or hi[0]>w or hi[1]>h:raise ValueError('UNSUPPORTED_PAGE_EDGE')
                step='visibility_render'
                switch();full=render(box);switch(selected={path['index']});only=render(box);switch(without=path['index']);without=render(box)
                # Use the actual physical parent page and inverse loader map.
                # Raster dimensions are ceil-rounded and are not a PDF MediaBox.
                # Preserve the original CTM evaluation as well: flattening its
                # float coordinates can change thin-stroke AA by a few levels.
                step='reference_geometry'
                local_points=[]
                original=objects[path['index']]
                for j in range(raw.FPDFPath_CountSegments(original)):
                    segment=raw.FPDFPath_GetPathSegment(original,j);xx,yy=ct.c_float(),ct.c_float()
                    if not raw.FPDFPathSegment_GetPoint(segment,ct.byref(xx),ct.byref(yy)):raise ValueError('REFERENCE_LOCAL_POINT')
                    local_points.append((xx.value,yy.value))
                reference=pdfium.PdfDocument.new();rp=reference.new_page(*page.get_size());shape=raw.FPDFPageObj_CreateNewPath(*local_points[0])
                try:
                    for x,y in local_points[1:]:
                        if not raw.FPDFPath_LineTo(shape,x,y):raise ValueError('REFERENCE_GEOMETRY')
                    if closed:raw.FPDFPath_Close(shape)
                    raw.FPDFPageObj_Transform(shape,*path['matrix'])
                    if not (raw.FPDFPageObj_SetStrokeColor(shape,*rgba) and raw.FPDFPageObj_SetStrokeWidth(shape,path['width_pt']) and raw.FPDFPageObj_SetLineCap(shape,0) and raw.FPDFPageObj_SetLineJoin(shape,0) and raw.FPDFPath_SetDrawMode(shape,0,1)):raise ValueError('REFERENCE_STYLE')
                    raw.FPDFPage_InsertObject(rp,shape);shape=None;expected=render(box,reference=rp)
                finally:
                    if shape:raw.FPDFPageObj_Destroy(shape)
                    rp.close();reference.close()
                step='visibility_comparison'
                if only.shape!=expected.shape or np.max(abs(only.astype(int)-expected.astype(int)))>2:raise ValueError('REFERENCE_CLIP_OR_JOIN_CHANGED')
                ink=np.any(expected<255,axis=2)
                if not ink.any() or any(np.any(ink[s]) for s in [0,-1]) or np.any(ink[:,0]) or np.any(ink[:,-1]):raise ValueError('INCOMPLETE_REFERENCE_BOUNDS')
                alpha=(255-expected[:,:,0].astype(float))/(255-rgba[0]);prediction=rgba[0]*alpha[:,:,None]+without*(1-alpha[:,:,None])
                if full.shape!=prediction.shape or np.max(abs(full[ink].astype(float)-prediction[ink]))>2:raise ValueError('OCCLUDED_OR_CONTEXT_COMPOSITING_CHANGED')
                # PDFium may clip unrelated context at the window boundary.
                # Every pixel of the complete candidate stroke must still equal
                # the unmodified full-page render, including its AA/end/join ink.
                if not np.array_equal(full[ink],baseline[box[1]:box[3],box[0]:box[2]][ink]):raise ValueError('PARENT_GRID_CHANGED')
                record=dict(policy=POLICY,source_id=sid,document=evidence.binding['document'],page_number=evidence.binding['page_number'],source_dpi=scale*72,source_size_px=[w,h],page_to_pixel=list(evidence.page_to_pixel),path=path,points=points,closed=closed,width_px=width,rgb=rgba[:3],line_join=join,fill_id=fill.object_id,fill=fill.payload(),visibility=dict(reference_equal=True,context_composite_equal=True,clip_api_count=path['clip_count'],full_ink_pixels=int(ink.sum()),box=list(box),reference_max_error=int(np.max(abs(only.astype(int)-expected.astype(int)))),context_max_error=float(np.max(abs(full[ink]-prediction[ink])))))
                records.append(record);decisions.append(dict(object_index=path['index'],decision='ADDED_COMPLETE_PATH',edges=len(_segments(points,closed))))
            except (ValueError,TypeError) as exc:
                failure=_failure_record(exc,step,object_index=path['index'])
                if failure['decision']=='NOT_EVALUATED':failure['remaining_scope']='UNTRAVERSED_TAIL_COUNT_UNKNOWN'
                decisions.append(failure)
                if failure['decision']=='NOT_EVALUATED':break
        return NativeStrokePlan(structure,tuple(records),tuple(decisions))
    finally:
        for o,state in zip(objects,states):raw.FPDFPageObj_SetIsActive(o,state)
        for o,state in zip(objects,states):
            actual=raw.FPDF_BOOL()
            if not raw.FPDFPageObj_GetIsActive(o,ct.byref(actual)) or actual.value!=state:raise RuntimeError('NATIVE_STROKE_RESTORE_FAILED')
        if objects:
            bm=page.render(scale=scale,grayscale=image.ndim==2)
            try:restored=np.array(bm.to_pil().convert('L' if image.ndim==2 else 'RGB'))
            finally:bm.close()
            if not np.array_equal(restored,image):raise RuntimeError('NATIVE_STROKE_RESTORED_RENDER_CHANGED')
        page.close();doc.close()


def commit_plan(structure,plan):
    if structure is not plan.base:raise ValueError('NATIVE_STROKE_STALE_PLAN')
    provenance=metadata_to_jsonable(structure.provenance);presentation=provenance.setdefault('stroke_presentation',{});old=presentation.get(KEY,[])
    records={r['source_id']:r for r in old}
    for r in plan.records:
        if r['source_id'] in records and records[r['source_id']]!=r:raise ValueError('NATIVE_STROKE_SOURCE_CHANGED')
        records[r['source_id']]=r
    if records:presentation[KEY]=list(records.values())
    return replace(structure,provenance=provenance,observations=(*structure.observations,dict(event=POLICY,decisions=plan.decisions)))


def apply_native_strokes(structure,image,evidence):
    if not getattr(evidence,'native_fills',()):return structure
    try:return commit_plan(structure,collect_plan(structure,image,evidence))
    except (ValueError,KeyError,OSError) as exc:
        failure=_failure_record(exc,'collect_or_commit',event=POLICY,output_action='RETAINED')
        return replace(structure,observations=(*structure.observations,failure))
