"""No optimizer, backward, training or OCR. One checkpoint; fixed raw-character inputs."""
import time,sys
import numpy as np
from PIL import Image
import torch
from common import *
model_module=load_module('goal16_frozen_model',G16/'model.py')

def main(mode):
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    saved=torch.load(CHECKPOINT,map_location='cpu',weights_only=False)
    assert saved['updates']==5000 and saved['configuration']==CONFIG
    model=model_module.JointModel();model.load_state_dict(saved['model_state']);model.eval()
    for p in model.parameters():p.requires_grad_(False)
    assert sum(p.numel() for p in model.parameters())==115784
    forward=0.;old={}
    if mode=='confirm':
        rows=read(PREVIOUS/'data/train.json');preds={r['id']:r for r in read(PREVIOUS/'fit-M/final-predictions.json')}
        chosen=[]
        for condition in ['complete','unit_hidden','numeric_hidden']:
            chosen.extend(sorted([r for r in rows if r['condition']==condition],key=lambda r:r['id'])[:2])
        for r in chosen:r['image']=str(PREVIOUS/'data'/r['image'])
        jobs=[('reading-confirmation',chosen)];old=preds
    else:
        assert mode=='probe';plan=read(OUT/'frozen-local.json');assert plan['visual_review_completed']
        assert not (OUT/'inference-started.json').exists(),'No second evaluation version'
        write(OUT/'inference-started.json',dict(utc=utc(),checkpoint=str(CHECKPOINT)))
        jobs=[('synthetic',read(OUT/'synthetic/pairs.json')),('real-local',[r for r in read(OUT/'real-local/pairs.json') if r['run_forward']])]
        forward=read(OUT/'reading-confirmation-resource.json')['forward_seconds']
    counts={};start=time.perf_counter()
    with torch.inference_mode():
        for name,rows in jobs:
            predictions=[]
            for offset in range(0,len(rows),32):
                batch=rows[offset:offset+32];allowed=[feature_record(r) for r in batch]
                arrays=[np.asarray(Image.open(Path(x['image']) if Path(x['image']).is_absolute() else OUT/x['image']).convert('L')).copy() for x in allowed]
                assert all(a.shape==(128,512) for a in arrays)
                pixels=(255.-torch.from_numpy(np.stack(arrays)).unsqueeze(1).float())/255.
                chars=torch.tensor([encode_candidate(x['candidate_raw']) for x in allowed]);scopes=torch.tensor([SCOPES.index(x['scope']) for x in allowed])
                if name=='real-local':
                    for i,r in enumerate(batch):
                        np.save(OUT/'real-local/arrays'/f"{r['id']}.npy",pixels[i].numpy())
                assert forward<300
                t=time.perf_counter();logits=model(pixels,chars,scopes);forward+=time.perf_counter()-t
                for i,r in enumerate(batch):
                    pred=annotation_from_classes(logits[i].argmax(-1).tolist())
                    predictions.append(dict(id=r['id'],prediction=pred,part_probabilities=logits[i].softmax(-1).tolist()))
                    if mode=='confirm':
                        assert pred==old[r['id']]['prediction']
                        assert np.allclose(predictions[-1]['part_probabilities'],old[r['id']]['part_probabilities'],atol=1e-6,rtol=1e-5)
            target=OUT/(name if name!='reading-confirmation' else '')/'predictions.json'
            if mode=='confirm':target=OUT/'reading-confirmation.json'
            write(target,predictions);counts[name]=len(predictions)
    unchanged=all(torch.equal(v,saved['model_state'][k]) for k,v in model.state_dict().items());assert unchanged
    resource=dict(utc=utc(),checkpoint=str(CHECKPOINT),checkpoint_updates=saved['updates'],parameter_count=115784,parameters_unchanged=unchanged,
        TRAINING_UPDATES=0,OPTIMIZER_UPDATES=0,OCR_RUNS=0,forward_seconds=forward,loop_wall_seconds=time.perf_counter()-start,counts=counts,
        torch=torch.__version__,python=sys.executable,mode=mode)
    write(OUT/('reading-confirmation-resource.json' if mode=='confirm' else 'inference-resource.json'),resource)
    print(json.dumps(resource));assert forward<=300

if __name__=='__main__':main(sys.argv[1])
