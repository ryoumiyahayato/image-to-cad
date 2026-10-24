"""Read actual external-CAD files; no converter, selection, or DXF writes."""
import sys, json, os
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'local-artifacts/research-goal07-reference-cad-20261022'
sys.path.insert(0, str(ROOT/'experiments/research_goal06_cad_roundtrip'))
from prepare import record, load, save
from readback import compare, render
import ezdxf

def minimal():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    folder=OUT/'minimal'
    original=folder/'input-original-2010.dxf'
    plan=load(ROOT/'local-artifacts/research-goal06-cad-roundtrip-20261022/minimal/plan-2010.json')
    result=[]
    for phase in ['input-original-2010','gui-saved-2010','gui-reopened-saved-2010']:
        path=folder/f'{phase}.dxf'
        if not path.exists(): continue
        r=compare(original,path,plan)
        r['input_units']=ezdxf.readfile(original).header.get('$INSUNITS')
        r['saved_units']=ezdxf.readfile(path).header.get('$INSUNITS')
        r['by_expression']={mode:{'total':len(rows),'width_preserved':sum(x['width_preserved'] for x in rows),'geometry_preserved':sum(x['geometry_preserved'] for x in rows)}
          for mode in ['CONST43','VERTEX40_41','POLYLINE2D']
          for rows in [[x for x in r['items'] if x['expression']==mode]]}
        save(folder/f'{phase}-readback.json',r)
        render(path,folder/f'{phase}.png')
        result.append({k:r[k] for k in ['saved','saved_version','saved_units','nonzero_width_preserved','geometry_preserved','zero_controls_preserved','by_expression']})
    save(OUT/'minimal-summary.json',result)
    print(json.dumps(result))

if __name__=='__main__':
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    minimal()
