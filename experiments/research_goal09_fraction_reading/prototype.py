"""Frozen local numeric representation; review hypotheses only, never writes CAD.

Inference takes no truth labels. Source rect is automatic within each normal OCR
object. Ink threshold is used only to locate blank columns; OCR sees original RGB.
"""
import argparse, datetime, json, math, os, re, sys, time
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
sys.path.insert(0,str(RUNTIME))
VERSION='goal09-local-numeric-v1'
PARAMS={'max_rotation':2.,'ink_threshold':180,'min_column_ink_height_ratio':.04,'min_gap_height_ratio':.18,'side_padding_height_ratio':.08,'max_numeric_objects':32,'max_numeric_regions_per_object':4}
UNIT=re.compile(r'^(?:inch\.?|inches|mm|cm|ft|degrees|%)$',re.I)
FRACTION=re.compile(r'(?<!\d)\d+/\d+(?!\d)')

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
def canonical(s):return re.sub(r'\s+',' ',s.strip()).replace('′',"'").replace('’',"'").replace('″','"')

def source_groups(image):
    import cv2,numpy as np
    h,w=image.shape[:2]
    mask=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)<PARAMS['ink_threshold']
    col=np.count_nonzero(mask,axis=0)>=max(1,round(PARAMS['min_column_ink_height_ratio']*h))
    if not col.any():return []
    occupied=np.flatnonzero(col);left,right=int(occupied[0]),int(occupied[-1])+1
    gaps=[];start=left
    while start<right:
        if col[start]:start+=1;continue
        end=start+1
        while end<right and not col[end]:end+=1
        if end-start>=max(3,round(PARAMS['min_gap_height_ratio']*h)):gaps.append((start,end))
        start=end
    groups=[];start=left
    for g0,g1 in gaps:groups.append((start,g0));start=g1
    groups.append((start,right))
    return groups

class Reader:
    def __init__(self, output):
        from app.ocr.ocr_recognition import _get_rapidocr_engine
        self.rec=_get_rapidocr_engine().text_rec;self.output=output;self.calls=0
    def read(self,image,name):
        import cv2,numpy as np
        from rapidocr.ch_ppocr_rec import TextRecInput
        folder=self.output/name;folder.mkdir(parents=True,exist_ok=False)
        cv2.imwrite(str(folder/'crop.png'),image)
        original=self.rec.resize_norm_img;normalization=[]
        def observe(im,ratio):
            value=original(im,ratio);np.save(folder/'model-input.npy',value)
            cv2.imwrite(str(folder/'model-input.png'),np.clip((value.transpose(1,2,0)+1)*127.5,0,255).astype('uint8'))
            normalization.append({'shape':list(value.shape),'dtype':str(value.dtype),'max_wh_ratio':float(ratio),'valid_width':min(value.shape[2],math.ceil(value.shape[1]*im.shape[1]/im.shape[0]))})
            return value
        self.rec.resize_norm_img=observe;t=time.perf_counter()
        try:r=self.rec(TextRecInput(img=image))
        finally:self.rec.resize_norm_img=original
        self.calls+=1
        return {'text':r.txts[0],'confidence':float(r.scores[0]),'seconds':time.perf_counter()-t,'normalization':normalization,'crop':str(folder/'crop.png')}

def numeric_regions(words,groups,height):
    regions=[];used=set()
    for i,word in enumerate(words):
        if i in used or not re.search(r'[0-9]',word):continue
        end=i
        if i+1<len(words) and UNIT.fullmatch(words[i+1]):end=i+1;used.add(end)
        regions.append({'word_start':i,'word_end':end+1,'original':' '.join(words[i:end+1]),'local_x':[max(0,groups[i][0]-max(1,round(.08*height))),groups[end][1]+max(1,round(.08*height))]})
    return regions

def admission(old,new):
    if canonical(old)==canonical(new):return 'NO_CHANGE','SAME_READING'
    if "'" in canonical(old):return 'ABSTAIN','FOOT_COMPOUND_UNSUPPORTED'
    if not FRACTION.search(new):return 'ABSTAIN','NEW_READING_NOT_COMPLETE_FRACTION'
    # Letter context and inch/metric unit may not disappear in a fraction hypothesis.
    old_units=re.findall(r'[A-Za-z]+|["%]',old)
    new_units=re.findall(r'[A-Za-z]+|["%]',new)
    if [s.casefold() for s in old_units]!=[s.casefold() for s in new_units]:return 'ABSTAIN','UNIT_OR_CONTEXT_CHANGED'
    if not re.fullmatch(r'\s*[+-]?(?:\d+\s+)?\d+/\d+\s*(?:"|%|inch\.?|inches|mm|cm|ft|degrees)?\s*',new,re.I):return 'ABSTAIN','AMBIGUOUS_NUMERIC_GROUP'
    return 'REVIEW_FRACTION_HYPOTHESIS','LOCAL_VISIBLE_CROP_REREADING_NOT_INDEPENDENT_TRUTH'

def run(normal_dir,regions,output,reuse_parent=None):
    import cv2
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    normal_dir=Path(normal_dir);source_path=normal_dir/'source-page.png'
    source=cv2.imread(str(source_path));data=json.loads((normal_dir/'result.json').read_text('utf8'))
    reader=Reader(output);results=[]
    cached={}
    if reuse_parent:
        # Only ordinary local control can be reused. This never influences selection.
        for r in json.loads(Path(reuse_parent).read_text('utf8')):
            if r['id']=='A-parent':cached[tuple(r['source_rect'])]={'text':r['output'],'confidence':r['confidence'],'reused_capability_control':True}
    for index,t in enumerate(data['texts']):
        if not re.search(r'[0-9]',t['text']):continue
        x,y,w,h=t['bbox'];rect=[x,y,x+w,y+h]
        if not any(x>=a and y>=b and x+w<=c and y+h<=d for a,b,c,d in regions):continue
        row={'index':index,'normal':t['text'],'bbox':t['bbox'],'source':str(source_path),'state':'ABSTAIN','reason':None,'segments':[],'hypothesis':t['text'],'automatic_correction':False}
        if len(results)>=PARAMS['max_numeric_objects']:row['reason']='OBJECT_BUDGET'
        elif abs(t['rotation_deg'])>PARAMS['max_rotation']:row['reason']='ROTATION_UNSUPPORTED'
        elif x<0 or y<0 or x+w>source.shape[1] or y+h>source.shape[0]:row['reason']='SOURCE_BOUNDS'
        else:
            crop=source[y:y+h,x:x+w].copy()
            row['ordinary_local']=cached.get(tuple(rect)) or reader.read(crop,f'{index:04d}/ordinary-parent')
            groups=source_groups(crop);words=t['text'].split()
            row['projection_groups']=groups;row['normal_words']=words
            if len(groups)!=len(words):row['reason']='SOURCE_WORD_ALIGNMENT_AMBIGUOUS'
            else:
                local=numeric_regions(words,groups,h);changed=[]
                if len(local)>PARAMS['max_numeric_regions_per_object']:row['reason']='REGION_BUDGET'
                else:
                    for j,region in enumerate(local):
                        a,b=region['local_x'];b=min(w,b)
                        observed=reader.read(crop[:,a:b].copy(),f'{index:04d}/numeric-{j}')
                        state,reason=admission(region['original'],observed['text'])
                        segment=dict(region,source_rect=[x+a,y,x+b,y+h],reading=observed,state=state,reason=reason,char_relation_status='NOT_INDEPENDENTLY_CERTIFIED',source_pixels_unaltered=True)
                        row['segments'].append(segment)
                        if state=='REVIEW_FRACTION_HYPOTHESIS':changed.append(segment)
                    if changed:
                        assembled=list(words)
                        for s in reversed(changed):assembled[s['word_start']:s['word_end']]=[s['reading']['text']]
                        row.update(state='REVIEW_FRACTION_HYPOTHESIS',reason='VISIBLE_LOCAL_READING_REQUIRES_HUMAN_CONFIRMATION',hypothesis=' '.join(assembled))
                    elif all(s['state']=='NO_CHANGE' for s in row['segments']):row.update(state='NO_CHANGE',reason='SAME_LOCAL_READING')
                    else:row['reason']='LOCAL_DISAGREEMENT_NOT_ADMITTED'
        results.append(row);dump(output/'results.json',results)
        print(index,row['state'],repr(row['normal']),'=>',repr(row['hypothesis']),row['reason'],flush=True)
    dump(output/'run.json',{'version':VERSION,'parameters':PARAMS,'UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runtime':str(RUNTIME),'source':str(source_path),'scope_rects':regions,'numeric_objects':len(results),'new_recognizer_calls':reader.calls,'batch_per_call':1,'label_inputs':False,'hidden_text_inputs':False,'DXF_written':False,'automatic_corrections':0})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--normal-dir',required=True);p.add_argument('--regions',required=True,help='JSON list of scope rectangles, no target labels');p.add_argument('--output',required=True);p.add_argument('--reuse-parent-control');a=p.parse_args();run(a.normal_dir,json.loads(a.regions),a.output,a.reuse_parent_control)
