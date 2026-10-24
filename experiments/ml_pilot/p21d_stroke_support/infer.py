import argparse
import time
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from common import config,write,image_tensor
from model import load_model

def starts(length,tile,stride):
    return sorted(set(list(range(0,max(1,length-tile+1),stride))+[max(0,length-tile)]))

@torch.inference_mode()
def tiled(image,model,device='cpu',cfg=None,forward=None):
    cfg=cfg or config();tile=cfg['effective_tile'];halo=cfg['halo'];stride=cfg['inference_stride']
    image=np.asarray(image);h,w=image.shape[:2]
    # Preserve pixel size, including small images. Reflect each source edge.
    ph,pw=max(h,tile),max(w,tile)
    padded=np.pad(image,((halo,ph-h+halo),(halo,pw-w+halo),(0,0)),mode='reflect' if min(h,w)>1 else 'edge')
    acc=np.zeros((ph,pw),np.float32);norm=np.zeros_like(acc)
    a=np.maximum(.05,np.hanning(tile)).astype(np.float32);weight=a[:,None]*a[None,:]
    blocks=0
    for y in starts(ph,tile,stride):
        for x in starts(pw,tile,stride):
            block=padded[y:y+tile+2*halo,x:x+tile+2*halo]
            if forward is None:score=model(image_tensor(block,device)).sigmoid()[0,0].cpu().numpy()
            else:score=forward(block)
            core=score[halo:halo+tile,halo:halo+tile]
            acc[y:y+tile,x:x+tile]+=core*weight;norm[y:y+tile,x:x+tile]+=weight;blocks+=1
    return (acc/norm)[:h,:w],dict(blocks=blocks,source_size=[w,h],input_resized=False,
           tile=tile,halo=halo,stride=stride,minimum_weight=float(norm.min()))

def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--image',required=True)
    p.add_argument('--out',required=True);p.add_argument('--device',default='cpu');args=p.parse_args()
    if args.device=='cuda' and not torch.cuda.is_available():raise SystemExit('NO_GPU')
    torch.set_num_threads(6);model,state=load_model(args.weights,args.device)
    image=np.asarray(Image.open(args.image).convert('RGB'));t=time.perf_counter();scores,info=tiled(image,model,args.device,state['config'])
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);np.save(out/'support.npy',scores,allow_pickle=False)
    Image.fromarray((scores*255).astype(np.uint8)).save(out/'support.png')
    write(out/'inference.json',dict(**info,seconds=time.perf_counter()-t,model_kind=state.get('kind','MAIN'),
          model_device=str(next(model.parameters()).device),source=str(Path(args.image).resolve()),
          semantic='uncalibrated visible-stroke support; not authorization to delete/connect',cad_written=False))

if __name__=='__main__':main()
