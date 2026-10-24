"""Reuse Goal16 numerical implementation. Only data loading and orchestration differ."""
import time
IMPORT_START=time.perf_counter()
import numpy as np
import torch
from PIL import Image
from common import *
runtime=load_module('goal16_runtime18',G16/'runtime.py')
JointModel=runtime.JointModel;configure=runtime.configure;inputs=runtime.inputs;losses=runtime.losses;predict=runtime.predict;memory=runtime.memory
metrics=runtime.metrics

def exact(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and torch.equal(a,b)
    if isinstance(a,dict):return a.keys()==b.keys() and all(exact(v,b[k]) for k,v in a.items())
    if isinstance(a,(list,tuple)):return len(a)==len(b) and all(exact(x,y) for x,y in zip(a,b))
    return a==b

def restored(mode):
    saved=torch.load(INITIAL,map_location='cpu',weights_only=False);assert saved['updates']==5000 and saved['configuration']==CONFIG
    model=JointModel();model.load_state_dict(saved['model_state']);assert sum(p.numel() for p in model.parameters())==115784
    assert exact(model.state_dict(),saved['model_state'])
    opt=runtime.optimizer_for(model)
    if mode=='RESTORE':
        opt.load_state_dict(saved['optimizer_state']);assert exact(opt.state_dict(),saved['optimizer_state'])
    torch.set_rng_state(saved['torch_rng_state'])
    return model,opt,saved

def cache_pixels(rows):
    cache={}
    for r in rows:
        if r['image'] in cache:continue
        p=Path(r['image']);p=p if p.is_absolute() else OUT/p
        assert p.resolve().is_relative_to((OUT/'data/images').resolve()) or p.resolve().is_relative_to((OLD/'data/images').resolve())
        a=np.asarray(Image.open(p).convert('L')).copy();assert a.shape==(128,512)
        cache[r['image']]=torch.from_numpy(a)
    return cache

def checkpoint(path,model,opt,arm,updates):
    torch.save(dict(model_state=model.state_dict(),optimizer_state=opt.state_dict(),configuration=CONFIG,arm=arm,
        historical_updates=5000,new_updates=updates,total_updates=5000+updates,torch_rng_state=torch.get_rng_state(),
        next_batch_plan_index=updates,initial_checkpoint=str(INITIAL),selection='Last predeclared completed checkpoint, never metric-selected'),path)

def joined(rows,preds):
    by={p['id']:p['prediction'] for p in preds};return [dict(r,prediction=by[r['id']]) for r in rows]

def train_summary(rows,preds):
    rr=joined(rows,preds);return dict(global_metrics=metrics.global_metrics(rr),roles=metrics.role_metrics(rr))
IMPORT_SECONDS=time.perf_counter()-IMPORT_START
