"""Inspect captured arrays and deterministic reconstructions; no OCR calls."""
from common import *
setup()
def main():
    import cv2,numpy as np
    from PIL import Image,ImageDraw,ImageFont
    from rapidocr.utils.process_img import get_rotate_crop_image
    from app.ocr.ocr_pipeline import _prepare_native_ocr_tile
    folder=OUT/'normal-observed';data=load(folder/'boundary-records.json');plan=load(OUT/'frozen-objects.json')['A']
    raw=cv2.imread(plan['source_page']);clean=cv2.cvtColor(_prepare_native_ocr_tile(raw),cv2.COLOR_GRAY2BGR)
    old=load(OLD/'normal-B/result.json');new=load(folder/'result.json')
    results=[];items=[]
    for call in data['recognition_calls']:
        for row in call['images']:
            if row['targets']:items.append((call,row))
    for t in plan['rows']:
        call,r=next((c,r) for c,r in items if t['id'] in r['targets'])
        f=Path(r['folder']);x0,y0,x1,y1=t['source_rect'];q=np.asarray(r['mapped_quad_working_page'],np.float32)
        actual=cv2.imread(str(f/'actual-recognizer-crop.png'));before=cv2.imread(str(f/'before-classification.png'))
        cleanwarp=get_rotate_crop_image(clean,q.copy());rawwarp=get_rotate_crop_image(raw,q.copy())
        oldcrop=cv2.imread(str(OLD/'B-PP-control'/t['id'].replace('A','B',1)/'actual-recognizer-crop.png'))
        oldnorm=np.load(OLD/'B-PP-control'/t['id'].replace('A','B',1)/'actual-model-input.npy')
        actualnorm=np.load(f/'actual-model-input.npy');normalizer=np.load(f/'normalizer-output.npy')
        diff=np.abs(actualnorm[:,:,:min(actualnorm.shape[2],oldnorm.shape[2])]-oldnorm[:,:,:min(actualnorm.shape[2],oldnorm.shape[2])])
        result={'id':t['id'],'source_rect':t['source_rect'],'actual_quad':q,'actual_crop_shape':list(actual.shape),'Goal11_crop_shape':list(oldcrop.shape),'crop_pixel_equal_to_Goal11':bool(np.array_equal(actual,oldcrop)),'raw_rectangle_equal_to_Goal11':bool(np.array_equal(raw[y0:y1,x0:x1],oldcrop)),'reconstructed_clean_warp_equal_actual_before_cls':bool(np.array_equal(cleanwarp,before)),'classifier_unchanged_pixels':bool(np.array_equal(before,actual)),'raw_warp_equal_clean_warp':bool(np.array_equal(rawwarp,cleanwarp)),'normalized_shape':list(actualnorm.shape),'Goal11_normalized_shape':list(oldnorm.shape),'actual_model_equals_normalizer':bool(np.array_equal(actualnorm,normalizer)),'model_input_equal_to_Goal11':bool(np.array_equal(actualnorm,oldnorm)),'shared_width_max_abs_tensor_difference':float(diff.max()),'batch':r['batch'],'batch_position':r['batch_position'],'batch_row':load(f/'first-decode.json'),'post_rec_text':call['returned'][r['input_index']]['text'],'historical_normal':t['normal_value'],'Goal11_parent_raw':t['goal11_parent_raw'],'normal_output_matches_history':new['texts'][t['normal_index']]['text']==t['normal_value'],'folder':str(f)}
        results.append(result)
    differences=[]
    for i in range(max(len(old['texts']),len(new['texts']))):
        a=old['texts'][i] if i<len(old['texts']) else None;b=new['texts'][i] if i<len(new['texts']) else None
        if a!=b:differences.append({'index':i,'old':a,'observed':b})
    dump(OUT/'boundary-comparison.json',{'UTC':utc(),'targets':results,'all_normal_candidate_records_equal':old['texts']==new['texts'],'all_accepted_records_equal':old['accepted']==new['accepted'],'normal_candidate_differences':differences,'reconstruction_is_not_historical_capture':True,'same_time_actual_inputs':'normal-observed/engine-00-*/actual-model-input.npy','first_error':'CTC_FIRST_DECODE','normal_saved_candidate_count':len(new['texts'])})
    font=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',17)
    canvas=Image.new('RGB',(1280,len(results)*205+50),'white');d=ImageDraw.Draw(canvas)
    d.text((12,10),'Goal12 SOURCE / ACTUAL NORMAL INPUT / Goal11 PARENT - DIAGNOSTIC_ONLY',(0,0,0),font=font)
    for i,(t,r) in enumerate(zip(plan['rows'],results)):
        y=50+i*205;x0,y0,x1,y1=t['source_rect'];f=Path(r['folder'])
        d.text((12,y),t['id']+' source='+t['source_truth'].encode('ascii','backslashreplace').decode(),(0,0,0),font=font)
        for j,(label,im) in enumerate([('RAW SOURCE PARENT',raw[y0:y1,x0:x1]),('ACTUAL NORMAL CROP',cv2.imread(str(f/'actual-recognizer-crop.png'))),('ACTUAL NORMAL TENSOR',cv2.imread(str(f/'actual-model-input.png'))) ]):
            tile=Image.fromarray(cv2.cvtColor(im,cv2.COLOR_BGR2RGB));tile.thumbnail((390,100));tile=tile.resize((tile.width*min(2,390//tile.width),tile.height*min(2,100//tile.height)),Image.Resampling.NEAREST)
            canvas.paste(tile,(12+j*420,y+44));d.text((12+j*420,y+25),label,(0,0,0),font=font)
        text='CTC='+r['batch_row']['text']+' | parent='+r['Goal11_parent_raw']
        d.text((12,y+155),text.encode('ascii','backslashreplace').decode(),(0,0,0),font=font)
    canvas.save(OUT/'source-normal-parent-boundaries.png')
    print(json.dumps({'all_normal_equal':old['texts']==new['texts'],'rows':[{k:r[k] for k in ['id','actual_crop_shape','Goal11_crop_shape','reconstructed_clean_warp_equal_actual_before_cls','classifier_unchanged_pixels','raw_warp_equal_clean_warp','normalized_shape','Goal11_normalized_shape','batch']} for r in results]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
