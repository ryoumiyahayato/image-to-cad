"""New independent original combinations. Establish components before assigning partitions."""
import random,time,csv
from collections import defaultdict,Counter
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from fontTools.ttLib import TTFont
from common import *
from coverage import audit
renderer=load_module('goal15_render_only',G15/'prepare_data.py')
old=renderer.old

def recipes():
    rng=random.Random(SEED+16);groups=[];used={r['candidate_raw'] for r in read(OLD_OUT/'data/pairs.json')}
    nums=list(range(11,99));rng.shuffle(nums);cursor=0
    for mechanism in MECHANISMS:
        for j in range(8):
            # Values are expression content, never IDs or split markers. All partitions assigned later.
            while True:
                n=nums[cursor%len(nums)];cursor+=1;d=rng.randrange(21,98);w=rng.randrange(6,24)
                F=lambda a,b,**kw:old.spec('fraction',n=str(a),d=str(b),**kw)
                M=lambda a,b,c,**kw:old.spec('mixed',whole=str(a),n=str(b),d=str(c),**kw)
                I=lambda a,**kw:old.spec('integer',whole=str(a),**kw)
                if mechanism=='fraction_integer':a,b=I(f'{n}{d}'),F(n,d)
                elif mechanism=='fraction_numerator':a,b=F(n,d),F(n+101,d)
                elif mechanism=='fraction_denominator':a,b=F(n,d),F(n,d+101)
                elif mechanism=='mixed_whole':a,b=M(w,n,d),M(w+31,n,d)
                elif mechanism=='mixed_boundary':a,b=M(w,n,d),F(f'{w}{n}',d)
                elif mechanism=='unit':a,b=F(n,d),F(n,d,unit='mm')
                elif mechanism=='decimal_point':a,b=old.spec('decimal',whole=f'{n}.{d}'),I(f'{n}{d}')
                elif mechanism=='sign':a,b=I(n*10+j,sign='-'),I(n*10+j)
                elif mechanism=='context':a,b=M(w,n,d,context='DIA. HOLE'),M(w,n,d,context='(typ.)')
                elif mechanism=='numeric_equivalence':a,b=F(n,100),old.spec('decimal',whole=f'0.{n:02d}')
                else:
                    w=15+j;a,b=M(w,1,2,glyph='½'),F(f'{w}1',2)
                candidates=[old.spelling(a),old.spelling(b)]
                if not set(candidates)&used:break
            used.update(candidates)
            groups.append(dict(id=f'{mechanism}-{j}',mechanism=mechanism,sources=[a,b],candidates=candidates,
                               origin='Goal16 new original expression combinations; no Goal15 rows reused'))
    return groups

def main():
    start=time.perf_counter();data=OUT/'data';assert not (data/'pairs.json').exists()
    (data/'images').mkdir(parents=True,exist_ok=True)
    fonts=[('barlow','Barlow-Regular.ttf'),('ibmplexmono','IBMPlexMono-Regular.ttf'),('sourceserif4','SourceSerif4[opsz,wght].ttf')]
    paths=[ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts'/f/n for f,n in fonts]
    groups=recipes();font_checks=[]
    needed=set(''.join(c for g in groups for c in g['candidates']))
    for (f,n),path in zip(fonts,paths):
        tt=TTFont(path);missing=sorted(c for c in needed if ord(c) not in tt.getBestCmap());tt.close();assert not missing
        assert 'SIL OPEN FONT LICENSE' in (path.parent/'OFL.txt').read_text(encoding='utf8')
        font_checks.append(dict(font=f,missing=missing,license='SIL OFL 1.1'))
    layouts=['inline','stacked','raised']
    appearances=[(f,l,0) for f in range(3) for l in [f,(f+1)%3]]+[(0,0,1)]
    jobs=[]
    for g in groups:
        for si,s in enumerate(g['sources']):
            for f,l,b in appearances:
                modes=['complete']
                if (f,l,b)==(0,0,0):modes+=['gray_outside','unit_hidden']+(['numeric_hidden'] if si==0 else [])
                for mode in modes:jobs.append((g,si,s,f,l,b,mode))
    random.Random(SEED+16).shuffle(jobs);images=[];pairs=[];arrays=[];errors=[]
    for i,(g,si,s,f,l,b,mode) in enumerate(jobs):
        pixels,glyphs,unknown,rect,err=renderer.render_view(s,paths[f],layouts[l],b,mode)
        errors.extend([i,*x] for x in err);identity=f'i{i:04d}';rel=f'images/{identity}.png';Image.fromarray(pixels).save(data/rel);arrays.append(pixels)
        images.append(dict(id=identity,image=rel,group=g['id'],source_index=si,mechanism=g['mechanism'],font=fonts[f][0],layout=layouts[l],background=b,
             appearance=f'{f}-{l}-{b}',mode=mode,unknown_roles=unknown,panel=rect,glyphs=glyphs,construction_only=s))
        for ci,candidate in enumerate(g['candidates']):
            for scope in SCOPES:
                pairs.append(dict(id='',image=rel,candidate_raw=candidate,scope=scope,group=g['id'],source_index=si,candidate_index=ci,
                    mechanism=g['mechanism'],condition=mode,appearance=f'{f}-{l}-{b}',annotation=label(parts(s),candidate,unknown,scope)))
    parent={g['id']:g['id'] for g in groups}
    def find(g):
        while parent[g]!=g:parent[g]=parent[parent[g]];g=parent[g]
        return g
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    _,idx,inv=np.unique(np.stack(arrays).reshape(len(arrays),-1),axis=0,return_index=True,return_inverse=True)
    for i,r in enumerate(images):
        match=int(idx[inv[i]]);assert np.array_equal(arrays[i],arrays[match]);union(r['group'],images[match]['group']);r['pixel_equivalence_id']=f'px{match:04d}'
    components=defaultdict(list)
    for g in groups:components[find(g['id'])].append(g)
    # Deterministic quota allocation AFTER actual exact-pixel closure, with multi-mechanism components handled jointly.
    labels={k:set(g['mechanism'] for g in gs) for k,gs in components.items()}
    minimum={'train':3,'validation':1,'sealed-test':2};assignment={};rng=random.Random(SEED+160);order=list(components);rng.shuffle(order)
    # All components allocated together; no promotion of conflicts into held-out partitions.
    def solve(index,counts):
        if index==len(order):return all(counts[s][me]>=q for s,q in minimum.items() for me in MECHANISMS)
        remaining=order[index:]
        for me in MECHANISMS:
            needed=sum(max(0,q-counts[s][me]) for s,q in minimum.items())
            if sum(me in labels[k] for k in remaining)<needed:return False
        k=order[index]
        choices=sorted(minimum,key=lambda s:sum(max(0,minimum[s]-counts[s][me]) for me in labels[k]),reverse=True)
        for s in choices:
            assignment[k]=s
            for me in labels[k]:counts[s][me]+=1
            if solve(index+1,counts):return True
            for me in labels[k]:counts[s][me]-=1
        assignment.pop(k,None);return False
    assert solve(0,{s:Counter() for s in minimum}),'Coverage cannot be allocated after component closure; no fit'
    imap={r['image']:r for r in images};seen={};expression_splits=defaultdict(set)
    for r in images:r['component']=find(r['group']);r['split']=assignment[r['component']]
    for p in pairs:
        im=imap[p['image']];p['component']=im['component'];p['split']=im['split'];encode_candidate(p['candidate_raw'])
        k=(im['pixel_equivalence_id'],p['candidate_raw'],p['scope'])
        if k in seen and seen[k]!=p['annotation']['parts']:errors.append(['identical-input-label-conflict',p['group']])
        seen[k]=p['annotation']['parts'];expression_splits[p['candidate_raw']].add(p['split'])
    if any(len(s)>1 for s in expression_splits.values()):errors.append(['expression leakage'])
    assert len(idx)<=3000 and len(pairs)<=12000
    random.Random(SEED+161).shuffle(pairs)
    for i,p in enumerate(pairs):p['id']=f'p{i:05d}'
    write(data/'images.json',images);write(data/'pairs.json',pairs);write(data/'semantic-groups.json',groups)
    for s in minimum:write(data/f'{s}.json',[p for p in pairs if p['split']==s])
    cov=audit(pairs,groups,data/'coverage')
    for s,q in minimum.items():
        for me in MECHANISMS:
            if len(cov[s]['mechanisms'][me]['components'])<q:errors.append(['coverage',s,me])
        for role in ROLES:
            for state in ['CONSISTENT','CONTRADICTION']:
                if not cov[s]['role_states'][role].get(state):errors.append(['missing role supervision',s,role,state])
    old_candidates={r['candidate_raw'] for r in read(OLD_OUT/'data/pairs.json')}
    assert not old_candidates.intersection(expression_splits)
    diagnostic=[];selected_groups={}
    for me in MECHANISMS:
        gid=sorted({p['group'] for p in pairs if p['split']=='train' and p['mechanism']==me})[0];selected_groups[me]=gid
        diagnostic += [p for p in pairs if p['group']==gid and p['appearance']=='0-0-0' and p['condition']=='complete' and p['scope']=='NUMBER_UNIT_CONTEXT']
    diagnostic += [p for p in pairs if p['group']==selected_groups['fraction_numerator'] and p['appearance']=='0-0-0' and p['condition']=='unit_hidden' and p['scope']=='NUMBER_UNIT_CONTEXT']
    diagnostic += [p for p in pairs if p['group']==selected_groups['context'] and p['appearance']=='0-0-0' and p['condition']=='complete' and p['scope']=='NUMBER_UNIT']
    diagnostic += [p for p in pairs if p['group'] in [selected_groups['fraction_numerator'],selected_groups['mixed_whole']] and p['appearance']=='0-0-0' and p['condition']=='numeric_hidden' and p['scope']=='NUMBER_UNIT_CONTEXT']
    assert len(diagnostic)==56 and len({p['id'] for p in diagnostic})==56
    assert any(p['annotation']['has_contradiction'] and p['annotation']['has_insufficient'] for p in diagnostic)
    write(data/'diagnostic.json',diagnostic)
    reps=[]
    for me in MECHANISMS:
        for mode in ['complete','gray_outside','unit_hidden','numeric_hidden']:
            reps.append(next(r for r in images if r['group']==selected_groups[me] and r['source_index']==0 and r['appearance']=='0-0-0' and r['mode']==mode))
    font=ImageFont.truetype(str(paths[0]),16)
    for page in range(6):
        sheet=Image.new('RGB',(1120,800),'#eee');draw=ImageDraw.Draw(sheet)
        for j,im in enumerate(reps[page*8:page*8+8]):
            x=j%2*560;y=j//2*200;sheet.paste(Image.open(data/im['image']).convert('RGB'),(x,y+25))
            draw.text((x+2,y+2),im['id']+' '+im['mechanism']+' '+im['mode'],font=font,fill='black')
            draw.text((x+2,y+155),'unknown: '+','.join(im['unknown_roles']),font=font,fill='black')
        sheet.save(data/f'contact-{page+1}.png')
    result=dict(utc=utc(),seconds=time.perf_counter()-start,errors=errors,base_scenes=len(groups)*2,semantic_groups=len(groups),components=len(components),
      image_files=len(images),distinct_pixels=len(idx),pairs=len(pairs),unique_input_candidate_scope=len(seen),candidate_strings=len(expression_splits),
      component_splits=dict(Counter(assignment.values())),pair_splits=dict(Counter(p['split'] for p in pairs)),
      merged_groups={k:[g['id'] for g in gs] for k,gs in components.items() if len(gs)>1},diagnostic_pairs=len(diagnostic),diagnostic_selected_groups=selected_groups,
      old_expression_overlap=0,font_checks=font_checks,split_method='Exact-pixel components first, then deterministic coverage-constrained assignment; no row promotion',
      original_data_only=True,hashes_computed=False)
    write(data/'data-check.json',result);print(json.dumps(result));assert not errors

if __name__=='__main__':main()
