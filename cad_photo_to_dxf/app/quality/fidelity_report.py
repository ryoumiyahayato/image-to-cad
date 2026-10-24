"""Static, offline HTML for the read-only saved-page inspector."""

from __future__ import annotations

from html import escape
from pathlib import Path
import json


def esc(value):
    return escape(str(value), quote=True)


CSS = """
:root{font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#173040;background:#edf2f5}
body{max-width:1380px;margin:0 auto;padding:28px}h1{font-size:28px;margin:8px 0}
h2{font-size:21px}h3{margin:6px 0 12px}p{line-height:1.65}.muted{color:#536b78}
a{color:#075c86}header,.card{background:white;border:1px solid #d6e0e5;border-radius:10px;padding:22px;margin:16px 0}
.notice{border-left:5px solid #ce7a1e;padding:8px 16px;background:#fff6e7}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.two{grid-template-columns:repeat(2,minmax(0,1fr))}figure{margin:0;min-width:0}
img{width:100%;object-fit:contain;background:#fafafa;border:1px solid #dde5e8}
figcaption{padding:6px 0;font-size:13px}.tag{display:inline-block;background:#e5f0f4;padding:4px 7px;margin:3px;font-size:12px;border-radius:4px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;border-bottom:1px solid #e1e7eb;padding:8px;word-break:break-word}
pre{white-space:pre-wrap;word-break:break-all;font-size:12px;max-height:340px;overflow:auto}
summary{cursor:pointer;padding:8px}code{overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:12px}
.thumb img{max-height:680px} .region img{image-rendering:auto;max-height:380px}
@media(max-width:900px){.grid{grid-template-columns:1fr}body{padding:12px}}
"""


def shell(title, content):
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title><style>{CSS}</style><body>{content}</body></html>"
    )


def picture(filename, caption):
    return f'<figure><a href="{esc(filename)}"><img loading="lazy" src="{esc(filename)}" alt="{esc(caption)}"></a><figcaption>{esc(caption)}</figcaption></figure>'


def detail(region, records):
    ident = region["id"]
    body = f'<article class="card region" id="{esc(ident)}"><h3>{esc(ident)} · {esc(region.get("review_priority", "历史区域"))}</h3>'
    body += f"<p>页内像素：{esc(region['bbox'])}。<b>不授权修改实体。</b></p>"
    for label in [
        region.get("visual_state", "HISTORICAL_LABEL"),
        region.get("engineering_state", region.get("declared_class")),
        region.get("source_state"),
    ]:
        body += f'<span class="tag">{esc(label)}</span>'
    body += '<div class="grid">' + picture(ident + "-source.png", "原始PDF当前页裁片")
    body += picture(ident + "-cad.png", "实际保存DXF，可见层")
    body += (
        picture(ident + "-diff.png", "红：源缺失候选；蓝：CAD额外候选；1px容差")
        + "</div>"
    )
    if "before" in region:
        body += '<div class="grid two">' + picture(
            ident + "-before.png", "已存在的历史正式/同次对照DXF"
        )
        body += "<div><h4>前后差异（Measured）</h4><table><tr><th>源阈值/容差</th><th>旧缺失/额外</th><th>当前缺失/额外</th></tr>"
        for a, b in zip(region["before"], region["current"], strict=True):
            body += f"<tr><td>{a['source_cut']}/{a['tolerance_px']}px</td><td>{a['missing_candidate_pixels']}/{a['extra_candidate_pixels']}</td><td>{b['missing_candidate_pixels']}/{b['extra_candidate_pixels']}</td></tr>"
        body += "</table><p>显示差异变化不等于工程修复授权。历史来源证书独立引用。</p></div></div>"
    body += (
        "<p>"
        + esc(region.get("note", "自动视觉候选。工程含义与端点职责仍待核对。"))
        + "</p>"
    )
    body += '<p class="muted">' + esc("; ".join(region.get("guards", []))) + "</p>"
    body += (
        "<details><summary>附近实际CAD实体与来源记录（bbox邻近不是像素归属）</summary>"
    )
    groups = set(region.get("entity_groups", []))
    associated = [r for r in records if r["geometry_group"] in groups]
    body += "<table><tr><th>几何组/当前handle</th><th>对象/图层</th><th>来源关联</th><th>字符串或几何</th></tr>"
    for r in associated:
        g = r["geometry_source_CAD_axes"]
        geometry_text = json.dumps(g, ensure_ascii=False)
        body += f"<tr><td>{esc(r['geometry_group'])}/{esc(r['current_file_handle'])}</td><td>{esc(r['type'])}/{esc(r['layer'])}</td><td>{esc(r['source_association'])}</td><td>{esc(geometry_text[:350])}</td></tr>"
    body += "</table><p>完整几何、原属性、XDATA、源候选与歧义见entities.json。组号只在当前输入版本中有意义。</p></details>"
    body += "<details><summary>区域测量、保护条件及历史证据引用</summary><pre>"
    body += (
        esc(json.dumps(region, ensure_ascii=False, indent=2))
        + "</pre></details></article>"
    )
    return body


def case_html(report, output):
    output = Path(output)
    title = f"{report['name']} · 整页CAD质量检查"
    body = f'<header><a href="../index.html">全部来源</a><h1>{esc(title)}</h1>'
    body += f"<p>物理第{report['page']['physical_page']}页 · {report['page']['dpi']} DPI · {esc(report['page']['size_px'])} px · {esc(report['algorithm'])}</p>"
    body += '<p class="notice">这是质量复核入口。Measured表示测量；Inferred表示自动候选；Verified仅引用独立历史证明；Unknown保留未知。工具不修改DXF，也不签发删除、移动、合并或补画资格。</p></header>'
    if report["coordinate"]["status"] != "VERIFIED":
        body += f'<section class="card"><h2>COORDINATE_CONTRACT_INCOMPLETE</h2><p>{esc(report["coordinate"].get("reason"))}</p>'
        body += picture("source.png", "仅源图参考；不提供定量CAD差异") + "</section>"
    else:
        body += '<section class="card"><h2>整页概览</h2><p>标号对应下方优先区域。点击图像可查看原尺寸；原图和CAD使用记录的纸面变换，没有图像配准。</p><div class="grid thumb">'
        body += (
            picture("overview.png", "源图与最多8个自动优先区域")
            + picture("cad.png", "实际正式DXF默认可见层")
            + picture("source.png", "原始PDF渲染")
            + "</div></section>"
        )
        body += '<section class="card"><h2>可复核指标</h2><p>'
        body += f"可见对象{report['visible_entities']}；隐藏对象{report['hidden_entities']}（未计为显示重复）；有唯一保存结构几何匹配{report['source_geometry_matched']}/{report['source_geometry_matched_denominator']}。"
        body += f"自动候选{len(report['candidates'])}，自动认证产品缺陷0。源关联为PARTIAL，不能据此计算工程错误率。</p>"
        body += (
            "<p>类型："
            + esc(report["visible_entity_types"])
            + "；审计："
            + esc(report["audit"])
            + "</p>"
        )
        body += (
            "<nav>"
            + "".join(
                f'<a href="#{esc(r["id"])}">{i + 1}: {esc(r["id"])}</a>'
                for i, r in enumerate(
                    report["candidates"][: report["limits"]["max_details"]]
                )
            )
            + "</nav></section>"
        )
        records = json.loads((output / "entities.json").read_text(encoding="utf-8"))
        for r in report["candidates"][: report["limits"]["max_details"]]:
            body += detail(r, records)
        body += '<section class="card"><h2>历史修复与保护案例</h2><p>以下类别来自引用记录。没有重新授予生产修改权限。</p></section>'
        for r in report["historical"]:
            body += detail(r, records)
    body += '<section class="card"><h2>输入、坐标、预算和限制</h2><p>输入身份及核心候选见<a href="report.json">report.json</a>。'
    if report["coordinate"]["status"] == "VERIFIED":
        body += '对象记录见<a href="entities.json">entities.json</a>。'
    body += "</p><pre>"
    summary = {k: v for k, v in report.items() if k not in {"candidates", "historical"}}
    body += esc(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre></section>"
    (output / "report.html").write_text(shell(title, body), encoding="utf-8")


def index_html(results, output):
    body = '<header><h1>整页CAD保真检查</h1><p>保存结果检查 · 无OCR重跑 · 无CAD修改</p><p class="notice">视觉差异产生待复核候选。报告不提供实体删除或重建许可。源关联缺失时保留Unknown。</p></header>'
    for result in results:
        body += f'<section class="card"><h2>{esc(result["name"])}</h2><p>{esc(result["status"])}</p>'
        if result["status"] in {"COMPLETED", "COORDINATE_CONTRACT_INCOMPLETE"}:
            body += f'<a href="{esc(result["name"])}/report.html">打开整页报告</a> · <a href="{esc(result["name"])}/report.json">JSON</a>'
            if result.get("coordinate", {}).get("status") == "VERIFIED":
                body += f"<p>可见对象{result['visible_entities']}；候选{len(result['candidates'])}；历史区域{len(result['historical'])}；耗时{result['seconds']:.2f}s。</p>"
        else:
            body += "<pre>" + esc(result.get("reason", "Failed")) + "</pre>"
        body += "</section>"
    Path(output, "index.html").write_text(
        shell("整页CAD保真检查", body), encoding="utf-8"
    )
