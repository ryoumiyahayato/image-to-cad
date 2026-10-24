"""Reuse explicit Goal18 scoring; add target/context separation and matched transitions."""
from collections import Counter,defaultdict
from common import *
prior=load_module('goal18_score_explicit19',G18/'score.py')
rate=prior.rate
def role_ok(r,k):return r['prediction']['parts'][k]==r['annotation']['parts'][k]
def target_ok(r):return role_ok(r,r['target_role'])
def context_ok(r):return role_ok(r,r['context_role'])
def other_ok(r):return all(role_ok(r,k) for k in ROLES if k not in [r['target_role'],r['context_role']])
def stats(rows):
    out=prior.stats(rows);wrong=[r for r in rows if r['annotation']['parts'][r['target_role']]=='CONTRADICTION'];right=[r for r in rows if r not in wrong]
    out['target']=dict(accuracy=rate(sum(target_ok(r) for r in rows),len(rows)),contradiction_recall=rate(sum(target_ok(r) for r in wrong),len(wrong)),
        false_alarm=rate(sum(r['prediction']['parts'][r['target_role']]=='CONTRADICTION' for r in right),len(right)),false_accept=rate(sum(r['prediction']['parts'][r['target_role']]=='CONSISTENT' for r in wrong),len(wrong)),
        abstain=rate(sum(r['prediction']['parts'][r['target_role']]=='INSUFFICIENT' for r in rows),len(rows)),erroneous_NA=rate(sum(r['prediction']['parts'][r['target_role']]=='NOT_APPLICABLE' for r in rows),len(rows)))
    out['context']=dict(accuracy=rate(sum(context_ok(r) for r in rows),len(rows)),predicted_states=dict(Counter(r['prediction']['parts'][r['context_role']] for r in rows)))
    out['other_roles_errors']={k:sum(not role_ok(r,k) for r in rows if k not in [r['target_role'],r['context_role']]) for k in ROLES}
    out['failure_separation']=dict(target_wrong=sum(not target_ok(r) for r in rows),target_right_context_wrong=sum(target_ok(r) and not context_ok(r) for r in rows),target_right_other_wrong=sum(target_ok(r) and not other_ok(r) for r in rows),
        overall_correct_without_true_target_contradiction=sum(r['prediction']['overall']=='CONTRADICTION' and not target_ok(r) for r in wrong))
    return out
def detailed(rows):
    out=stats(rows)
    for key,name in [('target_role','by_role'),('digits','by_digits'),('variant','by_variant'),('block','by_block')]:
        out[name]={str(v):stats([r for r in rows if r[key]==v]) for v in sorted({r[key] for r in rows},key=str)}
    return out
def transition(a,b):
    good=target_ok(a);now=target_ok(b)
    assert a['annotation']==b['annotation']
    return dict(before=a['id'],after=b['id'],block=a['block'],target_role=a['target_role'],digits=a['digits'],variant=a['variant'],
        target_before_correct=good,target_after_correct=now,target_broken=good and not now,target_repaired=not good and now,
        target_preserved_context_regressed=good and now and context_ok(a) and not context_ok(b),
        target_preserved_other_regressed=good and now and other_ok(a) and not other_ok(b),
        roles_regressed=[k for k in ROLES if role_ok(a,k) and not role_ok(b,k)],
        before_prediction=a['prediction'],after_prediction=b['prediction'])
def transitions(joined):
    by={(r['block'],r['condition'],r['source_index'],r['candidate_index']):r for r in joined}
    result={}
    for ca,cb,factor in EDGES:
        records=[transition(r,by[(r['block'],cb,r['source_index'],r['candidate_index'])]) for r in joined if r['condition']==ca]
        def summarize(rs):
            good=sum(r['target_before_correct'] for r in rs)
            return dict(pairs=len(rs),target_correct_before=good,target_correct_after=sum(r['target_after_correct'] for r in rs),target_broken=rate(sum(r['target_broken'] for r in rs),good),target_repaired=sum(r['target_repaired'] for r in rs),
                target_preserved_context_regressed=sum(r['target_preserved_context_regressed'] for r in rs),target_preserved_other_regressed=sum(r['target_preserved_other_regressed'] for r in rs),
                blocks_with_target_regression=sorted({r['block'] for r in rs if r['target_broken']}))
        result[f'{ca}->{cb}']=dict(factor=factor,summary=summarize(records),by_block={bid:summarize([r for r in records if r['block']==bid]) for bid in sorted({r['block'] for r in records})},records=records)
    return result
