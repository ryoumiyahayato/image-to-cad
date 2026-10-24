"""One final F/E/L evaluation after both arms terminate. Real arrays reused as-is."""
import time,copy
from collections import defaultdict
from engine import *
scorer=load_module('goal18_explicit_score',HERE/'score.py')
stats=scorer.stats;detailed=scorer.detailed;retention=scorer.retention;rate=scorer.rate

def main():
    configure();start=time.perf_counter();out=OUT/'evaluation';out.mkdir(exist_ok=True)
    assert not (out/'started.json').exists()
    resources={a:read(OUT/f'fit-{a}/resource.json') for a in ['E','L']}
    common=[n for n in [500,1000,2000] if all((OUT/f'fit-{a}/step-{n:04d}.pt').exists() for a in ['E','L'])]
    assert common,'No equal-step primary comparison exists; report incomplete without selecting unequal steps'
    chosen=max(common);paths={'F':INITIAL,**{a:OUT/f'fit-{a}/step-{chosen:04d}.pt' for a in ['E','L']}}
    write(out/'frozen-models.json',dict(utc=utc(),paths={k:str(v) for k,v in paths.items()},primary_new_updates=chosen,actual_new_updates={a:r['new_updates'] for a,r in resources.items()},
        planned_comparison_complete=chosen==2000,training_wall_sum=sum(r['training_wall_seconds'] for r in resources.values()),selection='Largest predeclared common completed step, before evaluating any model'))
    write(out/'started.json',dict(utc=utc(),models=['F','E','L']))
    data={name:read(OUT/'data'/f'{name}.json') for name in ['sealed-E','sealed-L','train-E','train-L']}
    old_images={r['image']:r for r in read(OLD/'data/images.json')}
    data['retention']=read(OLD/'data/validation.json')
    for r in data['retention']:r['source_kind']=old_images[r['image']]['construction_only']['kind'];r['image']=str(OLD/'data'/r['image'])
    data['real']=[r for r in read(OUT/'real-local/frozen-pairs.json') if r['run_forward']]
    cache=cache_pixels([r for name,rr in data.items() if name!='real' for r in rr]);array_cache={r['id']:torch.from_numpy(np.load(r['array']).copy()) for r in data['real']}
    baseline_old={r['id']:r['prediction'] for r in read(OLD/'fit-M/final-validation-predictions.json')}
    baseline_real={r['id']:r['prediction'] for r in read(G17/'real-local/predictions.json')}
    all_joined={};forward_seconds={};aggregate={};real_aggregate={}
    for name,path in paths.items():
        saved=torch.load(path,map_location='cpu',weights_only=False);model=JointModel();model.load_state_dict(saved['model_state']);model.eval();all_joined[name]={};forward_seconds[name]=0.;aggregate[name]={}
        if name!='F':assert saved['new_updates']==chosen
        for dataset,rows in data.items():
            preds=[]
            with torch.inference_mode():
                for offset in range(0,len(rows),32):
                    batch=rows[offset:offset+32]
                    if dataset=='real':
                        pixels=torch.stack([array_cache[r['id']] for r in batch]);chars=torch.tensor([encode_candidate(r['candidate_raw']) for r in batch]);scopes=torch.tensor([SCOPES.index(r['scope']) for r in batch]);x=(pixels,chars,scopes)
                    else:x=inputs(batch,cache)
                    t=time.perf_counter();logits=model(*x);forward_seconds[name]+=time.perf_counter()-t
                    for i,r in enumerate(batch):preds.append(dict(id=r['id'],prediction=annotation_from_classes(logits[i].argmax(-1).tolist()),part_probabilities=logits[i].softmax(-1).tolist()))
            rr=joined(rows,preds);all_joined[name][dataset]=rr
            target=OUT/'real-local'/name if dataset=='real' else out/name
            write(target/f'{dataset}-predictions.json',preds);write(target/f'{dataset}-joined.json',rr)
            if dataset=='real':
                eligible=[r for r in rr if r['contract_scorable']];pending=[r for r in rr if not r['contract_scorable']]
                real_aggregate[name]=dict(scorable=stats(eligible),pending=stats(pending),historical_correct=stats([r for r in eligible if r['candidate_kind']=='historical_OCR' and r['annotation']['overall']=='CONSISTENT']))
            else:aggregate[name][dataset]=detailed(rr) if dataset!='retention' else stats(rr)
            if name=='F' and dataset in ['retention','real']:
                prior=baseline_old if dataset=='retention' else baseline_real;assert all(r['prediction']==prior[r['id']] for r in rr),'Baseline reading changed'
        assert exact(model.state_dict(),saved['model_state'])
    groups=[]
    for b in aggregate['E']['sealed-E']['groups']:
        item=dict(component=b['id'],target_role=b['role'],models={})
        for name in paths:item['models'][name]=next(g for g in aggregate[name]['sealed-E']['groups'] if g['id']==b['id'])
        item['E_vs']={name:('improved' if b['roles_correct']>item['models'][name]['roles_correct'] else 'degraded' if b['roles_correct']<item['models'][name]['roles_correct'] else 'tied') for name in ['F','L']}
        groups.append(item)
    aggregate['group_comparison']=groups
    aggregate['retention_change']={name:retention(all_joined['F']['retention'],all_joined[name]['retention']) for name in ['E','L']}
    objects=[]
    for gid in sorted({r['group'] for r in data['real']}):
        obj=dict(source_object=gid,models={})
        for name in paths:
            rr=[r for r in all_joined[name]['real'] if r['group']==gid];signals=[];wrong_diagnostics=[]
            for r in rr:
                if r['annotation']['overall']!='CONTRADICTION':continue
                true_roles=[k for k,v in r['annotation']['parts'].items() if v=='CONTRADICTION']
                known=[k for k,v in r['annotation']['parts'].items() if v in ['CONSISTENT','NOT_APPLICABLE']]
                wrong_diagnostics.append(dict(id=r['id'],overall_rejected=r['prediction']['overall']=='CONTRADICTION',all_true_contradictions_identified=all(r['prediction']['parts'][k]=='CONTRADICTION' for k in true_roles),
                    all_other_known_roles_preserved=all(r['prediction']['parts'][k]==r['annotation']['parts'][k] for k in known),
                    false_contradiction_roles=[k for k in known if r['prediction']['parts'][k]=='CONTRADICTION'],true_contradiction_roles=true_roles))
            for mid in sorted({r['mapping_id'] for r in rr}):
                subset=[r for r in rr if r['mapping_id']==mid and r['contract_scorable']]
                wrong=[r for r in subset if r['candidate_kind']=='historical_OCR' and r['annotation']['overall']=='CONTRADICTION'];correct=[r for r in subset if r['candidate_kind']=='preprovided_source_reading' and r['annotation']['overall']=='CONSISTENT']
                if wrong and correct:
                    w,c=wrong[0],correct[0];signals.append(dict(mapping_id=mid,overall_pair=w['prediction']['overall']=='CONTRADICTION' and c['prediction']['overall']=='CONSISTENT',
                        role_pair=metrics.parts_correct(w) and metrics.parts_correct(c)))
            obj['models'][name]=dict(rows=rr,wrong_diagnostics=wrong_diagnostics,paired_signals=signals)
        objects.append(obj)
    for name in paths:
        sig=[s for o in objects for s in o['models'][name]['paired_signals']];wrong=[s for o in objects for s in o['models'][name]['wrong_diagnostics']]
        real_aggregate[name]['paired_overall']=rate(sum(s['overall_pair'] for s in sig),len(sig));real_aggregate[name]['paired_all_roles']=rate(sum(s['role_pair'] for s in sig),len(sig))
        real_aggregate[name]['wrong_all_true_roles_identified']=rate(sum(w['all_true_contradictions_identified'] for w in wrong),len(wrong))
        real_aggregate[name]['wrong_other_known_roles_preserved']=rate(sum(w['all_other_known_roles_preserved'] for w in wrong),len(wrong))
        real_aggregate[name]['wrong_rejection_with_false_role']=rate(sum(w['overall_rejected'] and bool(w['false_contradiction_roles']) for w in wrong),sum(w['overall_rejected'] for w in wrong))
        real_aggregate[name]['objects_with_paired_signal']=sum(any(s['overall_pair'] for s in o['models'][name]['paired_signals']) for o in objects)
    write(OUT/'real-local/object-comparison.json',objects)
    write(OUT/'real-aggregate.json',dict(assessment='AI_QA_PROVISIONAL',mapping_records=12,source_objects=8,array_inputs=21,scorable=19,pending=2,outside_contract_not_run=1,models=real_aggregate))
    write(out/'comparison.json',aggregate)
    for r in data['real']:assert np.array_equal(np.load(r['array']),array_cache[r['id']].numpy())
    resource=dict(utc=utc(),evaluation_wall_seconds=time.perf_counter()-start,forward_seconds=forward_seconds,model_parameters_unchanged=True,optimizer_updates=0,OCR_runs=0,
        real_arrays_source=str(G17/'real-local/arrays'),real_arrays_exact_reuse=True,baseline_validation_836_matches_history=True,baseline_real_21_matches_goal17=True)
    write(out/'resource.json',resource)
    print(json.dumps(dict(primary={k:aggregate[k]['sealed-E']['global_metrics'] for k in paths},four={k:aggregate[k]['sealed-E']['four_roles'] for k in paths},resource=resource)))

if __name__=='__main__':main()
