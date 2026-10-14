"""One bounded fixed-target/native-redetection comparison; never labels/trains."""

import copy
import ctypes
import html
import itertools
import json
import math
import shutil
import zipfile
import argparse
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image,ImageDraw,ImageFont

from common import ROOT,read,read_rows,atomic_json,write_rows
from feedback_diagnostic import render_window
from local_detection import inspect_window,map_line
from measurement import SourceWindow,measure_row
from prepare_v2 import build_pool
from queue_dedup import deduplicate
from target_view import target_overlay
from trial_sampling import to_display,pixel_center_to_pdf

PREVIEW=ROOT/'local-artifacts/product-fix-p3b/preview-trial-20261010-001'
PREVIOUS=ROOT/'local-artifacts/product-fix-p3b/feedback-fix-20261010-001'
OUT=ROOT/'local-artifacts/product-fix-p3b/local-scale-20261011-001'
POSITIONS=('preview-006','preview-010','preview-015','preview-001','preview-007')


def measure_fixed(original,gray,frame,origin,*,normalized):
    row={k:copy.deepcopy(original[k]) for k in ('sample_id','source_page','source_path','source_drawing_id','candidate_geometry','target_roi')}
    row['candidate_geometry']=[[g[0],map_line(g[1],original['coordinate_frame'],frame),g[2]] for g in original['candidate_geometry']]
    row.update(source_bbox=[*origin,gray.shape[1],gray.shape[0]],source_dpi=frame['effective_dpi'],coordinate_frame=frame,
               original_sample_id=original['sample_id'],label=None,training_authorized=False,human_answer_inherited=False,
               purpose='fixed_original_target_source_scale_comparison',diagnostic_profile_trace=True)
    if normalized:row['measurement_reference_frame']=original['coordinate_frame']
    source=SourceWindow(gray,origin,frame['render_size_px'])
    measure_row(row,source)
    row['quality']=inspect_window(row,gray,np.asarray(origin),original['coordinate_frame'])
    return row


def source_region_types(originals):
    """Target neighborhoods, not whole-page PATH count as vector proof."""
    by_file=defaultdict(list);result={}
    for row in originals:
        points=np.asarray([pixel_center_to_pdf(g[1][k:k+2],row['coordinate_frame']) for g in row['candidate_geometry'] for k in (0,2)])
        box=[*(points.min(0)-5),*(points.max(0)+5)]
        by_file[(row['source_path'],row['source_page'])].append((row['sample_id'],box))
    for (path,number),targets in by_file.items():
        with pdfium.PdfDocument(path) as doc:
            page=doc[number-1]
            try:
                counts={sid:Counter() for sid,_ in targets};nested={sid:0 for sid,_ in targets};levels=Counter()
                for obj in page.get_objects():
                    levels[obj.level]+=1
                    bounds=obj.get_bounds()
                    for sid,box in targets:
                        if bounds[0]<=box[2] and bounds[2]>=box[0] and bounds[1]<=box[3] and bounds[3]>=box[1]:
                            if obj.level: nested[sid]+=1
                            else:counts[sid][str(obj.type)]+=1
                for sid,box in targets:
                    result[sid]={'PDF_neighborhood_xyxy':list(map(float,box)),
                        'top_level_objects_intersecting_target_neighborhood':dict(counts[sid]),
                        'nested_object_bounds_not_registered':nested[sid],
                        'interpretation':'local vector paths, no image overlap' if not nested[sid] and counts[sid]['2'] and not counts[sid]['3'] else 'mixed or unresolved local content',
                        'original_scan_resolution_dpi':None,
                        'limit':'bounds establish regional source information, not identity of a particular LSD edge; nested forms would require explicit parent transforms'}
            finally:page.close()
    return result


def association(original,fixed,proposals,reference):
    """After detection only: geometric/source evidence, never human categories."""
    base=[np.asarray(g[1]).reshape(2,2) for g in original['candidate_geometry']]
    candidates=[]
    for row in proposals:
        if len(row['candidate_geometry'])!=len(base):continue
        mapped=[np.asarray(map_line(g[1],row['coordinate_frame'],reference)).reshape(2,2) for g in row['candidate_geometry']]
        for permutation in itertools.permutations(range(len(base))):
            distances=[];overlaps=[];angles=[]
            for old,j in zip(base,permutation):
                tangent=(old[1]-old[0])/np.linalg.norm(old[1]-old[0]);normal=np.array([-tangent[1],tangent[0]])
                new=mapped[j];direction=(new[1]-new[0])/np.linalg.norm(new[1]-new[0])
                angles.append(math.degrees(math.acos(float(np.clip(abs(tangent@direction),0,1)))))
                distances.append(float(np.max(np.abs((new-old[0])@normal))))
                projection=sorted((new-old[0])@tangent);length=np.linalg.norm(old[1]-old[0])
                overlaps.append(max(0,min(length,projection[1])-max(0,projection[0]))/length)
            if max(angles)<=3 and min(overlaps)>=.65:
                candidates.append((max(distances),row,permutation,overlaps))
    if not candidates:return None,{'status':'no_eligible_direction_and_extent_related_nomination','same_object':False}
    distance,row,order,overlap=min(candidates,key=lambda r:(r[0],r[1]['sample_id']))
    metrics=fixed['quality']['metrics']
    original_supported=all(metrics.get('AB'[i]+'_SOURCE_SUPPORT_RATIO',0)>=.9
        and metrics.get('AB'[i]+'_EDGE_ATTACHMENT',{}).get('directional_edge_ratio',0)>=.75
        for i in range(len(base)))
    same_edge_evidence=distance<=2 and original_supported
    return copy.deepcopy(row),{'status':'same_visible_edge_geometric_evidence' if same_edge_evidence else 'nearby_parallel_nomination_not_original_object_recovery',
        'same_object':'supported visible-edge association, entity/semantic identity unconfirmed' if same_edge_evidence else False,
        'max_normal_offset_reference_px':distance,'projected_overlap_fractions':overlap,'member_mapping':list(order),
        'basis':'parallel direction, shared extent, <=2 reference-pixel normal offset, original support >=0.9 and edge direction >=0.75; not binary quality eligibility, ID/category/file name',
        'limit':'does not authorize moving original geometry, inheriting labels, merging or deleting neighbors'}


def run():
    if OUT.exists():raise ValueError('Never overwrite an earlier scale diagnostic or rerun silently')
    original_by_id={r['sample_id']:r for r in read_rows(PREVIEW/'manifest.jsonl')}
    prior=read(PREVIOUS/'diagnostic-targets.json')
    native_by_id={r['original_sample_id']:r for r in prior}
    OUT.mkdir();images=OUT/'images';images.mkdir()
    record={'purpose':'development_local_scale_replay','training_authorized':False,'labels_assigned':0,
            'old_artifacts_rewritten':False,'positions':[],'entry_before_this_run':{
                'full_page_detection':{'TRIAL-02':{'size_px':[2573,1820],'dpi':110},'TRIAL-04':{'size_px':[4096,2898],'dpi':87.51097922848665},'TRIAL-05':{'size_px':[4096,2347],'dpi':94.58370750481077}},
                '320_DPI_role':'source display and remapped old targets/profile; no local LSD redetection existed',
                'profile':'legacy stroke_profile on actual low or native320 source with that version of final target; fixed pixel constants changed physical extent'}}
    plan=copy.deepcopy(read(PREVIOUS/'replay-plan.json'));plan['purpose']='development_local_scale_replay';plan['local_diagnostic_windows']=[];plan['pair_budget_per_cell']=250
    # Reference frame is the recorded full-page raster, per page. It is
    # intentionally not a new universal paper-distance/engineering-mm policy.
    for sid in POSITIONS:
        original=original_by_id[sid];case=OUT/sid;case.mkdir()
        if sid in native_by_id:
            saved=native_by_id[sid];gray=np.array(Image.open(PREVIOUS/saved['preview_files']['crop']).convert('L'))
            frame=saved['coordinate_frame'];origin=saved['source_bbox'][:2]
        else:
            x,y,w,h=original['source_bbox']
            gray,saved=render_window(original,[max(0,x-32),max(0,y-32),w+64,h+64],dpi=320)
            frame=saved['coordinate_frame'];origin=saved['source_bbox'][:2]
        Image.fromarray(gray).save(case/'native.png')
        metadata={'source_path':original['source_path'],'source_page':original['source_page'],'coordinate_frame':frame,
                  'origin_px':origin,'window_size_px':[gray.shape[1],gray.shape[0]],'reference_frame':original['coordinate_frame']}
        atomic_json(case/'window.json',metadata)
        low_gray=np.array(Image.open(PREVIEW/original['preview_files']['crop']).convert('L'))
        low=measure_fixed(original,low_gray,original['coordinate_frame'],original['source_bbox'][:2],normalized=True)
        old_native=measure_fixed(original,gray,frame,origin,normalized=False)
        fixed=measure_fixed(original,gray,frame,origin,normalized=True)
        positions=np.asarray([g[1] for g in original['candidate_geometry']]).reshape(-1,2)
        lowbox=[*(positions.min(0)-12),*(positions.max(0)+12)]
        plan['local_diagnostic_windows'].append({'reference_id':sid,'plan_unit':original['plan_unit'],
            'image_path':str((case/'native.png').relative_to(ROOT)),'metadata_path':str((case/'window.json').relative_to(ROOT)),
            'search_box_reference_xyxy':list(map(float,lowbox)),
            'search_basis':'old target neighborhood +/-12 reference pixels fixed before detection; not a crop or a forced target'})
        position={'original_sample_id':sid,'source_relative_path':original['source_relative_path'],'source_page':original['source_page'],
                  'reference_frame':original['coordinate_frame'],'native_source_window':metadata,
                  'fixed_original_on_low':low,'fixed_original_on_native_legacy_units':old_native,'fixed_original_on_native_reference_units':fixed,
                  'label_inherited':False}
        record['positions'].append(position)
        print(sid,'fixed-target source comparison complete',flush=True)
    record['regional_source_information']=source_region_types([original_by_id[sid] for sid in POSITIONS])
    atomic_json(OUT/'local-plan.json',plan)
    pool,pages,summaries=build_pool(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    history=[{**r,'display_geometry':r['display_geometry'],'display_crop_box':r['display_crop_box']} for r in original_by_id.values() if r['sample_id'] in POSITIONS]
    chosen,examples,selection=deduplicate(pool,None,preview_policy={'max_total':6,'max_page':2,'max_design':4,'max_difficult_page':0},history=history,preview_mode='development_replay')
    measured={}
    for row in chosen:
        page=next(pages[f'window-{i+1}'] for i,sid in enumerate(POSITIONS) if sid==row['diagnostic_position'])
        measure_row(row,SourceWindow(page['gray'],page['origin'],page['frame']['render_size_px']))
        measured[row['sample_id']]=row
    for index,position in enumerate(record['positions'],1):
        sid=position['original_sample_id'];page=pages[f'window-{index}'];original=original_by_id[sid]
        new,relation=association(original,position['fixed_original_on_native_reference_units'],page['eligible'],page['reference'])
        if new:
            if new['sample_id'] in measured:new=copy.deepcopy(measured[new['sample_id']])
            else:measure_row(new,SourceWindow(page['gray'],page['origin'],page['frame']['render_size_px']))
        position.update(local_redetection=next(s for s in summaries if s['reference_id']==sid),new_diagnostic_nomination=new,association=relation,
                        new_nomination_in_normal_selection=bool(new and new['sample_id'] in measured))
        display_position(position,original,page,images)
    record['actual_run']={'entry':'prepare_v2.build_pool -> extract.run -> trial_sampling.build_trial_pool(local diagnostic opt-in) -> native LSD/regional_nominations/local_geometry -> quality.inspect -> queue_dedup.deduplicate(development_replay) -> measurement.measure_row',
        'pages':3,'regions':5,'selected':len(chosen),'proposal_pool':len(pool),'selection':selection,'rejection_examples':examples,
        'pair_comparisons':sum(r['pair_comparisons'] for s in summaries for r in s['pair_budget']),
        'unexamined_comparisons':sum(r['unchecked_comparisons'] for s in summaries for r in s['pair_budget']),
        'original_previous_pair_statistics':'not recomputed or filled','control_coverage':'this diagnostic generated PAIR/SINGLE only; no inference about CONTROL',
        'full_page_context':'original saved low-resolution source caches; no high-DPI whole-page detection'}
    write_rows(OUT/'selected-diagnostic-targets.jsonl',chosen)
    atomic_json(OUT/'results.json',record)
    write_report(record)
    print(json.dumps({'output':str(OUT),'run':record['actual_run'],'positions':[{'id':p['original_sample_id'],'association':p['association'],'fixed_profile':p['fixed_original_on_native_reference_units']['measurement_status'],'new_profile':p['new_diagnostic_nomination']['measurement_status'] if p['new_diagnostic_nomination'] else None} for p in record['positions']]},ensure_ascii=False),flush=True)


def display_position(position,original,page,images):
    sid=position['original_sample_id'];gray=page['gray'];origin=page['origin']
    # Only package relevant source windows/context; no full engineering page.
    Image.fromarray(gray).save(images/(sid+'-source.png'))
    fixed=copy.deepcopy(position['fixed_original_on_native_reference_units']);fixed['source_bbox']=[*origin,gray.shape[1],gray.shape[0]]
    target_overlay(Image.fromarray(gray),fixed,1,trial=True).save(images/(sid+'-fixed.png'))
    if position['new_diagnostic_nomination']:
        new=copy.deepcopy(position['new_diagnostic_nomination']);new['source_bbox']=[*origin,gray.shape[1],gray.shape[0]]
        target_overlay(Image.fromarray(gray),new,1,trial=True).save(images/(sid+'-new.png'))
    shutil.copyfile(PREVIEW/original['preview_files']['crop'],images/(sid+'-old.png'))
    shutil.copyfile(PREVIEW/original['preview_files']['context_raw'],images/(sid+'-context.png'))
    position['comparison_images']={'old':'images/'+sid+'-old.png','source':'images/'+sid+'-source.png','fixed':'images/'+sid+'-fixed.png','context':'images/'+sid+'-context.png',
        'new':'images/'+sid+'-new.png' if position['new_diagnostic_nomination'] else None}


def write_report(record):
    # Report text is generated after actual detection, not a second UI or queue.
    from scale_report import write_report as shared
    shared(OUT,record)


def finish_corrected_run():
    """Reuse the same sources after the crop-border/probe-grid defects were found."""
    if (OUT/'initial-prototype-results.json').exists():raise ValueError('Corrected native run already performed')
    shutil.copyfile(OUT/'results.json',OUT/'initial-prototype-results.json')
    record=read(OUT/'results.json');originals={r['sample_id']:r for r in read_rows(PREVIEW/'manifest.jsonl')}
    record['prototype_corrections']=['same-side crop-border test replaces opposite-side endpoint error',
        'native 1px normal probes replace sparse reference-grid prototype which could miss narrow ink; only length thresholds get reference-unit conversion',
        'initial prototype results retained separately; not used as final output or training data']
    for p in record['positions']:
        original=originals[p['original_sample_id']];case=OUT/p['original_sample_id'];metadata=p['native_source_window']
        gray=np.array(Image.open(case/'native.png').convert('L'))
        low=np.array(Image.open(PREVIEW/original['preview_files']['crop']).convert('L'))
        p['fixed_original_on_low']=measure_fixed(original,low,original['coordinate_frame'],original['source_bbox'][:2],normalized=True)
        p['fixed_original_on_native_reference_units']=measure_fixed(original,gray,metadata['coordinate_frame'],metadata['origin_px'],normalized=True)
    plan=read(OUT/'local-plan.json')
    pool,pages,summaries=build_pool(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    history=[originals[sid] for sid in POSITIONS]
    chosen,examples,selection=deduplicate(pool,None,preview_policy={'max_total':6,'max_page':2,'max_design':4,'max_difficult_page':0},history=history,preview_mode='development_replay')
    measured={}
    for row in chosen:
        page=next(pages[f'window-{i+1}'] for i,sid in enumerate(POSITIONS) if sid==row['diagnostic_position'])
        measure_row(row,SourceWindow(page['gray'],page['origin'],page['frame']['render_size_px']));measured[row['sample_id']]=row
    for i,p in enumerate(record['positions'],1):
        page=pages[f'window-{i}'];original=originals[p['original_sample_id']]
        new,relation=association(original,p['fixed_original_on_native_reference_units'],page['eligible'],page['reference'])
        if new:
            if new['sample_id'] in measured:new=copy.deepcopy(measured[new['sample_id']])
            else:measure_row(new,SourceWindow(page['gray'],page['origin'],page['frame']['render_size_px']))
        p.update(local_redetection=next(s for s in summaries if s['reference_id']==p['original_sample_id']),new_diagnostic_nomination=new,
                 association=relation,new_nomination_in_normal_selection=bool(new and new['sample_id'] in measured))
        display_position(p,original,page,OUT/'images')
    record['actual_run'].update(selected=len(chosen),proposal_pool=len(pool),selection=selection,rejection_examples=examples,
        pair_comparisons=sum(r['pair_comparisons'] for s in summaries for r in s['pair_budget']),
        unexamined_comparisons=sum(r['unchecked_comparisons'] for s in summaries for r in s['pair_budget']))
    write_rows(OUT/'selected-diagnostic-targets.jsonl',chosen);atomic_json(OUT/'results.json',record)
    write_report(record)
    print(json.dumps({'selected':len(chosen),'eligible':len(pool),'pair_comparisons':record['actual_run']['pair_comparisons'],
        'positions':[{'id':p['original_sample_id'],'B':p['association']['status'],'A_profile':p['fixed_original_on_native_reference_units']['measurement_status'],
                     'B_profile':p['new_diagnostic_nomination']['measurement_status'] if p['new_diagnostic_nomination'] else None} for p in record['positions']]},ensure_ascii=False),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--finish-corrected-run',action='store_true')
    args=ap.parse_args()
    finish_corrected_run() if args.finish_corrected_run else run()
