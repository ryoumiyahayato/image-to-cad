"""Small self-contained same-location report; no annotation UI or monitoring."""

import html
import json
import re
import zipfile


SCOPE=[
 ('填充/阴影','契约Stage 1第3项及REPORT类别表明确为OTHER。','003原人工2与源页填充笔画范围冲突。','沿用已有排除范围；原2保留为冲突记录，不假造人工3。','无需新增范围；单项标签纠正需以后明确确认。'),
 ('轴线','未明确是否属于本次结构/规则笔画专家。','011、021涉及轴网/虚线。','建议可纳入图纸规则线子范围，保留虚线型；判断其一根笔画或独立边界，禁止跨间隔补线。','需确认新增接受范围；本轮不启用。'),
 ('尺寸线/引出线','文字、箭头等符号内部笔画有非目标约定；注记中的规则线范围未列明。','012半径注记整体与局部笔画不能混为一项。','建议规则线可单独纳入；文字/箭头/终止符号仍作为注记整体，不能从局部OTHER推出产品删除。','需确认线成员范围；原观察保持。'),
 ('专业管线','结构/规则笔画定义并未限于承重结构，但未列出管线子范围。','021黑管线与灰轴线仅几何平行，没有合并关系依据。','建议纳入有明确工程走向或可编辑边界的线；混合对目前只作关系/范围诊断。若两类均获准且需保留，可判断独立边界，不能自动赋2或合并。','需确认接受范围；本轮不硬标。'),
 ('设备安装详图边界','没有“设备即图标”规则；也没有仅靠线宽即可纳入的规则。','013是20S206设备/管道安装图局部。','建议按线的工程几何角色和上下文区分可编辑轮廓/管件边界与符号内部描画，不以设备名称或profile作答案。','需确认该子范围；本轮不启用。'),
 ('文字/符号局部及粘连区','字形、符号内部笔画属于非目标；显式有效对象是赋类别的前提。','018小连通域只是数字/斜线的墨迹片段；019门符号局部不能扩大为所有门构件真值。','无独占归属依据不产生可训练字符/OTHER真值；保留整对象及相交结构。','已有范围无需重定；粘连归属仍需证据，本轮不启动OCR/语义分割。')]


def profile_brief(row):
    parts=[]
    for m in row['current_p3a_measurement']:
        trace=m['intermediate_profile_trace'];fail=trace['failed_probe_branches'] if trace else {}
        reason='测得' if m['profile'] else '未取得'
        failures=[]
        for branch,count in fail.items():
            name='种子偏离超限' if 'seed' in branch else '无暗像素' if 'candidates' in branch else '探针越界' if 'xs.min' in branch else '暗段触及法向边缘'
            failures.append(f'{count}次{name}')
        parts.append(f"{m['display_member']}：{trace['valid_probes'] if trace else '?'}有效/19，{reason}"+
                     ('；'+','.join(failures) if failures else ''))
    return '；'.join(parts)


def conclusion(position):
    q=position['fixed_original_on_native_reference_units']['quality']
    relation=position['association']
    new=position['new_diagnostic_nomination']
    if 'EDGE_DIRECTION_UNCONFIRMED' in q['rejection_reasons']:
        return '原目标对应继续暂缓；局部新提名不能冒充原对象恢复。'
    if not q['HUMAN_QUEUE_ELIGIBLE']:
        return ('原固定拟合超严格距离限界；B有同边关联线索，但A未改、未宣称修复。'
                if relation['status']=='same_visible_edge_geometric_evidence' else
                '原固定拟合略超严格距离限界；原成员集合未重新对应，防退化仍有不足。')
    if not new:return '固定原目标有局部几何证据；没有取得可关联的新提名。'
    if relation['status']!='same_visible_edge_geometric_evidence':return '附近有新提名，未建立原对象对应；不移线、不继承答案。'
    return '有同一可见边缘的几何关联线索；拟合变化见实际梯度偏差。源实体/语义身份未独立确认。'


def write_report(out,record):
    e=html.escape;table=[];cards=[]
    for p in record['positions']:
        sid=p['original_sample_id'];frame=p['reference_frame'];native=p['native_source_window'];new=p['new_diagnostic_nomination']
        a=p['fixed_original_on_native_reference_units'];old=p['fixed_original_on_native_legacy_units'];b=p['local_redetection']
        table.append(f'<tr><td>{sid}<br>{e(p["source_relative_path"])}<br>物理第{p["source_page"]}页</td><td>{frame["effective_dpi"]:.2f}DPI<br>{frame["render_size_px"]}<br>局部320DPI {native["window_size_px"]}</td><td>{e(conclusion(p))}<br>{e(str(a["quality"]["rejection_reasons"]))}</td><td>{b["raw_lines_above_min_length"]}条长度合格LSD线<br>{b["proposal_counts"].get("quality_eligible",0)}个可用提名<br>{e(p["association"]["status"])}</td><td><b>旧单位320：</b>{e(profile_brief(old))}<br><b>参考规则320：</b>{e(profile_brief(a))}<br><b>新提名：</b>{e(profile_brief(new)) if new else "未取得"}</td></tr>')
        images=p['comparison_images']
        def figure(key,label):
            if not images[key]:return '<figure><p>未取得对应的新提名；不以别处容易目标补位。</p></figure>'
            return f'<figure><a href="{images[key]}" target="_blank"><img src="{images[key]}" alt="{e(label)}"></a><figcaption>{e(label)}</figcaption></figure>'
        image_html=figure('old','原尺度源像素（没有重新制作旧裁块）')+figure('fixed','A 固定原目标，320DPI源局部；起止只标同一成员端点')+figure('new','B 同区域真实LSD可关联的新提名；几何已变，不继承旧答案')
        if new:
            oldmetrics=a['quality']['metrics'];newmetrics=new['quality']['metrics']
            mapping=p['association'].get('member_mapping',list(range(len(a['candidate_geometry']))))
            offsets=[]
            for i,j in enumerate(mapping):
                am=oldmetrics.get('AB'[i]+'_EDGE_ATTACHMENT',{});bm=newmetrics.get('AB'[j]+'_EDGE_ATTACHMENT',{})
                offsets.append({'original_member':'AB'[i],'new_member':'AB'[j],
                    'original_peak_offset_source_px':am.get('median_peak_offset_px'),
                    'new_peak_offset_source_px':bm.get('median_peak_offset_px'),
                    'gradient_limit':'finite local evidence; neither a CAD entity identity nor a measured class'})
            p['fit_evidence']=offsets
        if p.get('raw_fragment_check'):
            fragments=p['raw_fragment_check']['member_neighborhoods']
            fragment_note='；'.join(f"{m['member']}附近低于40参考px的原生短段{m['short_related_segments_below_40_reference_px']}个，投影覆盖{m['projected_coverage_by_short_segments']:.1%}（未组装）" for m in fragments)
        else:fragment_note='未取得'
        detail=json.dumps({'regional_source_information':record['regional_source_information'][sid],
            'association':p['association'],'fit_evidence':p.get('fit_evidence'),
            'fixed_original_low':p['fixed_original_on_low']['current_p3a_measurement'],
            'fixed_native_legacy':old['current_p3a_measurement'],'fixed_native_reference':a['current_p3a_measurement'],
            'new_nomination':new['current_p3a_measurement'] if new else None,
            'new_in_normal_selection':p['new_nomination_in_normal_selection'],'local_redetection':b,
            'raw_fragment_check':p.get('raw_fragment_check'),
            'control_limit':'001新对仍在同一笔画邻域；成员强梯度侧归属不保证唯一。007原双边界未重新组对，不把附近单笔画线对当恢复。'},ensure_ascii=False,indent=2)
        cards.append(f'<article id="{sid}"><h2>{sid} · {e(conclusion(p))}</h2><p>{e(p["source_relative_path"])} · 第{p["source_page"]}页</p><div class="views">{image_html}</div><p><a href="{images["source"]}">未叠加320DPI真实源局部</a> · <a href="{images["context"]}">原位置上下文（旧来源栅格）</a></p><p>全段最长无支持间隔：{e(str([a["quality"]["metrics"].get("AB"[i]+"_MAX_UNSUPPORTED_RUN_PX") for i in range(len(a["candidate_geometry"]))]))}实际源像素。未知线型下，间隔只是连续性证据不足，不自动判为错误断裂。</p><p>本輪原生短段检查：{e(fragment_note)}。这是原生检测片段统计，不是新训练标签或已组装的物理结构。</p><details><summary>两种实验、各成员测量及实际中间值</summary><pre>{e(detail)}</pre></details></article>')
    scopes=''.join('<tr>'+''.join('<td>'+e(cell)+'</td>' for cell in row)+'</tr>' for row in SCOPE)
    units=[
        ('支持半径、均值/p95距离','1.25 / 1 / 2参考像素','仅长度单位换算到实际源像素；灰度180不变。'),
        ('最长无支持间隔','8参考像素','实际长度为连续失败点数×真实采样步距，且不超过目标长度；不是固定8个失败点。'),
        ('方向支持','0.75比例；25度；峰值20','无量纲/角度/灰度梯度；不乘DPI。Sobel核、0.6sigma保留为原生像素算子，响应不能当跨尺度识别率。正负极性均可通过。'),
        ('LSD最小段、共同投影、配对间距','40 / 40 / 0.5-60参考像素','最小检测长度换算到320源像素；配对/截短复用参考坐标几何，角差3度不变。LSD默认内尺度0.8为比例，sigma_scale0.6是本地像素算子。'),
        ('截短范围、端部余量、最短目标','180 / 4 / 32参考像素','复用local_geometry，不吸附邻线，也不自动跨开口补线。'),
        ('profile法向范围/步距/种子距离','原页形状算出的12-48 / 1 / ≤2参考像素','法向保持实际源1px步距；范围、≤2种子距离和宽度稳定容差按参考长度转换；19探针、0.12-0.88、≥12有效、稳定比例≥0.75保持原算法；宽度容差中的1是参考像素，25%是比例。'),
        ('PDF坐标/信息分辨率','纸面points，不是建筑实体毫米','每页参考DPI不同，未宣称全项目统一纸面容差；有效320渲染DPI与未知原扫描DPI分开。')]
    unitrows=''.join('<tr>'+''.join('<td>'+e(cell)+'</td>' for cell in row)+'</tr>' for row in units)
    actual=record['actual_run']
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P3B 原页局部重检与尺度对照</title><style>body{margin:0;background:#eef1f4;color:#1f2933;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}header,main{max-width:1540px;margin:auto;padding:22px}header,article{background:white}h1{font-size:26px;margin:0}h2{font-size:19px}article{padding:20px;margin:22px 0;border:1px solid #d3dbe2;border-radius:6px}.views{display:grid;grid-template-columns:.65fr 1.15fr 1.15fr;gap:12px}figure{margin:0}img{width:100%;height:440px;object-fit:contain;background:#fafafa;border:1px solid #d7dfe6}figcaption{font-size:13px;color:#4b5e6d}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #cbd5dd;padding:9px;vertical-align:top;text-align:left}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f4f6f8;padding:12px}a{color:#175e84}.note{border-left:3px solid #a26e2f;padding-left:12px}@media(max-width:800px){.views{grid-template-columns:1fr}header,main{padding:12px}}</style><header><h1>原页局部重检与尺度一致性 · 5个同位置</h1><p>006、010、015及001、007防退化对照；三个已有PDF页面。A固定原目标，B真实局部重新检测，不能互相冒充修复证据。新提名没有继承人工类别。</p><p class="note">上一轮320DPI只用于显示和旧几何测量，本轮才实际进入LSD。原生局部目标邻域检查未发现内嵌图像重叠，有局部PATH；这说明细节来自矢量局部，但不自动证明006原竖边存在。源信息来源详见每卡。</p><p>旧profile中010：7/19有效，12个因种子距离3&gt;2源像素被跳过；015：0/19有效，19个因距离4&gt;2被跳过。不是范围不足、裁边或宽度稳定性判定失败。新诊断以同页原整页栅格固定长度规则，法向保持原生1px密采，直接读320DPI真实源像素；没有借旧profile、填零或换目标制造成功。</p><p>ACTUAL<br>全量历史配对缺失统计未补做。开发回放明确允许已知位置；普通模式默认历史排除不变。CONTROL未生成，不能以PAIR或SINGLE输出证明其覆盖。</p><p>旧20回答、94/50、冻结18维及模型不变。008定位显示沿用，不把010/015邻边合并或按窗口截断。无训练、自动增标、标注UI、OCR/语义分割或后台任务。</p><p><a href="results.json">实际统计、固定原目标及新提名证据</a> · <a href="selected-diagnostic-targets.jsonl">正常选择入口的开发输出</a></p><div class="scroll"><table><thead><tr><th>位置/源页</th><th>原尺度/新局部</th><th>A固定原目标</th><th>B局部重检</th><th>测量与原因</th></tr></thead><tbody>COMPARE</tbody></table></div><details><summary>尺度参数及单位</summary><table><thead><tr><th>参数</th><th>尺度/单位</th><th>换算或边界</th></tr></thead><tbody>UNITS</tbody></table><p>这是本次诊断的明确参考策略，未替换生产默认或旧训练输入。profile成功与方向支持只能提供有限几何证据，不赋语义类别；程序STRUCTURAL GEOMETRY字段也不提供生产授权。</p></details><details><summary>专家任务范围建议（未启用新口径）</summary><table><thead><tr><th>对象</th><th>已有规定</th><th>冲突/缺项</th><th>建议</th><th>是否需确认</th></tr></thead><tbody>SCOPE</tbody></table><p>几何上几条笔画、当前专家是否接受、产品是否保留/整体编辑/允许改动是三个判断。非目标不授权删除，规则线也不等同于承重结构。</p></details></header><main>CARDS</main></html>'''
    document=document.replace('ACTUAL',e(f"实际运行：{actual['pages']}页/{actual['regions']}局部，{actual['pair_comparisons']}次本轮配对比较，{actual['unexamined_comparisons']}次因预算未比较；可用池{actual['proposal_pool']}，正常选择输出{actual['selected']}。"))
    changes='<details><summary>实际修改函数与局部检查</summary><ul>'+''.join('<li>'+e(name)+'</li>' for name in record.get('changed_functions',[]))+'</ul><p>'+e(record.get('local_checks',{}).get('scope','局部检查记录见results.json'))+'</p></details>'
    document=document.replace('COMPARE',''.join(table)).replace('UNITS',unitrows).replace('SCOPE',scopes).replace('CARDS',''.join(cards)).replace('</header>',changes+'</header>')
    (out/'index.html').write_text(document,encoding='utf-8')
    record['scope_proposals']=[dict(zip(('object','existing','conflict','suggestion','confirmation'),row)) for row in SCOPE]
    record['parameter_units']=[dict(zip(('parameter','unit','rule'),row)) for row in units]
    # Actual report image links, no PDF/cache/font/project files in package.
    paths=set(re.findall(r'(?:src|href)="([^"#]+)"',document))
    missing=[p for p in paths if not (out/p).is_file()]
    if missing:raise ValueError('Report local links missing: '+str(missing))
    record['self_contained_package']={'relative_link_count':len(paths),'missing_links':[],
        'files':sorted(['index.html',*paths]),'original_full_pages_included':False,'fonts_included':False}
    from common import atomic_json
    atomic_json(out/'results.json',record)
    with zipfile.ZipFile(out/'comparison-package.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted({'index.html',*paths}):archive.write(out/path,path)
