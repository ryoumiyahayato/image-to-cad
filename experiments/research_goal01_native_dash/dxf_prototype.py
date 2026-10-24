"""Experimental dash edit unit, not a production exporter."""
import json
from pathlib import Path
import numpy as np
import ezdxf

APPID='GOAL01_NATIVE_DASH'
def write_json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def source_tag(entity,index,dash):entity.set_xdata(APPID,[(1000,'EXPERIMENTAL_ONLY'),(1071,index),(1071,dash)])
def export(records,path,grouped):
    doc=ezdxf.new('R2010');doc.header['$INSUNITS']=0;doc.header['$MEASUREMENT']=0;doc.appids.new(APPID)
    doc.layers.new('EXPERIMENTAL_SOURCE_DASH');doc.layers.new('EXPERIMENTAL_MARKER');msp=doc.modelspace()
    msp.add_text('EXPERIMENTAL_ONLY / PAPER_PT / NOT PRODUCTION',dxfattribs={'layer':'EXPERIMENTAL_MARKER','height':3,'insert':(0,-15)})
    for row in records:
        index=row['index'];origin=np.array(row['page_points'][0]);rgb=row['rgba'][:3];color=(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
        target=doc.blocks.new('SOURCE_PATH_'+str(index)) if grouped else msp
        for k,(a,b) in enumerate(row['on_segments']):
            pts=np.array([a,b])-origin if grouped else np.array([a,b])
            e=target.add_lwpolyline(pts.tolist(),dxfattribs={'layer':'EXPERIMENTAL_SOURCE_DASH','const_width':row['page_width'],'true_color':color})
            source_tag(e,index,k)
        if grouped:
            insert=msp.add_blockref(target.name,origin.tolist(),dxfattribs={'layer':'EXPERIMENTAL_SOURCE_DASH'});source_tag(insert,index,-1)
    doc.saveas(path)
def identity(entity):
    tags=list(entity.get_xdata(APPID));return int(tags[1].value),int(tags[2].value)
def flatten(path):
    doc=ezdxf.readfile(path);rows=[]
    for e in doc.modelspace():
        if e.dxf.layer!='EXPERIMENTAL_SOURCE_DASH':continue
        for child in list(e.virtual_entities()) if e.dxftype()=='INSERT' else [e]:
            idx,dash=identity(child);pts=[list(p[:2]) for p in child.get_points('xy')]
            rows.append(dict(index=idx,dash=dash,points=pts,width=float(child.dxf.const_width),color=int(child.dxf.true_color)))
    return doc,sorted(rows,key=lambda r:(r['index'],r['dash']))
def canonical(records,move_index=None,delta=(0,0)):
    rows=[]
    for r in records:
        rgb=r['rgba'][:3];color=(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
        for k,p in enumerate(r['on_segments']):
            points=np.array(p)+np.array(delta if r['index']==move_index else [0,0]);rows.append(dict(index=r['index'],dash=k,points=points.tolist(),width=r['page_width'],color=color))
    return sorted(rows,key=lambda r:(r['index'],r['dash']))
def compare(actual,expected):
    if len(actual)!=len(expected):return dict(equal=False,reason='count mismatch',actual=len(actual),expected=len(expected))
    maxerror=0.;changed=[]
    for a,b in zip(actual,expected):
        error=float(np.abs(np.array(a['points'])-np.array(b['points'])).max());maxerror=max(maxerror,error)
        if (a['index'],a['dash'],a['color'])!=(b['index'],b['dash'],b['color']) or abs(a['width']-b['width'])>1e-8 or error>1e-8:changed.append([a['index'],a['dash']])
    return dict(equal=not changed,max_endpoint_error_pt=maxerror,mismatches=changed,dash_entities=len(actual))
def edit_file(input_path,out_path,index,delta):
    doc=ezdxf.readfile(input_path);selected=[]
    for e in doc.modelspace():
        if e.dxf.layer=='EXPERIMENTAL_SOURCE_DASH' and identity(e)[0]==index:selected.append(e)
    for e in selected:e.translate(*delta,0)
    doc.saveas(out_path);return dict(selected_units=len(selected),bulk_move_commands=1,internal_entity_transforms=len(selected),human_time_measured=False)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['verify','edit','verify_edited']);p.add_argument('--dir',required=True);a=p.parse_args();root=Path(a.dir);records=json.loads((root/'accepted.json').read_text(encoding='utf8'));first=records[0]['index'];results={}
    for kind in ['flat','grouped']:
        path=root/('EXPERIMENTAL-'+kind+'.dxf')
        if a.mode=='edit':results[kind]=edit_file(path,root/('EXPERIMENTAL-'+kind+'-edited.dxf'),first,(5,3))
        else:
            edited=a.mode=='verify_edited';doc,rows=flatten(root/('EXPERIMENTAL-'+kind+'-edited.dxf') if edited else path)
            results[kind]=compare(rows,canonical(records,first if edited else None,(5,3) if edited else (0,0)))
            results[kind]['top_level_source_entities']=sum(e.dxf.layer=='EXPERIMENTAL_SOURCE_DASH' for e in doc.modelspace())
    write_json(root/(a.mode+'-fresh-process.json'),results);print(json.dumps(results))
