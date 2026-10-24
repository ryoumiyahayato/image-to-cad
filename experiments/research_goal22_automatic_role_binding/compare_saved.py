"""Compare only already-frozen source geometry and raw OCR observations."""
import argparse
from common import *
from comparison_contract import compare_region

def compare_proposal(obj,region,reading,candidate):
    relation=next(x for x in obj['geometry']['relations'] if x['id']==region['group_id'])
    usable=region['state']=='USABLE' and relation['state']=='USABLE' and reading.get('reader_raw') is not None
    adapter=dict(id=region['id'],source_object_id=obj['source_object_id'],source_image=obj['parent']['source_image'],
        source_box=region['source_box'],box_origin=region['box_origin'],role=region['role'],
        visibility='COMPLETE_VISIBLE' if usable else 'UNCERTAIN',applicability='DIGITS_1_TO_3',
        role_binding='AUTOMATIC_GEOMETRIC_PROPOSAL',role_location_mode='NORMAL_PARENT_AUTOMATIC_PROPOSAL',crop_id=reading.get('crop'))
    result=compare_region(adapter,dict(reader='PP-OCRv6',reader_raw=reading.get('reader_raw') or ''),candidate)
    result.update(visibility='AUTOMATIC_COMPLETE_PROPOSAL_UNVERIFIED' if usable else 'UNCERTAIN',
        comparison_assumption='usable geometry proposal, not certified source truth',parent_provenance=obj['parent']['parent_provenance'],
        relation_proposal=relation['type'],region_state=region['state'],relation_state=relation['state'],
        automatic_write_authority=False,full_expression_verification='NOT_ESTABLISHED')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--object',required=True);p.add_argument('--region',required=True);p.add_argument('--candidate',required=True);p.add_argument('--output');a=p.parse_args()
    folder=OUT/a.stage;obj=next(o for o in read(folder/'regions.json')['objects'] if o['source_object_id']==a.object)
    region=next(r for r in obj['geometry']['regions'] if r['id']==a.region)
    reading=next(r for r in read(folder/'readings.json') if r['source_object_id']==a.object and r['region_id']==a.region)
    result=compare_proposal(obj,region,reading,a.candidate)
    if a.output:write(a.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
