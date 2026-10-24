"""New original scenes only. Reuses Goal14 renderer, fixes appearance and split coupling."""
import importlib.util
import itertools
import random
import time
from collections import Counter,defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from fontTools.ttLib import TTFont
from common import *

module=importlib.util.spec_from_file_location('goal14_renderer',G14/'generate.py')
old=importlib.util.module_from_spec(module);module.loader.exec_module(old)

def semantic_groups():
    S=old.spec;F=lambda n,d,**kw:S('fraction',n=str(n),d=str(d),**kw)
    M=lambda w,n,d,**kw:S('mixed',whole=str(w),n=str(n),d=str(d),**kw)
    I=lambda w,**kw:S('integer',whole=str(w),**kw)
    groups=[]
    for v in range(4):
        q=[2,4,8,6][v];w=v+1
        recipes=[
            ('fraction_integer',I(f'1{q}'),F(1,q)),
            ('fraction_numerator',F(v+2,7),F(v+3,7)),
            ('fraction_denominator',F(v+3,11+2*v),F(v+3,13+2*v)),
            ('mixed_whole',M(w,3,[8,16,32,64][v]),F(3,[8,16,32,64][v])),
            ('mixed_boundary',M(v+2,1,[4,8,16,32][v]),F(f'{v+2}1',[4,8,16,32][v])),
            ('unit',F(v+5,12+2*v),F(v+5,12+2*v,unit='mm')),
            ('decimal_point',S('decimal',whole=f'{v+2}.{v+3}'),I(f'{v+2}{v+3}')),
            ('sign',I(25+11*v,sign='-'),I(25+11*v)),
            ('context',M(w,5,12+2*v,context='DIA. HOLE'),M(w,5,12+2*v,context='(typ.)')),
            ('numeric_equivalence',F([1,3,7,9][v],10),S('decimal',whole=f'0.{[1,3,7,9][v]}')),
            ('unicode_boundary',M(w,1,2,glyph='½'),F(f'{w}1',2)),
        ]
        for mechanism,a,b in recipes:
            groups.append(dict(id=f'{mechanism}-{v}',mechanism=mechanism,variant=v,
                planned_split='train' if v<2 else 'validation' if v==2 else 'sealed-test',sources=[a,b],
                candidates=[old.spelling(a),old.spelling(b)]))
    return groups

def build():
    started=time.perf_counter();data=OUT/'data'
    if (data/'images.json').exists():raise RuntimeError('Preserve previous data; do not overwrite a frozen dataset')
    data.mkdir(parents=True,exist_ok=True);(data/'images').mkdir(exist_ok=True)
    ff=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts'
    fonts=[('barlow',ff/'barlow/Barlow-Regular.ttf'),('ibmplexmono',ff/'ibmplexmono/IBMPlexMono-Regular.ttf'),
           ('sourceserif4',ff/'sourceserif4/SourceSerif4[opsz,wght].ttf')]
    layouts=['inline','stacked','raised'];groups=semantic_groups()
    required_chars=set(''.join(old.spelling(s) for g in groups for s in g['sources']))
    font_checks=[]
    for name,path in fonts:
        tt=TTFont(path);cmap=tt.getBestCmap();missing=sorted(c for c in required_chars if ord(c) not in cmap);tt.close()
        assert not missing,(name,missing)
        assert 'SIL OPEN FONT LICENSE' in (path.parent/'OFL.txt').read_text(encoding='utf8')
        font_checks.append(dict(name=name,path=str(path.relative_to(ROOT)),missing=missing,license='SIL OFL 1.1'))
    # Each font gets two layouts; every layout gets two fonts. Both paper conditions for every pair.
    appearances=[(f,l,b) for f in range(3) for l in (f,(f+1)%3) for b in (0,1)]
    jobs=[]
    for g in groups:
        for source_index,s in enumerate(g['sources']):
            for f,l,b in appearances:
                modes=['complete']
                # Same three extra conditions for each font; background alternates across semantic groups.
                if l==f and b==g['variant']%2:modes+=['gray_outside','unit_hidden','numeric_hidden']
                for mode in modes:jobs.append((g,source_index,s,f,l,b,mode))
    random.Random(SEED).shuffle(jobs)
    images=[];pairs=[];arrays=[];validation_errors=[]
    prior_dir=OUT/'data-attempt1'
    prior={r['id']:r for r in read(prior_dir/'images.json')} if prior_dir.exists() else {}
    for index,(g,source_index,s,f,l,b,mode) in enumerate(jobs):
        # Repair at most 132 numeric views (528 new pairs), reuse other 1,584 images verbatim.
        # Total constructed pairs including rejected first-attempt numeric views remains 7,920.
        if prior and mode=='numeric_hidden' and source_index==1:continue
        if prior and mode!='numeric_hidden':
            saved=prior[f'i{index:04d}'];pixels=np.array(Image.open(prior_dir/saved['image']))
            glyphs=saved['glyphs'];unknown=saved['unknown_roles'];rect=saved['panel']
        else:
            pixels,glyphs,unknown,rect,found=render_view(s,fonts[f][1],layouts[l],b,mode)
            validation_errors.extend([index,*item] for item in found)
        identity=f'i{index:04d}';rel=f'images/{identity}.png'
        Image.fromarray(pixels).save(data/rel);arrays.append(pixels)
        image=dict(id=identity,image=rel,group=g['id'],source_index=source_index,mechanism=g['mechanism'],
                   font=fonts[f][0],layout=layouts[l],background=b,mode=mode,appearance=f'{f}-{l}-{b}',
                   unknown_roles=unknown,panel=rect,glyphs=glyphs,construction_only=s,
                   planned_split=g['planned_split'],visible_parts={r:None if r in unknown else parts(s)[r] for r in ROLES})
        images.append(image)
        for ci,candidate in enumerate(g['candidates']):
            for scope in SCOPES:
                annotation=label(parts(s),candidate,unknown,scope)
                pairs.append(dict(id='',image=rel,candidate_raw=candidate,scope=scope,group=g['id'],
                    source_index=source_index,candidate_index=ci,mechanism=g['mechanism'],
                    condition=mode,appearance=image['appearance'],annotation=annotation))
    return finish(data,groups,images,pairs,arrays,font_checks,started,validation_errors,fonts)

def render_view(s,font_path,layout,background,mode):
        validation_errors=[]
        pixels,masks,glyphs,bg=old.render(s,font_path,layout,background)
        before=masks.copy();unknown=[];rect=None
        if mode=='gray_outside':rect=[350,16,490,96]
        if mode=='unit_hidden':
            left=min(x['bbox'][0] for x in glyphs if 'unit' in x['roles'])-1
            rect=[left,0,512,128];unknown=['unit','context']
        if mode=='numeric_hidden':
            if s.get('numerator'):
                targets=[g for g in glyphs if 'denominator' in g['roles']]
                unknown=sorted({r for g in targets for r in g['roles']})
            else:
                targets=[g for g in glyphs if 'whole' in g['roles'] and g['char'].isdigit()][-1:]
                unknown=list(ROLES[:5])
            boxes=[g['bbox'] for g in targets]
            rect=[min(z[0] for z in boxes),min(z[1] for z in boxes),max(z[2] for z in boxes),max(z[3] for z in boxes)]
        if rect:
            x0,y0,x1,y1=rect
            touched={r for ma,gl in zip(before,glyphs) if (ma[y0:y1,x0:x1]>0).any() for r in gl['roles']}
            if mode=='gray_outside' and touched:validation_errors.append(['nuisance_overlaps_glyph',sorted(touched)])
            if mode=='unit_hidden' and touched.intersection(ROLES[:6]):validation_errors.append(['unit_panel_overlaps_number',sorted(touched)])
            if mode=='numeric_hidden':
                unknown=sorted(set(unknown)|touched)
                if 'unit' in unknown and s['context'] is None:unknown=sorted(set(unknown)|{'context'})
            bg[y0:y1,x0:x1]=210;bg[y0:y1,x0]=160
            pixels[y0:y1,x0:x1]=bg[y0:y1,x0:x1];masks[:,y0:y1,x0:x1]=0
        for gl,ma,orig in zip(glyphs,masks,before):
            gl['final_bbox']=old.bbox(ma);gl['final_pixels']=int((ma>32).sum());gl['original_pixels']=int((orig>32).sum())
            if mode=='gray_outside' and not np.array_equal(ma,orig):validation_errors.append(['nuisance_changed_ink'])
            if any(r not in unknown for r in gl['roles']) and gl['final_pixels']!=gl['original_pixels']:
                validation_errors.append(['occluded_role_determinate',gl['char'],gl['roles']])
        reconstruct=bg.copy()
        for ma in masks:reconstruct=np.minimum(reconstruct,255-ma)
        if not np.array_equal(pixels,reconstruct):validation_errors.append(['mask_alignment'])
        return pixels,glyphs,unknown,rect,validation_errors

def finish(data,groups,images,pairs,arrays,font_checks,started,validation_errors,fonts):
    # Sort and compare complete raw pixel rows. No computed pixel fingerprints or hashes.
    parent={g['id']:g['id'] for g in groups}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    _,unique,inverse=np.unique(np.stack(arrays).reshape(len(arrays),-1),axis=0,return_index=True,return_inverse=True)
    pixel_ids=[int(unique[k]) for k in inverse];equivalences=[]
    for i,match in enumerate(pixel_ids):
        if i!=match:
            assert np.array_equal(arrays[i],arrays[match])
            union(images[i]['group'],images[match]['group']);equivalences.append([i,match])
    priority={'train':0,'validation':1,'sealed-test':2}
    components=defaultdict(list)
    for g in groups:components[find(g['id'])].append(g)
    split={k:max((g['planned_split'] for g in v),key=lambda s:priority[s]) for k,v in components.items()}
    by_image={r['image']:r for r in images};pixel_lookup={r['image']:pixel_ids[i] for i,r in enumerate(images)}
    seen={};conflicts=[]
    for p in pairs:
        key=(pixel_lookup[p['image']],p['candidate_raw'],p['scope'])
        state=p['annotation']['parts']
        if key in seen and seen[key]!=state:conflicts.append([p['image'],p['candidate_raw'],p['scope']])
        seen[key]=state
        p['component']=find(p['group']);p['split']=split[p['component']]
        encode_candidate(p['candidate_raw'])
    for i,row in enumerate(images):
        row['pixel_equivalence_id']=f'px{pixel_ids[i]:04d}';row['component']=find(row['group']);row['split']=split[row['component']]
    random.Random(SEED+1).shuffle(pairs)
    for i,p in enumerate(pairs):p['id']=f'p{i:05d}'
    assert len(unique)<=2000 and len(pairs)<=8000
    for expected_split in ('train','validation','sealed-test'):
        if not any(p['split']==expected_split for p in pairs):validation_errors.append(['empty_partition',expected_split])
    if conflicts:validation_errors.append(['identical_input_label_conflicts',conflicts[:20]])
    # An expression cannot leak through a different font, layout, damage condition or contrast family.
    expression_splits=defaultdict(set)
    for g in groups:
        for c in g['candidates']:expression_splits[c].add(split[find(g['id'])])
    for c,sp in expression_splits.items():
        if len(sp)>1:validation_errors.append(['expression_across_splits',c,sorted(sp)])
    # Complete 2x2 contrast groups, including new-pair labels for each swap.
    complete=defaultdict(list)
    for p in pairs:
        if p['condition']=='complete' and p['scope']=='NUMBER_UNIT_CONTEXT':complete[(p['group'],p['appearance'])].append(p)
    for key,rows in complete.items():
        if len(rows)!=4 or {(r['source_index'],r['candidate_index']) for r in rows}!={(0,0),(0,1),(1,0),(1,1)}:
            validation_errors.append(['incomplete_cross',key])
        for r in rows:
            want='CONSISTENT' if r['source_index']==r['candidate_index'] else 'CONTRADICTION'
            if r['annotation']['overall']!=want:validation_errors.append(['unexpected_complete_label',key,r['id']])
    # Actual tables, not assertions that all appearance distributions must be identical.
    coverage=defaultdict(Counter)
    for p in pairs:
        im=by_image[p['image']]
        for field in ['font','layout','background','mode']:
            coverage[(p['split'],field,str(im[field]))][p['annotation']['overall']]+=1
        coverage[(p['split'],'font_layout',im['font']+'/'+im['layout'])][p['annotation']['overall']]+=1
    report=dict(errors=validation_errors,base_scenes=len(groups)*2,semantic_groups=len(groups),merged_components=len(components),
                final_image_files=len(images),distinct_final_pixels=len(unique),pairs=len(pairs),candidate_strings=len(expression_splits),
                merged_groups={k:[g['id'] for g in v] for k,v in components.items() if len(v)>1},
                image_splits=dict(Counter(r['split'] for r in images)),pair_splits=dict(Counter(p['split'] for p in pairs)),
                group_splits=dict(Counter(split.values())),overall=dict(Counter(p['annotation']['overall'] for p in pairs)),
                jointly_contradictory_unknown=sum(p['annotation']['has_contradiction'] and p['annotation']['has_insufficient'] for p in pairs),
                expression_split_overlap=[],pixel_conflicts=conflicts,font_checks=font_checks,
                role_states={role:dict(Counter(p['annotation']['parts'][role] for p in pairs)) for role in ROLES},
                complete_cross_groups=len(complete),coverage=[dict(split=k[0],factor=k[1],value=k[2],labels=dict(v)) for k,v in coverage.items()],
                construction_comparisons='Complete raw uint8 pixel-row sorting plus elementwise equality; no fingerprints',
                seconds=time.perf_counter()-started,
                not_covered=['exceeding prefix','explicit plus sign','Unicode quarter and three-quarter','blur/noise/rotation','real data'])
    write(data/'images.json',images);write(data/'pairs.json',pairs);write(data/'semantic-groups.json',groups)
    write(data/'data-check.json',report)
    for s in ['train','validation','sealed-test']:
        write(data/f'{s}.json',[p for p in pairs if p['split']==s])
    write(data/'input-locator.json',[dict(id=p['id'],**feature_record(p)) for p in pairs])
    # Original final rendering representatives across all mechanisms/visibility conditions.
    viewfont=ImageFont.truetype(str(fonts[0][1]),17)
    reps=[]
    for mechanism in dict.fromkeys(g['mechanism'] for g in groups):
        for mode in ['complete','gray_outside','unit_hidden','numeric_hidden']:
            reps.append(next(r for r in images if r['mechanism']==mechanism and r['mode']==mode and r['source_index']==0))
    for page in range((len(reps)+7)//8):
        sheet=Image.new('RGB',(1040,800),'#eeeeee');draw=ImageDraw.Draw(sheet)
        for j,row in enumerate(reps[page*8:page*8+8]):
            x=j%2*520;y=j//2*200;sheet.paste(Image.open(data/row['image']).convert('RGB'),(x,y+25))
            draw.text((x+3,y+3),f"{row['id']} {row['mechanism']} {row['font']}/{row['layout']}",font=viewfont,fill='black')
            draw.text((x+3,y+156),row['mode']+' | unknown: '+','.join(row['unknown_roles']),font=viewfont,fill='black')
        sheet.save(data/f'contact-{page+1}.png')
    print(json.dumps({k:report[k] for k in ['errors','base_scenes','semantic_groups','merged_components','final_image_files','distinct_final_pixels','pairs','candidate_strings','group_splits','pair_splits','jointly_contradictory_unknown','seconds']}),flush=True)
    if validation_errors:raise SystemExit(1)

if __name__=='__main__':build()
