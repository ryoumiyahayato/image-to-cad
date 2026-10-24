"""One isolated native-stroke repair mechanism. No QA file or target IDs read."""
import os,sys,json,ctypes as ct,time,math,argparse
from pathlib import Path
from types import SimpleNamespace
import numpy as np,cv2,ezdxf,pypdfium2 as pdfium,pypdfium2.raw as raw
from ezdxf.lldxf.tagwriter import TagCollector
ROOT=Path(__file__).resolve().parents[2]
FROZEN=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
sys.path.insert(0,str(FROZEN))
from app.geometry.native_source_group import _read_paths
from reference_p20d_native_stroke import _path_points,_segments,_inside_segment,_ambiguous_edge

POLICY={'version':'parent-grid-visible-stroke-v1','source':'opaque native monochrome stroke over accepted earlier native fill',
    'cap':0,'join':0,'dash':False,'transparency':False,'reference_error_max':2,'context_error_max':2,
    'parent_grid_equal':True,'native_width_px_max':64,'candidate_paths_max':20,'source_page_pixels_max':32000000,
    'local_roi_pixels_max':1000000,'time_budget_seconds':300,'geometry_edits':'add only; no old entity deletion or changes',
    'simple_control':'same rules; P20-D crop renderer rather than full-parent render then crop',
    'no_model':True,'no_target_labels':True}
def load(p):return json.loads(Path(p).read_text('utf8'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=lambda v:v.item() if hasattr(v,'item') else str(v)),'utf8')
def records(doc):return {e.dxf.handle:[(t.code,str(t.value)) for t in TagCollector.dxftags(e)] for e in doc.modelspace()}

def coordinate_map(doc,info):
    areas={f"PDF-FILL:p{f['source']['page_number']}:o{f['source']['object_index']}:s{f['source']['subpath_index']}":f for f in info['native_fills']}
    source=[];world=[];used=[]
    for e in doc.modelspace().query('HATCH'):
        if not e.has_xdata('P18_NATIVE_FILL'):continue
        sid=e.get_xdata('P18_NATIVE_FILL')[0].value
        if sid not in areas or len(e.paths)!=1 or not hasattr(e.paths[0],'vertices'):continue
        points=areas[sid]['points'];vertices=e.paths[0].vertices
        if len(points)!=len(vertices):continue
        source.extend(points);world.extend([v[:2] for v in vertices]);used.append(sid)
    if len(source)<6:raise ValueError('No sufficient identified native area correspondence')
    source=np.array(source);world=np.array(world);matrix=np.linalg.lstsq(np.c_[source,np.ones(len(source))],world,rcond=None)[0]
    error=np.linalg.norm(np.c_[source,np.ones(len(source))]@matrix-world,axis=1)
    unit=matrix[0,0]
    if max(error)>1e-6 or unit<=0 or not np.allclose(matrix[:2],[[unit,0],[0,-unit]],atol=1e-8,rtol=0):raise ValueError('Unsupported or inconsistent published coordinate mapping')
    return {'source_to_world':matrix.tolist(),'unit_per_source_pixel':float(unit),'matched_fill_ids':used,'matched_vertices':len(source),'max_error_world':float(max(error))}

def existing_structure(doc,frame):
    m=np.array(frame['source_to_world']);u=frame['unit_per_source_pixel'];offset=m[2]
    def inverse(q):return ((q[0]-offset[0])/u,(offset[1]-q[1])/u)
    lines=[];contours=[]
    for e in doc.modelspace():
        if e.dxftype()=='LINE':lines.append(SimpleNamespace(p1=inverse(e.dxf.start),p2=inverse(e.dxf.end)))
        elif e.dxftype()=='LWPOLYLINE':
            pts=[inverse(p) for p in e.get_points('xy')]
            # Open polylines are represented as separate edges here; do not add a closure.
            for a,b in zip(pts,pts[1:]+([pts[0]] if e.closed and pts else [])):lines.append(SimpleNamespace(p1=a,p2=b))
    return SimpleNamespace(straight_lines=lines,contours=contours)

def qualifies(path,fills,roi):
    points,closed=_path_points(path);p=np.array(points)
    if np.any(p<np.array(roi[:2])) or np.any(p>np.array(roi[2:])):return None
    areas=[f for f in fills if f['source']['object_index']<path['index'] and
        all(_inside_segment(a,b,f['points']) for a,b in _segments(points,closed))]
    if not areas:return None
    area=areas[0];ring=np.array(area['points'],np.float32)
    if not any(cv2.pointPolygonTest(ring,tuple(map(float,(np.array(a)+b)/2)),True)>1 for a,b in _segments(points,closed)):return None
    return points,closed,area

def study(pdf_file,page_number,dpi,info,doc,roi,mode,out):
    start=time.perf_counter();pdf=pdfium.PdfDocument(pdf_file);page=pdf[page_number-1]
    if page.get_rotation()!=0:raise ValueError('Page rotation unsupported; no silent canonicalization')
    width,height=info.get('size',info.get('size_px'));scale=dpi/72
    if width*height>POLICY['source_page_pixels_max']:raise ValueError('Page budget')
    mapping=info['native_fills'][0]['page_to_pixel']
    objects,states,paths,nonpaths=_read_paths(page,mapping,raw)
    full_parent=None;render_count=0
    def render(box=None,reference=None,force_parent=False):
        nonlocal render_count
        render_count+=1;pg=reference or page
        if time.perf_counter()-start>POLICY['time_budget_seconds']:raise TimeoutError('Study render budget exhausted')
        if box is None or mode=='parent' or force_parent:
            bm=pg.render(scale=scale)
            try:rgb=np.array(bm.to_pil().convert('RGB'))
            finally:bm.close()
            if rgb.shape[:2]!=(height,width):raise ValueError('Source canvas mismatch')
            return rgb if box is None else rgb[box[1]:box[3],box[0]:box[2]].copy()
        crop=tuple(max(0,v-1e-5)/scale for v in (box[0],height-box[3],width-box[2],box[1]))
        bm=pg.render(scale=scale,crop=crop)
        try:return np.array(bm.to_pil().convert('RGB'))
        finally:bm.close()
    def switch(selected=None,without=None):
        for i,(obj,state) in enumerate(zip(objects,states)):
            if not raw.FPDFPageObj_SetIsActive(obj,state if (selected is None or i in selected) and i!=without else 0):raise RuntimeError('Source object state failed')
    baseline=render();x0,y0,x1,y1=roi;cv2.imwrite(str(out/'source-roi-current.png'),cv2.cvtColor(baseline[y0:y1,x0:x1],cv2.COLOR_RGB2BGR))
    existing=existing_structure(doc,coordinate_map(doc,info));decisions=[];accepted=[];candidate_count=0
    try:
        for path in paths:
            if path['fill'] or not path['stroke']:continue
            try:qualified=qualifies(path,info['native_fills'],roi)
            except ValueError:continue
            if qualified is None:continue
            candidate_count+=1
            if candidate_count>POLICY['candidate_paths_max']:raise RuntimeError('Candidate budget exhausted, untraversed tail not evaluated')
            points,closed,fill=qualified;why=None
            rgba=path['rgba'];join=raw.FPDFPageObj_GetLineJoin(objects[path['index']])
            reason=''
            try:
                if not (rgba[0]==rgba[1]==rgba[2] and fill['rgb'][0]==fill['rgb'][1]==fill['rgb'][2] and rgba[0]<fill['rgb'][0] and rgba[3]==255):raise ValueError('UNSUPPORTED_COLOR_OR_CONTRAST')
                if path['line_cap'] or join or path['dash_count'] or path['transparent'] or path['clip_count']>0:raise ValueError('UNSUPPORTED_STYLE_OR_CLIP')
                a,b,c,d,_,_=path['matrix']
                if not np.allclose([a*a+b*b,c*c+d*d,a*c+b*d],[1,1,0],atol=1e-6):raise ValueError('UNSUPPORTED_SCALED_PEN')
                pen=path['width_pt']*scale
                if not 0<pen<=POLICY['native_width_px_max']:raise ValueError('WIDTH_UNSUPPORTED')
                ambiguity=_ambiguous_edge(existing,points,closed,pen)
                if ambiguity:raise ValueError('EXISTING_ALIGNED_GEOMETRY:'+str(ambiguity))
                p=np.array(points);pad=int(np.ceil(10*pen))+2;lo=np.floor(p.min(0)).astype(int)-pad;hi=np.ceil(p.max(0)).astype(int)+pad
                box=tuple(map(int,(*lo,*hi)))
                if min(lo)<0 or hi[0]>width or hi[1]>height:raise ValueError('PAGE_EDGE_UNSUPPORTED')
                switch();full=render(box);switch(selected={path['index']});only=render(box);switch(without=path['index']);without=render(box)
                original=objects[path['index']];local=[]
                for j in range(raw.FPDFPath_CountSegments(original)):
                    segment=raw.FPDFPath_GetPathSegment(original,j);xx,yy=ct.c_float(),ct.c_float();raw.FPDFPathSegment_GetPoint(segment,ct.byref(xx),ct.byref(yy));local.append((xx.value,yy.value))
                ref=pdfium.PdfDocument.new();rp=ref.new_page(*page.get_size());shape=raw.FPDFPageObj_CreateNewPath(*local[0])
                for q in local[1:]:raw.FPDFPath_LineTo(shape,*q)
                if closed:raw.FPDFPath_Close(shape)
                raw.FPDFPageObj_Transform(shape,*path['matrix']);raw.FPDFPageObj_SetStrokeColor(shape,*rgba);raw.FPDFPageObj_SetStrokeWidth(shape,path['width_pt']);raw.FPDFPageObj_SetLineCap(shape,0);raw.FPDFPageObj_SetLineJoin(shape,0);raw.FPDFPath_SetDrawMode(shape,0,1);raw.FPDFPage_InsertObject(rp,shape)
                expected=render(box,reference=rp);rp.close();ref.close()
                if only.shape!=expected.shape or np.max(abs(only.astype(int)-expected.astype(int)))>2:raise ValueError('REFERENCE_CLIP_OR_JOIN_CHANGED')
                ink=np.any(expected<255,axis=2)
                if not ink.any() or any(np.any(ink[s]) for s in [0,-1]) or np.any(ink[:,0]) or np.any(ink[:,-1]):raise ValueError('INCOMPLETE_REFERENCE_BOUNDS')
                alpha=(255-expected[:,:,0].astype(float))/(255-rgba[0]);prediction=rgba[0]*alpha[:,:,None]+without*(1-alpha[:,:,None])
                if full.shape!=prediction.shape or np.max(abs(full[ink].astype(float)-prediction[ink]))>2:raise ValueError('OCCLUDED_OR_CONTEXT_COMPOSITING_CHANGED')
                if not np.array_equal(full[ink],baseline[box[1]:box[3],box[0]:box[2]][ink]):raise ValueError('PARENT_GRID_CHANGED')
                record={'source_object':path['index'],'points':points,'closed':closed,'width_px':pen,'rgb':rgba[:3],
                    'source_file':str(Path(pdf_file).resolve()),'page':page_number,'dpi':dpi,'source_path':path,'fill_identity':fill['source'],
                    'visibility':{'grid':mode,'reference_max_error':int(np.max(abs(only.astype(int)-expected.astype(int)))),
                        'composite_max_error':float(np.max(abs(full[ink].astype(float)-prediction[ink]))),'parent_pixels_equal':True,'complete_visible_pixels':int(ink.sum()),'box':box}}
                accepted.append(record)
                cv2.imwrite(str(out/f"path-{path['index']}-only.png"),cv2.cvtColor(only,cv2.COLOR_RGB2BGR))
                reason='ACCEPT_COMPLETE_VISIBLE_PATH'
            except ValueError as error:reason=str(error)
            decisions.append({'source_object':path['index'],'decision':'ACCEPT' if reason=='ACCEPT_COMPLETE_VISIBLE_PATH' else 'REJECT','reason':reason})
    finally:
        switch();restored=render()
        if not np.array_equal(restored,baseline):raise RuntimeError('Source state restoration failed')
        page.close();pdf.close()
    save(out/'candidates.json',{'policy':POLICY,'grid':mode,'all_candidates':decisions,'accepted':accepted,'render_count':render_count,'seconds':time.perf_counter()-start,'source_state_restored':True})
    return accepted

def write_repair(doc,frame,accepted,out):
    mat=np.array(frame['source_to_world']);unit=frame['unit_per_source_pixel'];before=records(doc)
    if 'GOAL03_NATIVE_REPAIR' not in doc.layers:doc.layers.new('GOAL03_NATIVE_REPAIR',dxfattribs={'color':7})
    if 'GOAL03_SOURCE' not in doc.appids:doc.appids.new('GOAL03_SOURCE')
    created=[]
    for row in accepted:
        points=np.c_[row['points'],np.ones(len(row['points']))]@mat
        entity=doc.modelspace().add_lwpolyline(points,close=row['closed'],dxfattribs={'layer':'GOAL03_NATIVE_REPAIR','color':7,'const_width':row['width_px']*unit,'lineweight':0})
        payload=json.dumps({'source_object':row['source_object'],'page':row['page'],'points_source':row['points'],'width_px':row['width_px'],'source_file':row['source_file'],'grid':row['visibility']['grid']},separators=(',',':'))
        entity.set_xdata('GOAL03_SOURCE',[(1000,payload[i:i+240]) for i in range(0,len(payload),240)])
        created.append({'handle':entity.dxf.handle,'source_object':row['source_object']})
    after=records(doc)
    if any(after.get(h)!=record for h,record in before.items()):raise RuntimeError('Original entity changed')
    doc.saveas(out/'experimental.dxf');save(out/'created.json',created)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case-dir',required=True);parser.add_argument('--pdf',required=True);parser.add_argument('--page',type=int,required=True);parser.add_argument('--dpi',type=float,required=True);parser.add_argument('--roi',type=float,nargs=4,required=True);args=parser.parse_args()
    case=Path(args.case_dir);roi=list(map(int,args.roi));info=load(case/'historical-input.json');doc=ezdxf.readfile(case/'normal-baseline.dxf');frame=coordinate_map(doc,info);save(case/'coordinate-map.json',frame)
    for mode in ['crop','parent']:
        out=case/mode;out.mkdir(exist_ok=False);accepted=study(args.pdf,args.page,args.dpi,info,doc,roi,mode,out);write_repair(ezdxf.readfile(case/'normal-baseline.dxf'),frame,accepted,out)
        print(json.dumps({'mode':mode,'accepted_paths':len(accepted),'accepted_edges':sum(len(list(_segments(r['points'],r['closed']))) for r in accepted),'objects':[r['source_object'] for r in accepted]}),flush=True)
if __name__=='__main__':main()
