"""One frozen E pass: confirm existing 00/11 before evaluating new 01/10."""
import time
import numpy as np
import torch
from common import *
scorer=load_module('goal19_explicit_score',HERE/'score.py')
model_module=load_module('goal16_model19',G16/'model.py')
def main():
    start=time.perf_counter();plan=read(OUT/'frozen-plan.json');dest=OUT/'evaluation'
    dest.mkdir(exist_ok=True);assert not (dest/'started.json').exists()
    for rel in plan['sources']:assert (ROOT/rel).read_bytes()==(OUT/'frozen-source'/rel).read_bytes(),rel
    assert plan['pairs']==read(OUT/'data/pairs.json')
    torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.manual_seed(SEED);torch.use_deterministic_algorithms(True)
    saved=torch.load(CHECKPOINT,map_location='cpu',weights_only=False)
    for k in ['arm','historical_updates','new_updates','total_updates']:assert saved[k]==plan['checkpoint_identity'][k]
    assert saved['configuration']==CONFIG
    model=model_module.JointModel();model.load_state_dict(saved['model_state']);model.eval();model.requires_grad_(False)
    assert sum(p.numel() for p in model.parameters())==115784
    before={k:v.clone() for k,v in model.state_dict().items()};forward=0.;all_rows=[];readback={};conditions={}
    write(dest/'started.json',dict(utc=utc(),identity=plan['checkpoint_identity'],training_updates=0,optimizer_constructed=False))
    for cond in ['00','11','01','10']:
        if cond=='01':
            valid=all(v['valid'] for v in readback.values());write(dest/'readback.json',dict(valid=valid,conditions=readback))
            if not valid:raise RuntimeError('Reading confirmation failed; new-condition inference is stopped')
        rows=[r for r in plan['pairs'] if r['condition']==cond];preds=[]
        with torch.inference_mode():
            for offset in range(0,len(rows),32):
                batch=rows[offset:offset+32]
                pixels=torch.stack([torch.from_numpy(np.load(OUT/r['array'])) for r in batch])
                chars=torch.tensor([encode_candidate(r['candidate_raw']) for r in batch],dtype=torch.long)
                scopes=torch.tensor([SCOPES.index(r['scope']) for r in batch],dtype=torch.long)
                assert forward<plan['forward_limit_seconds']
                tick=time.perf_counter();logits=model(pixels,chars,scopes);forward+=time.perf_counter()-tick
                for i,r in enumerate(batch):preds.append(dict(id=r['id'],prediction=annotation_from_classes(logits[i].argmax(-1).tolist()),part_probabilities=logits[i].softmax(-1).tolist()))
        joined=[dict(r,**{k:v for k,v in p.items() if k!='id'}) for r,p in zip(rows,preds)]
        assert [r['id'] for r in rows]==[r['id'] for r in preds]
        write(dest/f'{cond}-predictions.json',preds);write(dest/f'{cond}-joined.json',joined)
        conditions[cond]=scorer.detailed(joined);all_rows.extend(joined)
        if cond in ['00','11']:
            dataset='train-E' if cond=='00' else 'sealed-E';baseline={r['id']:r for r in read(OLD/f'evaluation/E/{dataset}-predictions.json')};checks=[]
            for r in joined:
                b=baseline[r['baseline_pair_id']];pa=np.array(r['part_probabilities']);pb=np.array(b['part_probabilities'])
                checks.append(dict(id=r['id'],baseline_id=r['baseline_pair_id'],prediction_equal=r['prediction']==b['prediction'],probabilities_close=bool(np.allclose(pa,pb,atol=ATOL,rtol=RTOL)),max_abs_probability_difference=float(np.abs(pa-pb).max())))
            expected=plan['baseline_expected'][cond];s=conditions[cond]
            readback[cond]=dict(valid=all(c['prediction_equal'] and c['probabilities_close'] for c in checks) and s['global_metrics']['full_parts_exact']['n']==expected['all_roles'] and s['target']['contradiction_recall']['n']==expected['target_contradictions'],checks=checks)
    unchanged=all(torch.equal(v,before[k]) and torch.equal(v,saved['model_state'][k]) for k,v in model.state_dict().items())
    assert unchanged and forward<=120 and all(p.grad is None and not p.requires_grad for p in model.parameters())
    transitions=scorer.transitions(all_rows)
    write(dest/'metrics.json',dict(conditions=conditions,transitions=transitions))
    write(dest/'resource.json',dict(utc=utc(),wall_seconds=time.perf_counter()-start,forward_seconds=forward,model_parameters_unchanged=unchanged,state_tensors_compared=len(before),training_updates=0,optimizer_constructed=False,optimizer_updates=0,backward_calls=0,OCR_runs=0,model='GOAL18_E_FROZEN',pairs_evaluated=len(all_rows),real_evaluation='NOT_RERUN',old_validation='NOT_RERUN',source_bytes_unchanged=True,device='cpu',threads=4))
    print(json.dumps(dict(conditions={k:dict(target=v['target'],all_roles=v['global_metrics']['full_parts_exact'],context=v['context'],separation=v['failure_separation'],four_roles=v['four_roles']) for k,v in conditions.items()},transitions={k:v['summary'] for k,v in transitions.items()},forward_seconds=forward),ensure_ascii=False))
if __name__=='__main__':main()
