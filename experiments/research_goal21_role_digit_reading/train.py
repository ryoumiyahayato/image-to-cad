"""The single predeclared CPU trajectory. No evaluation or checkpoint selection in loop."""
import time
import random
import numpy as np
import torch
from common import *
from model import DigitReader,batch_arrays,encode

def main():
    assert read(OUT/'training-trigger.json')['TRAINING_TRIGGER']=='MET'
    checks=read(OUT/'training-program-checks.json');assert checks['minimum_alignment_all_records_valid']
    config=read(OUT/'frozen-plan.json')['training'];fit=OUT/'fit';fit.mkdir(exist_ok=False)
    write(fit/'trajectory-start.json',dict(utc=utc(),trajectories=1,configuration=config))
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.manual_seed(config['seed']);random.seed(config['seed']);np.random.seed(config['seed'])
    rng=random.Random(config['seed'])
    rows=[r for r in read(OUT/'training-data/manifest.json') if r['split']=='train']
    arrays=[np.load(absolute(r['array'])) for r in rows]
    model=DigitReader();assert sum(p.numel() for p in model.parameters())==checks['parameter_count']
    opt=torch.optim.Adam(model.parameters(),lr=.001,betas=(.9,.999),eps=1e-8,weight_decay=0)
    criterion=torch.nn.CTCLoss(blank=0,zero_infinity=False)
    log=[];updates=0;started=time.perf_counter();last_step_seconds=0.;reason='UPDATE_LIMIT'
    model.train()
    while updates<config['updates_limit']:
        elapsed=time.perf_counter()-started
        if elapsed+max(last_step_seconds*2,.5)>=config['hard_seconds_limit']:
            reason='TIME_LIMIT';break
        step_started=time.perf_counter();ids=[rng.randrange(len(rows)) for _ in range(config['batch_size'])]
        x,lengths=batch_arrays([arrays[i] for i in ids]);labels=[rows[i]['label'] for i in ids]
        target_lengths=torch.tensor([len(s) for s in labels],dtype=torch.long)
        target=torch.tensor([c for s in labels for c in encode(s)],dtype=torch.long)
        opt.zero_grad(set_to_none=True)
        logits=model(x,lengths)
        loss=criterion(logits.log_softmax(-1).transpose(0,1),target,lengths,target_lengths)
        if not torch.isfinite(loss):reason='NONFINITE_LOSS';break
        loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),5.)
        if not torch.isfinite(norm):reason='NONFINITE_GRADIENT';break
        opt.step();updates+=1;last_step_seconds=time.perf_counter()-step_started
        log.append(dict(update=updates,loss=float(loss.detach()),seconds=time.perf_counter()-started,
            sampled_ids=[rows[i]['id'] for i in ids]))
        if updates%100==0:print('UPDATE',updates,'LOSS',round(log[-1]['loss'],6),'SECONDS',round(log[-1]['seconds'],2),flush=True)
    assert all(torch.isfinite(p).all() for p in model.parameters())
    torch.save(dict(model_state=model.state_dict(),optimizer_state=opt.state_dict(),updates=updates,
        configuration=config,torch_rng_state=torch.get_rng_state(),sampler_state=rng.getstate(),
        checkpoint_rule='last valid state; never selected by validation or test'),fit/'final.pt')
    seconds=time.perf_counter()-started
    write(fit/'training-log.json',log)
    write(fit/'resource.json',dict(utc=utc(),updates=updates,trajectories=1,training_seconds=seconds,
        reason=reason,hard_limit_seconds=config['hard_seconds_limit'],within_budget=seconds<=600,
        parameter_count=checks['parameter_count'],train_records=len(rows),
        optimizer_steps=sorted({int(v['step']) for v in opt.state.values()}),
        final_loss=log[-1]['loss'] if log else None,python=sys.executable,
        torch_version=torch.__version__,device='cpu',threads=4,evaluation_during_training=False))
    print('TRAINING_FINISHED',updates,round(seconds,3),reason,flush=True)

if __name__=='__main__':main()
