"""One final evaluation of F/G/S after both fixed trajectories terminate."""
import time,copy
from engine import *
scorer=load_module('goal20_explicit_score',HERE/'score.py')
def main():
    start=time.perf_counter();plan=read(OUT/'frozen-plan.json');dest=OUT/'evaluation';dest.mkdir(exist_ok=True);assert not (dest/'started.json').exists()
    for rel in plan['source_paths']:assert (ROOT/rel).read_bytes()==(OUT/'frozen-source'/rel).read_bytes(),rel
    for rel in plan['data_paths']:assert (OUT/rel).read_bytes()==(OUT/'frozen-data'/rel).read_bytes(),rel
    resources={a:read(OUT/f'fit-{a}/resource.json') for a in ['G','S']};assert all(r['status'] in ['COMPLETE','BUDGET_STOP'] for r in resources.values())
    configure();new=read(OUT/'data/pairs.json');old=read(OUT/'data/retention.json');cache=cache_pixels(new+old)
    for im in read(OUT/'data/images.json'):
        assert np.array_equal(((255.-cache[str(OUT/im['image'])].float())/255.).unsqueeze(0).numpy(),np.load(OUT/im['array']))
    reference={r['id']:r for r in read(OUT/'data/F-reference-predictions.json')}
    grids=read(OUT/'data/grids.json');eval_ids={c:{r['id'] for r in read(OUT/f'data/eval-{c}.json')} for c in CONDITIONS};train_ids={a:{r['id'] for r in read(OUT/f'data/train-{a}.json')} for a in ['G','S']}
    paths={'F':INITIAL,'G':OUT/'fit-G/final.pt','S':OUT/'fit-S/final.pt'}
    write(dest/'started.json',dict(utc=utc(),models={a:str(p) for a,p in paths.items()},actual_updates={a:r['new_updates'] for a,r in resources.items()},selection='Predeclared final checkpoint only'))
    results={};retained={};forward={};all_joined={};baseline_checks=[]
    for name,path in paths.items():
        saved=torch.load(path,map_location='cpu',weights_only=False);model=JointModel();model.load_state_dict(saved['model_state']);model.eval();model.requires_grad_(False)
        assert saved['configuration']==CONFIG
        if name=='F':assert saved['updates']==5000
        else:assert saved['arm']==name and saved['new_updates']==resources[name]['new_updates'] and saved['historical_updates']==5000
        forward[name]=0.;all_joined[name]={}
        for dataset,rows in [('new',new),('retention',old)]:
            preds=[]
            with torch.inference_mode():
                for offset in range(0,len(rows),32):
                    batch=rows[offset:offset+32];x=inputs(batch,cache);tick=time.perf_counter();logits=model(*x);forward[name]+=time.perf_counter()-tick
                    for i,r in enumerate(batch):preds.append(dict(id=r['id'],prediction=annotation_from_classes(logits[i].argmax(-1).tolist()),part_probabilities=logits[i].softmax(-1).tolist()))
            rr=[dict(r,prediction=p['prediction']) for r,p in zip(rows,preds)];assert [r['id'] for r in rr]==[p['id'] for p in preds]
            write(dest/name/f'{dataset}-predictions.json',preds);write(dest/name/f'{dataset}-joined.json',rr);all_joined[name][dataset]=rr
            if name=='F' and dataset=='retention':
                for p in preds:
                    q=reference[p['id']];baseline_checks.append(dict(id=p['id'],prediction_equal=p['prediction']==q['prediction'],probabilities_close=bool(np.allclose(p['part_probabilities'],q['part_probabilities'],atol=1e-6,rtol=1e-5)),max_abs_probability_difference=float(np.max(np.abs(np.array(p['part_probabilities'])-np.array(q['part_probabilities']))))))
                write(dest/'F-reading-confirmation.json',baseline_checks)
                assert all(r['prediction_equal'] and r['probabilities_close'] for r in baseline_checks),'F reference mismatch; stop interpretation'
        assert exact(model.state_dict(),saved['model_state'])
        rr=all_joined[name]['new']
        results[name]=dict(train={a:scorer.score_rows([r for r in rr if r['id'] in ids]) for a,ids in train_ids.items()},conditions={c:scorer.condition([r for r in rr if r['id'] in eval_ids[c]],[g for g in grids if g['condition']==c]) for c in CONDITIONS},old=scorer.score_rows(all_joined[name]['retention']))
    assert results['F']['old']['global_metrics']['full_parts_exact']['n']==668
    retention={a:scorer.retention(all_joined['F']['retention'],all_joined[a]['retention']) for a in ['G','S']}
    comparisons={};common_blocks={}
    for model in results:
        common_blocks[model]=sorted(set.intersection(*[{b['id'] for b in results[model]['conditions'][c]['blocks'] if b['all_strict']} for c in CONDITIONS]))
    for c in CONDITIONS:
        gg={g['id']:g for g in results['G']['conditions'][c]['grids']};ss={g['id']:g for g in results['S']['conditions'][c]['grids']}
        comparisons[c]=dict(S_new_strict_ids=[k for k in ss if ss[k]['strict'] and not gg[k]['strict']],S_lost_strict_ids=[k for k in ss if not ss[k]['strict'] and gg[k]['strict']],blocks=[])
        for bid in sorted({g['block'] for g in grids}):
            comparison=dict(block=bid,models={model:next(b for b in results[model]['conditions'][c]['blocks'] if b['id']==bid) for model in results})
            comparisons[c]['blocks'].append(comparison)
    valid_budget=all(r['new_updates']==UPDATES and r['training_wall_seconds']<=300 for r in resources.values()) and sum(r['training_wall_seconds'] for r in resources.values())<=600
    gate={a:dict(all_four_strict_blocks=common_blocks[a],four_of_six=len(common_blocks[a])>=4,old668_broken=retention[a]['all_roles']['broken']['n'],unit_context_broken={k:v['broken'] for k,v in retention[a]['unit_context_all_state_protection'].items()},unknown_correct_broken=retention[a]['unknown_F_correct_broken']['n']) for a in ['G','S']}
    for a,v in gate.items():v['passed']=valid_budget and v['four_of_six'] and v['old668_broken']==0 and not any(v['unit_context_broken'].values()) and v['unknown_correct_broken']==0
    write(dest/'metrics.json',dict(models=results,retention_change=retention,S_vs_G=comparisons,same_blocks_all_conditions=common_blocks,research_continuation=gate,budget_control=valid_budget,difficulty_attribution='Pairing arrangement only; per-block/step difficulty profile differences disclosed before fitting'))
    write(dest/'resource.json',dict(utc=utc(),evaluation_wall_seconds=time.perf_counter()-start,forward_seconds=forward,model_state_unchanged=True,F_baseline836_reproduced=True,all_frozen_source_and_JSON_bytes_unchanged=True,actual_new_array_matches_legacy=True,training_wall_sum=sum(r['training_wall_seconds'] for r in resources.values()),actual_updates={a:r['new_updates'] for a,r in resources.items()},training_budget_control=valid_budget,real_evaluation='NOT_RUN',OCR_runs=0))
    print(json.dumps(dict(training_fit={a:results[a]['train'][a]['global_metrics']['full_parts_exact'] for a in ['G','S']},strict_four={a:{c:results[a]['conditions'][c]['strict_four'] for c in CONDITIONS} for a in results},research_continuation=gate,training_wall_sum=sum(r['training_wall_seconds'] for r in resources.values()),forward_seconds=forward)))
if __name__=='__main__':main()
