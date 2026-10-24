"""Small candidate-free digit sequence reader. Blank=0; digit zero=1."""
import math
import numpy as np
import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
from PIL import Image

BLANK=0

def normalize(pixels):
    """Only pixels determine height, effective width and padding."""
    if pixels.ndim==3:pixels=np.array(Image.fromarray(pixels).convert('L'))
    h,w=pixels.shape
    width=max(1,math.ceil(32*w/h));padded=4*math.ceil(width/4)
    image=np.array(Image.fromarray(pixels).resize((width,32),Image.Resampling.BILINEAR))
    array=np.ones((1,32,padded),dtype=np.float32)
    array[0,:,:width]=image.astype(np.float32)/127.5-1
    return array,width,padded//4

def batch_arrays(arrays):
    max_width=max(a.shape[-1] for a in arrays)
    batch=np.ones((len(arrays),1,32,max_width),dtype=np.float32)
    for i,a in enumerate(arrays):batch[i,:,:,:a.shape[-1]]=a
    return torch.from_numpy(batch),torch.tensor([a.shape[-1]//4 for a in arrays],dtype=torch.long)

def encode(text):return [int(c)+1 for c in text]

def decode_path(path):
    text=[];previous=None
    for c in path:
        c=int(c)
        if c!=previous and c!=BLANK:text.append(str(c-1))
        previous=c
    return ''.join(text)

def decode(logits,lengths):
    paths=logits.argmax(-1).detach().cpu()
    return [decode_path(paths[i,:int(n)].tolist()) for i,n in enumerate(lengths)]

class DigitReader(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn=nn.Sequential(
            nn.Conv2d(1,24,3,padding=1),nn.ReLU(),nn.MaxPool2d((2,2)),
            nn.Conv2d(24,48,3,padding=1),nn.ReLU(),nn.MaxPool2d((2,2)),
            nn.Conv2d(48,64,3,padding=1),nn.ReLU(),nn.MaxPool2d((2,1)),
            nn.Conv2d(64,64,3,padding=1),nn.ReLU())
        self.sequence=nn.GRU(64,48,batch_first=True,bidirectional=True)
        self.output=nn.Linear(96,11)
    def forward(self,pixels,valid_time_lengths):
        x=self.cnn(pixels).mean(2).transpose(1,2)
        packed=pack_padded_sequence(x,valid_time_lengths.cpu(),batch_first=True,enforce_sorted=False)
        packed,_=self.sequence(packed)
        x,_=pad_packed_sequence(packed,batch_first=True,total_length=x.shape[1])
        return self.output(x)
