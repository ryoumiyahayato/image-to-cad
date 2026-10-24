"""Reuses Goal15 network, adapter, optimizer and loss exactly; separate orchestration only."""
import time,os
IMPORT_START=time.perf_counter()
import numpy as np
import torch
from common import *
from model import JointModel,global_probabilities
legacy=load_module('goal15_adapter_only',G15/'worker.py')
metrics=load_module('goal15_metrics_only',G15/'evaluate.py')
configure=legacy.configure
inputs=legacy.inputs
load_pixels=legacy.load_pixels
memory=legacy.memory
IMPORT_SECONDS=time.perf_counter()-IMPORT_START

def optimizer_for(model):
    return torch.optim.Adam(model.parameters(),lr=CONFIG['learning_rate'],betas=tuple(CONFIG['adam_betas']),eps=CONFIG['adam_eps'],weight_decay=CONFIG['weight_decay'])

def targets(rows):
    return torch.tensor([[STATES.index(r['annotation']['parts'][role]) for role in ROLES] for r in rows]),torch.tensor([OVERALL.index(r['annotation']['overall']) for r in rows])

def losses(logits,rows):
    target,overall=targets(rows);weights=torch.tensor(CONFIG['role_class_weights'])
    part=torch.nn.functional.cross_entropy(logits.reshape(-1,4),target.reshape(-1),weight=weights)
    global_loss=torch.nn.functional.nll_loss(global_probabilities(logits).log(),overall)
    return part+CONFIG['overall_loss_weight']*global_loss,part,global_loss

def summarize(rows,predictions):
    predictions={r['id']:r for r in predictions};joined=[dict(r,prediction=predictions[r['id']]['prediction']) for r in rows]
    return dict(global_metrics=metrics.global_metrics(joined),roles=metrics.role_metrics(joined),complete_cross=metrics.complete_cross(joined))

@torch.no_grad()
def predict(model,rows,cache):
    model.eval();result=[];part_sums=[0.]*8;global_sum=0.
    for start in range(0,len(rows),32):
        batch=rows[start:start+32];logits=model(*inputs(batch,cache));prob=logits.softmax(-1);target,overall=targets(batch)
        weights=torch.tensor(CONFIG['role_class_weights'])
        unweighted=torch.nn.functional.cross_entropy(logits.reshape(-1,4),target.reshape(-1),reduction='none').view(-1,8)
        for i,role in enumerate(ROLES):part_sums[i]+=float(unweighted[:,i].sum())
        global_sum+=float(torch.nn.functional.nll_loss(global_probabilities(logits).log(),overall,reduction='sum'))
        for i,row in enumerate(batch):
            result.append(dict(id=row['id'],prediction=annotation_from_classes(logits[i].argmax(-1).tolist()),part_probabilities=prob[i].tolist(),
                target_indices=target[i].tolist(),role_nll=unweighted[i].tolist(),weighted_role_nll=(unweighted[i]*weights[target[i]]).tolist()))
    return result,dict(mean_unweighted_role_nll={r:part_sums[i]/len(rows) for i,r in enumerate(ROLES)},mean_aggregate_nll=global_sum/len(rows))

def save_checkpoint(path,model,opt,updates,generator):
    torch.save(dict(model_state=model.state_dict(),optimizer_state=opt.state_dict(),updates=updates,configuration=CONFIG,
       torch_rng_state=torch.get_rng_state(),sampler_rng_state=generator.get_state(),checkpoint_rule='predeclared milestone or final; final is primary'),path)

def restored_initial():
    model=JointModel();saved=torch.load(OUT/'initial.pt',map_location='cpu',weights_only=False);model.load_state_dict(saved['model_state'])
    assert all(torch.equal(v,saved['model_state'][k]) for k,v in model.state_dict().items())
    return model
