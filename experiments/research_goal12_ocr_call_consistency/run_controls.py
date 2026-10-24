"""One replay, two batch1 controls, one crop intervention per target batch.

Selection is diagnostic only, not an automatic repair. Labels never choose
outputs. Crop replacement keeps all other captured batch rows bitwise intact.
"""
import math,time
from common import *
setup()
def main():
    import cv2,numpy as np
    from app.ocr.ocr_recognition import _get_rapidocr_engine
    from app.ocr.ocr_pipeline import _prepare_native_ocr_tile
    folder=OUT/'causal-controls';folder.mkdir(exist_ok=False)
    meta=load(OUT/'normal-observed/boundary-records.json');target_batches=[b for b in meta['batches'] if b['targets']]
    targets=load(OUT/'frozen-objects.json')['A']['rows'];source=cv2.imread(str(OLD/'normal-B/source-page.png'))
    clean=cv2.cvtColor(_prepare_native_ocr_tile(source),cv2.COLOR_GRAY2BGR)
    details={i['batch_position']:(c,i) for c in [] for i in []} # mapping built explicitly below
    details={}
    for call in meta['recognition_calls']:
        for row in call['images']:
            if row['targets']:details[row['targets'][0]]=row
    plan={'UTC':utc(),'before_outputs':True,'changes':[
        {'case':'CAPTURED_BATCH_REPLAY','batch':55,'only_changed':'Nothing: exact captured six-row float32 array','question':'Does original first-decode reproduce without detection/crop/normalizer?'},
        {'case':'EXACT_ROW_BATCH1','targets':['A218-parent','A219-parent'],'only_changed':'Batch cardinality six to one; selected row bytes and width320 unchanged','question':'Is batch companion context needed for the error?'},
        {'case':'DETECTOR_BBOX_IN_ORIGINAL_BATCH','target_batches':[b['batch'] for b in target_batches],'only_changed':'Selected crop boundary: same prepared page, same detected quad bounding rectangle without perspective warp, same normalizer and original batch positions/padded widths. All non-selected rows unchanged.','question':'Does replacing geometric crop policy account for output flip on the six fixed objects?'}],
        'maximum_model_forwards':8,'no_parameter_search':True,'no_voting_or_output_selection':True,'diagnostic_target_selection_not_automatic_localization':True,'weights_configuration_dictionary_and_postprocess':'unchanged accepted baseline'}
    dump(folder/'plan.json',plan)
    rec=_get_rapidocr_engine().text_rec;records=[];started=time.perf_counter()
    def infer(name,batch,wh,maxratio,changes):
        t=time.perf_counter();pred=rec.session(batch);decoded=rec.postprocess_op(pred,False,wh_ratio_list=wh,max_wh_ratio=maxratio)[0]
        row={'case':name,'shape':list(batch.shape),'dtype':str(batch.dtype),'seconds':time.perf_counter()-t,'changed':changes,'outputs':[{'text':text,'confidence':float(score)} for text,score in decoded]}
        records.append(row);dump(folder/'results.json',records);print(name,row['outputs'],flush=True)
    b=next(b for b in target_batches if b['batch']==55);array=np.load(b['array'])
    infer('CAPTURED_BATCH_REPLAY_55',array,b['decode_kwargs']['wh_ratio_list'],b['decode_kwargs']['max_wh_ratio'],[])
    for name in ('A218-parent','A219-parent'):
        r=details[name];j=r['batch_position'];infer('EXACT_ROW_BATCH1_'+name,array[j:j+1], [b['decode_kwargs']['wh_ratio_list'][j]],b['decode_kwargs']['max_wh_ratio'],['batch_cardinality_only'])
    for b in target_batches:
        original=np.load(b['array']);batch=original.copy();wh=list(b['decode_kwargs']['wh_ratio_list']);changed=[]
        for target in b['targets']:
            r=details[target['ids'][0]];q=np.asarray(r['mapped_quad_working_page']);a,z=np.floor(q.min(axis=0)).astype(int),np.ceil(q.max(axis=0)).astype(int)
            x0,y0=a;x1,y1=z;crop=clean[y0:y1,x0:x1].copy();rawcrop=source[y0:y1,x0:x1]
            tensor=rec.resize_norm_img(crop,b['decode_kwargs']['max_wh_ratio']);j=target['batch_position'];batch[j]=tensor;wh[j]=crop.shape[1]/crop.shape[0]
            f=folder/target['ids'][0];f.mkdir();cv2.imwrite(str(f/'bbox-crop.png'),crop);np.save(f/'bbox-input.npy',tensor)
            changed.append({'id':target['ids'][0],'batch_position':j,'rect':[int(x0),int(y0),int(x1),int(y1)],'crop_shape':list(crop.shape),'raw_and_prepared_rectangle_equal':bool(np.array_equal(rawcrop,crop)),'normalization_width_unchanged':tensor.shape==original[j].shape})
        other=[i for i in range(len(batch)) if i not in [r['batch_position'] for r in changed]]
        if not np.array_equal(original[other],batch[other]):raise RuntimeError('Companion row modified')
        np.save(folder/f'batch-{b["batch"]:03d}-bbox.npy',batch)
        infer('DETECTOR_BBOX_BATCH_'+str(b['batch']),batch,wh,b['decode_kwargs']['max_wh_ratio'],changed)
    dump(folder/'runtime.json',{'seconds_including_model_init':time.perf_counter()-started,'model_forwards':len(records),'memory':memory(),'CPU':True,'model_and_dictionary':'same local PP-OCRv6 small accepted engine','new_models_or_training':False})
if __name__=='__main__':main()
