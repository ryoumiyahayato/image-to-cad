"""Exactly one bounded CPU training run. Reads synthetic train/validation only."""
import argparse
import json
import os
import platform
import random
import sys
import time
import numpy as np
import torch
from common import OUT, CFG_PATH, FractionCNN, tensor, probabilities, binary_metrics, read_json, write_json

def select_thresholds(y, p):
    candidates = np.round(np.arange(.05,.951,.01),2)
    metrics = [(float(t), binary_metrics(y,p,t)) for t in candidates]
    # Stable tie-break: larger threshold, to reduce unnecessary review.
    threshold, metric = max(metrics,key=lambda pair:(pair[1]['f1'],pair[0]))
    negative = [t for t,m in metrics if t <= threshold and m['tn']+m['fn']>=20
                and m['tn']/(m['tn']+m['fn']) >= .98]
    positive = [t for t,m in metrics if t >= threshold and m['tp']+m['fp']>=20 and m['precision']>=.95]
    return dict(binary_threshold=threshold, negative_cutoff=max(negative,default=0.0),
                positive_cutoff=min(positive,default=1.01),validation_binary=metric,
                selected_on='synthetic_validation_only',real_data_opened=False,test_opened=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume',type=str);args=parser.parse_args()
    cfg=read_json(CFG_PATH)
    if (OUT/'final-model.pt').exists(): raise RuntimeError('Completed run exists; no second fit allowed.')
    torch.set_num_threads(cfg['threads']);torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    random.seed(cfg['seed']);np.random.seed(cfg['seed']);torch.manual_seed(cfg['seed'])
    x=np.load(OUT/'train-images.npy',mmap_mode='r');y=np.load(OUT/'train-labels.npy')
    vx=np.load(OUT/'validation-images.npy',mmap_mode='r');vy=np.load(OUT/'validation-labels.npy')
    model=FractionCNN();optimizer=torch.optim.AdamW(model.parameters(),lr=cfg['learning_rate'],weight_decay=cfg['weight_decay'])
    loss_fn=torch.nn.BCEWithLogitsLoss()
    env=dict(python=sys.version,executable=sys.executable,torch=torch.__version__,numpy=np.__version__,
             platform=platform.platform(),device='cpu',threads=torch.get_num_threads(),pid=os.getpid(),
             model=str(model),parameter_count=sum(p.numel() for p in model.parameters()),config=cfg)
    write_json(OUT/'training-environment.json',env)
    # Run intent and actual model/environment are saved before any backward call.
    write_json(OUT/'training-config.json',cfg)
    start_epoch=0;history=[];elapsed_before=0.0
    if args.resume:
        state=torch.load(args.resume,map_location='cpu',weights_only=True)
        model.load_state_dict(state['model_state']);optimizer.load_state_dict(state['optimizer_state'])
        torch.set_rng_state(state['torch_rng']);start_epoch=state['epoch'];history=state['history']
        elapsed_before=state['training_seconds']
    else:
        torch.save({'model_state':model.state_dict(),'config':cfg},OUT/'initial-model.pt')
    initial=torch.load(OUT/'initial-model.pt',map_location='cpu',weights_only=True)['model_state']
    if not args.resume:
        t=time.perf_counter();probe=model(tensor(np.array(x[:8])));loss=loss_fn(probe,torch.tensor(y[:8]).float());loss.backward()
        grad=float(torch.sqrt(sum((p.grad**2).sum() for p in model.parameters() if p.grad is not None)))
        write_json(OUT/'forward-backward.json',dict(loss=float(loss.detach()),gradient_l2=grad,
                   finite=bool(torch.isfinite(loss)),seconds=time.perf_counter()-t,optimizer_steps=0))
        if not torch.isfinite(loss) or grad<=0: raise RuntimeError('Forward/backward check failed')
        optimizer.zero_grad(set_to_none=True)
    t=time.perf_counter()
    for epoch in range(start_epoch,cfg['epochs']):
        if epoch>start_epoch and elapsed_before+time.perf_counter()-t >= cfg['training_time_limit_seconds']: break
        et=time.perf_counter();model.train();order=torch.randperm(len(x)).numpy();total=0.;steps=0
        for begin in range(0,len(x),cfg['batch_size']):
            ids=order[begin:begin+cfg['batch_size']]
            bx=tensor(np.array(x[ids]));by=torch.from_numpy(y[ids]).float()
            optimizer.zero_grad(set_to_none=True);loss=loss_fn(model(bx),by);loss.backward();optimizer.step()
            total+=float(loss.detach())*len(ids);steps+=1
        model.eval();vp=probabilities(model,vx,cfg['batch_size'])
        val_loss=float(loss_fn(torch.logit(torch.from_numpy(vp).clamp(1e-7,1-1e-7)),torch.from_numpy(vy).float()))
        row=dict(epoch=epoch+1,train_loss=total/len(x),validation_loss=val_loss,
                 validation_at_half=binary_metrics(vy,vp,.5),seconds=time.perf_counter()-et,optimizer_steps=steps)
        history.append(row);write_json(OUT/'training-history.json',history)
        torch.save(dict(model_state=model.state_dict(),optimizer_state=optimizer.state_dict(),torch_rng=torch.get_rng_state(),
                   epoch=epoch+1,config=cfg,history=history,training_seconds=elapsed_before+time.perf_counter()-t),OUT/'checkpoint.pt')
        print(json.dumps(row),flush=True)
    elapsed=elapsed_before+time.perf_counter()-t
    thresholds=select_thresholds(vy,vp);write_json(OUT/'thresholds.json',thresholds)
    torch.save(dict(model_state=model.state_dict(),config=cfg,epoch=history[-1]['epoch']),OUT/'final-model.pt')
    changes=[]
    for name,value in model.state_dict().items():
        delta=value-initial[name]
        changes.append(dict(name=name,elements=value.numel(),changed_elements=int(torch.count_nonzero(delta)),
                            delta_l2=float(torch.linalg.vector_norm(delta)),max_abs_delta=float(delta.abs().max()),
                            initial_first8=initial[name].flatten()[:8].tolist(),final_first8=value.flatten()[:8].tolist()))
    write_json(OUT/'parameter-changes.json',dict(comparison='direct_tensor_subtraction_no_fingerprints',layers=changes))
    fixed=np.array(vx[:12]);np.save(OUT/'reload-fixed-inputs.npy',fixed,allow_pickle=False)
    write_json(OUT/'reload-reference.json',dict(pid=os.getpid(),probabilities=probabilities(model,fixed).tolist(),
                                              source='validation-first12',torch=torch.__version__))
    np.save(OUT/'validation-probabilities.npy',vp,allow_pickle=False)
    write_json(OUT/'training-summary.json',dict(training_seconds=elapsed,epochs=len(history),
               optimizer_steps=sum(r['optimizer_steps'] for r in history),real_fit_samples=0,
               completed=True,stopped_by_time=history[-1]['epoch']<cfg['epochs']))
    print('TRAINING_COMPLETE',elapsed,thresholds,flush=True)

if __name__=='__main__':main()
