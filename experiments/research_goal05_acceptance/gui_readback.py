"""Independent read-only GUI file comparison. No writing geometry or selecting CAD objects."""
import sys,json,math,collections
sys.dont_write_bytecode=True
from pathlib import Path
import numpy as np,ezdxf
from ezdxf.lldxf.tagwriter import TagCollector
from prepare import ROOT,OUT,load,save,layers
TOL=1e-9 # world-unit serialization roundoff only; no change to frozen source scoring
def same(a,b):
    if isinstance(a,(float,int,np.number)) and isinstance(b,(float,int,np.number)):return math.isclose(a,b,rel_tol=0,abs_tol=TOL)
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    return a==b
def plain(v):
    if isinstance(v,(str,int,float)):return v
    try:return [plain(x) for x in v]
    except TypeError:return str(v)
def record(e):
    # Handles/owner and XDATA are audited separately, not treated as visible geometry.
    return [(t.code,plain(t.value)) for t in TagCollector.dxftags(e) if t.code not in [5,330] and t.code<1000]
def anchor(e):
    if e.dxftype()=='LWPOLYLINE':return np.array(e.get_points('xy')[0],float)
    for name in ['start','insert','center']:
        if e.dxf.is_supported(name):return np.array(tuple(e.dxf.get(name))[:2],float)
    return None
def difference(a,b):
    remaining=list(b.modelspace());unmatched=[];mapping=[]
    for e in a.modelspace():
        x=anchor(e);r=record(e);found=None
        for i,f in enumerate(remaining):
            if f.dxftype()!=e.dxftype() or f.dxf.layer!=e.dxf.layer:continue
            y=anchor(f)
            if x is not None and y is not None and np.max(abs(x-y))>TOL:continue
            if same(r,record(f)):found=i;break
        if found is None:unmatched.append(e)
        else:
            f=remaining.pop(found);mapping.append({'old_handle':e.dxf.handle,'new_handle':f.dxf.handle})
    return unmatched,remaining,mapping
def row(e):
    r={'type':e.dxftype(),'handle':e.dxf.handle,'layer':e.dxf.layer,'tags':record(e)}
    if e.dxftype()=='LWPOLYLINE':r.update(points=[list(map(float,p)) for p in e.get_points('xyseb')],closed=bool(e.closed),const_width=float(e.dxf.const_width))
    return r
def widths(e):
    if e.dxftype()!='LWPOLYLINE':return None
    return [[float(e.dxf.const_width or p[2]),float(e.dxf.const_width or p[3])] for p in e.get_points('xyseb')]
def locate(doc,points,layer='GOAL03_NATIVE_REPAIR'):
    p=np.array(points,float)
    return [e for e in doc.modelspace().query('LWPOLYLINE') if e.dxf.layer==layer and len(e)==len(p) and np.allclose(np.array(e.get_points('xy')),p,rtol=0,atol=TOL)]
def main():
    results=[]
    for name in ['B-G19','A-G38']:
        folder=OUT/'gui'/name;plan=load(folder/'plan.json');docs={key:ezdxf.readfile(folder/file) for key,file in [('input','input-final-v2.dxf'),('no_edit','gui-no-edit-saved.dxf'),('edited','gui-edited.dxf'),('undone','gui-undone.dxf')]}
        before,after,mapping=difference(docs['no_edit'],docs['edited']);ub,ua,um=difference(docs['no_edit'],docs['undone'])
        target=np.array(plan['points_world']);shifted=target+np.array(plan['intended_translation_world'])
        oldtarget=locate(docs['no_edit'],target);newtarget=locate(docs['edited'],shifted);restored=locate(docs['undone'],target)
        assert len(before)==len(after)==len(oldtarget)==len(newtarget)==len(restored)==1
        assert before[0].dxf.handle==oldtarget[0].dxf.handle and after[0].dxf.handle==newtarget[0].dxf.handle
        assert not locate(docs['edited'],target) and not ub and not ua
        assert newtarget[0].closed==oldtarget[0].closed and widths(oldtarget[0])==widths(newtarget[0])
        assert layers(docs['no_edit'])==layers(docs['undone'])
        original_target=docs['input'].entitydb[plan['target_handle']]
        repair_width_changes=[]
        for e in docs['input'].modelspace().query('LWPOLYLINE'):
            if e.dxf.layer!='GOAL03_NATIVE_REPAIR':continue
            found=locate(docs['no_edit'],e.get_points('xy'));assert len(found)==1
            if not same(widths(e),widths(found[0])):repair_width_changes.append({'input_handle':e.dxf.handle,'gui_handle':found[0].dxf.handle,'before_widths':widths(e),'after_widths':widths(found[0])})
        text_styles={key:[{'name':s.dxf.name,'font':s.dxf.font,'bigfont':s.dxf.bigfont,'width':s.dxf.width} for s in d.styles] for key,d in docs.items() if key in ['input','no_edit']}
        def identities(d):return {'entities_with_xdata':sum(e.xdata is not None for e in d.modelspace()),'source_group_entities':sum(e.has_xdata('GOAL04_SOURCES') for e in d.modelspace()),'handles':[e.dxf.handle for e in d.modelspace()]}
        state={key:identities(d) for key,d in docs.items()}
        result={'case':name,'independent_interpreter':True,'GUI_operator':'AI','human_reviewed':False,
            'files':{key:str((folder/file).resolve()) for key,file in [('input','input-final-v2.dxf'),('no_edit','gui-no-edit-saved.dxf'),('edited','gui-edited.dxf'),('undone','gui-undone.dxf')]},
            'entity_counts':{key:len(d.modelspace()) for key,d in docs.items()},
            'GUI_SELECT':'PASS_BY_SAVED_ENTITY_DIFF','GUI_EDIT':'PASS_TRANSLATION','GUI_SAVE':'COMPLETED','GUI_UNDO':'PASS_GEOMETRY_RESTORED',
            'translation_world':plan['intended_translation_world'],'target_input_handle':plan['target_handle'],'target_gui_no_edit_handle':oldtarget[0].dxf.handle,'target_gui_edited_handle':newtarget[0].dxf.handle,
            'target_closed_input':bool(original_target.closed),'target_closed_after':bool(newtarget[0].closed),'changed_entities_old':[row(e) for e in before],'changed_entities_new':[row(e) for e in after],
            'old_position_residual_complete_target_entities':0,'non_target_entities_unchanged_after_edit':len(mapping),'undo_unmatched_old':len(ub),'undo_unmatched_new':len(ua),
            'non_target_attributes_check':'all parsed DXF entity tags except handles/owners and XDATA; numeric roundoff 1e-9 world units',
            'temporary_layers_restored_against_gui_no_edit':True,'layers_input':layers(docs['input']),'layers_gui_undone':layers(docs['undone']),
            'GUI_SERIALIZATION':'FAIL_REPAIR_PEN_WIDTH_LOST','repair_pen_width_change_count_before_edit':len(repair_width_changes),'repair_pen_width_changes':repair_width_changes,
            'target_width_input':widths(original_target),'target_width_no_edit':widths(oldtarget[0]),'target_width_edited':widths(newtarget[0]),'target_width_undone':widths(restored[0]),
            'identity':state,'styles':text_styles,'identity_fields_not_silently_ignored':True,
            'layer_interference_operations':{'lock_all':1,'unlock_repair':1,'restore_unlock_all':1,'hide_operations':0,'delete_geometry_operations':0},
            'scope':'single short polyline or one closed polyline; not complete dimensions, whole structures, or full drawing editability'}
        save(folder/'independent-gui-readback.json',result);results.append({k:result[k] for k in ['case','GUI_SELECT','GUI_EDIT','GUI_SAVE','GUI_UNDO','GUI_SERIALIZATION','entity_counts','repair_pen_width_change_count_before_edit','non_target_entities_unchanged_after_edit','old_position_residual_complete_target_entities','temporary_layers_restored_against_gui_no_edit']})
        print(json.dumps(results[-1]),flush=True)
    save(OUT/'gui-summary.json',results)
if __name__=='__main__':main()
