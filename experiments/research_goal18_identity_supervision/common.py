"""Goal18: shared existing contract; two separately restored bounded training arms."""
import json,sys,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
G16=ROOT/'experiments/research_goal16_numeric_fit_diagnosis'
OLD=ROOT/'local-artifacts/research-goal16-numeric-fit-diagnosis-20261023'
G17=ROOT/'local-artifacts/research-goal17-frozen-numeric-probe-20261023'
OUT=ROOT/'local-artifacts/research-goal18-identity-supervision-20261023'
INITIAL=OLD/'fit-M/last.pt';START_EPOCH=1792763020
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=load_module('goal16_contract18',G16/'common.py')
for name in ['G14','G15','ROLES','STATES','SCOPES','OVERALL','CHARSET','CHAR_TO_ID','MAX_CHARS','CONFIG','SEED','TRAIN_PYTHON','read','write','parts','label','aggregate','parse_candidate','feature_record','annotation_from_classes','encode_candidate']:
    globals()[name]=getattr(base,name)
sys.path.append(str(G16))
def utc():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
