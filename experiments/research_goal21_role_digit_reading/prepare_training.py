"""Conditional original-data generation and the required local CTC program checks."""
import ast
import functools
import shutil
import time
import numpy as np
import torch
from PIL import Image,ImageDraw
from common import *
from model import DigitReader,normalize,encode,decode_path

def main():
    trigger=read(OUT/'training-trigger.json');assert trigger['TRAINING_TRIGGER']=='MET'
    plan=read(OUT/'training-data-plan.json');base=OUT/'training-data';base.mkdir(exist_ok=False)
    (base/'images').mkdir();(base/'arrays').mkdir();(base/'licenses').mkdir()
    source=ROOT/'experiments/ml_pilot/p21c_fraction_guard/generate.py'
    tree=ast.parse(source.read_text('utf8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('font','text_image')]
    namespace={'functools':functools,'Image':Image,'ImageDraw':ImageDraw}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
    fonts={'barlow':'barlow/Barlow-Regular.ttf','ibmplexmono':'ibmplexmono/IBMPlexMono-Regular.ttf',
           'sourceserif4':'sourceserif4/SourceSerif4[opsz,wght].ttf'}
    font_root=ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts'
    for name,rel in fonts.items():
        license_file=(font_root/rel).parent/'OFL.txt'
        assert 'SIL OPEN FONT LICENSE' in license_file.read_text('utf8')
        shutil.copyfile(license_file,base/'licenses'/(name+'-OFL.txt'))
    rows=[];actual=[];generated_started=time.perf_counter()
    for split,strings in plan['strings'].items():
        families=plan['training_fonts']+([plan['reserved_font']] if split=='sealed-test' else [])
        sizes=plan['training_sizes'] if split=='train' else plan['evaluation_sizes']
        for text in strings:
            for family in families:
                for size in sizes:
                    iid=f't{len(rows):04d}'
                    im=namespace['text_image'](text,namespace['font'](str(font_root/fonts[family]),size))
                    array,width,steps=normalize(np.array(im))
                    needed=len(text)+sum(a==b for a,b in zip(text,text[1:]))
                    assert steps>=needed,(iid,text,steps,needed)
                    im.save(base/'images'/(iid+'.png'));np.save(base/'arrays'/(iid+'.npy'),array)
                    # Direct final-pixel equality, including shape; no hash functions.
                    duplicate=next((j for j,a in enumerate(actual) if a.shape==array.shape and np.array_equal(a,array)),None)
                    if duplicate is None:actual.append(array.copy())
                    rows.append(dict(id=iid,split=split,label=text,font=family,size=size,
                        image=relative(base/'images'/(iid+'.png')),array=relative(base/'arrays'/(iid+'.npy')),
                        valid_width=width,time_steps=steps,ctc_required_steps=needed,
                        pixel_group=duplicate if duplicate is not None else len(actual)-1,
                        label_source='same text passed to original pure text_image renderer',
                        real_data=False))
    assert len(rows)==plan['planned_generated_images'] and len(actual)<=4000
    by={}
    for r in rows:
        prev=by.setdefault(r['pixel_group'],(r['label'],r['split']))
        assert prev==(r['label'],r['split']),('pixel-label or split conflict',r['id'])
    # No optimization in these checks. Blank and digit zero are distinct.
    assert encode('0')==[1] and decode_path([0,1,1,0])=='0'
    assert encode('11')==[2,2] and decode_path([2,2,0,2])=='11'
    assert encode('111')==[2,2,2] and decode_path([2,0,2,0,2])=='111'
    assert decode_path([2,2,2])=='1' and decode_path([0,0])==''
    assert decode_path([2,0,2,0,2,0,2])=='1111'  # no expected-length truncation
    torch.manual_seed(21024);torch.set_num_threads(4);torch.set_num_interop_threads(1)
    model=DigitReader();params=sum(p.numel() for p in model.parameters());assert params<=300000
    sample=rows[0];array=np.load(absolute(sample['array']))
    with torch.no_grad():logits=model(torch.from_numpy(array[None]),torch.tensor([sample['time_steps']]))
    assert logits.shape==(1,sample['time_steps'],11)
    # Known valid repeated-digit targets: finite CTC; invalid alignment must not become zero.
    loss=torch.nn.CTCLoss(blank=0,zero_infinity=False)
    logp=torch.zeros(5,1,11).log_softmax(-1)
    valid=float(loss(logp,torch.tensor(encode('111')),torch.tensor([5]),torch.tensor([3])))
    invalid=float(loss(logp[:2],torch.tensor(encode('111')),torch.tensor([2]),torch.tensor([3])))
    assert np.isfinite(valid) and np.isinf(invalid)
    write(base/'manifest.json',rows)
    write(OUT/'training-program-checks.json',dict(utc=utc(),parameter_count=params,
        blank_index=0,digit_zero_index=1,repeated_11_111_encoding_decoding=True,
        minimum_alignment_all_records_valid=True,padding_and_lengths_from_pixels_only=True,
        labels_bound_to_render_calls=True,zero_infinity=False,invalid_alignment_remains_infinite=True,
        no_optimizer_constructed_or_updated=True,records=len(rows),unique_final_pixels=len(actual),
        generation_seconds=time.perf_counter()-generated_started,
        font_paths={k:str(font_root/v) for k,v in fonts.items()}))
    # All 18 illustrative images chosen by fixed order before training.
    chosen=[]
    for split in plan['strings']:
        for length in (1,2,3):
            chosen.extend([r for r in rows if r['split']==split and len(r['label'])==length][:2])
    canvas=Image.new('RGB',(850,100*len(chosen)),'#eeeeee');draw=ImageDraw.Draw(canvas)
    for j,r in enumerate(chosen):
        draw.text((8,100*j+5),str({k:r[k] for k in ('id','split','font','size','label')}),fill='black')
        im=Image.open(absolute(r['image'])).convert('RGB');canvas.paste(im.resize((im.width*2,im.height*2)),(8,100*j+25))
    canvas.save(base/'pretraining-contact.png')
    print('PREPARED_TRAINING',len(rows),'UNIQUE_PIXELS',len(actual),'PARAMETERS',params,flush=True)

if __name__=='__main__':main()
