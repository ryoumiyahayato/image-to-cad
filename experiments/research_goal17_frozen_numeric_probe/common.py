"""Goal17 read-only probe. Import the existing task, codec and metric definitions."""
import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
G16=ROOT/'experiments/research_goal16_numeric_fit_diagnosis'
PREVIOUS=ROOT/'local-artifacts/research-goal16-numeric-fit-diagnosis-20261023'
OUT=ROOT/'local-artifacts/research-goal17-frozen-numeric-probe-20261023'
CHECKPOINT=PREVIOUS/'fit-M/last.pt'
START_EPOCH=1792759692
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=load_module('goal16_contract',G16/'common.py')
for name in ['G14','G15','ROLES','STATES','SCOPES','OVERALL','CHARSET','CHAR_TO_ID','MAX_CHARS','CONFIG','SEED','TRAIN_PYTHON','read','write','parts','label','aggregate','parse_candidate','feature_record','annotation_from_classes','encode_candidate']:
    globals()[name]=getattr(base,name)
def utc():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
