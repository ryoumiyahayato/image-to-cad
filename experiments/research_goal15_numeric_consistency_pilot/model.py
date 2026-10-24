"""Random-initialized dual input network. No parsing or annotation input."""
import torch
from torch import nn
from common import CHARSET,ROLES,STATES

class JointModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.image=nn.Sequential(nn.Conv2d(1,8,3,2,1),nn.ReLU(),nn.Conv2d(8,16,3,2,1),nn.ReLU(),
            nn.Conv2d(16,24,3,2,1),nn.ReLU(),nn.Conv2d(24,24,3,2,1),nn.ReLU(),
            nn.AdaptiveAvgPool2d((4,16)),nn.Flatten(),nn.Linear(24*4*16,48),nn.ReLU())
        self.characters=nn.Embedding(len(CHARSET)+1,24,padding_idx=0)
        self.sequence=nn.GRU(24,32,batch_first=True,bidirectional=True)
        self.scopes=nn.Embedding(2,4)
        self.joint=nn.Sequential(nn.Linear(48+64+4,128),nn.ReLU(),nn.Linear(128,len(ROLES)*len(STATES)))

    def forward(self,pixels,candidate_raw,scope):
        # candidate_raw is a character-code tensor; no token/number/role parsing.
        x=self.image(pixels)
        lengths=(candidate_raw!=0).sum(1).cpu()
        packed=nn.utils.rnn.pack_padded_sequence(self.characters(candidate_raw),lengths,batch_first=True,enforce_sorted=False)
        _,h=self.sequence(packed);text=torch.cat((h[-2],h[-1]),dim=1)
        return self.joint(torch.cat((x,text,self.scopes(scope)),dim=1)).view(-1,len(ROLES),len(STATES))

def global_probabilities(logits):
    probabilities=logits.softmax(-1)
    no_contradiction=(1-probabilities[:,:,1]).prod(1)
    consistent=(probabilities[:,:,0]+probabilities[:,:,3]).prod(1)
    return torch.stack((consistent,1-no_contradiction,no_contradiction-consistent),1).clamp_min(1e-8)
