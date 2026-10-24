"""Exactly two independent registered trajectories. No evaluation during fitting."""
import os,sys,time
PROCESS_START=time.perf_counter()
from engine import *
def main(arm):
    assert arm in ['G','S'];plan=read(OUT/'frozen-plan.json');assert plan['visual_review']['completed']
    for rel in plan['source_paths']:assert (ROOT/rel).read_bytes()==(OUT/'frozen-source'/rel).read_bytes(),rel
    for rel in plan['data_paths']:assert (OUT/rel).read_bytes()==(OUT/'frozen-data'/rel).read_bytes(),rel
    rd=OUT/f'fit-{arm}';rd.mkdir(exist_ok=True);assert not (rd/'started.json').exists()
    previous=0.
    if arm=='S':
        g=read(OUT/'fit-G/resource.json');assert g['status'] in ['COMPLETE','BUDGET_STOP'];previous=g['training_wall_seconds']
    budget=min(300.,600.-previous);assert budget>10
    configure();tick=time.perf_counter();model,opt,saved=restored('RESTORE');initial_seconds=time.perf_counter()-tick
    assert saved['updates']==5000 and read(OLD/'fit-M/resource.json')['fit']=='M'
    write(rd/'initial-state.json',dict(utc=utc(),source=str(INITIAL),model_exact=exact(model.state_dict(),saved['model_state']),optimizer_exact=exact(opt.state_dict(),saved['optimizer_state']),optimizer_steps=sorted({int(v['step']) for v in opt.state.values()}),rng_exact=torch.equal(torch.get_rng_state(),saved['torch_rng_state']),historical_updates=5000,parameters=sum(p.numel() for p in model.parameters())))
    tick=time.perf_counter();new=read(OUT/f'data/train-{arm}.json');replay=read(OUT/'data/replay-rows.json');new_by={r['id']:r for r in new};old_by={r['id']:r for r in replay};schedule=read(OUT/'batch-plan.json');cache=cache_pixels(new+replay);load_seconds=time.perf_counter()-tick
    with (rd/'started.json').open('x',encoding='utf8') as f:json.dump(dict(utc=utc(),arm=arm,pid=os.getpid(),updates_planned=UPDATES,budget_seconds=budget),f,indent=2)
    updates=0;max_step=0.;start=time.perf_counter();stop='PLANNED_UPDATES';curve=[]
    try:
        with (rd/'training-log.jsonl').open('x',encoding='utf8') as log:
            for item in schedule:
                if time.perf_counter()-start+max(5.,2*max_step)>=budget:stop='HARD_BUDGET';break
                tick=time.perf_counter();model.train()
                batch=[new_by[k] for k in item['new_ids'][arm]]+[old_by[k] for k in item['replay_ids']]
                assert len(batch)==32 and item['update']==updates+1
                logits=model(*inputs(batch,cache));loss,part,glob=losses(logits,batch)
                assert torch.isfinite(loss),'Nonfinite loss; stop without another trajectory'
                opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),CONFIG['gradient_clip_norm']);opt.step();updates+=1
                duration=time.perf_counter()-tick;max_step=max(max_step,duration)
                row=dict(update=updates,block=item['block'],phase=item['phase'],loss=float(loss.detach()),role_loss=float(part.detach()),aggregate_loss=float(glob.detach()),step_seconds=duration,training_seconds=time.perf_counter()-start)
                curve.append(row);log.write(json.dumps(row)+'\n')
                if updates==1 or updates%250==0:log.flush();print(json.dumps(dict(arm=arm,**row)),flush=True)
        save_final(rd/'final.pt',model,opt,arm,updates)
        stored=torch.load(rd/'final.pt',map_location='cpu',weights_only=False)
        assert exact(stored['model_state'],model.state_dict()) and exact(stored['optimizer_state'],opt.state_dict())
        steps=sorted({int(v['step']) for v in opt.state.values()});assert steps==[5000+updates]
        write(rd/'training-curve.json',curve)
        resource=dict(utc=utc(),arm=arm,status='COMPLETE' if updates==UPDATES else 'BUDGET_STOP',new_updates=updates,historical_updates=5000,total_updates=5000+updates,training_wall_seconds=time.perf_counter()-start,budget_seconds=budget,stop_reason=stop,optimizer_steps=steps,checkpoint_readback_equal=True,initialization_seconds=initial_seconds,data_load_seconds=load_seconds,process_seconds=time.perf_counter()-PROCESS_START,train_validation_or_sealed_evaluations_during_training=0,**memory())
        assert resource['training_wall_seconds']<=budget and previous+resource['training_wall_seconds']<=600
        write(rd/'resource.json',resource);print(json.dumps(resource),flush=True)
    except Exception as e:
        save_final(rd/'failed-state.pt',model,opt,arm,updates)
        write(rd/'failure.json',dict(utc=utc(),error=repr(e),new_updates=updates,training_wall_seconds=time.perf_counter()-start,pid=os.getpid()))
        raise
if __name__=='__main__':main(sys.argv[1])
