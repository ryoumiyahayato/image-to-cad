"""Bounded selection-only comparison from the persisted three-page pool."""

import copy
import html
import zipfile
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

from common import ROOT, atomic_json, read, read_rows, write_rows
from queue_dedup import deduplicate
from selection_targets import coverage_against_outputs

PREVIOUS = ROOT/'local-artifacts/product-fix-p3b/local-lifecycle-20261011-001'
SOURCES = ROOT/'local-artifacts/product-fix-p3b/local-scale-20261011-001'
OUT = ROOT/'local-artifacts/product-fix-p3b/selection-fix-20261011-001'


def run():
    if OUT.exists():
        raise ValueError('Existing comparison is preserved; do not silently overwrite')
    old = read(PREVIOUS/'results.json')
    pool = read_rows(PREVIOUS/'eligible-pool.jsonl')
    previous_selected = read_rows(PREVIOUS/'selected-diagnostic-targets.jsonl')
    config = old['selection']['configuration']
    ordinary, _, ordinary_stats = deduplicate(copy.deepcopy(pool), None, preview_policy=config,
                                              preview_mode='development_replay')
    selected, _, selection = deduplicate(copy.deepcopy(pool), None,
                                         preview_policy={**config, 'max_difficult_page': 1},
                                         preview_mode='development_replay')
    positions = {p['reference_id']: p for p in old['positions']}
    by_id = {r['sample_id']: r for r in pool}
    before_decisions = {d['proposal']: d for d in old['selection']['decisions']}
    after_decisions = {d['proposal']: d for d in selection['decisions']}
    comparison = []
    for sid in ('preview-010', 'preview-015', 'preview-001', 'preview-007', 'preview-006'):
        position = positions[sid]
        nomination = position['new_associated_nomination']
        target = by_id[nomination['sample_id']] if nomination else None
        comparison.append({'reference_id': sid, 'target': target['sample_id'] if target else None,
            'source_drawing_id': position['original_fixed_target']['source_drawing_id'],
            'source_relative_path': position['source_relative_path'], 'source_page': position['source_page'],
            'source_edge_association': position['association_after_detection'],
            'before_decision': before_decisions.get(target['sample_id']) if target else None,
            'after_decision': after_decisions.get(target['sample_id']) if target else None,
            'before_coverage': coverage_against_outputs(target, previous_selected) if target else None,
            'ordinary_after_coverage': coverage_against_outputs(target, ordinary) if target else None,
            'after_coverage': coverage_against_outputs(target, selected) if target else None,
            'label_inherited': False})
    page_counts = []
    for page, count in sorted(Counter(r['plan_unit'] for r in pool).items()):
        example = next(r for r in pool if r['plan_unit'] == page)
        rejections = selection['primary_rejections_per_page'].get(page, {})
        page_counts.append({'page_plan': page, 'source_drawing_id': example['source_drawing_id'],
            'source_page': example['source_page'], 'pool': count,
            'exact_target_representatives_removed': rejections.get('same_target_representative', 0),
            'before': old['selection']['selected_per_page'].get(page, 0),
            'after_ordinary': selection['ordinary_selected_per_page'].get(page, 0),
            'after_extra': selection['selected_difficult_per_page'].get(page, 0),
            'not_retained': sum(rejections.values()),
            'unexamined': selection['unexamined_after_total_cap_per_page'].get(page, 0)})
    report = {'purpose': 'development_selection_only_saved_pool_comparison',
        'SELECTION_FIX_RESULT': '部分改善',
        '007_PAIR_RETAINED': 'YES' if next(p for p in comparison if p['reference_id']=='preview-007')['after_coverage']['full_target_coverage_fraction'] >= .98 else 'NO',
        '006_UNCLEAR_NOMINATION_WITHHELD': 'YES' if positions['preview-006']['new_associated_nomination'] is None else 'NO',
        'input': str((PREVIOUS/'eligible-pool.jsonl').relative_to(ROOT)),
        'page_plan': str((SOURCES/'local-plan.json').relative_to(ROOT)),
        'same_ordinary_caps_and_total_budget': True,
        'extra_configuration_difference': {'before_max_difficult_page': config['max_difficult_page'], 'after_max_difficult_page': 1},
        'ordinary_before': len(previous_selected), 'ordinary_after': len(ordinary), 'extra_after': len(selected)-len(ordinary),
        'before_selection': old['selection'], 'ordinary_after_selection': ordinary_stats,
        'after_selection': selection, 'positions': comparison, 'page_counts': page_counts,
        'source_edge_geometry_changed': False, 'detector_or_renderer_run': False,
        'source_images_changed': False, 'labels_assigned': 0, 'training_run': False,
        'profile_policy': 'No remeasurement or inherited cached profile; unchanged saved geometry/quality only. This is not a feature export.',
        'TEST_SCOPE': {'new_direct_checks_passed': 8, 'existing_direct_checks_passed': 3,
            'checks': ['complete target representative', 'shared member vs full relation', 'interval union/gaps/parallel edges',
                'same crop distinct target burden', 'saved pool order and endpoint reversal',
                'real coverage and unchanged geometry/007/006 pool boundary', 'default history exclusion',
                'CONTROL opportunity and bounded extra accounting', 'existing difficult identity and region/long-line caps'],
            'full_suite_run': False, 'unrelated_security_alignment_review': 0,
            'total_task_time_or_cost': '未取得'},
        'NEXT_STEP': '可开展有界真实页面候选质量试验；尚未验证真实CONTROL及完整新页生成路径。本轮不生成下一批。',
        'limits': ['same-source edge evidence is not semantic object identity or a human class',
                   '010 SINGLE not separately selected; its entire member is present in another PAIR',
                   '001 full relation remains absent, despite one fully covered member',
                   '135 line-only proposals on three saved pages; no end-to-end distribution claim']}
    OUT.mkdir(parents=True)
    atomic_json(OUT/'results.json', report)
    write_rows(OUT/'selected-diagnostic-targets.jsonl', selected)
    deliver(report, positions, pool, previous_selected, ordinary, selected)
    print('selection-only comparison:', len(pool), 'saved proposals;', len(ordinary), 'ordinary +', len(selected)-len(ordinary), 'extra;', OUT)


def deliver(report, positions, pool, before, ordinary, after):
    assets = OUT/'images'
    assets.mkdir(exist_ok=True)
    title = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 26)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    small = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 16)
    purple, green = (168, 33, 175), (0, 131, 93)

    def pane(sid, rows, box, size):
        with Image.open(SOURCES/sid/'native.png') as source:
            image = source.convert('RGB')
        draw = ImageDraw.Draw(image)
        origin = positions[sid]['native_window']['origin_px']
        requested = positions[sid]['new_associated_nomination']
        if requested:
            for member in requested['candidate_geometry']:
                g = member[1]
                p = [g[i]-origin[i % 2] for i in range(4)]
                dx, dy = p[2]-p[0], p[3]-p[1]
                extent = (dx*dx+dy*dy)**.5
                for offset in range(0, int(extent), 12):
                    end = min(extent, offset+6)
                    draw.line([p[0]+dx*offset/extent, p[1]+dy*offset/extent,
                               p[0]+dx*end/extent, p[1]+dy*end/extent], fill=(20, 97, 205), width=2)
        for row in rows:
            for member in row['candidate_geometry']:
                g = member[1]
                p = [g[i]-origin[i % 2] for i in range(4)]
                color = green if row.get('difficult_addition') else purple
                draw.line(p, fill=color, width=3)
                for x, y in zip(p[::2], p[1::2]):
                    draw.ellipse((x-3, y-3, x+3, y+3), fill=color)
        image = image.crop(box)
        image.thumbnail(size, Image.Resampling.NEAREST)
        return image

    explanations = {
        'preview-010': ('010｜不同源笔画：原区域占用没有代表072',
            ['原来：036＋167在上方同一笔画附近，占用相近裁区。',
             '同限额修正：072＋036；相同长度档内，平均墨迹距离／支持半径更小。',
             '072请求区间覆盖99.9994%；独立SINGLE仍未输出，不能声称两个任务等价。']),
        'preview-015': ('015｜共享142不等于完整覆盖',
            ['原来：117＋142，只覆盖142请求区间38.1275%。',
             '普通名额：106＋142；仍为短PAIR，不能代表完整单线。',
             '额外名额：142完整SINGLE；新增84.75纸面点未覆盖范围，含下方上下文。',
             '按真实区间并集计算；没有补间隙、合线或修改几何。']),
        'preview-001': ('001｜完整关系仍未输出，不用共享成员冒充恢复',
            ['原来和现在：112＋686；001所需686＋257已在池中且质量通过。',
             '686约100%保留，257为0%；完整线对关系为0%，并非等价输出。',
             '普通页面名额2已满；总预算6的额外机会用于更大未覆盖范围的015。',
             '没有证据证明该关系必须压过已选关系，本轮不强制提高优先级。'])}
    cards = []
    for sid, (heading, lines) in explanations.items():
        rows = [r for r in pool if r['diagnostic_position'] == sid]
        points = [g[1][i:i+2] for r in rows for g in r['candidate_geometry'] for i in (0, 2)]
        origin = positions[sid]['native_window']['origin_px']
        w, h = positions[sid]['native_window']['window_size_px']
        box = [max(0, min(p[0] for p in points)-origin[0]-65),
               max(0, min(p[1] for p in points)-origin[1]-65),
               min(w, max(p[0] for p in points)-origin[0]+65),
               min(h, max(p[1] for p in points)-origin[1]+65)]
        image = Image.new('RGB', (1500, 860), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((20, 12), heading, font=title, fill='black')
        source = next(r for r in pool if r['diagnostic_position'] == sid)
        draw.text((20, 51), f"{source['source_drawing_id']}／第{source['source_page']}页；原生320 DPI保存窗口", font=small, fill='black')
        for x, label, batch in zip((20, 515, 1010), ('原选择', '同普通名额修正', '含独立额外名额'), (before, ordinary, after)):
            chosen = [r for r in batch if r['diagnostic_position'] == sid]
            draw.text((x, 84), label, font=font, fill='black')
            image.paste(pane(sid, chosen, box, (460, 510)), (x, 120))
            draw.text((x, 640), '；'.join(r['sample_id'].replace('local-proposal-', '') for r in chosen), font=small, fill='black')
        for y, line in enumerate(lines):
            draw.text((20, 683+y*32), line, font=font, fill='black')
        draw.text((20, 826), '蓝虚线＝待追踪提名；紫＝普通输出；绿＝额外输出。仅显示叠层；无人工类别。', font=small, fill='black')
        path = assets/(sid.removeprefix('preview-')+'.png')
        image.save(path)
        cards.append((heading, 'images/'+path.name))
    image = Image.new('RGB', (1400, 750), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((20, 12), '必要对照｜007完整PAIR保留；006原提名仍无法对应', font=title, fill='black')
    for x, sid in ((20, 'preview-007'), (720, 'preview-006')):
        draw.text((x, 60), sid+'｜最终选择；灰线为旧诊断定位', font=font, fill='black')
        old = copy.deepcopy(positions[sid]['original_fixed_target'])
        selected = [r for r in after if r['diagnostic_position'] == sid]
        w, h = positions[sid]['native_window']['window_size_px']
        # A separate grey overlay is localization evidence, not a selected target.
        shown = pane(sid, selected, [0, 0, w, h], (640, 530))
        scale = shown.width/w
        overlay = ImageDraw.Draw(shown)
        origin = positions[sid]['native_window']['origin_px']
        for g in old['candidate_geometry']:
            p = [(g[1][i]-origin[i % 2])*scale for i in range(4)]
            overlay.line(p, fill=(150, 150, 150), width=1)
        image.paste(shown, (x, 100))
    draw.text((20, 649), '007：128＋188完整关系及两成员区间均100%；未改检测、配对或最终几何。', font=font, fill='black')
    draw.text((20, 681), '006：附近016仍为另一可见边缘；原竖向提名未恢复。本轮选择器不能制造新几何。', font=font, fill='black')
    draw.text((20, 717), '同位置回放，不是独立新样本；profile不证明对象归属。', font=small, fill='black')
    image.save(assets/'controls.png')
    cards.append(('007／006必要对照', 'images/controls.png'))
    table = ''.join('<tr>'+''.join(f'<td>{html.escape(str(row[k]))}</td>' for k in
        ('page_plan', 'source_drawing_id', 'source_page', 'pool', 'exact_target_representatives_removed', 'before', 'after_ordinary', 'after_extra', 'not_retained', 'unexamined'))+'</tr>' for row in report['page_counts'])
    text = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>P3B选择修正比较</title>
<style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.6;max-width:1500px}img{width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:6px;text-align:left}</style>
<h1>P3B选择修正：部分改善</h1>
<p>同一保存候选池135项，三页、五个既定窗口。没有检测、PDF渲染、标注或训练。总预算6、普通每页2及其他普通上限不变。原5普通；修正5普通＋1额外。额外每页上限由旧回放0恢复为已有配置1，单列统计。</p>
<p>正常选择函数经queue_dedup入口调用；本次显式development_replay，允许已知位置。普通new_information的历史排除默认仍生效。本包不是新标注队列或训练输入。</p>
<p>代表选择先核对同页完整成员集和源尺度几何，再比较实际范围及源支持。原计划的候选类型轮转保留CONTROL机会；不使用人工类别。当前真实池没有CONTROL，不能声称其真实表现已验证。</p>
<p>名额是展示负担限制，不是等价判定。同长线以几何和实际区间并集记录占用；近共线代理仅用于负担排序，不能把不同边缘或不同成员关系认成同一目标。未自动识别节点、开口或建筑语义。</p>
<table><tr><th>计划</th><th>原图</th><th>页</th><th>池</th><th>同目标代表去重</th><th>原保留</th><th>修正普通</th><th>额外</th><th>未保留</th><th>未检查</th></tr>'''+table+'</table>'
    text += ''.join(f'<h2>{html.escape(heading)}</h2><img src="{path}" alt="{html.escape(heading)}">' for heading, path in cards)
    text += '<p>11项直接功能检查通过；无全量套件、无无关安全／对齐审查。耗时和成本的完整记录未取得。旧94/50、20项回答、模型和生产DXF/OCR未修改。</p><p>下一步可开展有界真实页面候选质量试验；真实CONTROL、完整新页生成路径及页面分布尚未验证。本轮到此停止。</p><p><a href="results.json">比较记录</a>；<a href="selected-diagnostic-targets.jsonl">6项开发选择记录（无人工标签／无特征导出）</a></p></html>'
    (OUT/'index.html').write_text(text, encoding='utf-8')
    with zipfile.ZipFile(OUT/'comparison-package.zip', 'w', zipfile.ZIP_DEFLATED) as package:
        for name in ('index.html', 'results.json', 'selected-diagnostic-targets.jsonl'):
            package.write(OUT/name, name)
        for path in assets.iterdir():
            package.write(path, 'images/'+path.name)


if __name__ == '__main__':
    run()
