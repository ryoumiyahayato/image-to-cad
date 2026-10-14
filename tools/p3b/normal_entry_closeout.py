"""Normal selection on the entire saved pool plus one explicit new PDF page."""

import argparse
import copy
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from common import ROOT, read, read_rows, write_rows
from control_targets import ControlContext
from extract import run as extract_run
from inventory import planned_sources
from new_page_preview import data_image, escaped, geometry_details, overlay, page_location
from preview_selection import iou, same_page, select_preview_mode
from quality import ink_distance, inspect
from selection_targets import same_observed_target
from trial_sampling import append_preview_history, load_history


def compact_selection(selection):
    return {k:v for k,v in selection.items() if k not in ('decisions',)}


def stable_against_permutation(rows,history,configuration,chosen):
    alternative,_,_=select_preview_mode(copy.deepcopy(list(reversed(rows))),history,
                                       {**configuration,'record_decisions':False})
    return (len(alternative)==len(chosen) and all(any(same_observed_target(r,a) and
                r['display_crop_box']==a['display_crop_box'] for a in alternative) for r in chosen))


def reselect_with_recorded_context(output):
    """Only selection after fixing the observed history-context ingestion omission."""
    output=Path(output);saved=ROOT/'local-artifacts/product-fix-p3b/new-page-trial-20261011-001'
    result=read(output/'run.json');plan=read(saved/'page-plan.json');new_plan=read(output/'new-page-plan.json')
    supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json')
    sources=planned_sources({'rows':plan['rows']+new_plan['rows']},supplement)
    history,_=load_history(plan,sources)
    for directory,round_name in [('preview-trial-20261010-001','previous20_preview'),
                                 ('selection-fix-20261011-001','local_repair_preview'),
                                 ('new-page-trial-20261011-001','previous16_development_preview')]:
        path=ROOT/'local-artifacts/product-fix-p3b'/directory/'manifest.jsonl'
        if not path.is_file() and directory.startswith('selection-fix'):path=path.parent/'selected-diagnostic-targets.jsonl'
        append_preview_history(history,path,round_name)
    with gzip.open(output/'four-page-quality-pool.jsonl.gz','rt',encoding='utf-8') as f:rows=list(map(json.loads,f))
    cfg=result['selection']['configuration']
    chosen,_,selection=select_preview_mode(copy.deepcopy(rows),history,cfg)
    stable=stable_against_permutation(rows,history,cfg,chosen);assert stable
    existing=read_rows(output/'manifest.jsonl');new_chosen=[r for r in existing if r['plan_unit']=='OBS-05']
    before=[r for r in existing if r['plan_unit']!='OBS-05']
    decisions={d['proposal']:d for d in selection['decisions']};by_id={r['sample_id']:r for r in rows}
    for s in result['statistics']:
        if s['plan_unit']=='OBS-05':continue
        unit=s['plan_unit'];picked=[r for r in chosen if r['plan_unit']==unit]
        counts=Counter(d.get('reason') for d in selection['decisions'] if d['outcome']=='rejected' and by_id[d['proposal']]['plan_unit']==unit)
        s.update(selection_rejections=dict(counts),same_target_dedup=sum(v for k,v in counts.items() if k in ('same_target','same_target_representative')),
             selected=dict(Counter(r['target_kind'] for r in picked)),final_count=len(picked),
             ordinary=selection['ordinary_selected_per_page'].get(unit,0),extra=selection['selected_difficult_per_page'].get(unit,0))
    for item in result['known_previous16']:
        d=decisions.get(item['proposal']);item['selection_reason']=d.get('reason') if d else 'quality_deferred'
        item['selected']=any(r['sample_id']==item['proposal'] for r in chosen)
    for row in chosen:row['purpose']='normal_sampling_development_preview';row['training_authorized']=False
    write_rows(output/'manifest.jsonl',chosen+new_chosen)
    result['selection']=compact_selection(selection)
    result['selection_stable_under_input_permutation']=stable
    result['history_context_count']=sum(bool(r.get('display_context_box')) for r in history)
    result['bounded_fix']={'function':'append_preview_history',
        'defect':'retained preview context bounds in run.json omitted when ingesting manifest history',
        'action':'consume recorded context bounds with existing source-frame mapping',
        'thresholds_changed':False,'quality_or_detection_repeated':False,
        'four_page_count_before':len(before),'four_page_count_after':len(chosen)}
    (output/'run.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'history_context_count':result['history_context_count'],'four_page_final':len(chosen),
                      'new_page_final':len(new_chosen),'statistics':result['statistics']},ensure_ascii=False))


def run(output):
    output=Path(output);saved=ROOT/'local-artifacts/product-fix-p3b/new-page-trial-20261011-001'
    supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json')
    base_plan=read(saved/'page-plan.json');new_plan=read(output/'new-page-plan.json')
    old_run=read(saved/'run.json');before=read_rows(saved/'manifest.jsonl')
    # The thirteen-subset manifest is never an input to quality or selection.
    with gzip.open(saved/'eligible-pool.jsonl.gz','rt',encoding='utf-8') as f:
        pool=list(map(json.loads,f))
    qualified=[];statistics=[];known={r['sample_id']:i for i,r in enumerate(before,1)};known_quality={}
    for unit in base_plan['rows']:
        name=unit['plan_unit'];page_rows=[copy.deepcopy(r) for r in pool if r['plan_unit']==name]
        gray=np.array(Image.open(saved/'sources'/name/'source.png').convert('L'))
        distance=ink_distance(gray);context=ControlContext.from_saved_rows(gray,page_rows)
        passing=Counter();held=Counter();control_states=Counter();known_old_failure=0
        for row in page_rows:
            evidence=context.assess(row['target_roi']) if row['target_kind']=='CONTROL' else None
            old_quality=row['quality']
            row['quality']=inspect(row,gray,distance,require_directional_edge=True,control_evidence=evidence)
            if evidence:control_states[evidence['status']]+=1
            if row['sample_id'] in known:
                known_quality[row['sample_id']]={'old_item':known[row['sample_id']],
                     'quality_pass':row['quality']['HUMAN_QUEUE_ELIGIBLE'],
                     'quality_reasons':row['quality']['rejection_reasons'],
                     'control_evidence':evidence}
            if row['target_kind']!='CONTROL':
                assert row['quality']['metrics']==old_quality['metrics']
                assert row['quality']['rejection_reasons']==old_quality['rejection_reasons']
            if row['quality']['HUMAN_QUEUE_ELIGIBLE']:
                passing[row['target_kind']]+=1;qualified.append(row)
            else:held[row['target_kind']]+=1
        prior=next(s for s in old_run['statistics'] if s['plan_unit']==name)
        statistics.append({'plan_unit':name,'source':prior['source'],'page':prior['page'],
             'original_nominations':prior['nominated'],'quality_rechecked':dict(Counter(r['target_kind'] for r in page_rows)),
             'old_quality_rejected_geometry_not_saved':sum(prior['nominated'].values())-len(page_rows),
             'quality_pass':dict(passing),'quality_deferred_this_run':dict(held),
             'CONTROL_states':dict(control_states)})
        print(f'{name}: rechecked {len(page_rows)}, pass {sum(passing.values())}, deferred {sum(held.values())}',flush=True)
        del context,distance,gray
    sources=planned_sources({'rows':base_plan['rows']+new_plan['rows']},supplement)
    history,history_summary=load_history(base_plan,sources)
    for directory,round_name in [('preview-trial-20261010-001','previous20_preview'),
                                 ('selection-fix-20261011-001','local_repair_preview'),
                                 ('new-page-trial-20261011-001','previous16_development_preview')]:
        path=ROOT/'local-artifacts/product-fix-p3b'/directory/'manifest.jsonl'
        # Selection repair stores its targets under this retained name.
        if not path.is_file() and directory.startswith('selection-fix'):
            path=path.parent/'selected-diagnostic-targets.jsonl'
        append_preview_history(history,path,round_name)
    cfg={**old_run['selection']['configuration'],'require_control_validity':True}
    chosen,_,selection=select_preview_mode(copy.deepcopy(qualified),history,cfg)
    stable=stable_against_permutation(qualified,history,cfg,chosen)
    assert stable
    decisions={d['proposal']:d for d in selection['decisions']}
    for s in statistics:
        name=s['plan_unit'];final=[r for r in chosen if r['plan_unit']==name]
        rejected=Counter(d.get('reason') for d in selection['decisions']
                         if d['outcome']=='rejected' and next(r for r in qualified if r['sample_id']==d['proposal'])['plan_unit']==name)
        s.update(selection_rejections=dict(rejected),same_target_dedup=sum(v for k,v in rejected.items() if k in ('same_target','same_target_representative')),
                 selected=dict(Counter(r['target_kind'] for r in final)),final_count=len(final),
                 ordinary=selection['ordinary_selected_per_page'].get(name,0),extra=selection['selected_difficult_per_page'].get(name,0))
    known_trace=[]
    for row in before:
        sid=row['sample_id'];decision=decisions.get(sid)
        known_trace.append({'proposal':sid,**known_quality[sid],
                 'selection_reason':decision.get('reason') if decision else 'quality_deferred',
                 'selected':any(r['sample_id']==sid for r in chosen)})
    print('four-page normal selected',len(chosen),'stable',stable,flush=True)
    new_pool,pages,summaries=extract_run(None,None,output,page_plan=new_plan,supplement=supplement)
    new_cfg={**cfg,'max_total':4,'max_design':4}
    new_chosen,_,new_selection=select_preview_mode(copy.deepcopy(new_pool),history,new_cfg)
    new_stable=stable_against_permutation(new_pool,history,new_cfg,new_chosen)
    assert new_stable
    ns=summaries[0];new_name=ns['plan_unit'];new_unit=pages[new_name]['unit']
    statistics.append({'plan_unit':new_name,'source':new_unit['source_drawing_id'],'page':13,
       'original_nominations':ns['regional_nomination_kind_counts'],'quality_rechecked':ns['regional_nomination_kind_counts'],
       'old_quality_rejected_geometry_not_saved':0,'quality_pass':ns['quality_pass_kind_counts'],
       'CONTROL_states':ns['control_validity_counts'],
       'quality_deferred_this_run':{k:ns['regional_nomination_kind_counts'].get(k,0)-ns['quality_pass_kind_counts'].get(k,0) for k in ('PAIR','SINGLE','CONTROL')},
       'selection_rejections':new_selection['decision_counts'],
       'same_target_dedup':sum(v for k,v in new_selection['decision_counts'].items() if k in ('same_target','same_target_representative')),
       'selected':dict(Counter(r['target_kind'] for r in new_chosen)),'final_count':len(new_chosen),
       'ordinary':new_selection['ordinary_selected_per_page'].get(new_name,0),'extra':new_selection['selected_difficult_per_page'].get(new_name,0)})
    all_chosen=chosen+new_chosen
    for row in all_chosen:
        row['purpose']='normal_sampling_development_preview';row['training_authorized']=False
        assert row['label'] is None
    write_rows(output/'manifest.jsonl',all_chosen)
    for name,values in [('four-page-quality-pool.jsonl.gz',qualified),('new-page-quality-pool.jsonl.gz',new_pool)]:
        with gzip.open(output/name,'wt',encoding='utf-8') as f:
            for row in values:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    # No per-rejection diagnostic JSON. Aggregate counts plus the sixteen old target outcomes.
    result={'purpose':'normal-entry-closeout-development-preview','statistics':statistics,'known_previous16':known_trace,
            'selection':compact_selection(selection),'new_page_selection':compact_selection(new_selection),
            'history_positions':len(history),'history_summary':history_summary,
            'history_cutoff':'current prior preview16 included as development exposure; no claim of recorded user click events',
            'four_page_detection_repeated':False,'four_page_quality_scope':len(pool),
            'four_page_original_nomination_count':sum(sum(s['nominated'].values()) for s in old_run['statistics']),
            'prior_rejected_geometry_not_obtained':sum(s['old_quality_rejected_geometry_not_saved'] for s in statistics),
            'normal_history_exclusion_applied':True,'selection_stable_under_input_permutation':stable,
            'new_page_selection_stable_under_input_permutation':new_stable,
            'new_page_generation_summary':{k:v for k,v in ns.items() if k not in ('quality_examples','diagnostic_reference_matches')},
            'labels_assigned':0,'annotation_UI_started':False,'training_started':False,'extra_low_relevance_review':0}
    (output/'run.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'new-page-plan.json').write_text(json.dumps(new_plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'four_page_final':len(chosen),'new_page_final':len(new_chosen),
                      'old_target_outcomes':[r for r in known_trace if r['old_item'] in (9,10,11,12,14)],
                      'statistics':statistics},ensure_ascii=False),flush=True)


def export(output):
    """One self-contained observation HTML, including actual unresolved outputs."""
    output=Path(output);saved=ROOT/'local-artifacts/product-fix-p3b/new-page-trial-20261011-001'
    result=read(output/'run.json');rows=read_rows(output/'manifest.jsonl')
    old=read_rows(saved/'manifest.jsonl');by_id={r['sample_id']:r for r in rows}
    images={u:Image.open(output/'new-page-source.png' if u=='OBS-05' else saved/'sources'/u/'source.png').convert('L')
            for u in {r['plan_unit'] for r in rows}}
    def pcs(v):return '/'.join(str(v.get(k,0)) for k in ('PAIR','SINGLE','CONTROL'))
    def totals(s):
        rejection=s['selection_rejections']
        history=sum(v for k,v in rejection.items() if k.startswith('historical_'))
        quota=sum(v for k,v in rejection.items() if not k.startswith('historical_') and k not in ('same_target','same_target_representative'))
        return history,quota
    table='<table><caption>三项顺序均为PAIR/SINGLE/CONTROL；通过与暂缓都是候选条件，不是人工类别或错误率</caption><thead><tr><th>来源／页</th><th>实际提名</th><th>本轮质量重检</th><th>质量通过</th><th>本轮质量暂缓/不通过</th><th>历史排除</th><th>区域/名额排除</th><th>本批同目标去重</th><th>最终P/S/C</th><th>普通＋额外</th></tr></thead><tbody>'
    for s in result['statistics']:
        hist,quota=totals(s)
        table+=f'<tr><td>{escaped(s["source"])}/{s["page"]}</td><td>{pcs(s["original_nominations"])}</td><td>{pcs(s["quality_rechecked"])}</td><td>{pcs(s["quality_pass"])}</td><td>{pcs(s["quality_deferred_this_run"])}</td><td>{hist}</td><td>{quota}</td><td>{s["same_target_dedup"]}</td><td>{pcs(s["selected"])}</td><td>{s["ordinary"]}+{s["extra"]}</td></tr>'
    table+='</tbody></table><p>原四页4078项提名中，1240项旧质量拒绝的完整几何未取得；本轮从全部2838项保存候选重检，2159项通过、679个CONTROL暂缓。新页621项实际提名、127项通过。不能把历史或区域排除改称同目标去重。</p>'
    known='<table><caption>前16项的相关去向；当前历史包括前16项预览及其已记录上下文</caption><thead><tr><th>旧项</th><th>本轮质量</th><th>正常选择</th><th>含义</th></tr></thead><tbody>'
    for item in result['known_previous16']:
        if item['old_item'] not in (9,10,11,12,14):continue
        meaning='线片段依据成立，质量暂缓，不生成OTHER标签' if not item['quality_pass'] else '质量仍通过；因已有历史接触排除，不能当作无效对象'
        known+=f'<tr><td>{item["old_item"]:02}</td><td>{"通过" if item["quality_pass"] else "暂缓"}</td><td>{escaped(item["selection_reason"])}</td><td>{meaning}</td></tr>'
    known+='</tbody></table><p>四页16个最终提名均为原保存池中的其他目标，未读取13项子集来决定结果。替补不与09/12/14一一对应：先满足当前历史与地域约束，再轮转选择。没有强制保留每页CONTROL。</p>'
    findings=[
        {'proposal':'proposal-NEW-01-000416','issue':'CONTROL_false_object_extent',
         'observation':'提名框指向虚线矩形折角。转折使墨迹呈二维形态，仍被当作可分离墨迹候选；这不能证明独立字符/符号对象。'},
        {'proposal':'proposal-NEW-04-000857','related':'proposal-NEW-04-000856','issue':'redundant_extra_context',
         'observation':'标题下划线的两侧被分别作为SINGLE呈现。裁框IoU约0.954；普通项只有一个成员，现复合规则只从两成员带判断，自动额外机会仍能绕过。'},
        {'proposal':'proposal-NEW-01-001440','related':'proposal-NEW-01-001439','issue':'same_fill_region_burden',
         'observation':'同一填充区域的相邻斜线再次呈现。载体不同不证明填充区内的新判断价值；没有赋人工类别。'},
        {'proposal':'proposal-OBS-05-000589','related':'proposal-OBS-05-000579','issue':'new_page_parallel_band_burden',
         'observation':'新页两项位于相近平行带，裁框IoU约0.877。可能存在不同真实边缘，但再次呈现的收益尚未证明，不能仅凭新成员ID和源支持声明新信息。'},
        {'proposal':'proposal-OBS-05-000430','issue':'CONTROL_glyph_extent_unconfirmed',
         'observation':'新页CONTROL只确认7×5px连通墨迹范围；原像素下无法确认它独占完整文字或符号。'}]
    for f in findings:
        if f.get('related'):f['crop_iou']=iou(by_id[f['proposal']]['display_crop_box'],by_id[f['related']]['display_crop_box'])
    notes={f['proposal']:f['observation'] for f in findings}
    for f in findings:
        if f.get('related'):notes[f['related']]=f['observation']
    result['P3B_SAMPLING_STATUS']='PARTIALLY_READY'
    result['substantive_findings']=findings
    result['review_scope']='observation only; retained output is not a hard-label-ready set'
    result['PAIR_SINGLE_quality_unchanged_on_all_saved_line_candidates']=True
    result['replacement_count_four_pages']=sum(r['plan_unit']!='OBS-05' and r['sample_id'] not in {o['sample_id'] for o in old} for r in rows)
    css=re.search(r'<style>(.*?)</style>',(saved/'index.html').read_text(encoding='utf-8'),re.S).group(1)
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B 正常入口阶段收口</title><style>'+css+'</style><main>'
    document+='''<header><h1>P3B 正常取样入口复核</h1><p><strong>P3B_SAMPLING_STATUS: PARTIALLY_READY</strong></p>
<p>原四页正常函数输出16项＋独立新页4项，共20项。当前保留表示选择器实际输出，不等于对象语义合格。本页只供检查，无标注、保存答案或训练功能。</p>
<p>质量→同目标代表→历史/跨类型区域→页/区域/长线名额→有限额外→最终预览。此前16项的已记录裁框和上下文均进入历史；没有推断用户点击事件。旧94/50、人工回答、模型、生产DXF/OCR保持原状。</p></header>'''
    document+=f'<div class="summary">{table}{known}<p>唯一有界修正：原历史接入漏读run.json里的上下文框。现在由trial_sampling.load_history读取显式preview_history_manifests，并按记录帧换算；16个上下文已接入。修正后只重跑受影响的选择，质量和检测未重跑，阈值未变。</p>'
    document+='''<p>正常执行和输入顺序稳定性成立；已知直线/虚线片段不再通过。剩余实质问题是：二维虚线折角仍可进入CONTROL；SINGLE起点的重复边缘和填充区仍能获得额外机会。因此不能收口为所有候选可直接硬标。</p>
<p>有效文字/符号是否过排尚未证明：旧Z/F质量仍通过，只因已看历史排除；一、减号、下划线及断开的字内墨迹仍可能落入范围不确定。暂缓不表示这些内容在最终产品应被删除。</p>
<p>独立边界没有被合并或改动；几何合格对象仍会被历史/展示名额限制，不能宣称没有压掉有价值的新关系。新页17项的两边界仍保留，当前没有人工语义真值支持整体误抑制率结论。</p>
<p>原32669个未检查配对组合保持原状，不作完整召回声明。四页重检仅利用保存的父LSD证据；新页使用该页真实LSD结果。坐标一致、墨迹覆盖和二维形态均不能替代对象语义。</p></div>'''
    document+='<h2>本轮发现的实质问题</h2><ul>'+''.join(f'<li>{escaped(f["proposal"])}：{escaped(f["observation"])}</li>' for f in findings)+'</ul>'
    document+='<div class="summary"><h2>独立新页</h2><p>0026_20260601.pdf 第13页，コンセント設備3階平面図 / E-010；F07-SEYA-CULTURAL-CENTER-ELECTRICAL，现有划分尚未分配。登记历史为该文件11/12页，未取得13页已呈现目标；不是验证/盲测来源。该页单栅格图，原扫描仪DPI未取得。实际110DPI渲染1821×1288进入检测；781条检测长段，计划区域621项提名，127项质量通过，最终4项。本页没有训练/验证标签。</p></div>'
    defs=[]
    for unit,im in images.items():
        preview=Image.open(output/'new-page-view.png' if unit=='OBS-05' else saved/'sources'/unit/'page-view.png').convert('L')
        defs.append(f'<image id="page-{unit}" href="{data_image(preview)}" width="{im.width}" height="{im.height}" preserveAspectRatio="none"/>')
    document+=f'<svg width="0" height="0" aria-hidden="true"><defs>{"".join(defs)}</defs></svg>'
    checks=[]
    for n,row in enumerate(rows,1):
        im=images[row['plan_unit']];x,y,w,h=row['source_bbox'];raw=im.crop((x,y,x+w,y+h));url=data_image(raw)
        assert list(im.size)==row['coordinate_frame']['render_size_px']
        assert 0<=x<x+w<=im.width and 0<=y<y+h<=im.height
        for _,g,_ in row['candidate_geometry']:
            assert all(x<=g[i]<=x+w and y<=g[i+1]<=y+h for i in (0,2))
        context=im.crop((max(0,x-160),max(0,y-160),min(im.width,x+w+160),min(im.height,y+h+160)))
        layer='<button data-layer="none">原图</button><button data-layer="all">提名叠加</button>'
        if row['candidate_geometry']:layer+='<button data-layer="A">只看A</button>'
        if len(row['candidate_geometry'])==2:layer+='<button data-layer="B">只看B</button>'
        overlap=[f'{r["sample_id"]} IoU={iou(row["display_crop_box"],r["display_crop_box"]):.3f}' for r in rows
                 if r is not row and same_page(row,r) and iou(row['display_crop_box'],r['display_crop_box'])>0]
        note=notes.get(row['sample_id'],'源墨迹可定位，工程对象归属和人工类别未确认。')
        if row['target_kind']=='CONTROL':
            e=row['quality']['control_object_evidence']
            reason=[f'阈值连通范围与当前框一致，源墨迹{e["component_ink_pixels"]}像素；二维展开仅为候选证据',
                    '未识别OCR内容，未认证完整字形或工程对象；不赋OTHER类别',
                    '当前历史/区域/名额条件通过，不表示人工回答或对象真值']
        else:reason=row['retain_reasons']
        if row.get('difficult_addition'):reason=reason+['额外只使用几何代理；object_relation不是建筑对象/结构节点识别。具体重复负担见本卡观察。']
        document+=f'''<article data-mode="all"><h2>当前第{n:02}项 / {len(rows)}　{escaped(row['sample_id'])}</h2>
<p>{escaped(row['source_drawing_id'])} / 第{row['source_page']}页 · {escaped(row['source_family_id'])} · {escaped(row['region_id'])}<br>{'额外机会' if row.get('difficult_addition') else '普通名额'}；提名形式{row['target_kind']}，不是人工类别。</p><p class="note">{escaped(note)}</p>
<div class="images"><figure>{page_location(row,im,row['plan_unit'])}<figcaption>整页与当前最终裁框</figcaption></figure><figure><img class="context" src="{data_image(context)}" alt="无叠加上下文"><figcaption>无叠加上下文，裁框外扩160源像素</figcaption></figure><figure><img class="raw" src="{url}" alt="原始灰度裁块"><figcaption>原灰度裁块，未改变源像素</figcaption></figure><figure><div>{layer}<select aria-label="显示缩放"><option value="1">显示1倍</option><option value="2" selected>显示2倍</option><option value="3">显示3倍</option></select></div><div class="zoom">{overlay(row,url)}</div><figcaption>{'区域目标，无A/B成员' if row['target_kind']=='CONTROL' else '端点A1/A2/B1/B2仅为位置编号，无流向含义'}；显示放大不增加原信息。</figcaption></figure></div>
<details><summary>来源、成员、当前坐标与实际保留依据</summary><p>{escaped(row['source_relative_path'])}<br>有效DPI={row['source_dpi']:.3f}；原划分={escaped(row['source_existing_split'])}；当前仅开发观察，类别为空。</p><p>{geometry_details(row)}</p><ul>{''.join('<li>'+escaped(v)+'</li>' for v in reason)}</ul><p>本批裁框相交：{escaped('；'.join(overlap) or '无')}。相交不等于完全相同目标。</p><p>历史排除已执行；事件日志不完整及语义未知限制仍保留。该来源无同图同版坐标配准CAD参与真值。</p></details></article>'''
        checks.append({'proposal':row['sample_id'],'source_frame_and_crop_bounds':True,'target_points_in_original_crop':True})
    document+='''<p>阶段已收口到本次观察结果。后续是否开始人工标注由用户决定；当前不启动标注、训练或下一批。</p></main><script>
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>b.closest('article').dataset.mode=b.dataset.layer));
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',()=>s.closest('figure').querySelector('.target').style.width=(256*Number(s.value))+'px'));
</script></html>'''
    (output/'index.html').write_text(document,encoding='utf-8')
    result['preview_local_checks']=checks
    (output/'run.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'HTML':str((output/'index.html').resolve()),'count':len(rows),
                     'status':result['P3B_SAMPLING_STATUS'],'kind_counts':dict(Counter(r['target_kind'] for r in rows))},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    parser.add_argument('--reselect-recorded-context',action='store_true')
    parser.add_argument('--export-only',action='store_true')
    args=parser.parse_args()
    (export if args.export_only else reselect_with_recorded_context if args.reselect_recorded_context else run)(args.output)
