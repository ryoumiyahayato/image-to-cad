"""ResNet18-compatible encoder and full-resolution U-Net decoder.
Encoder adapted from torchvision (BSD-3-Clause), see TORCHVISION-LICENSE.txt.
No torchvision installation or classifier image-resize pipeline is required.
"""
from pathlib import Path
import torch
from torch import nn
from torch.nn import functional as F
from common import config,weights_load,write

class BasicBlock(nn.Module):
    def __init__(self,a,b,stride=1):
        super().__init__()
        self.conv1=nn.Conv2d(a,b,3,stride,1,bias=False);self.bn1=nn.BatchNorm2d(b)
        self.relu=nn.ReLU(inplace=True);self.conv2=nn.Conv2d(b,b,3,1,1,bias=False);self.bn2=nn.BatchNorm2d(b)
        self.downsample=nn.Sequential(nn.Conv2d(a,b,1,stride,bias=False),nn.BatchNorm2d(b)) if stride!=1 or a!=b else None
    def forward(self,x):
        z=x if self.downsample is None else self.downsample(x)
        return self.relu(self.bn2(self.conv2(self.relu(self.bn1(self.conv1(x)))))+z)

class Encoder(nn.Module):
    def __init__(self):
        super().__init__();self.conv1=nn.Conv2d(3,64,7,2,3,bias=False);self.bn1=nn.BatchNorm2d(64)
        self.relu=nn.ReLU(inplace=True);self.maxpool=nn.MaxPool2d(3,2,1)
        self.layer1=nn.Sequential(BasicBlock(64,64),BasicBlock(64,64))
        self.layer2=nn.Sequential(BasicBlock(64,128,2),BasicBlock(128,128))
        self.layer3=nn.Sequential(BasicBlock(128,256,2),BasicBlock(256,256))
        self.layer4=nn.Sequential(BasicBlock(256,512,2),BasicBlock(512,512))
    def forward(self,x):
        a=self.relu(self.bn1(self.conv1(x)));b=self.layer1(self.maxpool(a));c=self.layer2(b);d=self.layer3(c);e=self.layer4(d)
        return a,b,c,d,e

def conv(a,b):return nn.Sequential(nn.Conv2d(a,b,3,padding=1,bias=False),nn.GroupNorm(8,b),nn.ReLU(inplace=True),
                                  nn.Conv2d(b,b,3,padding=1,bias=False),nn.GroupNorm(8,b),nn.ReLU(inplace=True))
class StrokeUNet(nn.Module):
    def __init__(self):
        super().__init__();self.encoder=Encoder()
        self.d4=conv(512+256,128);self.d3=conv(128+128,64);self.d2=conv(64+64,32)
        self.d1=conv(32+64,24);self.full=conv(24+3,16);self.head=nn.Conv2d(16,1,1)
    def train(self,mode=True):
        super().train(mode)
        # Small-batch transfer: keep pretrained running statistics, train affine/conv parameters.
        for m in self.encoder.modules():
            if isinstance(m,nn.BatchNorm2d):m.eval()
        return self
    def forward(self,x):
        a,b,c,d,e=self.encoder(x)
        up=lambda z,s:F.interpolate(z,size=s.shape[-2:],mode='bilinear',align_corners=False)
        z=self.d4(torch.cat([up(e,d),d],1));z=self.d3(torch.cat([up(z,c),c],1))
        z=self.d2(torch.cat([up(z,b),b],1));z=self.d1(torch.cat([up(z,a),a],1))
        return self.head(self.full(torch.cat([up(z,x),x],1)))

def pretrained(model,cache,record=None):
    cfg=config();cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    path=cache/cfg['pretrained_file']
    if not path.exists():
        # Official PyTorch download helper; no new fingerprint manifests.
        torch.hub.download_url_to_file(cfg['pretrained_url'],str(path),progress=False)
    state=weights_load(path);encoder={k:v for k,v in state.items() if not k.startswith('fc.')}
    model.encoder.load_state_dict(encoder,strict=True)
    current=model.encoder.state_dict()
    missing=[k for k in current if k not in encoder]
    # This official checkpoint predates BatchNorm's bookkeeping counter.
    if any(not k.endswith('.num_batches_tracked') or int(current[k])!=0 for k in missing):
        raise RuntimeError(f'Unexpected encoder tensors missing: {missing}')
    same=all(torch.equal(current[k].cpu(),v) for k,v in encoder.items())
    info=dict(source=cfg['pretrained_url'],file=str(path),bytes=path.stat().st_size,
              loaded_tensors=len(encoder),all_encoder_tensors_equal=same,zero_initialized_batch_counters=missing,
              excluded=['fc.weight','fc.bias'],
              training_data='ImageNet-1K (pretraining only; dataset not downloaded)',
              use='isolated research; no production/redistribution rights inferred',
              code_license='BSD-3-Clause; pretrained terms warning retained in MODEL-SOURCE.md')
    if not same:raise RuntimeError('Pretrained encoder tensor mismatch')
    if record:write(record,info)
    return info

def load_model(path,device='cpu'):
    model=StrokeUNet();state=weights_load(path);model.load_state_dict(state['model'],strict=True)
    return model.to(device).eval(),state
