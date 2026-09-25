"""Build a portable, prediction-blind expert review package.

This module is deliberately separate from the localhost review server.  It
turns the frozen E1 ordering and Local-D source evidence into a self-contained
static package for an independent reviewer.  It does not read or copy any
mutable E2 review state and it contains no model or adjudication logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
import zipfile

from PIL import Image

from .human_review_session import load_review_manifest, verify_review_assets


EXPERT_SCHEMA_VERSION = 1
EXPERT_PACKAGE_NAME = "expert-review-package-v1"
ALLOWED_LABELS: tuple[str, ...] = (
    "STRUCTURAL_CONTINUATION",
    "ANNOTATION_OR_GLYPH",
    "AMBIGUOUS",
    "INVALID_FOR_TASK",
)


@dataclass(frozen=True)
class ExpertPackageBuild:
    """Paths and counts returned after a package has been built."""

    package_dir: Path
    zip_path: Path
    manifest_sha256: str
    candidate_count: int
    clean_local_count: int
    clean_context_count: int


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(value: str, limit: int = 54) -> str:
    output = "".join(character if character.isalnum() else "-" for character in value.upper())
    output = "-".join(part for part in output.split("-") if part)
    return output[:limit].strip("-") or "UNIT"


def _repo_paths(repo_root: Path) -> dict[str, Path]:
    validation = repo_root / "cad_photo_to_dxf" / "validation"
    local_d_runtime = (
        repo_root
        / "local-artifacts"
        / "draftsman"
        / "user-supplied-candidate-mining-v2-local-d"
    )
    return {
        "e1_manifest": validation
        / "user-supplied-human-review-v2-local-e1"
        / "human-review-manifest.json",
        "e1_order": validation
        / "user-supplied-human-review-v2-local-e1"
        / "review-order.json",
        "frozen_candidates": validation
        / "user-supplied-candidate-mining-v2-local-d"
        / "frozen-candidate-set.json",
        "source_renders": local_d_runtime / "source-renders",
        "default_output": repo_root
        / "local-artifacts"
        / "draftsman"
        / EXPERT_PACKAGE_NAME,
        "default_zip": repo_root
        / "local-artifacts"
        / "draftsman"
        / f"{EXPERT_PACKAGE_NAME}.zip",
    }


def _ensure_frozen_inputs(repo_root: Path) -> tuple[Any, dict[str, Any], dict[str, Path]]:
    paths = _repo_paths(repo_root)
    for key in ("e1_manifest", "e1_order", "frozen_candidates", "source_renders"):
        if not paths[key].exists():
            raise FileNotFoundError(paths[key])

    e1 = load_review_manifest(paths["e1_manifest"], paths["e1_order"])
    if len(e1.items) != 24:
        raise ValueError(f"expected exactly 24 E1 items, found {len(e1.items)}")
    # This checks the pre-existing E1 assets without using them as package
    # evidence.  The package crops are regenerated from unmarked source renders.
    verify_review_assets(e1.items, repo_root)

    frozen = _read_json(paths["frozen_candidates"])
    candidates = frozen.get("frozen_candidates")
    if not isinstance(candidates, list) or len(candidates) != 24:
        raise ValueError("Local-D frozen candidate set must contain exactly 24 candidates")
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Local-D candidate record must be an object")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("Local-D candidate is missing candidate_id")
        if candidate_id in candidate_by_id:
            raise ValueError(f"duplicate Local-D candidate: {candidate_id}")
        candidate_by_id[candidate_id] = candidate

    e1_ids = [item.item_id for item in e1.items]
    if set(e1_ids) != set(candidate_by_id):
        raise ValueError("E1 candidate IDs do not match Local-D frozen candidate IDs")
    return e1, candidate_by_id, paths


def _source_render(source_render_dir: Path, selected_unit_id: str) -> Path:
    expected = source_render_dir / f"{_slug(selected_unit_id)}.png"
    if expected.is_file():
        return expected
    matches = [
        path
        for path in source_render_dir.glob("*.png")
        if path.stem == _slug(selected_unit_id)
    ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"could not resolve one Local-D source render for {selected_unit_id}: {matches}"
        )
    return matches[0]


def _box(value: Any, field_name: str) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field_name} must be [left, top, right, bottom]")
    left, top, right, bottom = (int(round(float(part))) for part in value)
    if left < 0 or top < 0 or right <= left or bottom <= top:
        raise ValueError(f"invalid {field_name}: {value}")
    return left, top, right, bottom


def _point(value: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field_name} must be [x, y]")
    return float(value[0]), float(value[1])


def _relative_point(point: tuple[float, float], crop_box: tuple[int, int, int, int]) -> list[float]:
    return [round(point[0] - crop_box[0], 3), round(point[1] - crop_box[1], 3)]


def _relative_segment(segment: Mapping[str, Any], crop_box: tuple[int, int, int, int], field_name: str) -> dict[str, list[float]]:
    return {
        "start": _relative_point(_point(segment.get("start"), f"{field_name}.start"), crop_box),
        "end": _relative_point(_point(segment.get("end"), f"{field_name}.end"), crop_box),
    }


def _marker_geometry(candidate: Mapping[str, Any], crop_box: tuple[int, int, int, int], size: tuple[int, int]) -> dict[str, Any]:
    marker = {
        "width": size[0],
        "height": size[1],
        "fragment_a": _relative_segment(candidate.get("fragment_a_geometry"), crop_box, "fragment_a_geometry"),
        "fragment_b": _relative_segment(candidate.get("fragment_b_geometry"), crop_box, "fragment_b_geometry"),
        "gap_endpoint_a": _relative_point(_point(candidate.get("gap_endpoint_a"), "gap_endpoint_a"), crop_box),
        "gap_endpoint_b": _relative_point(_point(candidate.get("gap_endpoint_b"), "gap_endpoint_b"), crop_box),
    }
    return marker


def _colored_pixel_fraction(image: Image.Image) -> float:
    """Return a small-image estimate of non-neutral pixels.

    Local-D renders are monochrome engineering evidence.  A noticeable amount
    of saturated color is a useful guard against accidentally copying the old
    marker-baked E1 crops into the clean package.
    """

    sample = image.convert("RGB").resize((128, 128))
    pixels = list(sample.getdata())
    colored = sum(1 for red, green, blue in pixels if max(red, green, blue) - min(red, green, blue) > 18)
    return colored / max(1, len(pixels))


def _write_clean_crop(
    source_path: Path,
    crop_box: tuple[int, int, int, int],
    destination: Path,
) -> tuple[int, int]:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
        if crop_box[2] > image.width or crop_box[3] > image.height:
            raise ValueError(
                f"crop box {crop_box} exceeds source render {source_path} {image.size}"
            )
        crop = image.crop(crop_box)
        if _colored_pixel_fraction(crop) > 0.01:
            raise ValueError(f"source render contains unexpected colored overlay: {source_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        crop.save(destination, format="PNG", optimize=True)
        return crop.size


def _package_manifest(e1: Any, candidates: Mapping[str, Mapping[str, Any]], output_dir: Path, paths: Mapping[str, Path]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    local_count = 0
    context_count = 0
    for item in e1.items:
        candidate = candidates[item.item_id]
        candidate_id = item.item_id
        source_render = _source_render(paths["source_renders"], candidate["selected_unit_id"])
        local_box = _box(candidate.get("local_crop_box_px"), "local_crop_box_px")
        context_box = _box(candidate.get("context_crop_box_px"), "context_crop_box_px")
        local_path = output_dir / "assets" / "local" / f"{candidate_id}.png"
        context_path = output_dir / "assets" / "context" / f"{candidate_id}.png"
        local_size = _write_clean_crop(source_render, local_box, local_path)
        context_size = _write_clean_crop(source_render, context_box, context_path)
        local_count += 1
        context_count += 1
        items.append(
            {
                "review_index": item.review_index,
                "candidate_id": candidate_id,
                "local_image": f"assets/local/{candidate_id}.png",
                "context_image": f"assets/context/{candidate_id}.png",
                "marker": {
                    "local": _marker_geometry(candidate, local_box, local_size),
                    "context": _marker_geometry(candidate, context_box, context_size),
                },
            }
        )

    return {
        "schema_version": EXPERT_SCHEMA_VERSION,
        "package_id": EXPERT_PACKAGE_NAME,
        "reviewer_session_type": "INDEPENDENT_EXPERT_OBSERVATION",
        "candidate_count": len(items),
        "allowed_human_labels": list(ALLOWED_LABELS),
        "source_manifest_identity": {
            "manifest_name": paths["e1_manifest"].name,
            "order_name": paths["e1_order"].name,
            "manifest_sha256": _sha256(paths["e1_manifest"]),
            "order_sha256": _sha256(paths["e1_order"]),
        },
        "review_order": [item["candidate_id"] for item in items],
        "items": items,
        "governance": {
            "expert_review_package": "CONTROLLED_EXTERNAL_REVIEW_ONLY",
            "public_redistribution": "NOT_AUTHORIZED",
            "model_exposure": "NONE",
            "reviewer_a_data_included": False,
            "source_full_documents_included": False,
        },
        "counts": {
            "clean_local_views": local_count,
            "clean_context_views": context_count,
        },
    }


def _html_manifest_json(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>工程图纸专家盲审</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#5b6875; --line:#d6dde5; --panel:#ffffff; --soft:#f4f7fa; --accent:#0b6e99; --accent-soft:#e5f4fb; --danger:#9e3030; --shadow:0 12px 30px rgba(29,48,66,.10); }
    * { box-sizing:border-box; }
    body { margin:0; background:#eef2f5; color:var(--ink); font-family:"Segoe UI","Microsoft YaHei",sans-serif; line-height:1.45; }
    button, input, textarea { font:inherit; }
    button { cursor:pointer; }
    .topbar { position:sticky; top:0; z-index:10; display:flex; justify-content:space-between; gap:24px; align-items:center; padding:14px 24px; background:#142b3b; color:#fff; box-shadow:0 2px 10px rgba(0,0,0,.18); }
    .topbar h1 { margin:0; font-size:20px; letter-spacing:.02em; }
    .topbar .progress { text-align:right; font-size:14px; }
    .topbar .progress strong { display:block; font-size:18px; }
    .shell { max-width:1600px; margin:0 auto; padding:22px; }
    .notice { background:#fff9e8; border:1px solid #ecd696; border-left:5px solid #c78b00; border-radius:10px; padding:14px 17px; margin-bottom:18px; }
    .notice strong { display:block; font-size:17px; margin-bottom:4px; }
    .layout { display:grid; grid-template-columns:minmax(0, 1fr) 350px; gap:18px; align-items:start; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); }
    .evidence-panel { padding:16px; }
    .panel-heading { display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:12px; }
    .panel-heading h2 { margin:0; font-size:18px; }
    .panel-heading span { color:var(--muted); font-size:13px; }
    .evidence-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    .evidence-card { border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--soft); min-width:0; }
    .evidence-card h3 { margin:0; padding:9px 12px; font-size:15px; background:#f8fafc; border-bottom:1px solid var(--line); }
    .image-stage { position:relative; background:#fff; overflow:hidden; line-height:0; cursor:zoom-in; }
    .image-stage img { display:block; width:100%; height:auto; max-width:100%; }
    .image-stage .marker-layer { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
    .image-stage .marker-layer .fragment-a { stroke:#087ea4; }
    .image-stage .marker-layer .fragment-b { stroke:#a04891; }
    .image-stage .marker-layer .endpoint-a { stroke:#238647; fill:#f3fff6; }
    .image-stage .marker-layer .endpoint-b { stroke:#b47700; fill:#fff8df; }
    .image-stage .marker-layer line { fill:none; stroke-width:1.6; stroke-opacity:.78; stroke-dasharray:7 5; vector-effect:non-scaling-stroke; }
    .image-stage .marker-layer circle { stroke-width:1.6; stroke-opacity:.9; vector-effect:non-scaling-stroke; }
    .image-stage .marker-layer .endpoint-cross { stroke-width:1.35; stroke-opacity:.82; vector-effect:non-scaling-stroke; }
    .compare-wrap { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:8px; background:#f6f8fa; }
    .compare-wrap > div { min-width:0; }
    .compare-label { padding:4px 6px; color:var(--muted); font-size:12px; background:#edf2f6; border:1px solid var(--line); border-bottom:0; }
    .side-panel { display:flex; flex-direction:column; gap:14px; }
    .control-panel, .guidance-panel, .identity-panel, .export-panel { padding:16px; }
    .control-panel h2, .guidance-panel h2, .identity-panel h2, .export-panel h2 { margin:0 0 10px; font-size:17px; }
    .view-controls { display:grid; grid-template-columns:repeat(3,1fr); gap:7px; }
    .view-button, .secondary-button { border:1px solid #afbdc8; border-radius:8px; background:#fff; color:var(--ink); padding:9px 6px; font-size:13px; }
    .view-button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .marker-toggle { display:flex; align-items:center; gap:8px; margin-top:12px; font-weight:600; }
    .marker-toggle input { width:18px; height:18px; accent-color:var(--accent); }
    .legend { margin-top:12px; padding:10px; border:1px solid var(--line); border-radius:8px; background:#f9fbfc; font-size:12px; }
    .legend-title { font-weight:700; margin-bottom:5px; }
    .legend-row { display:flex; align-items:center; gap:7px; margin:4px 0; }
    .swatch { width:18px; height:5px; border-radius:3px; display:inline-block; }
    .swatch.a { background:#087ea4; } .swatch.b { background:#a04891; } .swatch.ea { width:11px; height:11px; border:2px solid #238647; border-radius:50%; background:#f3fff6; } .swatch.eb { width:11px; height:11px; border:2px solid #b47700; border-radius:50%; background:#fff8df; }
    .guidance-panel p { margin:7px 0; font-size:13px; }
    .guidance-panel .question { padding:9px 10px; background:var(--accent-soft); border-radius:8px; font-weight:700; }
    .guidance-panel details { margin-top:8px; }
    .guidance-panel summary { cursor:pointer; font-weight:700; }
    .guidance-panel ul { padding-left:20px; margin:5px 0; font-size:12px; }
    .field { display:flex; flex-direction:column; gap:5px; margin:9px 0; }
    .field label { font-size:12px; color:var(--muted); font-weight:700; }
    .field input, .field textarea { border:1px solid #b9c6d0; border-radius:7px; padding:8px 9px; background:#fff; color:var(--ink); }
    .field textarea { min-height:70px; resize:vertical; }
    .button-row { display:flex; gap:8px; flex-wrap:wrap; }
    .primary-button { border:1px solid var(--accent); border-radius:8px; background:var(--accent); color:#fff; padding:9px 12px; font-weight:700; }
    .secondary-button { padding:9px 12px; }
    .label-panel { margin-top:18px; padding:16px; }
    .label-panel h2 { margin:0 0 10px; font-size:18px; }
    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; }
    .label-button { text-align:left; min-height:90px; border:2px solid #b9c7d1; border-radius:10px; padding:10px; background:#fff; color:var(--ink); }
    .label-button:hover, .label-button:focus-visible { border-color:var(--accent); box-shadow:0 0 0 3px rgba(11,110,153,.16); outline:none; }
    .label-button.active { border-color:#167744; background:#effaf3; }
    .label-button .key { float:right; color:var(--accent); font-size:18px; font-weight:800; }
    .label-button strong { display:block; font-size:15px; }
    .label-button small { display:block; color:var(--muted); margin-top:5px; font-size:11px; line-height:1.35; }
    .bottom-row { display:grid; grid-template-columns:auto 1fr auto; gap:10px; align-items:center; margin-top:12px; }
    .nav-button { border:1px solid #aebcc7; border-radius:8px; padding:10px 15px; background:#fff; }
    .save-status { color:var(--muted); font-size:13px; text-align:center; }
    .counts { display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px; }
    .count { padding:7px; background:#f5f8fa; border:1px solid var(--line); border-radius:7px; font-size:12px; }
    .count strong { display:block; font-size:17px; }
    .error { display:none; margin-top:10px; padding:9px; border-radius:7px; color:#8e2222; background:#fff0f0; border:1px solid #e2aaaa; }
    .error.visible { display:block; }
    .completion { display:none; margin-top:10px; padding:11px; border-radius:8px; color:#125f35; background:#effaf3; border:1px solid #a9d6b9; font-weight:700; }
    .completion.visible { display:block; }
    .modal { position:fixed; inset:0; z-index:30; background:rgba(7,18,28,.82); display:flex; flex-direction:column; }
    .modal[hidden] { display:none; }
    .modal-bar { display:flex; align-items:center; gap:8px; padding:10px 14px; color:#fff; background:rgba(8,24,35,.94); }
    .modal-bar strong { margin-right:auto; }
    .modal-bar button { border:1px solid #8397a6; border-radius:6px; background:#183649; color:#fff; padding:6px 9px; }
    .zoom-readout { min-width:50px; text-align:center; font-variant-numeric:tabular-nums; }
    .zoom-viewport { flex:1; overflow:auto; display:flex; align-items:flex-start; justify-content:center; padding:22px; cursor:grab; }
    .zoom-viewport.dragging { cursor:grabbing; }
    .zoom-content { position:relative; transform-origin:top left; line-height:0; }
    .zoom-content img { display:block; max-width:90vw; max-height:78vh; width:auto; height:auto; }
    .zoom-content .marker-layer { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
    .modal-hint { color:#d6e2eb; padding:5px 14px 12px; font-size:12px; background:rgba(8,24,35,.94); }
    @media (max-width:1100px) { .layout { grid-template-columns:1fr; } .side-panel { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); } .guidance-panel { grid-column:1/-1; } }
    @media (max-width:760px) { .shell { padding:12px; } .topbar { padding:12px; align-items:flex-start; } .topbar h1 { font-size:17px; } .topbar .progress { font-size:12px; } .evidence-grid, .label-grid, .side-panel { grid-template-columns:1fr; } .label-button { min-height:72px; } .bottom-row { grid-template-columns:1fr 1fr; } .save-status { grid-column:1/-1; grid-row:1; } .nav-button { width:100%; } }
  </style>
</head>
<body>
  <header class="topbar">
    <h1>工程图纸专家盲审 · Reviewer B</h1>
    <div class="progress"><strong id="progress-label">候选 1 / 24</strong><span id="completed-label">已完成 0 / 24 · 待审核 24</span></div>
  </header>
  <main class="shell">
    <section class="notice">
      <strong>看得出来才判；看不出来就选“无法可靠判断”，不要猜。</strong>
      <div>这是独立的专家观察记录。请只根据 LOCAL + CONTEXT 判断，不需要知道具体电气元件名称，也不会显示其他审核员或模型结果。</div>
    </section>
    <div class="layout">
      <section class="panel evidence-panel">
        <div class="panel-heading"><h2 id="candidate-title">候选</h2><span id="view-status">清洁视图 · 点击图片可放大</span></div>
        <div id="evidence-grid" class="evidence-grid"></div>
        <div class="field"><label for="candidate-note">本候选备注（可选）</label><textarea id="candidate-note" placeholder="记录你判断时看到的证据或疑问"></textarea></div>
        <div class="bottom-row"><button id="previous-button" class="nav-button">← 上一个</button><div id="save-status" class="save-status">状态：正在加载</div><button id="next-button" class="nav-button">下一个 →</button></div>
        <div id="completion" class="completion">24 / 24 已完成。请导出审核结果并发送 JSON；本页面不会自动冻结数据集。</div>
        <div id="error" class="error"></div>
      </section>
      <aside class="side-panel">
        <section class="panel control-panel">
          <h2>查看方式</h2>
          <div class="view-controls"><button class="view-button active" data-view="CLEAN">清洁</button><button class="view-button" data-view="MARKED">标记</button><button class="view-button" data-view="COMPARE">对照</button></div>
          <label class="marker-toggle"><input id="marker-toggle" type="checkbox"> 显示候选标记</label>
          <div class="legend">
            <div class="legend-title">候选标记图例（仅表示候选位置，不表示答案）</div>
            <div class="legend-row"><span class="swatch a"></span><span>Fragment A（片段 A）</span></div>
            <div class="legend-row"><span class="swatch b"></span><span>Fragment B（片段 B）</span></div>
            <div class="legend-row"><span class="swatch ea"></span><span>Gap endpoint A（间隙端点 A）</span></div>
            <div class="legend-row"><span class="swatch eb"></span><span>Gap endpoint B（间隙端点 B）</span></div>
            <div>不绘制连接桥；默认清洁视图不会覆盖原图。</div>
          </div>
        </section>
        <section class="panel identity-panel">
          <h2>审核者信息（可选）</h2>
          <div class="field"><label for="reviewer-id">reviewer_id</label><input id="reviewer-id" autocomplete="off" placeholder="可留空"></div>
          <div class="field"><label for="reviewer-role">reviewer_role</label><input id="reviewer-role" value="DOMAIN_PRACTITIONER" autocomplete="off"></div>
          <div class="field"><label for="reviewer-note">审核说明（可选）</label><textarea id="reviewer-note" placeholder="可留空"></textarea></div>
        </section>
        <section class="panel guidance-panel">
          <h2>判断原则</h2>
          <p class="question">如果人工重新描这张工程图，这两段是否应作为同一个实际工程对象的线连接起来？</p>
          <p>不需要判断对象的专业名称。若必须依赖无法确认的专业含义，请选择“无法可靠判断”。</p>
          <details open><summary>四个标签的含义</summary>
            <p><strong>结构连续</strong>：两段属于同一个实际工程对象或安装对象，应作为同一条对象线继续连接。</p>
            <p><strong>注释 / 文字 / 图纸版式</strong>：尺寸线、延长线、leader、文字笔画、表格线、标题栏、图框或 revision / legend / layout rule 等。</p>
            <p><strong>无法可靠判断</strong>：查看 LOCAL + CONTEXT 后仍不能可靠判断；不要猜。</p>
            <p><strong>候选本身无效</strong>：错误配对、无关线、crop 错位、转换损坏、证据不足或候选生成失败。</p>
          </details>
        </section>
        <section class="panel export-panel">
          <h2>结果</h2>
          <div class="button-row"><button id="export-button" class="primary-button">导出审核结果 JSON</button><label class="secondary-button">导入审核结果 <input id="import-file" type="file" accept="application/json" hidden></label></div>
          <div id="export-status" class="save-status" style="margin-top:9px;text-align:left">本地自动保存；导出的 JSON 是发送给项目负责人的结果。</div>
          <div id="counts" class="counts"></div>
        </section>
      </aside>
    </div>
    <section class="panel label-panel"><h2>请选择一个标签（键盘 1 / 2 / 3 / 4）</h2><div id="label-grid" class="label-grid"></div></section>
  </main>
  <div id="image-modal" class="modal" hidden><div class="modal-bar"><strong id="modal-title">图片放大</strong><button id="zoom-out">−</button><button id="zoom-reset">适合窗口</button><button id="zoom-in">＋</button><span id="zoom-readout" class="zoom-readout">100%</span><button id="modal-close">关闭</button></div><div id="zoom-viewport" class="zoom-viewport"><div id="zoom-content" class="zoom-content"></div></div><div class="modal-hint">滚轮缩放；按住拖动可平移。Esc 关闭。</div></div>
  <script>
    "use strict";
    const PACKAGE = __PACKAGE_MANIFEST__;
    const LABELS = [
      { value:"STRUCTURAL_CONTINUATION", title:"结构连续", key:"1", text:"同一个实际工程对象或安装对象的连续线。" },
      { value:"ANNOTATION_OR_GLYPH", title:"注释 / 文字 / 图纸版式", key:"2", text:"尺寸、leader、文字、表格、标题栏、图框或版式规则。" },
      { value:"AMBIGUOUS", title:"无法可靠判断", key:"3", text:"LOCAL + CONTEXT 仍无法可靠判断；不要猜。" },
      { value:"INVALID_FOR_TASK", title:"候选本身无效", key:"4", text:"不是一个有效的“两段是否应该连接”问题。" }
    ];
    const LABEL_VALUES = new Set(LABELS.map(item => item.value));
    const STORAGE_KEY = "draftsman-expert-review-v1:" + PACKAGE.source_manifest_identity.manifest_sha256;
    const $ = selector => document.querySelector(selector);
    const state = { session:null, index:0, viewMode:"CLEAN", markerToggle:false, busy:false, modalScale:1, drag:null, noteTimer:null };
    function now() { return new Date().toISOString(); }
    function sessionId() { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); return "expert-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2); }
    function blankItems() { const items = {}; PACKAGE.items.forEach(item => { items[item.candidate_id] = { human_label:null, reviewer_note:null, review_status:"PENDING", updated_at:null, label_history:[] }; }); return items; }
    function newSession() { const timestamp = now(); return { schema_version:1, review_session_id:sessionId(), reviewer_id:null, reviewer_role:"DOMAIN_PRACTITIONER", reviewer_note:null, review_started_at:timestamp, review_updated_at:timestamp, review_order:PACKAGE.review_order.slice(), items:blankItems() }; }
    function validOrder(order) { return Array.isArray(order) && order.length === PACKAGE.items.length && order.every((id, index) => id === PACKAGE.review_order[index]); }
    function normalizeSession(raw) {
      if (!raw || raw.schema_version !== 1 || !validOrder(raw.review_order) || !raw.items || typeof raw.items !== "object") return null;
      const expected = new Set(PACKAGE.review_order); if (Object.keys(raw.items).length !== expected.size || Object.keys(raw.items).some(id => !expected.has(id))) return null;
      const items = {};
      for (const id of PACKAGE.review_order) {
        const item = raw.items[id]; if (!item || ![null, ...LABEL_VALUES].includes(item.human_label)) return null;
        const status = item.human_label === null ? "PENDING" : "REVIEWED";
        if (item.review_status !== status || (item.reviewer_note !== null && typeof item.reviewer_note !== "string")) return null;
        items[id] = { human_label:item.human_label, reviewer_note:item.reviewer_note || null, review_status:status, updated_at:item.updated_at || null, label_history:Array.isArray(item.label_history) ? item.label_history : [] };
      }
      return { schema_version:1, review_session_id:typeof raw.review_session_id === "string" && raw.review_session_id ? raw.review_session_id : sessionId(), reviewer_id:typeof raw.reviewer_id === "string" ? raw.reviewer_id : null, reviewer_role:typeof raw.reviewer_role === "string" && raw.reviewer_role ? raw.reviewer_role : "DOMAIN_PRACTITIONER", reviewer_note:typeof raw.reviewer_note === "string" ? raw.reviewer_note : null, review_started_at:raw.review_started_at || now(), review_updated_at:raw.review_updated_at || now(), review_order:PACKAGE.review_order.slice(), items };
    }
    function loadSession() { let raw = null; try { raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); } catch (_) {} state.session = normalizeSession(raw) || newSession(); const pending = PACKAGE.review_order.findIndex(id => state.session.items[id].human_label === null); state.index = pending >= 0 ? pending : 0; persist("状态：已加载本地审核会话"); }
    function persist(message) { state.session.review_updated_at = now(); try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.session)); setStatus(message || "状态：已自动保存"); } catch (_) { setStatus("状态：浏览器未允许本地保存；请及时导出 JSON"); } }
    function setStatus(message) { $("#save-status").textContent = message; }
    function currentItem() { return PACKAGE.items[state.index]; }
    function currentState() { return state.session.items[currentItem().candidate_id]; }
    function esc(value) { return String(value).replace(/[&<>\"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[character])); }
    function markerSvg(marker) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.classList.add("marker-layer"); svg.setAttribute("viewBox", `0 0 ${marker.width} ${marker.height}`); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("aria-label", "候选位置标记");
      function line(segment, className) { const line = document.createElementNS("http://www.w3.org/2000/svg", "line"); line.setAttribute("x1", segment.start[0]); line.setAttribute("y1", segment.start[1]); line.setAttribute("x2", segment.end[0]); line.setAttribute("y2", segment.end[1]); line.classList.add(className); svg.appendChild(line); }
      function endpoint(point, className) { const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); circle.setAttribute("cx", point[0]); circle.setAttribute("cy", point[1]); circle.setAttribute("r", "5"); circle.classList.add(className); svg.appendChild(circle); const crossA = document.createElementNS("http://www.w3.org/2000/svg", "line"); crossA.setAttribute("x1", point[0]-8); crossA.setAttribute("y1", point[1]); crossA.setAttribute("x2", point[0]+8); crossA.setAttribute("y2", point[1]); crossA.classList.add("endpoint-cross", className); svg.appendChild(crossA); const crossB = document.createElementNS("http://www.w3.org/2000/svg", "line"); crossB.setAttribute("x1", point[0]); crossB.setAttribute("y1", point[1]-8); crossB.setAttribute("x2", point[0]); crossB.setAttribute("y2", point[1]+8); crossB.classList.add("endpoint-cross", className); svg.appendChild(crossB); }
      line(marker.fragment_a, "fragment-a"); line(marker.fragment_b, "fragment-b"); endpoint(marker.gap_endpoint_a, "endpoint-a"); endpoint(marker.gap_endpoint_b, "endpoint-b"); return svg;
    }
    function imageStage(item, kind, marked) { const stage = document.createElement("div"); stage.className = "image-stage"; stage.tabIndex = 0; const image = document.createElement("img"); image.src = item[kind === "local" ? "local_image" : "context_image"]; image.alt = `${item.candidate_id} ${kind.toUpperCase()} 清洁证据`; stage.appendChild(image); if (marked) stage.appendChild(markerSvg(item.marker[kind])); stage.addEventListener("click", () => openModal(item, kind, marked)); stage.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openModal(item, kind, marked); } }); return stage; }
    function imagePanel(item, kind, marked, label) { const card = document.createElement("div"); card.className = "evidence-card"; const heading = document.createElement("h3"); heading.textContent = label; card.appendChild(heading); card.appendChild(imageStage(item, kind, marked)); return card; }
    function renderEvidence() { const item = currentItem(); const grid = $("#evidence-grid"); grid.innerHTML = ""; const marked = state.markerToggle || state.viewMode === "MARKED"; if (state.viewMode === "COMPARE") { [ ["local","LOCAL"], ["context","CONTEXT"] ].forEach(([kind, label]) => { const card = document.createElement("div"); card.className = "evidence-card"; const heading = document.createElement("h3"); heading.textContent = label; card.appendChild(heading); const wrap = document.createElement("div"); wrap.className = "compare-wrap"; const clean = document.createElement("div"); clean.innerHTML = '<div class="compare-label">清洁证据（无标记）</div>'; clean.appendChild(imageStage(item, kind, false)); const tagged = document.createElement("div"); tagged.innerHTML = '<div class="compare-label">候选标记（可选）</div>'; tagged.appendChild(imageStage(item, kind, true)); wrap.append(clean, tagged); card.appendChild(wrap); grid.appendChild(card); }); } else { grid.appendChild(imagePanel(item, "local", marked, "LOCAL · 清洁源证据")); grid.appendChild(imagePanel(item, "context", marked, "CONTEXT · 清洁源证据")); } $("#view-status").textContent = state.viewMode === "COMPARE" ? "清洁 + 标记对照 · 点击任一图片可放大" : marked ? "标记视图 · 图例解释所有标记" : "清洁视图 · 原图未加候选图形"; }
    function renderLabels() { const current = currentState(); const grid = $("#label-grid"); grid.innerHTML = ""; LABELS.forEach(label => { const button = document.createElement("button"); button.className = "label-button" + (current.human_label === label.value ? " active" : ""); button.dataset.label = label.value; button.innerHTML = `<span class="key">${label.key}</span><strong>${label.title}</strong><small>${label.value}<br>${label.text}</small>`; button.addEventListener("click", () => setLabel(label.value)); grid.appendChild(button); }); }
    function renderCounts() { const counts = {}; LABELS.forEach(label => counts[label.value] = 0); let completed = 0; PACKAGE.review_order.forEach(id => { const label = state.session.items[id].human_label; if (label) { completed += 1; counts[label] += 1; } }); $("#completed-label").textContent = `已完成 ${completed} / ${PACKAGE.items.length} · 待审核 ${PACKAGE.items.length - completed}`; $("#counts").innerHTML = LABELS.map(label => `<div class="count"><strong>${counts[label.value]}</strong>${label.title}</div>`).join(""); $("#completion").classList.toggle("visible", completed === PACKAGE.items.length); }
    function render() { const item = currentItem(); const itemState = currentState(); $("#progress-label").textContent = `候选 ${item.review_index} / ${PACKAGE.items.length}`; $("#candidate-title").textContent = `候选 ${item.review_index} · ${item.candidate_id}`; $("#candidate-note").value = itemState.reviewer_note || ""; $("#reviewer-id").value = state.session.reviewer_id || ""; $("#reviewer-role").value = state.session.reviewer_role || "DOMAIN_PRACTITIONER"; $("#reviewer-note").value = state.session.reviewer_note || ""; $("#marker-toggle").checked = state.markerToggle; document.querySelectorAll(".view-button").forEach(button => button.classList.toggle("active", button.dataset.view === state.viewMode)); renderEvidence(); renderLabels(); renderCounts(); }
    function setLabel(label) { if (state.busy || !LABEL_VALUES.has(label)) return; const itemState = currentState(); const old = itemState.human_label; const timestamp = now(); if (old !== label) itemState.label_history.push({ timestamp, old_label:old, new_label:label }); itemState.human_label = label; itemState.review_status = "REVIEWED"; itemState.updated_at = timestamp; persist(`状态：已保存「${LABELS.find(item => item.value === label).title}」`); render(); const next = PACKAGE.review_order.findIndex((id, index) => index > state.index && state.session.items[id].human_label === null); if (next >= 0) { state.index = next; setTimeout(render, 220); } }
    function saveCandidateNote() { const note = $("#candidate-note").value.trim(); currentState().reviewer_note = note || null; currentState().updated_at = now(); persist("状态：候选备注已保存"); }
    function saveIdentity() { state.session.reviewer_id = $("#reviewer-id").value.trim() || null; state.session.reviewer_role = $("#reviewer-role").value.trim() || "DOMAIN_PRACTITIONER"; state.session.reviewer_note = $("#reviewer-note").value.trim() || null; persist("状态：审核者信息已保存"); }
    function move(delta) { saveCandidateNote(); state.index = Math.max(0, Math.min(PACKAGE.items.length - 1, state.index + delta)); render(); }
    function openModal(item, kind, marked) { $("#modal-title").textContent = `${item.candidate_id} · ${kind.toUpperCase()}${marked ? " · 标记" : " · 清洁"}`; const content = $("#zoom-content"); content.innerHTML = ""; const image = document.createElement("img"); image.src = item[kind === "local" ? "local_image" : "context_image"]; image.alt = "放大查看"; content.appendChild(image); if (marked) content.appendChild(markerSvg(item.marker[kind])); state.modalScale = 1; updateModalScale(); $("#image-modal").hidden = false; document.body.style.overflow = "hidden"; $("#modal-close").focus(); }
    function closeModal() { $("#image-modal").hidden = true; document.body.style.overflow = ""; }
    function updateModalScale() { $("#zoom-content").style.transform = `scale(${state.modalScale})`; $("#zoom-readout").textContent = `${Math.round(state.modalScale * 100)}%`; }
    function adjustZoom(delta) { state.modalScale = Math.max(.5, Math.min(4, state.modalScale + delta)); updateModalScale(); }
    function downloadJson(payload, filename) { const blob = new Blob([JSON.stringify(payload, null, 2)], {type:"application/json;charset=utf-8"}); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 500); }
    function exportResult() { saveCandidateNote(); saveIdentity(); const exportedAt = now(); const payload = { schema_version:1, review_session_id:state.session.review_session_id, reviewer_id:state.session.reviewer_id, reviewer_role:state.session.reviewer_role, reviewer_note:state.session.reviewer_note, source_manifest_identity:PACKAGE.source_manifest_identity, review_started_at:state.session.review_started_at, review_exported_at:exportedAt, review_order:PACKAGE.review_order.slice(), items:PACKAGE.items.map(item => ({ review_index:item.review_index, candidate_id:item.candidate_id, human_label:state.session.items[item.candidate_id].human_label, reviewer_note:state.session.items[item.candidate_id].reviewer_note, review_status:state.session.items[item.candidate_id].review_status, updated_at:state.session.items[item.candidate_id].updated_at, label_history:state.session.items[item.candidate_id].label_history })) }; downloadJson(payload, `expert-review-${state.session.review_session_id}.json`); $("#export-status").textContent = `已导出：${payload.items.filter(item => item.human_label).length}/${payload.items.length} 已完成。`; }
    function validateImport(payload) { if (!payload || payload.schema_version !== 1 || !payload.source_manifest_identity || payload.source_manifest_identity.manifest_sha256 !== PACKAGE.source_manifest_identity.manifest_sha256 || !validOrder(payload.review_order) || !Array.isArray(payload.items) || payload.items.length !== PACKAGE.items.length) throw new Error("结果文件与本专家包的冻结候选集合不匹配"); const byId = {}; payload.items.forEach(item => { if (!item || byId[item.candidate_id] || !PACKAGE.review_order.includes(item.candidate_id) || ![null, ...LABEL_VALUES].includes(item.human_label)) throw new Error("结果文件包含未知候选或非法标签"); byId[item.candidate_id] = item; }); if (Object.keys(byId).length !== PACKAGE.items.length) throw new Error("结果文件未覆盖全部候选"); return byId; }
    function importResult(file) { const reader = new FileReader(); reader.onload = () => { try { const payload = JSON.parse(reader.result); const imported = validateImport(payload); const hasLabels = Object.values(imported).some(item => item.human_label !== null); if (hasLabels && !window.confirm("该文件包含已有审核结果，可能来自另一位审核者。只有在确认它属于 Reviewer B 当前会话时才导入；本操作不会合并或裁决标签。继续导入吗？")) return; const session = newSession(); session.review_session_id = typeof payload.review_session_id === "string" && payload.review_session_id ? payload.review_session_id : session.review_session_id; session.reviewer_id = typeof payload.reviewer_id === "string" ? payload.reviewer_id : null; session.reviewer_role = typeof payload.reviewer_role === "string" && payload.reviewer_role ? payload.reviewer_role : "DOMAIN_PRACTITIONER"; session.reviewer_note = typeof payload.reviewer_note === "string" ? payload.reviewer_note : null; session.review_started_at = payload.review_started_at || session.review_started_at; PACKAGE.review_order.forEach(id => { const item = imported[id]; session.items[id] = { human_label:item.human_label, reviewer_note:typeof item.reviewer_note === "string" ? item.reviewer_note : null, review_status:item.human_label === null ? "PENDING" : "REVIEWED", updated_at:item.updated_at || null, label_history:Array.isArray(item.label_history) ? item.label_history : [] }; }); state.session = session; const pending = PACKAGE.review_order.findIndex(id => state.session.items[id].human_label === null); state.index = pending >= 0 ? pending : 0; persist("状态：审核结果已导入并校验"); render(); } catch (error) { showError(error.message || "导入失败"); } }; reader.readAsText(file); }
    function showError(message) { const element = $("#error"); element.textContent = message; element.classList.add("visible"); setTimeout(() => element.classList.remove("visible"), 5000); }
    function isTyping(target) { return target && (["INPUT","TEXTAREA","SELECT"].includes(target.tagName) || target.isContentEditable); }
    $("#previous-button").addEventListener("click", () => move(-1)); $("#next-button").addEventListener("click", () => move(1)); $("#candidate-note").addEventListener("input", () => { clearTimeout(state.noteTimer); state.noteTimer = setTimeout(saveCandidateNote, 650); }); $("#reviewer-id").addEventListener("input", saveIdentity); $("#reviewer-role").addEventListener("input", saveIdentity); $("#reviewer-note").addEventListener("input", saveIdentity); $("#export-button").addEventListener("click", exportResult); $("#import-file").addEventListener("change", event => { if (event.target.files && event.target.files[0]) importResult(event.target.files[0]); event.target.value = ""; }); $("#marker-toggle").addEventListener("change", event => { state.markerToggle = event.target.checked; state.viewMode = state.markerToggle ? "MARKED" : "CLEAN"; render(); }); document.querySelectorAll(".view-button").forEach(button => button.addEventListener("click", () => { state.viewMode = button.dataset.view; state.markerToggle = state.viewMode !== "CLEAN"; render(); })); $("#modal-close").addEventListener("click", closeModal); $("#zoom-in").addEventListener("click", () => adjustZoom(.25)); $("#zoom-out").addEventListener("click", () => adjustZoom(-.25)); $("#zoom-reset").addEventListener("click", () => { state.modalScale = 1; updateModalScale(); }); $("#zoom-viewport").addEventListener("wheel", event => { event.preventDefault(); adjustZoom(event.deltaY < 0 ? .1 : -.1); }, {passive:false}); $("#zoom-viewport").addEventListener("pointerdown", event => { state.drag = {x:event.clientX, y:event.clientY, left:event.currentTarget.scrollLeft, top:event.currentTarget.scrollTop}; event.currentTarget.classList.add("dragging"); event.currentTarget.setPointerCapture(event.pointerId); }); $("#zoom-viewport").addEventListener("pointermove", event => { if (!state.drag) return; event.currentTarget.scrollLeft = state.drag.left - (event.clientX - state.drag.x); event.currentTarget.scrollTop = state.drag.top - (event.clientY - state.drag.y); }); $("#zoom-viewport").addEventListener("pointerup", () => { state.drag = null; $("#zoom-viewport").classList.remove("dragging"); }); $("#zoom-viewport").addEventListener("pointercancel", () => { state.drag = null; $("#zoom-viewport").classList.remove("dragging"); }); document.addEventListener("keydown", event => { if (!$(' #image-modal'.trim()).hidden) { if (event.key === "Escape") closeModal(); return; } if (isTyping(event.target)) return; if (["1","2","3","4"].includes(event.key)) { event.preventDefault(); setLabel(LABELS[Number(event.key)-1].value); } else if (event.key === "ArrowLeft") { event.preventDefault(); move(-1); } else if (event.key === "ArrowRight") { event.preventDefault(); move(1); } });
    try { loadSession(); render(); } catch (error) { showError(error.message || "审核会话加载失败"); }
  </script>
</body>
</html>
"""


def render_review_html(manifest: Mapping[str, Any]) -> str:
    return HTML_TEMPLATE.replace("__PACKAGE_MANIFEST__", _html_manifest_json(manifest))


def _readme() -> str:
    return """工程图纸专家盲审包 v1

这是一个离线、预测盲的 Reviewer B 独立审核包。双击 review.html 即可打开；不需要安装 Draftsman、Git、Python 或网络。

使用：
1. 默认清洁视图显示未加候选图形的 LOCAL 与 CONTEXT。
2. 如需确认候选位置，可打开“显示候选标记”。图例会说明 Fragment A、Fragment B 和两个间隙端点；标记不表示答案，也不会绘制连接桥。
3. 使用四个标签按钮或键盘 1 / 2 / 3 / 4。备注会自动保存到本地浏览器存储。
4. 审核完成后点击“导出审核结果 JSON”，只发送导出的 JSON 文件给项目负责人。

审核问题：如果人工重新描这张工程图，这两段是否应作为同一个实际工程对象的线连接起来？
看得出来才判；看不出来就选“无法可靠判断”，不要猜。

导出的 JSON 是独立的审核员观察记录，不是最终真值。不要将 Reviewer A 的结果导入本包，除非明确确认该文件属于当前 Reviewer B 会话；导入会要求确认。

EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
MODEL_EXPOSURE: NONE
REVIEWER_A_DATA_INCLUDED: NO
FULL_SOURCE_DWG_PDF_INCLUDED: NO
"""


def _safe_replace_directory(path: Path) -> None:
    path = path.resolve()
    if path.name != EXPERT_PACKAGE_NAME or path.parent.name != "draftsman" or path.parent.parent.name != "local-artifacts":
        raise ValueError(f"refusing to replace unexpected package path: {path}")
    if path.exists():
        shutil.rmtree(path)


def _zip_package(package_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir).as_posix())


def validate_built_package(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    if manifest.get("candidate_count") != 24 or len(manifest.get("items", [])) != 24:
        raise ValueError("expert package does not contain exactly 24 candidates")
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    if "fetch(" in html or "XMLHttpRequest" in html or "<script src=" in html or "<link href=" in html:
        raise ValueError("expert package contains a network dependency")
    if "REVIEWER_A" in html or "review-state.json" in html or "review-export.json" in html:
        raise ValueError("expert package exposes Reviewer A or mutable E2 state")
    if "Fragment A" not in html or "Fragment B" not in html or "Gap endpoint A" not in html or "Gap endpoint B" not in html:
        raise ValueError("expert package is missing the marker legend")
    local_count = context_count = 0
    for item in manifest["items"]:
        for key in ("local_image", "context_image"):
            path = package_dir / Path(*item[key].split("/"))
            if not path.is_file():
                raise FileNotFoundError(path)
            with Image.open(path) as image:
                if image.width <= 0 or image.height <= 0 or _colored_pixel_fraction(image) > 0.01:
                    raise ValueError(f"clean package image failed validation: {path}")
            if key == "local_image":
                local_count += 1
            else:
                context_count += 1
    for path in package_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dwg", ".pdf", ".dxf"}:
            raise ValueError(f"full source document included: {path}")
    return {"candidate_count": len(manifest["items"]), "clean_local_count": local_count, "clean_context_count": context_count}


def build_expert_review_package(
    repo_root: Path,
    *,
    output_dir: Path | None = None,
    zip_path: Path | None = None,
    replace: bool = False,
) -> ExpertPackageBuild:
    repo_root = Path(repo_root).resolve()
    e1, candidates, paths = _ensure_frozen_inputs(repo_root)
    package_dir = Path(output_dir or paths["default_output"]).resolve()
    final_zip = Path(zip_path or paths["default_zip"]).resolve()
    if package_dir.exists():
        if not replace:
            raise FileExistsError(f"package directory exists; pass replace=True: {package_dir}")
        _safe_replace_directory(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = _package_manifest(e1, candidates, package_dir, paths)
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_dir / "review.html").write_text(render_review_html(manifest), encoding="utf-8")
    (package_dir / "README.txt").write_text(_readme(), encoding="utf-8")
    validate = validate_built_package(package_dir)
    _zip_package(package_dir, final_zip)
    return ExpertPackageBuild(
        package_dir=package_dir,
        zip_path=final_zip,
        manifest_sha256=manifest["source_manifest_identity"]["manifest_sha256"],
        candidate_count=validate["candidate_count"],
        clean_local_count=validate["clean_local_count"],
        clean_context_count=validate["clean_context_count"],
    )


__all__ = [
    "ALLOWED_LABELS",
    "EXPERT_PACKAGE_NAME",
    "ExpertPackageBuild",
    "build_expert_review_package",
    "render_review_html",
    "validate_built_package",
]
