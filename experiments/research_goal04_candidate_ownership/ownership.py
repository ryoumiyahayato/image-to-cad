"""Goal04 full-path ownership. No QA, target IDs, source/ROI allowlists or new geometry."""
import sys,json,argparse,itertools,copy
sys.dont_write_bytecode=True
from pathlib import Path
import numpy as np,cv2,ezdxf
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/research_goal03_local_repair'))
from repair import load,save,records,write_repair,_segments

POLICY={'version':'complete-path-ownership-v2','geometry_delta':'min(1/255 source pixel, minimum pen width/128)',
 'witness_max_channel_difference':1,'width_relative_roundoff':float(32*np.finfo(np.float32).eps),
 'exact_existing_geometry_roundoff_px':1e-8,'partial_overlap':'DEFER_COMPLETE_ORIGINAL_CANDIDATES_WITH_UNIQUE_INTERVALS',
 'representative':'original canonical geometry; no averaging/trimming/extending','cluster':'pairwise complete; no single-link chaining',
 'upstream_visibility':'unchanged Goal03 parent','normal_entities':'immutable','QA_input':False,'model':False}

def clean(row):return {k:v for k,v in row.items() if not k.startswith('_')}
def points(row):
    p=np.asarray(row['points'],float)
    if row['closed'] and len(p)>2 and np.linalg.norm(p[0]-p[-1])<1e-12:p=p[:-1]
    return p
def variants(row):
    p=points(row)
    for q in [p,p[::-1]]:
        for i in range(len(q) if row['closed'] else 1):yield np.roll(q,i,axis=0)
def key(row):
    geometry=min(tuple(map(tuple,p)) for p in variants(row))
    return (tuple(row['rgb']),float(row['width_px']),bool(row['closed']),geometry,str(row.get('source_file','')),row.get('page',0),row.get('source_object',-1))
def delta(a,b):return min(1/255,min(a['width_px'],b['width_px'])/128)
def shape_error(a,b):
    if a['closed']!=b['closed'] or len(points(a))!=len(points(b)):return float('inf')
    p=points(a)
    return min(float(np.linalg.norm(p-q,axis=1).max()) for q in variants(b))
def style_equal(a,b):
    if a.get('_width_unknown') or b.get('_width_unknown'):return False
    for row in [a,b]:
        s=row.get('source_path',{})
        if s.get('line_cap',0)!=0 or s.get('line_join',0)!=0 or s.get('dash_count',0) or s.get('transparent',False):return False
    width=max(a['width_px'],b['width_px']);tol=max(1e-10,POLICY['width_relative_roundoff']*width)
    return tuple(a['rgb'])==tuple(b['rgb']) and abs(a['width_px']-b['width_px'])<=tol
def context_equal(a,b):
    return all(a.get(k) is None or b.get(k) is None or a[k]==b[k] for k in ['source_file','page','dpi'])
def witness_difference(a,b):
    if a.get('_existing') and not a.get('_witness_dir'):
        return 0 if shape_error(a,b)<=POLICY['exact_existing_geometry_roundoff_px'] else None
    if b.get('_existing') and not b.get('_witness_dir'):return witness_difference(b,a)
    rows=[]
    for r in [a,b]:
        box=np.array(r['visibility']['box'],int);file=Path(r['_witness_dir'])/f"path-{r['source_object']}-only.png";im=cv2.imread(str(file))
        if im is None or tuple(im.shape[:2])!=(box[3]-box[1],box[2]-box[0]):raise ValueError('Missing or misregistered parent-grid witness')
        rows.append((box,im))
    lo=np.minimum(rows[0][0][:2],rows[1][0][:2]);hi=np.maximum(rows[0][0][2:],rows[1][0][2:])
    if np.prod(hi-lo)>1000000:raise ValueError('Local witness comparison budget exceeded')
    canvases=[]
    for box,im in rows:
        canvas=np.full((hi[1]-lo[1],hi[0]-lo[0],3),255,np.uint8);canvas[box[1]-lo[1]:box[3]-lo[1],box[0]-lo[0]:box[2]-lo[0]]=im;canvases.append(canvas)
    return int(np.abs(canvases[0].astype(int)-canvases[1].astype(int)).max())
def equivalent(a,b):
    error=shape_error(a,b);eps=delta(a,b)
    result={'geometry_error_px':None if not np.isfinite(error) else error,'delta_px':eps,'style_equal':style_equal(a,b),'context_equal':context_equal(a,b)}
    if error>eps or not result['style_equal'] or not result['context_equal']:return False,result
    witness=witness_difference(a,b);result['witness_max_delta']=witness
    return witness is not None and witness<=1,result

def overlap_intervals(a,b):
    """Positive collinear overlap only; contacts/T/crossings are not duplicate intervals."""
    rows=[];eps=delta(a,b)
    for i,(x,y) in enumerate(_segments(tuple(map(tuple,points(a))),a['closed'])):
        x,y=np.array(x),np.array(y);v=y-x;length=np.linalg.norm(v)
        if length<1e-10:continue
        u=v/length;n=np.array([-u[1],u[0]])
        for j,(c,d) in enumerate(_segments(tuple(map(tuple,points(b))),b['closed'])):
            c,d=np.array(c),np.array(d)
            if max(abs((c-x)@n),abs((d-x)@n))>eps:continue
            lo=max(0,min((c-x)@u,(d-x)@u));hi=min(length,max((c-x)@u,(d-x)@u))
            if hi-lo>max(1e-8,2*eps):rows.append({'edge':i,'other_edge':j,'start_px':float(lo),'end_px':float(hi),'length_px':float(hi-lo)})
    return rows
def unique_intervals(row,others):
    covered={}
    for other in others:
        for v in overlap_intervals(row,other):covered.setdefault(v['edge'],[]).append((v['start_px'],v['end_px']))
    unique=[]
    for i,(a,b) in enumerate(_segments(tuple(map(tuple,points(row))),row['closed'])):
        length=float(np.linalg.norm(np.array(b)-a));end=0
        for lo,hi in sorted(covered.get(i,[])):
            if lo>end+1e-8:unique.append({'edge':i,'start_px':end,'end_px':lo,'length_px':lo-end})
            end=max(end,hi)
        if end<length-1e-8:unique.append({'edge':i,'start_px':end,'end_px':length,'length_px':length-end})
    return unique

def existing_rows(doc,frame):
    u=frame['unit_per_source_pixel'];offset=np.array(frame['source_to_world'])[2];out=[]
    def inverse(p):return [(p[0]-offset[0])/u,(offset[1]-p[1])/u]
    for e in doc.modelspace():
        if e.dxftype() not in ['LINE','LWPOLYLINE'] or doc.layers.get(e.dxf.layer).is_off() or doc.layers.get(e.dxf.layer).is_frozen() or e.dxf.get('invisible',0):continue
        if e.dxftype()=='LINE':p=[inverse(e.dxf.start),inverse(e.dxf.end)];closed=False;width=None
        else:
            rawpoints=list(e.get_points());p=[inverse(q) for q in rawpoints];closed=bool(e.closed)
            width=float(e.dxf.const_width)/u if e.dxf.const_width>0 and all(not q[2] and not q[3] and not q[4] for q in rawpoints) else None
        if len(p)<2:continue
        if e.rgb is not None:rgb=list(e.rgb)
        else:
            color=e.dxf.color if e.dxf.color!=256 else doc.layers.get(e.dxf.layer).color
            rgb=[0,0,0] if color in [0,7] else list(ezdxf.colors.aci2rgb(abs(color)))
        source={}
        if e.has_xdata('GOAL03_SOURCE'):source=json.loads(''.join(t.value for t in e.get_xdata('GOAL03_SOURCE')))
        layer=doc.layers.get(e.dxf.layer);linetype=e.dxf.linetype.upper()
        if linetype=='BYLAYER':linetype=layer.dxf.linetype.upper()
        unsupported_linetype=linetype!='CONTINUOUS'
        # BYBLOCK cannot be resolved here; defer rather than asserting an opaque style.
        transparency_raw=e.dxf.get('transparency',None)
        nonopaque=e.is_transparency_by_block or e.transparency>0 or (e.is_transparency_by_layer and layer.transparency>0)
        out.append({'points':p,'closed':closed,'width_px':width or 1.,'rgb':rgb,'source_file':source.get('source_file'),'page':source.get('page'),'dpi':None,
            '_width_unknown':width is None,'_existing':True,'_handle':e.dxf.handle,'source_path':{'line_cap':0,'line_join':0,'dash_count':int(unsupported_linetype),'transparent':nonopaque},
            'existing_style_evidence':{'linetype':linetype,'transparency_raw':transparency_raw,'layer_transparency':layer.transparency}})
    return out

def select(candidates,existing):
    candidates=sorted(candidates,key=key);n=len(candidates);pairs={};adj=[set() for _ in candidates];relationships=[]
    for i,j in itertools.combinations(range(n),2):
        eq,proof=equivalent(candidates[i],candidates[j]);pairs[i,j]=(eq,proof)
        if eq:adj[i].add(j);adj[j].add(i)
    groups=[];unseen=set(range(n))
    while unseen:
        todo=[min(unseen)];group=set()
        while todo:
            v=todo.pop()
            if v in group:continue
            group.add(v);unseen.discard(v);todo.extend(adj[v]-group)
        groups.append(sorted(group))
    unsafe={};conflicts={i:[] for i in range(n)}
    for g in groups:
        if any(not pairs[min(i,j),max(i,j)][0] for i,j in itertools.combinations(g,2)):
            for i in g:unsafe[i]='DEFER_NONTRANSITIVE_NEAR_EQUIVALENCE'
    for i,j in itertools.combinations(range(n),2):
        if pairs[i,j][0]:continue
        overlap=overlap_intervals(candidates[i],candidates[j])
        if overlap:
            conflicts[i].append(candidates[j]);conflicts[j].append(candidates[i]);unsafe[i]=unsafe[j]='DEFER_PARTIAL_OR_STYLE_CONFLICT'
            relationships.append({'sources':[candidates[i]['source_object'],candidates[j]['source_object']],'relation':'POSITIVE_OVERLAP_NOT_COMPLETE_EQUIVALENCE','intervals':overlap,'proof':pairs[i,j][1]})
    owners=[];pending=[]
    for group in groups:
        members=[candidates[i] for i in group];rep=members[0];oldowners=[];oldconflict=[]
        for old in existing:
            eq,proof=equivalent(rep,old)
            if eq:oldowners.append((old,proof))
            elif overlap_intervals(rep,old):oldconflict.append(old)
        if any(i in unsafe for i in group) or oldconflict or len(oldowners)>1:
            reason=next((unsafe[i] for i in group if i in unsafe),'DEFER_BASELINE_PARTIAL_STYLE_OR_MULTIPLE_OWNERS')
            for i,row in zip(group,members):
                others=conflicts[i]+oldconflict+[candidates[j] for j in group if j!=i and i in unsafe]
                pending.append({'source_object':row['source_object'],'decision':'PENDING','reason':reason,'original_candidate':clean(row),
                    'unique_intervals':unique_intervals(row,others),'baseline_conflict_handles':[e['_handle'] for e in oldconflict]})
            continue
        proofs=[]
        for row in members:
            valid,proof=equivalent(rep,row);assert valid;proofs.append({'source_object':row['source_object'],**proof})
        owner={'decision':'REUSE_BASELINE_OWNER' if oldowners else 'ADOPT_REPRESENTATIVE','representative':clean(rep),'members':[clean(r) for r in members],
            'source_objects':sorted(r['source_object'] for r in members),'full_equivalence_proofs':proofs,'existing_handle':oldowners[0][0]['_handle'] if oldowners else None,
            'suppressed_sources':[r['source_object'] for r in members[1:]],'baseline_proof':oldowners[0][1] if oldowners else None}
        owners.append(owner)
    decisions=[]
    for owner in owners:
        for row in owner['members']:
            decisions.append({'source_object':row['source_object'],'decision':owner['decision'] if row['source_object']==owner['representative']['source_object'] else 'SUPPRESS_COMPLETE_EQUIVALENT',
                'representative_source':owner['representative']['source_object'],'retained_source_objects':owner['source_objects'],'reason':'complete same-style parent-grid witnessed equivalence; original representative geometry retained'})
    decisions.extend({k:r[k] for k in ['source_object','decision','reason']} for r in pending)
    return {'policy':POLICY,'owners':owners,'pending':pending,'decisions':sorted(decisions,key=lambda r:r['source_object']),'relationships':relationships}

def run(baseline,framefile,candidatefile,witnessdir,out):
    out=Path(out);out.mkdir(exist_ok=False);frame=load(framefile);receipt=load(candidatefile)
    if receipt['grid']!='parent' or not receipt['source_state_restored']:raise ValueError('Only restored parent-grid candidate receipts supported')
    candidates=[{**copy.deepcopy(row),'_witness_dir':str(Path(witnessdir).resolve())} for row in receipt['accepted']]
    doc=ezdxf.readfile(baseline);before=records(doc);selection=select(candidates,existing_rows(doc,frame));newowners=[o for o in selection['owners'] if not o['existing_handle']]
    write_repair(doc,frame,[o['representative'] for o in newowners],out);doc=ezdxf.readfile(out/'experimental.dxf');created=load(out/'created.json');assert len(created)==len(newowners)
    if 'GOAL04_SOURCES' not in doc.appids:doc.appids.new('GOAL04_SOURCES')
    for owner,createdrow in zip(newowners,created):
        owner['handle']=createdrow['handle'];payload=json.dumps({'version':1,'representative_source':owner['representative']['source_object'],'source_objects':owner['source_objects']},separators=(',',':'))
        doc.entitydb[owner['handle']].set_xdata('GOAL04_SOURCES',[(1000,payload[i:i+240]) for i in range(0,len(payload),240)])
    for owner in selection['owners']:
        if owner['existing_handle']:owner['handle']=owner['existing_handle']
    after=records(doc);changed=[h for h in before if after.get(h)!=before[h]]
    if changed:raise RuntimeError('Old model-space entity changed')
    doc.saveas(out/'experimental.dxf');selection.update(input_baseline=str(Path(baseline).resolve()),input_candidates=str(Path(candidatefile).resolve()),
        input_witness_dir=str(Path(witnessdir).resolve()),new_entities=len(newowners),suppressed_count=sum(len(o['suppressed_sources']) for o in selection['owners']),
        old_entity_count=len(before),old_entity_changes=changed,upstream_rejections=[r for r in receipt['all_candidates'] if r['decision']!='ACCEPT'])
    save(out/'selection.json',selection);print(json.dumps({'owners':len(selection['owners']),'new_entities':len(newowners),'suppressed':selection['suppressed_count'],'pending':len(selection['pending'])}))
    return selection
def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--frame',required=True);p.add_argument('--candidates',required=True);p.add_argument('--witness-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.baseline,a.frame,a.candidates,a.witness_dir,a.out)
if __name__=='__main__':main()
