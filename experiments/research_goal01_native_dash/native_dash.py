"""Bounded native dash evidence. No raster-gap inference or production writes."""
import ctypes as ct
import math
from pathlib import Path
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw

POLICY=dict(version='native-dash-edit-unit-v1.1',page_rotation='private-memory canonicalization; original rotation recorded',max_objects=12000,
    path_segments=2,line_cap=0,stroke_only=True,opaque_only=True,similarity_rtol=1e-6,
    positive_dash_values_only=True,render_scale=4,roi_padding_pt=3,
    reconstruction_iou_min=.995,all_center_witnesses_visible=True,
    source_kind='one native PDF drawing path, not an inferred engineering member',
    no_raster_group_inference=True,no_occluded_interval_completion=True)

def dash_intervals(length,pattern,phase):
    p=list(map(float,pattern));p=p*2 if len(p)%2 else p
    if not p or min(p)<=0:raise ValueError('positive dash lengths required')
    phase=float(phase)%sum(p);i=0
    while phase>=p[i]-1e-10:
        phase-=p[i];i=(i+1)%len(p)
    pos=0.;remaining=p[i]-phase;on=[]
    while pos<length-1e-9:
        end=min(length,pos+remaining)
        if i%2==0 and end>pos:on.append([pos,end])
        pos=end;i=(i+1)%len(p);remaining=p[i]
    return on
def page_objects(page):return list(page.get_objects(max_depth=1))
def canonical_page(page):
    rotation=page.get_rotation();media=page.get_mediabox();crop=page.get_cropbox()
    if not np.allclose(media[:2],[0,0],atol=1e-6) or not np.allclose(crop,media,atol=1e-6):raise ValueError('nontrivial page crop/origin unsupported')
    page.set_rotation(0)
    return dict(original_page_rotation=rotation,coordinate_frame='unrotated PDF canvas, bottom-left origin; source file unchanged',media_box=list(media))
def metadata(index,obj):
    row=dict(index=index,type=obj.type)
    if obj.type!=raw.FPDF_PAGEOBJ_PATH:return row
    count=raw.FPDFPageObj_GetDashCount(obj);row['dash_count']=count
    if count<=0:return row
    arr=(ct.c_float*count)();phase=ct.c_float()
    if not raw.FPDFPageObj_GetDashArray(obj,arr,count) or not raw.FPDFPageObj_GetDashPhase(obj,ct.byref(phase)):raise RuntimeError('dash metadata unavailable')
    fill=ct.c_int();stroke=raw.FPDF_BOOL();raw.FPDFPath_GetDrawMode(obj,ct.byref(fill),ct.byref(stroke))
    width=ct.c_float();raw.FPDFPageObj_GetStrokeWidth(obj,ct.byref(width));rgba=[ct.c_uint() for _ in range(4)];raw.FPDFPageObj_GetStrokeColor(obj,*[ct.byref(v) for v in rgba])
    segments=[];n=raw.FPDFPath_CountSegments(obj)
    for j in range(n):
        seg=raw.FPDFPath_GetPathSegment(obj,j);x,y=ct.c_float(),ct.c_float();raw.FPDFPathSegment_GetPoint(seg,ct.byref(x),ct.byref(y))
        segments.append(dict(type=raw.FPDFPathSegment_GetType(seg),point=[x.value,y.value],close=bool(raw.FPDFPathSegment_GetClose(seg))))
    active=raw.FPDF_BOOL();raw.FPDFPageObj_GetIsActive(obj,ct.byref(active));clip=raw.FPDFPageObj_GetClipPath(obj)
    row.update(dash=list(arr),phase=phase.value,fill=fill.value,stroke=bool(stroke.value),width=width.value,
        cap=raw.FPDFPageObj_GetLineCap(obj),rgba=[v.value for v in rgba],matrix=list(obj.get_matrix().get()),segments=segments,
        transparent=bool(raw.FPDFPageObj_HasTransparency(obj)),clip_count=raw.FPDFClipPath_CountPaths(clip) if clip else 0,
        active=bool(active.value),bounds=list(obj.get_bounds()))
    return row
def screen(row):
    if row.get('dash_count',0)<=0:return 'NO_EXPLICIT_DASH_AUTHORITY'
    s=row['segments']
    if len(s)!=2 or [x['type'] for x in s]!=[raw.FPDF_SEGMENT_MOVETO,raw.FPDF_SEGMENT_LINETO] or any(x['close'] for x in s):return 'NOT_SINGLE_OPEN_STRAIGHT_PATH'
    if not row['stroke'] or row['fill']!=0:return 'FILL_OR_NO_STROKE'
    if not row['active'] or row['transparent'] or row['rgba'][3]!=255:return 'INACTIVE_OR_TRANSPARENT'
    if row['cap']!=0:return 'UNSUPPORTED_CAP'
    if row['clip_count']>0:return 'EXPLICIT_CLIP'
    if not row['dash'] or min(row['dash'])<=0:return 'ZERO_OR_INVALID_DASH'
    a,b,c,d,e,f=row['matrix'];mat=np.array([[a,c],[b,d]],float);sv=np.linalg.svd(mat,compute_uv=False)
    if sv.min()<=0 or not np.isclose(sv[0],sv[1],rtol=POLICY['similarity_rtol'],atol=1e-10):return 'NONUNIFORM_TRANSFORM'
    points=np.array([s[0]['point'],s[1]['point']],float);mapped=points@mat.T+[e,f]
    if not np.isfinite(mapped).all() or np.linalg.norm(points[1]-points[0])<1e-6 or row['width']<=0:return 'DEGENERATE'
    row['page_points']=mapped.tolist();row['page_width']=row['width']*float(sv[0]);row['uniform_scale']=float(sv[0])
    return None
def expand(row,phase=None):
    a,b=np.array(row['page_points']);v=b-a;length=np.linalg.norm(v);pattern=np.array(row['dash'])*row['uniform_scale'];phase=row['phase']*row['uniform_scale'] if phase is None else phase
    intervals=dash_intervals(length,pattern,phase)
    return [(a+v*(x/length),a+v*(y/length)) for x,y in intervals]
def simple_pdf_bytes(width,height,segments,stroke_width,rgb):
    # An in-memory rendering witness, not an external document or data upload.
    c=['q',f'{stroke_width:.10f} w','0 J',f'{rgb[0]/255:.8f} {rgb[1]/255:.8f} {rgb[2]/255:.8f} RG']
    for a,b in segments:c.append(f'{a[0]:.10f} {a[1]:.10f} m {b[0]:.10f} {b[1]:.10f} l S')
    c.append('Q');stream='\n'.join(c).encode('ascii')
    objs=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.10f} {height:.10f}] /Resources << >> /Contents 4 0 R >>'.encode(),b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,o in enumerate(objs,1):offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+o+b'\nendobj\n'
    start=len(data);data+=f'xref\n0 {len(objs)+1}\n0000000000 65535 f \n'.encode()
    for v in offsets[1:]:data+=f'{v:010d} 00000 n \n'.encode()
    data+=f'trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode();return bytes(data)
def roi_for(row,size):
    a=np.array(row['page_points']);pad=max(POLICY['roi_padding_pt'],row['page_width']*2)
    return [max(0,math.floor(a[:,0].min()-pad)),max(0,math.floor(a[:,1].min()-pad)),min(math.floor(size[0]),math.ceil(a[:,0].max()+pad)),min(math.floor(size[1]),math.ceil(a[:,1].max()+pad))]
def render_roi(page,box):
    w,h=page.get_size();x0,y0,x1,y1=box
    return np.array(page.render(scale=POLICY['render_scale'],crop=(x0,y0,w-x1,h-y1)).to_pil().convert('RGB'))
def set_active(obj,state):
    if not raw.FPDFPageObj_SetIsActive(obj,int(state)):raise RuntimeError('activation failed')
def visibility(page,objects,row):
    box=roi_for(row,page.get_size());states=[]
    for o in objects:
        v=raw.FPDF_BOOL();raw.FPDFPageObj_GetIsActive(o,ct.byref(v));states.append(bool(v.value))
    full=render_roi(page,box)
    try:
        for o in objects:set_active(o,False)
        set_active(objects[row['index']],True);only=render_roi(page,box)
        for o,s in zip(objects,states):set_active(o,s)
        set_active(objects[row['index']],False);without=render_roi(page,box)
    finally:
        for o,s in zip(objects,states):set_active(o,s)
    restored=render_roi(page,box);assert np.array_equal(restored,full),'page activation not restored'
    on=expand(row);proxy=pdfium.PdfDocument(simple_pdf_bytes(*page.get_size(),on,row['page_width'],row['rgba'][:3]));pred=render_roi(proxy[0],box)
    srcink=only.min(axis=2)<200;predink=pred.min(axis=2)<200;union=int((srcink|predink).sum());intersection=int((srcink&predink).sum());iou=intersection/max(1,union)
    delta=np.max(np.abs(full.astype(int)-without.astype(int)),axis=2);witnesses=[];scale=POLICY['render_scale']
    for a,b in on:
        n=max(1,math.ceil(np.linalg.norm(b-a)*scale));ts=(np.arange(n)+.5)/n;ps=a[None,:]+ts[:,None]*(b-a)[None,:]
        xs=np.floor((ps[:,0]-box[0])*scale).astype(int);ys=np.floor((box[3]-ps[:,1])*scale).astype(int)
        good=(xs>=0)&(xs<delta.shape[1])&(ys>=0)&(ys<delta.shape[0]);witnesses.extend((good&(delta[np.clip(ys,0,delta.shape[0]-1),np.clip(xs,0,delta.shape[1]-1)]>=2)).tolist())
    why=None
    if iou<POLICY['reconstruction_iou_min']:why='DASH_RECONSTRUCTION_OR_CLIP_MISMATCH'
    elif not all(witnesses):why='SOURCE_NOT_FULLY_VISIBLE_OR_DUPLICATE'
    facts=dict(box_pdf=box,scale=scale,iou=iou,source_ink_pixels=int(srcink.sum()),proxy_ink_pixels=int(predink.sum()),pixel_difference=int(np.any(only!=pred,axis=2).sum()),
        center_witnesses=len(witnesses),visible_center_witnesses=int(sum(witnesses)),restored_identical=True,clip_api_count=row['clip_count'],
        clip_policy='negative/unavailable clip count alone is not accepted; independent reconstructed geometry must match actual isolated raster')
    return why,facts,dict(full=full,only=only,without=without,proxy=pred)
def collect(path,page_index=0,indices=None,max_candidates=12):
    doc=pdfium.PdfDocument(Path(path).read_bytes());page=doc[page_index]
    page_coordinates=canonical_page(page)
    objs=page_objects(page)
    if len(objs)>POLICY['max_objects']:raise ValueError('page object budget')
    records=[];images={};eligible=0
    for i,o in enumerate(objs):
        row=metadata(i,o)
        if row.get('dash_count',0)<=0:continue
        if indices is not None and i not in indices:continue
        row.update(source=str(Path(path).resolve()),page=page_index+1,role='SOURCE_DRAWING_PATH, not a beam/wall identity',**page_coordinates)
        reason=screen(row)
        if reason is None:
            eligible+=1
            if eligible>max_candidates:reason='LOCAL_EVIDENCE_BUDGET'
            else:
                reason,facts,im=visibility(page,objs,row);row['visibility']=facts;images[i]=im
        row['decision']='ACCEPT_EDIT_UNIT' if reason is None else 'KEEP_UNCHANGED';row['reason']=reason or 'explicit complete visible dashed drawing path'
        if reason is None:row['on_segments']=[[a.tolist(),b.tolist()] for a,b in expand(row)]
        records.append(row)
    return records,images,dict(page_size=list(page.get_size()),root_objects=len(objs),policy=POLICY,**page_coordinates)
