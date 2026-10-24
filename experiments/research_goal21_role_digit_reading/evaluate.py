"""Score stored raw strings. No model calls and no label-dependent repair."""
import re
import time
from collections import Counter,defaultdict
from common import *
from compare import compare_region
from candidate_contract import parse_candidate

def edits(reference,hypothesis):
    n,m=len(reference),len(hypothesis)
    dp=[[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1):dp[i][0]=i
    for j in range(m+1):dp[0][j]=j
    for i in range(1,n+1):
        for j in range(1,m+1):
            dp[i][j]=min(dp[i-1][j]+1,dp[i][j-1]+1,dp[i-1][j-1]+(reference[i-1]!=hypothesis[j-1]))
    i,j=n,m;c=Counter()
    while i or j:
        if i and j and dp[i][j]==dp[i-1][j-1]+(reference[i-1]!=hypothesis[j-1]):
            if reference[i-1]!=hypothesis[j-1]:c['substitutions']+=1
            i-=1;j-=1
        elif i and dp[i][j]==dp[i-1][j]+1:c['deletions']+=1;i-=1
        else:c['insertions']+=1;j-=1
    return {k:c[k] for k in ('deletions','insertions','substitutions')}

def basic(rows):
    scored=[r for r in rows if r.get('label') is not None]
    total_edits=Counter();error_cases=Counter()
    for r in scored:
        e=edits(r['label'],r['reader_raw']);total_edits.update(e)
        for k,n in e.items():
            if n:error_cases[k]+=1
    return dict(total=len(rows),scorable=len(scored),unscored=len(rows)-len(scored),
        exact=sum(r['reader_raw']==r['label'] for r in scored),
        characters=sum(len(r['label']) for r in scored),edit_counts=dict(total_edits),
        error_case_counts=dict(error_cases),
        cer=sum(total_edits.values())/sum(len(r['label']) for r in scored) if scored else None,
        invalid_raw_format=sum(not bool(re.fullmatch('[0-9]{1,3}',r['reader_raw'])) for r in scored))

def grouped_metrics(rows):
    return dict(overall=basic(rows),by_length={str(n):basic([r for r in rows if r.get('label') is not None and len(r['label'])==n]) for n in (1,2,3)},
        repeated_anywhere=basic([r for r in rows if r.get('label') is not None and len(set(r['label']))<len(r['label'])]),
        adjacent_repeated=basic([r for r in rows if r.get('label') is not None and any(a==b for a,b in zip(r['label'],r['label'][1:]))]))

def unique_crops(rows):
    out={}
    for r in rows:
        if r['crop_id'] in out:assert out[r['crop_id']]['label']==r['label']
        else:out[r['crop_id']]=r
    return list(out.values())

def pairing_diagnostics(rows):
    by=defaultdict(dict)
    for r in rows:by[(r['font'],r['size'])][r['label']]=r
    count=Counter();pairs=[]
    for (font,size),values in by.items():
        strings=sorted(values)
        for i,a in enumerate(strings):
            for b in strings[i+1:]:
                if len(a)!=len(b):continue
                positions=[j for j,(x,y) in enumerate(zip(a,b)) if x!=y]
                kind='single_position' if len(positions)==1 else 'permutation' if sorted(a)==sorted(b) else None
                if kind is None:continue
                good=values[a]['reader_raw']==a and values[b]['reader_raw']==b
                count[kind+'_pairs']+=1;count[kind+'_both_exact']+=int(good)
                pairs.append(dict(font=font,size=size,a=a,b=b,changed_positions=positions,type=kind,both_exact=good,
                    raw_a=values[a]['reader_raw'],raw_b=values[b]['reader_raw']))
    return dict(count),pairs

def score_training():
    manifest=read(OUT/'training-data/manifest.json');pred={r['id']:r for r in read(OUT/'training-evaluation/predictions.json')}
    joined=[dict(r,reader_raw=pred[r['id']]['reader_raw']) for r in manifest]
    groups={'train':[r for r in joined if r['split']=='train'],
        'validation-unseen-values-seen-fonts':[r for r in joined if r['split']=='validation'],
        'sealed-unseen-values-seen-fonts':[r for r in joined if r['split']=='sealed-test' and r['font']!='sourceserif4'],
        'sealed-unseen-values-held-font':[r for r in joined if r['split']=='sealed-test' and r['font']=='sourceserif4']}
    metrics={}
    for name,rows in groups.items():
        metrics[name]=grouped_metrics(rows);counts,pairs=pairing_diagnostics(rows);metrics[name]['value_pair_checks']=counts
        strings=defaultdict(list)
        for r in rows:strings[r['label']].append(r)
        metrics[name]['strings_all_appearances_exact']=dict(exact=sum(all(r['label']==r['reader_raw'] for r in rr) for rr in strings.values()),total=len(strings))
        write(OUT/'training-evaluation'/(name+'-pairs.json'),pairs)
    write(OUT/'training-evaluation/failed.json',[r for r in joined if r['label']!=r['reader_raw']])
    write(OUT/'training-evaluation/metrics.json',metrics)
    return metrics

def compare_real(rows,readings,reader_name):
    objects={o['source_object_id']:o for o in read(OUT/'real-local/objects.json')};out=[]
    for r in rows:
        candidates=[]
        for h in objects[r['source_object_id']]['historical_inputs']:
            if h['candidate_raw'] not in [a[1] for a in candidates]:candidates.append((h['mapping_id'],h['candidate_raw']))
        candidates.append(('preprovided_source_reading',objects[r['source_object_id']]['source_visual_reading']))
        for origin,raw in candidates:
            item=compare_region(r,readings[r['crop_id']],raw);item['candidate_origin']=origin
            out.append(item)
    write(OUT/'real-local'/reader_name/'comparisons.json',out)
    return dict(Counter(r['failure_reason'] or r['comparison_result'] for r in out))

def score_regions(reader_name):
    rows=read(OUT/'real-local/regions.json')+read(OUT/'synthetic/regions.json')
    pred={r['crop_id']:r for group in ('real-local','synthetic') for r in read(OUT/group/reader_name/'predictions.json')}
    joined=[dict(r,reader_raw=pred[r['crop_id']]['reader_raw']) for r in rows]
    metrics={}
    for group in ('real','goal20','old-protection','control'):
        rr=[r for r in joined if r['group']==group]
        metrics[group]=dict(region_mappings=grouped_metrics(rr),unique_pixels=grouped_metrics(unique_crops(rr)),
            independent_sources=len({r['source_object_id'] for r in rr}))
    real=[r for r in joined if r['group']=='real']
    metrics['real']['comparison_status_counts']=compare_real(real,pred,reader_name)
    metrics['real']['historical_correct_protection']=basic([r for r in real if r['historical_correct_numeric']])
    metrics['real']['by_design']={d:grouped_metrics([r for r in real if r['design']==d]) for d in sorted({r['design'] for r in real})}
    protection=[r for r in joined if r['group']=='old-protection']
    metrics['old-protection']['historical_pair_coverage']=dict(covered_pairs=len({p for r in protection for p in r['old_correct_pair_ids']}),original_correct_pairs=668,
        covered_source_images=len({r['source_object_id'] for r in protection}),digit_fields=len(protection),
        roles=dict(Counter(r['role'] for r in protection)),full_eight_role_evaluation=False)
    for group in ('real-local','synthetic'):
        rr=[r for r in joined if (r['group']=='real')==(group=='real-local')]
        write(OUT/group/reader_name/'scored-regions.json',rr)
        write(OUT/group/reader_name/'failures.json',[r for r in rr if r['label'] is not None and r['reader_raw']!=r['label']])
    # Goal20 fixed comparisons; exactly the two supplied numeric fields, not eight roles.
    mapping={(r['source_object_id'].removeprefix('G20:'),r['role']):r for r in joined if r['group']=='goal20'}
    pairs=read(OUT/'synthetic/goal20-pairs.json');outputs=[];pair_correct={}
    for p in pairs:
        correct=[]
        for role in ('numerator','denominator'):
            r=mapping[(p['image_id'],role)];item=compare_region(r,pred[r['crop_id']],p['candidate_raw'])
            expected='DIGIT_VALUE_EQUAL' if parse_candidate(p['candidate_raw'])['parts'][role]==r['label'] else 'DIGIT_VALUE_MISMATCH'
            item.update(pair_id=p['id'],condition=p['condition'],block=p['block'],expected_numeric_comparison=expected,
                comparison_correct=item['comparison_result']==expected)
            correct.append(item['comparison_correct']);outputs.append(item)
        pair_correct[p['id']]=all(correct)
    grids=read(OUT/'synthetic/goal20-grids.json');grid_results=[dict(g,both_numeric_fields_correct_all_four=all(pair_correct[p] for p in g['pair_ids'])) for g in grids]
    conditions={}
    for condition in ('00','01','10','11'):
        gg=[g for g in grid_results if g['condition']==condition]
        fixed_ids={p for g in gg for p in g['pair_ids']}
        pp=[p for p in pairs if p['id'] in fixed_ids]
        conditions[condition]=dict(pair_both_numeric_correct=sum(pair_correct[p['id']] for p in pp),pairs=len(pp),
            total_pair_pool=sum(p['condition']==condition for p in pairs),
            strict_four_numeric_correct=sum(g['both_numeric_fields_correct_all_four'] for g in gg),strict_four_total=len(gg),
            blocks_all_numeric_four_correct=sum(all(g['both_numeric_fields_correct_all_four'] for g in gg if g['block']==b) for b in sorted({g['block'] for g in gg})),blocks=6)
    metrics['goal20']['fixed_comparisons']=conditions
    write(OUT/'synthetic'/reader_name/'comparisons.json',outputs)
    write(OUT/'synthetic'/reader_name/'four-cells.json',grid_results)
    write(OUT/(reader_name+'-metrics.json'),metrics)
    return metrics,joined

def same_crop(ocr,digit):
    by={r['id']:r for r in digit};items=[]
    for a in ocr:
        b=by[a['id']]
        status='UNSCORABLE' if a['label'] is None else ('BOTH_EXACT' if a['reader_raw']==a['label'] and b['reader_raw']==a['label'] else
            'OCR_ONLY' if a['reader_raw']==a['label'] else 'DIGIT_ONLY' if b['reader_raw']==a['label'] else 'BOTH_FAILED')
        items.append(dict(region_id=a['id'],source_object_id=a['source_object_id'],design=a.get('design'),group=a['group'],role=a['role'],
            label=a['label'],ocr_raw=a['reader_raw'],digit_raw=b['reader_raw'],status=status,
            historical_correct=a['historical_correct_numeric'],source_box=a['source_box'],crop_id=a['crop_id']))
    real=[r for r in items if r['group']=='real'];objects=[]
    for oid in sorted({r['source_object_id'] for r in real}):
        rr=[r for r in real if r['source_object_id']==oid]
        if any(r['status']=='UNSCORABLE' for r in rr):status='PARTIALLY_UNSCORABLE'
        else:
            a=all(r['ocr_raw']==r['label'] for r in rr);b=all(r['digit_raw']==r['label'] for r in rr)
            status='BOTH_EXACT' if a and b else 'OCR_ONLY' if a else 'DIGIT_ONLY' if b else 'BOTH_FAILED'
        objects.append(dict(source_object_id=oid,design=rr[0]['design'],status=status,fields=len(rr),
            scorable_fields=sum(r['label'] is not None for r in rr),extra_correct_fields=sum(r['status']=='DIGIT_ONLY' for r in rr),
            losses_to_ocr=sum(r['status']=='OCR_ONLY' for r in rr)))
    write(OUT/'real-local/same-crop-fields.json',real);write(OUT/'real-local/same-crop-objects.json',objects)
    write(OUT/'real-local/new-correct.json',[r for r in real if r['status']=='DIGIT_ONLY'])
    write(OUT/'real-local/ocr-correct-losses.json',[r for r in real if r['status']=='OCR_ONLY'])
    write(OUT/'real-local/historical-correct-losses.json',[r for r in real if r['historical_correct'] and r['label'] is not None and r['digit_raw']!=r['label']])
    write(OUT/'synthetic/same-crop-fields.json',[r for r in items if r['group']!='real'])
    return dict(real_fields=dict(Counter(r['status'] for r in real)),real_objects=dict(Counter(r['status'] for r in objects)),
        real_by_design={d:dict(fields=dict(Counter(r['status'] for r in real if r['design']==d)),objects=dict(Counter(r['status'] for r in objects if r['design']==d))) for d in sorted({r['design'] for r in real})},
        extra_correct_independent_objects=len({r['source_object_id'] for r in real if r['status']=='DIGIT_ONLY'}),
        losses_to_ocr_independent_objects=len({r['source_object_id'] for r in real if r['status']=='OCR_ONLY'}),
        historical_real_protection_losses=sum(r['historical_correct'] and r['label'] is not None and r['digit_raw']!=r['label'] for r in real))

def main():
    started=time.perf_counter()
    train=score_training();ocr,orows=score_regions('ocr');digit,drows=score_regions('digit');same=same_crop(orows,drows)
    # Direct candidate-change control uses immutable saved reading; no network is called.
    r=next(r for r in orows if r['group']=='goal20');reading={'reader':'stored-control','reader_raw':r['reader_raw']}
    a=compare_region(r,reading,'12/14"');b=compare_region(r,reading,'99/88"');assert a['reader_raw']==b['reader_raw']==reading['reader_raw']
    assert parse_candidate('11/2')['parts']['whole'] is None
    assert not parse_candidate('1½2" (typ.)')['supported']
    controls=dict(candidate_change_leaves_raw_reading_unchanged=True,reader_not_called_by_comparator=True,
        no_inserted_mixed_number_space=True,no_malformed_candidate_repair=True,
        untested_roles_never_consistent=all(x['full_eight_role_verification']=='NOT_ESTABLISHED' for x in (a,b)),
        meaning='system design controls, not learned role composition')
    write(OUT/'comparison-program-checks.json',controls)
    summary=dict(utc=utc(),training=train,ocr=ocr,digit=digit,same_crop=same,
        TRAINING_TRIGGER='MET',NEW_TRAINING_TRAJECTORIES=1,ROLE_LOCATION_MODE='ORACLE_DIAGNOSTIC',
        AUTOMATIC_ROLE_LOCALIZATION='NOT_EVALUATED',FULL_EIGHT_ROLE_VERIFICATION='NOT_ESTABLISHED',
        REAL_ASSESSMENT='AI_QA_PROVISIONAL',INDEPENDENT_C='NOT_RUN',FORMAL_CAD_IMPROVEMENT=0,
        HUMAN_NET_LABOR='NOT_MEASURED',PRODUCTION_PROMOTION='NO_GO',scoring_seconds=time.perf_counter()-started)
    write(OUT/'summary.json',summary)
    print(json.dumps(dict(training={k:v['overall'] for k,v in train.items()},same_crop=same),ensure_ascii=False))

if __name__=='__main__':main()
