"""Read back final pixels, labels and splits; count the rejected construction too. No fit."""
from collections import defaultdict,Counter
from datetime import datetime,timezone
import numpy as np
from PIL import Image
from common import *

def main():
    data=OUT/'data';images=read(data/'images.json');pairs=read(data/'pairs.json');previous=read(OUT/'data-attempt1/images.json')
    by={r['image']:r for r in images};old={r['id']:r for r in previous};errors=[];changed=[]
    arrays=[np.array(Image.open(data/r['image'])) for r in images]
    for i,r in enumerate(images):
        if not np.array_equal(arrays[i],np.array(Image.open(OUT/'data-attempt1'/old[r['id']]['image']))):changed.append(r['id'])
    # Old numeric views are the only pixels not reused in the final dataset.
    retired=[r for r in previous if r['mode']=='numeric_hidden']
    all_arrays=arrays+[np.array(Image.open(OUT/'data-attempt1'/r['image'])) for r in retired]
    _,first,inverse=np.unique(np.stack(all_arrays).reshape(len(all_arrays),-1),axis=0,return_index=True,return_inverse=True)
    actual_pixels={r['image']:int(inverse[i]) for i,r in enumerate(images)}
    bins=defaultdict(list)
    for i,r in enumerate(images):bins[int(inverse[i])].append(r)
    for rows in bins.values():
        if len({r['split'] for r in rows})!=1:errors.append('cross-split equal pixels')
        if len({r['component'] for r in rows})!=1:errors.append('cross-component equal pixels')
    seen={};scope_counts=Counter();expression_splits=defaultdict(set)
    for p in pairs:
        im=by[p['image']];scope_counts[p['scope']]+=1
        if p['split']!=im['split'] or p['component']!=im['component']:errors.append('pair split mismatch')
        expected=label(parts(im['construction_only']),p['candidate_raw'],im['unknown_roles'],p['scope'])
        if expected!=p['annotation']:errors.append('label reconstruction mismatch '+p['id'])
        k=(actual_pixels[p['image']],p['candidate_raw'],p['scope'])
        if k in seen and seen[k]!=p['annotation']:errors.append('identical input different labels')
        seen[k]=p['annotation'];expression_splits[p['candidate_raw']].add(p['split'])
        if set(feature_record(p))!={'image','candidate_raw','scope'}:errors.append('adapter fields')
        encode_candidate(p['candidate_raw'])
    if any(len(v)>1 for v in expression_splits.values()):errors.append('expression leakage')
    for split in ['train','validation','sealed-test']:
        if read(data/f'{split}.json')!=[p for p in pairs if p['split']==split]:errors.append('split list mismatch')
        if not any(p['split']==split for p in pairs):errors.append('empty '+split)
    # All nuisance pairs must match complete-input labels exactly.
    full={(p['group'],p['source_index'],p['candidate_index'],p['appearance'],p['scope']):p for p in pairs if p['condition']=='complete'}
    for p in pairs:
        if p['condition']=='gray_outside':
            q=full[(p['group'],p['source_index'],p['candidate_index'],p['appearance'],p['scope'])]
            if p['annotation']!=q['annotation']:errors.append('nuisance label changed')
    cumulative_pairs=len(read(OUT/'data-attempt1/pairs.json'))+len(changed)*4
    if len(first)>2000 or cumulative_pairs>8000:errors.append('cumulative construction budget')
    result=dict(utc=datetime.now(timezone.utc).isoformat(),errors=errors,checks_passed=not errors,
        final_distinct_pixels=len(bins),cumulative_distinct_pixels=len(first),cumulative_constructed_pairs=cumulative_pairs,
        repaired_image_count=len(changed),reused_image_count=len(images)-len(changed),final_unique_input_candidate_scope_triplets=len(seen),
        final_pairs=len(pairs),final_files=len(images),scope_counts=dict(scope_counts),
        pixels_compared='Complete raw uint8 arrays with sorting and equality. No hashes.',
        input_adapter_fields=['pixels loaded by path','candidate_raw','scope'],
        visual_review=dict(status='AI_REVIEWED',pages=[f'data/contact-{i}.png' for i in range(1,7)],
            finding='All 11 mechanism families reviewed across complete/nuisance/unit occlusion/numeric occlusion representatives; glyph boundaries and retained quotes/signs inspected.',human_review='NOT_RUN'),
        rejected_first_attempt='Whole-prefix masking merged 44 semantic groups into 3 components and left no train partition. No fitting occurred. Retained for diagnosis only.')
    write(OUT/'data-readback-check.json',result);print(json.dumps(result));assert not errors

if __name__=='__main__':main()
