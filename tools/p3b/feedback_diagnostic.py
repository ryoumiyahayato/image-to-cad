"""Bounded same-location feedback diagnostics. Never labels or trains targets."""

import copy
import ctypes
import json
import math
import argparse
import html
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image

from common import ROOT,read,read_rows,atomic_json,write_rows
from inventory import build as inventory_build
from trial_sampling import render_explicit,device_to_pdf,to_pdf,pixel_center_to_pdf,pdf_to_pixel_center
from target_view import target_overlay
from measurement import SourceWindow,measure_row
from quality import inspect,ink_distance,edge_attachment,sample_line,pair_metrics

BASE=ROOT/"local-artifacts/product-fix-p3b/preview-trial-20261010-001"
OUT=ROOT/"local-artifacts/product-fix-p3b/feedback-fix-20261010-001"


def inverse_frame(point,frame):
    matrix=np.column_stack((frame["pdf_x_per_pixel"],frame["pdf_y_per_pixel"]))
    return np.linalg.solve(matrix,np.array(point)-frame["pdf_origin"]).tolist()


def render_window(row,box,dpi=320):
    """Real PDF local render, with actual bitmap offsets after crop rounding."""
    with pdfium.PdfDocument(row["source_path"]) as doc:
        page=doc[row["source_page"]-1]
        try:
            pw,ph=page.get_size();scale=dpi/72;size=[math.ceil(pw*scale),math.ceil(ph*scale)]
            p0=np.array(device_to_pdf(page,size,[0,0]));px=np.array(device_to_pdf(page,size,[size[0],0]));py=np.array(device_to_pdf(page,size,[0,size[1]]))
            frame={"page_size_points":[pw,ph],"render_size_px":size,"effective_dpi":dpi,
                "page_rotation":page.get_rotation(),"pdf_origin":p0.tolist(),
                "pdf_x_per_pixel":((px-p0)/size[0]).tolist(),"pdf_y_per_pixel":((py-p0)/size[1]).tolist(),
                "media_box_pdf":list(page.get_mediabox()),"crop_box_pdf":list(page.get_cropbox())}
            x,y,w,h=box
            corners=[inverse_frame(to_pdf(p,row["coordinate_frame"]),frame) for p in ([x,y],[x+w,y],[x,y+h],[x+w,y+h])]
            left,top=np.floor(np.min(corners,axis=0)).astype(int);right,bottom=np.ceil(np.max(corners,axis=0)).astype(int)
            left,top=max(0,left),max(0,top);right,bottom=min(size[0],right),min(size[1],bottom)
            bitmap=page.render(scale=scale,crop=(left/scale,(size[1]-bottom)/scale,(size[0]-right)/scale,top/scale),grayscale=True)
            try:
                gray=np.array(bitmap.to_pil().convert("L"))
                args=bitmap._render_args[1]
                origin=[-args[0],-args[1]]
            finally:bitmap.close()
            revision=copy.deepcopy(row)
            revision["sample_id"]="diagnostic-"+row["sample_id"]
            revision["original_sample_id"]=row["sample_id"]
            revision["candidate_geometry"]=[[g[0],sum([pdf_to_pixel_center(pixel_center_to_pdf(g[1][k:k+2],row["coordinate_frame"]),frame) for k in (0,2)],[]),g[2]] for g in row["candidate_geometry"]]
            if row.get("target_roi"):
                tx,ty,tw,th=row["target_roi"]
                aa=inverse_frame(to_pdf([tx,ty],row["coordinate_frame"]),frame)
                bb=inverse_frame(to_pdf([tx+tw,ty+th],row["coordinate_frame"]),frame)
                revision["target_roi"]=[*aa,bb[0]-aa[0],bb[1]-aa[1]]
            revision.update(source_bbox=[*origin,gray.shape[1],gray.shape[0]],coordinate_frame=frame,
                source_dpi=dpi,label=None,label_provenance=None,training_authorized=False,
                purpose="same_location_diagnostic_not_new_sample",human_answer_inherited=False)
            measure_row(revision,SourceWindow(gray,origin,size))
            types=Counter()
            for obj in page.get_objects():types[str(obj.type)]+=1
            revision["source_page_object_types"]=dict(types)
            revision["native_window"]={"original_box_xywh":box,"actual_origin_full_raster_px":origin,
                "actual_window_size_px":[gray.shape[1],gray.shape[0]],"requested_dpi":dpi,
                "role":"source PDF local render; not 8x display or a new independent sample",
                "identity_limit":"affine mapping does not establish which source edge the old LSD target nominated"}
            return gray,revision
        finally:page.close()


def collect():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"issues.json").exists():raise ValueError("Feedback already read; do not overwrite or reread human answers")
    rows=read_rows(BASE/"manifest.jsonl");by_id={r["sample_id"]:r for r in rows}
    answers=read(BASE/"trial-labels.json")
    issues=[{"original_sample_id":r["sample_id"],"original_response":copy.deepcopy(answers["answers"][r["sample_id"]]),
        "source":{k:r[k] for k in ("source_path","source_page","source_bbox","candidate_geometry","target_roi")},
        "question":"待定向核对" if answers["answers"][r["sample_id"]].get("observation") or r["sample_id"] in ("preview-011",) else "无新增备注；保留为未独立核实的原回答",
        "reproduced":"尚未完成定向核对","correction":None,"remaining":None} for r in rows]
    record={"purpose":"feedback closure / same-location diagnostics, no new labeling or training",
        "answers_read":{"path":str(BASE/"trial-labels.json"),"processed":sum(a["processed"] for a in answers["answers"].values()),
            "statuses":dict(Counter(a["status"] for a in answers["answers"].values())),
            "categories":dict(Counter(a["category"] for a in answers["answers"].values() if a["category"])),
            "last_action":answers["history"][-1]["action"],"training_authorized":answers["training_authorized"],
            "note":"16 classified is persisted status, not independent label correctness; startup answer_created=false is irrelevant to completion"},
        "issues":issues,"original_answers_and_assets_changed":False,"replay":None}
    atomic_json(OUT/"issues.json",record)
    plan=copy.deepcopy(read(BASE/"plan.json"));supp=read(ROOT/"docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json")
    plan["rows"]=[u for u in plan["rows"] if u["plan_unit"] in ("TRIAL-04","TRIAL-02","TRIAL-05")]
    caches={}
    for unit in inventory_build(page_plan=plan,supplement=supp):
        folder=OUT/unit["plan_unit"].lower();folder.mkdir(exist_ok=True)
        gray,frame=render_explicit(unit)
        Image.fromarray(gray).save(folder/"source.png")
        atomic_json(folder/"frame.json",{"source_path":unit["resolved_path"],"source_page":unit["page_or_layout"]["page_number"],"frame":frame})
        caches[unit["plan_unit"]] = gray,frame
        print(unit["plan_unit"],"source",gray.shape,flush=True)
    diagnostic=[]
    for sid in ("preview-006","preview-010","preview-015","preview-018"):
        row=by_id[sid];folder=OUT/sid[-3:];folder.mkdir(exist_ok=True)
        full,frame=caches[row["plan_unit"]];x,y,w,h=row["source_bbox"]
        with Image.open(BASE/row["preview_files"]["crop"]) as im:original=np.array(im.convert("L"))
        row["original_crop_matches_real_same_frame_render"]=bool(np.array_equal(original,full[y:y+h,x:x+w]))
        box=row["source_bbox"]
        if row.get("target_roi"):
            tx,ty,tw,th=row["target_roi"];box=[tx-24,ty-24,tw+48,th+48]
        gray,revision=render_window(row,box)
        Image.fromarray(gray).save(folder/"native.png")
        target_overlay(Image.fromarray(gray),revision,1,trial=True).save(folder/"native-target.png")
        revision["original_crop_matches_real_same_frame_render"]=row["original_crop_matches_real_same_frame_render"]
        diagnostic.append(revision)
        print(sid,"same low pixels",row["original_crop_matches_real_same_frame_render"],"native",gray.shape,"objects",revision["source_page_object_types"],flush=True)
    atomic_json(OUT/"diagnostic-targets.json",diagnostic)
    atomic_json(OUT/"replay-plan.json",plan)


def map_saved_windows():
    """Correct centre/boundary convention without another PDF render."""
    originals={r["sample_id"]:r for r in read_rows(BASE/"manifest.jsonl")}
    revisions=read(OUT/"diagnostic-targets.json")
    for revision in revisions:
        row=originals[revision["original_sample_id"]]
        revision["candidate_geometry"]=[[g[0],sum([pdf_to_pixel_center(pixel_center_to_pdf(g[1][k:k+2],row["coordinate_frame"]),revision["coordinate_frame"]) for k in (0,2)],[]),g[2]] for g in row["candidate_geometry"]]
        revision["coordinate_convention"]="LSD/array pixel centres +0.5 to PDF device boundaries; native centre -0.5. ROI/crop boxes are boundaries."
        folder=OUT/revision["original_sample_id"][-3:]
        gray=np.array(Image.open(folder/"native.png").convert("L"))
        measure_row(revision,SourceWindow(gray,revision["source_bbox"][:2],revision["coordinate_frame"]["render_size_px"]))
        target_overlay(Image.fromarray(gray),revision,1,trial=True).save(folder/"native-target.png")
        x,y,_,_=revision["source_bbox"]
        distance=ink_distance(gray)
        ratio=revision["source_dpi"]/row["source_dpi"]
        revision["native_source_checks"]=[{"member":"AB"[i],
            "edge":edge_attachment(gray, (np.asarray(g[1]).reshape(2,2)-[x,y]).flatten(),radius_px=1.25*ratio),
            "extent":sample_line(gray,distance,(np.asarray(g[1]).reshape(2,2)-[x,y]).flatten(),support_radius_px=1.25*ratio,tangent_probe_px=3*ratio),
            "tolerance_basis":"same physical tolerance as the original low-resolution 1.25px; not a claim of exact edge identity"}
            for i,g in enumerate(revision["candidate_geometry"])]
    atomic_json(OUT/"diagnostic-targets.json",revisions)


def compact_diagnostics(revisions, originals):
    """Native revisions cannot carry old raster metrics/features or UI claims."""
    retained=("sample_id","original_sample_id","source_path","source_relative_path","source_page",
        "source_drawing_id","source_entry_id","source_family_id","source_bbox","source_dpi",
        "candidate_geometry","candidate_geometry_ids","target_roi","target_kind","coordinate_frame",
        "coordinate_convention","native_window","native_source_checks","source_page_object_types",
        "original_crop_matches_real_same_frame_render","purpose","human_answer_inherited",
        "training_authorized","label","label_provenance","current_p3a_measurement","measurement_rule",
        "measurement_status","measurement_missing_reason","profile_member_rule","feature_profile_geometry_id",
        "sampling_conditions")
    result=[]
    for row in revisions:
        revision={k:copy.deepcopy(row.get(k)) for k in retained}
        original=originals[row['original_sample_id']]
        revision['original_target_reference']={k:original[k] for k in ('sample_id','source_bbox','candidate_geometry','target_roi','coordinate_frame','source_dpi','parent_geometry')}
        revision['quality']={'metrics':pair_metrics(*[g[1] for g in revision['candidate_geometry']]) if len(revision['candidate_geometry'])==2 else {},
                             'identity_limit':'native source diagnostics recorded separately; old quality/features not inherited'}
        prefix=row['original_sample_id'][-3:]
        revision['preview_files']={'crop':prefix+'/native.png','target':prefix+'/native-target.png'}
        with Image.open(OUT/prefix/'native.png') as image:
            target_overlay(image.convert('L'),revision,1,trial=True).save(OUT/prefix/'native-target.png')
        revision['split']='diagnostic_not_a_dataset'
        result.append(revision)
    return result


def finalize():
    """One compact issue record and eight same-position comparison cards."""
    originals={r['sample_id']:r for r in read_rows(BASE/'manifest.jsonl')}
    record=read(OUT/'issues.json')
    from preview_trial import coordinate_check
    replay_rows=read_rows(OUT/'replay/targets.jsonl')
    for row in replay_rows:
        with Image.open(OUT/row['plan_unit'].lower()/'source.png') as im:
            coordinate_check(row,np.asarray(im.convert('L')))
    write_rows(OUT/'replay/targets.jsonl',replay_rows)
    revisions=compact_diagnostics(read(OUT/'diagnostic-targets.json'),originals)
    atomic_json(OUT/'diagnostic-targets.json',revisions)
    native={r['original_sample_id']:r for r in revisions}
    findings={
      'preview-003':('任务口径/原回答冲突','源页连续斜线填充带中的两成员；不是因为PAIR标题才判为阴影。',
        '来源上下文可见重复斜向填充笔画；人工2与旧契约填充/阴影属于3存在冲突。',
        '仅记录冲突；原2和备注不改。','是否将此项按旧契约处理，仍需针对该对象确认；本轮不生成硬标签。'),
      'preview-005':('防退化对照','外图框两侧提名边缘。','方向边缘检查两成员均1.00，原几何不改。','无需移线。','原类别1未作为独立真值重验。'),
      'preview-006':('提名对应不明/栅格信息损失','同位置原PDF局部320DPI；父几何及原裁块。',
        '原低清裁块与重新读取的同帧源像素一致；截短未改变垂向位置。A/B位于密集斜向填充带内，最近黑像素/profile不能证明对应垂直边界。低清B方向边缘比例约0.55，局部矢量渲染同物理容差A=0、B≈0.23。',
        'quality.edge_attachment + inspect在显式页入口检查边缘方向；原线对在真实回放中产生1次，因EDGE_DIRECTION_UNCONFIRMED暂不进入可用池。未吸附、未改称中心线。',
        '未确认每个原成员对应的独立源对象。有限梯度检查不能保证排除全部错拟合；本轮未为该带另选容易目标。'),
      'preview-007':('上层对象与底层边界','上下文是楼梯邻接的水平双边界。','两个底层边界共同属于更大结构，不要求先证明整体完整才能保存两边。',
        '保留原2；用作独立双边界防退化对照。','不做墙组装/房间识别；原类别未独立认证。'),
      'preview-008':('整页定位显示含义','九龙物理第8页；003裁框[305,746,256,256]，008裁框[481,734,256,256]。',
        '同页不同目标。008线x≈609，003裁框最右x=561，008无需在003内。共享图以003旧整页图为底并叠加全部同色框；当前候选未突出。单候选定位图及源裁块引用正确；未发现上项缓存串图。',
        'RepairTrialApp.whole_page及preview_refine.write_gallery优先当前page_position，明确红框只指当前裁块；全部同页位置只作次级参考。旧HTML/图片保留。',
        '没有移动008；本轮未打开标注UI，当前文件读取分支已通过局部调用检查。'),
      'preview-010':('相邻真实笔画/边缘拟合精度','同位置原PDF局部320DPI保留楼梯、横向边界与标注。',
        '像素上有不同高度的平行笔画，其中一条中间断开；未见三条完全重合的同一源笔画。目标处于近边界的低清拟合位置，局部梯度峰偏差约2.18原生像素（约0.49 PDF点），未证明为裁块坐标错位。',
        '不合并或删除邻线；补显式像素中心/裁框边界映射及近边缘证据。回放仍产生原单线提名，可用池保留；输出的PAIR只是另一关系提名，不继承该单线的人工1。',
        '未取得此PDF对应CAD实体逐条配准，不能断言不存在实体重复。高DPI修订未取得稳定profile，缺失原因保留。'),
      'preview-011':('任务范围未规定','仓库水物理第7页轴网/轴线相关目标。','旧契约没有明确轴线/尺寸/引出线范围；observation_code=1不是类别1。',
        '规则待定与原观察保留。建议以后先明确是否纳入注记规则线，不通过外观或profile决定。','本轮未形成监督标签。'),
      'preview-012':('连通区域/注记整体语义','小区域ROI位于R2000及其半径/箭头线关系内，原600像素上下文可见。',
        '目标是区域而不是A线；上下文足以显示R2000和周围线弧关系。局部墨迹不能自动当独立结构。',
        '保留人工OTHER及整体注记观察，不扩大为所有半径附近对象的通用真值。','尺寸/半径注记是否属于本任务仍缺明确规格；不删除产品尺寸标注。'),
      'preview-013':('设备安装图范围未规定','20S206印刷页16，PDF物理第9页；设备/管道安装详图局部。',
        '归族为图集；可见线不等于建筑结构边界，profile不决定设备图语义。',
        '保留rule_pending_observation及observation_code=1；建议单独声明安装图/管道规则边界是否属于任务。','本轮没有类别1或监督硬标签。'),
      'preview-015':('全段范围核对','同位置320DPI源局部包含两个窗及中间墙段。',
        '窗内有不同竖向成员，候选邻接的最外侧竖边沿全段连续；同物理1.25低清像素容差内支持比例1.00、最长无支持间隔0。拟合与局部边缘峰存在约2.99原生像素偏差，不证明对象绝对唯一。',
        '原目标未截断/移位。sample_line记录全段最长无支持间隔，显式页入口对>8源像素的间隔暂缓；窗口本身不触发截断。真实回放原提名仍保留。',
        '连续邻边不等于完整墙体识别；局部原生修订无稳定profile，如实记缺失。未把近边自动吸附成真实CAD边界。'),
      'preview-018':('区域不是独占对象边界','同位置原PDF局部可见20X1.25M中的2与斜向笔画接近/粘连。',
        '阈值160连通域ROI仅4×8低清像素，是墨迹小片段，不等于完整独立字符。原生源图显示数字局部和邻近斜线关系，不能保证ROI只属于一个对象。',
        'extract.nominations/trial_sampling明确threshold-connected目标范围依据；不擦除斜线、不清理字符、不自动生成OTHER。原回答仅对应旧区域。',
        '没有实现语义分割或字符归属判断；真实回放同ROI仍可提名，用途只限对象归属诊断。'),
      'preview-019':('局部笔画/门符号对象归属','旧上下文包含门扇/开启弧，目标在短水平门扇笔画。',
        '源上下文支持用户门符号局部的观察；不是由于附近有任意圆弧就排除墙线。',
        '保留原OTHER及对象归属观察，不扩大为删除门符号的生产授权。','不声明整类门构件都不能作结构边界；本轮不改产品。'),
      'preview-020':('上层结构/底层边界','楼梯详图下侧两条水平边界及邻接墙线。','同属墙/楼梯上层对象不意味着合成一根；两条需分别保留的边界符合类别2的已有定义。',
        '保留原2；两成员方向边缘检查均1.00。','不以此重建墙、BLOCK或整层实体；原标签未独立认证。'),
      'preview-021':('几何配对/对象关系未确定','黑色DN25相关水平管线与灰色虚线轴网水平成员。',
        'extract.nominations仅按≤3度、0.5–60像素间距及≥40像素共同投影配对，没有同对象或任务范围证据。不是承诺两成员来自同一笔画。',
        '新入口proposal_relation明确只为几何关系提名；不因不同对象自动删除该对或赋1/2/3。',
        '若将任务限定为已确认结构边界，该混合对不具备分类依据；轴线/专业管线是否纳入仍规则待定。原deferred只计一次。'),
    }
    for issue in record['issues']:
        sid=issue['original_sample_id'];row=originals[sid]
        issue['source'].update({k:row[k] for k in ('source_drawing_id','source_relative_path','source_dpi','coordinate_frame','parent_geometry')})
        if sid in findings:
            layer,evidence,reproduced,correction,remaining=findings[sid]
            issue.update(question=layer,source_evidence=evidence,reproduced=reproduced,correction=correction,remaining=remaining)
        else:
            issue.update(question='未报告新的对应/范围问题',source_evidence='原裁块/上下文及原最终回答保留',
                reproduced='未额外独立核实类别正确性',correction='无目标或答案修改',remaining='保存为人工回答，不据此授权训练或产品删除')
        issue['diagnostic_revision']=native.get(sid,{}).get('sample_id')
        issue['human_answer_applies_to']='original_target_only'
    control_results=[]
    for sid in ('preview-001','preview-005','preview-006','preview-007','preview-020'):
        row=copy.deepcopy(originals[sid]);x,y,_,_=row['source_bbox']
        gray=np.array(Image.open(BASE/row['preview_files']['crop']).convert('L'))
        row['source_bbox']=[0,0,256,256]
        for g in row['candidate_geometry']:g[1]=(np.asarray(g[1]).reshape(2,2)-[x,y]).flatten().tolist()
        control_results.append({'original_sample_id':sid,'before':inspect(row,gray),'after':inspect(row,gray,require_directional_edge=True),'geometry_moved':False})
    record['local_checks']={'command':'../.venv/Scripts/python.exe -B -m unittest discover -s tools/p3b -p test_feedback_repair.py -v',
        'result':'6 tests passed','scope':'current locator file selection without UI launch; real hatch/clear controls; mid-segment gap; rotated pixel-centre mapping and endpoint/ROI convention; explicit source-cache mismatch',
        'actual_same_frame_crop_equality':{r['original_sample_id']:r['original_crop_matches_real_same_frame_render'] for r in revisions},
        'controls':control_results,'not_run':'full suite; model; production CAD/OCR; semantic independent correctness or annotation UI interaction'}
    record['changed_functions']=['quality.edge_attachment / sample_line / inspect','trial_sampling.render_explicit / pixel_center_to_pdf / pdf_to_pixel_center / build_trial_pool',
        'trial_labeling.RepairTrialApp.whole_page / load_trial','preview_refine.write_gallery','extract.nominations (region extent metadata)',
        'preview_trial.coordinate_check (line pixel centres vs ROI box boundaries)',
        'feedback_diagnostic (bounded diagnostics and actual-entry replay, no new app)']
    comparisons=sum(r['pair_comparisons'] for p in record['replay']['pages'] for r in p['region_pair_budget'])
    unchecked=sum(r['unchecked_comparisons'] for p in record['replay']['pages'] for r in p['region_pair_budget'])
    record['replay']['pair_comparisons']=comparisons
    record['replay']['unchecked_pair_comparisons']=unchecked
    record['limitations']=['Old initial per-region pairing/rejection counts remain unobtained; no historical numbers fabricated.',
        f'Replay examined {comparisons} pair comparisons, {unchecked} comparisons were not examined (budget). Selection stopped after 3; remaining 450 pool entries unexamined by selector, not called deduplicated.',
        'No unique source-entity correspondence proved by coordinate roundtrip, profiles or gradient checks.',
        'CAD views remain deferred; no new registration or conversion; new residential sources continue separately.',
        'Training, active/automatic labeling and self-training remain paused; no second-review task, UI launch or watcher.']
    record['completed_date']='2026-10-11'
    atomic_json(OUT/'issues.json',record)
    write_comparison(record,originals,native)


def write_comparison(record,originals,native):
    e=html.escape
    rel=lambda path:os.path.relpath(path,OUT).replace('\\','/')
    issues={r['original_sample_id']:r for r in record['issues']}
    def fig(path,label):
        url=rel(path)
        return f'<figure><a href="{e(url)}" target="_blank"><img loading="lazy" src="{e(url)}" alt="{e(label)}"></a><figcaption>{e(label)}</figcaption></figure>'
    cards=[]
    order=['preview-006','preview-008','preview-010','preview-015','preview-003','preview-018','preview-021']
    for sid in order:
        row=originals[sid];issue=issues[sid];images=row['preview_files']
        note=issue['original_response'].get('observation') or '无新增备注'
        if sid=='preview-008':
            views=fig(BASE/images['shared_page_position'],'修复前：共享整页全部同色框，以003定位图为底')+fig(BASE/images['page_position'],'修复后入口读取此图：只显示当前008裁块红框')+fig(BASE/images['crop'],'原008源像素，未移动')
        elif sid in native:
            views=fig(BASE/images['target'],'修复前：用户当时看到的原目标')+fig(OUT/native[sid]['preview_files']['crop'],'同位置原PDF局部320DPI：未叠加真实源像素')+fig(OUT/native[sid]['preview_files']['target'],'诊断修订：同一原目标物理位置，未吸附邻线；不继承回答')
        else:
            diagnostic=OUT/sid[-3:];diagnostic.mkdir(exist_ok=True)
            displayrow=copy.deepcopy(row);displayrow['source_bbox']=row['context_bbox']
            with Image.open(BASE/images['context_raw']) as im:
                target_overlay(im.convert('L'),displayrow,1,trial=True).save(diagnostic/'context-target.png')
            views=fig(BASE/images['target'],'原目标/原裁块保持原样')+fig(BASE/images['context_raw'],'原源图上下文，不借标题判类别')+fig(diagnostic/'context-target.png','修复后的说明视图：原目标在现有上下文中的位置，几何未改')
        if sid in native:
            detail=json.dumps({k:native[sid][k] for k in ('coordinate_convention','source_page_object_types','native_source_checks','current_p3a_measurement','measurement_status','measurement_missing_reason')},ensure_ascii=False,indent=2)
        else:detail=json.dumps({k:row[k] for k in ('source_bbox','context_bbox','candidate_geometry','target_roi')},ensure_ascii=False,indent=2)
        cards.append(f'<article id="{sid}"><h2>{sid} · {e(issue["question"])}</h2><p class="source">{e(row["source_relative_path"])} · PDF物理第{row["source_page"]}页 · 原DPI {row["source_dpi"]:.2f}</p><blockquote>用户原备注：{e(note)}</blockquote><div class="views">{views}</div><p><b>定位结论：</b>{e(issue["reproduced"])}</p><p><b>实际修正：</b>{e(issue["correction"])}</p><p><b>仍未解决：</b>{e(issue["remaining"])}</p><p><a href="{e(rel(BASE/images["page_position"]))}">此目标整页位置</a> · <a href="{e(rel(BASE/images["context_raw"]))}">无叠加原上下文</a></p><details><summary>实际目标、源图及测量记录</summary><pre>{e(detail)}</pre></details></article>')
    controlviews=''.join(fig(BASE/originals[sid]['preview_files']['target'],sid+'：前后几何/图片不变，新增方向检查通过；不是独立认证标签') for sid in ('preview-001','preview-007'))
    cards.append('<article id="unaffected-controls"><h2>未受影响对照 · 001 / 007</h2><div class="views">'+controlviews+'</div><p>001人工1：单笔画的两侧边缘；007人工2：需分别保留的双边界。候选类型不决定类别。同属墙/楼梯等对象不要求合并为一根线。005/020也通过本轮方向检查，记录在issues.json。没有改目标或答案。</p></article>')
    scope=''.join(f'<li>{sid}：{e(issues[sid]["reproduced"])} {e(issues[sid]["remaining"])}</li>' for sid in ('preview-011','preview-013','preview-012','preview-019','preview-020'))
    replay=record['replay'];replayfigs=''.join(fig(OUT/r['preview_files']['target'],r['sample_id']+' '+r['plan_unit']+'：正常选择输出，未人工分类，不代替旧问题目标') for r in read_rows(OUT/'replay/targets.jsonl'))
    replaylinks=''.join(f'<li>{r["sample_id"]} {r["plan_unit"]} / 第{r["source_page"]}页：<a href="{e(r["preview_files"]["page_position"])}">整页定位</a> · <a href="{e(r["preview_files"]["context_raw"])}">原上下文</a> · <a href="{e(r["preview_files"]["crop"])}">裁块</a></li>' for r in read_rows(OUT/'replay/targets.jsonl'))
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B 反馈定向修复对照</title><style>body{margin:0;background:#eef1f4;color:#202a34;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}header,main{max-width:1480px;margin:auto;padding:22px}header,article{background:white}h1{font-size:27px;margin:0}h2{font-size:21px;margin:0}article{padding:22px;margin:20px 0;border:1px solid #d2d9df;border-radius:6px}.views{display:flex;flex-wrap:wrap;gap:14px}figure{margin:0;flex:1;min-width:260px}img{width:100%;height:460px;object-fit:contain;background:#fafafa;border:1px solid #d5dce2}figcaption,.source{font-size:14px;color:#485969}blockquote{margin:12px 0;padding:8px 14px;background:#f5f7f9;border-left:3px solid #738797}pre{font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;padding:12px}a{color:#176286}details{padding:12px 0}.notice{border-left:4px solid #b97a29;padding-left:13px}@media(max-width:700px){header,main{padding:12px}img{height:380px}}</style><header><h1>P3B 试标反馈收口 · 8张定向对照卡</h1><p>20项已处理，16项保存分类（7单笔画、3独立双边界、6非本任务对象），011/013规则观察、006/021暂缓。最后save_and_end；training_authorized=false。16项保存分类不是16个独立核实的正确标签，0个明确指错不是全部目标正确。</p><p class="notice">只查看修复效果，不再标20项。本页没有分类按钮、自动保存、训练或后台任务。原回答、修改历史、旧裁片、004/022排除历史、94/50及模型保留。</p><p>PDF局部320DPI来自同位置原页矢量路径（各问题页含16787/49082/166923个PATH，部分另有印章图像），不是旧像素8倍插值。色线是原目标回映，不是正确源对象答案；新增原生测量未借用旧profile。</p><p><a href="issues.json">紧凑问题记录（原回答保留）</a> · <a href="diagnostic-targets.json">同位置诊断修订及逐成员测量</a></p><details><summary>正常生成入口开发回放（3页，3个输出；不计新样本）</summary><p>实际路径：显式原PDF页缓存→全页LSD检测→预定局部2×2区域及比较预算→最终目标和方向/全段支持检查→正常去重选择→共享测量→裁块与当前整页定位。453个支持池提名，仅选3个；没有读取旧候选池来挪线。</p><p>PAIRCOUNT次局部配对比较；一个区域因1000次预算尚有PAIRUNCHECKED次未比较。选择到3个即停止，450个池条目未由选择器继续检查；本次去重拒绝计数为0，不代表池内没有重复。已知区域的跨轮排除为开发复现明确关闭，批内规则仍启用；本批绝不能作新信息标注队列。旧006匹配提名产生后被方向检查暂缓，未以容易样本补位；另外三个输出不替代它。</p>REPLAYVIEWS<ul>REPLAYLINKS</ul><p><a href="replay/targets.jsonl">真实输出记录</a> · <a href="replay-plan.json">回放区域计划</a> · counts/有限检查记录见issues.json。不声明端到端分布均衡或识别准确率。</p></details><details><summary>其他对象口径与保留边界</summary><p>依据LABELING-CONTRACT-V2.md §Stage 1 physical class第1–3项及REPORT.md §Label rubric and provenance：1一条结构/规则笔画（含两侧边缘）；2两条需分别保留的独立边界；3文字/符号内部笔画、填充/阴影等非本任务对象。类别3不授权产品删除对象。</p><ul>SCOPE</ul><p>尺寸、轴线、引出线、安装详图边界及专业管线的具体接受范围仍待明确；不让用户猜规则，不从profile推断语义，不建立新的复杂标签体系。</p></details><p>仅6项局部测试已运行。未打开标注UI、未运行全量测试；CAD视图继续暂缓。暂停训练、自动增标及自训练。查看后由用户决定后续工作。</p></header><main>CARDS</main></html>'''
    (OUT/'index.html').write_text(document.replace('PAIRCOUNT',str(replay['pair_comparisons'])).replace('PAIRUNCHECKED',str(replay['unchecked_pair_comparisons'])).replace('REPLAYVIEWS','<div class="views">'+replayfigs+'</div>').replace('REPLAYLINKS',replaylinks).replace('SCOPE',scope).replace('CARDS',''.join(cards)),encoding='utf-8')
    print(f'Comparison: {OUT/"index.html"}; {len(cards)} cards; original human answers untouched',flush=True)


def replay():
    """One bounded run through the normal offline explicit-page entry."""
    from prepare_v2 import build_pool
    from queue_dedup import deduplicate
    from preview_trial import annotate,coordinate_check
    from PIL import ImageDraw,ImageFont
    folder=OUT/"replay"
    if folder.exists():raise ValueError("Never replace a completed development replay")
    rows=read_rows(BASE/"manifest.jsonl")
    plan=read(OUT/"replay-plan.json")
    # Known issue observation windows fixed BEFORE new detection, in the old
    # page's raster coordinates. They constrain search, never set output crops.
    windows={"TRIAL-02":[720,100,1080,440],"TRIAL-04":[3190,1450,3630,1910],
             "TRIAL-05":[2990,285,3370,630]}
    references={"TRIAL-02":["preview-010"],"TRIAL-04":["preview-006","preview-018"],
                "TRIAL-05":["preview-015"]}
    for unit in plan["rows"]:
        key=unit["plan_unit"];frame=read(OUT/key.lower()/"frame.json")["frame"]
        w,h=frame["render_size_px"];pw,ph=frame["page_size_points"]
        box=windows[key]
        unit["regions"]=[{"observation_box_pdf_points_approx":[box[0]*pw/w,box[1]*ph/h,box[2]*pw/w,box[3]*ph/h],
            "landmark":"已反馈问题同位置开发回放；不计新信息；观察范围不是裁框"}]
        prefix=str((OUT/key.lower()).relative_to(ROOT)).replace('\\','/')
        unit["source_render_cache"]={"image":prefix+"/source.png","frame":prefix+"/frame.json"}
        unit["pair_comparison_budget_per_region"]=1000
        unit["diagnostic_reference_targets"]=[{"original_sample_id":r["sample_id"],"display_geometry":r["display_geometry"],
            "display_target_box":r.get("display_target_box")} for r in rows if r["sample_id"] in references[key]]
    plan["purpose"]="bounded_development_replay_not_new_samples"
    atomic_json(OUT/"replay-plan.json",plan)
    pool,pages,summaries=build_pool(page_plan=plan,supplement=read(ROOT/"docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json"))
    chosen,examples,selection=deduplicate(pool,None,preview_policy={"max_total":3,"max_page":1,"max_difficult_page":0},history=[])
    folder.mkdir()
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20)
    for number,row in enumerate(chosen,1):
        row["proposal_id"]=row["sample_id"];row["sample_id"]=f"dev-replay-{number:03d}"
        row.update(purpose="known_position_development_replay",training_authorized=False,
                   human_answer_inherited=False,new_information_claimed=False,label=None,label_provenance=None)
        gray=pages[row["plan_unit"]]["gray"]
        measure_row(row,gray);coordinate_check(row,gray)
        target=folder/row["sample_id"];target.mkdir()
        x,y,w,h=row["source_bbox"]
        patch=Image.fromarray(gray[y:y+h,x:x+w]);patch.save(target/"gray.png")
        target_overlay(patch,row,2,trial=True).save(target/"target.png")
        # Final target extent plus readable neighboring relations, not an entire
        # room scaled down into the classifier crop.
        points=np.asarray([g[1] for g in row["candidate_geometry"]]).reshape(-1,2) if row["candidate_geometry"] else np.array([[x+w/2,y+h/2]])
        a=np.maximum(0,np.floor(points.min(0)-210).astype(int));b=np.minimum([gray.shape[1],gray.shape[0]],np.ceil(points.max(0)+210).astype(int))
        row["context_bbox"]=[*a.tolist(),*(b-a).tolist()]
        Image.fromarray(gray[a[1]:b[1],a[0]:b[0]]).save(target/"context-raw.png")
        annotate(Image.fromarray(gray[a[1]:b[1],a[0]:b[0]]).convert('RGB'),row,a).save(target/"context.png")
        image=Image.fromarray(gray).convert('RGB');scale=min(1,1500/image.width)
        image=image.resize((round(image.width*scale),round(image.height*scale)),Image.Resampling.LANCZOS)
        draw=ImageDraw.Draw(image);draw.rectangle((x*scale,y*scale,(x+w)*scale,(y+h)*scale),outline='#db2435',width=4)
        draw.text((x*scale,max(0,y*scale-26)),row['sample_id'],font=font,fill='#db2435')
        image.save(target/"page-position.jpg",quality=90)
        row["preview_files"]={key:f"replay/{row['sample_id']}/{name}" for key,name in {
            "crop":"gray.png","target":"target.png","context_raw":"context-raw.png","context":"context.png","page_position":"page-position.jpg"}.items()}
    write_rows(folder/"targets.jsonl",chosen)
    record=read(OUT/"issues.json")
    record["replay"]={"actual_entry":"prepare_v2.build_pool -> extract.run -> trial_sampling.build_trial_pool -> queue_dedup.deduplicate -> measurement.measure_row -> actual crop/current page locator",
        "purpose":"known-position development replay; no new information, labeling, train/validation or inherited answers",
        "history_policy":"Known-region replay explicitly omits cross-round exposure exclusion for reproduction; within-run identity, cross-kind region and shared-line limits unchanged. Not usable as a new-label queue.",
        "source_cache":"three actual original PDF page rasters collected this task; no old candidate pool used",
        "pages":summaries,"supported_pool":len(pool),"selected":len(chosen),"selection":selection,"rejection_examples":examples,
        "labels_assigned":0,"model_runs":0}
    atomic_json(OUT/"issues.json",record)
    print(json.dumps({"supported_pool":len(pool),"selected":len(chosen),"selection":selection,"reference_matches":[r['diagnostic_reference_matches'] for r in summaries]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=('collect','map-windows','replay','finalize'))
    action=ap.parse_args().action
    {'collect':collect,'map-windows':map_saved_windows,'replay':replay,'finalize':finalize}[action]()
