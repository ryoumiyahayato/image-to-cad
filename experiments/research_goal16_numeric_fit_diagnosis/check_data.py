"""Final data readback: pixel closure, label identity, contrast purity, exposure and coverage."""
import time
from collections import defaultdict,Counter
import numpy as np
from PIL import Image
from common import *

def main():
    start=time.perf_counter();data=OUT/'data';images=read(data/'images.json');rows=read(data/'pairs.json');groups=read(data/'semantic-groups.json');errors=[]
    oldimages=read(OLD_OUT/'data/images.json')
    oldunique={r['pixel_equivalence_id']:r for r in oldimages}
    aa=[np.array(Image.open(data/r['image'])) for r in images]
    aa += [np.array(Image.open(OLD_OUT/'data'/r['image'])) for r in oldunique.values()]
    _,first,inv=np.unique(np.stack(aa).reshape(len(aa),-1),axis=0,return_index=True,return_inverse=True)
    final_index={r['image']:int(inv[i]) for i,r in enumerate(images)};imap={r['image']:r for r in images}
    bins=defaultdict(list)
    for i,r in enumerate(images):bins[int(inv[i])].append(r)
    for bb in bins.values():
        if len({r['split'] for r in bb})!=1 or len({r['component'] for r in bb})!=1:errors.append(['equal pixels not grouped'])
    oldpixelset=set(int(v) for v in inv[len(images):]);exposure=[r['id'] for r in images if final_index[r['image']] in oldpixelset]
    seen={};expressions=defaultdict(set);full=defaultdict(list)
    for r in rows:
        im=imap[r['image']]
        if (r['split'],r['component'])!=(im['split'],im['component']):errors.append(['pair image split',r['id']])
        a=label(parts(im['construction_only']),r['candidate_raw'],im['unknown_roles'],r['scope'])
        if a!=r['annotation']:errors.append(['label recompute',r['id']])
        key=(final_index[r['image']],r['candidate_raw'],r['scope'])
        if key in seen and seen[key]!=a['parts']:errors.append(['same input conflicting label',r['id']])
        seen[key]=a['parts'];expressions[r['candidate_raw']].add(r['split'])
        if r['condition']=='complete':full[(r['group'],r['appearance'],r['scope'])].append(r)
    for key,b in full.items():
        if len(b)!=4 or {(r['source_index'],r['candidate_index']) for r in b}!={(0,0),(0,1),(1,0),(1,1)}:errors.append(['cross missing',key])
        if key[2]=='NUMBER_UNIT_CONTEXT':
            for r in b:
                if r['annotation']['overall']!=('CONSISTENT' if r['source_index']==r['candidate_index'] else 'CONTRADICTION'):errors.append(['cross labels',r['id']])
    if any(len(s)>1 for s in expressions.values()):errors.append(['expression split overlap'])
    oldpairs=read(OLD_OUT/'data/pairs.json');oldexpressions={r['candidate_raw'] for r in oldpairs}
    if oldexpressions.intersection(expressions):errors.append(['old expression reused'])
    # Preserve explicit single-role meaning; structural mechanisms are separately described.
    expected_single={'fraction_numerator':'numerator','fraction_denominator':'denominator','mixed_whole':'whole','unit':'unit','sign':'sign','context':'context'}
    for g in groups:
        if g['mechanism'] in expected_single:
            a,b=map(parts,g['sources']);changed=[r for r in ROLES if a[r]!=b[r]]
            if changed!=[expected_single[g['mechanism']]]:errors.append(['not single role',g['id'],changed])
    cov=read(data/'coverage/coverage.json')
    for s,q in [('train',3),('validation',1),('sealed-test',2)]:
        if read(data/f'{s}.json')!=[r for r in rows if r['split']==s]:errors.append(['split list mismatch',s])
        for mechanism in MECHANISMS:
            if len(cov[s]['mechanisms'][mechanism]['components'])<q:errors.append(['coverage',s,mechanism])
        for role in ROLES:
            for state in ['CONSISTENT','CONTRADICTION']:
                if not cov[s]['role_states'][role].get(state):errors.append(['role state absent',s,role,state])
    diagnostic=read(data/'diagnostic.json');byid={r['id']:r for r in rows}
    if not 32<=len(diagnostic)<=64:errors.append(['diagnostic size'])
    if any(r!=byid[r['id']] or r['split']!='train' for r in diagnostic):errors.append(['diagnostic outside train'])
    # Nuisance comparison does not alter any labels; no inferred hidden answers.
    full_lookup={(r['group'],r['appearance'],r['source_index'],r['candidate_index'],r['scope']):r for r in rows if r['condition']=='complete'}
    for r in rows:
        if r['condition']=='gray_outside':
            twin=full_lookup[(r['group'],r['appearance'],r['source_index'],r['candidate_index'],r['scope'])]
            if r['annotation']!=twin['annotation']:errors.append(['nuisance label changed',r['id']])
    if len(bins)>3000 or len(rows)>12000:errors.append(['budget exceeded'])
    result=dict(utc=utc(),seconds=time.perf_counter()-start,passed=not errors,errors=errors,
      final_distinct_pixels=len(bins),final_image_files=len(images),pairs=len(rows),unique_input_candidate_scope=len(seen),
      original_candidate_strings=len(expressions),goal15_expression_overlap=len(oldexpressions.intersection(expressions)),goal15_pixel_overlap_image_ids=exposure,
      complete_cross_instances_both_scopes=len(full),diagnostic_pairs=len(diagnostic),single_role_mechanisms=expected_single,
      actual_post_merge_coverage={s:{me:len(v['components']) for me,v in c['mechanisms'].items()} for s,c in cov.items()},
      actual_units_by_split={s:c['actual_units'] for s,c in cov.items()},
      visual_review='AI reviewed all 6 contact sheets, 11 mechanisms x complete/nuisance/unit-hidden/numeric-hidden on fixed diagnostic font/layout; no human acceptance claimed',
      no_id_watermark_or_partition_feature=True,pixel_comparison='Whole uint8 pixel rows and direct equality; no hashes',
      limitations=['Only baseline Barlow inline has both backgrounds and nuisance/occlusion. Other fonts/layouts have complete white-background views.',
      'Single visual operations such as moving the decimal or fraction separator affect multiple Goal14 contract roles; these are not reported as single-role contrasts.'])
    sealed=[r for r in rows if r['split']=='sealed-test' and r['condition']=='complete' and r['scope']=='NUMBER_UNIT_CONTEXT']
    ceilings={}
    for factor in ['image','candidate']:
        counts=defaultdict(Counter)
        for r in sealed:
            key=(final_index[r['image']] if factor=='image' else r['candidate_raw'],r['scope']);counts[key][r['annotation']['overall']]+=1
        ceilings[factor]=dict(majority_correct=sum(max(v.values()) for v in counts.values()),pairs=len(sealed),buckets=len(counts))
    write(OUT/'data/sealed-distribution-only.json',dict(utc=utc(),model_inference='NOT_RUN',ceilings=ceilings,
        pairs=len(sealed),image_files=len({r['image'] for r in sealed}),distinct_pixels=len({final_index[r['image']] for r in sealed}),
        appearance_cross_instances=len({(r['group'],r['appearance']) for r in sealed}),semantic_groups=len({r['group'] for r in sealed}),components=len({r['component'] for r in sealed})))
    write(OUT/'data-readback-check.json',result);print(json.dumps(result));assert not errors

if __name__=='__main__':main()
