"""Original, redistributable mechanism fixtures; run with bundled reportlab Python."""
import json
from pathlib import Path
from reportlab.pdfgen import canvas

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'local-artifacts/research-goal01-native-dash-20261021'
def main(output=None):
    global OUT
    if output is not None:OUT=Path(output).resolve()
    OUT.mkdir(parents=True,exist_ok=False);path=OUT/'original-dash-fixtures.pdf'
    c=canvas.Canvas(str(path),pagesize=(360,180),pageCompression=0,invariant=1);cases=[]
    def start(name):
        c.setFont('Helvetica',10);c.drawString(20,160,'ORIGINAL RESEARCH FIXTURE - '+name);c.setLineWidth(2);c.setLineCap(0);c.setStrokeColorRGB(0,0,0)
    def line(x0=40,x1=310,y=100,pattern=(12,6),phase=0):
        c.setDash(list(pattern),phase);c.line(x0,y,x1,y)
    def finish(name,expected):
        cases.append(dict(name=name,page=len(cases)+1,expected=expected,roi_pdf=[30,75,320,125]));c.showPage()
    start('EXPLICIT_DASH');line();finish('explicit_dash','one explicit edit unit')
    start('INDEPENDENT_SEGMENTS');c.setDash([])
    for x in range(40,310,18):c.line(x,100,min(x+12,310),100)
    finish('independent_segments','no dash source authority; keep independent')
    start('TRUE_OPENING');line(40,160);line(190,310);finish('true_opening','two edit units; preserve 30pt opening')
    start('PARALLEL');line(y=94);line(y=106);finish('parallel','two distinct units')
    start('PHASE_7');line(phase=7);finish('phase_7','source phase retained; naive zero phase fails')
    start('OCCLUDED');line();c.setFillColorRGB(1,1,1);c.rect(130,90,80,20,fill=1,stroke=0);finish('occluded','reject hidden source intervals')
    start('CLIPPED');c.saveState();p=c.beginPath();p.rect(100,80,120,40);c.clipPath(p,stroke=0);line();c.restoreState();finish('clipped','reject clip mismatch')
    start('BATCHED_SUBPATHS');c.setDash([12,6]);p=c.beginPath();p.moveTo(40,100);p.lineTo(140,100);p.moveTo(210,100);p.lineTo(310,100);c.drawPath(p);finish('batched_subpaths','reject treating drawing batch as one object')
    start('NONUNIFORM');c.saveState();c.translate(40,100);c.scale(2,.5);line(0,135,0);c.restoreState();finish('nonuniform','reject unsupported stroke transform')
    start('ROTATED');c.saveState();c.translate(40,80);c.rotate(8);line(0,270,0);c.restoreState();finish('rotated','retain similarity-transformed straight dash')
    start('ROUND_CAP');c.setLineCap(1);line();finish('round_cap','reject unsupported cap in initial prototype')
    start('ODD_PATTERN');line(pattern=(8,4,2));finish('odd_pattern','duplicate odd pattern before on/off interpretation')
    c.save();(OUT/'fixture-cases.json').write_text(json.dumps(dict(license='CC0 original programmatic fixtures',cases=cases),ensure_ascii=False,indent=2),encoding='utf8')
    print(str(path),path.stat().st_size,'bytes',len(cases),'pages')
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out');a=p.parse_args();main(a.out)
