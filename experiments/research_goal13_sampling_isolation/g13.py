"""Goal13 isolated paths and plain JSON; no hashes or production writes."""
import datetime
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'local-artifacts/research-goal13-sampling-isolation-20261023'
G12 = ROOT / 'local-artifacts/research-goal12-ocr-call-consistency-20261023'
METHOD12 = ROOT / 'experiments/research_goal12_ocr_call_consistency'
RUNTIME = ROOT / 'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
SOURCE = ROOT / 'local-artifacts/research-goal11-formula-model-20261023/normal-B/source-page.png'

def load(path):
    return json.loads(Path(path).read_text('utf8'))

def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
        default=lambda x: asdict(x) if is_dataclass(x) else x.tolist() if hasattr(x, 'tolist') else str(x)), 'utf8')

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def setup():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RUNTIME))
    sys.path.append(str(METHOD12))

def target_record(meta, name):
    matches = [(c, r) for c in meta['recognition_calls'] for r in c['images'] if name in r['targets']]
    if len(matches) != 1:
        raise RuntimeError(f'Nonunique captured source object: {name}')
    call, row = matches[0]
    batch = next(b for b in meta['batches'] if b['rec_call'] == call['rec_call'] and row['input_index'] in b['indices'])
    return call, row, batch, batch['indices'].index(row['input_index'])
