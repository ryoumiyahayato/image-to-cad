"""Goal21: independent region reading, then bounded candidate comparison."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'local-artifacts/research-goal21-role-digit-reading-20261024'
G20 = ROOT / 'local-artifacts/research-goal20-pairing-structure-20261023'
G16 = ROOT / 'local-artifacts/research-goal16-numeric-fit-diagnosis-20261023'
G14 = ROOT / 'local-artifacts/research-goal14-numeric-consistency-task-20261023'
TRAIN_PYTHON = ROOT / 'local-artifacts/product-p21c-fraction-learning-20261020/runtime/Scripts/python.exe'
OCR_PYTHON = ROOT.parent / '.venv/Scripts/python.exe'
START_EPOCH = 1792772121
DIGIT_ROLES = ('whole', 'numerator', 'denominator')
OTHER_ROLES = ('relation', 'decimal_point', 'sign', 'unit', 'context')

def utc():
    return datetime.now(timezone.utc).isoformat()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

def relative(path):
    return str(Path(path).resolve().relative_to(ROOT)).replace('\\', '/')

def absolute(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path
