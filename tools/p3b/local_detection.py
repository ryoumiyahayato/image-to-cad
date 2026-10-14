"""Opt-in PDF local redetection through the existing offline proposal pipeline."""

import copy
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from common import ROOT,read
from inventory import build as inventory_build
from extract import lines_from_source,crop_box,PAIR_MAX_SEPARATION_PX
from prepare_v2 import local_geometry
from quality import inspect,ink_distance
from trial_sampling import (render_explicit,pixel_center_to_pdf,pdf_to_pixel_center,
                            to_display,to_pdf,line_groups,regional_nominations)


def map_line(line,source_frame,target_frame):
    return sum([pdf_to_pixel_center(pixel_center_to_pdf(line[k:k+2],source_frame),target_frame) for k in (0,2)],[])


def inspect_window(row,gray,origin,reference_frame,distance=None):
    """Keep actual source data/geometry; convert only documented length units."""
    local=copy.deepcopy(row)
    for member in local['candidate_geometry']:
        member[1]=(np.asarray(member[1]).reshape(2,2)-origin).ravel().tolist()
    local['source_bbox']=[row['source_bbox'][0]-origin[0],row['source_bbox'][1]-origin[1],*row['source_bbox'][2:]]
    scale=row['source_dpi']/reference_frame['effective_dpi']
    return inspect(local,gray,distance,require_directional_edge=True,pixel_scale=scale)


def confined_to_crop_border(points,size,margin):
    """Both endpoints near the SAME boundary; through-lines are real candidates."""
    return any(np.all(points[:,axis]<margin) or np.all((size[axis]-1-points[:,axis])<margin)
               for axis in (0,1))


def partition_native_fragments(raw,origin,source,reference,size,prefix):
    """Keep raw evidence trace separately; final parent threshold is unchanged.

    Short evidence is not a queue candidate. No chains or gap filling are
    needed when existing long members were lost at the pairing-cell boundary.
    """
    scale=source['effective_dpi']/reference['effective_dpi']
    parents=[];trace=[]
    for gid,line,role in raw:
        points=np.asarray(line).reshape(2,2)
        full=(points+origin).ravel().tolist()
        mapped=map_line(full,source,reference)
        border=confined_to_crop_border(points,size,3*scale)
        length=float(np.linalg.norm(points[1]-points[0]))
        reason='crop_border' if border else 'parent_length_below_40_reference_px' if length<40*scale else None
        trace.append({'fragment_id':prefix+gid,'native_endpoints_global_px':full,
                      'reference_endpoints_px':mapped,'native_length_px':length,
                      'reference_length_px':float(np.linalg.norm(np.asarray(mapped)[2:]-mapped[:2])),
                      'border_passed':not border,'length_passed':length>=40*scale,
                      'stop_before_pairing':reason,'queue_parent':reason is None})
        if reason is None:parents.append((prefix+gid,mapped,role))
    return parents,trace


def build_local_trial_pool(page_plan,supplement):
    """Native local pixels -> LSD -> normal nominations/trim/quality.

    Parent proposals use the saved full-page reference grid for geometric
    nomination lengths. Final targets and quality use native source pixels.
    Nothing is selected by preview ID, category, file name, or model score.
    """
    units=inventory_build(page_plan=page_plan,supplement=supplement)
    pages={};rows=[];summaries=[]
    reuse=read(ROOT/page_plan['diagnostic_fragment_reuse_path']) if page_plan.get('diagnostic_fragment_reuse_path') else None
    for unit in units:
        gray,frame=render_explicit(unit)
        pages[unit['plan_unit']]={'gray':gray,'frame':frame,'unit':unit}
    for index,window in enumerate(page_plan['local_diagnostic_windows'],1):
        page=pages[window['plan_unit']];unit=page['unit'];reference=page['frame']
        metadata=read(ROOT/window['metadata_path'])
        if Path(metadata['source_path']).resolve()!=Path(unit['resolved_path']).resolve() or metadata['source_page']!=unit['page_or_layout']['page_number']:
            raise ValueError('Local source metadata differs from explicit original PDF/page')
        with Image.open(ROOT/window['image_path']) as im:native=np.array(im.convert('L'))
        if [native.shape[1],native.shape[0]]!=metadata['window_size_px']:
            raise ValueError('Local source dimensions differ from metadata')
        source=metadata['coordinate_frame'];origin=np.asarray(metadata['origin_px'])
        scale=source['effective_dpi']/reference['effective_dpi']
        if reuse is None:
            raw=lines_from_source(native,limit=None,min_length_px=0)
        else:
            saved=next(r for r in reuse if r['reference_id']==window['reference_id'])
            if saved['source_window_metadata']!=metadata:raise ValueError('Diagnostic fragment reuse source frame differs')
            raw=[];prefix=f'local-{index:02d}-'
            for f in saved['fragments']:
                if not f['fragment_id'].startswith(prefix):raise ValueError('Diagnostic parent namespace differs')
                full=f['native_endpoints_global_px']
                if not np.allclose(map_line(full,source,reference),f['reference_endpoints_px'],atol=1e-8):
                    raise ValueError('Diagnostic raw fragment coordinate frame differs')
                raw.append((f['fragment_id'][len(prefix):],
                    (np.asarray(full).reshape(2,2)-origin).ravel().tolist(),'PROPOSAL_ONLY'))
        parents,fragment_trace=partition_native_fragments(raw,origin,source,reference,
            [native.shape[1],native.shape[0]],f'local-{index:02d}-')
        border=sum(t['length_passed'] and not t['border_passed'] for t in fragment_trace)
        # One fixed search box per observed physical region, subdivided before
        # nominations. It is not the crop and does not force the old target.
        box=window['search_box_reference_xyxy'];cells=[]
        pw,ph=reference['page_size_points'];w,h=reference['render_size_px']
        for iy in range(2):
            for ix in range(2):
                cell=[box[0]+(box[2]-box[0])*ix/2,box[1]+(box[3]-box[1])*iy/2,
                      box[0]+(box[2]-box[0])*(ix+1)/2,box[1]+(box[3]-box[1])*(iy+1)/2]
                cells.append({'region_id':f'{unit["plan_unit"]}-local-{index}-search-{iy+1}-{ix+1}',
                              'pixel_box':cell,'display_box':[cell[0]*pw/w,cell[1]*ph/h,cell[2]*pw/w,cell[3]*ph/h],
                              'preferred_kind':'PAIR' if (iy+ix)%2==0 else 'SINGLE'})
        groups=line_groups(parents,reference,cells)
        statistics=[];counts=Counter();kinds=Counter();rejected=[];pair_trace=[];proposal_trace=[]
        distance=ink_distance(native)
        proposals=[]
        for nomination in regional_nominations(parents,native,cells,groups,
                pair_budget=page_plan['pair_budget_per_cell'],budget_stats=statistics,include_components=False,
                member_halo_px=PAIR_MAX_SEPARATION_PX,pair_trace=pair_trace):
            cx,cy=nomination['center']
            cell=next((c for c in cells if c['pixel_box'][0]<=cx<c['pixel_box'][2] and c['pixel_box'][1]<=cy<c['pixel_box'][3]),None)
            if cell is None:continue
            counts['in_search_region']+=1
            reference_geometry=local_geometry(nomination['geometry'],[cx,cy])
            if not reference_geometry:counts['no_final_extent']+=1;continue
            geometry=[[g[0],map_line(g[1],reference,source),g[2]] for g in reference_geometry]
            center=np.asarray([g[1] for g in geometry]).reshape(-1,2).mean(0)
            bbox=crop_box(native,center-origin,side=round(256*scale))
            bbox=[bbox[0]+int(origin[0]),bbox[1]+int(origin[1]),*bbox[2:]]
            crop_corners=[pdf_to_pixel_center(to_pdf(p,source),reference) for p in ([bbox[0],bbox[1]],[bbox[0]+bbox[2],bbox[1]+bbox[3]])]
            display_box=to_display([crop_corners[0][0]+.5,crop_corners[0][1]+.5,crop_corners[1][0]+.5,crop_corners[1][1]+.5],reference)
            row={'sample_id':f'local-proposal-{index:02d}-{counts["in_search_region"]:05d}',
                'diagnostic_position':window['reference_id'],'plan_unit':unit['plan_unit'],
                'source_entry_id':unit['source_entry_id'],'source_drawing_id':unit['source_drawing_id'],
                'source_family_id':unit['source_family_id'],'source_page':metadata['source_page'],
                'source_path':metadata['source_path'],'source_relative_path':unit['relative_path'],
                'source_dpi':source['effective_dpi'],'source_bbox':bbox,'coordinate_frame':source,
                'native_window_origin_px':origin.tolist(),'candidate_geometry':geometry,
                'candidate_geometry_ids':[g[0] for g in geometry],'target_roi':None,
                'target_kind':'PAIR' if len(geometry)==2 else 'SINGLE','preferred_kind':cell['preferred_kind'],
                'region_id':cell['region_id'],'region_landmark':'existing physical issue region, true native local LSD',
                'display_geometry':[to_display(g[1],reference) for g in reference_geometry],
                'display_parent_geometry':[to_display(next(p[1] for p in parents if p[0]==g[0]),reference) for g in reference_geometry],
                'display_crop_box':display_box,'display_target_box':None,
                'longline_proxy_ids':[f'{index}-{groups[g[0]]}' for g in geometry],
                'measurement_reference_frame':reference,'diagnostic_profile_trace':True,
                'purpose':'development_local_scale_replay','training_authorized':False,'label':None,
                'human_answer_inherited':False,'split':'diagnostic_not_dataset','line_style':'unknown',
                'new_information_claimed':False,'source_existing_split':unit['source_existing_split'],
                'proposal_relation':'geometry only; same source object and task membership are not established'}
            row['quality']=inspect_window(row,native,origin,reference,distance)
            proposal_trace.append({'sample_id':row['sample_id'],'members':row['candidate_geometry_ids'],
                'target_kind':row['target_kind'],'region_id':row['region_id'],
                'final_reference_geometry':reference_geometry,
                'quality_eligible':row['quality']['HUMAN_QUEUE_ELIGIBLE'],
                'quality_reasons':row['quality']['rejection_reasons']})
            kinds[row['target_kind']]+=1
            if row['quality']['HUMAN_QUEUE_ELIGIBLE']:
                rows.append(row);counts['quality_eligible']+=1;proposals.append(row)
            else:
                counts.update(row['quality']['rejection_reasons'])
                if len(rejected)<3:rejected.append({'id':row['sample_id'],'reasons':row['quality']['rejection_reasons']})
        pages[f'window-{index}']={'gray':native,'frame':source,'origin':origin.tolist(),
                                  'reference':reference,'window':window,'eligible':proposals,
                                  'fragments':fragment_trace,'pair_trace':pair_trace,'proposal_trace':proposal_trace,
                                  'cells':cells}
        summaries.append({'reference_id':window['reference_id'],'plan_unit':unit['plan_unit'],
            'source_window_size_px':[native.shape[1],native.shape[0]],'effective_dpi':source['effective_dpi'],
            'reference_dpi':reference['effective_dpi'],'actual_lsd_input':'native PDF local source pixels',
            'detected_min_length_px':0,'candidate_parent_min_length_px':40*scale,
            'raw_fragment_count':len(raw),'raw_lines_above_min_length':sum(t['length_passed'] for t in fragment_trace),
            'short_evidence_not_queue_candidates':sum(not t['length_passed'] for t in fragment_trace),
            'native_fragment_source':'saved current-run native LSD evidence; no second detection' if reuse is not None else 'actual native local LSD detection',
            'border_halo_lines_held':border,'pair_member_halo_reference_px':PAIR_MAX_SEPARATION_PX,
            'proposal_counts':dict(counts),'proposal_kind_counts':dict(kinds),'pair_budget':statistics,
            'rejected_examples':rejected,'control_coverage':'not generated: line-only local diagnostic, not proof of CONTROL behavior'})
        print(window['reference_id'],native.shape,'native fragments reused:' if reuse is not None else '320 DPI local LSD:',
              len(raw),'fragments,',counts['quality_eligible'],'eligible',flush=True)
    return rows,pages,summaries
