"""Pure comparison: completed independent reading first, raw candidate second."""
import argparse
import re
from common import *
from candidate_contract import parse_candidate

def compare_region(region,reading,candidate_raw):
    # This projection excludes source labels and all source-reading strings.
    result={k:region.get(k) for k in ('id','source_object_id','source_image','source_box','box_origin',
        'role','visibility','applicability','role_binding','role_location_mode','crop_id')}
    result.update(reader=reading['reader'],reader_raw=reading['reader_raw'],candidate_raw=candidate_raw,
        candidate_role_value=None,comparison_result='NOT_EVALUATED',failure_reason=None,
        untested_fields=[r for r in DIGIT_ROLES+OTHER_ROLES if r!=region['role']],
        full_eight_role_verification='NOT_ESTABLISHED',automatic_write_authority=False,
        external_role_binding=True)
    parsed=parse_candidate(candidate_raw)
    result['candidate_parse_supported']=parsed['supported']
    result['candidate_role_value']=parsed['parts'].get(region['role'])
    if region['visibility']!='COMPLETE_VISIBLE' or region['applicability']!='DIGITS_1_TO_3':
        result['failure_reason']='OBJECT_OR_FIELD_NOT_COVERED'
    elif not re.fullmatch('[0-9]{1,3}',reading['reader_raw']):
        result['failure_reason']='DIGIT_READING_FAILURE'
    elif not parsed['supported']:
        result['failure_reason']='CANDIDATE_PARSE_FAILURE'
    elif result['candidate_role_value'] is not None and not re.fullmatch('[0-9]{1,3}',result['candidate_role_value']):
        result['failure_reason']='CANDIDATE_FIELD_OUTSIDE_DIGIT_CONTRACT'
    elif result['candidate_role_value']!=reading['reader_raw']:
        result['comparison_result']='DIGIT_VALUE_MISMATCH'
        result['mismatch_reason']='CANDIDATE_ROLE_ABSENT' if result['candidate_role_value'] is None else 'ROLE_VALUE_DIFFERENT'
    else:
        result['comparison_result']='DIGIT_VALUE_EQUAL'
    return result

def main():
    p=argparse.ArgumentParser(description='Compare an existing immutable digit reading with a new raw candidate. No model call.')
    p.add_argument('--region-id',required=True);p.add_argument('--reader',choices=['ocr','digit'],default='ocr')
    p.add_argument('--candidate',required=True);p.add_argument('--output')
    args=p.parse_args()
    # A technical archive intentionally omits real-local; synthetic comparisons still run.
    rows=[r for group in ('real-local','synthetic')
          if (OUT/group/'regions.json').exists() for r in read(OUT/group/'regions.json')]
    row=next((r for r in rows if r['id']==args.region_id),None)
    if row is None:p.error('region not present in this local data set')
    group='real-local' if row['group']=='real' else 'synthetic'
    readings=read(OUT/group/args.reader/'predictions.json')
    reading=next(r for r in readings if r['crop_id']==row['crop_id'])
    result=compare_region(row,reading,args.candidate)
    if args.output:write(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
