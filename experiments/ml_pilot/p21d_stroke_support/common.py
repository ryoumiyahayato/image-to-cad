import json
import random
from pathlib import Path
import numpy as np
import torch

HERE=Path(__file__).resolve().parent

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def config(path=None):return read(path or HERE/'config.json')
def seed_all(seed):
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
def image_tensor(image,device):
    x=torch.from_numpy(np.asarray(image).copy()).permute(2,0,1).float().unsqueeze(0)/255
    mean=x.new_tensor([.485,.456,.406])[None,:,None,None]
    std=x.new_tensor([.229,.224,.225])[None,:,None,None]
    return ((x-mean)/std).to(device)
def loss_fn(logits,target,valid):
    bce=torch.nn.functional.binary_cross_entropy_with_logits(logits,target,reduction='none',pos_weight=logits.new_tensor(8.))
    bce=(bce*valid).sum()/valid.sum().clamp_min(1)
    p=logits.sigmoid()*valid;t=target*valid
    dice=1-(2*(p*t).sum()+1)/(p.sum()+t.sum()+1)
    return .5*bce+.5*dice
def confusion(target,pred,valid):
    t,p,v=target.astype(bool),pred.astype(bool),valid.astype(bool)
    return np.array([(t&p&v).sum(),(~t&p&v).sum(),(~t&~p&v).sum(),(t&~p&v).sum()],dtype=np.int64)
def metrics(counts):
    tp,fp,tn,fn=map(int,counts);precision=tp/max(1,tp+fp);recall=tp/max(1,tp+fn)
    return dict(tp=tp,fp=fp,tn=tn,fn=fn,precision=precision,recall=recall,
                f1=2*precision*recall/max(1e-12,precision+recall),iou=tp/max(1,tp+fp+fn))
def rng_state():
    n=np.random.get_state()
    return dict(python=random.getstate(),numpy=[n[0],torch.from_numpy(n[1].astype(np.int64)),n[2],n[3],n[4]],
                torch=torch.get_rng_state(),cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [])
def restore_rng(s):
    random.setstate(s['python']);n=s['numpy'];np.random.set_state((n[0],n[1].numpy().astype(np.uint32),n[2],n[3],n[4]))
    torch.set_rng_state(s['torch'])
    if torch.cuda.is_available() and s['cuda']:torch.cuda.set_rng_state_all(s['cuda'])
def weights_load(path):return torch.load(path,map_location='cpu',weights_only=True)
