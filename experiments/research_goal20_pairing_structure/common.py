"""Goal20 fixed pairing intervention; all numerical contracts inherited unchanged."""
import sys,json,importlib.util
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
G18=ROOT/'experiments/research_goal18_identity_supervision'
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=load_module('goal18_contract20',G18/'common.py')
for name in ['G14','G15','G16','ROLES','STATES','SCOPES','OVERALL','CHARSET','CHAR_TO_ID','MAX_CHARS','CONFIG','SEED','TRAIN_PYTHON','read','write','parts','label','aggregate','parse_candidate','feature_record','annotation_from_classes','encode_candidate']:
    globals()[name]=getattr(base,name)
OUT=ROOT/'local-artifacts/research-goal20-pairing-structure-20261023'
OLD=ROOT/'local-artifacts/research-goal16-numeric-fit-diagnosis-20261023'
INITIAL=OLD/'fit-M/last.pt'
START_EPOCH=1792767936
UPDATES=1992
CONDITIONS=['00','01','10','11']
RING=[(0,0),(1,0),(1,1),(2,1),(2,2),(3,2),(3,3),(0,3),(0,1),(3,1),(3,0),(2,0),(2,3),(1,3),(1,2),(0,2)]
NODES=[(i,j) for i in range(4) for j in range(4)]
def utc():return datetime.now(timezone.utc).isoformat()
def edge(a,b):return tuple(sorted((tuple(a),tuple(b))))
def graphs():
    g={edge((i,j),(i^1,j)) for i,j in NODES}|{edge((i,j),(i,j^1)) for i,j in NODES}
    s={edge(a,b) for a,b in zip(RING,RING[1:]+RING[:1])}
    full={edge(a,b) for a in NODES for b in NODES if sum(x!=y for x,y in zip(a,b))==1}
    return g,s,full
def relation_role(a,b):
    assert sum(x!=y for x,y in zip(a,b))==1
    return 'numerator' if a[0]!=b[0] else 'denominator'
def change(a,b):
    positions=[i for i,(x,y) in enumerate(zip(a,b)) if x!=y]
    return dict(digits=len(a),changed_positions=positions,changed_digits=len(positions),variant='permutation' if sorted(a)==sorted(b) else 'replacement')
