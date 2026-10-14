"""Refine the existing preview in place, reusing its actual saved source pixels."""

import copy
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from common import ROOT, read, read_rows, atomic_json, write_rows
from features import feature_vector
from inventory import build as inventory_build
from measurement import canonical_geometry
from prepare_v2 import measure_trial_targets as train_measure
from validation_v2 import measure_trial_targets as validation_measure
from preview_trial import apply_content_sources
from trial_sampling import cells_for, load_history, pdf_to_device, to_pdf
from preview_selection import history_relation, select_preview

DESCRIPTIONS = {
 "preview-001":("楼梯竖向线对","楼梯平面中靠近梁、踏步的两条竖向边缘提名","保留梁和踏步上下文，检查两提名边缘的对象关系"),
 "preview-002":("喷淋竖管局部","带DN150标注的竖向管线边缘提名","水专业新增管线与支管可见，区别于共享建筑底图"),
 "preview-003":("斜向阴影线对","左侧楼梯旁阴影内的两条斜向边缘提名","保留阴影、柱边和楼梯，检查提名对象归属，不预置结构类别"),
 "preview-004":("编号字形局部","消防编号字形的竖向局部边缘","与旧上下文重叠，但未取得所要求的新增对象关系差异"),
 "preview-005":("图集说明栏线对","‘系统及报警阀组’说明栏右侧的窄边缘线对","扫描说明栏窄线对作为笔画边缘关系对照，保留原灰度供核对"),
 "preview-006":("教室墙边线对","11#教室左侧墙边附近的竖向窄线对","保留墙边与开口邻接上下文，检查边缘关系，不预置人工类别"),
 "preview-007":("楼梯边缘线对","东侧楼梯下沿附近的水平线对","保留楼梯、转角及门洞，提供与说明栏窄线对不同的对象关系"),
 "preview-008":("门洞邻接竖线","两处门洞转角之间的竖向边缘提名","保留门洞和转角，局部提名与相邻对象关系可检查"),
 "preview-009":("图集字母墨迹","尺寸注记B附近的一块连通墨迹","仅保留一个明确框出的字母注记对照，不自动赋OTHER"),
 "preview-010":("楼梯上部横线","楼梯上部的水平边缘提名","保留踏步与相邻尺度线，其他同载体局部段共享名额"),
 "preview-011":("轴网边缘局部","柱网附近灰色竖向规则线的右侧边缘提名","保留轴网与水专业支管关系；记录约一像素外侧拟合偏差，不改称中心线"),
 "preview-012":("半径注记墨迹","R2000半径注记附近的一块连通墨迹","保留一个注记对照，不重复提名周围全部字符"),
 "preview-013":("图集安装图竖边","正视图中带21/22/23部件标注附近的竖向边缘提名","保留部件与相邻视图；安装详图在旧任务中的语义边界待确认"),
 "preview-014":("弧墙相邻直段","曲墙转角之前的水平直段边缘提名","另给上下文保留弧线和教室，未把整个房间压缩为裁块"),
 "preview-015":("东侧边线局部","东侧楼梯与洁具房外边附近的竖向边缘提名","保留窗、柱和房间邻接；同区共线载体只有一个普通名额"),
 "preview-016":("楼梯注记墨迹","楼梯图边缘注记的一块连通墨迹","少量明确目标对照，框内对象归属待人工查看，不赋训练类别"),
 "preview-017":("间距注记墨迹","1200间距注记中的一块连通墨迹","保留一个尺寸文字对照；它不因为来自水专业就变成新建筑结构"),
 "preview-018":("密集标注墨迹","密集电气/尺寸注记中的一块连通墨迹","保留局部对象归属难点及足够上下文，不借附近线取得profile"),
 "preview-019":("门洞水平短段","门洞上沿与柱之间的水平边缘短段","保留门弧、柱和上下相邻墙边，检查开口邻接关系"),
 "preview-020":("楼梯下部线对","楼梯下部横向边缘提名","保留踏步与尺度线，人工确认是笔画边缘还是独立对象边界"),
 "preview-021":("喷淋支管与轴线","A指向喷淋支管附近边缘，B指向建筑轴网灰线边缘","保留专业新增对象与底图轴线的邻接差异，不把PAIR当双线真值"),
 "preview-022":("窄间隙定位问题","教室分隔处的两条水平边缘提名","A处在窄间隙附近，不能明确贴到哪条源边缘，不改称中心线"),
}
PRINTED = {"TRIAL-01":"水施-07","TRIAL-02":"GS-05B","TRIAL-03":"电消施-08/11",
           "TRIAL-04":"未核实；文件名为建施-10B","TRIAL-05":"电施-05",
           "TRIAL-06":"未取得印刷图号；图名为八层消防平面图","TRIAL-07":"20S206图集页16"}
EXAMPLES=['preview-004被排除：不同字形目标不足以证明环保局页有新增对象关系，未用旧长线补位。',
          'preview-022被排除：A窄间隙附近的边缘归属不清，未借中心线解释或最近黑像素宣布正确。',
          'preview-005与007均保留：说明栏窄线对与楼梯相邻线对有不同源对象上下文，未预置SINGLE/PARALLEL类别。',
          'preview-021保留：喷淋支管与底图轴线的邻接差异；只声明专业新增对象，不编造水/电页面精确配准。']


def recover_raw_context(base, row):
    """Replace only marked pixels using the same-coordinate original grey crop."""
    with Image.open(base/row["preview_files"]["context"]) as im:
        context=im.convert("RGB")
    with Image.open(base/row["preview_files"]["crop"]) as im:
        crop=im.convert("L")
    x,y,w,h=row["source_bbox"]
    cx,cy,cw,ch=row["context_bbox"]
    if not (cx<=x and cy<=y and x+w<=cx+cw and y+h<=cy+ch):
        raise ValueError("Saved grey crop does not fit the existing context frame")
    context.paste(crop.convert("RGB"),(x-cx,y-cy))
    pixels=np.array(context)
    if not (np.array_equal(pixels[:,:,0],pixels[:,:,1]) and np.array_equal(pixels[:,:,0],pixels[:,:,2])):
        raise ValueError("Original context pixels outside the saved crop cannot be recovered")
    return context,pixels[:,:,0]


def read_page_frames(plan):
    frames={}
    for unit in plan["rows"]:
        if unit["page_or_layout"]["type"]!="PDF": continue
        with pdfium.PdfDocument(unit["absolute_read_path"]) as doc:
            page=doc[unit["page_or_layout"]["page_number"]-1]
            try:
                frames[unit["plan_unit"]]={"media_box_pdf":list(page.get_mediabox()),
                    "crop_box_pdf":list(page.get_cropbox()),"page_rotation_degrees":page.get_rotation(),
                    "rotated_display_size_pdf_points":list(page.get_size()),
                    "physical_PDF_page_number":unit["page_or_layout"]["page_number"],
                    "printed_sheet_or_atlas_page":PRINTED[unit["plan_unit"]]}
            finally: page.close()
    return frames


def decorate(row,unit,frame):
    row=copy.deepcopy(row)
    title,identity,reason=DESCRIPTIONS[row["sample_id"]]
    row.update({"short_title":title,"target_identity_description":identity,
                "specific_retain_reason":reason,"container_identity":unit["container_identity"],
                "content_source":unit["content_source"],"source_family_id":unit["content_source"]["family_id"],
                "development_exposure":"修复预览／执行者已逐张查看；非未经接触的盲测素材",
                "user_presentation_state":"未记录用户逐目标查看事件；不伪造点击/呈现日志",
                "batch_use":"repair_preview_only","split":"unassigned_preview",
                "intentional_review":False,
                "geometry_semantics":"LSD检测线段，按原算法作为边缘提名；未确认为中心线或真实实体边界" if row["candidate_geometry"] else "阈值连通墨迹区域；没有线成员",
                "semantic_status":"未赋人工类别；尺寸线、轴线及安装详图的旧任务口径边界待确认",
                "page_frame":frame,
                "box_schemas":{"source_bbox":"xywh in detection raster","context_bbox":"xywh in same raster",
                               "target_roi":"xywh in same raster","legacy_LocalD_boxes":"xyxy in its recorded render frame"},
                "crop_mapping":{"origin_source_px":row["source_bbox"][:2],"size_px":row["source_bbox"][2:],
                    "padding_ltrb_px":[0,0,0,0],"rescaled_source_pixels":False,
                    "placement":"clamped crop placement; observation windows are not crop boxes"},
                "display_mapping":{"crop":"responsive display only; optional 8x nearest-neighbour view",
                                   "extra_DPI_sample":False,"A_start_end":"A起/A止为同一A成员的两个端点，不是两条线"},
                "geometry_fit_note":"原记录的最近墨迹距离仅为局部拟合辅助证据，不证明目标身份；未因轻微偏差修改人工类别"})
    width,height=row["coordinate_frame"]["render_size_px"]
    pw,ph=row["coordinate_frame"]["page_size_points"]
    row["parent_geometry"]=[{"geometry_id":g[0],"detection_role":"LSD_edge_segment_proposal",
       "source_endpoints_px":[p[0]*width/pw,p[1]*height/ph,p[2]*width/pw,p[3]*height/ph],
       "recovery_basis":"recorded parent coordinates plus exact original raster/display frame",
       "final_display_member":"AB"[i]} for i,(g,p) in enumerate(zip(row["candidate_geometry"],row["display_parent_geometry"]))]
    row["normalized_target_identity"]={"container":row["source_entry_id"],"physical_page":row["source_page"],
        "content_id":row["content_source"].get("content_id"),
        "canonical_members":[[g[0],g[1]] for g in canonical_geometry(row["candidate_geometry"])],
        "region_target":row["target_roi"]}
    if row["sample_id"] in ("preview-002","preview-021"):
        row["professional_difference_evidence"]=reason
    row["proxy_is_physical_geometry"] = False
    row["proxy_limitation"]="共线载体/区域只分配呈现名额；未合并门洞两侧、平行边界或原图实体"
    return row


def target_svg(row):
    x,y,_,_=row["source_bbox"]
    groups=[]
    for i,(_,line,_) in enumerate(row["candidate_geometry"]):
        color=("#db2435","#0078aa")[i]
        member="AB"[i]
        points=[(line[k]-x,line[k+1]-y) for k in (0,2)]
        a,b=points
        close=len(row["candidate_geometry"])==2 and row["quality"]["metrics"]["PAIR_SEPARATION_STABILITY"]["mean_px"]<3
        dash=f' stroke-dasharray="4 4" stroke-dashoffset="{i*4}"' if close else ''
        shapes=[f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="0.65" opacity="0.85"{dash}/>']
        for j,(px,py) in enumerate(points):
            shapes.append(f'<circle cx="{px}" cy="{py}" r="1.6" fill="none" stroke="{color}" stroke-width="0.65"/>')
            lx=max(3,min(223,px+(-22 if i==0 else 5)))
            ly=max(10,min(245,py+(-5 if i==0 else 12)))
            shapes.append(f'<text x="{lx}" y="{ly}" font-size="8" fill="{color}" stroke="white" stroke-width="1" paint-order="stroke">{member}{"起" if j==0 else "止"}</text>')
        groups.append(f'<g data-member="{member}">'+''.join(shapes)+'</g>')
    if row["target_roi"]:
        tx,ty,tw,th=row["target_roi"]
        groups.append(f'<g data-member="R"><rect x="{tx-x}" y="{ty-y}" width="{tw}" height="{th}" fill="none" stroke="#db2435" stroke-width=".65"/><text x="{tx-x}" y="{max(8,ty-y-3)}" font-size="8" fill="#db2435">区域目标</text></g>')
    return '<svg viewBox="0 0 256 256" aria-label="候选边缘或区域叠加">'+''.join(groups)+'</svg>'


def shared_page_positions(base,rows):
    directory=base/'pages'
    directory.mkdir(exist_ok=True)
    result={}
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    for unit in sorted({r["plan_unit"] for r in rows}):
        same=[r for r in rows if r["plan_unit"]==unit]
        with Image.open(base/same[0]["preview_files"]["page_position"]) as im: page=im.convert('RGB')
        scale=page.width/same[0]["coordinate_frame"]["render_size_px"][0]
        draw=ImageDraw.Draw(page)
        for row in same:
            x,y,w,h=row["source_bbox"]
            draw.rectangle((x*scale,y*scale,(x+w)*scale,(y+h)*scale),outline='#bd2032',width=2)
            draw.text((x*scale,max(0,y*scale-20)),row["sample_id"][-3:],fill='#bd2032',font=font)
        path=directory/(unit.lower()+'.jpg')
        page.save(path,quality=90)
        result[unit]=path.relative_to(base).as_posix()
    return result


def write_gallery(base,rows,page_table,issues,examples):
    cards=[]
    for row in rows:
        sid=row['sample_id']; e=html.escape
        images=row['preview_files']; source_uri=Path(row['source_path']).as_uri()+f"#page={row['source_page']}"
        geometry_note=row['geometry_fit_note']
        member_note=' / '.join(f"{'AB'[i]}={g[0]}" for i,g in enumerate(row['candidate_geometry'])) or '区域目标，无A/B线成员'
        controls=''.join(f'<button type="button" onclick="mode(this,\'{m}\')">{label}</button>' for m,label in [('none','原图'),('A','只看A'),('B','只看B'),('all','A+B')]) if row['candidate_geometry'] else '<button type="button" onclick="mode(this,\'none\')">原图</button><button type="button" onclick="mode(this,\'all\')">目标框</button>'
        detail=json.dumps({k:row[k] for k in ['parent_geometry','candidate_geometry','source_bbox','context_bbox','target_roi','page_frame',
            'coordinate_frame','box_schemas','crop_mapping','display_mapping','endpoint_coordinate_checks',
            'normalized_target_identity','current_p3a_measurement','feature_profile_geometry_id','profile_member_rule',
            'sampling_conditions','trial_features_18','trial_feature_missing_semantics','history_relation_status']},ensure_ascii=False,indent=2)
        cards.append(f'''<article id="{sid}"><h2>{sid[-3:]} · {e(row['short_title'])}</h2>
<p>{e(row['source_relative_path'])}<br>来源ID：{e(row['source_drawing_id'])} / {e(row['source_entry_id'])}；PDF物理第{row['source_page']}页；印刷标识：{e(row['page_frame']['printed_sheet_or_atlas_page'])}<br>容器族：{e(str(row['container_identity']['document_package_family']))}；内容族：{e(row['source_family_id'])}；用途：修复预览／开发已接触</p>
<div class="views"><figure><a href="{images['page_position']}" target="_blank"><img src="{images['page_position']}" alt="当前候选整页位置"></a><figcaption>红框只表示当前{sid}裁块，不是其他候选或计划观察区；<a href="{images['shared_page_position']}" target="_blank">同页全部位置（次级参考）</a>；<a href="{source_uri}" target="_blank">打开原PDF该页</a></figcaption></figure>
<figure><a href="{images['context_raw']}" target="_blank"><img src="{images['context_raw']}" alt="未叠加上下文"></a><figcaption>未叠加上下文，点击原尺寸</figcaption></figure>
<figure><a href="{images['crop']}" target="_blank"><img src="{images['crop']}" alt="原始灰度裁块"></a><figcaption>原始256×256灰度裁块</figcaption></figure>
<figure><div class="viewport"><div class="crop"><img src="{images['crop']}" alt="同一原始灰度裁块">{target_svg(row)}</div></div><div class="buttons">{controls}<button type="button" onclick="zoom(this,1)">1倍</button><button type="button" onclick="zoom(this,8)">8倍显示</button></div><figcaption>A红、B蓝；起/止为同一成员的两个端点，非两条线或流向。显示放大不增加DPI。</figcaption></figure></div>
<p><b>目标指向：</b>{e(row['target_identity_description'])}。{e(member_note)}<br><b>局部贴合：</b>{e(geometry_note)}<br><b>语义：</b>{e(row['semantic_status'])}</p>
<p>历史关系：{e(row['history_relation_status'])}。本批没有新增有意复核。</p><p class="reason">保留理由：{e(row['specific_retain_reason'])}</p>
<p>测量状态：{e(row['measurement_status'])}；18维选用成员：{e(str(row['feature_profile_geometry_id']))}。按规范化几何选择首个有效成员，未平均A/B。</p>
<details><summary>父几何、端点、坐标和双成员测量</summary><pre>{e(detail)}</pre></details></article>''')
    table_rows=''.join(f"<tr><td>{r['plan_unit']} · PDF第{r['physical_page']}页</td><td>{r['read']}</td><td>{r['search_candidates']}</td><td>{r['supported_candidates']}</td><td>{r['initial_retained']}</td><td>{r['final_retained']}</td><td>{html.escape(r['supplement_removed_reason'])}</td><td>{r['initial_selection_reduction']}</td></tr>" for r in page_table)
    issue_html=''.join(f"<li>{html.escape(i['sample_id'])}：{html.escape(i['reason'])}（原记录和图片保留，未补样）</li>" for i in issues)
    example_html=''.join('<li>'+html.escape(x)+'</li>' for x in examples)
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B 修复预览</title>
<style>body{margin:0;background:#eef1f4;color:#1d2934;font:15px/1.6 system-ui,"Microsoft Yahei",sans-serif}header,main{max-width:1540px;margin:auto;padding:24px}header,article{background:white}h1{font-size:26px;margin:0}h2{font-size:20px;margin:0}article{padding:20px;margin:24px 0;border:1px solid #d4dce3;border-radius:8px}.views{display:grid;grid-template-columns:1.15fr 1.15fr 1fr 1fr;gap:12px}figure{margin:0}figure> a>img{width:100%;height:330px;object-fit:contain;background:#fafafa;border:1px solid #dbe1e6}.viewport{height:330px;overflow:auto;background:#fafafa;border:1px solid #dbe1e6}.crop{width:100%;position:relative;aspect-ratio:1}.crop img{width:100%;display:block;image-rendering:pixelated}.crop svg{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;pointer-events:none}figcaption{font-size:13px;color:#536574}.buttons{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}button{font:inherit;font-size:13px;padding:4px 7px;border:1px solid #bdc8d3;background:white;border-radius:4px;cursor:pointer}.reason{border-left:3px solid #6085a2;padding-left:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f9;padding:10px;font-size:12px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px;border:1px solid #d4dce3;text-align:left}.scroll{overflow:auto}@media(max-width:1050px){.views{grid-template-columns:1fr 1fr}}@media(max-width:620px){.views{grid-template-columns:1fr}header,main{padding:12px}}</style>
<header><h1>P3B 小范围修复预览 · COUNT个可用候选</h1><p>检查取样、指向和显示；不填写分类键，不启动标注或训练。PAIR/SINGLE/CONTROL仅是提名形式。旧94/50及模型保持原样。</p><p>边缘提名保持原始定义；没有把窄间隙中的提名改称中心线。每张提供原灰度、无叠加上下文和独立A/B显示。8倍只放大已有像素。</p><p>TRIAL-07：容器为仓库PDF资料包，内容为20S206图集页16。仓库水第7页与电第6页共享底图；只使用逻辑轴区代理，没有精确跨页配准。三个CAD视图暂缓。</p><p><a href="candidate-index.json">小型候选索引</a> · <a href="manifest.jsonl">完整试用记录</a> · <a href="run.json">局部检查与统计口径</a></p>
<div class="scroll"><table><thead><tr><th>计划页</th><th>读取</th><th>搜索区提名</th><th>像素支持候选</th><th>初版保留</th><th>现在保留</th><th>本次排除</th><th>初版限额/去重减量合计</th></tr></thead><tbody>TABLE</tbody></table></div>
<p>初版质量原因是多标签，不相加。初版去重只保存全局首命中原因，逐页的已看/同区/长线分解未取得；上表合计为支持候选数减初版保留数。本次补充排除单独计数，不重复相加；没有为补统计重渲染。</p><ul>ISSUES</ul><ul>EXAMPLES</ul><p>尺寸、轴线及安装图语义边界仍待确认；目标身份与局部拟合分开说明。本批已经用于开发调试，不能以后称为未接触盲测。</p></header><main>CARDS</main>
<script>function mode(b,m){const f=b.closest('figure');f.querySelectorAll('[data-member]').forEach(g=>g.style.display=(m==='all'||g.dataset.member===m)?'':'none')}function zoom(b,k){const c=b.closest('figure').querySelector('.crop');c.style.width=k===1?'100%':(256*k)+'px'}</script></html>'''
    (base/'index.html').write_text(document.replace('COUNT',str(len(rows))).replace('TABLE',table_rows).replace('ISSUES',issue_html).replace('EXAMPLES',example_html).replace('CARDS',''.join(cards)),encoding='utf-8')


def refine_existing(output):
    base=output.resolve()
    allowed=(ROOT/'local-artifacts/product-fix-p3b').resolve()
    if allowed not in base.parents or not (base/'manifest.jsonl').is_file():
        raise ValueError('Only an existing local P3B preview may be refined')
    run=read(base/'run.json')
    if run['purpose']!='repair_preview_only': raise ValueError('Not a repair preview')
    if run.get('supplement_version')=='preview-supplement-v1':
        print('Existing preview already refined; no new process/render/batch needed.')
        return
    for name in ('manifest.jsonl','run.json','plan.json','index.html'):
        snapshot=base/('initial-'+name)
        if not snapshot.exists():
            with snapshot.open('x',encoding='utf-8',newline='\n') as f:
                f.write((base/name).read_text(encoding='utf-8'))
    initial=read_rows(base/'initial-manifest.jsonl')
    run=read(base/'initial-run.json')
    plan=apply_content_sources(read(base/'plan.json'),read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    units={r['plan_unit']:r for r in plan['rows']}
    # Filter protected associations before reading even page metadata.
    permitted=inventory_build(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    allowed_units={r['plan_unit'] for r in permitted}
    safe_plan={**plan,'rows':[r for r in plan['rows'] if r['plan_unit'] in allowed_units]}
    frames=read_page_frames(safe_plan)  # Metadata only. No page rendering.
    for unit in plan['rows']:
        if unit['plan_unit'] in frames: unit['actual_page_frame']=frames[unit['plan_unit']]
    prepared,windows,issues=[],{},[]
    for original in initial:
        if original['plan_unit'] not in allowed_units:
            issues.append({'sample_id':original['sample_id'],'plan_unit':original['plan_unit'],
                           'reason':'已知保护来源关联，跳过内容读取；不影响其他页面','category':'protected_source_association'})
            continue
        row=decorate(original,units[original['plan_unit']],frames[original['plan_unit']])
        if row['sample_id']=='preview-004':
            issues.append({'sample_id':row['sample_id'],'plan_unit':row['plan_unit'],'reason':'旧上下文中的编号字形局部；未取得TRIAL-06要求的新增对象关系差异','category':'relation_difference_not_established'})
            continue
        if row['sample_id']=='preview-022':
            issues.append({'sample_id':row['sample_id'],'plan_unit':row['plan_unit'],'reason':'A边缘提名落在窄间隙附近，源边缘归属不清；最近黑像素及坐标往返不能证明身份','category':'unclear_edge_attachment'})
            continue
        context,pixels=recover_raw_context(base,row)
        path=base/row['sample_id']/'context-raw.png'
        context.save(path)
        row['preview_files']['context_raw']=path.relative_to(base).as_posix()
        windows[row['sample_id']]=(pixels,row['context_bbox'][:2],row['coordinate_frame']['render_size_px'])
        prepared.append(row)
    sources=inventory_build(page_plan=plan,supplement=read(ROOT/'docs/product-fix-p3b/SOURCE-SUPPLEMENT-20261010.json'))
    history,_=load_history(plan,sources)
    for row in prepared:
        rejection,_,notes=history_relation(row,history)
        if rejection: raise ValueError(f"Existing retained target now conflicts with history: {row['sample_id']} {rejection}")
        samepage=[h for h in history if h['source_drawing_id']==row['source_drawing_id'] and h['source_page']==row['source_page']]
        row['history_relation_code']='different_target_outside_recorded_regions' if samepage and not notes else 'history_incomplete_unknown'
        row['history_relation_status']=(
            '同页已有目标/上下文记录，本目标在这些区域之外；现有记录未命中同目标，仍非全新图纸' if samepage and not notes else
            '历史不足，无法确认是否曾看；现有可映射记录未命中同目标')+'；V1事件不完整，跨格式对应有限；本批没有有意复核'
        row['historical_relations']=notes
    chosen,_,new_selection=select_preview(prepared,history,{})
    chosen_ids={r['sample_id'] for r in chosen}
    for row in prepared:
        if row['sample_id'] not in chosen_ids:
            issues.append({'sample_id':row['sample_id'],'plan_unit':row['plan_unit'],'reason':'补充限额/复用关系检查未保留；没有新增替代目标','category':'supplement_selection'})
    # Preserve original stable numbering and page rotation; no new nominations.
    chosen=[r for r in prepared if r['sample_id'] in chosen_ids]
    train=train_measure(chosen,windows)
    validation=validation_measure(chosen,windows)
    reverse=copy.deepcopy(chosen)
    for row in reverse:
        row['candidate_geometry']=[[g[0],g[1][2:]+g[1][:2],g[2]] for g in reversed(row['candidate_geometry'])]
    reversed_measured=train_measure(reverse,windows)
    for a,b,c in zip(train,validation,reversed_measured):
        if a['current_p3a_measurement']!=b['current_p3a_measurement']: raise ValueError('Two entry measurements differ')
        aa=[{k:v for k,v in m.items() if k!='display_member'} for m in a['current_p3a_measurement']]
        cc=[{k:v for k,v in m.items() if k!='display_member'} for m in c['current_p3a_measurement']]
        if aa!=cc or a['feature_profile_geometry_id']!=c['feature_profile_geometry_id']: raise ValueError('Member canonicalization differs')
        va=feature_vector(a,base/a['sample_id'])
        vb=feature_vector(b,base/b['sample_id'])
        vc=feature_vector(c,base/c['sample_id'])
        if not np.array_equal(va,vb) or not np.array_equal(va,vc): raise ValueError('18-vector selection depends on entry/member order')
        a['trial_features_18']=va.tolist()
        a['trial_feature_missing_semantics']={
            'zero_placeholders':[k for k in ('distance_px','angle_delta_deg','overlap_px') if k not in a.get('features',{})],
            'profile_zero_placeholders':a['feature_profile_geometry_id'] is None,
            'profile_known_flag':'width_known=0 indicates missing; width/stability/core/offset/sample/contrast zeros then are placeholders',
            'real_zero_examples':'present measured angle delta or centre offset may equal zero; measured source pixel statistics may equal zero',
            'unchanged_contract':'existing 18 names/order, pair_present, scaler and old frozen vectors remain unchanged'}
        a['measurement_provenance']='same saved unoverlaid source window, actual full-page sampling shape/origin; no inherited profile'
    shared=shared_page_positions(base,train)
    for row in train: row['preview_files']['shared_page_position']=shared[row['plan_unit']]
    oldcounts=Counter(r['plan_unit'] for r in initial)
    finalcounts=Counter(r['plan_unit'] for r in train)
    table=[]
    for page in run['pages']:
        unit=page['plan_unit']; counts=page['proposal_counts']
        defined_regions=cells_for(units[unit],page['coordinate_frame'])
        units[unit]['selection_regions_defined_before_candidates']=defined_regions
        units[unit]['selection_region_rule']='Each approximate observation window was divided into a fixed 2x2 search grid before detection; region IDs are not created per candidate'
        table.append({'plan_unit':unit,'physical_page':page['page'],'read':True,
            'search_candidates':counts['in_search_cells'],'supported_candidates':counts['supported_targets'],
            'initial_retained':oldcounts[unit],'final_retained':finalcounts[unit],
            'initial_selection_reduction':counts['supported_targets']-oldcounts[unit],
            'initial_per_reason_reductions':None,
            'reason_detail_limit':'初版只存全局首命中原因，逐页细分未取得；未重跑/重渲染回补',
            'supplement_removed':oldcounts[unit]-finalcounts[unit],
            'supplement_removed_reason':'；'.join(i['reason'] for i in issues if i['plan_unit']==unit) or '0',
            'quality_flags_nonexclusive':{k:v for k,v in counts.items() if k not in ('in_search_cells','supported_targets')}})
    examples=EXAMPLES
    write_gallery(base,train,table,issues,examples)
    write_rows(base/'manifest.jsonl',train)
    atomic_json(base/'plan.json',plan)
    index=[{k:r[k] for k in ['sample_id','short_title','source_drawing_id','source_entry_id','source_relative_path','source_page','page_frame','container_identity','content_source','target_kind','candidate_geometry_ids','specific_retain_reason','history_relation_code','history_relation_status','measurement_status','feature_profile_geometry_id','preview_files']} for r in train]
    atomic_json(base/'candidate-index.json',{'purpose':'repair_preview_only','label_fields_present':False,'rows':index,'excluded_existing_candidates':issues})
    run.update({'supplement_version':'preview-supplement-v1','selected':len(train),'supplement_issues':issues,
        'per_page_table':table,'supplement_selection':new_selection,
        'profile_status_counts':dict(Counter(r['measurement_status'] for r in train)),
        'actual_same_target_measurement_check':{'targets':len(train),'two_real_entries':'prepare_v2.measure_trial_targets / validation_v2.measure_trial_targets',
           'source_pixels':'recovered unoverlaid existing context using exact saved grey crop coordinates',
           'profile_members_equal':True,'18_vectors_equal':True,'A_B_swap_and_endpoint_reverse_equal':True,
           'old_94_50_measured':False,'PDF_pages_rerendered':0},
        'visual_inspection':{'initial_candidates_inspected':22,'usable_candidates':len(train),'coverage':'all used pages; unoverlaid crop/context and existing whole-page locations, including rotation270 and page-edge crop',
            'semantic_labels_assigned':0,'geometry_error_is_not_target_identity':True},
        'pair_budget_change_scope':'区域预算已接入后续明确试用入口；本批复用既有提名，未重跑旧提名池。初版逐区比较次数未取得。',
        'local_check_scope':'14 tests in test_trial_sampling.py; actual 20 target two-entry/profile/18-vector canonicalization comparison; no full suite',
        'browser_interaction_check':'未取得：内置浏览器安全策略拒绝file://；未用其他浏览器或HTTP方式绕过',
        'history_coordinate_mapping':'本轮7页MediaBox=CropBox且原点为0；Local-D既有PNG尺寸与记录一致。旋转与旧pdftoppm MediaBox读取方式核对后使用各轴实际比例；保留取整误差，不称精确配准',
        'development_exposure':'This batch has been accessed for repair/debugging; never claim untouched blind provenance',
        'new_pdf_renders':0,'new_candidates':0,'new_batches':0})
    atomic_json(base/'run.json',run)
    print(f"Refined existing preview: {base/'index.html'}; {len(train)} usable; {len(issues)} excluded; no new PDF render/batch")


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    refine_existing(parser.parse_args().output)
