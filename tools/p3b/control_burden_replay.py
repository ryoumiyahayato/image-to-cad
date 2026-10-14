"""Revalidate the saved sixteen; export a subset preview without filling slots."""

import argparse
import copy
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from control_targets import ControlContext
from new_page_preview import data_image, escaped, geometry_details, overlay, page_location
from preview_selection import select_preview_mode
from quality import inspect
from selection_targets import compound_carrier_burden


def run(saved, output):
    saved,output=Path(saved),Path(output)
    # Aggregate assessment already ran once. Recheck only the four original controls.
    result=json.loads((output/'run.json').read_text(encoding='utf-8'))
    with gzip.open(saved/'eligible-pool.jsonl.gz','rt',encoding='utf-8') as f:pool=list(map(json.loads,f))
    before=[json.loads(l) for l in (saved/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    old_run=json.loads((saved/'run.json').read_text(encoding='utf-8'))
    by_id={r['sample_id']:r for r in pool}
    ordinal={r['sample_id']:i for i,r in enumerate(before,1)}
    inputs=[copy.deepcopy(by_id[r['sample_id']]) for r in before]
    sources={u:np.array(Image.open(saved/'sources'/u/'source.png').convert('L'))
             for u in sorted({r['plan_unit'] for r in before})}
    for unit,gray in sources.items():
        context=ControlContext.from_saved_rows(gray,[r for r in pool if r['plan_unit']==unit])
        for row in inputs:
            if row['plan_unit']==unit and row['target_kind']=='CONTROL':
                evidence=context.assess(row['target_roi'])
                row['quality']=inspect(row,gray,require_directional_edge=True,control_evidence=evidence)
        del context
    for row in inputs:row['purpose']='development_candidate_replay'
    cfg={**old_run['selection']['configuration'],'require_control_validity':True}
    selected,_,selection=select_preview_mode(inputs,[],cfg,mode='development_replay')
    output.mkdir(exist_ok=True,parents=True)
    chosen={r['sample_id'] for r in selected}
    assert len(selected)<=len(before)
    assert all(r['candidate_geometry']==by_id[r['sample_id']]['candidate_geometry'] and
               r['target_roi']==by_id[r['sample_id']]['target_roi'] and
               r['source_bbox']==by_id[r['sample_id']]['source_bbox'] and r['label'] is None for r in selected)
    # Display/replay assertions for the known cases, never selection rules.
    assert before[8]['sample_id'] not in chosen and before[11]['sample_id'] not in chosen
    assert before[9]['sample_id'] in chosen and before[10]['sample_id'] in chosen
    assert before[3]['sample_id'] in chosen and before[13]['sample_id'] not in chosen
    summary_rows=[]
    for s,control in zip(old_run['statistics'],result['CONTROL_assessment']['rows']):
        unit=s['plan_unit'];nominations=s['nominated'];passing=dict(s['quality_pass'])
        passing['CONTROL']=control['separable_ink_candidate']
        final=Counter(r['target_kind'] for r in selected if r['plan_unit']==unit)
        summary_rows.append({'source':s['source'],'page':s['page'],'plan_unit':unit,
                'original_regional_nominations':nominations,'original_quality_pass':s['quality_pass'],
                'new_quality_candidate_counts':passing,'CONTROL_deferred_line':control['line_fragment'],
                'CONTROL_deferred_uncertain':control['uncertain_extent'],
                'same_target_dedup_original_pool':s['exact_target_dedup'],
                'previous_preview_count':4,'current_preview_count':sum(final.values()),
                'current_preview_kinds':dict(final),
                'ordinary':selection['ordinary_selected_per_page'].get(unit,0),
                'extra':selection['selected_difficult_per_page'].get(unit,0)})
    result.update(based_on=str(saved.resolve()),purpose='development_subset_replay_not_new_information',
                  PDF_render_repeated=False,LSD_detection_repeated=False,new_candidates_created=0,
                  count_before=len(before),count_after=len(selected),kind_counts=dict(Counter(r['target_kind'] for r in selected)),
                  statistics=summary_rows,changed_functions=['ControlContext.assess','quality.inspect',
                  'trial_sampling.build_trial_pool/regional_nominations','selection_difference/compound_carrier_burden',
                  'select_preview/select_preview_mode'],
                  limits=['full glyph/entity semantics unconfirmed','saved-parent LSD evidence only in this replay',
                          '32669 unchecked old pair combinations unchanged','normal historical exclusion default retained'],
                  ordinary=sum(selection['ordinary_selected_per_page'].values()),
                  extra=sum(selection['selected_difficult_per_page'].values()),labels_assigned=0,
                  extra_low_relevance_review=0)
    cases=[]
    for index in (8,11,9,10,3,13):
        row=next(r for r in inputs if r['sample_id']==before[index]['sample_id'])
        case={'old_item':index+1,'proposal':row['sample_id'],'retained':row['sample_id'] in chosen,
              'candidate_state':'retained_preview' if row['sample_id'] in chosen else 'deferred',
              'target_and_crop_unchanged':True,'label':None}
        if row['target_kind']=='CONTROL':case['control_evidence']=row['quality']['control_object_evidence']
        if index==13:case['burden_evidence']=compound_carrier_burden(row,[before[3]])
        cases.append(case)
    result['cases']=cases
    result['selection_rejections']=[{'proposal':d['proposal'],'reason':d.get('reason'),
        'deferred':True,'source_geometry_discarded':False,'label':None,
        'information_uncertainty':d.get('information_uncertainty')} for d in selection['decisions'] if d['outcome']=='rejected']
    (output/'manifest.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected),encoding='utf-8')
    (output/'run.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def pcs(c):return '/'.join(str(c.get(k,0)) for k in ('PAIR','SINGLE','CONTROL'))
    table='<table><caption>四页计数；三项顺序均为PAIR/SINGLE/CONTROL；当前预览只从原16项取子集</caption><thead><tr><th>来源／页</th><th>原区域提名</th><th>原质量通过</th><th>现候选条件通过</th><th>CONTROL暂缓<br>线证据／范围不明</th><th>同目标去重</th><th>预览前→后</th><th>当前普通＋额外</th></tr></thead><tbody>'
    for s in summary_rows:
        table+=f'<tr><td>{escaped(s["source"])}/{s["page"]}</td><td>{pcs(s["original_regional_nominations"])}</td><td>{pcs(s["original_quality_pass"])}</td><td>{pcs(s["new_quality_candidate_counts"])}</td><td>{s["CONTROL_deferred_line"]}/{s["CONTROL_deferred_uncertain"]}</td><td>{s["same_target_dedup_original_pool"]}</td><td>4→{s["current_preview_count"]}</td><td>{s["ordinary"]}+{s["extra"]}</td></tr>'
    table+='</tbody></table><p>当前候选条件通过数量包含可分离二维墨迹；不是完整字符/工程对象认证。原始提名数、原同目标去重0保留，暂缓和区域名额不改称目标去重。</p>'
    text={
        9:'前：仅凭9个墨迹像素通过。后：沿同一方向有7个相似片段，间隔11px。暂缓CONTROL；不补成字符，不赋类别。',
        12:'前：232个墨迹像素通过。后：与两条保存的长线边缘重合约99.1%/100%。当前范围为线载体片段，暂缓CONTROL。',
        10:'保留。阈值连通范围7×12px完整，墨迹有二维展开，没有长线重合证据。可作为对象候选；Z只是既有指向观察，不是本轮OCR输出。',
        11:'保留。阈值连通范围7×10px完整，墨迹有二维展开，没有长线重合证据。可作为对象候选；F只是既有指向观察，不是本轮OCR输出。',
        4:'原PAIR保留，端点与源像素不改。A/B两条边缘可定位；不据此自动判一条或两条。',
        14:'第三条细线有独立墨迹，与原PAIR不是相同目标。裁框IoU=0.765，完整目标已经在原04裁框内，平行共同投影约86.1%。没有新增节点、开口或需要再标的关系证据，因此暂缓额外呈现；没有合并或删除源边界。'}
    compare='<h2>六项修正前后</h2><div class="examples">'
    for case in cases:
        row=next(r for r in inputs if r['sample_id']==case['proposal']);im=Image.fromarray(sources[row['plan_unit']])
        x,y,w,h=row['source_bbox'];raw=data_image(im.crop((x,y,x+w,y+h)))
        compare+=f'<section><h3>原第{case["old_item"]:02}项 · {"保留" if case["retained"] else "暂缓"}</h3><p>{escaped(row["sample_id"])}</p>{overlay(row,raw)}<p>{text[case["old_item"]]}</p></section>'
    compare+='</div><p>04/14同一源区域：上图原像素显示放大，下图仅叠加位置；红/蓝为04，绿为14。放大不增加源信息。</p>'
    compare+=f'<img style="width:100%;height:auto" alt="04与14原灰度及三成员同位置对照" src="{data_image(Image.open(output/"carrier-check.png"))}">'
    defs=[];cards=[]
    for unit,gray in sources.items():
        page=Image.open(saved/'sources'/unit/'page-view.png').convert('L')
        defs.append(f'<image id="page-{unit}" href="{data_image(page)}" width="{gray.shape[1]}" height="{gray.shape[0]}" preserveAspectRatio="none"/>')
    for n,row in enumerate(selected,1):
        im=Image.fromarray(sources[row['plan_unit']]);x,y,w,h=row['source_bbox'];raw=data_image(im.crop((x,y,x+w,y+h)))
        context=im.crop((max(0,x-160),max(0,y-160),min(im.width,x+w+160),min(im.height,y+h+160)))
        layer='<button data-layer="none">原图</button><button data-layer="all">提名叠加</button>'
        if row['candidate_geometry']:layer+='<button data-layer="A">只看A</button>'
        if len(row['candidate_geometry'])==2:layer+='<button data-layer="B">只看B</button>'
        reason='<li>'+'</li><li>'.join(escaped(v) for v in row['retain_reasons'])+'</li>'
        cards.append(f'''<article data-mode="all"><h2>原第{ordinal[row['sample_id']]:02}项 · 当前{n}/{len(selected)}　{escaped(row['sample_id'])}</h2>
<p>{escaped(row['source_drawing_id'])} / 第{row['source_page']}页 · {escaped(row['source_family_id'])} · {escaped(row['region_id'])}<br>{'额外名额' if row.get('difficult_addition') else '普通名额'}；提名形式{row['target_kind']}，不是人工类别。</p>
<div class="images"><figure>{page_location(row,im,row['plan_unit'])}<figcaption>整页与当前裁框</figcaption></figure><figure><img class="context" src="{data_image(context)}" alt="无标记上下文"><figcaption>无叠加上下文</figcaption></figure><figure><img class="raw" src="{raw}" alt="原始灰度裁块"><figcaption>原灰度裁块，未改像素</figcaption></figure><figure><div>{layer}<select aria-label="显示缩放"><option value="1">显示1倍</option><option value="2" selected>显示2倍</option><option value="3">显示3倍</option></select></div><div class="zoom">{overlay(row,raw)}</div><figcaption>{'区域目标，无A/B成员' if row['target_kind']=='CONTROL' else 'A1/A2/B1/B2仅为端点编号，没有流向含义'}</figcaption></figure></div>
<details><summary>来源、成员及保留依据</summary><p>{escaped(row['source_relative_path'])}<br>源栅格DPI={row['source_dpi']:.3f}；现有划分={escaped(row['source_existing_split'])}</p><p>{geometry_details(row)}</p><ul>{reason}</ul><p>仅开发回放，历史接触已知。普通选样仍默认历史排除。本页没有新人工类别。</p></details></article>''')
    old_html=(saved/'index.html').read_text(encoding='utf-8')
    css=re.search(r'<style>(.*?)</style>',old_html,re.S).group(1)
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B CONTROL与展示负担修复预览</title><style>'+css+'</style><main>'
    document+=f'<header><h1>CONTROL与复合线区域展示负担修复</h1><p>原16项→当前{len(selected)}项：{pcs(result["kind_counts"])}。原编号保留，有缺口。没有补入其他候选，没有重渲染PDF或重跑LSD。</p><p>源像素、原目标及裁框不改。暂缓是提名/信息依据不足，不是人工OTHER或AMBIGUOUS。PAIR/SINGLE定义不变；01/02近距离两侧和03分离边界只作观察，不自动赋类别。</p></header>'
    document+=f'<div class="summary">{table}<p>CONTROL修正接入正常显式选页质量入口；本轮只回放已保存候选。可分离墨迹不能证明完整字形或语义。孤立的一、减号、下划线不能凭宽高比判无效；缺对应依据时保留范围不确定。</p><p>复合载体规则只限制自动额外展示，不负责合并边界或重建墙体。有独立节点/开口等明确证据时，已有困难差异机制仍可使用。第14项第三条墨迹确实存在，但当前不能证明独立工程边界或再次标注收益。</p><p>原32669个配对组合未检查，召回覆盖仍未知。原验证/盲测划分不动。没有训练、标注、OCR、生产几何修改或后台任务。</p></div>'
    document+=compare+f'<h2>当前13项修复预览</h2><svg width="0" height="0" aria-hidden="true"><defs>{"".join(defs)}</defs></svg>'+''.join(cards)
    document+='''<p>停在修复预览，等待查看；无标注按钮或保存答案入口。</p></main><script>
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>b.closest('article').dataset.mode=b.dataset.layer));
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',()=>s.closest('figure').querySelector('.target').style.width=(256*Number(s.value))+'px'));
</script></html>'''
    (output/'index.html').write_text(document,encoding='utf-8')
    print(json.dumps({'HTML':str((output/'index.html').resolve()),'count':len(selected),
                      'ordinary':result['ordinary'],'extra':result['extra'],
                      'CONTROL_scope':'four existing controls; aggregate 1370 assessment reused',
                      'no_replacement_candidates':True},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('saved',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();run(args.saved,args.output)
