"""Exactly registered Fit-D, then conditional Fit-M. No metric-based checkpoint selection."""
import time,argparse
PROCESS_START=time.perf_counter()
from runtime import *

def fit(which):
    plan=read(OUT/'frozen-plan.json');assert plan['data_and_implementation_checks_passed']
    assert plan['base_configuration']==CONFIG and plan['fits']==FITS
    for frozen in (OUT/'frozen-source').glob('*.py'):
        assert frozen.read_bytes()==(HERE/frozen.name).read_bytes(),'Frozen source changed: '+frozen.name
    for old_folder,sub in [(G15,'goal15'),(G14,'goal14')]:
        for frozen in (OUT/'frozen-source'/sub).glob('*.py'):
            assert frozen.read_bytes()==(old_folder/frozen.name).read_bytes(),'Frozen dependency changed: '+frozen.name
    rd=OUT/f'fit-{which}';rd.mkdir(exist_ok=True)
    if which=='M':
        diag=read(OUT/'fit-D/final-result.json');assert diag['all_pairs_all_roles_exact'] is True,'Fit-D failed; Fit-M forbidden'
        budget=900-read(OUT/'fit-D/resource.json')['training_wall_seconds'];limit=5000
    else:budget=240.;limit=2000
    with (rd/'started.json').open('x',encoding='utf8') as stream:json.dump(dict(utc=utc(),pid=os.getpid(),fit=which,max_updates=limit,training_wall_budget=budget),stream,indent=2)
    configure();initialize=time.perf_counter();model=restored_initial();opt=optimizer_for(model);assert len(opt.state)==0
    generator=torch.Generator().manual_seed(SEED);init_seconds=time.perf_counter()-initialize
    loading=time.perf_counter();rows=read(OUT/'data'/('diagnostic.json' if which=='D' else 'train.json'));cache=load_pixels(rows)
    validation=read(OUT/'data/validation.json') if which=='M' else [];valcache=load_pixels(validation) if validation else {}
    loading_seconds=time.perf_counter()-loading;updates=0;curve=[];observations=[];max_step=0.;stop='MAX_UPDATES'
    milestones=[500,1000,1500,2000] if which=='D' else [500,2000,5000]
    # No optimization or outcome selection in this initial observation.
    if which=='D':
        prediction,loss=predict(model,rows,cache);write(rd/'predictions-0000.json',prediction)
        write(rd/'metrics-0000.json',dict(**summarize(rows,prediction),losses=loss))
    started=time.perf_counter();observation_seconds=0.
    while updates<limit:
        elapsed=time.perf_counter()-started
        observation_reserve=(max(5.,2*observations[-1]['seconds']) if observations else 30.) if which=='M' and updates+1 in milestones else 0.
        if elapsed+max(5.,2*max_step,observation_reserve)>budget:stop='TRAINING_WALL_BUDGET';break
        step=time.perf_counter();model.train()
        selected=torch.randint(len(rows),(32,),generator=generator).tolist();batch=[rows[i] for i in selected]
        logits=model(*inputs(batch,cache));loss,part,glob=losses(logits,batch)
        if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss; stop this registered fit; no replacement run')
        opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),CONFIG['gradient_clip_norm']);opt.step();updates+=1
        duration=time.perf_counter()-step;max_step=max(max_step,duration)
        curve.append(dict(update=updates,loss=float(loss.detach()),role_loss=float(part.detach()),aggregate_loss=float(glob.detach()),step_seconds=duration,training_wall_elapsed=time.perf_counter()-started))
        if updates==1 or updates%250==0:print(json.dumps(dict(stage=f'FIT-{which}',**curve[-1])),flush=True)
        if updates in milestones:
            tick=time.perf_counter()
            save_checkpoint(rd/f'step-{updates:04d}.pt',model,opt,updates,generator)
            prediction,losses_at_step=predict(model,rows,cache);summary=summarize(rows,prediction)
            write(rd/f'predictions-{updates:04d}.json',prediction);write(rd/f'metrics-{updates:04d}.json',dict(**summary,losses=losses_at_step))
            if which=='M':
                vp,vl=predict(model,validation,valcache);write(rd/f'validation-predictions-{updates:04d}.json',vp)
                write(rd/f'validation-metrics-{updates:04d}.json',dict(**summarize(validation,vp),losses=vl))
            used=time.perf_counter()-tick;observation_seconds+=used
            observations.append(dict(update=updates,seconds=used,global_correct=summary['global_metrics']['accuracy'],all_roles_correct=summary['global_metrics']['full_parts_exact']))
            print(json.dumps(dict(stage=f'FIT-{which}-FIXED-OBSERVATION',**observations[-1])),flush=True)
    training_wall=time.perf_counter()-started
    if updates==0:raise RuntimeError('No optimizer update; do not retry')
    save_checkpoint(rd/'last.pt',model,opt,updates,generator);write(rd/'training-curve.json',curve);write(rd/'observations.json',observations)
    evaluation=time.perf_counter();prediction,final_losses=predict(model,rows,cache);summary=summarize(rows,prediction)
    write(rd/'final-predictions.json',prediction);write(rd/'final-metrics.json',dict(**summary,losses=final_losses))
    byid={r['id']:r for r in prediction}
    failures=[dict(r,**{k:v for k,v in byid[r['id']].items() if k!='id'}) for r in rows if r['annotation']['parts']!=byid[r['id']]['prediction']['parts'] or r['annotation']['overall']!=byid[r['id']]['prediction']['overall']]
    write(rd/'failed-pairs.json',failures)
    exact=len(failures)==0
    write(rd/'final-result.json',dict(utc=utc(),fit=which,updates=updates,pairs=len(rows),all_pairs_all_roles_exact=exact,failed_pairs=len(failures),
          criterion='Every pair overall and all eight roles equal frozen truth; final checkpoint only',
          fit_M_authorized_by_diagnosis=exact if which=='D' else None))
    if which=='M':
        vp,vl=predict(model,validation,valcache);write(rd/'final-validation-predictions.json',vp);write(rd/'final-validation-metrics.json',dict(**summarize(validation,vp),losses=vl))
    evaluation_seconds=time.perf_counter()-evaluation
    saved=torch.load(rd/'last.pt',map_location='cpu',weights_only=False)
    assert saved['updates']==updates and all(torch.equal(v,saved['model_state'][k]) for k,v in model.state_dict().items())
    resource=dict(utc=utc(),status='COMPLETE',fit=which,parameters=sum(p.numel() for p in model.parameters()),optimizer_updates=updates,stop_reason=stop,
      training_wall_seconds=training_wall,training_wall_budget_seconds=budget,fixed_observations_inside_training_wall_seconds=observation_seconds,
      final_evaluation_seconds=evaluation_seconds,imports_seconds=IMPORT_SECONDS,initialization_seconds=init_seconds,data_load_seconds=loading_seconds,
      process_wall_seconds=time.perf_counter()-PROCESS_START,checkpoint_bytes=(rd/'last.pt').stat().st_size,checkpoint_readback_equal=True,
      initial_source='initial.pt (0 updates), never Fit-D learned weights',optimizer_initial_state_empty=True,
      cpu_threads=4,interop_threads=1,input_shape=[32,1,128,512],seed=SEED,**memory())
    write(rd/'resource.json',resource);print(json.dumps(resource),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fit',choices=['D','M'],required=True);a=p.parse_args()
    try:fit(a.fit)
    except Exception as exc:
        write(OUT/f'fit-{a.fit}'/'failure.json',dict(utc=utc(),error=repr(exc),pid=os.getpid(),status='FAILED_REGISTERED_FIT_NO_RETRY',process_wall_seconds=time.perf_counter()-PROCESS_START,**memory()));raise
