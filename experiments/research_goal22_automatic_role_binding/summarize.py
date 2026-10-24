"""Aggregate saved results and historical controls. No locator, detector or model call."""
from collections import Counter
import re
from common import *

def main():
    stages=['synthetic/SYNTHETIC-v1','real-local/A-v1','synthetic/SYNTHETIC-v2','real-local/A-v2','real-local/B-v2']
    runtimes=[dict(stage=s,**read(OUT/s/'runtime.json')) for s in stages]
    A=read(OUT/'real-local/A-v2/evaluation.json');B=read(OUT/'real-local/B-v2/evaluation.json')
    fields=A['fields']+B['fields'];objects=A['objects']+B['objects'];extra=A['extra_proposals']+B['extra_proposals']
    for name,rows in {
        'protection-reading-losses':[f for f in fields if f['normal_field_status']=='CORRECT' and f['raw_exact'] is False],
        'unsupported-alerts':[f for f in fields if f['review_outcome']=='UNSUPPORTED_OR_WRONG_ALERT'],
        'false-alarms-on-correct':[f for f in fields if f['review_outcome']=='FALSE_ALARM_ON_CORRECT'],
        'abstentions':[f for f in fields if f['review_outcome'].startswith('ABSTAIN')],
        'uncovered-or-incomplete':[f for f in fields if not f['scorable'] or not f['binding_correct']],
        'extra-proposals':extra}.items():write(OUT/'real-local'/(name+'.json'),rows)
    oracle={r['id']:r for r in read(G21/'real-local/ocr/scored-regions.json')};history=[];new=[];loss=[]
    g09=ROOT/'local-artifacts/research-goal09-fraction-reading-20261022'
    oldA=read(g09/'A-v1/results.json');oldB=read(g09/'B-v1-completed/results.json')
    for o in objects:
        oid=o['source_object_id'];idx=int(oid.rsplit(':',1)[1]);old=next((r for r in (oldA if oid.startswith('G37:') else oldB if oid.startswith('MNDOT:') else []) if r['index']==idx),None)
        rr=[f for f in fields if f['source_object_id']==oid]
        item=dict(source_object_id=oid,normal_candidate=rr[0]['normal_candidate'],goal09=None if old is None else
            dict(state=old['state'],hypothesis=old.get('hypothesis'),ordinary_local=old.get('ordinary_local',{}).get('text'),
                 local_raw=[s.get('reading',{}).get('text') for s in old.get('segments',[])],automatic_correction=old['automatic_correction']),
            goal21_oracle=[dict(role=f['role'],reader_raw=oracle[f['reference_id']]['reader_raw']) for f in rr],
            goal22=[dict(role=f['role'],reader_raw=f['reader_raw'],valid_exact_evidence=f['valid_exact_evidence']) for f in rr],
            full_expression_verified=False)
        history.append(item)
        for f in rr:
            if not f['scorable']:continue
            was=oracle[f['reference_id']]['reader_raw']==f['label']
            if f['raw_exact'] and not was:new.append(f)
            if was and not f['raw_exact']:loss.append(f)
    write(OUT/'real-local/historical-controls.json',history);write(OUT/'real-local/new-reading-vs-oracle.json',new);write(OUT/'real-local/lost-reading-vs-oracle.json',loss)
    examples=read(OUT/'synthetic/examples.json');sr=read(OUT/'synthetic/SYNTHETIC-v2/regions.json')['objects'];sp=read(OUT/'synthetic/SYNTHETIC-v2/readings.json');diagnostics=[]
    for ex,obj in zip(examples,sr):
        relation=obj['geometry']['relations'];pr=[r for r in sp if r['source_object_id']==ex['source_object_id']]
        diagnostics.append(dict(kind=ex['kind'],region_count=len(pr),raw_strings=[r.get('reader_raw') for r in pr],
            region_states=[r['state'] for r in pr],relations=[{'type':r['type'],'state':r['state'],'roles':r['roles']} for r in relation],
            real_engineering_score=False,
            interpretation='correct standalone target; engineering-line proposal read non-digit and remains extra' if ex['kind']=='engineering-line' else
                'branched diagonal withheld; fixture does not actually join the numeral glyph, so true glyph-to-slash joining not certified' if ex['kind']=='joined-separator' else
                'truncated denominator not read; relation uncertain; numerator raw is partial evidence only' if ex['kind']=='incomplete' else
                'target role/raw outputs and independent-group separation inspected; synthetic only'))
    write(OUT/'synthetic/diagnostics.json',diagnostics)
    notes=read(OUT/'real-local/assessment-notes.json')
    numeric=dict(source_objects=len(objects),parent_provenance=dict(Counter(o['parent_provenance'] for o in objects)),
        proposed_regions=sum(len(o['geometry']['regions']) for stage in ['real-local/A-v2','real-local/B-v2'] for o in read(OUT/stage/'regions.json')['objects']),required_regions=len(fields),scorable_regions=sum(f['scorable'] for f in fields),unscored_regions=sum(not f['scorable'] for f in fields),
        complete_locations=sum(f['localization_complete'] and f['scorable'] for f in fields),complete_binding_evidence=sum(f['binding_correct'] for f in fields),
        raw_exact=sum(f['raw_exact'] is True for f in fields),valid_exact_evidence=sum(f['valid_exact_evidence'] for f in fields),
        complete_required_numeric_objects=sum(o['all_required_digits_and_relation'] for o in objects),
        normal_parent_objects_with_some_valid_evidence=sum(o['valid_exact_regions']>0 for o in objects),
        review_outcomes=dict(Counter(f['review_outcome'] for f in fields)),
        true_issue_objects=len({f['source_object_id'] for f in fields if f['review_outcome']=='TRUE_ISSUE'}),
        unsupported_alert_objects=len({f['source_object_id'] for f in fields if f['review_outcome']=='UNSUPPORTED_OR_WRONG_ALERT'}),
        extra_non_numeric_region_proposals=len(extra),extra_false_numeric_bindings=sum(e['false_numeric_binding'] for e in extra),
        review_objects=sum(o['review_required'] for o in objects),target_review_regions=sum(f['needs_review'] for f in fields),extra_review_regions=len(extra),
        unresolved_required_relations=sum(o['unresolved_required_relations'] for o in objects),new_reading_vs_goal21_oracle=len(new),lost_reading_vs_goal21_oracle=len(loss),
        known_correct_numeric_objects_requiring_review=sum(o['review_required'] and o['source_object_id'] in notes['known_normal_numeric_correct_objects'] for o in objects),known_correct_note='Offline source/history assessment: includes one object with an existing unverified unit problem. No numerical contradiction false alarm; still queued by read/parser failures.',
        full_expression_verified_objects=0)
    resources=dict(stages=runtimes,locator_compute_seconds=sum(r['locator_seconds'] for r in runtimes),
        ocr_forward_seconds=sum(r['ocr_forward_seconds'] for r in runtimes),ocr_initialization_seconds=sum(r['ocr_init_seconds'] for r in runtimes),
        measured_operation_seconds=sum(r['operation_seconds'] for r in runtimes),new_rec_calls=sum(r['ocr_new_calls'] for r in runtimes),cache_reuses=sum(r['ocr_cache_hits'] for r in runtimes),
        evaluation_scoring_seconds=sum(read(OUT/s/'evaluation.json')['summary']['seconds'] for s in ['real-local/A-v1','real-local/A-v2','real-local/B-v2']),
        resource_wait_seconds=0,source_pages_copied=0,new_detector_calls=0,training_updates=0,manual_parent_windows_runtime=0,
        human_role_boxes_runtime=0,AI_evaluation_role_boxes_reused=18,AI_parent_inventory_reviews=10,
        continuous_human_time=None,continuous_agent_time=None,unmeasured_other_CPU_time=None,downloads_bytes=0,deleted_files=0,released_bytes=0)
    write(OUT/'summary.json',dict(utc=utc(),A=A['summary'],B=B['summary'],final=numeric,resources=resources,
        decision='LIMITED_NORMAL_PARENT_LOCALIZATION_AND_BINDING_EVIDENCE_NO_GO_STOP_AFTER_GOAL22',
        REAL_ASSESSMENT='AI_QA_PROVISIONAL',INDEPENDENT_C='NOT_RUN',FORMAL_CAD_IMPROVEMENT=0,HUMAN_NET_LABOR='NOT_MEASURED',PRODUCTION_PROMOTION='NO_GO'))
    print(json.dumps({'final':numeric,'resources':{k:v for k,v in resources.items() if k!='stages'}},ensure_ascii=False))
if __name__=='__main__':main()
