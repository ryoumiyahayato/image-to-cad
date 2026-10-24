"""One CPU fit and frozen evaluation. Last checkpoint only. No real inputs."""
import time
PROCESS_START=time.perf_counter()
import os,sys,json,ctypes,random,argparse,platform
from datetime import datetime,timezone
import numpy as np
from PIL import Image
IMPORT_TORCH_START=time.perf_counter()
import torch
TORCH_IMPORT_SECONDS=time.perf_counter()-IMPORT_TORCH_START
from common import *
from model import JointModel,global_probabilities
IMPORT_SECONDS=time.perf_counter()-PROCESS_START

def utc():return datetime.now(timezone.utc).isoformat()

def memory():
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong),('PeakWorkingSetSize',ctypes.c_size_t),
                  ('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                  ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                  ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t),('PrivateUsage',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32');psapi=ctypes.WinDLL('psapi');kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    ok=psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb)
    if not ok:raise ctypes.WinError()
    return dict(peak_working_set_bytes=counters.PeakWorkingSetSize,peak_pagefile_bytes=counters.PeakPagefileUsage,
                current_private_bytes=counters.PrivateUsage,method='Windows PROCESS_MEMORY_COUNTERS_EX for this worker PID')

def configure():
    torch.set_num_threads(CONFIG['cpu_threads']);torch.set_num_interop_threads(CONFIG['interop_threads'])
    torch.manual_seed(SEED);np.random.seed(SEED);random.seed(SEED)
    torch.use_deterministic_algorithms(True)

def load_rows(split):return read(OUT/'data'/f'{split}.json')

def load_pixels(rows):
    cache={}
    for row in rows:
        x=feature_record(row)
        p=(OUT/'data'/x['image']).resolve()
        if not p.is_relative_to((OUT/'data/images').resolve()):raise ValueError('Only this goal original images are allowed')
        if x['image'] not in cache:
            a=np.array(Image.open(p).convert('L'),dtype=np.uint8)
            if a.shape!=(128,512):raise ValueError('Frozen input shape mismatch')
            cache[x['image']]=torch.from_numpy(a.copy())
    return cache

def inputs(rows,cache):
    # Explicit allowlist; metadata/roles/labels cannot pass to the network.
    xx=[feature_record(r) for r in rows]
    images=torch.stack([cache[x['image']] for x in xx]).unsqueeze(1).float()
    chars=torch.tensor([encode_candidate(x['candidate_raw']) for x in xx],dtype=torch.long)
    scopes=torch.tensor([SCOPES.index(x['scope']) for x in xx],dtype=torch.long)
    return (255.-images)/255.,chars,scopes

def preflight():
    configure();initialization=time.perf_counter();model=JointModel();init_seconds=time.perf_counter()-initialization
    parameter_count=sum(x.numel() for x in model.parameters());assert parameter_count<=500000
    rows=load_rows('train');assert rows
    chosen=[]
    for mode in ['complete','gray_outside','unit_hidden','numeric_hidden']:
        chosen.append(next(r for r in rows if r['condition']==mode))
    cache=load_pixels(chosen);x=inputs(chosen,cache)
    with torch.no_grad():y=model(*x)
    assert list(y.shape)==[4,8,4]
    previews=OUT/'actual-inputs';previews.mkdir(exist_ok=True)
    records=[]
    for i,row in enumerate(chosen):
        a=x[0][i].numpy();np.save(previews/f'{i}.npy',a)
        Image.fromarray(np.rint((1-a[0])*255).astype(np.uint8)).save(previews/f'{i}.png')
        records.append(dict(pair_id=row['id'],pixels_tensor=f'actual-inputs/{i}.npy',candidate_raw=row['candidate_raw'],scope=row['scope'],shape=list(a.shape),
                            pixel_roundtrip_equal=bool(np.array_equal(np.rint((1-a[0])*255).astype(np.uint8),cache[row['image']].numpy()))))
    write(OUT/'preflight.json',dict(utc=utc(),python=sys.executable,python_version=platform.python_version(),torch=torch.__version__,numpy=np.__version__,
          pillow=__import__('PIL').__version__,model=str(model),parameters=parameter_count,trainable_parameters=parameter_count,
          forward_shape=list(y.shape),actual_inputs=records,import_seconds=IMPORT_SECONDS,initialization_seconds=init_seconds,
          train_started=False,device='cpu',threads=torch.get_num_threads(),memory=memory()))
    print(json.dumps(dict(stage='PREFLIGHT_ONLY',parameters=parameter_count,shape=list(y.shape),torch=torch.__version__,import_seconds=IMPORT_SECONDS)),flush=True)

def run():
    plan=read(OUT/'frozen-plan.json');assert plan['data_checks_passed'] and plan['visual_review_completed']
    assert plan['configuration']==CONFIG
    run_dir=OUT/'run';run_dir.mkdir(exist_ok=True)
    with (run_dir/'started.json').open('x',encoding='utf8') as stream:
        json.dump(dict(utc=utc(),pid=os.getpid(),configuration=CONFIG,one_fit_only=True),stream,indent=2)
    configure();init_start=time.perf_counter();model=JointModel();optimizer=torch.optim.Adam(model.parameters(),lr=CONFIG['learning_rate'],betas=tuple(CONFIG['adam_betas']),eps=CONFIG['adam_eps'],weight_decay=CONFIG['weight_decay'])
    parameter_count=sum(p.numel() for p in model.parameters());assert parameter_count==plan['model_parameters']
    initial={n:p.detach().clone() for n,p in model.named_parameters()};init_seconds=time.perf_counter()-init_start
    loading=time.perf_counter();rows=load_rows('train');cache=load_pixels(rows);load_seconds=time.perf_counter()-loading
    generator=torch.Generator().manual_seed(SEED);class_weights=torch.tensor(CONFIG['role_class_weights'])
    curve=[];updates=0;stop_reason='MAX_UPDATES';gradients=None;start=time.perf_counter();max_step=0.
    model.train()
    while updates<CONFIG['max_updates']:
        elapsed=time.perf_counter()-start
        if elapsed+max(5.,max_step*2)>CONFIG['max_training_seconds']:stop_reason='WALL_BUDGET';break
        step_start=time.perf_counter();indices=torch.randint(len(rows),(CONFIG['batch_size'],),generator=generator).tolist()
        batch=[rows[i] for i in indices];x=inputs(batch,cache)
        target=torch.tensor([[STATES.index(r['annotation']['parts'][role]) for role in ROLES] for r in batch],dtype=torch.long)
        overall_target=torch.tensor([OVERALL.index(r['annotation']['overall']) for r in batch],dtype=torch.long)
        logits=model(*x)
        part_loss=torch.nn.functional.cross_entropy(logits.reshape(-1,4),target.reshape(-1),weight=class_weights)
        overall_loss=torch.nn.functional.nll_loss(global_probabilities(logits).log(),overall_target)
        loss=part_loss+CONFIG['overall_loss_weight']*overall_loss
        if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss; trial invalid; do not start a second training')
        optimizer.zero_grad(set_to_none=True);loss.backward()
        if gradients is None:gradients=dict(tensors_with_nonzero_gradient=sum(bool(p.grad is not None and (p.grad!=0).any()) for p in model.parameters()),
                                           total_absolute_gradient=sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
        torch.nn.utils.clip_grad_norm_(model.parameters(),CONFIG['gradient_clip_norm']);optimizer.step();updates+=1
        seconds=time.perf_counter()-step_start;max_step=max(max_step,seconds)
        row=dict(update=updates,loss=float(loss.detach()),part_loss=float(part_loss.detach()),overall_loss=float(overall_loss.detach()),
                 training_elapsed_seconds=time.perf_counter()-start,step_seconds=seconds)
        curve.append(row)
        if updates==1 or updates%50==0:print(json.dumps(dict(stage='TRAIN',**row)),flush=True)
    training_seconds=time.perf_counter()-start
    if updates==0:raise RuntimeError('No update within the budget')
    parameter_delta=sum(float((p.detach()-initial[n]).square().sum()) for n,p in model.named_parameters())**.5
    checkpoint=run_dir/'last.pt'
    torch.save(dict(model_state=model.state_dict(),optimizer_state=optimizer.state_dict(),updates=updates,configuration=CONFIG,
                    torch_rng_state=torch.get_rng_state(),sampler_rng_state=generator.get_state(),checkpoint_rule=CONFIG['checkpoint']),checkpoint)
    write(run_dir/'training-curve.json',curve)
    # Validation and sealed-test labels are first read by this worker only after training has ended and last.pt exists.
    eval_start=time.perf_counter();model.eval();predictions={}
    with torch.no_grad():
        for split in ['train','validation','sealed-test']:
            eval_rows=rows if split=='train' else load_rows(split)
            eval_cache=cache if split=='train' else load_pixels(eval_rows)
            output=[]
            for offset in range(0,len(eval_rows),32):
                batch=eval_rows[offset:offset+32];logits=model(*inputs(batch,eval_cache))
                states=logits.argmax(-1).tolist();probabilities=logits.softmax(-1).tolist()
                for row,state,prob in zip(batch,states,probabilities):
                    output.append(dict(id=row['id'],prediction=annotation_from_classes(state),part_probabilities=prob))
            write(run_dir/f'{split}-predictions.json',output)
            predictions[split]=len(output)
            print(json.dumps(dict(stage='EVALUATE_FINAL_CHECKPOINT',split=split,pairs=len(output))),flush=True)
    evaluation_seconds=time.perf_counter()-eval_start
    # Read back the same last checkpoint and compare every tensor; no retraining/selection.
    loaded=torch.load(checkpoint,map_location='cpu',weights_only=False)
    assert loaded['updates']==updates and len(loaded['optimizer_state']['state'])>0
    assert all(torch.equal(model.state_dict()[k],v) for k,v in loaded['model_state'].items())
    resource=dict(status='COMPLETE',utc=utc(),pid=os.getpid(),python=sys.executable,torch=torch.__version__,device='cpu',
                  parameters=parameter_count,checkpoint_bytes=checkpoint.stat().st_size,updates=updates,stop_reason=stop_reason,
                  import_seconds=IMPORT_SECONDS,torch_import_seconds=TORCH_IMPORT_SECONDS,initialization_seconds=init_seconds,train_data_load_seconds=load_seconds,
                  raw_float32_parameter_bytes=parameter_count*4,
                  training_seconds=training_seconds,evaluation_seconds=evaluation_seconds,process_elapsed_seconds=time.perf_counter()-PROCESS_START,
                  cpu_threads=torch.get_num_threads(),interop_threads=torch.get_num_interop_threads(),actual_input_shape=[32,1,128,512],
                  gradient_check=gradients,parameter_change_l2=parameter_delta,checkpoint_state_readback=True,predictions=predictions,
                  validation_test_used_for_optimization=False,**memory())
    write(run_dir/'resource.json',resource);print(json.dumps(resource),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--preflight',action='store_true');args=ap.parse_args()
    if args.preflight:preflight()
    else:
        try:run()
        except Exception as exc:
            write(OUT/'run/failure.json',dict(utc=utc(),error=repr(exc),status='INVALID_OR_FAILED_DO_NOT_RETRAIN',pid=os.getpid(),**memory()))
            raise
