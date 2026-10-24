"""One registered arm per process. E and L independent, same frozen replay and seed."""
import os,sys,time
PROCESS_START=time.perf_counter()
from engine import *

def run(arm):
    assert arm in ['E','L'];plan=read(OUT/'frozen-plan.json');assert plan['visual_review_completed']
    for f in plan['sources']:assert (ROOT/f['path']).read_bytes()==(OUT/f['copy']).read_bytes()
    if arm=='L':assert read(OUT/'fit-E/resource.json')['status'] in ['COMPLETE','BUDGET_STOP']
    rd=OUT/f'fit-{arm}';rd.mkdir(exist_ok=True)
    configure();t=time.perf_counter();model,opt,initial=restored(plan['optimizer_mode']);initial_seconds=time.perf_counter()-t
    write(rd/'initial-state-record.json',dict(utc=utc(),source=str(INITIAL),historical_updates=5000,optimizer_mode=plan['optimizer_mode'],
        model_exact=exact(model.state_dict(),initial['model_state']),optimizer_exact=exact(opt.state_dict(),initial['optimizer_state']) if plan['optimizer_mode']=='RESTORE' else len(opt.state)==0,
        optimizer_steps=sorted(set(int(s['step']) for s in opt.state.values())),seed=SEED,rng_from_initial=True))
    t=time.perf_counter();new=read(OUT/'data'/f'train-{arm}.json');replay=read(OUT/'data/replay-rows.json');replay_by={r['id']:r for r in replay}
    groups={g: [r for r in new if r['group']==g] for g in sorted({r['group'] for r in new})};cache=cache_pixels(new+replay);schedule=read(OUT/'batch-plan.json');loading_seconds=time.perf_counter()-t
    previous=read(OUT/'fit-E/resource.json')['training_wall_seconds'] if arm=='L' else 0.
    # Reserve half the total budget for the second arm. Includes observations, saves and failed work.
    budget=min(300.,600.-previous) if arm=='E' else 600.-previous
    with (rd/'started.json').open('x',encoding='utf8') as f:json.dump(dict(utc=utc(),pid=os.getpid(),arm=arm,budget_seconds=budget,max_new_updates=2000),f,indent=2)
    updates=0;observations=[];curve=[];max_step=0.;stop='MAX_UPDATES';start=time.perf_counter()
    try:
        with (rd/'training-log.jsonl').open('x',encoding='utf8') as log:
            for item in schedule:
                if time.perf_counter()-start+max(5.,2*max_step)>budget:stop='TRAINING_WALL_BUDGET';break
                tick=time.perf_counter();model.train()
                batch=[r for gid in item['new_groups'] for r in groups[gid]]+[replay_by['replay:'+rid] for rid in item['replay_ids']]
                assert len(batch)==32 and item['update']==updates+1
                logits=model(*inputs(batch,cache));loss,part,glob=losses(logits,batch)
                if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss; preserve this trajectory, no replacement run')
                opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),CONFIG['gradient_clip_norm']);opt.step();updates+=1
                elapsed=time.perf_counter()-tick;max_step=max(max_step,elapsed)
                row=dict(update=updates,total_historical_plus_new=5000+updates,loss=float(loss.detach()),role_loss=float(part.detach()),aggregate_loss=float(glob.detach()),step_seconds=elapsed,training_elapsed=time.perf_counter()-start)
                curve.append(row);log.write(json.dumps(row)+'\n')
                if updates==1 or updates%250==0:log.flush();print(json.dumps(dict(arm=arm,**row)),flush=True)
                if updates in [500,1000,2000]:
                    tick=time.perf_counter();checkpoint(rd/f'step-{updates:04d}.pt',model,opt,arm,updates)
                    preds,loss_record=predict(model,new,cache);summary=train_summary(new,preds)
                    write(rd/f'new-train-predictions-{updates:04d}.json',preds);write(rd/f'new-train-metrics-{updates:04d}.json',dict(**summary,loss=loss_record))
                    ob=dict(update=updates,seconds=time.perf_counter()-tick,overall=summary['global_metrics']['accuracy'],all_roles=summary['global_metrics']['full_parts_exact']);observations.append(ob)
                    print(json.dumps(dict(arm=arm,observation=ob)),flush=True)
        checkpoint(rd/'last.pt',model,opt,arm,updates)
        write(rd/'training-curve.json',curve);write(rd/'observations.json',observations)
        training_wall=time.perf_counter()-start
        # Final new-training-only observation; no sealed, validation or real rows are loaded here.
        t=time.perf_counter();preds,ll=predict(model,new,cache);write(rd/'final-new-train-predictions.json',preds);write(rd/'final-new-train-metrics.json',dict(**train_summary(new,preds),loss=ll));eval_seconds=time.perf_counter()-t
        stored=torch.load(rd/'last.pt',map_location='cpu',weights_only=False);assert exact(stored['model_state'],model.state_dict()) and exact(stored['optimizer_state'],opt.state_dict())
        steps=sorted(set(int(s['step']) for s in opt.state.values()));assert steps==[5000+updates] if plan['optimizer_mode']=='RESTORE' else steps==[updates]
        resource=dict(utc=utc(),status='COMPLETE' if updates==2000 else 'BUDGET_STOP',arm=arm,new_updates=updates,historical_updates=5000,stop_reason=stop,
            training_wall_seconds=training_wall,budget_seconds=budget,observations_inside_budget_seconds=sum(r['seconds'] for r in observations),
            initialization_seconds=initial_seconds,data_loading_seconds=loading_seconds,final_train_evaluation_seconds=eval_seconds,import_seconds=IMPORT_SECONDS,
            process_seconds=time.perf_counter()-PROCESS_START,optimizer_steps=steps,checkpoint_readback_equal=True,seed=SEED,
            sealed_evaluations_during_training=0,old_validation_evaluations_during_training=0,real_evaluations_during_training=0,**memory())
        write(rd/'resource.json',resource);print(json.dumps(resource),flush=True)
    except Exception as exc:
        write(rd/'failure.json',dict(utc=utc(),arm=arm,error=repr(exc),completed_new_updates=updates,training_wall_seconds=time.perf_counter()-start,pid=os.getpid()))
        raise

if __name__=='__main__':run(sys.argv[1])
