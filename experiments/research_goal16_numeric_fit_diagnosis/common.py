"""Goal16: same Goal15 contract and numerical configuration; separate files and fit budgets."""
import sys,json,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
G15=ROOT/'experiments/research_goal15_numeric_consistency_pilot'
OLD_OUT=ROOT/'local-artifacts/research-goal15-numeric-consistency-pilot-20261023'
OUT=ROOT/'local-artifacts/research-goal16-numeric-fit-diagnosis-20261023'

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

base=load_module('goal15_fixed_common',G15/'common.py')
for name in ['ROLES','STATES','SCOPES','OVERALL','SEED','TRAIN_PYTHON','CHARSET','CHAR_TO_ID','MAX_CHARS','CONFIG',
             'read','write','aggregate','label','parts','parse_candidate','feature_record','annotation_from_classes','encode_candidate','G14']:
    globals()[name]=getattr(base,name)
GOAL_START_EPOCH=1792756234
FITS={'D':dict(max_updates=2000,max_training_seconds=240),
      'M':dict(max_updates=5000,combined_training_seconds=900,checkpoints=[500,2000,5000])}
MECHANISMS=['fraction_integer','fraction_numerator','fraction_denominator','mixed_whole','mixed_boundary','unit',
            'decimal_point','sign','context','numeric_equivalence','unicode_boundary']

def utc():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
