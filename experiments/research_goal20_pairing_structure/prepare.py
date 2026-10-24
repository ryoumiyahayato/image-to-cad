"""All values, graphs, inputs, labels and step exposure frozen before model use."""
import copy,random
from collections import Counter,defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from common import *
renderer=load_module('goal14_renderer20',G14/'generate.py')

# Index rotations are fixed here, before model outputs. Across each digit-length
# stratum, G/S changed-position and permutation/replacement counts are identical.
RECIPES=[
 dict(N0=[12,21,34,43],D0=[14,41,27,72],N1=[18,81,26,62],D1=[17,71,28,82]),
 dict(N0=[57,78,87,75],D0=[38,49,94,83],N1=[37,59,95,73],D1=[36,47,63,74]),
 dict(N0=[11,13,15,19],D0=[23,45,32,54],N1=[66,67,68,69],D1=[24,44,64,84]),
 dict(N0=[123,321,456,654],D0=[126,621,347,743],N1=[124,421,357,753],D1=[127,721,348,843]),
 dict(N0=[167,258,852,761],D0=[168,259,952,861],N1=[169,278,872,961],D1=[179,268,971,862]),
 dict(N0=[234,235,237,238],D0=[145,267,541,762],N1=[264,274,284,294],D1=[246,346,546,646]),
]

def connected(edges):
    adj={a:set() for a in NODES}
    for a,b in edges:adj[a].add(b);adj[b].add(a)
    unseen=set(NODES);components=[]
    while unseen:
        todo=[min(unseen)];seen=set()
        while todo:
            a=todo.pop()
            if a in seen:continue
            seen.add(a);todo.extend(adj[a]-seen)
        unseen-=seen;components.append(sorted(seen))
    return adj,components

def main():
    (OUT/'data/images').mkdir(parents=True,exist_ok=False);(OUT/'data/arrays').mkdir();(OUT/'data/masks').mkdir()
    g,s,full=graphs();arms={'G':g,'S':s};graph_control={}
    for arm,edges in arms.items():
        adj,cc=connected(edges);assert len(edges)==16 and all(len(v)==2 for v in adj.values())
        assert all(Counter(relation_role(a,b) for b in bs)=={'numerator':1,'denominator':1} for a,bs in adj.items())
        assert len(cc)==(4 if arm=='G' else 1)
        graph_control[arm]=dict(edges=sorted(edges),components=cc,node_degree=2,one_neighbor_each_role=True,bidirectional=True)
    held=full-(g|s);assert len(held)==24 and len(g&s)==8
    font=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/ibmplexmono/IBMPlexMono-Regular.ttf'
    assert 'SIL OPEN FONT LICENSE' in (font.parent/'OFL.txt').read_text(encoding='utf8')
    historical_rows=read(OLD/'data/train.json');historical_images={r['image']:r for r in read(OLD/'data/images.json')}
    historical_values=defaultdict(Counter);historical_sources=Counter();historical_candidates=Counter(r['candidate_raw'] for r in historical_rows);historical_relations=Counter()
    for r in historical_rows:
        sp=historical_images[r['image']]['construction_only'];cp=parse_candidate(r['candidate_raw'])
        for role in ['whole','numerator','denominator']:
            if sp.get(role) is not None:historical_values['image_'+role][str(sp[role])]+=1
        # Parse using the existing contract; retain raw candidate history separately.
        for role in ['whole','numerator','denominator']:
            value=cp.get('parts',cp).get(role)
            if value is not None:historical_values['candidate_'+role][str(value)]+=1
        historical_sources[renderer.spelling(sp)]+=1
        historical_relations[(renderer.spelling(sp),r['candidate_raw'],r['scope'])]+=1
    exposed=set()
    for p in [ROOT/'local-artifacts/research-goal17-frozen-numeric-probe-20261023/synthetic/pairs.json',ROOT/'local-artifacts/research-goal18-identity-supervision-20261023/data/pairs.json',ROOT/'local-artifacts/research-goal19-role-composition-20261023/data/pairs.json']:
        exposed.update(r['candidate_raw'] for r in read(p))
    train_values={str(x) for b in RECIPES for k in ['N0','D0'] for x in b[k]}
    eval_values={str(x) for b in RECIPES for k in ['N1','D1'] for x in b[k]}
    assert not train_values&eval_values
    blocks=[];images=[];pairs=[];image_by={};array_cache={};control_cache={};pixel_arrays=[];history=[]
    for bi,recipe in enumerate(RECIPES):
        bid=f'b{bi}';b=dict(id=bid,**{k:list(map(str,v)) for k,v in recipe.items()});blocks.append(b)
        assert all(len(set(v))==4 for k,v in b.items() if k!='id')
        for k in ['N0','D0','N1','D1']:
            assert len({len(x) for x in b[k]})==1
            for value in b[k]:history.append(dict(block=bid,pool=k,value=value,seen_in_new_grid_training=value in train_values,historical_counts={tag:cnt[value] for tag,cnt in historical_values.items()}))
        for cond in CONDITIONS:
            nv=b['N'+cond[0]];dv=b['D'+cond[1]]
            for i,j in NODES:
                iid=f'{bid}-{cond}-{i}{j}';sp=renderer.spec('fraction',n=nv[i],d=dv[j]);raw=renderer.spelling(sp)
                assert raw not in exposed,('previously exposed Goal17-19 expression',raw)
                a,masks,glyphs,bg=renderer.render(sp,font,'stacked',0);x=((np.float32(255)-a.astype(np.float32))/np.float32(255))[None]
                roles={r:np.maximum.reduce([m for m,gl in zip(masks,glyphs) if r in gl['roles']]) if any(r in gl['roles'] for gl in glyphs) else np.zeros_like(a) for r in ROLES}
                image=f'data/images/{iid}.png';array=f'data/arrays/{iid}.npy'
                Image.fromarray(a).save(OUT/image);np.save(OUT/array,x);np.savez_compressed(OUT/f'data/masks/{iid}.npz',background=bg,**roles)
                im=dict(id=iid,block=bid,condition=cond,node=[i,j],source=sp,raw=raw,image=image,array=array,glyphs=glyphs,shape=[1,128,512],font=str(font),layout='stacked',font_size=36,fraction_font_size=23,scale=1,shift=[0,0],historical_source_occurrences=historical_sources[raw],historical_candidate_occurrences=historical_candidates[raw],goal17_19_expression_exposed=False)
                images.append(im);image_by[(bid,cond,(i,j))]=im;array_cache[iid]=x;control_cache[iid]=(roles,glyphs,bg);pixel_arrays.append(a)
            # Complete pool of all self and all directed single-role comparisons.
            for a in NODES:
                for z in NODES:
                    if sum(x!=y for x,y in zip(a,z))>1:continue
                    im=image_by[(bid,cond,a)];cm=image_by[(bid,cond,z)];ann=label(parts(im['source']),cm['raw'],(),scope='NUMBER_UNIT')
                    role=relation_role(a,z) if a!=z else None
                    assert [r for r,v in ann['parts'].items() if v=='CONTRADICTION']==([role] if role else [])
                    assert ann['parts']['unit']==ann['parts']['relation']=='CONSISTENT' and not ann['has_insufficient']
                    codes=encode_candidate(cm['raw']);assert ''.join(CHARSET[x-1] for x in codes if x)==cm['raw']
                    pid=f'{bid}:{cond}:{a[0]}{a[1]}:{z[0]}{z[1]}'
                    pairs.append(dict(id=pid,block=bid,component=bid,condition=cond,source_node=list(a),candidate_node=list(z),image_id=im['id'],image=str(OUT/im['image']),array=im['array'],candidate_raw=cm['raw'],candidate_codes=codes,scope='NUMBER_UNIT',target_role=role,digits=len(im['source'][role]) if role else len(nv[0]),change=change(im['source'][role],cm['source'][role]) if role else None,annotation=ann,historical_relation_occurrences=historical_relations[(im['raw'],cm['raw'],'NUMBER_UNIT')]))
    by={(r['block'],r['condition'],tuple(r['source_node']),tuple(r['candidate_node'])):r for r in pairs}
    train={};records={};views={};difficulty={};per_block_difficulty={}
    for arm,edges in arms.items():
        train[arm]=[r for r in pairs if r['condition']=='00' and (r['source_node']==r['candidate_node'] or edge(r['source_node'],r['candidate_node']) in edges)]
        records[arm]=[];views[arm]={};per_block_difficulty[arm]={}
        for b in blocks:
            bid=b['id'];views[arm][bid]={}
            for phase,role in [('C',None),('N','numerator'),('D','denominator')]:
                rr=[r for r in train[arm] if r['block']==bid and r['target_role']==role];assert len(rr)==16
                views[arm][bid][phase]=[r['id'] for r in rr]
            records[arm].extend(views[arm][bid]['C']+views[arm][bid]['N']+views[arm][bid]['C']+views[arm][bid]['D'])
            per_block_difficulty[arm][bid]=dict(Counter(json.dumps(dict(role=r['target_role'],**r['change']),sort_keys=True) for r in train[arm] if r['block']==bid and r['change']))
        difficulty[arm]=dict(Counter(json.dumps(dict(role=r['target_role'],**r['change']),sort_keys=True) for r in train[arm] if r['change']))
        assert len(train[arm])==288 and len(records[arm])==384 and len(set(records[arm]))==288
        write(OUT/f'data/train-{arm}.json',train[arm]);write(OUT/f'data/train-records-{arm}.json',records[arm])
    assert difficulty['G']==difficulty['S'],(difficulty['G'],difficulty['S'])
    # Frozen equal-step exposure. Each complete 24-step round visits all six blocks once.
    rng=random.Random(SEED);schedule=[];batch_controls=[]
    for epoch in range(83):
        order=[b['id'] for b in blocks];rng.shuffle(order)
        for bid in order:
            for phase in ['C','N','C','D']:
                step=len(schedule)+1;replay=[historical_rows[rng.randrange(len(historical_rows))]['id'] for _ in range(16)]
                item=dict(update=step,cycle=epoch,block=bid,phase=phase,new_ids={a:views[a][bid][phase] for a in arms},replay_ids=replay,new_positions=list(range(16)),replay_positions=list(range(16,32)))
                aa=[[next(r for r in train[arm] if r['id']==pid) for pid in item['new_ids'][arm]] for arm in arms]
                for key in ['image','candidate_raw','scope']:
                    assert Counter(r[key] for r in aa[0])==Counter(r[key] for r in aa[1])
                assert [r['image'] for r in aa[0]]==[r['image'] for r in aa[1]]
                assert [r['annotation']['parts'] for r in aa[0]]==[r['annotation']['parts'] for r in aa[1]]
                dc=[Counter(json.dumps(r['change'],sort_keys=True) for r in rr) for rr in aa]
                batch_controls.append(dict(update=step,block=bid,phase=phase,image_counts_equal=True,candidate_counts_equal=True,image_positions_equal=True,role_labels_by_position_equal=True,scope_equal=True,replay_ids_equal=True,replay_positions_equal=True,difficulty_histogram_equal=dc[0]==dc[1],difficulty={a:dict(d) for a,d in zip(arms,dc)}))
                schedule.append(item)
    assert len(schedule)==UPDATES
    old_by={r['id']:r for r in historical_rows};replay_ids=sorted({rid for b in schedule for rid in b['replay_ids']});replay=[]
    for rid in replay_ids:
        r=copy.deepcopy(old_by[rid]);r['image']=str(OLD/'data'/r['image']);replay.append(r)
    grids=[];eval_ids={c:set() for c in CONDITIONS}
    for b in blocks:
        for cond in CONDITIONS:
            edges=held if cond=='00' else full
            for a,z in sorted(edges):
                ids=[by[(b['id'],cond,x,y)]['id'] for x,y in [(a,a),(a,z),(z,a),(z,z)]]
                assert all(edge(a,z) not in arms[arm] for arm in arms) if cond=='00' else True
                role=relation_role(a,z);im=image_by[(b['id'],cond,a)];cm=image_by[(b['id'],cond,z)]
                grid=dict(id=f"{b['id']}:{cond}:{a[0]}{a[1]}-{z[0]}{z[1]}",block=b['id'],condition=cond,target_role=role,context_role='denominator' if role=='numerator' else 'numerator',pair_ids=ids,change=change(im['source'][role],cm['source'][role]))
                grids.append(grid);eval_ids[cond].update(ids)
    for cond,ids in eval_ids.items():write(OUT/f'data/eval-{cond}.json',[r for r in pairs if r['id'] in ids])
    # Full model-array deduplication; no hash or fingerprint.
    aa=np.stack(pixel_arrays);_,inv=np.unique(aa.reshape(len(aa),-1),axis=0,return_inverse=True)
    px={im['id']:int(v) for im,v in zip(images,inv)};unique={(px[r['image_id']],r['candidate_raw'],r['scope']) for r in pairs}
    assert len(set(inv.tolist()))==384 and len(unique)==2688 and len(unique)<=3000
    controls=[]
    def check_inputs(ida,idb,changed,kind):
        x,y=array_cache[ida],array_cache[idb];ma,ga,ba=control_cache[ida];mb,gb,bb=control_cache[idb];checks={}
        for role in ROLES:
            if role==changed:continue
            support=(ma[role]>0)|(mb[role]>0)
            checks[role]=dict(glyphs_positions_equal=[g for g in ga if role in g['roles']]==[g for g in gb if role in g['roles']],mask_equal=bool(np.array_equal(ma[role],mb[role])),final_model_pixels_equal=bool(np.array_equal(x[0][support],y[0][support])))
        outside=int(np.count_nonzero((x[0]!=y[0])&~((ma[changed]>0)|(mb[changed]>0))))
        passed=all(all(v.values()) for v in checks.values()) and np.array_equal(ba,bb) and outside==0
        controls.append(dict(a=ida,b=idb,changed_role=changed,kind=kind,roles=checks,changed_outside_role=outside,background_equal=bool(np.array_equal(ba,bb)),status='MET' if passed else 'INPUT_CONTROL_NOT_MET'))
    for b in blocks:
        bid=b['id']
        for cond in CONDITIONS:
            for a,z in sorted(full):check_inputs(image_by[(bid,cond,a)]['id'],image_by[(bid,cond,z)]['id'],relation_role(a,z),'within_grid')
        for ca,cb,role in [('00','01','denominator'),('10','11','denominator'),('00','10','numerator'),('01','11','numerator')]:
            for node in NODES:check_inputs(image_by[(bid,ca,node)]['id'],image_by[(bid,cb,node)]['id'],role,'cross_condition')
    assert all(c['status']=='MET' for c in controls)
    for arm in arms:
        write(OUT/f'data/graph-{arm}.json',graph_control[arm])
    write(OUT/'data/blocks.json',blocks);write(OUT/'data/images.json',images);write(OUT/'data/pairs.json',pairs);write(OUT/'data/grids.json',grids);write(OUT/'data/replay-rows.json',replay);write(OUT/'batch-plan.json',schedule)
    write(OUT/'data/historical-exposure.json',dict(values=history,image_expressions=[{k:im[k] for k in ['id','raw','condition','historical_source_occurrences','historical_candidate_occurrences']} for im in images],comparison_relation_seen=sum(r['historical_relation_occurrences']>0 for r in pairs),new_values_absent_current_training=True,goal17_19_complete_expression_overlap=0))
    write(OUT/'input-controls.json',controls);write(OUT/'batch-controls.json',batch_controls)
    summary=dict(utc=utc(),graphs=graph_control,training_images_each=96,training_unique_pairs_each=288,training_sample_records_each=384,distinct_pixel_inputs=384,distinct_all_pairs=2688,
        eval_unique_pairs={c:len(ids) for c,ids in eval_ids.items()},eval_grids=dict(Counter(g['condition'] for g in grids)),blocks=6,total_updates=UPDATES,complete_rounds=83,
        input_controls=len(controls),input_control='MET',difficulty=difficulty,difficulty_global_equal=True,difficulty_by_block=per_block_difficulty,difficulty_equal_batches=sum(r['difficulty_histogram_equal'] for r in batch_controls),
        difficulty_limitation='Aggregate role/digit-length/changed-positions/permutation histograms match exactly across the six-block pool and actual 83 repeated rounds. Some individual blocks and wrong-pair steps differ; this is a pairing-arrangement experiment, not an isolated proof of pure graph connectivity.',
        replay_draws_each=UPDATES*16,replay_unique_rows=len(replay),hashes_computed=False,model_outputs_seen=False)
    write(OUT/'data-control.json',summary)
    # Native-size contact sheets: each block/condition contains all sixteen images.
    ff=ImageFont.truetype(str(font),14)
    for b in blocks:
        for cond in CONDITIONS:
            sheet=Image.new('RGB',(1040,8*150),'#eee');draw=ImageDraw.Draw(sheet)
            for k,node in enumerate(NODES):
                im=image_by[(b['id'],cond,node)];x=(k%2)*520;y=(k//2)*150
                sheet.paste(Image.open(OUT/im['image']),(x,y+22));draw.text((x+4,y+2),im['id']+' '+im['raw'],font=ff,fill='black')
            sheet.save(OUT/f"data/contact-{b['id']}-{cond}.png")
    print(json.dumps({k:v for k,v in summary.items() if k not in ['graphs','difficulty','difficulty_by_block']},ensure_ascii=False))
if __name__=='__main__':main()
