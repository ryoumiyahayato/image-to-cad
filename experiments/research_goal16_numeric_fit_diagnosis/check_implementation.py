"""Local per-role implementation checks; backward only, zero optimizer updates."""
import time,platform
from PIL import Image
from runtime import *

def main():
    started=time.perf_counter();assert not (OUT/'initial.pt').exists();configure();model=JointModel();model.eval()
    initial={k:v.detach().clone() for k,v in model.state_dict().items()};rows=read(OUT/'data/diagnostic.json');cache=load_pixels(rows);x=inputs(rows,cache)
    y=model(*x);target,overall=targets(rows);errors=[];examples=[]
    preview=OUT/'actual-inputs';preview.mkdir(parents=True,exist_ok=True)
    for i,row in enumerate(rows):
        decoded=''.join(CHARSET[t-1] for t in x[1][i].tolist() if t);length=int((x[1][i]!=0).sum())
        if decoded!=row['candidate_raw'] or length!=len(row['candidate_raw']):errors.append(['character alignment',row['id']])
        if int(x[2][i])!=SCOPES.index(row['scope']):errors.append(['scope alignment',row['id']])
        if [STATES[t] for t in target[i].tolist()]!=[row['annotation']['parts'][r] for r in ROLES]:errors.append(['role index',row['id']])
        raw=np.array(Image.open(OUT/'data'/row['image']))
        restored=np.rint((1-x[0][i,0].numpy())*255).astype(np.uint8)
        if not np.array_equal(raw,restored):errors.append(['pixel alignment',row['id']])
        np.save(preview/(row['id']+'.npy'),x[0][i].numpy());Image.fromarray(restored).save(preview/(row['id']+'.png'))
        examples.append(dict(id=row['id'],image=row['image'],candidate_raw=row['candidate_raw'],decoded=decoded,characters=x[1][i].tolist(),
             length=length,scope=row['scope'],scope_index=int(x[2][i]),target_indices=target[i].tolist(),targets=row['annotation'],
             initial_output_logits=y[i].detach().tolist(),initial_output=annotation_from_classes(y[i].argmax(-1).tolist()),tensor_shape=list(x[0][i].shape)))
    # Pair permutation must permute inputs and outputs identically. Padding beyond actual lengths must be ignored.
    permutation=torch.arange(len(rows)-1,-1,-1)
    permuted=model(x[0][permutation],x[1][permutation],x[2][permutation])
    padding=model(x[0],torch.cat([x[1],torch.zeros((len(rows),7),dtype=torch.long)],1),x[2])
    pair_error=float((permuted-y[permutation]).abs().max());padding_error=float((padding-y).abs().max())
    if pair_error>1e-6:errors.append(['pair permutation',pair_error])
    if padding_error>1e-6:errors.append(['GRU padding',padding_error])
    poisoned=[dict(r,annotation={'never':'input'},font='wrong',component='wrong',split='wrong',source_index=999) for r in rows]
    poisoned_x=inputs(poisoned,cache)
    if not all(torch.equal(a,b) for a,b in zip(x,poisoned_x)):errors.append(['metadata leaks'])
    weights=torch.tensor(CONFIG['role_class_weights'])
    unreduced=torch.nn.functional.cross_entropy(y.reshape(-1,4),target.reshape(-1),weight=weights,reduction='none').view(-1,8)
    contributions=unreduced.sum(0)/weights[target].sum()
    total,part,glob=losses(y,rows)
    manual_equal=torch.allclose(contributions.sum(),part,atol=1e-7)
    if not manual_equal:errors.append(['weighted CE reduction'])
    gradients={}
    for i,role in enumerate(ROLES):
        gy,gw,gb=torch.autograd.grad(contributions[i],[y,model.joint[2].weight,model.joint[2].bias],retain_graph=True)
        head=gw[i*4:(i+1)*4];head_bias=gb[i*4:(i+1)*4]
        gradients[role]=dict(contribution_to_actual_training_part_loss=float(contributions[i]),unreduced_weighted_nll=unreduced[:,i].detach().tolist(),
          truth_counts=dict(__import__('collections').Counter(r['annotation']['parts'][role] for r in rows)),
          output_logit_gradient_l1=float(gy[:,i].abs().sum()),head_weight_gradient_l1=float(head.abs().sum()),head_bias_gradient=head_bias.tolist(),
          nonzero_gradient_for_all_four_classes=[bool((gy[:,i,j]!=0).any()) for j in range(4)])
        if not float(head.abs().sum())>0 or not float(gy[:,i].abs().sum())>0:errors.append(['no role gradient',role])
    # Exact categorical cases and one finite soft distribution verify the product formulas against the same contract.
    cases=[[0]*8,[3]*8]
    for i in range(8):
        for state in [1,2,3]:v=[0]*8;v[i]=state;cases.append(v)
        for j in range(8):
            if i!=j:v=[0]*8;v[i]=1;v[j]=2;cases.append(v)
    categorical=torch.full((len(cases),8,4),-80.)
    for i,case in enumerate(cases):
        for j,state in enumerate(case):categorical[i,j,state]=80.
    distributions=global_probabilities(categorical);semantic_rows=[]
    for case,p in zip(cases,distributions):
        a=annotation_from_classes(case);pred=OVERALL[int(p.argmax())]
        if pred!=a['overall']:errors.append(['aggregate categorical mismatch',case])
        semantic_rows.append(dict(role_indices=case,discrete=a,differentiable_probabilities=p.tolist()))
    soft=torch.zeros((1,8,4),dtype=torch.float64);soft[:,:,0]=1.;soft[0,0]=torch.tensor([.2,.3,.4,.1]);soft[0,1]=torch.tensor([.4,.2,.1,.3])
    enumerated=torch.zeros(3,dtype=torch.float64)
    for a in range(4):
        for b in range(4):
            case=[a,b]+[0]*6;state=annotation_from_classes(case)['overall'];enumerated[OVERALL.index(state)]+=soft[0,0,a]*soft[0,1,b]
    actual=global_probabilities(soft.clamp_min(1e-200).log())[0]
    if not torch.allclose(actual,enumerated,atol=1e-7):errors.append(['soft aggregation probability mismatch'])
    # Scope supervision deliberately differs only in context role for the matched context examples.
    context=[r for r in rows if r['mechanism']=='context'];scope_cases=[]
    for r in context:
        if r['scope']=='NUMBER_UNIT':
            twin=next(p for p in context if p['image']==r['image'] and p['candidate_raw']==r['candidate_raw'] and p['scope']=='NUMBER_UNIT_CONTEXT')
            changed=[k for k in ROLES if r['annotation']['parts'][k]!=twin['annotation']['parts'][k]]
            if changed!=['context']:errors.append(['scope supervision',r['id']])
            scope_cases.append(dict(ids=[r['id'],twin['id']],changed_roles=changed))
    assert all(torch.equal(v,initial[k]) for k,v in model.state_dict().items())
    result=dict(utc=utc(),seconds=time.perf_counter()-started,errors=errors,passed=not errors,optimizer_updates=0,
       parameters=sum(p.numel() for p in model.parameters()),model_source_byte_equal=(HERE/'model.py').read_bytes()==(G15/'model.py').read_bytes(),
       configuration_equal_to_goal15=CONFIG==read(OLD_OUT/'frozen-plan.json')['configuration'],
       pair_permutation_max_error=pair_error,padding_max_error=padding_error,weighted_role_loss_manual_equal=bool(manual_equal),
       actual_part_loss=float(part),actual_global_loss=float(glob),actual_total_loss=float(total),gradients=gradients,scope_cases=scope_cases,
       aggregation_cases=semantic_rows,soft_aggregation=dict(enumerated=enumerated.tolist(),actual=actual.tolist()),
       python=sys.executable,python_version=platform.python_version(),torch=torch.__version__,numpy=np.__version__,pillow=__import__('PIL').__version__,
       imports_seconds=IMPORT_SECONDS,memory=memory(),limitations='Checks exclude label/index/adapter/padding/role-gradient omission and aggregation-formula mismatch on these cases; do not identify an optimizer or representation failure layer.',
       model_or_loss_implementation_repairs='NONE: no reproducible implementation error found by these checks')
    write(OUT/'implementation-check.json',result);write(OUT/'implementation-examples.json',examples)
    assert not errors
    torch.save(dict(model_state=initial,seed=SEED,configuration=CONFIG,optimizer_updates=0,initialization='PyTorch defaults; no pretrained state'),OUT/'initial.pt')
    print(json.dumps({k:result[k] for k in ['passed','errors','parameters','optimizer_updates','pair_permutation_max_error','padding_max_error','seconds']}))

if __name__=='__main__':main()
