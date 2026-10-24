import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
import pypdfium2 as pdfium
from ezdxf.render.linetypes import LineTypeRenderer
from ezdxf.math import Vec3
from native_dash import collect,expand,render_roi,simple_pdf_bytes,screen,metadata,page_objects,POLICY

ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'local-artifacts/research-goal01-native-dash-20261021'
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main(output=None):
    global OUT
    if output is not None:OUT=Path(output).resolve()
    out=OUT/'experiment1';out.mkdir(exist_ok=False);path=OUT/'original-dash-fixtures.pdf';cases=json.loads((OUT/'fixture-cases.json').read_text(encoding='utf8'))['cases'];allrows=[]
    doc=pdfium.PdfDocument(path)
    a=render_roi(doc[0],[30,75,320,125]);b=render_roi(doc[1],[30,75,320,125]);same=int(np.any(a!=b,axis=2).sum())
    for case in cases:
        rows,images,info=collect(path,case['page']-1);accepted=[r for r in rows if r['decision']=='ACCEPT_EDIT_UNIT']
        source=render_roi(doc[case['page']-1],[30,75,320,125]);Image.fromarray(source).save(out/(case['name']+'-source.png'))
        result=dict(**case,records=rows,accepted=len(accepted),accepted_dashes=sum(len(r['on_segments']) for r in accepted))
        if case['name']=='phase_7':
            row=accepted[0] if accepted else rows[0]
            if 'page_points' in row:
                renderer=LineTypeRenderer(np.array(row['dash'])*row['uniform_scale']);segs=[(np.array(a)[:2],np.array(b)[:2]) for a,b in renderer.line_segment(Vec3(row['page_points'][0]),Vec3(row['page_points'][1]))]
                proxy=pdfium.PdfDocument(simple_pdf_bytes(360,180,segs,row['page_width'],row['rgba'][:3]));naive=render_roi(proxy[0],[30,75,320,125]);Image.fromarray(naive).save(out/'phase-naive-dxf-renderer.png')
                result['direct_dash_array_line_type_pixel_difference']=int(np.any(source!=naive,axis=2).sum())
                sheet=Image.new('RGB',(source.shape[1],source.shape[0]*2+40),'white');dr=ImageDraw.Draw(sheet);sheet.paste(Image.fromarray(source),(0,20));sheet.paste(Image.fromarray(naive),(0,source.shape[0]+40));dr.text((4,3),'SOURCE PDF phase=7',fill='black');dr.text((4,source.shape[0]+23),'DIRECT SAME DASH ARRAY - DXF renderer begins at phase zero',fill='black');sheet.save(out/'phase-counterexample.png')
        allrows.append(result);print(case['name'],result['accepted'],[(r['index'],r['reason']) for r in rows],flush=True)
    write(out/'results.json',dict(experiment='E1 original mechanism/counterexamples',identical_pixels_different_source_authority_difference=same,cases=allrows,
        hypotheses_supported=['same visible dashes do not authorize grouping separate native objects','preserving explicit phase requires more than copying dash array'],
        no_real_product_claim=True))
    thumbs=[]
    for c in cases:
        im=Image.open(out/(c['name']+'-source.png')).resize((580,100));tile=Image.new('RGB',(580,125),'white');tile.paste(im,(0,25));ImageDraw.Draw(tile).text((4,5),c['name']+' / ORIGINAL FIXTURE',fill='black');thumbs.append(tile)
    sheet=Image.new('RGB',(1160,125*6),'white')
    for i,t in enumerate(thumbs):sheet.paste(t,((i%2)*580,(i//2)*125))
    sheet.save(out/'fixture-overview.png')
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root');a=p.parse_args();main(a.root)
