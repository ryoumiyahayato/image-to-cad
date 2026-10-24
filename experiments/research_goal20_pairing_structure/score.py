"""Same Goal14/15 role/aggregate correctness; explicit shared-grid denominators."""
from collections import Counter
from common import *
metrics=load_module('goal15_metrics20',G15/'evaluate.py')
old_score=load_module('goal18_retention20',G18/'score.py')
rate=metrics.rate
def role_ok(r,k):return r['prediction']['parts'][k]==r['annotation']['parts'][k]
def score_rows(rows):return dict(global_metrics=metrics.global_metrics(rows),roles=metrics.role_metrics(rows))
def target_metrics(rows,role):
    other='denominator' if role=='numerator' else 'numerator'
    rr=[r for r in rows if r['target_role'] in [role,None]]
    wrong=[r for r in rr if r['target_role']==role];correct=[r for r in rr if r['target_role'] is None]
    return dict(unique_role_view_pairs=len(rr),correct_pair_count=len(correct),wrong_pair_count=len(wrong),target_accuracy=rate(sum(role_ok(r,role) for r in rr),len(rr)),
        target_contradiction_recall=rate(sum(role_ok(r,role) for r in wrong),len(wrong)),target_false_alarm=rate(sum(r['prediction']['parts'][role]=='CONTRADICTION' for r in correct),len(correct)),
        target_false_accept=rate(sum(r['prediction']['parts'][role]=='CONSISTENT' for r in wrong),len(wrong)),target_abstain=rate(sum(r['prediction']['parts'][role]=='INSUFFICIENT' for r in rr),len(rr)),
        other_numeric_errors={s:sum(r['prediction']['parts'][other]==s for r in rr) for s in ['CONTRADICTION','INSUFFICIENT','NOT_APPLICABLE']},
        other_roles_errors={k:sum(not role_ok(r,k) for r in rr) for k in ROLES if k not in [role,other]},
        overall_correct_wrong_role=sum(r['prediction']['overall']=='CONTRADICTION' and r['prediction']['parts'][role]!='CONTRADICTION' for r in wrong))
def condition(rows,grids):
    by={r['id']:r for r in rows};out=score_rows(rows);out['targets']={role:target_metrics(rows,role) for role in ['numerator','denominator']}
    gg=[]
    for grid in grids:
        rr=[by[k] for k in grid['pair_ids']];overall=all(metrics.correct(r) for r in rr);roles=all(metrics.parts_correct(r) for r in rr)
        gg.append(dict(grid,overall_all=overall,all_roles=roles,strict=overall and roles,target_all=all(role_ok(r,grid['target_role']) for r in rr),context_all=all(role_ok(r,grid['context_role']) for r in rr)))
    out['grids']=gg;out['strict_four']=rate(sum(g['strict'] for g in gg),len(gg));out['four_overall']=rate(sum(g['overall_all'] for g in gg),len(gg))
    out['blocks']=[]
    for bid in sorted({r['block'] for r in rows}):
        rr=[r for r in rows if r['block']==bid];gs=[g for g in gg if g['block']==bid]
        out['blocks'].append(dict(id=bid,pairs=len(rr),images=len({r['image_id'] for r in rr}),strict_four=rate(sum(g['strict'] for g in gs),len(gs)),all_roles_correct=rate(sum(metrics.parts_correct(r) for r in rr),len(rr)),
            all_strict=all(g['strict'] for g in gs),targets={role:target_metrics(rr,role) for role in ['numerator','denominator']}))
    out['blocks_all_strict']=rate(sum(b['all_strict'] for b in out['blocks']),len(out['blocks']))
    out['grid_slices']={key:{str(v):rate(sum(g['strict'] for g in gg if (g['target_role'] if key=='target_role' else g['change'][key])==v),sum((g['target_role'] if key=='target_role' else g['change'][key])==v for g in gg)) for v in sorted({g['target_role'] if key=='target_role' else g['change'][key] for g in gg},key=str)} for key in ['target_role','digits','variant','changed_digits']}
    return out
def retention(before,after):
    out=old_score.retention(before,after);bm={r['id']:r for r in before};am={r['id']:r for r in after}
    for name,fn in [('overall',metrics.correct),('all_roles',metrics.parts_correct)]:
        added=[r['id'] for r in after if fn(r) and not fn(bm[r['id']])]
        out[name]['added_ids']=added;out[name]['added']=len(added);out[name]['net_change']=len(added)-out[name]['broken']['n']
    for role in ROLES:
        gained=[r['id'] for r in after if role_ok(r,role) and not role_ok(bm[r['id']],role)]
        broken=[r['id'] for r in before if role_ok(r,role) and not role_ok(am[r['id']],role)]
        out['roles'][role].update(added_ids=gained,all_state_broken_ids=broken,net_change=len(gained)-len(broken))
    protected=[(r,k) for r in before for k in ROLES if r['annotation']['parts'][k]=='INSUFFICIENT' and role_ok(r,k)]
    broken=[dict(id=r['id'],role=k,after=am[r['id']]['prediction']['parts'][k]) for r,k in protected if not role_ok(am[r['id']],k)]
    all_unknown=[(r,k) for r in after for k in ROLES if r['annotation']['parts'][k]=='INSUFFICIENT']
    out['unknown_F_correct_broken']=dict(n=len(broken),d=len(protected),items=broken)
    out['unknown_after_wrong']=rate(sum(not role_ok(r,k) for r,k in all_unknown),len(all_unknown))
    out['unit_context_all_state_protection']={k:dict(broken=len(out['roles'][k]['all_state_broken_ids']),ids=out['roles'][k]['all_state_broken_ids']) for k in ['unit','context']}
    return out
