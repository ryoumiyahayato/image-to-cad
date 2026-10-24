import json
import sys
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'local-artifacts/research-goal22-automatic-role-binding-20261024'
G21=ROOT/'local-artifacts/research-goal21-role-digit-reading-20261024'
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def utc():return datetime.now(timezone.utc).isoformat()
def rel(p):return str(Path(p).resolve().relative_to(ROOT)).replace('\\','/')
def abs_path(p):return Path(p) if Path(p).is_absolute() else ROOT/p
