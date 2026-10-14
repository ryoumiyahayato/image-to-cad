"""Export a saved new-page trial as one HTML file; no detection or labeling."""

import argparse
import base64
import gzip
import html
import io
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from preview_selection import iou, same_page
from trial_sampling import to_display


def escaped(value):
    return html.escape(str(value), quote=True)


def data_image(im):
    buffer = io.BytesIO()
    im.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def rectangle(box, color, width=1):
    x, y, w, h = box
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def overlay(row, raw_url):
    x, y, w, h = row['source_bbox']
    parts = [f'<svg class="target" viewBox="0 0 {w} {h}" role="img" aria-label="原像素及提名叠加">',
             f'<image href="{raw_url}" width="{w}" height="{h}"/>']
    close = row['quality']['metrics'].get('PAIR_SEPARATION_STABILITY', {}).get('mean_px', 100) < 3
    for i, (gid, line, _) in enumerate(row['candidate_geometry']):
        a, b = 'AB'[i], ('#d62036', '#0074ad')[i]
        px, py, qx, qy = line[0]-x, line[1]-y, line[2]-x, line[3]-y
        dash = f'stroke-dasharray="4 4" stroke-dashoffset="{i*4}"' if close else ''
        parts.append(f'<g class="member-{a}"><title>{escaped(gid)}</title><line x1="{px}" y1="{py}" x2="{qx}" y2="{qy}" stroke="{b}" stroke-width=".65" {dash}/>')
        for j, (ex, ey) in enumerate(((px, py), (qx, qy)), 1):
            lx = min(max(ex+(-21 if i == 0 else 5), 2), w-22)
            ly = min(max(ey+(-9 if i == 0 else 11), 9), h-2)
            parts.append(f'<circle cx="{ex}" cy="{ey}" r="1.6" fill="none" stroke="{b}" stroke-width=".65"/><text x="{lx}" y="{ly}" fill="{b}" stroke="white" stroke-width="1.8" paint-order="stroke" font-size="8">{a}{j}</text>')
        parts.append('</g>')
    if row['target_roi']:
        tx, ty, tw, th = row['target_roi']
        parts.append('<g class="region-target">' + rectangle([tx-x, ty-y, tw, th], '#d62036', .65) + '</g>')
    return ''.join(parts) + '</svg>'


def page_location(row, image, unit):
    x, y, w, h = row['source_bbox']
    iw, ih = image.size
    return (f'<svg viewBox="0 0 {iw} {ih}" role="img" aria-label="整页与当前裁框">'
            f'<use href="#page-{escaped(unit)}"/>' + rectangle([x, y, w, h], '#d62036', max(iw, ih)/350) + '</svg>')


def geometry_details(row):
    lines = []
    for i, (gid, g, _) in enumerate(row['candidate_geometry']):
        lines.append(f'{"AB"[i]}={gid}；源栅格端点 ' + ', '.join(f'{v:.3f}' for v in g))
    if row['target_roi']:
        lines.append('区域目标，无A/B成员；源栅格ROI(x,y,w,h)=' + str(row['target_roi']))
    lines.append('最终源栅格裁框(x,y,w,h)=' + str(row['source_bbox']))
    lines.append('纸面裁框(左,上,右,下，PDF点)=' + str([round(v, 3) for v in row['display_crop_box']]))
    lines.append('纸面端点=' + str([[round(v, 3) for v in g] for g in row['display_geometry']]))
    return '<br>'.join(escaped(s) for s in lines)


def statistics(run):
    def counts(v):
        return ' / '.join(str(v.get(k, 0)) for k in ('PAIR', 'SINGLE', 'CONTROL'))
    trs = []
    for s in run['statistics']:
        excluded = sum(s['excluded_by_selection'].values()) - s['exact_target_dedup']
        trs.append(f'<tr><td>{escaped(s["source"])}</td><td>{s["page"]}</td>'
                   f'<td>{counts(s["nominated"])}</td><td>{counts(s["quality_pass"])}</td>'
                   f'<td>{s["exact_target_dedup"]}</td><td>{excluded}</td>'
                   f'<td>{counts(s["selected"])}</td><td>{s["ordinary"]}+{s["extra"]}</td></tr>')
    control = []
    for s in run['statistics']:
        reasons = s['CONTROL_selection_reasons']
        control.append(f'<tr><td>{s["plan_unit"]}</td><td>{s["raw_nomination_kind_counts"]["CONTROL"]}</td>'
                       f'<td>{s["nominated"]["CONTROL"]}</td><td>{s["quality_pass"]["CONTROL"]}</td>'
                       f'<td>{sum(reasons.values())}</td><td>{s["selected"]["CONTROL"]}</td>'
                       f'<td>区域上限 {reasons.get("region_cap",0)}；跨类型裁区 {reasons.get("cross_kind_region_occupancy",0)}；页/族名额 {reasons.get("page_or_design_cap",0)}</td></tr>')
    return (f'<table><caption>计划区域内提名及实际保留；三项顺序均为PAIR / SINGLE / CONTROL</caption>'
            f'<thead><tr><th>原图ID</th><th>页</th><th>提名</th><th>质量通过</th><th>同目标去重</th><th>区域/名额排除</th><th>最终</th><th>普通+额外</th></tr></thead><tbody>{"".join(trs)}</tbody></table>'
            '<p>区域/名额排除不等于重复目标。质量失败原因可同时发生；上表仅计实际通过数量。</p>'
            f'<details><summary>CONTROL真实入口数量与卡点</summary><table><thead><tr><th>页单元</th><th>全页产生</th><th>落入区域</th><th>基础质量通过</th><th>选择排除</th><th>最终</th><th>首次触发原因</th></tr></thead><tbody>{"".join(control)}</tbody></table>'
            '<p>CONTROL入口为阈值160、8连通墨迹；基础质量只查墨迹与裁边。通过不代表完整字符、符号或非线条对象。</p></details>')


def export(directory):
    directory = Path(directory)
    rows = [json.loads(l) for l in (directory/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    run = json.loads((directory/'run.json').read_text(encoding='utf-8'))
    plan = json.loads((directory/'page-plan.json').read_text(encoding='utf-8'))
    units = {u['plan_unit']: u for u in plan['rows']}
    sources = {u: Image.open(directory/'sources'/u/'source.png').convert('L') for u in units}
    with gzip.open(directory/'eligible-pool.jsonl.gz', 'rt', encoding='utf-8') as f:
        pool = {r['sample_id']: r for r in map(json.loads, f)}
    assert len(rows) <= 18 and len({r['sample_id'] for r in rows}) == len(rows)
    assert all(r['label'] is None and not r['training_authorized'] for r in rows)
    checks, cards, defs = [], [], []
    for unit, src in sources.items():
        view = Image.open(directory/'sources'/unit/'page-view.png').convert('L')
        defs.append(f'<image id="page-{unit}" href="{data_image(view)}" width="{src.width}" height="{src.height}" preserveAspectRatio="none"/>')
    review = {
        'proposal-NEW-01-000668': '异常：标框仅覆盖虚线中的9×1px短段。没有独立字符或非线条对象依据，不能认作有效字符。',
        'proposal-NEW-03-000370': '异常：标框覆盖116×2px墙边墨迹。CONTROL基础质量未区分线条片段与字符，工程语义未确认。',
        'proposal-NEW-04-000506': '指向抽查：可辨认字母Z的墨迹范围；连通框是否独占字符仍未认证。没有赋OTHER或其他人工类别。',
        'proposal-NEW-02-000505': '指向抽查：可辨认字母F的墨迹范围；字符语义及最终产品处理未决定。没有赋人工类别。',
        'proposal-NEW-01-001290': '区域同时含楼梯、填充与注记；提名指向竖边。几何支持不能单独决定对象范围或人工类别。',
        'proposal-NEW-04-000845': '提名指向斜向填充下方的水平边；源边可定位，但填充/规则边界归属未决定。',
    }
    for n, row in enumerate(rows, 1):
        unit = row['plan_unit']; src = sources[unit]; x, y, w, h = row['source_bbox']
        original = pool[row['sample_id']]
        assert row['candidate_geometry'] == original['candidate_geometry']
        assert row['target_roi'] == original['target_roi']
        assert 0 <= x < x+w <= src.width and 0 <= y < y+h <= src.height
        assert list(src.size) == row['coordinate_frame']['render_size_px']
        error = 0
        for (_, g, _), display in zip(row['candidate_geometry'], row['display_geometry']):
            error = max(error, max(abs(a-b) for a,b in zip(to_display(g, row['coordinate_frame']), display)))
            assert all(0 <= g[i]-x <= w and 0 <= g[i+1]-y <= h for i in (0,2))
        assert error < 1e-7
        raw = src.crop((x,y,x+w,y+h)); raw_url = data_image(raw)
        assert np.array_equal(np.asarray(raw), np.asarray(Image.open(io.BytesIO(base64.b64decode(raw_url.split(',',1)[1])))))
        cx1, cy1, cx2, cy2 = max(0,x-160), max(0,y-160), min(src.width,x+w+160), min(src.height,y+h+160)
        context = src.crop((cx1,cy1,cx2,cy2))
        overlaps = [{'target': old['sample_id'], 'crop_iou': round(iou(row['display_crop_box'],old['display_crop_box']),4)}
                    for old in rows if old is not row and same_page(row,old) and iou(row['display_crop_box'],old['display_crop_box']) > 0]
        overlap_text = '；'.join(f'{o["target"]}：裁框IoU={o["crop_iou"]}' for o in overlaps) or '本批其他裁框不相交'
        title = units[unit]['page_or_layout']['title']
        reason = '<li>'+'</li><li>'.join(escaped(s) for s in row['retain_reasons'])+'</li>'
        extra = row.get('difficulty_difference', {})
        if extra:
            reason += ('<li>额外依据：源像素支持及方向支持通过；与比较输出的法向支持带不重叠/方向不同，新增几何载体成员 '
                       + escaped(', '.join(extra['new_geometric_carrier_members']))
                       + '。未覆盖范围单独不足以入选；没有确认建筑对象、节点、开口或工程语义。</li>')
        kind_info = '区域目标，无A/B成员' if row['target_kind']=='CONTROL' else ('一个A目标，无B成员' if row['target_kind']=='SINGLE' else 'A/B两条提名，不表示人工类别2')
        controls = '<button data-layer="none">原图</button><button data-layer="all">提名叠加</button>'
        if row['candidate_geometry']:
            controls += '<button data-layer="A">只看A</button>'
            if len(row['candidate_geometry'])==2: controls += '<button data-layer="B">只看B</button>'
        note = review.get(row['sample_id'], '源墨迹及几何可定位；对象归属与一条/两条的人工类别未确认。')
        card = f'''<article id="candidate-{n}" data-mode="all">
<h2>第{n}项 / {len(rows)}　{escaped(row['sample_id'])} <small>{'额外机会' if row.get('difficult_addition') else '普通名额'}</small></h2>
<p>{escaped(unit)} · {escaped(row['source_drawing_id'])} · 第{row['source_page']}页 · {escaped(title)}<br>{escaped(row['source_family_id'])} · {escaped(row['region_id'])}</p>
<p class="note">{escaped(note)}</p>
<div class="images"><figure>{page_location(row,src,unit)}<figcaption>整页定位：红框为当前最终裁框；点击图片可放大浏览</figcaption></figure>
<figure><img class="context" src="{data_image(context)}" alt="无叠加上下文"><figcaption>无叠加上下文，{context.width}×{context.height}源像素；裁框外扩160px</figcaption></figure>
<figure><img class="raw" src="{raw_url}" alt="原始灰度裁块"><figcaption>原始灰度裁块，{w}×{h}；未修改像素</figcaption></figure>
<figure><div class="layer-buttons">{controls}<select aria-label="显示缩放"><option value="1">显示1倍</option><option value="2" selected>显示2倍</option><option value="3">显示3倍</option></select></div><div class="zoom">{overlay(row,raw_url)}</div><figcaption>{kind_info}。端点A1/A2/B1/B2仅为位置编号，无流向含义。显示放大不增加源信息。</figcaption></figure></div>
<details><summary>来源、目标、实际坐标与保留依据</summary><p>{escaped(row['source_relative_path'])}<br>现有划分：{escaped(row['source_existing_split'])}；本批用途：开发预览，未分配训练标签。<br>有效渲染DPI：{row['source_dpi']:.3f}；栅格 {src.width}×{src.height}；页面旋转 {row['coordinate_frame']['page_rotation']}°</p>
<p>{geometry_details(row)}</p><ul>{reason}</ul><p>本批重叠：{escaped(overlap_text)}。裁框相交不等于相同目标。</p>
<p>历史：同文件/页码未取得登记呈现目标；同族其他页已有开发接触，V1事件日志不完整，不能声称用户从未看过。</p>
<p>CAD：{escaped(units[unit]['CAD_pair_status']['detail'])}；本页无已确认同图同版坐标配准资料参与检测。</p></details></article>'''
        cards.append(card)
        checks.append({'proposal':row['sample_id'],'geometry_unchanged':True,
                       'paper_mapping_max_error_pt':error, 'raw_pixels_match_source':True,
                       'context_box_source_px':[cx1,cy1,cx2,cy2], 'batch_crop_overlaps':overlaps,
                       'source_object_observation':note})
    examples = []
    for ex in run['review_exceptions'][:2]:
        r = pool[ex['proposal']]; x,y,w,h = r['source_bbox']
        src = sources[r['plan_unit']]; raw_url=data_image(src.crop((x,y,x+w,y+h)))
        if ex['proposal']=='proposal-NEW-01-000117':
            cause='未保留：首次额外选择只证明沿同载体还有未覆盖局部，不能证明新的几何关系；新规则不据此增加额外名额。最终普通入口触发页/族名额。'
        else:
            cause='未保留：原额外理由仅比较邻近CONTROL，没有线几何关系证据。不能把文字邻近的一条线自动当新工程关系；最终触发区域上限。'
        examples.append(f'<section><h3>{escaped(ex["proposal"])}</h3>{overlay(r,raw_url)}<p>{cause}</p></section>')
    exceptions = ('<h2>最多四个异常/未保留例</h2><div class="examples">'+''.join(examples)+
                  '<section><h3>proposal-NEW-01-000668</h3><p>已保留供检查的CONTROL：9×1px虚线短段。基础质量通过，不是有效字符依据。见第9项。</p></section>'
                  '<section><h3>proposal-NEW-03-000370</h3><p>已保留供检查的CONTROL：116×2px墙边片段。不能据CONTROL形式赋OTHER。见第12项。</p></section></div>')
    unchecked = sum(s['unchecked_pair_comparisons'] for s in run['statistics'])
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>P3B 新页面取样预览 · 20261011-001</title><style>
body{margin:0;background:#f2f4f6;color:#172630;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1600px;margin:auto;padding:24px}h1{font-size:28px}h2{font-size:20px;overflow-wrap:anywhere}h3{font-size:16px}small{font-size:13px;color:#65727a}article,header,.summary{background:white;padding:22px;margin:20px 0;border:1px solid #dce3e7;border-radius:8px}p{margin:12px 0}.note{background:#fff4d8;border-left:3px solid #b77a18;padding:10px}table{border-collapse:collapse;font-size:14px;width:100%;background:white}th,td{border:1px solid #ccd7df;padding:8px;text-align:left}caption{text-align:left;padding:10px 0;font-weight:600}.images{display:grid;grid-template-columns:1fr 1fr;gap:18px}figure{margin:0;min-width:0;overflow:auto;border:1px solid #dce3e7;padding:8px}figure>svg,img.context{display:block;width:100%;height:auto}img.raw{display:block;width:512px;max-width:100%;image-rendering:pixelated}svg.target{display:block;width:512px;max-width:none;background:white;image-rendering:pixelated}.zoom{overflow:auto}figcaption{font-size:13px;color:#53646d;margin-top:8px}button,select{background:#f6f8fa;color:#172630;padding:7px 12px;border:1px solid #b9c8d1;border-radius:4px;margin:3px;cursor:pointer}details{padding:10px 0}summary{cursor:pointer;font-weight:600}article[data-mode=none] .member-A,article[data-mode=none] .member-B,article[data-mode=none] .region-target{display:none}article[data-mode=A] .member-B,article[data-mode=B] .member-A{display:none}.examples{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}.examples section{background:white;padding:16px}.examples svg.target{max-width:100%}a{color:#00669b}nav{display:flex;gap:12px;flex-wrap:wrap}figure>svg:fullscreen,figure>img:fullscreen{background:white;object-fit:contain}@media(max-width:850px){main{padding:10px}.images,.examples{grid-template-columns:1fr}table{display:block;overflow:auto}}
</style><main>'''
    document += f'''<header><h1>P3B 新页面端到端取样预览</h1><p>16项：4 PAIR / 8 SINGLE / 4 CONTROL。四个设计族，四个新文件/页面；每页3个普通名额＋1个有界几何差异机会。候选形式不是人工类别。本页无标注、保存答案或训练功能。</p>
<p>源PDF→显式页→实际87.511/110DPI栅格→LSD与CONTROL→计划区域→源像素质量→目标代表→历史/跨类型区域→页/区域/长线限额→有限额外→最终裁框。</p>
<p>新东方改造建施09A第1页、九龙消防电气第9页、环保局消防扫描第9页、综合仓库水专业第8页。它们未参与既定修复窗口。环保局页由3303×2335嵌入扫描图生成110DPI栅格；扫描仪DPI未取得，没有声称插值增加细节。</p>
<nav>{''.join(f'<a href="#candidate-{i}">{i:02}</a>' for i in range(1,17))}</nav></header>
<div class="summary">{statistics(run)}<p>四页的普通输出均覆盖两个计划观察区，未按第一页来源或第一个窗口耗尽名额。两个初版额外项仅有未覆盖理由，修正后没有保留。4个当前额外项有源支持与几何载体差异，工程对象关系仍未确认。</p>
<p>CONTROL可提名字母Z/F，但另两项仍是线条片段；字符独占边界未通过此入口解决。当前批有相交裁框，用额外名额保留不同几何关系，不能宣称零结构重复或语义准确率。</p>
<p>每个区域最多600次配对比较；{unchecked}个原始组合未检查，未取得其中剩余有效线对数。全页大幅图未一律320DPI渲染。本轮没有测试非零页面旋转的真实输入。</p>
<p>CAD未取得同图同版及坐标配准关系，未用于真值。历史默认排除生效；原验证和盲测来源未用于此次页面试验，未打开盲测内容。旧94/50、人工答案、模型和生产输出没有改动。</p></div>
<svg width="0" height="0" aria-hidden="true"><defs>{''.join(defs)}</defs></svg>{''.join(cards)}{exceptions}
<p>本批仅供用户检查生成与选择质量。停止在预览，不自动开始标注或下一批。</p></main>
<script>
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>b.closest('article').dataset.mode=b.dataset.layer));
document.querySelectorAll('select').forEach(s=>s.addEventListener('change',()=>s.closest('figure').querySelector('.target').style.width=(256*Number(s.value))+'px'));
document.querySelectorAll('figure>svg,figure>img').forEach(i=>i.addEventListener('click',()=>{{if(i.requestFullscreen)i.requestFullscreen()}}));
</script></html>'''
    destination = directory/'index.html'
    destination.write_text(document, encoding='utf-8')
    # Checks belong to this run; never write to historical labels/features.
    run['preview_checks'] = {'selected_count':len(rows),'referenced_images_embedded':True,
                             'source_pixel_and_mapping_checks':checks,
                             'visual_review_limit':'source-directed observations, not human classifications; browser interactions not automated'}
    run['CONTROL_object_observations'] = {'recognizable_letter_proposals':2,
                                         'linear_ink_fragment_proposals':2,
                                         'exclusive_glyph_boundary_confirmed':False,
                                         'labels_assigned':0}
    (directory/'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'preview':str(destination.resolve()),'candidates':len(rows),
                      'kind_counts':dict(Counter(r['target_kind'] for r in rows)),
                      'bytes':destination.stat().st_size,'coordinate_and_raw_checks':len(checks)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    export(parser.parse_args().directory)
