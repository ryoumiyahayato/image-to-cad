"""One original render per new combination; offline full-array and role controls."""
import copy
from collections import Counter
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from common import *
renderer=load_module('goal14_renderer19',G14/'generate.py')

def main():
    (OUT/'data/images').mkdir(parents=True,exist_ok=False)
    (OUT/'data/arrays').mkdir()
    (OUT/'data/masks').mkdir()
    groups={g['id']:g for g in read(OLD/'data/groups.json')}
    font=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/ibmplexmono/IBMPlexMono-Regular.ttf'
    images=[];pairs=[];blocks=[];cache={};old_checks=[]
    for role in ['numerator','denominator']:
        other='denominator' if role=='numerator' else 'numerator'
        for bi in range(3):
            bid=f'{role}-{bi}';g0=groups[f'train-{bid}'];g1=groups[f'sealed-{bid}']
            assert g0['variants']==g1['variants']
            block=dict(id=bid,target_role=role,context_role=other,T0=[s[role] for s in g0['sources']],T1=[s[role] for s in g1['sources']],C0=g0['sources'][0][other],C1=g1['sources'][0][other],variants=g0['variants'])
            blocks.append(block)
            for cond in CONDITIONS:
                tg=g0 if cond[0]=='0' else g1;cg=g0 if cond[1]=='0' else g1
                sources=[dict(copy.deepcopy(s),**{other:cg['sources'][0][other]}) for s in tg['sources']]
                candidates=[renderer.spelling(s) for s in sources]
                for si,s in enumerate(sources):
                    iid=f'{bid}-{cond}-e{si+1}'
                    a,masks,glyphs,bg=renderer.render(s,font,'stacked',0)
                    reconstructed=bg.copy()
                    for mask in masks:reconstructed=np.minimum(reconstructed,255-mask)
                    assert np.array_equal(a,reconstructed) and all(g['bbox'] for g in glyphs)
                    image_path=OUT/f'data/images/{iid}.png'
                    reused=None
                    if cond in ['00','11']:
                        split='train' if cond=='00' else 'sealed'
                        image_path=OLD/f'data/images/{split}-{bid}-e{si+1}.png'
                        original=np.asarray(Image.open(image_path).convert('L'))
                        old_checks.append(dict(image_id=iid,original=str(image_path),pixels_equal=bool(np.array_equal(a,original)),model_arrays_equal=bool(np.array_equal(normalize(a),normalize(original))),changed_pixels=int(np.count_nonzero(a!=original))))
                        reused=str(image_path)
                        a=original.copy()
                    else:Image.fromarray(a).save(image_path)
                    arr=normalize(a);np.save(OUT/f'data/arrays/{iid}.npy',arr)
                    role_masks={r:np.maximum.reduce([m for m,g in zip(masks,glyphs) if r in g['roles']]) if any(r in g['roles'] for g in glyphs) else np.zeros_like(a) for r in ROLES}
                    np.savez_compressed(OUT/f'data/masks/{iid}.npz',background=bg,**role_masks)
                    im=dict(id=iid,block=bid,condition=cond,source_index=si,source=s,image=str(image_path),array=f'data/arrays/{iid}.npy',masks=f'data/masks/{iid}.npz',glyphs=glyphs,reused_goal18=reused,shape=list(arr.shape),dtype=str(arr.dtype),font=str(font),layout='stacked',font_size=36,fraction_font_size=23,scale=1,shift=[0,0],canvas=[512,128])
                    images.append(im);cache[(bid,cond,si)]=(a,arr,role_masks,glyphs,bg)
                for si,s in enumerate(sources):
                    for ci in [si,[1,0,3,2][si]]:
                        ann=label(parts(s),candidates[ci],(),scope='NUMBER_UNIT')
                        expected={r:('CONSISTENT' if r in [role,other,'relation','unit'] else 'NOT_APPLICABLE') for r in ROLES}
                        if si!=ci:expected[role]='CONTRADICTION'
                        assert ann['parts']==expected and not ann['has_insufficient']
                        encoded=encode_candidate(candidates[ci]);decoded=''.join(CHARSET[x-1] for x in encoded if x)
                        assert decoded==candidates[ci] and len(encoded)==MAX_CHARS
                        iid=f'{bid}-{cond}-e{si+1}'
                        baseline=f"{'train' if cond=='00' else 'sealed'}-{bid}:E:e{si+1}:c{ci+1}" if cond in ['00','11'] else None
                        row=dict(id=f'{bid}:{cond}:e{si+1}:c{ci+1}',block=bid,component=bid,group=f'{bid}:{cond}',condition=cond,target_role=role,context_role=other,source_index=si,candidate_index=ci,contrast=f'{bid}:{cond}:{si//2}',digits=2+si//2,variant=tg['variants'][si//2],image_id=iid,array=f'data/arrays/{iid}.npy',candidate_raw=candidates[ci],candidate_codes=encoded,scope='NUMBER_UNIT',annotation=ann,baseline_pair_id=baseline)
                        pairs.append(row)
    controls=[]
    for block in blocks:
        bid=block['id']
        for c0,c1,factor in EDGES:
            changed=block['context_role'] if factor=='C' else block['target_role']
            held=block['target_role'] if factor=='C' else block['context_role']
            for si in range(4):
                a,x,ma,ga,ba=cache[(bid,c0,si)];b,y,mb,gb,bb=cache[(bid,c1,si)]
                role_checks={}
                for r in ROLES:
                    if r==changed:continue
                    support=(ma[r]>0)|(mb[r]>0)
                    role_checks[r]=dict(glyphs_and_positions_equal=[g for g in ga if r in g['roles']]==[g for g in gb if r in g['roles']],mask_equal=bool(np.array_equal(ma[r],mb[r])),final_input_pixels_equal=bool(np.array_equal(x[0][support],y[0][support])),support_pixels=int(support.sum()))
                diff=a!=b;changed_support=(ma[changed]>0)|(mb[changed]>0)
                rec=dict(block=bid,source_index=si,edge=f'{c0}->{c1}',factor=factor,changed_role=changed,held_role=held,roles=role_checks,background_equal=bool(np.array_equal(ba,bb)),shape_scale_shift_fixed=True,changed_pixels=int(diff.sum()),changed_outside_changed_role=int((diff&~changed_support).sum()))
                rec['passed']=rec['background_equal'] and rec['changed_outside_changed_role']==0 and all(all(v[k] for k in ['glyphs_and_positions_equal','mask_equal','final_input_pixels_equal']) for v in role_checks.values())
                rec['status']='MET' if rec['passed'] else 'INPUT_CONTROL_NOT_MET';controls.append(rec)
    arrays=np.stack([cache[(r['block'],r['condition'],r['source_index'])][0] for r in images])
    _,inverse=np.unique(arrays.reshape(len(arrays),-1),axis=0,return_inverse=True)
    pixel_id={im['id']:int(i) for im,i in zip(images,inverse)}
    unique_pairs={};conflicts=[]
    for r in pairs:
        key=(pixel_id[r['image_id']],r['candidate_raw'],r['scope'])
        if key in unique_pairs and unique_pairs[key]!=r['annotation']:conflicts.append(r['id'])
        unique_pairs[key]=r['annotation']
    assert len(images)==96 and len(pairs)==192 and not conflicts
    for cond in CONDITIONS:
        rows=[r for r in pairs if r['condition']==cond]
        assert len(rows)==48 and Counter(r['annotation']['overall'] for r in rows)=={'CONSISTENT':24,'CONTRADICTION':24}
        for bid in [b['id'] for b in blocks]:
            rr=[r for r in rows if r['block']==bid]
            assert len(rr)==8
            assert sorted(Counter(r['image_id'] for r in rr).values())==[2]*4
            assert sorted(Counter(r['candidate_raw'] for r in rr).values())==[2]*4
        write(OUT/f'data/{cond}.json',rows)
    check=dict(utc=utc(),images=96,new_images=48,reused_images=48,distinct_pixel_inputs=len(set(inverse.tolist())),pairs=192,distinct_input_pairs=len(unique_pairs),label_conflicts=conflicts,blocks=6,conditions=4,baseline_reproduction=old_checks,input_controls=controls,input_control='MET' if all(c['passed'] for c in controls) and all(c['model_arrays_equal'] for c in old_checks) else 'INPUT_CONTROL_NOT_MET',labels_recomputed=True,codec_round_trip=True,model_output_seen=False,hashes_computed=False)
    write(OUT/'data/blocks.json',blocks);write(OUT/'data/images.json',images);write(OUT/'data/pairs.json',pairs);write(OUT/'input-control.json',check)
    ff=ImageFont.truetype(str(font),15)
    # One contact sheet per block: all 16 expressions at native pixel size.
    for block in blocks:
        sheet=Image.new('RGB',(1040,8*158),'#eeeeee');d=ImageDraw.Draw(sheet)
        for ci,cond in enumerate(CONDITIONS):
            for si in range(4):
                x=(si%2)*520;y=(ci*2+si//2)*158
                a=cache[(block['id'],cond,si)][0]
                sheet.paste(Image.fromarray(a),(x,y+25))
                d.text((x+5,y+3),f"{block['id']} {cond} e{si+1}",font=ff,fill='black')
        sheet.save(OUT/f"data/contact-{block['id']}.png")
    print(json.dumps({k:v for k,v in check.items() if k not in ['baseline_reproduction','input_controls']},ensure_ascii=False))

if __name__=='__main__':main()
