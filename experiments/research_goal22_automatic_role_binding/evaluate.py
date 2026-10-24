"""Offline reference evaluation. Only this stage reads manual roles and correct values."""
import argparse,re,time
from collections import Counter
import numpy as np
from PIL import Image
from common import *
from candidate_contract import parse_candidate
from compare_saved import compare_proposal

def ink_points(page,box):
    x0,y0,x1,y1=box;yy,xx=np.where(page[y0:y1,x0:x1]<180)
    return xx+x0,yy+y0
def inside(points,box):
    x,y=points;x0,y0,x1,y1=box;return int(((x>=x0)&(x<x1)&(y>=y0)&(y<y1)).sum())
def center(box):return ((box[0]+box[2])/2,(box[1]+box[3])/2)

def main():
    arg=argparse.ArgumentParser();arg.add_argument('--split',choices=['A','B'],required=True);arg.add_argument('--version',required=True);args=arg.parse_args();started=time.perf_counter()
    folder=OUT/'real-local'/(args.split+'-'+args.version)
    objects=read(folder/'regions.json')['objects'];readings=read(folder/'readings.json')
    refs={r['source_object_id']:r for r in read(OUT/'real-local/evaluation-reference.json')}
    normal={r['source_object_id']:r['candidate_raw'] for r in read(OUT/'real-local/normal-reference.json')}
    fields=[];out_objects=[];comparisons=[];extras=[]
    for obj in objects:
        oid=obj['source_object_id'];ref=refs[oid];targets=ref['required_roles'];proposals=obj['geometry']['regions'];relations=obj['geometry']['relations']
        page=np.array(Image.open(abs_path(obj['parent']['source_image'])).convert('L'));points={t['id']:ink_points(page,t['source_box']) for t in targets}
        rows=[];matched=set();byrole={};candidate=parse_candidate(normal[oid])
        for t in targets:
            pts=points[t['id']];total=len(pts[0]);options=[]
            for p in proposals:
                covered=inside(pts,p['source_box'])
                if covered:
                    other=sum(inside(points[x['id']],p['source_box']) for x in targets if x['id']!=t['id'] and x['label'] is not None)
                    b=p['source_box'];options.append((covered,-other,p['role']==t['role'],-(b[2]-b[0])*(b[3]-b[1]),p))
            chosen=max(options,key=lambda x:x[:4]) if options else None;p=chosen[-1] if chosen else None
            reading=next((r for r in readings if r['source_object_id']==oid and p and r['region_id']==p['id']),{})
            if p:matched.add(p['id'])
            scorable=t['label'] is not None;covered=chosen[0] if chosen else 0;foreign=-chosen[1] if chosen else 0
            row=dict(source_object_id=oid,role=t['role'],reference_id=t['id'],reference_box=t['source_box'],label=t['label'],visibility=t['visibility'],
                proposal_id=p['id'] if p else None,proposal_box=p['source_box'] if p else None,proposed_role=p['role'] if p else None,
                reference_ink_pixels=total,preserved_reference_ink=covered,missed_reference_ink=total-covered,foreign_role_ink=foreign,
                localization_complete=bool(p and covered==total and total>0 and foreign==0),role_name_correct=bool(p and p['role']==t['role']),
                region_state=p['state'] if p else 'MISSING',reader_raw=reading.get('reader_raw'),raw_exact=reading.get('reader_raw')==t['label'] if scorable else None,
                scorable=scorable,normal_candidate=normal[oid],normal_role_value=candidate['parts'].get(t['role']),
                normal_field_status=('CORRECT' if candidate['parts'].get(t['role'])==t['label'] else 'INCORRECT') if candidate['supported'] and scorable else 'UNDETERMINED')
            row['geometry_usable']=bool(row['localization_complete'] and row['role_name_correct'] and row['region_state']=='USABLE' and scorable)
            rows.append(row);byrole[t['role']]=row
        fraction_relation=None
        if 'numerator' in byrole and 'denominator' in byrole:
            n,d=byrole['numerator'],byrole['denominator'];nc,dc=center(n['reference_box']),center(d['reference_box'])
            for reln in relations:
                if reln['roles'].get('numerator')!=n['proposal_id'] or reln['roles'].get('denominator')!=d['proposal_id']:continue
                if not reln.get('separator_source_box'):continue
                sc=center(reln['separator_source_box'])
                if (n['geometry_usable'] and d['geometry_usable'] and reln['state']=='USABLE'
                    and nc[0]<sc[0]<dc[0] and nc[1]<sc[1]<dc[1]):fraction_relation=reln
        for row in rows:
            p=next((x for x in proposals if x['id']==row['proposal_id']),None)
            if row['role'] in ('numerator','denominator'):binding=bool(fraction_relation)
            elif len(targets)==1:binding=bool(p and any(r['type']=='PROPOSED_STANDALONE' and r['roles'].get('whole')==p['id'] for r in relations))
            else:binding=bool(fraction_relation and fraction_relation['type']=='PROPOSED_MIXED' and fraction_relation['roles'].get('whole')==row['proposal_id'])
            row['binding_correct']=bool(row['geometry_usable'] and binding)
            row['valid_exact_evidence']=bool(row['binding_correct'] and row['raw_exact'])
            if p:
                reading=next(r for r in readings if r['source_object_id']==oid and r['region_id']==p['id'])
                c=compare_proposal(obj,p,reading,normal[oid]);comparisons.append(c)
                row['comparison_result']=c['comparison_result'];row['failure_reason']=c['failure_reason']
            else:row.update(comparison_result='NOT_EVALUATED',failure_reason='MISSING_ROLE')
            if row['comparison_result']=='DIGIT_VALUE_MISMATCH':
                row['review_outcome']='TRUE_ISSUE' if row['valid_exact_evidence'] and row['normal_field_status']=='INCORRECT' else 'FALSE_ALARM_ON_CORRECT' if row['normal_field_status']=='CORRECT' else 'UNSUPPORTED_OR_WRONG_ALERT'
            elif row['comparison_result']=='DIGIT_VALUE_EQUAL':
                row['review_outcome']='VALID_DIGIT_EQUAL' if row['valid_exact_evidence'] else 'UNSUPPORTED_EQUALITY'
            else:row['review_outcome']='ABSTAIN_'+str(row['failure_reason'])
            row['needs_review']=row['review_outcome']!='VALID_DIGIT_EQUAL' or not row['valid_exact_evidence']
        objextras=[]
        for p in proposals:
            if p['id'] in matched:continue
            reading=next(r for r in readings if r['source_object_id']==oid and r['region_id']==p['id']);raw=reading.get('reader_raw')
            c=compare_proposal(obj,p,reading,normal[oid]);comparisons.append(c)
            e=dict(source_object_id=oid,region_id=p['id'],source_box=p['source_box'],role=p['role'],state=p['state'],reader_raw=raw,
                category='EXTRANEOUS_PROPOSAL',false_numeric_binding=bool(p['state']=='USABLE' and raw is not None and re.fullmatch('[0-9]{1,3}',raw)),
                comparison_result=c['comparison_result'],failure_reason=c['failure_reason'],needs_review=True)
            objextras.append(e);extras.append(e)
        expected_fraction='numerator' in byrole
        fullrelation=bool(fraction_relation) if expected_fraction else all(r['binding_correct'] for r in rows)
        if expected_fraction and 'whole' in byrole:fullrelation=bool(fullrelation and byrole['whole']['binding_correct'])
        incomplete=sum(not r['binding_correct'] for r in rows)
        objrow=dict(source_object_id=oid,design=obj['parent']['design'],parent_provenance=obj['parent']['parent_provenance'],parent_box=obj['parent']['parent_box'],
            required_regions=len(rows),scorable_regions=sum(r['scorable'] for r in rows),complete_locations=sum(r['localization_complete'] and r['scorable'] for r in rows),
            correct_bindings=sum(r['binding_correct'] for r in rows),valid_exact_regions=sum(r['valid_exact_evidence'] for r in rows),
            relation_correct=fullrelation,all_required_digits_and_relation=bool(fullrelation and all(r['valid_exact_evidence'] for r in rows)),
            all_window_numeric_evidence=bool(fullrelation and all(r['valid_exact_evidence'] for r in rows) and not any(e['false_numeric_binding'] for e in objextras)),
            target_review_regions=sum(r['needs_review'] for r in rows),extra_proposals=len(objextras),extra_false_numeric_bindings=sum(e['false_numeric_binding'] for e in objextras),
            unresolved_required_relations=int(not fullrelation),extra_ambiguous_relations=sum(r['state']!='USABLE' for r in relations if r is not fraction_relation),
            review_required=bool(any(r['needs_review'] for r in rows) or objextras),full_expression_verified=False,unit_context_status='NOT_EVALUATED')
        out_objects.append(objrow);fields.extend(rows)
    summary=dict(split=args.split,version=args.version,source_objects=len(objects),required_regions=len(fields),scorable_regions=sum(r['scorable'] for r in fields),
        unscored_regions=sum(not r['scorable'] for r in fields),complete_locations=sum(r['localization_complete'] and r['scorable'] for r in fields),
        correct_bindings=sum(r['binding_correct'] for r in fields),raw_exact_on_matched_regions=sum(r['raw_exact'] is True for r in fields),
        valid_exact_regions=sum(r['valid_exact_evidence'] for r in fields),complete_required_objects=sum(r['all_required_digits_and_relation'] for r in out_objects),
        normal_parent_objects_with_valid_evidence=sum(r['valid_exact_regions']>0 and r['parent_provenance']=='NORMAL_DETECTOR_PARENT' for r in out_objects),
        extra_region_proposals=len(extras),false_numeric_bindings=sum(e['false_numeric_binding'] for e in extras),
        review_outcomes=dict(Counter(r['review_outcome'] for r in fields)),target_review_regions=sum(r['needs_review'] for r in fields),
        extra_review_regions=len(extras),objects_needing_review=sum(o['review_required'] for o in out_objects),
        unresolved_required_relations=sum(o['unresolved_required_relations'] for o in out_objects),runtime_human_role_boxes=0,
        full_expression_verification='NUMERIC_SUBTASK_ONLY_UNITS_CONTEXT_NOT_EVALUATED',assessment='AI_QA_PROVISIONAL',seconds=time.perf_counter()-started)
    write(folder/'evaluation.json',dict(summary=summary,objects=out_objects,fields=fields,extra_proposals=extras,comparisons=comparisons))
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
