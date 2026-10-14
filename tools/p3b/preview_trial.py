"""Generate only a bounded, unlabelled repair-preview gallery."""

import argparse
import copy
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from common import ROOT, read, write_rows, atomic_json
from inventory import build as inventory_build
from measurement import measure_row
from prepare_v2 import build_pool
from queue_dedup import deduplicate
from target_view import target_overlay
from trial_sampling import load_history, pdf_to_device, to_pdf, pixel_center_to_pdf

ATLAS_FAMILY = "STANDARD-ATLAS-20S206"


def apply_content_sources(plan, supplement):
    """Container and page-content ancestry are distinct, consumed fields."""
    registry={r["entry_id"]:r for r in supplement["rows"]}
    for unit in plan["rows"]:
        if unit["page_or_layout"]["type"]!="PDF": continue
        original=registry[unit["source_entry_id"]]
        unit["container_identity"]={"entry_id":original["entry_id"],
            "relative_path":unit["relative_path"],"materials_root":supplement["materials_root"],
            "document_package_family":original["family"].get("plan_id")}
        if "content_source" not in unit:
            unit["content_source"]={"family_id":unit["design_family"]["plan_id"],
                                    "kind":"engineering_page","registration":"not_cross_format_registered"}
        if unit["plan_unit"] in ("TRIAL-01","TRIAL-05"):
            unit["content_source"].update({"shared_base_group":"WAREHOUSE-FLOOR4-BASE",
                "logical_base_region":"axis2_3-B_C" if unit["plan_unit"]=="TRIAL-01" else "axis8_9-F_G",
                "relation":"same building base, different professional sheets",
                "registration":"logical zones only; no precise page-to-page registration"})
        if unit["plan_unit"]=="TRIAL-07":
            # Keep the initial inherited value. Never rewrite the frozen/prep tables.
            initial=read(ROOT/"docs/product-fix-p3b/PAGE-REGION-TRIAL-PLAN-20261010.json")
            before=next(r["design_family"] for r in initial["rows"] if r["plan_unit"]=="TRIAL-07")
            unit["content_source"]={"family_id":ATLAS_FAMILY,"kind":"standard_atlas_page",
                "content_id":"20S206/page16/预作用装置安装图（一）",
                "atlas_number":"20S206","printed_atlas_page":16,
                "previous_inherited_design_family":before,
                "correction_reason":"PDF容器属于仓库资料包；此页图形源自20S206，不继承仓库设计族",
                "registration":"original atlas page identified; cross-container pixel mapping not established"}
            unit["design_family"]={"legacy_id":None,"plan_id":ATLAS_FAMILY,
                "basis":"图集号20S206及实际印刷页16","confidence":"已定向核实；容器族另存"}
    return plan


def atlas_reuse(plan, supplement):
    """Reuse the completed targeted check; never repeat the domestic PDF scan."""
    base=ROOT/"local-artifacts/product-fix-p3b/preview-trial-20261010-001"
    record=base/"initial-run.json"
    if not record.is_file(): record=base/"run.json"
    if record.is_file():
        result=copy.deepcopy(read(record).get("atlas_content_reuse",{}))
        result["reused_record"]=str(record)
        result["new_source_reads"]=0
        result["current_scope"]="复用既有定向检查；不同重采样/印章/编辑版本的跨项目复用仍未证实"
        return result
    return {"family":ATLAS_FAMILY,"new_source_reads":0,
            "limits":"既有复用记录未取得；仅保留明确图集页身份，不声明没有跨项目复用"}


def annotate(image, row, origin, scale=1):
    draw = ImageDraw.Draw(image)
    for member, (_,line,_) in enumerate(row["candidate_geometry"]):
        color = ("#e32936","#007eae")[member]
        pts = [((line[k]-origin[0])*scale,(line[k+1]-origin[1])*scale) for k in (0,2)]
        draw.line(pts, fill=color, width=2)
        for x,y in pts:
            draw.ellipse((x-3,y-3,x+3,y+3),fill=color,outline="white")
    if row["target_roi"]:
        x,y,w,h = row["target_roi"]
        draw.rectangle(((x-origin[0])*scale,(y-origin[1])*scale,
                        (x+w-origin[0])*scale,(y+h-origin[1])*scale),outline="#e32936",width=2)
    return image


def coordinate_check(row, gray):
    frame = row["coordinate_frame"]
    endpoints = [(f"{'AB'[i]}{j+1}",line[k:k+2]) for i,(_,line,_) in enumerate(row["candidate_geometry"])
                 for j,k in enumerate((0,2))]
    if not endpoints:
        x,y,w,h = row["target_roi"]
        endpoints = [("ROI top-left",[x,y]),("ROI bottom-right",[x+w,y+h])]
    checks = []
    with pdfium.PdfDocument(row["source_path"]) as doc:
        page = doc[row["source_page"]-1]
        try:
            for name, point in endpoints:
                is_line = bool(row["candidate_geometry"])
                pdf_point = pixel_center_to_pdf(point,frame) if is_line else to_pdf(point,frame)
                back = pdf_to_device(page,frame["render_size_px"],pdf_point)
                if is_line:back = [v-.5 for v in back]
                error = float(np.max(abs(np.array(back)-point)))
                nearest = None
                if row["candidate_geometry"]:
                    x,y = point
                    x0,y0 = max(0,int(x)-4),max(0,int(y)-4)
                    yy,xx = np.where(gray[y0:int(y)+5,x0:int(x)+5]<180)
                    if len(xx):
                        nearest = float(np.min(np.hypot(xx+x0-x,yy+y0-y)))
                checks.append({"endpoint":name,"source_pixel":list(point),"PDFium_page_point":pdf_point,
                               "coordinate_convention":"array pixel centre +0.5 -> device; integer inverse -0.5" if is_line else "ROI corner is a raster box boundary",
                               "mapped_back_pixel":back,"roundtrip_max_axis_error_px":error,
                               "nearest_source_ink_px":nearest})
        finally:
            page.close()
    row["endpoint_coordinate_checks"] = checks
    return checks


def write_preview(output, rows, pages):
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf",20)
    cards = []
    overview = Image.new("RGB",(5*288, max(1,(len(rows)+4)//5)*310),"#f0f1f2")
    for number,row in enumerate(rows,1):
        row["proposal_id"] = row["sample_id"]
        row["sample_id"] = f"preview-{number:03d}"
        row["label_contract"] = "preview-only; no label assignment"
        gray = pages[row["plan_unit"]]["gray"]
        measure_row(row,gray)
        coordinate_check(row,gray)
        folder = output/row["sample_id"]
        folder.mkdir()
        x,y,w,h = row["source_bbox"]
        patch = Image.fromarray(gray[y:y+h,x:x+w])
        patch.save(folder/"gray.png")
        overlay = target_overlay(patch,row,scale=2)
        overlay.save(folder/"target.png")
        # Explicit context follows the target crop, not the planned observation box.
        cx,cy = x+w/2,y+h/2
        x0,y0 = max(0,round(cx-300)),max(0,round(cy-300))
        x1,y1 = min(gray.shape[1],x0+600),min(gray.shape[0],y0+600)
        row["context_bbox"] = [x0,y0,x1-x0,y1-y0]
        context = annotate(Image.fromarray(gray[y0:y1,x0:x1]).convert("RGB"),row,[x0,y0])
        context.save(folder/"context.png")
        full = Image.fromarray(gray).convert("RGB")
        scale = min(1,1500/full.width)
        full = full.resize((round(full.width*scale),round(full.height*scale)),Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(full)
        draw.rectangle((x*scale,y*scale,(x+w)*scale,(y+h)*scale),outline="#e32936",width=4)
        draw.text((max(0,x*scale),max(0,y*scale-25)),row["sample_id"],fill="#e32936",font=font)
        full.save(folder/"page-position.jpg",quality=90)
        row["preview_files"] = {k:f"{row['sample_id']}/{v}" for k,v in {
            "page_position":"page-position.jpg","context":"context.png","crop":"gray.png","target":"target.png"}.items()}
        thumb = overlay.resize((256,256),Image.Resampling.LANCZOS)
        ox,oy = ((number-1)%5)*288+16,((number-1)//5)*310+38
        overview.paste(thumb,(ox,oy))
        ImageDraw.Draw(overview).text((ox,oy-27),f"{number:02d} {row['plan_unit']} {row['target_kind']}",fill="#15202c",font=font)
        basename = html.escape(Path(row["source_path"]).name)
        metadata = (f"{html.escape(row['sample_id'])} · {html.escape(row['source_drawing_id'])} · 第{row['source_page']}页 · {row['target_kind']}候选")
        images = ''.join(f'<figure><a href="{path}" target="_blank"><img src="{path}" alt="{label}" loading="lazy"></a><figcaption>{label}</figcaption></figure>'
                         for label,path in [("整页位置（红框）",row["preview_files"]["page_position"]),
                                            ("上下文（端点标记）",row["preview_files"]["context"]),
                                            ("原裁块",row["preview_files"]["crop"]),
                                            ("目标：A红 / B蓝 / 点为端点",row["preview_files"]["target"])])
        reason = '；'.join(row["retain_reasons"])
        profile = f"测量：{row['measurement_status']}"
        if row["measurement_status"]=="no_valid_profile":
            profile += "（没有稳定且有源图支持的profile；未记为实测零宽度）"
        elif row["measurement_status"]=="not_applicable":
            profile += "（区域目标没有线几何）"
        endpoint_errors = [c["roundtrip_max_axis_error_px"] for c in row["endpoint_coordinate_checks"]]
        detail = json.dumps({k:row[k] for k in ["source_relative_path","source_family_id","region_landmark","source_bbox","candidate_geometry","target_roi","endpoint_coordinate_checks","current_p3a_measurement","historical_relations"]},ensure_ascii=False,indent=2)
        cards.append(f'<article id="{row["sample_id"]}"><h2>{metadata}</h2><p>{basename} · 来源族 {html.escape(row["source_family_id"])}</p><div class="views">{images}</div><p class="reason">保留理由：{html.escape(reason)}</p><p>{html.escape(profile)} · 坐标回映最大轴误差 {max(endpoint_errors):.3f}px</p><details><summary>目标坐标、测量与历史关系</summary><pre>{html.escape(detail)}</pre></details></article>')
    overview.save(output/"overview.jpg",quality=92)
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B 修复裁切预览</title>
<style>body{margin:0;background:#f1f3f5;color:#1c2733;font:16px/1.6 system-ui,"Microsoft Yahei",sans-serif}header,main{max-width:1560px;margin:auto;padding:24px}header{background:white}h1{margin:0;font-size:26px}h2{font-size:19px;margin:0}article{background:white;border:1px solid #d7dce2;border-radius:8px;padding:20px;margin:24px 0}.views{display:grid;grid-template-columns:1.2fr 1.2fr 1fr 1fr;gap:14px}figure{margin:0}img{width:100%;height:350px;object-fit:contain;background:#fafafa;border:1px solid #d9dee3}figcaption{font-size:14px;color:#526274}.reason{border-left:3px solid #617d96;padding-left:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#f6f7f9;padding:12px}@media(max-width:1000px){.views{grid-template-columns:1fr 1fr}}@media(max-width:600px){.views{grid-template-columns:1fr}header,main{padding:12px}}</style>
<header><h1>P3B 小范围修复裁切预览</h1><p>COUNT个未标注候选 · 7个显式PDF页面 · 点击图片查看原尺寸</p><p>本批仅供检查裁切与选样。PAIR / SINGLE / CONTROL是候选形式，人工类别尚未赋值。没有训练，也没有改旧94/50。</p><p>整页红框是最终裁块位置；上下文保留对象关系。约估观察区仅用于搜索。TRIAL-07按20S206图集归族；CAD视图暂缓。新预览的生成不冒充已经人工看过。</p><p><a href="manifest.jsonl">候选记录</a> · <a href="run.json">选样配置、历史范围、图集复用与局部检查说明</a> · <a href="overview.jpg">候选总览</a></p></header><main>CARDS</main></html>'''
    (output/"index.html").write_text(document.replace('COUNT',str(len(rows))).replace('CARDS',''.join(cards)),encoding='utf-8')


def run(output, max_candidates=30):
    output = output.resolve()
    local = (ROOT/"local-artifacts/product-fix-p3b").resolve()
    if local not in output.parents:
        raise ValueError("Preview output must be a new directory under local-artifacts/product-fix-p3b")
    if output.exists():
        raise ValueError("Never overwrite an existing preview")
    old_plan = read(ROOT/"docs/product-fix-p3b/PAGE-REGION-TRIAL-PLAN-20261010.json")
    plan = copy.deepcopy(old_plan)
    supplement = read(ROOT/"docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json")
    apply_content_sources(plan,supplement)
    print("Checking 20S206 reuse in existing domestic PDF materials",flush=True)
    reuse = atlas_reuse(plan,supplement)
    rows,pages,page_summary = build_pool(page_plan=plan,supplement=supplement)
    sources = inventory_build(page_plan=plan,supplement=supplement)
    history,history_summary = load_history(plan,sources)
    chosen,examples,selection = deduplicate(rows,None,preview_policy={"max_total":min(30,max_candidates)},history=history)
    output.mkdir(parents=True)
    write_preview(output,chosen,pages)
    write_rows(output/"manifest.jsonl",chosen)
    atomic_json(output/"plan.json",plan)
    atomic_json(output/"run.json",{
        "purpose":"repair_preview_only", "selected":len(chosen),"labels_assigned":0,"model_runs":0,
        "pages":page_summary,"selection":selection,"decision_examples":examples,
        "history_scope":history_summary,"atlas_content_reuse":reuse,
        "profile_status_counts":dict(Counter(r["measurement_status"] for r in chosen)),
        "coordinate_check":"所有保留目标记录PDFium回映及线端点最近源图墨迹距离；还需视觉抽查。ROI角点不要求落在墨迹上。",
        "cad_views":"Deferred: no confirmed PDF/layout registration; no new CAD conversion or rendering",
        "limits":["长线/区域是有限代理，不保证识别全部物理结构","图集不同分辨率/重编辑的跨项目复用仍未证实","V1没有完整事件日志；队列/已看集合与真实呈现事件分开记录"],
        "unchanged":"original materials, old plans, historical queues/labels, frozen94/50 inputs and first baseline model"})
    print(f"Preview: {output/'index.html'}; {len(chosen)} candidates",flush=True)
    return chosen


if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--max-candidates",type=int,default=30)
    ap.add_argument("--refine-existing",action="store_true")
    args = ap.parse_args()
    if args.refine_existing:
        from preview_refine import refine_existing
        refine_existing(args.output)
    else:
        run(args.output,args.max_candidates)
