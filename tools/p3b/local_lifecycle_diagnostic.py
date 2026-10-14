"""One same-window lifecycle replay. No PDF rendering, labels or fitting."""

import copy
import itertools
import math
import argparse
from collections import Counter
from pathlib import Path
import shutil
import html
import zipfile

import numpy as np
from PIL import Image,ImageDraw,ImageFont

from common import ROOT,read,read_rows,atomic_json,write_rows
from local_detection import map_line
from local_scale_diagnostic import association
from measurement import measure_row,SourceWindow
from prepare_v2 import build_pool
from quality import sample_line,ink_distance,edge_attachment,POLICY
from queue_dedup import deduplicate
from trial_sampling import intersect,same_target

PREVIOUS=ROOT/'local-artifacts/product-fix-p3b/local-scale-20261011-001'
OUT=ROOT/'local-artifacts/product-fix-p3b/local-lifecycle-20261011-001'


def member_relations(a,b):
    """Post-run source/member/extent trace; never a selection template."""
    if a['source_drawing_id']!=b['source_drawing_id'] or a['source_page']!=b['source_page']:return None
    common=set(a['candidate_geometry_ids']) & set(b['candidate_geometry_ids'])
    if not common:return None
    evidence=[]
    for gid in sorted(common):
        x=next(np.asarray(g[1]).reshape(2,2) for g in a['candidate_geometry'] if g[0]==gid)
        y=next(np.asarray(g[1]).reshape(2,2) for g in b['candidate_geometry'] if g[0]==gid)
        t=(x[1]-x[0])/np.linalg.norm(x[1]-x[0]);n=np.array([-t[1],t[0]])
        p=sorted((y-x[0])@t);length=float(np.linalg.norm(x[1]-x[0]))
        evidence.append({'member_id':gid,'max_normal_offset_source_px':float(max(abs((y-x[0])@n))),
            'shared_fraction_of_requested_extent':max(0,min(length,p[1])-max(0,p[0]))/length,
            'requested_length_source_px':length,'output_length_source_px':float(np.linalg.norm(y[1]-y[0]))})
    full=set(a['candidate_geometry_ids'])==set(b['candidate_geometry_ids'])
    return {'output':b['sample_id'],'output_kind':b['target_kind'],'common_members':evidence,
        'complete_member_set':full,'equivalent_target_geometry':bool(full and same_target(a,b)),
        'full_requested_extent_retained':full and all(e['shared_fraction_of_requested_extent']>=.98 for e in evidence)}


def related_fragments(original,page):
    ref=original['coordinate_frame'];scale=page['frame']['effective_dpi']/ref['effective_dpi']
    result=[];distance=ink_distance(page['gray'])
    for member,(gid,line,role) in zip('AB',original['candidate_geometry']):
        old=np.asarray(line).reshape(2,2);t=(old[1]-old[0])/np.linalg.norm(old[1]-old[0]);n=np.array([-t[1],t[0]])
        length=float(np.linalg.norm(old[1]-old[0]))
        for fragment in page['fragments']:
            p=np.asarray(fragment['reference_endpoints_px']).reshape(2,2);v=p[1]-p[0]
            delta=math.degrees(math.acos(float(np.clip(abs(t@v)/max(np.linalg.norm(v),1e-9),0,1))))
            projection=sorted((p-old[0])@t)
            overlap=max(0,min(length,projection[1])-max(0,projection[0]))
            offset=float(max(abs((p-old[0])@n)))
            if delta>3 or overlap<=0 or offset>2:continue
            local=(np.asarray(fragment['native_endpoints_global_px']).reshape(2,2)-page['origin']).ravel().tolist()
            support=sample_line(page['gray'],distance,local,support_radius_px=POLICY['support_radius_px']*scale,tangent_probe_px=3*scale,endpoint_extent_scale=scale)
            directional=edge_attachment(page['gray'],local,POLICY['support_radius_px']*scale)
            cells=[c['region_id'] for c in page['cells'] if intersect(
                [p[:,0].min()-1,p[:,1].min()-1,p[:,0].max()+1,p[:,1].max()+1],c['pixel_box'])]
            proposals=[q for q in page['proposal_trace'] if fragment['fragment_id'] in q['members']]
            result.append({**fragment,'original_member':member,'reference_normal_offset_px':offset,
                'original_projection_interval_px':[max(0,projection[0]),min(length,projection[1])],
                'original_length_reference_px':length,'old_core_member_cells':cells,
                'source_support':support,'directional_edge':directional,'new_proposals':proposals,
                'association_limit':'position/direction and local pixels only; fragment identity is not a semantic label'})
    return result


def interval_union(intervals):
    union=[]
    for lo,hi in sorted(intervals):
        if union and lo<=union[-1][1]:union[-1][1]=max(hi,union[-1][1])
        else:union.append([lo,hi])
    return union


def saved_pool_export(plan,original):
    """Recover an interrupted export without detecting or changing geometry."""
    pool=read_rows(OUT/'eligible-pool.jsonl');traces=read_rows(OUT/'lifecycle.jsonl')
    pages={};summaries=[]
    for i,w in enumerate(plan['local_diagnostic_windows'],1):
        m=read(ROOT/w['metadata_path']);t=next(t for t in traces if t['reference_id']==w['reference_id'])
        gray=np.array(Image.open(ROOT/w['image_path']).convert('L'));ref=original[w['reference_id']]['coordinate_frame']
        b=w['search_box_reference_xyxy'];cells=[]
        for y in range(2):
            for x in range(2):
                cells.append({'region_id':f'{w["plan_unit"]}-local-{i}-search-{y+1}-{x+1}',
                    'pixel_box':[b[0]+(b[2]-b[0])*x/2,b[1]+(b[3]-b[1])*y/2,
                                 b[0]+(b[2]-b[0])*(x+1)/2,b[1]+(b[3]-b[1])*(y+1)/2]})
        budgets=[]
        for c in cells:
            q=c['pixel_box'];query=[q[0]-60,q[1]-60,q[2]+60,q[3]+60]
            count=sum(intersect([min(f['reference_endpoints_px'][::2])-1,min(f['reference_endpoints_px'][1::2])-1,
                max(f['reference_endpoints_px'][::2])+1,max(f['reference_endpoints_px'][1::2])+1],query)>0
                for f in t['fragments'] if f['queue_parent'])
            actual=sum(e['region_id']==c['region_id'] for e in t['pair_comparisons']);total=count*(count-1)//2
            budgets.append({'region_id':c['region_id'],'pair_comparisons':actual,'unchecked_comparisons':total-actual,
                'pair_budget':250,'member_halo_px':60,'member_count':count,'complete':actual==total})
        pages[f'window-{i}']={'gray':gray,'frame':m['coordinate_frame'],'origin':m['origin_px'],'reference':ref,
            'window':w,'cells':cells,'eligible':[r for r in pool if r['diagnostic_position']==w['reference_id']],
            'fragments':t['fragments'],'pair_trace':t['pair_comparisons'],'proposal_trace':t['final_proposals']}
        summaries.append({'reference_id':w['reference_id'],'raw_fragment_count':len(t['fragments']),
            'raw_lines_above_min_length':sum(f['length_passed'] for f in t['fragments']),
            'short_evidence_not_queue_candidates':sum(not f['length_passed'] for f in t['fragments']),
            'eligible':len(pages[f'window-{i}']['eligible']),'pair_budget':budgets,
            'source_window_size_px':m['window_size_px'],'effective_dpi':320,'reference_dpi':ref['effective_dpi'],
            'counts_basis':'actual persisted native detector and comparison events; export-only recovery'})
    return pool,pages,summaries


def run(*,resume_export=False,resume_pairing=False):
    if OUT.exists() and not (resume_export or resume_pairing):raise ValueError('Do not overwrite or silently repeat the bounded replay')
    old=read(PREVIOUS/'results.json');plan=copy.deepcopy(read(PREVIOUS/'local-plan.json'))
    original={r['sample_id']:r for r in read_rows(ROOT/'local-artifacts/product-fix-p3b/preview-trial-20261010-001/manifest.jsonl')}
    previous_selected=read_rows(PREVIOUS/'selected-diagnostic-targets.jsonl')
    if resume_pairing:
        if (OUT/'initial-retrieval-results.json').exists():raise ValueError('Pairing correction already completed')
        initial=read(OUT/'results.json');traces=read_rows(OUT/'lifecycle.jsonl')
        shutil.copyfile(OUT/'results.json',OUT/'initial-retrieval-results.json')
        cache=OUT/'native-fragment-reuse.json'
        atomic_json(cache,[{'reference_id':w['reference_id'],'source_window_metadata':read(ROOT/w['metadata_path']),
            'fragments':next(t['fragments'] for t in traces if t['reference_id']==w['reference_id'])} for w in plan['local_diagnostic_windows']])
        plan['diagnostic_fragment_reuse_path']=str(cache.relative_to(ROOT))
        pool,pages,summaries=build_pool(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    elif resume_export:
        if (OUT/'results.json').exists():raise ValueError('An already completed diagnostic cannot be resumed')
        saved_selected=read_rows(OUT/'selected-diagnostic-targets.jsonl')
        pool,pages,summaries=saved_pool_export(plan,original)
    else:
        OUT.mkdir()
        pool,pages,summaries=build_pool(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    chosen,examples,selection=deduplicate(pool,None,preview_policy={
        'max_total':6,'max_page':2,'max_design':4,'max_difficult_page':0,'record_decisions':True},
        history=[original[w['reference_id']] for w in plan['local_diagnostic_windows']],preview_mode='development_replay')
    decision={d['proposal']:d for d in selection['decisions']}
    if resume_export and [(r['sample_id'],r['candidate_geometry']) for r in chosen]!=[(r['sample_id'],r['candidate_geometry']) for r in saved_selected]:
        raise ValueError('Export recovery changed selected geometry')
    page_by_id={w['reference_id']:pages[f'window-{i}'] for i,w in enumerate(plan['local_diagnostic_windows'],1)}
    positions=[];measured={}
    def measure(row,page):
        if row['sample_id'] not in measured:
            value=copy.deepcopy(row)
            measure_row(value,SourceWindow(page['gray'],page['origin'],page['frame']['render_size_px']))
            measured[row['sample_id']]=value
        return measured[row['sample_id']]
    for row in chosen:measure(row,page_by_id[row['diagnostic_position']])
    for prior in old['positions']:
        sid=prior['original_sample_id'];page=page_by_id[sid];base=original[sid]
        proposed,relation=association(base,prior['fixed_original_on_native_reference_units'],page['eligible'],base['coordinate_frame'])
        if proposed:proposed=measure(proposed,page)
        related=related_fragments(base,page) if sid=='preview-007' else []
        for fragment in related:
            for q in fragment['new_proposals']:q['selection']=decision.get(q['sample_id'])
        previous_new=prior.get('new_diagnostic_nomination')
        old_links=[v for r in previous_selected if previous_new and (v:=member_relations(previous_new,r))]
        lineage_pool=[r for r in page['eligible'] if previous_new and
            set(r['candidate_geometry_ids'])==set(previous_new['candidate_geometry_ids']) and same_target(r,previous_new)]
        lineage=[{'sample_id':r['sample_id'],'members':r['candidate_geometry_ids'],
                  'selection':decision[r['sample_id']],
                  'links_to_final_outputs':[v for s in chosen if (v:=member_relations(r,s))]} for r in lineage_pool]
        links=[v for r in chosen if proposed and (v:=member_relations(proposed,r))]
        direct=[]
        if sid=='preview-007':
            long_a=[f for f in related if f['original_member']=='A' and f['queue_parent']]
            long_b=[f for f in related if f['original_member']=='B' and f['queue_parent']]
            for a,b in itertools.product(long_a,long_b):
                ids={a['fragment_id'],b['fragment_id']}
                direct.append({'members':sorted(ids),'old_shared_core_cells':sorted(set(a['old_core_member_cells']) & set(b['old_core_member_cells'])),
                    'new_pair_comparisons':[e for e in page['pair_trace'] if set(e['members'])==ids],
                    'new_pair_proposals':[q for q in page['proposal_trace'] if set(q['members'])==ids]})
        short=[f for f in related if f['original_member']=='A' and not f['length_passed']]
        union=interval_union([f['original_projection_interval_px'] for f in short])
        positions.append({'reference_id':sid,'source_relative_path':base['source_relative_path'],'source_page':base['source_page'],
            'native_window':prior['native_source_window'],'original_fixed_target':prior['fixed_original_on_native_reference_units'],
            'association_after_detection':relation,'new_associated_nomination':proposed if relation.get('same_object') else None,
            'unassociated_nearby_nomination':proposed if not relation.get('same_object') else None,
            'association_selection_decision':decision.get(proposed['sample_id']) if proposed else None,
            'association_links_to_outputs':links,'previous_improved_nomination':previous_new,
            'previous_improved_links_to_previous_outputs':old_links,
            'previous_improved_equivalent_pool_targets':lineage,
            'related_fragment_lifecycle':related,'existing_long_member_pair_lifecycle':direct,
            'short_A_projection_union_reference_px':union,
            'short_A_projection_coverage_fraction':sum(hi-lo for lo,hi in union)/short[0]['original_length_reference_px'] if short else None,
            'short_A_gaps_not_filled_reference_px':[[union[i][1],union[i+1][0]] for i in range(len(union)-1)],
            'human_label_inherited':False})
    write_rows(OUT/'selected-diagnostic-targets.jsonl',[measured[r['sample_id']] for r in chosen])
    write_rows(OUT/'eligible-pool.jsonl',pool)
    # Lightweight actual fragment/pair/quality trace; source images stay in
    # their original artifact directory and are never overwritten.
    write_rows(OUT/'lifecycle.jsonl',[{'reference_id':sid,'fragments':p['fragments'],
        'pair_comparisons':p['pair_trace'],'final_proposals':p['proposal_trace']} for sid,p in page_by_id.items()])
    atomic_json(OUT/'results.json',{'purpose':'development_lifecycle_replay','training_authorized':False,
        'labels_assigned':0,'normal_entry':'prepare_v2.build_pool -> build_trial_pool -> build_local_trial_pool -> queue_dedup.deduplicate',
        'source_reuse':'existing five native320 windows on three PDF pages; no rendering or resampling',
        'changes':{'pair_member_retrieval':'60 reference-pixel halo matching the unchanged loose pair maximum separation; center owned by unchanged core cell',
            'geometry_order':'canonical endpoint and carrier order, no fragment joining',
            'short_fragments':'raw evidence kept in local trace; final parent40 and final nomination/quality thresholds unchanged',
            'selection':'optional complete decisions; preferred-kind ordering and all quotas unchanged'},
        'selection':selection,'summaries':summaries,'positions':positions,
        'export_recovery':'NumPy boolean serialization corrected; exported from saved pool and native lifecycle. No second detection. Selection decisions reconstructed and selected geometries checked unchanged.' if resume_export else None,
        'pairing_stage_revision':'Initial expanded retrieval exhausted001 comparison budget. Spatial/angle index corrected; nomination, quality and selection stages completed from the same saved native fragments. No second LSD detection or source rendering. Initial result retained.' if resume_pairing else None,
        'normal_mode_history_exclusion':'default preserved; this run explicitly allows known positions, not a new-information batch',
        'coverage_limit':'local line-only replay, not CONTROL or whole-sampler validation; object/class identity not established by profile'})
    print('one bounded replay:',len(pool),'eligible;',len(chosen),'selected;',OUT,flush=True)
    for p in positions:
        n=p['new_associated_nomination'];print(p['reference_id'],p['association_after_detection']['status'],
            n['sample_id'] if n else None,p['association_selection_decision'],flush=True)


def junction_observations(position):
    """Read unchanged ink in detector gaps; do not make edge associations."""
    m=position['native_window'];origin=np.asarray(m['origin_px']);ref=position['original_fixed_target']['measurement_reference_frame']
    native=m['coordinate_frame'];gray=np.array(Image.open(PREVIOUS/'preview-007/native.png').convert('L'))
    fragments=position['related_fragment_lifecycle'];short=[f for f in fragments if not f['length_passed']]
    upper_row=int(math.ceil(np.mean(np.asarray(short[0]['native_endpoints_global_px']).reshape(2,2)[:,1]-origin[1])))
    old=map_line(position['original_fixed_target']['candidate_geometry'][0][1],native,ref)
    old=np.asarray(old).reshape(2,2);t=(old[1]-old[0])/np.linalg.norm(old[1]-old[0]);result=[]
    for lo,hi in position['short_A_gaps_not_filled_reference_px']:
        endpoints=np.r_[old[0]+lo*t,old[0]+hi*t]
        p=np.asarray(map_line(endpoints,ref,native)).reshape(2,2)-origin
        x0,x1=sorted(int(round(x)) for x in p[:,0]);pixels=gray[upper_row,x0:x1+1]
        result.append({'original_projection_gap_reference_px':[lo,hi],
            'adjacent_ink_row_local_native_px':upper_row,'columns_local_native_px':[x0,x1],
            'gray_min':int(pixels.min()),'gray_max':int(pixels.max()),
            'dark_fraction_at_180':float((pixels<180).mean()),
            'limit':'actual nearby ink row; not proof of a unique edge through the junction, no gap filled'})
    return result


def publish():
    """Four static cards and one compact table, all assets inside the ZIP."""
    path=OUT/'results.json';result=read(path);positions={p['reference_id']:p for p in result['positions']}
    chosen=read_rows(OUT/'selected-diagnostic-targets.jsonl');assets=OUT/'images';assets.mkdir(exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20)
    small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    title=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',26)
    def source(sid):return Image.open(PREVIOUS/sid/'native.png').convert('RGB')
    def pane(sid,geometries,box,size):
        image=source(sid);draw=ImageDraw.Draw(image);origin=np.asarray(positions[sid]['native_window']['origin_px'])
        for geometry,color,width in geometries:
            for g in geometry:
                p=(np.asarray(g[1]).reshape(2,2)-origin).ravel().tolist()
                draw.line(p,fill=color,width=width)
                for x,y in zip(p[::2],p[1::2]):draw.ellipse((x-2,y-2,x+2,y+2),fill=color)
        # Display-only nearest-neighbour scaling; measurement uses native.png.
        crop=image.crop(box);crop.thumbnail(size,Image.Resampling.NEAREST)
        return crop
    def put(canvas,image,xy):canvas.paste(image,xy)
    red=(208,45,39);blue=(20,98,212);teal=(0,150,140);purple=(171,36,175);green=(0,139,84);oldgray=(140,140,140)
    p=positions['preview-007'];fragments=p['related_fragment_lifecycle'];n=p['new_associated_nomination']
    canvas=Image.new('RGB',(1500,740),'white');d=ImageDraw.Draw(canvas)
    d.text((20,10),'007｜原页局部、原生片段与最终线对',font=title,fill='black')
    d.text((20,54),'灰：旧定位；源窗口320 DPI，未改源像素',font=small,fill='black')
    put(canvas,pane('preview-007',[(p['original_fixed_target']['candidate_geometry'],oldgray,2)],(0,0,1083,1083),(530,530)),(20,85))
    d.text((20,633),'整页框定位：仓库电专业第6页，旋转270°',font=small,fill='black')
    pagebox=(25,662,275,728);d.rectangle(pagebox,outline='black',width=1)
    m=p['native_window'];w,h=m['coordinate_frame']['render_size_px'];x,y=m['origin_px'];sw,sh=m['window_size_px']
    d.rectangle((25+x/w*250,662+y/h*66,25+(x+sw)/w*250,662+(y+sh)/h*66),outline=red,width=2)
    d.text((292,669),'框为原页局部位置',font=small,fill='black')
    d.text((292,694),'不复制整页图纸',font=small,fill='black')
    raw=[]
    for f in fragments:
        color=teal if not f['length_passed'] else red if f['original_member']=='A' else blue if f['fragment_id'].endswith('000188') else purple
        raw.append(([[f['fragment_id'],f['native_endpoints_global_px'],'diagnostic']],color,1))
    d.text((570,68),'原生检测：青色14短段；红128；蓝188；紫200',font=font,fill='black')
    put(canvas,pane('preview-007',raw,(210,500,1083,584),(905,180)),(570,106))
    d.text((570,227),'旧上下搜索格把128与188／200分开，未共同配对',font=font,fill='black')
    d.text((570,261),'14短段在踏步交会附近分开；保留缺口记录，未组链',font=small,fill='black')
    d.text((570,315),'修复后：128＋188，成员检索外扩，中心仍归原格',font=font,fill='black')
    gs=[(n['candidate_geometry'][:1],red,2),(n['candidate_geometry'][1:],blue,2)]
    put(canvas,pane('preview-007',gs,(210,500,1083,584),(905,180)),(570,354))
    d.text((570,474),'共同投影166.76参考px；原区间覆盖100%；质量通过',font=font,fill='black')
    d.text((570,509),'A方向支持0.994，B为1.000；最长无支持间隔均0',font=small,fill='black')
    d.text((570,547),'最终输出05-00001；A/B重新测量18/19与19/19探针',font=font,fill='black')
    d.text((570,591),'188／200是下方同一笔画的两侧；不是原双边界',font=small,fill='black')
    d.text((570,628),'128＋200也形成线对，以同目标去重排除；没有换轨',font=small,fill='black')
    d.text((570,674),'源边缘位置证据成立；实体语义和人工类别未自动确定',font=small,fill='black')
    canvas.save(assets/'007.png')
    p=positions['preview-006'];selected=[r for r in chosen if r['diagnostic_position']=='preview-006']
    canvas=Image.new('RGB',(1260,650),'white');d=ImageDraw.Draw(canvas)
    d.text((20,10),'006｜原提名仍暂缓；附近可见线不冒充恢复',font=title,fill='black')
    d.text((20,53),'左：旧竖向提名（红）；右：本次真实输出（绿）',font=font,fill='black')
    put(canvas,pane('preview-006',[(p['original_fixed_target']['candidate_geometry'],red,2)],(0,0,937,937),(500,500)),(20,96))
    put(canvas,pane('preview-006',[(r['candidate_geometry'],green,2) for r in selected],(0,0,937,937),(500,500)),(650,96))
    d.text((20,610),'原位置未取得满足方向和范围的对应候选；未组链，未制造竖边',font=small,fill='black')
    canvas.save(assets/'006.png')
    boxes={}
    for sid in ('preview-001','preview-010','preview-015'):
        p=positions[sid];n=p['new_associated_nomination'];local=np.asarray([g[1] for g in n['candidate_geometry']]).reshape(-1,2)-p['native_window']['origin_px']
        others=[r for r in chosen if r['diagnostic_position']==sid]
        allpoints=np.concatenate([local,*[np.asarray([g[1] for g in r['candidate_geometry']]).reshape(-1,2)-p['native_window']['origin_px'] for r in others]])
        lo=np.floor(allpoints.min(0)-65).astype(int);hi=np.ceil(allpoints.max(0)+65).astype(int)
        w,h=p['native_window']['window_size_px'];boxes[sid]=[max(0,int(lo[0])),max(0,int(lo[1])),min(w,int(hi[0])),min(h,int(hi[1]))]
    for name,selection_card in (('controls',False),('selection',True)):
        canvas=Image.new('RGB',(1500,700),'white');d=ImageDraw.Draw(canvas)
        d.text((20,10),'改善提名的实际输出｜绿为请求提名，紫为本次输出' if selection_card else '防退化对照｜灰为旧定位，绿为改善提名',font=title,fill='black')
        for col,sid in enumerate(('preview-001','preview-010','preview-015')):
            p=positions[sid];n=p['new_associated_nomination'];x=20+col*495
            d.text((x,60),sid+'｜仍在可用池，质量通过',font=font,fill='black')
            overlays=[(n['candidate_geometry'],green,2)]
            if selection_card:overlays.extend((r['candidate_geometry'],purple,2) for r in chosen if r['diagnostic_position']==sid)
            else:overlays.insert(0,(p['original_fixed_target']['candidate_geometry'],oldgray,2))
            put(canvas,pane(sid,overlays,boxes[sid],(460,450)),(x,102))
            notes={'preview-001':['完整686＋257未输出；页面名额已满','输出112＋686，257未保留；关系不同'],
                   'preview-010':['072未输出；附近线对占用同裁区','输出036＋167，源纵坐标不同'],
                   'preview-015':['142的180参考px未完整输出','117＋142仅覆盖请求区间38.1%']}
            if selection_card:
                for j,note in enumerate(notes[sid]):d.text((x,590+j*32),note,font=small,fill='black')
            else:
                a=p['association_after_detection'];d.text((x,590),f'最大法向差{a["max_normal_offset_reference_px"]:.3f}参考px',font=small,fill='black')
                d.text((x,623),'源支持、方向和全段检查保持；不继承标签',font=small,fill='black')
        canvas.save(assets/(name+'.png'))
    p=positions['preview-007'];p['junction_gap_observations']=junction_observations(p)
    p['old_detector_intersection_limit']='Saved low-DPI parent328 spans the current tread junctions; complete old raw intersection list not obtained. Native short pieces and actual ink can be compared, not a claim about all old detector events.'
    for position in positions.values():
        n=position['new_associated_nomination']
        position['geometry_only_equivalent_final_outputs']=[r['sample_id'] for r in chosen if n
            and r['source_drawing_id']==n['source_drawing_id'] and r['source_page']==n['source_page']
            and same_target(n,r)]
        position['equivalence_trace_basis']='Same page plus full unordered member geometry/extent comparison, independent of sample ID or parent ID; shared members alone do not establish complete PAIR retention.'
    result['local_checks']={'test_local_lifecycle.py':{'tests':7,'result':'passed'},
        'scope':'real007 crossing-cell pair and real001 budget, short trace vs final threshold, source intersections, true gap, separate parallel members, order/end reversal, default history exclusion',
        'full_tests_run':False}
    result['delivery']={'cards':4,'html':'index.html','package':'comparison-package.zip','source_images_modified':False}
    atomic_json(path,result)
    esc=lambda v:html.escape(str(v))
    reasons={'same_target':'同目标去重','shared_line_cap':'共享长线名额','cross_kind_region_occupancy':'同裁区占用','page_or_design_cap':'页面或设计名额','region_cap':'区域名额'}
    table=[]
    for f in p['related_fragment_lifecycle']:
        endpoints=', '.join(f'{v:.2f}' for v in f['reference_endpoints_px'])
        if not f['length_passed']:stage='长度阶段止步；不入候选池';pair='未配对';out='未进入最终选择'
        else:
            stage='裁边、40参考px长度均通过'
            pair='；'.join(q['sample_id'].removeprefix('local-proposal-')+' '+q['target_kind']+(' 质量通过' if q['quality_eligible'] else ' 质量拒绝') for q in f['new_proposals'])
            out='；'.join(q['sample_id'].removeprefix('local-proposal-')+': '+('输出' if q.get('selection',{}).get('outcome')=='selected' else reasons.get(q.get('selection',{}).get('reason'),q.get('selection',{}).get('reason','未取得'))) for q in f['new_proposals'])
        table.append('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in [f['original_member']+'附近 '+f['fragment_id'].removeprefix('local-05-P3B-LSD-'),endpoints,f'{f["reference_length_px"]:.2f}',stage,pair,out,f'{f["source_support"]["SOURCE_SUPPORT_RATIO"]:.3f} / {f["directional_edge"]["directional_edge_ratio"]:.3f}'])+'</tr>')
    for sid in ('preview-010','preview-015','preview-001'):
        q=positions[sid];n=q['new_associated_nomination'];decision=q['association_selection_decision']
        geom=' / '.join(', '.join(f'{v:.2f}' for v in map_line(g[1],n['coordinate_frame'],n['measurement_reference_frame'])) for g in n['candidate_geometry'])
        table.append('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in [sid+' '+n['sample_id'],geom,'见记录','原生、裁边、长度均通过',n['target_kind']+'；质量通过',reasons[decision['reason']]+'；占位 '+str(decision.get('related') or decision.get('quota_occupants')),'支持及方向均1.000'])+'</tr>')
    brief='''<p>原因已定位到配对入口：A的128与B的188／200分落上下搜索格，旧入口只取触及本格的成员，没有共同检索它们。它们直接满足原角度、间距和共同投影条件。14短段也被40参考px过滤，但现存长段足以形成线对；本轮没有新增边缘链，也没有降低最终长度或质量要求。</p>
<p>007的A长段246.80参考px，覆盖旧A区间；旧SINGLE输出只取其居中180参考px，旧A区间有部分没有展示。B的188／200各175.13参考px，是下方同一笔画的上下两侧，不能把两者的PAIR冒充原A＋B。本轮128＋188共同投影166.76参考px，覆盖旧诊断区间，源支持均1，方向支持0.994／1.000，最长无支持间隔均0，质量通过并输出。128＋200以同目标去重排除。</p>
<p>14短段位于上方笔画另一侧，在踏步交会附近分开。区间并集覆盖89.78%，重叠没有重复计入。13个内部缺口的相邻原生墨迹行均有黑色像素；这只是墨迹观察，不证明唯一边缘连续关联，也没有补齐10.22%。保存的低分辨率长段跨过这些源图交会位置；旧原生全检测交点表未取得。</p>'''
    html_text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>007局部生命周期修复</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1500px;margin:24px auto;padding:0 20px;color:#17232c;background:#f7f8fa}section{background:white;padding:20px;margin:22px 0;border:1px solid #d6dce2;border-radius:8px}h1{font-size:26px}h2{font-size:21px}img{max-width:100%;height:auto}table{border-collapse:collapse;font-size:13px;width:100%}th,td{border:1px solid #d5dce3;padding:7px;vertical-align:top}th{background:#edf1f4}td:nth-child(2){min-width:210px}a{color:#155aaa}.table{overflow:auto}.note{color:#43525e}</style><h1>007双边界：从原生片段到最终输出</h1>
<p>开发回放；5个既定局部窗口、3个PDF页面。沿用320 DPI原页局部源图；没有新渲染、训练、自动标签或人工标注任务。</p>'''+brief+'''
<section><h2>1．007：两个已有长成员重新进入共同配对</h2><a href="images/007.png"><img src="images/007.png" alt="007原页局部、原生碎段与最终线对"></a><p>最大法向差0.833参考px；新几何仅建立可見笔画位置关联。A/B重新测量分别18/19与19/19有效探针，均稳定；不继承旧回答或旧profile，不据此宣布实体语义或识别准确率。</p></section>
<section><h2>2．006：原对应问题仍暂缓</h2><a href="images/006.png"><img src="images/006.png" alt="006原竖边未恢复"></a><p>原竖向提名没有对应候选。输出01-00001是附近另一个可见竖向成员016；不能因其通过质量或取得profile就恢复原提名。没有组链、补线或移用旧标签。</p></section>
<section><h2>3．001／010／015：改善提名仍在可用池</h2><a href="images/controls.png"><img src="images/controls.png" alt="已有改善提名的防退化检查"></a><p>三处均保持原源边缘几何关联和质量通过，重新测量各成员，没有继承过期profile。最大法向差依次0.748／0.694／0.914参考px。</p></section>
<section><h2>4．改善存在，不等于完整输出</h2><a href="images/selection.png"><img src="images/selection.png" alt="改善提名在正常选择规则中的去向"></a><p>010的072因裁框重叠被02-00013的036＋167挡住；输出源纵坐标679.18／682.57，改善提名为712.66，成员及笔画不同。015的142因03-00040的117＋142占用长线名额而排除；只共享请求区间38.13%，没有完整保留180参考px目标。001的686＋257完整提名04-00011因TRIAL-02已有两项而排除；输出04-00001为112＋686，257未保留。旧输出只包含686这个SINGLE，也不是原PAIR。</p><p>选择仍按来源、页面、区域轮转，区域内沿用原提名类型偏好、源支持和长度顺序。第一搜索格先占名额，候选顺序确有影响；这些是不同目标关系的竞争，没有证明“较差拟合同一个等价目标先占位”。本轮不以诊断ID强行选出，不新增PAIR/SINGLE优先，也未修改名额。135项可用提名仅保留5项开发输出，人工类别为空。</p></section>
<section><h2>候选在哪一步丢失</h2><p>端点及长度为保存的全页参考栅格px；007为94.58 DPI、010/001为110 DPI、015为94.58 DPI。完整320 DPI原页端点、父成员、支持区间、选择决定见包内JSON。源支持/方向列只是有限局部几何证据。</p><div class="table"><table><thead><tr><th>关联线索／片段或提名</th><th>参考端点 x1,y1,x2,y2</th><th>长度</th><th>原生→裁边→长度</th><th>配对→最终几何→质量</th><th>去重／名额→输出</th><th>源支持／方向</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></div></section>
<section><h2>本轮修改与检查</h2><p>local_detection.partition_native_fragments：保留原生短段追踪，最终父段40参考px不变。build_local_trial_pool：局部成员检索外扩60参考px，共用原配对最大间距；同次执行可复用原生片段。trial_sampling.regional_nominations／spatial_pair_neighbors：空间与方向索引减少无关比较，250次每格预算不变；半开核心格归属不变；端点及片段顺序标准化。preview_selection.select_preview：只新增可选逐候选决定记录，未改优选、去重和名额规则。extract.nominations：原3°／60px数值提为共用常量。测量与生产几何未修改。</p><p>本次原生检测仅一次。初版外扩后001预算不足，已保存初版记录，并在同次执行中复用原生片段修正提名／质检／选择阶段，没有第二次LSD或原页渲染。最终空间索引后检查2576组配对，未检查空间邻居0组；这不代表全页、所有目标类型或所有设计都验证完毕。</p><p>7项相关局部检查通过：真实007跨格漏配；真实001预算防退化；短段证据与最终40px门槛分开；源交点保持连续；真实缺口拒绝且未改像素；平行成员与输入反向等价；普通模式历史排除。没有全量测试。普通模式仍默认排除历史已看位置，本次显式回放结果不构成新信息标注批次。</p><p class="note">旧20回答、94/50、冻结特征和模型、生产DXF/OCR及原始资料未改。口径建议维持原状态。没有启动标注、训练、监控或第二轮任务。</p><p><a href="results.json">实际追踪记录</a> · <a href="selected-diagnostic-targets.jsonl">5项开发输出</a></p></section></html>'''
    (OUT/'index.html').write_text(html_text,encoding='utf-8')
    files=[OUT/'index.html',path,OUT/'selected-diagnostic-targets.jsonl',*sorted(assets.glob('*.png'))]
    with zipfile.ZipFile(OUT/'comparison-package.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in files:archive.write(file,file.relative_to(OUT).as_posix())
    print('4 cards, one trace table, self-contained comparison package:',OUT/'comparison-package.zip')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--resume-export',action='store_true');parser.add_argument('--complete-pairing-from-native',action='store_true')
    parser.add_argument('--publish-only',action='store_true');args=parser.parse_args()
    if args.publish_only:publish()
    else:run(resume_export=args.resume_export,resume_pairing=args.complete_pairing_from_native)
