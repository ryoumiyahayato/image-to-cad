"""Partition/component/mechanism/role coverage and explicit single-factor contrasts."""
import csv
from collections import defaultdict,Counter
from common import *

def audit(rows,groups,output):
    output.mkdir(parents=True,exist_ok=True);counts=Counter()
    for r in rows:
        for role in ROLES:counts[(r['split'],r['component'],r['mechanism'],role,r['annotation']['parts'][role])]+=1
    records=[dict(zip(['split','component','mechanism','role','state','pairs'],[*k,v])) for k,v in sorted(counts.items())]
    with (output/'partition-component-mechanism-role.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=['split','component','mechanism','role','state','pairs']);w.writeheader();w.writerows(records)
    group_map={g['id']:g for g in groups};contrasts=[]
    for gid in sorted({r['group'] for r in rows}):
        g=group_map[gid];sample=next(r for r in rows if r['group']==gid)
        aa,bb=[parts(s) for s in g['sources']]
        changed=[r for r in ROLES if aa[r]!=bb[r]]
        contrasts.append(dict(group=gid,component=sample['component'],split=sample['split'],mechanism=sample['mechanism'],
            candidates=g['candidates'],changed_contract_roles=changed,single_contract_role=changed[0] if len(changed)==1 else None,
            interpretation='Single contract role' if len(changed)==1 else 'One structural/visual operation can alter several contract roles; not a single-role claim'))
    write(output/'contrasts.json',contrasts)
    result={}
    for split in ['train','validation','sealed-test']:
        rr=[r for r in rows if r['split']==split];cs=[c for c in contrasts if c['split']==split]
        chars=set(''.join(r['candidate_raw'] for r in rr))
        result[split]=dict(pairs=len(rr),images=len({r['image'] for r in rr}),components=len({r['component'] for r in rr}),
          mechanisms={me:dict(components=sorted({c['component'] for c in cs if c['mechanism']==me}),semantic_groups=len({c['group'] for c in cs if c['mechanism']==me})) for me in MECHANISMS},
          role_states={role:dict(Counter(r['annotation']['parts'][role] for r in rr)) for role in ROLES},
          single_role_contrast_components={role:sorted({c['component'] for c in cs if c['single_contract_role']==role}) for role in ROLES},
          joint_contradiction_unknown=sum(r['annotation']['has_contradiction'] and r['annotation']['has_insufficient'] for r in rr),
          actual_characters=sorted(chars),declared_but_absent_characters=sorted(set(CHARSET)-chars),
          actual_units=sorted({parse_candidate(r['candidate_raw'])['parts']['unit'] for r in rr if parse_candidate(r['candidate_raw'])['parts']['unit'] is not None}),
          candidate_strings=sorted({r['candidate_raw'] for r in rr}))
    write(output/'coverage.json',result);return result

if __name__=='__main__':
    result=audit(read(OLD_OUT/'data/pairs.json'),read(OLD_OUT/'data/semantic-groups.json'),OUT/'goal15-audit')
    metrics=read(OLD_OUT/'evaluation/metrics.json')
    write(OUT/'goal15-audit/observations.json',dict(utc=utc(),read_only=True,
      training_contradiction_recall={r:metrics['splits']['train']['roles'][r]['contradiction_recall'] for r in ROLES},
      historical_status='Goal15 train/validation/test outputs exposed; no rows moved into Goal16 train',
      findings=['Unit has zero train contradiction, no mm candidate. Numerator-only contrast components absent in train.',
                'Numerator contradiction 23/528, denominator 48/360, relation 9/828, context 0/66 in Goal15 train.',
                'Coverage absence explains missing unit supervision; poor performance on supervised roles is not explained by absence alone.']))
    print(json.dumps({s:{me:len(v['components']) for me,v in x['mechanisms'].items()} for s,x in result.items()}))
