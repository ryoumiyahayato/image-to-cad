"""Read actual GUI roundtrips in an independent process; render fixed original specimens."""
import os,sys,json,math
os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.dont_write_bytecode=True
from pathlib import Path
from prepare import OUT,load,save,record,effective_widths,rows
import ezdxf,numpy as np,cv2
from ezdxf.addons.drawing import RenderContext,Frontend,layout,config
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.math import BoundingBox2d
from PySide6.QtCore import QByteArray,QRectF
from PySide6.QtGui import QGuiApplication,QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

def render(path,target):
    doc=ezdxf.readfile(path);backend=SVGBackend()
    cfg=config.Configuration(background_policy=config.BackgroundPolicy.WHITE,color_policy=config.ColorPolicy.BLACK,min_lineweight=.01)
    Frontend(RenderContext(doc),backend,config=cfg).draw_layout(doc.modelspace(),finalize=True)
    svg=backend.get_string(layout.Page(19,22,layout.Units.mm,margins=layout.Margins.all(0)),
          settings=layout.Settings(fit_page=False,scale=1,min_stroke_width=.001),render_box=BoundingBox2d([(-.7,-.7),(18.3,21.3)]))
    target.with_suffix('.svg').write_text(svg,'utf8')
    image=QImage(1140,1320,QImage.Format.Format_ARGB32);image.fill(0xffffffff)
    painter=QPainter(image);renderer=QSvgRenderer(QByteArray(svg.encode('utf8')));assert renderer.isValid();renderer.render(painter,QRectF(0,0,1140,1320));painter.end();assert image.save(str(target))

def compare(original,saved,plan):
    a=ezdxf.readfile(original);b=ezdxf.readfile(saved);results=[]
    for spec in plan['items']:
        layer=spec['input']['layer'];before=[e for e in a.modelspace() if e.dxf.layer==layer];after=[e for e in b.modelspace() if e.dxf.layer==layer]
        assert len(before)==1
        row={'sample':spec['sample'],'expression':spec['expression'],'expected_width':spec['expected_width'],'original':record(before[0]),'saved_entity_count_on_layer':len(after)}
        if len(after)==1 and after[0].dxftype() in ['LWPOLYLINE','POLYLINE']:
            e=after[0];row['saved']=record(e)
            row['geometry_preserved']=len(rows(e))==len(spec['expected_points']) and np.allclose(np.array(rows(e))[:,:2],spec['expected_points'],atol=1e-9,rtol=0) and bool(e.is_closed)==spec['closed']
            row['width_preserved']=np.allclose(effective_widths(e),spec['expected_width'],atol=1e-12,rtol=0)
            row['closing_segment_width']=effective_widths(e)[-1] if spec['closed'] else None
        else:row.update(geometry_preserved=False,width_preserved=False)
        results.append(row)
    return {'input':str(original),'saved':str(saved),'input_version':a.dxfversion,'saved_version':b.dxfversion,
            'input_entities':len(a.modelspace()),'saved_entities':len(b.modelspace()),'items':results,
            'nonzero_total':sum(r['expected_width']>0 for r in results),'nonzero_width_preserved':sum(r['expected_width']>0 and r['width_preserved'] for r in results),
            'geometry_preserved':sum(r['geometry_preserved'] for r in results),'zero_controls_preserved':sum(r['expected_width']==0 and r['width_preserved'] for r in results),
            'independent_interpreter':True,'roundoff':'geometry1e-9 drawing units, widths1e-12 drawing units; no change to frozen real QA',
            'render_conditions':'ezdxf SVG frontend, WHITE/BLACK, min_lineweight0.01mm, same 19x22mm box[-0.7,-0.7,18.3,21.3], scale1,1140x1320px; QtSvg raster; no width substitution'}

def main():
    app=QGuiApplication.instance() or QGuiApplication([]);summary=[]
    for label in ['2010','2007']:
        folder=OUT/'minimal';original=folder/f'original-{label}.dxf';plan=load(folder/f'plan-{label}.json')
        render(original,folder/f'original-{label}.png')
        for phase in ['gui-saved','gui-reopened-saved']:
            path=folder/f'{phase}-{label}.dxf'
            if not path.exists():continue
            result=compare(original,path,plan);save(folder/f'{phase}-{label}-readback.json',result)
            render(path,folder/f'{phase}-{label}.png')
            summary.append({k:result[k] for k in ['saved','input_version','saved_version','nonzero_total','nonzero_width_preserved','geometry_preserved','zero_controls_preserved']})
    save(OUT/'minimal-summary.json',summary);print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
