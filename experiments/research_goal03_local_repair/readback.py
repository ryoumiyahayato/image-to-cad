"""Separate-process scoring of saved DXFs. QA is read only here, never by repair."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse,json,math
from pathlib import Path
import numpy as np,cv2,ezdxf
from PySide6.QtGui import QGuiApplication
from repair import load,save,records,_segments
from preview_goal03 import render_emitted_dxf_preview

def edge_list(doc,frame,only_new=False):
    u=frame['unit_per_source_pixel'];offset=np.array(frame['source_to_world'])[2]
    def inverse(p):return np.array([(p[0]-offset[0])/u,(offset[1]-p[1])/u])
    result=[]
    for e in doc.modelspace():
        new=e.has_xdata('GOAL03_SOURCE')
        if only_new and not new:continue
        if e.dxftype()=='LINE':points=[e.dxf.start,e.dxf.end];closed=False
        elif e.dxftype()=='LWPOLYLINE':points=e.get_points('xy');closed=e.closed
        else:continue
        sid=None
        if new:sid=json.loads(''.join(t.value for t in e.get_xdata('GOAL03_SOURCE')))['source_object']
        for a,b in _segments(tuple(map(inverse,points)),closed):
            result.append({'handle':e.dxf.handle,'a':a,'b':b,'source_object':sid,'width_px':(float(e.dxf.const_width)/u if e.dxftype()=='LWPOLYLINE' else 0),'new':new})
    return result

def score_target(target,edges,qa,require_source=True):
    a,b=np.array(target['points']);v=b-a;length=np.linalg.norm(v);n=max(2,math.ceil(length/qa['sample_step_px'])+1)
    q=a+np.linspace(0,1,n)[:,None]*v;dist=np.full(n,np.inf);own=[]
    for e in edges:
        if require_source and e['source_object']!=target['native_path']:continue
        c,d=e['a'],e['b'];w=d-c
        if np.linalg.norm(w)==0 or abs(v[0]*w[1]-v[1]*w[0])/(length*np.linalg.norm(w))>math.sin(math.radians(1)):continue
        t=np.clip((q-c)@w/(w@w),0,1);dist=np.minimum(dist,np.linalg.norm(q-c-t[:,None]*w,axis=1));own.append(e)
    hit=dist<=1;longest=run=0
    for h in hit:run=0 if h else run+1;longest=max(longest,run)
    gap=max(0,longest-1)*length/(n-1)
    widths=[abs(e['width_px']-target['width_px']) for e in own]
    endpoint=max(dist[0],dist[-1])
    if require_source:
        endpoint=min((min(max(np.linalg.norm(a-e['a']),np.linalg.norm(b-e['b'])),max(np.linalg.norm(a-e['b']),np.linalg.norm(b-e['a']))) for e in own),default=float('inf'))
    width=min(widths,default=float('inf')) if require_source else 0
    return {'id':target['id'],'complete':bool(hit.mean()>=qa['own_geometry_coverage_min'] and gap<=qa['max_gap_span_px'] and endpoint<=qa['endpoint_tolerance_px'] and width<=qa['width_tolerance_px']),
        'coverage':float(hit.mean()),'max_gap_span_px':gap,'sample_step_actual_px':length/(n-1),'endpoint_error_px':None if not np.isfinite(endpoint) else float(endpoint),
        'width_error_px':None if not np.isfinite(width) else width,'actual_handles':sorted(set(e['handle'] for e in own))}

def overlap(a,b):
    v=a['b']-a['a'];length=np.linalg.norm(v)
    if length<1e-8:return 0
    u=v/length;n=np.array([-u[1],u[0]]);c,d=b['a']-a['a'],b['b']-a['a']
    if max(abs(c@n),abs(d@n))>.1:return 0
    return max(0,min(length,max(c@u,d@u))-max(0,min(c@u,d@u)))

def main():
    p=argparse.ArgumentParser();p.add_argument('--case-dir',required=True);args=p.parse_args();case=Path(args.case_dir)
    app=QGuiApplication.instance() or QGuiApplication([]);qa=load(case/'frozen-assessment.json');frame=load(case/'coordinate-map.json')
    baseline=ezdxf.readfile(case/'normal-baseline.dxf');old=records(baseline);x0,y0,x1,y1=qa['roi'];roi=(x0,y0,x1-x0,y1-y0);imgs={};results={}
    for mode in ['normal','crop','parent']:
        file=case/'normal-baseline.dxf' if mode=='normal' else case/mode/'experimental.dxf';doc=ezdxf.readfile(file);all_edges=edge_list(doc,frame);new=edge_list(doc,frame,True)
        current=records(doc);changed=[h for h,t in old.items() if current.get(h)!=t]
        img=render_emitted_dxf_preview(doc,file.parent,qa['source_canvas'],roi=roi,units_per_source_pixel=frame['unit_per_source_pixel'])
        if img.ndim==2:img=cv2.cvtColor(img,cv2.COLOR_GRAY2BGR)
        imgs[mode]=img
        cv2.imwrite(str(case/f'{mode}-saved-dxf-roi.png'),img)
        targets=[score_target(t,new if mode!='normal' else all_edges,qa,mode!='normal') for t in qa['targets']]
        duplicates=[]
        for i,a in enumerate(new):
            for b in all_edges:
                if a['handle']==b['handle'] or (b['new'] and a['handle']>=b['handle']):continue
                value=overlap(a,b)
                if value>2:duplicates.append({'a':a['handle'],'b':b['handle'],'overlap_px':value})
        results[mode]={'dxf':str(file.resolve()),'entities':len(doc.modelspace()),'new_paths':len(set(e['handle'] for e in new)),
            'complete_edges':sum(t['complete'] for t in targets),'targets':targets,'changed_original_entities':changed,'aligned_duplicate_intervals':duplicates,
            'new_paths_widths_px':sorted(set(round(e['width_px'],9) for e in new))}
    for mode in ['crop','parent']:
        # These are actual saved DXF renders. Only score predeclared areas; unknown pixels are not background.
        added=np.any(imgs[mode]!=imgs['normal'],axis=2)
        checks=[]
        for r in qa['negative_regions']:
            a,b,c,d=r['box'];checks.append({'id':r['id'],'changed_pixels':int(added[b-y0:d-y0,a-x0:c-x0].sum())})
        protection=[]
        for line in qa['protection_lines']:
            a,b=np.array(line['points']);mask=np.zeros(added.shape,np.uint8);cv2.line(mask,tuple(np.rint(a-[x0,y0]).astype(int)),tuple(np.rint(b-[x0,y0]).astype(int)),1,3)
            before=cv2.cvtColor(imgs['normal'],cv2.COLOR_BGR2GRAY)<100;after=cv2.cvtColor(imgs[mode],cv2.COLOR_BGR2GRAY)<100
            protection.append({'id':line['id'],'lost_dark_pixels':int((before&~after&(mask>0)).sum()),'changed_pixels':int((added&(mask>0)).sum())})
        results[mode]['negative_regions']=checks;results[mode]['protection_lines']=protection
    panels=[]
    source=cv2.imread(str(case/'source-roi.png'))
    for label,img in [('SOURCE LOCAL_EVAL_ONLY',source),('NORMAL SAVED DXF',imgs['normal']),('SIMPLE CROP SAVED DXF',imgs['crop']),('EXPERIMENTAL PARENT GRID DXF',imgs['parent'])]:
        panel=cv2.copyMakeBorder(img,30,0,0,0,cv2.BORDER_CONSTANT,value=(255,255,255));cv2.putText(panel,label,(10,21),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),1);panels.append(panel)
    cv2.imwrite(str(case/'comparison.png'),np.vstack(panels))
    save(case/'independent-readback.json',{'annotation':qa['annotation'],'independent_process':True,'score_uses_saved_dxf_geometry':True,'results':results})
    print(json.dumps({k:{x:v[x] for x in ['entities','new_paths','complete_edges','changed_original_entities','aligned_duplicate_intervals']} for k,v in results.items()}))
if __name__=='__main__':main()

