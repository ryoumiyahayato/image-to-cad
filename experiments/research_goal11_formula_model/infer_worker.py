"""One frozen FormulaRecognition model, one process, batch1 official preprocessing."""
import json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local-artifacts/research-goal11-formula-model-20261023';RUN=OUT/os.environ.get('GOAL11_RUN_NAME','run')
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
os.environ['PADDLE_PDX_CACHE_HOME']=str(OUT/'runtime/cache/paddlex')
os.environ['HF_HOME']=str(OUT/'runtime/cache/huggingface')
os.environ['MODELSCOPE_CACHE']=str(OUT/'runtime/cache/modelscope')
os.environ['XDG_CACHE_HOME']=str(OUT/'runtime/cache/xdg')
os.environ['OMP_NUM_THREADS']='8';os.environ['MKL_NUM_THREADS']='8';os.environ['OPENBLAS_NUM_THREADS']='8'
sys.dont_write_bytecode=True
START=time.perf_counter()
def event(stage,**values):
    row={'stage':stage,'pid':os.getpid(),'time':time.time(),'elapsed':time.perf_counter()-START,**values}
    with (RUN/'events.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    temp=RUN/'worker-state.tmp';temp.write_text(json.dumps(row,ensure_ascii=False),'utf8');os.replace(temp,RUN/'worker-state.json')
    print(json.dumps(row,ensure_ascii=False),flush=True)
def main():
    event('INTERPRETER_STARTED')
    begin=time.perf_counter()
    import paddle
    from paddleocr import FormulaRecognition
    import importlib.metadata as metadata
    event('IMPORT_COMPLETE',seconds=time.perf_counter()-begin,paddle_version=paddle.__version__)
    model_dir=OUT/'model/PP-FormulaNet_plus-L'
    event('MODEL_LOADING')
    begin=time.perf_counter()
    model=FormulaRecognition(model_name='PP-FormulaNet_plus-L',model_dir=str(model_dir),device='cpu',cpu_threads=8,enable_hpi=False)
    event('MODEL_LOADED',seconds=time.perf_counter()-begin,wrapper_class=type(model).__name__)
    # Inspect only this local predictor's boundary. No shared code changes.
    predictor=getattr(model,'paddlex_predictor',getattr(model,'_predictor',None))
    boundary={'predictor_class':str(type(predictor)),'attributes':list(vars(predictor)) if predictor is not None and hasattr(predictor,'__dict__') else []}
    (RUN/'predictor-boundary.json').write_text(json.dumps(boundary,ensure_ascii=False,indent=2),'utf8')
    # Hook is installed only when the official predictor exposes its static infer boundary.
    current={'id':None};capture=[]
    call_boundary='runner' if predictor is not None and hasattr(predictor,'runner') else 'infer'
    if predictor is not None and hasattr(predictor,call_boundary):
        original=getattr(predictor,call_boundary)
        class Observe:
            def __call__(self,*args,**kwargs):
                arrays=[]
                def visit(value,path):
                    if hasattr(value,'shape') and hasattr(value,'dtype'):arrays.append({'argument':path,'shape':list(value.shape),'dtype':str(value.dtype)})
                    elif isinstance(value,dict):
                        for k,v in value.items():visit(v,path+'.'+str(k))
                    elif isinstance(value,(list,tuple)):
                        for i,v in enumerate(value):visit(v,path+'.'+str(i))
                visit(args,'args');visit(kwargs,'kwargs')
                capture.append({'id':current['id'],'actual_static_infer_inputs':arrays})
                return original(*args,**kwargs)
            def __getattr__(self,name):return getattr(original,name)
        setattr(predictor,call_boundary,Observe())
    rows=json.loads((OUT/'frozen-inputs.json').read_text('utf8'))['rows']
    inputs=[{'id':'RUNTIME_CHECK_ORIGINAL','path':str(OUT/'runtime-check.png')}]+[{'id':r['id'],'path':r['path']} for r in rows]
    results=[]
    for row in inputs:
        current['id']=row['id'];event('INFERENCE',id=row['id']);begin=time.perf_counter()
        output=model.predict(input=row['path'],batch_size=1)
        raw=[]
        for n,res in enumerate(output):
            item=res.json
            raw.append(item);res.save_to_json(save_path=str(RUN/(row['id']+f'-{n}-raw.json')))
        record={'id':row['id'],'input':row['path'],'seconds':time.perf_counter()-begin,'raw_results':raw,'comparable_confidence':None,'actual_input_boundary':[r for r in capture if r['id']==row['id']]}
        results.append(record);(RUN/'raw-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8');event('INFERENCE_COMPLETE',id=row['id'],seconds=record['seconds'])
    (RUN/'environment.json').write_text(json.dumps({'Python':sys.version,'packages':{n:metadata.version(n) for n in ['paddlepaddle','paddleocr','paddlex','numpy','opencv-contrib-python','psutil']},'model':'PP-FormulaNet_plus-L','model_dir':str(model_dir),'device':'cpu','precision':'FP32','threads':8,'batch_size':1,'decode':'official defaults','new_training':False,'predictor_boundary':boundary},ensure_ascii=False,indent=2),'utf8')
    event('COMPLETE',engineering_inputs=len(rows))
if __name__=='__main__':main()
