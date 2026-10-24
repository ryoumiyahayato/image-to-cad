"""Semantic source-vs-GUI no-edit audit. Read only; no acceptance threshold changes."""
import sys,collections
sys.dont_write_bytecode=True
from gui_readback import same,plain,widths,OUT,load,save
import ezdxf

def get(e,n,default=None):
    value=e.dxf.get(n,default) if e.dxf.is_supported(n) else default
    return None if value is None else plain(value)

def hatch_boundary(path):
    if hasattr(path,'vertices'):
        points=list(path.vertices)
        if any(p[2] for p in points):raise ValueError('Curved HATCH requires explicit arc comparison')
        return [[list(a[:2]),list(b[:2])] for a,b in zip(points,points[1:]+([points[0]] if path.is_closed else []))]
    if any(type(e).__name__!='LineEdge' for e in path.edges):raise ValueError('Non-line HATCH edge requires explicit comparison')
    return [[plain(e.start),plain(e.end)] for e in path.edges]

def geometry(e):
    t=e.dxftype()
    if t=='LWPOLYLINE':return {'xyb':[list(p) for p in e.get_points('xyb')],'closed':bool(e.closed),'elevation':get(e,'elevation',0.),'extrusion':get(e,'extrusion',(0,0,1))}
    if t=='LINE':return {n:get(e,n) for n in ['start','end']}
    if t=='CIRCLE':return {n:get(e,n) for n in ['center','radius']}
    if t=='TEXT':
        r={n:get(e,n,d) for n,d in [('insert',(0,0,0)),('text',''),('height',0),('rotation',0),('width',1),('oblique',0),('halign',0),('valign',0),('text_generation_flag',0),('extrusion',(0,0,1))]}
        if r['halign'] or r['valign']:r['align_point']=get(e,'align_point',(0,0,0))
        return r
    if t=='HATCH':
        return {'paths':[hatch_boundary(p) for p in e.paths],
                **{n:get(e,n,d) for n,d in [('elevation',(0,0,0)),('extrusion',(0,0,1)),('solid_fill',1),('pattern_name','SOLID'),('hatch_style',0)]}}
    if t=='IMAGE':return {**{n:get(e,n) for n in ['insert','u_pixel','v_pixel','image_size']},'boundary':plain(e.boundary_path),'clipping':get(e,'clipping',0)}
    raise ValueError('Unreviewed entity type '+t)

def equal(a,b):
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return same(a,b)

def visible(e):
    layer=e.doc.layers.get(e.dxf.layer)
    true=get(e,'true_color');color=get(e,'color',256)
    rgb=true if true is not None else ('ACI',abs(layer.dxf.color) if color==256 else color)
    lw=get(e,'lineweight',-1);lt=get(e,'linetype','BYLAYER').upper()
    r={'color':plain(rgb),'lineweight':layer.dxf.lineweight if lw==-1 else lw,'linetype':layer.dxf.linetype.upper() if lt=='BYLAYER' else lt,
       'transparency':get(e,'transparency',0),'invisible':get(e,'invisible',0),'thickness':get(e,'thickness',0.),'layer_hidden':layer.is_off() or layer.is_frozen()}
    if e.dxftype()=='LWPOLYLINE':r['effective_widths']=widths(e)
    if e.dxftype()=='TEXT':
        r['text_style']=get(e,'style','Standard')
        style=e.doc.styles.get(r['text_style']);r['font']=style.dxf.font;r['style_width']=style.dxf.width
    if e.dxftype()=='IMAGE':
        r.update({n:get(e,n,d) for n,d in [('flags',3),('brightness',50),('contrast',50),('fade',0)]})
        r['image_filename']=e.doc.entitydb[e.dxf.image_def_handle].dxf.filename
    return r

def main():
    summary=[]
    for name in ['B-G19','A-G38']:
        folder=OUT/'gui'/name;a=ezdxf.readfile(folder/'input-final-v2.dxf');b=ezdxf.readfile(folder/'gui-no-edit-saved.dxf')
        # Object order is not a match criterion. Geometry, type and layer must agree.
        pools=collections.defaultdict(list)
        for e in b.modelspace():pools[(e.dxftype(),e.dxf.layer)].append((e,geometry(e)))
        unmatched=[];changes=[];pairs=[]
        for e in a.modelspace():
            g=geometry(e);bucket=pools[(e.dxftype(),e.dxf.layer)]
            index=next((i for i,(f,h) in enumerate(bucket) if equal(g,h)),None)
            if index is None:unmatched.append({'handle':e.dxf.handle,'type':e.dxftype(),'layer':e.dxf.layer,'geometry':g});continue
            f,h=bucket.pop(index);av,bv=visible(e),visible(f)
            delta={k:{'before':av[k],'after':bv[k]} for k in av if not equal(av[k],bv[k])}
            if delta:changes.append({'input_handle':e.dxf.handle,'gui_handle':f.dxf.handle,'type':e.dxftype(),'layer':e.dxf.layer,'changes':delta})
            pairs.append((e,f))
        extra=[{'handle':f.dxf.handle,'type':f.dxftype(),'layer':f.dxf.layer,'geometry':g} for bucket in pools.values() for f,g in bucket]
        counts=collections.Counter(k for row in changes for k in row['changes'])
        la={l.dxf.name:{'off':l.is_off(),'frozen':l.is_frozen(),'locked':l.is_locked(),'color':l.dxf.color,'flags':l.dxf.flags} for l in a.layers}
        lb={l.dxf.name:{'off':l.is_off(),'frozen':l.is_frozen(),'locked':l.is_locked(),'color':l.dxf.color,'flags':l.dxf.flags} for l in b.layers}
        result={'case':name,'independent_process':True,'source':'input-final-v2.dxf','comparison':'gui-no-edit-saved.dxf',
                'matching':'type + layer + complete explicit geometry; order and identity not used; 1e-9 world roundoff only',
                'geometry_matched':len(pairs),'unmatched_input':unmatched,'unmatched_gui':extra,
                'attribute_change_counts':dict(counts),'attribute_changes':changes,'raw_layer_changes_by_name':{k:{'before':la.get(k),'after':lb.get(k)} for k in la.keys()|lb.keys() if la.get(k)!=lb.get(k)},
                'scope':'entity geometry and explicit resolved visible attributes; font rendering and IMAGE flag effect require visual application check',
                'input_xdata_entities':sum(e.xdata is not None for e in a.modelspace()),'gui_xdata_entities':sum(e.xdata is not None for e in b.modelspace())}
        save(folder/'source-vs-gui-serialization.json',result)
        summary.append({k:result[k] for k in ['case','geometry_matched','attribute_change_counts','input_xdata_entities','gui_xdata_entities']})
        summary[-1].update(unmatched_input=len(unmatched),unmatched_gui=len(extra));print(summary[-1],flush=True)
    save(OUT/'serialization-summary.json',summary)
if __name__=='__main__':main()
