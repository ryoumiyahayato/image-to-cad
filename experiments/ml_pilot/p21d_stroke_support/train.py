"""Single-GPU main run; one optional resource batch adjustment, checkpointed cursor."""
import argparse
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
import numpy as np
import torch
from common import config,read,write,seed_all,image_tensor,loss_fn,confusion,metrics,rng_state,restore_rng,weights_load
from model import StrokeUNet,pretrained,load_model
from scenes import make_scene,scene_ids

def batch(ids,augmentation,device):
    ss=[make_scene(f,i,augmentation) for f,i in ids]
    return (torch.cat([image_tensor(s[0],device) for s in ss]),
            torch.from_numpy(np.stack([s[1] for s in ss])[:,None]).float().to(device),
            torch.from_numpy(np.stack([1-s[2] for s in ss])[:,None]).float().to(device))

@torch.inference_mode()
def validate(model,cfg,device):
    model.eval();losses=[];counts={str(t):np.zeros(4,dtype=np.int64) for t in cfg['threshold_candidates']}
    for f,i in scene_ids('validation',cfg):
        x,y,v=batch([(f,i)],0,device);z=model(x);losses.append(float(loss_fn(z,y,v)))
        p=z.sigmoid()[0,0].cpu().numpy();yy=y[0,0].cpu().numpy();vv=v[0,0].cpu().numpy()
        for t in cfg['threshold_candidates']:counts[str(t)]+=confusion(yy,p>=t,vv)
    return float(np.mean(losses)),{t:metrics(c) for t,c in counts.items()}

def save(path,state):
    temporary=Path(str(path)+'.tmp');torch.save(state,temporary);os.replace(temporary,path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--resume')
    p.add_argument('--resource-batch',type=int,choices=[2]);p.add_argument('--local-smoke-steps',type=int,default=0)
    args=p.parse_args();cfg=config();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    smoke=args.local_smoke_steps>0;device='cpu' if smoke else 'cuda'
    if not smoke and not torch.cuda.is_available():raise SystemExit('NO_GPU')
    proof=read(out/'preflight.json') if (out/'preflight.json').exists() else None
    if not smoke and (not proof or proof['status']!='PASS' or proof['device']!='cuda'):
        raise RuntimeError('Passing actual CUDA preflight required')
    if (out/'training-summary.json').exists():raise RuntimeError('Completed main run exists; no second training')
    if (out/'run-config.json').exists() and not args.resume and not args.resource_batch:
        raise RuntimeError('Existing run requires explicit checkpoint resume')
    if args.resource_batch and not args.resume and (out/'last.pt').exists():
        raise RuntimeError('Restore last.pt with --resume; do not restart existing updates')
    seed_all(cfg['seed']);torch.set_num_threads(6)
    if smoke:
        # Same structure and full576 pixels; only2 original scenes, one step, no validation/test.
        cfg=dict(cfg,train_families=[0],train_scenes_per_family=2,max_epochs=1,batch_size=1,accumulation=1)
    model=StrokeUNet();pretrained(model,out/'pretrained',out/'pretrained-load.json');model.to(device)
    encoder=list(model.encoder.parameters());rest=[v for n,v in model.named_parameters() if not n.startswith('encoder.')]
    optimizer=torch.optim.AdamW([dict(params=encoder,lr=cfg['encoder_lr']),dict(params=rest,lr=cfg['decoder_lr'])],weight_decay=cfg['weight_decay'])
    ids=scene_ids('train',cfg);effective=cfg['batch_size']*cfg['accumulation']
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=cfg['max_epochs']*math.ceil(len(ids)/effective))
    scaler=torch.amp.GradScaler('cuda',enabled=device=='cuda' and cfg['amp'])
    epoch=cursor=step=bad_epochs=0;elapsed=0.;best=math.inf;history=[];adjusted=False
    initial_parameter_values={n:float(v.detach().flatten()[0].cpu()) for n,v in model.named_parameters()}
    state=None
    if args.resume:
        state=weights_load(args.resume)
        if state['config']!=cfg:raise RuntimeError('Config/split changed')
        model.load_state_dict(state['model']);optimizer.load_state_dict(state['optimizer']);schedule.load_state_dict(state['scheduler'])
        scaler.load_state_dict(state['scaler']);restore_rng(state['rng'])
        epoch,cursor,step=state['epoch'],state['cursor'],state['step'];elapsed=state['compute_seconds']
        best=state['best_loss'];bad_epochs=state['bad_epochs'];history=state['history'];adjusted=state['resource_adjusted']
        initial_parameter_values=state['initial_parameter_values']
        if math.isfinite(best) and not (out/'best.pt').exists():
            raise RuntimeError('Restore the previously saved best.pt as well as last.pt before resuming')
        print('RESUME',epoch,cursor,step,elapsed,flush=True)
    batch_size=cfg['batch_size'];accumulation=cfg['accumulation']
    if args.resource_batch:
        if adjusted:raise RuntimeError('Only one resource adjustment is allowed')
        batch_size=2;accumulation=effective//batch_size;adjusted=True
    elif state and state['resource_adjusted']:
        batch_size=state['actual_batch'];accumulation=state['actual_accumulation']
    write(out/'run-config.json',dict(config=cfg,kind='LOCAL_MAIN_CODE_SMOKE_ONLY' if smoke else 'COLAB_GPU_MAIN',
        actual_batch=batch_size,actual_accumulation=accumulation,effective_batch=effective,resource_adjusted=adjusted))
    environment=dict(python=sys.version,torch=torch.__version__,cuda=torch.version.cuda,numpy=np.__version__,
        device=device,model_device=str(next(model.parameters()).device),gpu=torch.cuda.get_device_name() if device=='cuda' else None,
        gpu_memory_bytes=torch.cuda.get_device_properties(0).total_memory if device=='cuda' else None,platform=platform.platform(),pid=os.getpid())
    write(out/'environment.json',environment)
    start=time.perf_counter();initial_elapsed=elapsed;last_cursor=cursor
    train_total=state.get('train_total',0.) if state else 0.;train_n=state.get('train_n',0) if state else 0
    def snapshot():
        return dict(model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=schedule.state_dict(),scaler=scaler.state_dict(),
            rng=rng_state(),epoch=epoch,cursor=last_cursor,step=step,compute_seconds=initial_elapsed+time.perf_counter()-start,
            best_loss=best,bad_epochs=bad_epochs,history=history,config=cfg,resource_adjusted=adjusted,
            actual_batch=batch_size,actual_accumulation=accumulation,initial_parameter_values=initial_parameter_values,
            train_total=train_total,train_n=train_n,kind='LOCAL_MAIN_CODE_SMOKE_ONLY' if smoke else 'COLAB_GPU_MAIN')
    stop_reason='MAX_EPOCHS'
    try:
        while epoch<cfg['max_epochs']:
            order=np.random.default_rng(cfg['seed']+epoch).permutation(len(ids));model.train()
            while cursor<len(ids):
                spent=initial_elapsed+time.perf_counter()-start
                if spent>=cfg['main_seconds'] or spent+(proof or {}).get('gpu_compute_seconds',0)>=cfg['total_gpu_seconds']-300:
                    stop_reason='TIME_BUDGET';break
                last_cursor=cursor;optimizer.zero_grad(set_to_none=True)
                group_ids=[ids[j] for j in order[cursor:cursor+effective]]
                for offset in range(0,len(group_ids),batch_size):
                    x,y,v=batch(group_ids[offset:offset+batch_size],epoch+1,device)
                    with torch.autocast(device_type=device,enabled=device=='cuda' and cfg['amp']):z=model(x);loss=loss_fn(z,y,v)
                    if not torch.isfinite(loss):raise RuntimeError('Non-finite training loss')
                    # Exact effective-batch scaling; no spatial downsampling for OOM.
                    scaler.scale(loss*(len(x)/len(group_ids))).backward()
                    train_total+=float(loss.detach())*len(x);train_n+=len(x)
                scaler.step(optimizer);scaler.update();schedule.step();step+=1;cursor+=len(group_ids);last_cursor=cursor
                if step%cfg['checkpoint_every_steps']==0:save(out/'last.pt',snapshot());print('STEP',step,'seconds',spent,flush=True)
                if smoke and step>=args.local_smoke_steps:stop_reason='LOCAL_SMOKE_COMPLETE';break
            if stop_reason in ['TIME_BUDGET','LOCAL_SMOKE_COMPLETE']:break
            vl,vm=validate(model,cfg,device);epoch+=1;cursor=last_cursor=0
            improved=vl<best
            if improved:best=vl;bad_epochs=0
            else:bad_epochs+=1
            history.append(dict(epoch=epoch,step=step,train_loss=train_total/max(1,train_n),validation_loss=vl,
                best_loss=best,seconds=initial_elapsed+time.perf_counter()-start,validation_thresholds=vm,
                peak_gpu_bytes=torch.cuda.max_memory_allocated() if device=='cuda' else 0))
            train_total=0.;train_n=0;write(out/'history.json',history)
            if improved:save(out/'best.pt',snapshot())
            save(out/'last.pt',snapshot());print(json.dumps(history[-1]),flush=True)
            if bad_epochs>=cfg['early_stop_patience']:stop_reason='EARLY_STOP';break
        save(out/'last.pt',snapshot())
    except torch.OutOfMemoryError:
        optimizer.zero_grad(set_to_none=True)
        if device=='cuda':torch.cuda.empty_cache()
        save(out/'last.pt',snapshot());write(out/'interruption.json',dict(reason='OOM',step=step,cursor=last_cursor,resource_adjusted=adjusted))
        raise
    except KeyboardInterrupt:
        optimizer.zero_grad(set_to_none=True);save(out/'last.pt',snapshot())
        write(out/'interruption.json',dict(reason='USER_INTERRUPT',step=step,cursor=last_cursor,resource_adjusted=adjusted))
        raise
    if smoke:
        write(out/'local-main-smoke.json',dict(step=step,cursor=last_cursor,status='CODE_PATH_EXECUTED',main_gpu_training=False))
        return
    if not (out/'best.pt').exists():
        write(out/'interruption.json',dict(reason='NO_COMPLETED_VALIDATION',step=step));raise RuntimeError('No validated best checkpoint')
    best_state=weights_load(out/'best.pt');best_model,_=load_model(out/'best.pt',device)
    changed=[n for n,v in best_model.named_parameters() if initial_parameter_values[n]!=float(v.detach().flatten()[0].cpu())]
    write(out/'parameter-updates.json',dict(method='direct first scalar per named parameter; not a file fingerprint',
        initial=initial_parameter_values,changed_names=changed,changed_tensors=len(changed),
        encoder_changed=sum(n.startswith('encoder.') for n in changed),decoder_changed=sum(not n.startswith('encoder.') for n in changed),
        optimizer_states=len(best_state['optimizer']['state']),best_step=best_state['step']))
    vl,vm=validate(best_model,cfg,device)
    selected=max(cfg['threshold_candidates'],key=lambda t:(vm[str(t)]['f1'],t))
    write(out/'thresholds.json',dict(threshold=selected,selected_on='synthetic_validation_only',best_epoch=best_state['epoch'],metrics=vm))
    probe=make_scene(24,0,0)[0]
    with torch.inference_mode():reference=best_model(image_tensor(probe,device)).sigmoid()[0,0].cpu().numpy()
    np.save(out/'reload-image.npy',probe,allow_pickle=False);np.save(out/'reload-reference.npy',reference,allow_pickle=False)
    write(out/'training-summary.json',dict(kind='COLAB_GPU_MAIN',completed=True,stop_reason=stop_reason,
        best_epoch=best_state['epoch'],last_epoch=epoch,optimizer_steps=step,
        compute_seconds=initial_elapsed+time.perf_counter()-start,preflight_gpu_seconds=proof['gpu_compute_seconds'],
        real_fit=0,train_independent_scenes=len(ids),successful_update_sample_draws=step*effective,
        parameter_tensors_changed=len(changed),resource_adjusted=adjusted))

if __name__=='__main__':main()
