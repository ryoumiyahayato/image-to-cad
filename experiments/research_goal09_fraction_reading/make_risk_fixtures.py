"""Eight original risk fixtures, not real-source scores or a detector evaluation."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local-artifacts/research-goal09-fraction-reading-20261022/risk-fixtures'
FONT=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/barlow/Barlow-Regular.ttf'
CASES=[('integer','14 inch.'),('decimal','1.4 inch.'),('minus','-14 mm'),('hyphen','1-4'),('foot_inch',"2'-0\""),('multiplication','4×6'),('rebar','#4'),('nearby_slash','14 inch.')]

if __name__=='__main__':
    OUT.mkdir(exist_ok=False)
    font=ImageFont.truetype(str(FONT),32)
    image=Image.new('RGB',(640,len(CASES)*70),'white');draw=ImageDraw.Draw(image)
    objects=[]
    for i,(role,text) in enumerate(CASES):
        x,y=40,i*70+15
        draw.text((x,y),text,font=font,fill='black')
        box=list(draw.textbbox((x,y),text,font=font));box=[box[0]-4,box[1]-4,box[2]+4,box[3]+4]
        if role=='nearby_slash':
            draw.line((17,y+36,29,y+4),fill='black',width=2);box[0]=13
        x0,y0,x1,y1=box
        objects.append({'text':text,'bbox':[x0,y0,x1-x0,y1-y0],'rotation_deg':0,'role':role,'source_truth_by_construction':text})
    image.save(OUT/'source-page.png')
    (OUT/'result.json').write_text(json.dumps({'texts':objects,'status':'SYNTHETIC_RISK_FIXTURE_WITH_SUPPLIED_CORRECT_OCR_OBJECT','normal_pipeline_run':False,'font':str(FONT),'license':'existing Barlow OFL.txt beside font; font not copied','purpose':'limited punctuation/leader admission checks, not real transfer'},ensure_ascii=False,indent=2),'utf8')
