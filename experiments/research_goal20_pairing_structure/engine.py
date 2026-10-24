"""Goal18 restoration and Goal16 numerical runtime, with this goal's paths."""
import time
IMPORT_START=time.perf_counter()
from common import *
legacy=load_module('goal18_engine20',G18/'engine.py')
for name in ['torch','np','JointModel','configure','inputs','losses','memory','exact','restored','cache_pixels']:
    globals()[name]=getattr(legacy,name)
IMPORT_SECONDS=time.perf_counter()-IMPORT_START
def save_final(path,model,opt,arm,updates):
    torch.save(dict(model_state=model.state_dict(),optimizer_state=opt.state_dict(),configuration=CONFIG,arm=arm,historical_updates=5000,new_updates=updates,total_updates=5000+updates,
        torch_rng_state=torch.get_rng_state(),next_batch_plan_index=updates,initial_checkpoint=str(INITIAL),goal='Goal20',selection='Fixed final checkpoint after 1992 planned updates or hard budget stop, never metric-selected'),path)
