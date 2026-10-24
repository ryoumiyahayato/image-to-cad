"""Frozen Goal18 E composition diagnostic. No training runtime imports."""
import importlib.util,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
G18=ROOT/'experiments/research_goal18_identity_supervision'
OLD=ROOT/'local-artifacts/research-goal18-identity-supervision-20261023'
OUT=ROOT/'local-artifacts/research-goal19-role-composition-20261023'
CHECKPOINT=OLD/'fit-E/step-2000.pt'
START_EPOCH=1792765560
CONDITIONS=['00','01','10','11']
EDGES=[('00','01','C'),('10','11','C'),('00','10','T'),('01','11','T')]
ATOL=1e-6
RTOL=1e-5
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
base=load_module('goal18_contract19',G18/'common.py')
for name in ['G14','G15','G16','ROLES','STATES','SCOPES','OVERALL','CHARSET','MAX_CHARS','CONFIG','SEED','TRAIN_PYTHON','read','write','parts','label','aggregate','annotation_from_classes','encode_candidate']:
    globals()[name]=getattr(base,name)
def utc():return datetime.now(timezone.utc).isoformat()
def normalize(a):
    import numpy as np
    return ((np.float32(255)-a.astype(np.float32))/np.float32(255))[None]
