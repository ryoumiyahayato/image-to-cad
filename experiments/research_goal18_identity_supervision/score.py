"""Existing role/aggregate scoring with explicit Goal18 four-grid and retention units."""
from collections import defaultdict
from common import *
metrics=load_module('goal15_metrics18',G15/'evaluate.py');rate=metrics.rate
def stats(rows):
    out=dict(global_metrics=metrics.global_metrics(rows),roles=metrics.role_metrics(rows))
    unknown=[(r,k) for r in rows for k,v in r['annotation']['parts'].items() if v=='INSUFFICIENT']
    out['unknown_roles_made_determinate']=rate(sum(r['prediction']['parts'][k]!='INSUFFICIENT' for r,k in unknown),len(unknown))
    joint=[r for r in rows if r['annotation']['has_contradiction'] and r['annotation']['has_insufficient']]
    out['joint_every_contradiction_and_unknown_retained']=rate(sum(all(r['prediction']['parts'][k]==v for k,v in r['annotation']['parts'].items() if v in ['CONTRADICTION','INSUFFICIENT']) for r in joint),len(joint))
    out['abstain_all']=rate(sum(r['prediction']['overall']=='INSUFFICIENT' for r in rows),len(rows))
    if rows and 'target_role' in rows[0]:
        wrong=[r for r in rows if r['annotation']['overall']=='CONTRADICTION']
        out['target_role_contradiction_recall']=rate(sum(r['prediction']['parts'][r['target_role']]=='CONTRADICTION' for r in wrong),len(wrong))
        cross=defaultdict(list);groups=defaultdict(list)
        for r in rows:cross[r['contrast']].append(r);groups[r['component']].append(r)
        full=[(k,b) for k,b in sorted(cross.items()) if len(b)==4]
        out['four_grids']=[dict(id=k,component=b[0]['component'],overall_all=all(metrics.correct(r) for r in b),roles_all=all(metrics.parts_correct(r) for r in b),pair_ids=[r['id'] for r in b]) for k,b in full]
        out['four_overall']=rate(sum(x['overall_all'] for x in out['four_grids']),len(full))
        out['four_roles']=rate(sum(x['roles_all'] for x in out['four_grids']),len(full))
        out['groups']=[dict(id=k,role=b[0]['target_role'],pairs=len(b),overall_correct=sum(metrics.correct(r) for r in b),roles_correct=sum(metrics.parts_correct(r) for r in b),overall_all=all(metrics.correct(r) for r in b),roles_all=all(metrics.parts_correct(r) for r in b)) for k,b in sorted(groups.items())]
        out['groups_all_roles']=rate(sum(g['roles_all'] for g in out['groups']),len(groups))
    return out

def detailed(rows):
    result=stats(rows)
    result['by_role']={k:stats([r for r in rows if r['target_role']==k]) for k in sorted({r['target_role'] for r in rows})}
    result['by_digits']={str(k):stats([r for r in rows if r['digits']==k]) for k in sorted({r['digits'] for r in rows},key=str)}
    result['by_variant']={k:stats([r for r in rows if r['variant']==k]) for k in sorted({r['variant'] for r in rows})}
    return result

def retention(baseline,after):
    bm={r['id']:r for r in baseline};after_by={r['id']:r for r in after}
    out={}
    for name,check in [('overall',metrics.correct),('all_roles',metrics.parts_correct)]:
        good=[r for r in baseline if check(r)];broken=[r['id'] for r in good if not check(after_by[r['id']])]
        out[name]=dict(previous_correct=len(good),broken=rate(len(broken),len(good)),broken_ids=broken)
    out['roles']={}
    for role in ROLES:
        correct=[r for r in baseline if r['annotation']['parts'][role]==r['prediction']['parts'][role]]
        positive=[r for r in correct if r['annotation']['parts'][role]=='CONSISTENT']
        out['roles'][role]=dict(all_F_correct_broken=rate(sum(after_by[r['id']]['prediction']['parts'][role]!=r['annotation']['parts'][role] for r in correct),len(correct)),
            true_consistent_F_correct_broken=rate(sum(after_by[r['id']]['prediction']['parts'][role]!='CONSISTENT' for r in positive),len(positive)),
            broken_ids=[r['id'] for r in positive if after_by[r['id']]['prediction']['parts'][role]!='CONSISTENT'])
    integers=[r for r in baseline if r['source_kind']=='integer' and r['annotation']['overall']=='CONSISTENT' and metrics.parts_correct(r)]
    out['correct_integer_all_roles_broken']=rate(sum(not metrics.parts_correct(after_by[r['id']]) for r in integers),len(integers))
    return out
