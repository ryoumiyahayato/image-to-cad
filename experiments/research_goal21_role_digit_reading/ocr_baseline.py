"""One fixed installed PP-OCRv6 REC call per distinct actual normalized input."""
import math
import os
import time
import importlib.metadata
import numpy as np
from common import *

def main():
    started=time.perf_counter();plan=read(OUT/'frozen-plan.json')
    assert plan['status']=='FROZEN_BEFORE_ANY_GOAL21_READER_OUTPUT'
    assert not (OUT/'ocr-runtime.json').exists()
    runtime=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
    os.environ['QT_QPA_PLATFORM']='offscreen';sys.path.insert(0,str(runtime))
    import cv2
    from app.ocr.ocr_recognition import _get_rapidocr_engine
    from rapidocr.ch_ppocr_rec.typings import TextRecInput
    rec=_get_rapidocr_engine().text_rec
    session=rec.session
    class Capture:
        def __init__(self):self.tensor=None;self.pred=None;self.seconds=0.;self.calls=0
        def __getattr__(self,name):return getattr(session,name)
        def __call__(self,array):
            self.tensor=array.copy();t=time.perf_counter();self.pred=session(array)
            self.seconds+=time.perf_counter()-t;self.calls+=1
            return self.pred
    capture=Capture();rec.session=capture
    crops=read(OUT/'real-local/crops.json')+read(OUT/'synthetic/crops.json')
    results=[];inputs=[];cached=[]
    start_inference=time.perf_counter()
    for row in crops:
        crop=cv2.imread(str(absolute(row['crop'])));assert crop is not None
        ratio=max(rec.rec_image_shape[2]/rec.rec_image_shape[1],crop.shape[1]/crop.shape[0])
        expected=rec.resize_norm_img(crop,ratio)[None].astype(np.float32)
        dup=next((i for i,a in enumerate(inputs) if a.shape==expected.shape and np.array_equal(a,expected)),None)
        dst=OUT/row['group']/'ocr';dst.mkdir(parents=True,exist_ok=True)
        if dup is None:
            output=rec(TextRecInput(img=crop,return_word_box=False))
            assert np.array_equal(capture.tensor,expected)
            p=dst/(row['crop_id']+'.npy');np.save(p,capture.tensor)
            result=dict(crop_id=row['crop_id'],reader='PP-OCRv6',reader_raw=output.txts[0],
                confidence=float(output.scores[0]),actual_input=relative(p),input_shape=list(capture.tensor.shape),
                valid_width=min(expected.shape[-1],math.ceil(48*crop.shape[1]/crop.shape[0])),
                ctc_argmax=capture.pred[0].argmax(-1).tolist(),ctc_maximum=capture.pred[0].max(-1).tolist(),
                output_timestep_count=int(capture.pred.shape[1]),reused_from=None)
            inputs.append(capture.tensor.copy());cached.append(result)
        else:
            result=dict(cached[dup],crop_id=row['crop_id'],reused_from=cached[dup]['crop_id'])
        results.append(result)
        if row['group']=='real-local':print(row['crop_id'],repr(result['reader_raw']),flush=True)
        if len(results)%25==0:print('read',len(results),'of',len(crops),flush=True)
    for group in ('real-local','synthetic'):
        ids={r['crop_id'] for r in crops if r['group']==group}
        write(OUT/group/'ocr/predictions.json',[r for r in results if r['crop_id'] in ids])
    config={k:str(v) for k,v in dict(rec.cfg).items()}
    write(OUT/'ocr-runtime.json',dict(utc=utc(),frozen_utc=plan['frozen_utc'],
        python=sys.executable,rapidocr_version=importlib.metadata.version('rapidocr'),
        onnxruntime_version=importlib.metadata.version('onnxruntime'),configuration=config,
        source_module=str(runtime/'app/ocr/ocr_recognition.py'),
        recognizer_module=str(Path(sys.modules[type(rec).__module__].__file__)),
        model_path=str(getattr(session,'model_path',rec.cfg.get('model_path'))),
        inference_calls=capture.calls,unique_crop_count=len(crops),actual_array_deduplicated=len(inputs),
        model_forward_seconds=capture.seconds,inference_wall_seconds=time.perf_counter()-start_inference,
        process_wall_seconds=time.perf_counter()-started,detector_calls=0,classifier_calls=0,
        decoder='original installed decoder; raw output, no postfilter or string repair',
        input_contract=['digit region pixels'],candidate_input=False))
    print('OCR_COMPLETE',len(results),capture.calls,round(capture.seconds,3),flush=True)

if __name__=='__main__':main()
