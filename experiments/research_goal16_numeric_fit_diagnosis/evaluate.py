"""Final-only sealed comparison, or explicit NOT_RUN after failed Fit-D."""
import time
from collections import defaultdict
from runtime import *

def component_stability(rows,predictions):
    by={p['id']:p['prediction'] for p in predictions};buckets=defaultdict(list)
    for r in rows:
        if r['condition'] in ['complete','gray_outside']:buckets[(r['component'],r['group'],r['source_index'],r['candidate_index'],r['scope'])].append(r)
    components=defaultdict(list)
    for k,bb in buckets.items():
        components[k[0]].append(dict(group=k[1],source_index=k[2],candidate_index=k[3],scope=k[4],appearance_instances=len(bb),
          overall_stable=len({by[r['id']]['overall'] for r in bb})==1,
          all_roles_stable=all(by[r['id']]['parts']==by[bb[0]['id']]['parts'] for r in bb),
          all_overall_correct=all(by[r['id']]['overall']==r['annotation']['overall'] for r in bb),
          all_roles_correct=all(by[r['id']]['parts']==r['annotation']['parts'] for r in bb)))
    return dict(components={k:dict(all_variations_overall_stable=all(v['overall_stable'] for v in vs),all_variations_roles_stable=all(v['all_roles_stable'] for v in vs),
        all_variations_overall_correct=all(v['all_overall_correct'] for v in vs),all_variations_roles_correct=all(v['all_roles_correct'] for v in vs),cases=vs) for k,vs in components.items()},
        denominator=len(components))

def main():
    start=time.perf_counter();d=read(OUT/'fit-D/final-result.json')
    if not d['all_pairs_all_roles_exact']:
        write(OUT/'evaluation/status.json',dict(utc=utc(),fit_D='FAILED_ALL_PAIRS_ALL_ROLES_CRITERION',fit_M='NOT_RUN',
            new_sealed_model_evaluation='NOT_RUN',goal15_model_on_new_test='NOT_RUN',reason='Fit-D did not fully fit the fixed diagnostic; stop per protocol',
            diagnostic_metrics='fit-D/final-metrics.json',diagnostic_failures='fit-D/failed-pairs.json',seconds=time.perf_counter()-start))
        print('Fit-D failed criterion. Fit-M and new sealed inference NOT_RUN.');return
    assert read(OUT/'fit-M/resource.json')['status']=='COMPLETE'
    configure();rows=read(OUT/'data/sealed-test.json');cache=load_pixels(rows);images={r['image']:r for r in read(OUT/'data/images.json')}
    paths={'goal15-final':OLD_OUT/'run/last.pt','fit-M-step-0500':OUT/'fit-M/step-0500.pt','fit-M-final':OUT/'fit-M/last.pt'}
    results={}
    for name,path in paths.items():
        if not path.exists():results[name]=dict(status='NOT_REACHED');continue
        state=torch.load(path,map_location='cpu',weights_only=False);model=JointModel();model.load_state_dict(state['model_state'])
        predictions,ll=predict(model,rows,cache);write(OUT/'evaluation'/f'{name}-predictions.json',predictions)
        by={r['id']:r['prediction'] for r in predictions};joined=[dict(r,prediction=by[r['id']]) for r in rows]
        results[name]=dict(status='EVALUATED_NO_UPDATES',checkpoint=str(path),updates=state['updates'],**summarize(rows,predictions),losses=ll,
          same_test_single_input_ceilings=metrics.ceilings(joined,images),appearance_stability=metrics.stability(joined,images),
          component_stability=component_stability(rows,predictions),single_factor={me:metrics.global_metrics([r for r in joined if r['mechanism']==me]) for me in MECHANISMS})
        print(json.dumps(dict(model=name,accuracy=results[name]['global_metrics']['accuracy'],full_roles=results[name]['global_metrics']['full_parts_exact'])),flush=True)
    write(OUT/'evaluation/comparison.json',results)
    write(OUT/'evaluation/status.json',dict(utc=utc(),fit_D='PASSED',fit_M='COMPLETE',new_sealed_model_evaluation='COMPLETE',seconds=time.perf_counter()-start,
      comparisons='Same new sealed data: Goal15 versus M500 reflects recorded data changes; M500 versus final reflects continued updates. Final checkpoint is primary.',**memory()))

if __name__=='__main__':main()
