"""Array-level diagnosis of four saved Goal09 inputs. No inference or source edits."""
import json, math
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[2]
PREV=ROOT/'local-artifacts/research-goal09-fraction-reading-20261022'
OUT=ROOT/'local-artifacts/research-goal10-numeric-input-integrity-20261022'

# Provisional visible-component regions, used only for diagnosis, never inference.
# Slash and numerator may share a connected component; not a character classifier.
PARTS={int(k):v for k,v in json.loads((OUT/'part-annotations.json').read_text('utf8'))['parts'].items()}

def inspect(source,record,rect,index):
    path=ROOT/record['crop'];crop=cv2.imread(str(path));x,y,xx,yy=rect
    tensor_path=path.parent/record.get('tensor_file','model-input.npy')
    tensor=np.load(tensor_path,allow_pickle=False)
    h,w=crop.shape[:2];channels,height,width=tensor.shape
    valid=min(width,math.ceil(height*w/h))
    expected=np.zeros(tensor.shape,dtype=np.float32)
    resized=cv2.resize(crop,(valid,height)).astype('float32').transpose(2,0,1)/255
    resized-=.5;resized/=.5;expected[:,:,:valid]=resized
    eq=np.array_equal(crop,source[y:yy,x:xx])
    checks=[]
    for name,box in PARTS[index]:
        a,b,c,d=box;pixels=source[b:d,a:c,0]<230;ys,xs=np.where(pixels)
        sx,sy=xs+a,ys+b;inside=(sx>=x)&(sx<xx)&(sy>=y)&(sy<yy)
        ax=max(0,math.floor((a-x)*valid/w));bx=min(valid,math.ceil((c-x)*valid/w))
        ay=max(0,math.floor((b-y)*height/h));by=min(height,math.ceil((d-y)*height/h))
        region=tensor[:,ay:by,ax:bx]
        checks.append({'part':name,'source_rect':box,'source_nonwhite_pixels_threshold230':len(xs),'source_pixels_in_crop':int(inside.sum()),'crop_retains_all_marked_source_pixels':bool(inside.all()),'predicted_model_rect_active_only':[ax,ay,bx,by],'actual_model_pixels_below_source_gray230_equivalent':int(np.count_nonzero(region[0] < ((230/255-.5)/.5))) if region.size else 0,'semantic_label':'AI_QA_PROVISIONAL spatial component; not independent character truth'})
    return {'actual_crop':str(path),'source_rect':rect,'crop_shape':list(crop.shape),'source_slice_array_equal':eq,'tensor':str(tensor_path),'tensor_shape':list(tensor.shape),'active_width':valid,'right_padding':width-valid,'expected_installed_normalization_array_equal':bool(np.array_equal(tensor,expected)),'maximum_absolute_tensor_difference':float(np.max(np.abs(tensor-expected))),'normalization':'cv2 default INTER_LINEAR; float32 /255, -.5, /.5; zero right padding','parts':checks,'reading':record['text'],'confidence':record['confidence']}

def figure(source,row,checks):
    x,y,w,h=row['bbox'];context=source[y-8:y+h+8,x-8:x+w+8]
    context=Image.fromarray(cv2.cvtColor(context,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(context);draw.rectangle((8,8,8+w-1,8+h-1),outline='red')
    panels=[('SOURCE CONTEXT / red = normal OCR bbox',context,4)]
    for key in ['ordinary_parent','Goal09_local']:
        if checks[key] is None:continue
        p=Path(checks[key]['actual_crop']);panels.extend([(key+' ACTUAL CROP',Image.open(p),4),(key+' ACTUAL MODEL INPUT / includes right padding',Image.open(p.parent/'model-input.png'),3)])
    height=sum(28+im.height*scale+14 for label,im,scale in panels)
    canvas=Image.new('RGB',(1100,height+50),'white');d=ImageDraw.Draw(canvas);d.text((8,8),f"OBJECT {row['index']} / SOURCE INPUT EVIDENCE / LOCAL_EVAL_ONLY",fill='black');top=40
    for label,im,scale in panels:
        d.text((8,top),label,fill='black');top+=25;im=im.convert('RGB').resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST);canvas.paste(im,(8,top));top+=im.height+17
    if not row['segments']:d.text((8,height+25),'GOAL09 LOCAL NOT RUN: source/OCR word alignment rejected before local recognition',fill='red')
    canvas.save(OUT/f"A-{row['index']}-saved-input-chain.png")

def main():
    source=cv2.imread(str(PREV/'normal-B/source-page.png'))
    rows=json.loads((PREV/'B-v1-completed/results.json').read_text('utf8'))
    normal=json.loads((PREV/'normal-B/result.json').read_text('utf8'))['texts']
    results=[]
    for row in rows:
        i=row['index'];x,y,w,h=row['bbox']
        parent=inspect(source,row['ordinary_local'],[x,y,x+w,y+h],i)
        local=inspect(source,row['segments'][0]['reading'],row['segments'][0]['source_rect'],i) if row['segments'] else None
        checks={'index':i,'normal_value':row['normal'],'normal_detection_bbox':row['bbox'],'normal_detection_quad':normal[i]['quad'],'original_normal_internal_recognizer_crop':'NOT_SAVED; no claim reconstructed parent is byte-identical to that historical inference','ordinary_parent':parent,'Goal09_local':local,'Goal09_local_status':'RAN' if local else 'NOT_RUN_REJECTED_BEFORE_LOCAL_RECOGNITION','Goal09_decision':row['state'],'Goal09_reason':row['reason'],'Goal09_candidate':None if row['state']!='REVIEW_FRACTION_HYPOTHESIS' else row['hypothesis'],'final_retained_value':row['normal'],'first_loss_in_full_normal_pipeline':'NOT_NEWLY_LOCATED','human_reviewed':False,'assessment':'AI_QA_PROVISIONAL'}
        figure(source,row,checks);results.append(checks)
    (OUT/'input-diagnosis.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    for r in results:
        print(r['index'],'parent_equal',r['ordinary_parent']['source_slice_array_equal'],'normalize_equal',r['ordinary_parent']['expected_installed_normalization_array_equal'],'local',r['Goal09_local_status'])
        for stage in ['ordinary_parent','Goal09_local']:
            if r[stage]:print(stage,[(p['part'],p['source_pixels_in_crop'],p['source_nonwhite_pixels_threshold230'],p['actual_model_pixels_below_source_gray230_equivalent']) for p in r[stage]['parts']])
if __name__=='__main__':main()
