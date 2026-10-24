"""Existing REC only. Exact tensor cache; raw decoder output is never rewritten."""
import os,time,math
import numpy as np
import cv2
from common import *

class FixedOCR:
    def __init__(self):
        runtime=ROOT/'local-artifacts/product-p21a-raster-group-layout-20261020/baseline-runtime/cad_photo_to_dxf'
        os.environ['QT_QPA_PLATFORM']='offscreen';sys.path.insert(0,str(runtime))
        from app.ocr.ocr_recognition import _get_rapidocr_engine
        from rapidocr.ch_ppocr_rec.typings import TextRecInput
        t=time.perf_counter();self.rec=_get_rapidocr_engine().text_rec;self.init_seconds=time.perf_counter()-t;self.Input=TextRecInput
        config={k:str(v) for k,v in dict(self.rec.cfg).items()}
        assert config==read(G21/'ocr-runtime.json')['configuration'],'installed OCR configuration drift'
        self.config=config;self.cache=[];self.new=[];self.forward_seconds=0.;self.cache_hits=0
        for group in ['real-local','synthetic']:
            for row in read(G21/group/'ocr/predictions.json'):
                self.cache.append((np.load(abs_path(row['actual_input'])),dict(row,cache_origin='Goal21')))
        old=OUT/'real-local/ocr-cache.json'
        self.records=read(old) if old.exists() else []
        for row in self.records:self.cache.append((np.load(abs_path(row['actual_input'])),row))
    def read_pixels(self,pixels,group):
        crop=cv2.cvtColor(pixels,cv2.COLOR_RGB2BGR)
        ratio=max(self.rec.rec_image_shape[2]/self.rec.rec_image_shape[1],crop.shape[1]/crop.shape[0])
        expected=self.rec.resize_norm_img(crop,ratio)[None].astype(np.float32)
        old=next((row for array,row in self.cache if array.shape==expected.shape and np.array_equal(array,expected)),None)
        if old is not None:
            self.cache_hits+=1
            return {k:old[k] for k in ['reader_raw','confidence','actual_input','input_shape']}|{'reused':True,'cache_origin':old.get('cache_origin','Goal22')}
        if len(self.records)>=100:return dict(status='BUDGET_STOP',reader_raw=None,reused=False)
        session=self.rec.session;captured={}
        class Capture:
            def __getattr__(self,name):return getattr(session,name)
            def __call__(self,array):
                captured['array']=array.copy();t=time.perf_counter();value=session(array)
                captured['seconds']=time.perf_counter()-t;captured['pred']=value;return value
        self.rec.session=Capture()
        try:result=self.rec(self.Input(img=crop,return_word_box=False))
        finally:self.rec.session=session
        assert np.array_equal(captured['array'],expected)
        path=OUT/group/'ocr'/('input-'+str(len(self.records)).zfill(3)+'.npy');path.parent.mkdir(parents=True,exist_ok=True);np.save(path,captured['array'])
        row=dict(reader='PP-OCRv6',reader_raw=result.txts[0],confidence=float(result.scores[0]),actual_input=rel(path),
            input_shape=list(expected.shape),ctc_argmax=captured['pred'][0].argmax(-1).tolist(),reused=False,cache_origin='Goal22',
            valid_width=min(expected.shape[-1],math.ceil(48*crop.shape[1]/crop.shape[0])),forward_seconds=captured['seconds'])
        self.forward_seconds+=captured['seconds'];self.records.append(row);self.new.append(row);self.cache.append((expected.copy(),row))
        write(OUT/'real-local/ocr-cache.json',self.records)
        return row
