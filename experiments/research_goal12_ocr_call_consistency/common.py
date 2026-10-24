"""Goal12 paths and local JSON, no production imports or file fingerprints."""
import datetime, json, os, sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'local-artifacts/research-goal12-ocr-call-consistency-20261023'
OLD = ROOT/'local-artifacts/research-goal11-formula-model-20261023'
RUNTIME = ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
def load(p): return json.loads(Path(p).read_text('utf8'))
def dump(p,v):
    Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=lambda x:asdict(x) if is_dataclass(x) else x.tolist() if hasattr(x,'tolist') else str(x)), 'utf8')
def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def setup():
    os.environ['QT_QPA_PLATFORM']='offscreen';sys.dont_write_bytecode=True
    sys.path.insert(0,str(RUNTIME))
def memory():
    import ctypes
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]
    k=ctypes.WinDLL('kernel32');p=ctypes.WinDLL('psapi');k.GetCurrentProcess.restype=w.HANDLE
    p.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD]
    value=Counters();value.cb=ctypes.sizeof(value)
    if not p.GetProcessMemoryInfo(k.GetCurrentProcess(),ctypes.byref(value),value.cb):raise ctypes.WinError()
    return {name:int(getattr(value,name)) for name,_ in value._fields_}
