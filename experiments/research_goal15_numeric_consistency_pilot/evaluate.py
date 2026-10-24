"""Frozen metrics. Consumes only the final checkpoint's saved predictions; no fit."""
from collections import Counter,defaultdict
from PIL import Image,ImageDraw,ImageFont
from common import *

METRIC_DEFINITIONS={
 'global':'3x3 true-row/predicted-column counts in CONFIG overall order. All rows included.',
 'false_accept':'true CONTRADICTION predicted CONSISTENT / true CONTRADICTION',
 'false_alarm':'true CONSISTENT predicted CONTRADICTION / true CONSISTENT',
 'correct_abstain':'true CONSISTENT predicted INSUFFICIENT / true CONSISTENT',
 'insufficient_global_determinate':'true overall INSUFFICIENT predicted overall other / true overall INSUFFICIENT',
 'unknown_erased':'true has_insufficient but predicted has_insufficient false / true has_insufficient',
 'joint_retained':'true has_contradiction and has_insufficient; count prediction preserving both flags, and stricter every unknown role retained',
 'roles':'Each role: 4x4 counts; accuracy only truth not NOT_APPLICABLE, predicted NOT_APPLICABLE is wrong there; true NOT_APPLICABLE separately.',
 'complete_cross':'NUMBER_UNIT_CONTEXT and complete condition only, four rows per semantic group/appearance; all four overall right and all four role dictionaries right separately.',
 'independence':'Semantic groups may share merged components; component all-correct count separate; appearance instances are not independent observations.',
 'swaps':'Same image two candidates / same candidate two images within each complete cross group. Count both correct; labels taken from actual new pairs.',
 'single_input_ceilings':'Actual sealed complete cross subset. Sum largest label count in each pixel+scope or candidate_raw+scope bin divided by subset rows. Distribution ceilings, not extra models.',
 'stability':'Complete rows grouped by semantic/source/candidate/scope. Font varies at fixed layout/background; layout varies at fixed font/background; background varies at fixed font/layout. Count same prediction and all correct separately. Gray outside matched to exact complete appearance.',
 'examples':'For each mechanism show first lexically ordered all-four-overall-right and all-four-not-right group if available; no invented successes. Joint unknown examples chosen by actual both-flags retention.',
}

def rate(n,d):return dict(n=int(n),d=int(d),rate=n/d if d else None)
def correct(r):return r['annotation']['overall']==r['prediction']['overall']
def parts_correct(r):return r['annotation']['parts']==r['prediction']['parts']
def filtered_count(rows,predicate,success):
    subset=[r for r in rows if predicate(r)];return rate(sum(success(r) for r in subset),len(subset))

def global_metrics(rows):
    cm=[[0]*3 for _ in range(3)]
    for r in rows:cm[OVERALL.index(r['annotation']['overall'])][OVERALL.index(r['prediction']['overall'])]+=1
    result=dict(pairs=len(rows),confusion_true_rows_predicted_columns=cm,order=OVERALL,
      truth_counts=dict(Counter(r['annotation']['overall'] for r in rows)),accuracy=rate(sum(correct(r) for r in rows),len(rows)),
      full_parts_exact=rate(sum(parts_correct(r) for r in rows),len(rows)))
    for name,true,pred in [('false_accept','CONTRADICTION','CONSISTENT'),('false_alarm','CONSISTENT','CONTRADICTION'),('correct_abstain','CONSISTENT','INSUFFICIENT')]:
        result[name]=filtered_count(rows,lambda r:r['annotation']['overall']==true,lambda r:r['prediction']['overall']==pred)
    result['insufficient_global_determinate']=filtered_count(rows,lambda r:r['annotation']['overall']=='INSUFFICIENT',lambda r:r['prediction']['overall']!='INSUFFICIENT')
    result['unknown_erased']=filtered_count(rows,lambda r:r['annotation']['has_insufficient'],lambda r:not r['prediction']['has_insufficient'])
    joint=lambda r:r['annotation']['has_contradiction'] and r['annotation']['has_insufficient']
    result['joint_both_flags_retained']=filtered_count(rows,joint,lambda r:r['prediction']['has_contradiction'] and r['prediction']['has_insufficient'])
    result['joint_all_unknown_roles_retained']=filtered_count(rows,joint,lambda r:r['prediction']['has_contradiction'] and all(r['prediction']['parts'][k]=='INSUFFICIENT' for k,v in r['annotation']['parts'].items() if v=='INSUFFICIENT'))
    return result

def role_metrics(rows):
    result={}
    for role in ROLES:
        cm=[[0]*4 for _ in range(4)]
        for r in rows:cm[STATES.index(r['annotation']['parts'][role])][STATES.index(r['prediction']['parts'][role])]+=1
        applicable=[r for r in rows if r['annotation']['parts'][role]!='NOT_APPLICABLE'];na=[r for r in rows if r['annotation']['parts'][role]=='NOT_APPLICABLE']
        result[role]=dict(order=list(STATES),confusion_true_rows_predicted_columns=cm,
          applicable_accuracy=rate(sum(r['annotation']['parts'][role]==r['prediction']['parts'][role] for r in applicable),len(applicable)),
          applicable_predicted_not_applicable=rate(sum(r['prediction']['parts'][role]=='NOT_APPLICABLE' for r in applicable),len(applicable)),
          truly_not_applicable_accuracy=rate(sum(r['prediction']['parts'][role]=='NOT_APPLICABLE' for r in na),len(na)),
          unknown_recall=rate(cm[2][2],sum(cm[2])),contradiction_recall=rate(cm[1][1],sum(cm[1])))
    return result

def complete_cross(rows):
    buckets=defaultdict(list)
    for r in rows:
        if r['condition']=='complete' and r['scope']=='NUMBER_UNIT_CONTEXT':buckets[(r['group'],r['appearance'])].append(r)
    records=[]
    for key,b in sorted(buckets.items()):
        assert len(b)==4
        records.append(dict(group=key[0],appearance=key[1],component=b[0]['component'],mechanism=b[0]['mechanism'],
          overall_all_right=all(correct(r) for r in b),parts_all_right=all(parts_correct(r) for r in b),pair_ids=[r['id'] for r in b]))
    by_mechanism={}
    for mechanism in sorted({r['mechanism'] for r in records}):
        bs=[r for r in records if r['mechanism']==mechanism]
        by_mechanism[mechanism]=dict(all_four_overall=rate(sum(r['overall_all_right'] for r in bs),len(bs)),all_four_parts=rate(sum(r['parts_all_right'] for r in bs),len(bs)),
          semantic_groups=len({r['group'] for r in bs}),components=len({r['component'] for r in bs}))
    components=defaultdict(list)
    for r in records:components[r['component']].append(r)
    swaps={}
    for name,axis in [('same_image_candidate_swap','source_index'),('same_candidate_image_swap','candidate_index')]:
        groups=defaultdict(list)
        for b in buckets.values():
            for r in b:groups[(r['group'],r['appearance'],r[axis])].append(r)
        assert all(len(v)==2 for v in groups.values())
        swaps[name]=dict(both_correct=rate(sum(all(correct(r) for r in b) for b in groups.values()),len(groups)),
          prediction_changes=rate(sum(len({r['prediction']['overall'] for r in b})==2 for b in groups.values()),len(groups)))
    return dict(all_four_overall=rate(sum(r['overall_all_right'] for r in records),len(records)),all_four_parts=rate(sum(r['parts_all_right'] for r in records),len(records)),
        all_appearances_component_right=rate(sum(all(r['overall_all_right'] for r in b) for b in components.values()),len(components)),
        by_mechanism=by_mechanism,swaps=swaps,records=records)

def ceilings(rows,images):
    rows=[r for r in rows if r['condition']=='complete' and r['scope']=='NUMBER_UNIT_CONTEXT'];result={}
    for name in ['image','candidate']:
        counts=defaultdict(Counter)
        for r in rows:
            key=(images[r['image']]['pixel_equivalence_id'] if name=='image' else r['candidate_raw'],r['scope'])
            counts[key][r['annotation']['overall']]+=1
        result[name]=dict(majority=rate(sum(max(c.values()) for c in counts.values()),len(rows)),bins=len(counts))
    result['model_subset_accuracy']=rate(sum(correct(r) for r in rows),len(rows));return result

def stability(rows,images):
    full=[r for r in rows if r['condition']=='complete'];result={}
    for factor,held in [('font',['layout','background']),('layout',['font','background']),('background',['font','layout'])]:
        bins=defaultdict(list)
        for r in full:bins[(r['group'],r['source_index'],r['candidate_index'],r['scope'],*(images[r['image']][k] for k in held))].append(r)
        groups=[b for b in bins.values() if len({images[r['image']][factor] for r in b})>1]
        result[factor]=dict(overall_stable=rate(sum(len({r['prediction']['overall'] for r in b})==1 for b in groups),len(groups)),
            all_correct=rate(sum(all(correct(r) for r in b) for b in groups),len(groups)),
            all_parts_stable=rate(sum(all(b[0]['prediction']['parts']==r['prediction']['parts'] for r in b) for b in groups),len(groups)))
    key=lambda r:(r['group'],r['source_index'],r['candidate_index'],r['scope'],r['appearance'])
    lookup={key(r):r for r in full};groups=[(r,lookup[key(r)]) for r in rows if r['condition']=='gray_outside']
    result['gray_outside']=dict(overall_stable=rate(sum(a['prediction']['overall']==b['prediction']['overall'] for a,b in groups),len(groups)),
        both_correct=rate(sum(correct(a) and correct(b) for a,b in groups),len(groups)),
        all_parts_stable=rate(sum(a['prediction']['parts']==b['prediction']['parts'] for a,b in groups),len(groups)))
    return result

def examples(rows,cross):
    by={r['id']:r for r in rows};records=[];folder=OUT/'evaluation/examples';folder.mkdir(parents=True,exist_ok=True)
    for mechanism in sorted({r['mechanism'] for r in cross['records']}):
        for outcome in [True,False]:
            chosen=next((r for r in cross['records'] if r['mechanism']==mechanism and r['overall_all_right']==outcome),None)
            records.append(dict(mechanism=mechanism,outcome='PASS' if outcome else 'FAIL',available=chosen is not None,
                rows=[by[i] for i in chosen['pair_ids']] if chosen else []))
    joint=[r for r in rows if r['annotation']['has_contradiction'] and r['annotation']['has_insufficient']]
    for outcome in [True,False]:
        chosen=next((r for r in joint if (r['prediction']['has_contradiction'] and r['prediction']['has_insufficient'])==outcome),None)
        records.append(dict(mechanism='joint_contradiction_unknown',outcome='PASS' if outcome else 'FAIL',available=chosen is not None,rows=[chosen] if chosen else []))
    font=ImageFont.truetype(str(ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/barlow/Barlow-Regular.ttf'),19)
    for record in records:
        if not record['rows']:continue
        sheet=Image.new('RGB',(1120,50+160*len(record['rows'])),'#eeeeee');draw=ImageDraw.Draw(sheet)
        draw.text((12,10),record['mechanism']+' | '+record['outcome']+' | sealed synthetic test',font=font,fill='black')
        for j,r in enumerate(sorted(record['rows'],key=lambda r:(r['source_index'],r['candidate_index']))):
            y=45+160*j;sheet.paste(Image.open(OUT/'data'/r['image']).convert('RGB'),(5,y))
            draw.text((530,y+4),f"{r['id']}  candidate: {r['candidate_raw']}",font=font,fill='black')
            draw.text((530,y+32),'truth: '+r['annotation']['overall'],font=font,fill='black')
            draw.text((530,y+60),'prediction: '+r['prediction']['overall'],font=font,fill='black')
            draw.text((530,y+90),r['scope']+' | '+r['condition'],font=font,fill='black')
            draw.text((530,y+118),'unknown true/pred: '+str(r['annotation']['has_insufficient'])+'/'+str(r['prediction']['has_insufficient']),font=font,fill='black')
        path=folder/(record['mechanism']+'-'+record['outcome']+'.png');sheet.save(path);record['display']=str(path.relative_to(OUT)).replace('\\','/')
    write(OUT/'evaluation/examples.json',records)

def main():
    assert read(OUT/'run/resource.json')['status']=='COMPLETE'
    all_rows={};result={'definitions':METRIC_DEFINITIONS,'splits':{}}
    images={r['image']:r for r in read(OUT/'data/images.json')}
    for split in ['train','validation','sealed-test']:
        rows=read(OUT/'data'/f'{split}.json');preds={p['id']:p for p in read(OUT/'run'/f'{split}-predictions.json')};assert len(preds)==len(rows)
        for r in rows:r['prediction']=preds[r['id']]['prediction']
        assert all(aggregate(r['prediction']['parts'])=={k:r['prediction'][k] for k in aggregate(r['prediction']['parts'])} for r in rows)
        all_rows[split]=rows
        result['splits'][split]=dict(global_metrics=global_metrics(rows),roles=role_metrics(rows),complete_cross=complete_cross(rows),stability=stability(rows,images),
            by_condition={c:global_metrics([r for r in rows if r['condition']==c]) for c in sorted({r['condition'] for r in rows})})
    result['sealed_test_single_input_ceilings']=ceilings(all_rows['sealed-test'],images)
    write(OUT/'evaluation/metrics.json',result)
    examples(all_rows['sealed-test'],result['splits']['sealed-test']['complete_cross'])
    print(json.dumps({s:result['splits'][s]['global_metrics'] for s in all_rows}))

if __name__=='__main__':main()
