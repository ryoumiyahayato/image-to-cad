"""Fixed Goal15 scorer plus Goal17 coarse-distribution and object-level summaries."""
from collections import Counter,defaultdict
from PIL import Image,ImageDraw,ImageFont
from common import *
metrics=load_module('goal15_fixed_metrics',G15/'evaluate.py')
rate=metrics.rate

def stats(rows):
    out=dict(global_metrics=metrics.global_metrics(rows),roles=metrics.role_metrics(rows))
    unknown=[(r,k) for r in rows for k,v in r['annotation']['parts'].items() if v=='INSUFFICIENT']
    out['unknown_roles_made_determinate']=rate(sum(r['prediction']['parts'][k]!='INSUFFICIENT' for r,k in unknown),len(unknown))
    joint=[r for r in rows if r['annotation']['has_contradiction'] and r['annotation']['has_insufficient']]
    out['joint_all_contradiction_and_unknown_roles_retained']=rate(sum(all(r['prediction']['parts'][k]==v for k,v in r['annotation']['parts'].items() if v in ['CONTRADICTION','INSUFFICIENT']) for r in joint),len(joint))
    out['abstain_all']=rate(sum(r['prediction']['overall']=='INSUFFICIENT' for r in rows),len(rows))
    out['contradiction_abstain']=rate(sum(r['prediction']['overall']=='INSUFFICIENT' for r in rows if r['annotation']['overall']=='CONTRADICTION'),sum(r['annotation']['overall']=='CONTRADICTION' for r in rows))
    return out

def ceilings(rows,imap):
    out={}
    for kind in ['image','candidate','coarse']:
        bins=defaultdict(Counter)
        for r in rows:
            key=(imap[r['image']]['pixel_equivalence_id'],r['scope']) if kind=='image' else (r['candidate_raw'],r['scope']) if kind=='candidate' else json.dumps(r['coarse'],sort_keys=True)
            bins[key][r['annotation']['overall']]+=1
        out[kind]=dict(majority=rate(sum(max(c.values()) for c in bins.values()),len(rows)),bins=len(bins))
    out['model_accuracy']=rate(sum(metrics.correct(r) for r in rows),len(rows));return out

def stability(rows):
    buckets=defaultdict(list)
    for r in rows:buckets[(r['component'],r['source_index'],r['candidate_index'],r['scope'])].append(r)
    eligible=[b for b in buckets.values() if len({r['appearance'] for r in b})>1]
    return dict(cell_groups=len(eligible),overall_stable=rate(sum(len({r['prediction']['overall'] for r in b})==1 for b in eligible),len(eligible)),
        overall_stable_and_correct=rate(sum(all(metrics.correct(r) for r in b) for b in eligible),len(eligible)),
        all_roles_stable=rate(sum(all(r['prediction']['parts']==b[0]['prediction']['parts'] for r in b) for b in eligible),len(eligible)),
        all_roles_stable_and_correct=rate(sum(all(metrics.parts_correct(r) for r in b) for b in eligible),len(eligible)))

def examples(rows,cross):
    folder=OUT/'synthetic/examples';folder.mkdir(exist_ok=True);by={r['id']:r for r in rows};selected=[]
    font=ImageFont.truetype(str(ROOT/'local-artifacts/product-p21c-fraction-learning-20261020/fonts/barlow/Barlow-Regular.ttf'),17)
    for cat in sorted({r['mechanism'] for r in cross['records']}):
        for passing in [True,False]:
            choice=next((r for r in cross['records'] if r['mechanism']==cat and r['parts_all_right']==passing),None)
            rec=dict(category=cat,all_roles_pass=passing,available=choice is not None)
            if choice:
                items=[by[x] for x in choice['pair_ids']];rec['pair_ids']=choice['pair_ids'];sheet=Image.new('RGB',(1130,4*170),'#eee');draw=ImageDraw.Draw(sheet)
                for j,r in enumerate(sorted(items,key=lambda r:(r['source_index'],r['candidate_index']))):
                    y=j*170;sheet.paste(Image.open(OUT/r['image']).convert('RGB'),(0,y+20))
                    draw.text((520,y+12),r['id']+' candidate '+r['candidate_raw'],fill='black',font=font)
                    draw.text((520,y+42),'truth '+r['annotation']['overall']+' | prediction '+r['prediction']['overall'],fill='black',font=font)
                    draw.text((520,y+72),'truth '+','.join(v[:1] if v!='NOT_APPLICABLE' else '-' for v in r['annotation']['parts'].values()),fill='black',font=font)
                    draw.text((520,y+102),'pred  '+','.join(v[:1] if v!='NOT_APPLICABLE' else '-' for v in r['prediction']['parts'].values()),fill='black',font=font)
                path=folder/(cat+('-PASS' if passing else '-FAIL')+'.png');sheet.save(path);rec['image']=str(path.relative_to(OUT))
            selected.append(rec)
    write(folder/'selection.json',selected)

def main():
    syn=read(OUT/'synthetic/pairs.json');pred={r['id']:r for r in read(OUT/'synthetic/predictions.json')};assert len(syn)==len(pred)
    for r in syn:r['prediction']=pred[r['id']]['prediction']
    imap={r['image']:r for r in read(OUT/'synthetic/images.json')};core=[r for r in syn if r['section']=='core']
    result=dict(all=stats(syn),sections={},categories={},variants={},ceilings={})
    for section in sorted({r['section'] for r in syn}):
        ss=[r for r in syn if r['section']==section];result['sections'][section]=stats(ss)
        if section in ['core','length_control','protection']:
            result['sections'][section]['four_grid']=metrics.complete_cross(ss);result['sections'][section]['appearance_stability']=stability(ss)
    for cat in sorted({r['category'] for r in syn}):
        ss=[r for r in syn if r['category']==cat and r['section'] in ['core','seen_anchor','protection']]
        result['categories'][cat]=stats(ss)
    for variant in sorted({r['variant'] for r in core}):result['variants'][variant]=stats([r for r in core if r['variant']==variant])
    full=[r for r in core if r['scope']=='NUMBER_UNIT_CONTEXT']
    for name,ss in [('all_core',full),('equal_length_identity',[r for r in full if r['category'] in ['A_numerator','B_denominator']]),('role_swap',[r for r in full if r['category']=='C_role_swap']),('structure',[r for r in full if r['category']=='D_boundary'])]:result['ceilings'][name]=ceilings(ss,imap)
    # Matched length controls are compared within the same base component and appearance; shared A/A rows are disclosed.
    comparison=[]
    for component in sorted({r['component'] for r in syn if r['section']=='length_control'}):
        for section in ['core','length_control']:
            ss=[r for r in syn if r['component']==component and r['section']==section]
            comparison.append(dict(component=component,section=section,metrics=stats(ss)))
    result['matched_length_controls']=comparison
    write(OUT/'synthetic/metrics.json',result);write(OUT/'synthetic/joined.json',syn)
    examples(syn,result['sections']['core']['four_grid'])
    real=read(OUT/'real-local/pairs.json');pred={r['id']:r for r in read(OUT/'real-local/predictions.json')}
    for r in real:r['prediction']=pred[r['id']]['prediction'] if r['run_forward'] else None
    write(OUT/'real-local/joined.json',real)
    eligible=[r for r in real if r['contract_scorable']];pending=[r for r in real if r['run_forward'] and not r['contract_scorable']]
    objects=[]
    for group in sorted({r['group'] for r in real}):
        rr=[r for r in real if r['group']==group];same=defaultdict(list)
        for r in rr:
            if r['prediction']:same[(r['candidate_raw'],r['scope'])].append(r)
        matched=[]
        for key,rs in same.items():
            if len({r['mapping_id'] for r in rs})>1:matched.append(dict(candidate_raw=key[0],scope=key[1],mapping_ids=[r['mapping_id'] for r in rs],overall_equal=len({r['prediction']['overall'] for r in rs})==1,roles_equal=all(r['prediction']['parts']==rs[0]['prediction']['parts'] for r in rs)))
        signal=[]
        for mid in sorted({r['mapping_id'] for r in rr}):
            subset=[r for r in rr if r['mapping_id']==mid and r['contract_scorable']]
            wrong=[r for r in subset if r['candidate_kind']=='historical_OCR' and r['annotation']['overall']=='CONTRADICTION']
            correct=[r for r in subset if r['candidate_kind']=='preprovided_source_reading' and r['annotation']['overall']=='CONSISTENT']
            if wrong and correct:signal.append(dict(mapping_id=mid,wrong_rejected=wrong[0]['prediction']['overall']=='CONTRADICTION',correct_accepted=correct[0]['prediction']['overall']=='CONSISTENT',both=wrong[0]['prediction']['overall']=='CONTRADICTION' and correct[0]['prediction']['overall']=='CONSISTENT',both_all_roles=metrics.parts_correct(wrong[0]) and metrics.parts_correct(correct[0])))
        objects.append(dict(source_object=group,rows=rr,matched_same_candidate_input_consistency=matched,paired_signal=signal))
    write(OUT/'real-local/objects.json',objects)
    historical_correct=[r for r in eligible if r['candidate_kind']=='historical_OCR' and r['annotation']['overall']=='CONSISTENT']
    all_signals=[s for o in objects for s in o['paired_signal']]
    real_summary=dict(assessment='AI_QA_PROVISIONAL',forwards=len(pred),scorable_pairs=len(eligible),pending_pairs=len(pending),outside_contract=sum(not r['run_forward'] for r in real),
        scorable=stats(eligible),pending=stats(pending),historical_correct_protection=stats(historical_correct),
        paired_signal=rate(sum(s['both'] for s in all_signals),len(all_signals)),paired_signal_all_roles=rate(sum(s['both_all_roles'] for s in all_signals),len(all_signals)),
        objects_with_any_paired_signal=sum(any(s['both'] for s in o['paired_signal']) for o in objects),objects_with_eligible_pair=sum(bool(o['paired_signal']) for o in objects),total_source_objects=len(objects))
    write(OUT/'real-local/metrics.json',real_summary)
    # This aggregate file has no real item IDs, source strings, row labels or row predictions and may be archived.
    write(OUT/'real-aggregate.json',real_summary)
    print(json.dumps(dict(synthetic={s:v['global_metrics'] for s,v in result['sections'].items()},ceilings=result['ceilings'],real=real_summary)))

if __name__=='__main__':main()
