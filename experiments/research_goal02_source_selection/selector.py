"""One local interactive prototype; no target labels are read here."""
import sys, json, time, argparse
from pathlib import Path
from dataclasses import dataclass
import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.tools.text import caret_decode
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QTransform, QPainterPathStroker, QPen, QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QPushButton,QLabel,QGraphicsView,QGraphicsScene,QListWidget,QListWidgetItem,QComboBox)

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cad_photo_to_dxf'))
from app.ocr.librecad_lff import librecad_text_metrics,librecad_text_path
from app.export.ocr_outline_export import native_text_file_content

ART=ROOT/'local-artifacts/research-goal02-source-selection-20261021'
OLD=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020'
CASES={'USDA7184':'B','NDSU708':'C'}

def read_json(path):return json.loads(Path(path).read_text('utf8'))
def write_json(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
def tags(entity):
    # Full existing records for exact undo/changed-snapshot comparisons; no digest.
    return [(t.code,str(t.value)) for t in TagCollector.dxftags(entity)]
def doc_records(doc):return {e.dxf.handle:tags(e) for e in doc.modelspace()}
def same_snapshot(a,b):return doc_records(a)==doc_records(b)
def glyph_path(entity,height):
    text=caret_decode(entity.dxf.text); m=librecad_text_metrics(text)
    t=QTransform();t.translate(entity.dxf.insert.x,entity.dxf.insert.y)
    t.rotate(entity.dxf.rotation);t.scale(entity.dxf.height/m.em_height*entity.dxf.width,-entity.dxf.height/m.em_height)
    p=QTransform(1,0,0,-1,0,height).map(t.map(librecad_text_path(text)))
    stroke=QPainterPathStroker();stroke.setWidth(1.)
    return stroke.createStroke(p)

@dataclass
class Row:
    handle:str
    source_index:int
    text:str
    source:QRectF
    cad:QRectF
    path:object

class Data:
    def __init__(self,case):
        self.case=case; self.folder=ART/case; self.old=OLD/CASES[case]
        self.input=self.folder/'initial.dxf'; self.doc=ezdxf.readfile(self.input)
        original=ezdxf.readfile(self.old/'BASE/single.dxf')
        if not same_snapshot(self.doc,original):raise ValueError('Initial DXF differs from the recorded normal snapshot')
        self.before=doc_records(self.doc)
        source_info=read_json(self.old/'BASE/input.json')
        self.height,self.width=source_info['shape'];self.source_info=source_info
        metadata=read_json(self.old/'BASE/result.json')['texts']
        if not all(x['approved'] for x in metadata):raise ValueError('Unsupported export filter: do not guess row numbering')
        entities=list(self.doc.modelspace().query('TEXT'))
        if len(entities)!=len(metadata):raise ValueError('TEXT/source count mismatch')
        self.rows=[];seen=set()
        for e in entities:
            if not e.has_xdata('OCR_TEXT_LINE'):raise ValueError('Missing row reference')
            x=[t.value for t in e.get_xdata('OCR_TEXT_LINE')];i=x[0]
            if not isinstance(i,int) or i in seen or not 1<=i<=len(metadata):raise ValueError('Ambiguous row reference')
            seen.add(i); c=metadata[i-1]
            if x[1]!=c['text'] or e.dxf.text!=native_text_file_content(c['text']) or abs(x[2]-c['confidence'])>1e-9:
                raise ValueError('Row reference disagrees with normal source record')
            q=c['quad']
            xs=[p[0] for p in q];ys=[p[1] for p in q]
            source=QRectF(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys))
            path=glyph_path(e,self.height)
            self.rows.append(Row(e.dxf.handle,i,c['text'],source,path.boundingRect(),path))
        write_json(self.folder/'association.json',{
            'version':'source-window-v1','source':source_info,'snapshot_file':str(self.input),
            'normal_reference':str(self.old/'BASE/single.dxf'),
            'binding':'Exact full modelspace record equality with normal reference before loading; row index/text/confidence checked; changed external snapshot refused',
            'relations':[{'handle':r.handle,'run_row_index':r.source_index,'text':r.text,
                'source_xywh':[r.source.x(),r.source.y(),r.source.width(),r.source.height()],
                'cad_source_xywh':[r.cad.x(),r.cad.y(),r.cad.width(),r.cad.height()],
                'relation':'existing editable TEXT only; leader/contours not owned'} for r in self.rows]})

    def window(self,rect,mode):
        accepted=[];partial=[]
        for r in self.rows:
            bounds=r.source if mode=='source' else r.cad
            if rect.contains(bounds):accepted.append(r.handle)
            elif rect.intersects(bounds):partial.append(r.handle)
        return accepted,partial

class View(QGraphicsView):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.scene_=QGraphicsScene();self.setScene(self.scene_)
        self.setBackgroundBrush(QColor('lightgray'));self.start=None;self.rubber=None
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:
            self.start=self.mapToScene(e.position().toPoint());self.rubber=self.scene_.addRect(QRectF(self.start,self.start),QPen(QColor('blue'),1));return
        super().mousePressEvent(e)
    def mouseMoveEvent(self,e):
        if self.start is not None:self.rubber.setRect(QRectF(self.start,self.mapToScene(e.position().toPoint())).normalized());return
        super().mouseMoveEvent(e)
    def mouseReleaseEvent(self,e):
        if self.start is not None:
            rect=QRectF(self.start,self.mapToScene(e.position().toPoint())).normalized();self.scene_.removeItem(self.rubber);self.start=None
            if rect.width()>2 and rect.height()>2:self.owner.rectangle(rect)
            return
        super().mouseReleaseEvent(e)

class Window(QMainWindow):
    def __init__(self,case,mode,run):
        super().__init__();self.data=Data(case);self.mode=mode;self.run=run
        self.out=self.data.folder/run;self.out.mkdir(exist_ok=True)
        self.started=time.perf_counter();self.events=[];self.selected=[];self.partial=[];self.confirmed=False;self.edited=False
        self.zooming=False;self.overlays=[]
        self.setWindowTitle(f'Goal02 {case} {mode} {run} | DIAGNOSTIC_ONLY');self.resize(1160,850)
        c=QWidget();self.setCentralWidget(c);layout=QVBoxLayout(c)
        layout.addWidget(QLabel('Select existing editable note TEXT only; exclude leader/texture/neighbor. ACI color 2; Undo; save. AI_QA_PROVISIONAL.'))
        bar=QHBoxLayout();layout.addLayout(bar)
        for text,fn in [('Full page',self.full),('Zoom window',self.zoom),('Clear',self.clear),('Confirm selection',self.confirm),('Set color 2',self.edit),('Undo',self.undo),('Save current',self.save)]:
            b=QPushButton(text);b.clicked.connect(fn);bar.addWidget(b)
        row=QHBoxLayout();layout.addLayout(row,1);self.view=View(self);row.addWidget(self.view,1)
        self.list=QListWidget();self.list.setMaximumWidth(260);row.addWidget(self.list)
        self.status=QLabel();layout.addWidget(self.status)
        image=self.data.old/('SOURCE_RENDER.png' if mode=='source' else 'BASE/SAVED_DXF_RENDER.png')
        self.view.scene_.addPixmap(QPixmap(str(image)))
        self.view.setSceneRect(0,0,self.data.width,self.data.height)
        self.log('open',mode=mode,initial_dxf=str(self.data.input));self.full()
    def log(self,action,**details):
        self.events.append({'n':len(self.events)+1,'elapsed_executor_seconds':time.perf_counter()-self.started,'action':action,**details})
        write_json(self.out/'events.json',{'operator':'AI executor via Windows UI, not human timing','method':self.mode,'events':self.events})
    def full(self):
        self.view.fitInView(self.view.sceneRect(),Qt.KeepAspectRatio);self.log('full_page');self.status.setText('Full page. Zoom by a window, then drag selection rectangle.')
    def zoom(self):self.zooming=True;self.log('zoom_tool');self.status.setText('Drag a zoom window on this page.')
    def rectangle(self,rect):
        coords=[rect.x(),rect.y(),rect.right(),rect.bottom()]
        if self.zooming:
            self.view.fitInView(rect,Qt.KeepAspectRatio);self.zooming=False;self.log('zoom_rectangle',xyxy=coords);return
        start=time.perf_counter();self.selected,self.partial=self.data.window(rect,self.mode);self.confirmed=False
        self.log('select_window',xyxy=coords,selected=self.selected,partial=self.partial,program_ms=(time.perf_counter()-start)*1000)
        self.draw()
    def draw(self):
        for item in self.overlays:self.view.scene_.removeItem(item)
        self.overlays=[];self.list.clear()
        for r in self.data.rows:
            if r.handle not in self.selected+self.partial:continue
            state='SELECT' if r.handle in self.selected else 'PARTIAL — EXCLUDED'
            self.list.addItem(f'{state}\n{r.handle}: {r.text}')
            pen=QPen(QColor('#e16600' if r.handle in self.selected else '#dc2020'),1.5)
            bounds=r.source if self.mode=='source' else r.cad
            self.overlays.append(self.view.scene_.addRect(bounds,pen))
        self.status.setText(f'Selected {len(self.selected)}; partial excluded {len(self.partial)}. Inspect text list and overlay, then Confirm. No geometry changed.')
    def clear(self):
        self.selected=[];self.partial=[];self.confirmed=False;self.log('clear');self.draw()
    def confirm(self):
        self.confirmed=bool(self.selected);self.log('confirm',selected=self.selected,partial_excluded=self.partial)
        write_json(self.out/'selection.json',{'selected':self.selected,'partial_excluded':self.partial,'confirmed':self.confirmed,'method':self.mode,'source_record':str(self.data.folder/'association.json')})
        self.grab().save(str(self.out/'selection.png'));self.status.setText('Confirmed current set; no DXF mutation. Set color 2 next.')
    def edit(self):
        if not self.confirmed or self.edited:self.status.setText('Confirm a nonempty selection first; undo current edit before another.');return
        self.original_colors={h:(self.data.doc.entitydb[h].dxf.hasattr('color'),self.data.doc.entitydb[h].dxf.color) for h in self.selected}
        for h in self.selected:self.data.doc.entitydb[h].dxf.color=2
        self.edited=True;self.log('edit_color',selected=self.selected,color=2)
        self.save('edited');self.status.setText('Color changed only in experiment. Saved edited.dxf. Undo restores exact previous colors.')
    def undo(self):
        if not self.edited:return
        for h,(present,value) in self.original_colors.items():
            e=self.data.doc.entitydb[h]
            if present:e.dxf.color=value
            else:e.dxf.discard('color')
        exact=doc_records(self.data.doc)==self.data.before;self.edited=False
        self.log('undo',exact_modelspace_restored=exact);self.save('undone');self.status.setText(f'Undo exact original modelspace records: {exact}. Saved undone.dxf.')
    def save(self,name=None):
        name=name if isinstance(name,str) else 'current'
        path=self.out/(name+'.dxf');self.data.doc.saveas(path);self.log('save',path=str(path))
    def showEvent(self,e):
        super().showEvent(e)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0,lambda:self.view.fitInView(self.view.sceneRect(),Qt.KeepAspectRatio))

def main():
    p=argparse.ArgumentParser();p.add_argument('--case',choices=CASES,required=True);p.add_argument('--mode',choices=['geometry','source'],required=True);p.add_argument('--run',required=True);args=p.parse_args()
    app=QApplication(sys.argv);w=Window(args.case,args.mode,args.run);w.show();sys.exit(app.exec())
if __name__=='__main__':main()
