"""Original four-expression groups, paired marginal equality, fixed replay schedule."""
import random,copy
from collections import Counter,defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from common import *
renderer=load_module('goal15_render18',G15/'prepare_data.py');old=renderer.old

def main():
    folder=OUT/'data';(folder/'images').mkdir(parents=True,exist_ok=False)
    specs={
      'train':{'numerator':[(24,42,135,153,53),(36,39,268,269,61),(57,75,481,487,89)],
               'denominator':[(25,52,136,163,34),(47,49,258,259,68),(68,86,347,349,72)]},
      'sealed':{'numerator':[(28,82,146,164,47),(43,49,357,359,73),(67,76,582,589,97)],
                'denominator':[(26,62,145,154,38),(35,39,276,278,56),(48,84,367,369,82)]}}
    font=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/ibmplexmono/IBMPlexMono-Regular.ttf'
    assert 'SIL OPEN FONT LICENSE' in (font.parent/'OFL.txt').read_text(encoding='utf8')
    from fontTools.ttLib import TTFont
    tt=TTFont(font);assert all(ord(c) in tt.getBestCmap() for c in '0123456789/"');tt.close()
    historical=set()
    for path in [OLD/'data/pairs.json',ROOT/'local-artifacts/research-goal15-numeric-consistency-pilot-20261023/data/pairs.json',G17/'synthetic/pairs.json']:
        historical.update(r['candidate_raw'] for r in read(path))
    groups=[];images=[];pairs=[];arrays=[];errors=[]
    for split,roles in specs.items():
        for role,recipes in roles.items():
            for j,values in enumerate(recipes):
                gid=f'{split}-{role}-{j}';digits=values[:4];other=values[4]
                sources=[old.spec('fraction',n=str(d if role=='numerator' else other),d=str(other if role=='numerator' else d)) for d in digits]
                candidates=[old.spelling(s) for s in sources];assert not historical.intersection(candidates)
                assert len(set(candidates))==4 and all(len(str(x))==(2 if i<2 else 3) for i,x in enumerate(digits))
                variant=lambda a,b:'permutation' if sorted(str(a))==sorted(str(b)) else 'replacement'
                g=dict(id=gid,split=split,target_role=role,sources=sources,candidates=candidates,variants=[variant(digits[0],digits[1]),variant(digits[2],digits[3])]);groups.append(g)
                for si,s in enumerate(sources):
                    a,glyphs,unknown,panel,found=renderer.render_view(s,font,'stacked',0,'complete');errors.extend(found);assert not unknown and panel is None
                    assert all(x['original_pixels']==x['final_pixels'] and x['final_bbox'] for x in glyphs)
                    iid=f'{gid}-e{si+1}';path=f'data/images/{iid}.png';Image.fromarray(a).save(OUT/path);arrays.append(a)
                    im=dict(id=iid,image=path,group=gid,split=split,source_index=si,source=s,glyphs=glyphs,canvas=[512,128],font=str(font),layout='stacked',font_size=36,fraction_font_size=23,unknown_roles=[])
                    images.append(im)
                for arm,cross in [('E',[1,0,3,2]),('L',[2,3,0,1])]:
                    for si,s in enumerate(sources):
                        for is_wrong,ci in [(False,si),(True,cross[si])]:
                            pairset=si//2 if arm=='E' else si%2
                            row=dict(id=f'{gid}:{arm}:e{si+1}:c{ci+1}',image=f'data/images/{gid}-e{si+1}.png',candidate_raw=candidates[ci],scope='NUMBER_UNIT',
                                component=gid,group=gid,split=split,target_role=role,arm=arm,source_index=si,candidate_index=ci,
                                contrast=f'{gid}:{arm}:{pairset}',digits=2+pairset if arm=='E' else '2_vs_3',variant=g['variants'][pairset] if arm=='E' else 'length_change',
                                annotation=label(parts(s),candidates[ci],(),scope='NUMBER_UNIT'))
                            assert [r for r,v in row['annotation']['parts'].items() if v=='CONTRADICTION']==([role] if is_wrong else [])
                            encode_candidate(row['candidate_raw']);pairs.append(row)
    assert not errors
    # Complete-array comparison, no hashes. Separate new training, sealed and Goal17 exposed pixels.
    old_images=read(G17/'synthetic/images.json');old_arrays=[np.asarray(Image.open(G17/r['image']).convert('L')) for r in old_images]
    all_arrays=np.stack(arrays+old_arrays);_,index,inverse=np.unique(all_arrays.reshape(len(all_arrays),-1),axis=0,return_index=True,return_inverse=True)
    assert len(set(int(x) for x in inverse[:48]))==48
    assert not set(inverse[:48]).intersection(inverse[48:])
    by_image={im['image']:i for i,im in enumerate(images)};seen={}
    for r in pairs:
        k=(int(inverse[by_image[r['image']]]),r['candidate_raw'],r['scope'])
        assert k not in seen or seen[k]==r['annotation']['parts'];seen[k]=r['annotation']['parts']
    fairness=[]
    for g in groups:
        arms={a:[r for r in pairs if r['group']==g['id'] and r['arm']==a] for a in ['E','L']}
        for key in ['image','candidate_raw']:
            assert Counter(r[key] for r in arms['E'])==Counter(r[key] for r in arms['L'])
        assert Counter(json.dumps(r['annotation']['parts'],sort_keys=True) for r in arms['E'])==Counter(json.dumps(r['annotation']['parts'],sort_keys=True) for r in arms['L'])
        correct=lambda rs:{(r['image'],r['candidate_raw'],r['scope']) for r in rs if r['annotation']['overall']=='CONSISTENT'}
        assert correct(arms['E'])==correct(arms['L'])
        assert [r['image'] for r in arms['E']]==[r['image'] for r in arms['L']]
        assert [r['annotation']['parts'] for r in arms['E']]==[r['annotation']['parts'] for r in arms['L']]
        fairness.append(dict(group=g['id'],same_image_counts=True,same_candidate_counts=True,same_correct_pairs=True,same_role_label_counts=True,same_image_order=True,only_wrong_partner_differs=True))
    train_old=read(OLD/'data/train.json');by_id={r['id']:r for r in train_old};rng=random.Random(SEED);schedule=[]
    # Random schedule fixed without any model output. Each role cycles through its 3 groups, shuffled once per cycle.
    choices={role:[] for role in ['numerator','denominator']}
    for step in range(1,2001):
        chosen=[]
        for role in choices:
            if not choices[role]:choices[role]=[f'train-{role}-{i}' for i in range(3)];rng.shuffle(choices[role])
            chosen.append(choices[role].pop())
        replay=[train_old[rng.randrange(len(train_old))]['id'] for _ in range(16)]
        schedule.append(dict(update=step,new_groups=chosen,replay_ids=replay))
    replay_ids=sorted({x for s in schedule for x in s['replay_ids']});replay_rows=[]
    for rid in replay_ids:
        r=copy.deepcopy(by_id[rid]);r['image']=str(OLD/'data'/r['image']);r['id']='replay:'+rid;replay_rows.append(r)
    # All per-batch role/image/candidate marginal constraints follow by concatenating the checked complete groups and identical replay.
    for split in ['train','sealed']:
        for arm in ['E','L']:write(folder/f'{split}-{arm}.json',[r for r in pairs if r['split']==split and r['arm']==arm])
    write(folder/'images.json',images);write(folder/'groups.json',groups);write(folder/'pairs.json',pairs)
    write(OUT/'batch-plan.json',schedule);write(folder/'replay-rows.json',replay_rows)
    write(folder/'pairing-check.json',dict(utc=utc(),groups=fairness,errors=errors,new_images=48,new_distinct_pixels=48,train_groups=6,sealed_groups=6,
        pairs_per_arm_per_partition=48,distinct_pairs_per_partition=72,same_scope='NUMBER_UNIT',original_expression_overlap_historical=0,
        exact_pixel_overlap_train_sealed=0,exact_pixel_overlap_goal17=0,same_input_label_conflicts=0,
        replay_source='Goal16 original train only; labels unchanged',replay_unique_rows=len(replay_rows),replay_draws_per_arm=32000,batch_plan_seed=SEED,
        per_batch=dict(new_rows=16,old_rows=16,new_groups=2,images_candidates_label_counts_equal=True),hashes_computed=False))
    # Preserve real arrays in place: read their shapes/values, never transform or re-render.
    real=read(G17/'real-local/pairs.json');frozen=[]
    for r in real:
        rr=copy.deepcopy(r);rr['array']=str(G17/'real-local/arrays'/f"{r['id']}.npy") if r['run_forward'] else None
        if rr['array']:
            arr=np.load(rr['array']);assert arr.shape==(1,128,512) and arr.dtype==np.float32 and np.isfinite(arr).all() and arr.min()>=0 and arr.max()<=1
        frozen.append(rr)
    assert sum(r['run_forward'] for r in frozen)==21 and sum(r['contract_scorable'] for r in frozen)==19
    write(OUT/'real-local/frozen-pairs.json',frozen)
    # Both partitions can be inspected for data validity before training; sealed model outputs remain unseen until both trajectories stop.
    ff=ImageFont.truetype(str(font),16)
    for split in ['train','sealed']:
        sheet=Image.new('RGB',(1050,6*170),'#eee');draw=ImageDraw.Draw(sheet)
        for gi,g in enumerate([g for g in groups if g['split']==split]):
            for si in range(4):
                x=(si%2)*525;y=gi*170+(si//2)*75
                im=Image.open(OUT/f"data/images/{g['id']}-e{si+1}.png");im=im.resize((256,64));sheet.paste(im,(x,y+18));draw.text((x+260,y+25),g['id']+f' e{si+1}',font=ff,fill='black')
        sheet.save(folder/f'contact-{split}.png')
    print(json.dumps(read(folder/'pairing-check.json')))

if __name__=='__main__':main()
