"""Unmodified Goal21 compare_region; labels are not inputs."""
import re
from candidate_contract import parse_candidate
DIGIT_ROLES=("whole","numerator","denominator")
OTHER_ROLES=("relation","decimal_point","sign","unit","context")

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
