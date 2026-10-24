"""Goal15 isolated configuration. Imports only Goal14's pure task contract."""
import sys
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'local-artifacts/research-goal15-numeric-consistency-pilot-20261023'
G14=ROOT/'experiments/research_goal14_numeric_consistency_task'
sys.path.insert(0,str(G14))
from task import ROLES,STATES,read,write,aggregate,label,parts,parse_candidate
SCOPES=['NUMBER_UNIT','NUMBER_UNIT_CONTEXT']
OVERALL=['CONSISTENT','CONTRADICTION','INSUFFICIENT']
SEED=20261023
TRAIN_PYTHON=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/runtime/Scripts/python.exe'
# Fixed from the supported grammar, before looking at prediction results.
CHARSET=list(' 0123456789/".-+()ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz¼½¾″”')
CHARSET=list(dict.fromkeys(CHARSET))
CHAR_TO_ID={c:i+1 for i,c in enumerate(CHARSET)}
MAX_CHARS=40
CONFIG=dict(seed=SEED,cpu_threads=4,interop_threads=1,batch_size=32,learning_rate=.001,
            optimizer='Adam',adam_betas=[.9,.999],adam_eps=1e-8,weight_decay=0.,gradient_clip_norm=5.,max_updates=500,max_training_seconds=900,
            role_class_weights=[1.,1.5,1.5,.25],overall_loss_weight=.5,
            input_shape=[1,128,512],preprocessing='PNG grayscale uint8 -> float32 (255-x)/255; no resize/crop/augmentation',
            checkpoint='last valid optimizer update; no validation or test checkpoint selection',
            characters=CHARSET,max_characters=MAX_CHARS,scopes=SCOPES,roles=list(ROLES),states=list(STATES),
            overall=list(OVERALL),label_contract='Goal14 task.py unchanged; Goal15 conservative observable occlusion roles v1')

def feature_record(row):
    return {k:row[k] for k in ['image','candidate_raw','scope']}

def annotation_from_classes(values):
    status={r:STATES[int(v)] for r,v in zip(ROLES,values)}
    return dict(parts=status,**aggregate(status))

def encode_candidate(raw):
    if len(raw)>MAX_CHARS or any(c not in CHAR_TO_ID for c in raw):raise ValueError('Out-of-contract candidate')
    return [CHAR_TO_ID[c] for c in raw]+[0]*(MAX_CHARS-len(raw))
