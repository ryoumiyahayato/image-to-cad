"""Final-checkpoint inference on pixels only. Candidates and ground truth never enter reader."""
import time
import numpy as np
import torch
from PIL import Image
from common import *
from model import DigitReader,normalize,decode_path

class PixelReader:
    def __init__(self,checkpoint):
        saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
        self.model=DigitReader();self.model.load_state_dict(saved['model_state']);self.model.eval()
        for p in self.model.parameters():p.requires_grad_(False)
        self.updates=saved['updates'];self.seconds=0.;self.calls=0
        self.cache_arrays=[];self.cache_results=[]
    @torch.inference_mode()
    def read(self,pixels):
        array,width,steps=normalize(pixels)
        idx=next((i for i,a in enumerate(self.cache_arrays) if a.shape==array.shape and np.array_equal(a,array)),None)
        if idx is not None:return dict(self.cache_results[idx],valid_width=width,reused=True),array
        x=torch.from_numpy(array[None]);lengths=torch.tensor([steps],dtype=torch.long)
        t=time.perf_counter();logits=self.model(x,lengths);self.seconds+=time.perf_counter()-t;self.calls+=1
        probabilities=logits[0,:steps].softmax(-1).numpy();path=probabilities.argmax(-1).tolist()
        result=dict(reader='Goal21-DigitCTC',reader_raw=decode_path(path),valid_width=width,
            input_shape=list(x.shape),valid_time_steps=steps,ctc_argmax=path,
            ctc_probabilities=probabilities.tolist(),reused=False)
        self.cache_arrays.append(array.copy());self.cache_results.append(result)
        return result,array

def main():
    started=time.perf_counter();assert not (OUT/'digit-runtime.json').exists()
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    reader=PixelReader(OUT/'fit/final.pt')
    manifest=read(OUT/'training-data/manifest.json');results=[]
    for r in manifest:
        pixels=np.array(Image.open(absolute(r['image'])).convert('RGB'))
        result,array=reader.read(pixels)
        assert np.array_equal(array,np.load(absolute(r['array'])))
        results.append(dict(result,id=r['id'],actual_input=r['array']))
    write(OUT/'training-evaluation/predictions.json',results)
    crops=read(OUT/'real-local/crops.json')+read(OUT/'synthetic/crops.json');results=[]
    for r in crops:
        result,array=reader.read(np.array(Image.open(absolute(r['crop'])).convert('RGB')))
        folder=OUT/r['group']/'digit';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(r['crop_id']+'.npy');np.save(path,array[None])
        results.append(dict(result,crop_id=r['crop_id'],actual_input=relative(path)))
    for group in ('real-local','synthetic'):
        ids={r['crop_id'] for r in crops if r['group']==group}
        write(OUT/group/'digit/predictions.json',[r for r in results if r['crop_id'] in ids])
    write(OUT/'digit-runtime.json',dict(utc=utc(),checkpoint=relative(OUT/'fit/final.pt'),updates=reader.updates,
        inference_calls=reader.calls,records=len(manifest)+len(crops),model_seconds=reader.seconds,
        evaluation_wall_seconds=time.perf_counter()-started,input_contract=['pixels'],
        normalizer='Pillow L and BILINEAR, height32, preserve aspect; white right padding to multiple4',
        decoder='greedy over image-derived time length; complete untruncated raw string',
        no_candidates_or_labels_passed=True,ctc_path_is_not_character_source_certification=True))
    print('FINAL_INFERENCE_COMPLETE',reader.calls,'SECONDS',round(reader.seconds,3),flush=True)

if __name__=='__main__':main()
