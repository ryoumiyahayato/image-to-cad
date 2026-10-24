"""Local checks requested by Goal14. Not a production gate or recognition evaluation."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import jsonschema
from PIL import Image, ImageDraw, ImageFont
from task import OUT, ROOT, ROLES, PAIR_SCHEMA, read, write, aggregate, model_input, load_model_input

def main(out):
    pairs=read(out/'pairs.json');images=read(out/'images.json');by_image=defaultdict(list);errors=[]
    for p in pairs:
        jsonschema.validate(p,PAIR_SCHEMA);by_image[p['image']].append(p)
        a=p['annotation'];agg=aggregate(a['parts'],a['scope_status']=='SUPPORTED')
        if any(a[k]!=agg[k] for k in agg):errors.append(['aggregation',p['pair_id']])
        if set(model_input(p))!={'image','candidate_raw','scope'}:errors.append(['input_projection',p['pair_id']])
        loaded=load_model_input(p,out)
        if set(loaded)!={'pixels','candidate_raw','scope'} or loaded['pixels'].size!=(512,128):errors.append(['model_adapter',p['pair_id']])
    write(out/'model-inputs.json',[model_input(p) for p in pairs])
    groups=defaultdict(set);twins=defaultdict(list);visible_roles=Counter();views=[]
    for row in images:
        pix=np.array(Image.open(out/row['image']).convert('L'))
        z=np.load(out/row['mask_file']);masks=z['masks'];bg=z['background'];reconstructed=bg.copy()
        for mask in masks:reconstructed=np.minimum(reconstructed,255-mask)
        if not np.array_equal(pix,reconstructed):errors.append(['pixel_mask_alignment',row['image']])
        for r in ROLES:
            if r in row['unknown_roles'] or r=='relation':continue
            if row['visible_parts'][r] is not None:
                count=sum(g['visible_pixels'] for g in row['glyphs'] if r in g['roles'])
                if count==0:errors.append(['missing_visible_role',row['image'],r])
                visible_roles[r]+=1
        for g,mask in zip(row['glyphs'],masks):
            yy,xx=np.where(mask>32);b=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)] if len(xx) else None
            if b!=g['final_bbox'] or len(xx)!=g['visible_pixels']:errors.append(['glyph_box',row['image']])
        if row['construction_only']['expression']['glyph']:
            glyph=[g for g in row['glyphs'] if g['char']=='½']
            if len(glyph)!=1 or set(glyph[0]['roles'])!={'numerator','denominator','relation'}:errors.append(['vulgar_glyph_mapping',row['image']])
        groups[row['group']].add(row['proposed_partition'])
        if row['mode']=='hidden_denominator':twins[row['group']].append(row)
        if len(Image.open(out/row['image']).size)!=2 or Image.open(out/row['image']).size!=(512,128):errors.append(['dimensions',row['image']])
    for g,splits in groups.items():
        if len(splits)!=1:errors.append(['group_leak',g])
    planned_differences={
        'separator14':{'whole','numerator','denominator','relation'},'separator18':{'whole','numerator','denominator','relation'},
        'mixed_whole':{'whole','relation'},'mixed_boundary':{'whole','numerator','relation'},
        'denominator':{'denominator'},'unit':{'unit'},'context':{'context'},
        'decimal':{'whole','relation','decimal_point'},'sign':{'sign'},
        'numeric_equivalence':{'whole','numerator','denominator','relation','decimal_point'},
        'unicode':{'whole','numerator','relation'}}
    for row in images:
        if row['mode']!='complete':continue
        for p in by_image[row['image']]:
            actual={r for r,s in p['annotation']['parts'].items() if s=='CONTRADICTION'}
            if actual and actual!=planned_differences[row['group'].split(':')[1]]:errors.append(['unplanned_candidate_change',p['pair_id'],sorted(actual)])
    for group,rows in twins.items():
        if len(rows)!=2:errors.append(['twin_count',group]);continue
        a,b=rows
        if not np.array_equal(np.array(Image.open(out/a['image'])),np.array(Image.open(out/b['image']))):errors.append(['hidden_twins_pixels_differ',group])
        aa={p['candidate_raw']:p['annotation'] for p in by_image[a['image']]};bb={p['candidate_raw']:p['annotation'] for p in by_image[b['image']]}
        if aa!=bb:errors.append(['unobservable_truth_label_conflict',group])
    arrays=[np.asarray(Image.open(out/r['image'])) for r in images]
    identical_pairs=0;unique_observations=[]
    for i,a in enumerate(images):
        matches=[]
        for j in range(i):
            b=images[j]
            if not np.array_equal(arrays[i],arrays[j]):continue
            matches.append(j)
            identical_pairs+=1
            if a['proposed_partition']!=b['proposed_partition']:errors.append(['identical_pixels_across_partitions',a['image'],b['image']])
            if a['unknown_roles']!=b['unknown_roles']:errors.append(['pixel_identical_visibility_conflict',a['image'],b['image']])
            pa={p['candidate_raw']:p['annotation'] for p in by_image[a['image']]}
            pb={p['candidate_raw']:p['annotation'] for p in by_image[b['image']]}
            for candidate in pa.keys() & pb.keys():
                if pa[candidate]!=pb[candidate]:errors.append(['pixel_identical_candidate_label_conflict',a['image'],b['image'],candidate])
        if not matches:unique_observations.append(i)
    shortcut_counts={}
    for field in ('font','layout','background','mode'):
        buckets=defaultdict(Counter)
        for row in images:
            for p in by_image[row['image']]:buckets[str(row[field])][p['annotation']['overall']]+=1
        shortcut_counts[field]={k:dict(v) for k,v in buckets.items()}
    complete=[p for r in images if r['mode']=='complete' for p in by_image[r['image']]]
    cand=defaultdict(Counter);img=defaultdict(Counter)
    for p in complete:
        cand[p['candidate_raw']][p['annotation']['overall']]+=1;img[p['image']][p['annotation']['overall']]+=1
    # Dataset-only majority ceilings, not trained or inferred baseline performance.
    ceilings={name:sum(max(c.values()) for c in bucket.values())/len(complete) for name,bucket in [('candidate_only',cand),('image_only',img)]}
    crossed_candidates=sum(len(c)>1 for c in cand.values())
    if not all(set(c)=={'CONSISTENT','CONTRADICTION'} for c in img.values()):errors.append(['incomplete_image_crossing'])
    if not all(set(c)=={'CONSISTENT','CONTRADICTION'} for c in cand.values()):errors.append(['incomplete_candidate_crossing'])
    # Overlay every final input; separate files from model inputs so annotations cannot enter training by accident.
    overlaydir=out/'overlays';overlaydir.mkdir(exist_ok=True)
    colors={'whole':'#12834d','numerator':'#175ee0','denominator':'#b035cf','relation':'#ed6900','unit':'#d02020','context':'#865300','sign':'#009999','decimal_point':'#009999'}
    ui=ImageFont.truetype(str(ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/barlow/Barlow-Regular.ttf'),16)
    for row in images:
        im=Image.open(out/row['image']).convert('RGB');d=ImageDraw.Draw(im)
        for g in row['glyphs']:
            if g['final_bbox']:
                b=g['final_bbox'];d.rectangle((b[0],b[1],b[2]-1,b[3]-1),outline=colors[g['roles'][0]],width=1)
        im.save(overlaydir/Path(row['image']).name)
    representatives=[]
    for family in ('barlow','ibmplexmono','sourceserif4'):
        for group in ('separator18','mixed_whole','denominator','unit','decimal','unicode'):
            representatives.append(next(r for r in images if r['font']==family and r['group'].endswith(':'+group) and r['mode']=='complete' and r['source_object'].endswith(':0')))
        for mode in ('hidden_denominator','unit_crop','context_occluded','shifted'):
            representatives.append(next(r for r in images if r['font']==family and r['mode']==mode))
    for page in range(3):
        selected=representatives[page*10:(page+1)*10];sheet=Image.new('RGB',(1040,1050),'#f4f4f4');d=ImageDraw.Draw(sheet)
        for i,row in enumerate(selected):
            x=(i%2)*520;y=(i//2)*210
            sheet.paste(Image.open(out/row['image']).convert('RGB'),(x,y+25))
            d.text((x+5,y+3),f"{Path(row['image']).stem} | {row['layout']} | {row['mode']}",font=ui,fill='black')
            for k,p in enumerate(by_image[row['image']][:3]):
                a=p['annotation'];d.text((x+5,y+151+k*18),f"{p['candidate_raw']} => {a['overall']} {'+ unknown' if a['has_insufficient'] else ''}",font=ui,fill='black')
        sheet.save(out/f'contact-{page+1}.png')
    result=dict(images=len(images),pairs=len(pairs),overall_counts=dict(Counter(p['annotation']['overall'] for p in pairs)),
                has_insufficient=sum(p['annotation']['has_insufficient'] for p in pairs),
                contradiction_and_insufficient=sum(p['annotation']['has_insufficient'] and p['annotation']['has_contradiction'] for p in pairs),
                visible_role_image_counts=dict(visible_roles),complete_crossed_images=len(img),crossed_candidate_strings=crossed_candidates,
                complete_subset_single_input_majority_ceilings=ceilings,hidden_twin_groups=len(twins),groups=len(groups),
                partition_counts=dict(Counter(r['proposed_partition'] for r in images)),
                identical_pixel_image_pairs=identical_pairs,
                distinct_final_pixel_inputs=len(unique_observations),shortcut_label_counts=shortcut_counts,
                split_family='font family; all contrast groups and duplicate rendered inputs of that font remain together',
                checked='schema, aggregation, mask/pixel alignment, visible roles, planned mutations, crossed pairs, hidden twins, all identical pixels, group containment, exported input allowlist',
                limitations=['Masks and generation share layout logic; final human/AI visual inspection remains separate.',
                             'Damage/background/font partition confounding is not ruled out by these checks.',
                             'Identifier randomization is not proof against all shortcuts. No training occurred.'],
                visual_review_files=[f'contact-{i}.png' for i in (1,2,3)],errors=errors)
    write(out/'validation.json',result);print(__import__('json').dumps(result,ensure_ascii=False))
    if errors:raise SystemExit(1)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=OUT/'synthetic-v5');main(ap.parse_args().out)
