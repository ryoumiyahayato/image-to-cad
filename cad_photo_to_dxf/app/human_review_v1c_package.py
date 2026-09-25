"""Build the V1C corrected-review package.

V1C is a focused presentation correction for the existing portable review
package.  It reuses the frozen E1/Local-D asset pipeline from
``expert_review_package`` but gives the reviewer a compact workflow, a fresh
independent browser session, and an image-coordinate-aligned marker overlay
inside the enlarged viewer.

The package contains no mutable Reviewer-A state and no model output.  The
static HTML is deliberately independent of the Draftsman GUI so the same
review-session shape can be reused by a future native client.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from .expert_review_package import (
    ALLOWED_LABELS,
    ExpertPackageBuild,
    _ensure_frozen_inputs,
    _html_manifest_json,
    _package_manifest,
    _zip_package,
    validate_built_package,
)


V1C_SCHEMA_VERSION = 2
V1C_PACKAGE_NAME = "human-review-package-v1c"


V1C_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>人工作图审核</title>
  <style>
    :root {
      color-scheme: light;
      --ink:#17202a; --muted:#5d6a76; --line:#d5dde5; --panel:#fff;
      --soft:#f3f6f8; --navy:#173447; --accent:#0b6e99;
      --red:#d83b3b; --blue:#2468d2; --yellow:#d29a00;
      --shadow:0 8px 24px rgba(30,48,64,.10);
    }
    * { box-sizing:border-box; }
    html, body { min-height:100%; }
    body {
      margin:0; padding:0 0 126px; background:#edf1f4; color:var(--ink);
      font-family:"Segoe UI","Microsoft YaHei",sans-serif; line-height:1.4;
    }
    button, input, textarea { font:inherit; }
    button { cursor:pointer; }
    .topbar {
      position:sticky; top:0; z-index:40; display:flex; align-items:center;
      gap:18px; min-height:64px; padding:10px 18px; color:#fff;
      background:var(--navy); box-shadow:0 2px 12px rgba(0,0,0,.20);
    }
    .brand { flex:0 0 auto; }
    .brand h1 { margin:0; font-size:20px; letter-spacing:.02em; }
    .progress { min-width:180px; margin-right:auto; color:#dce8ef; font-size:13px; }
    .progress strong { display:block; color:#fff; font-size:16px; }
    .top-actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
    .top-actions button, .top-actions label {
      display:inline-flex; align-items:center; gap:6px; min-height:36px;
      padding:7px 10px; border:1px solid rgba(255,255,255,.38); border-radius:7px;
      background:rgba(255,255,255,.10); color:#fff; font-size:13px;
    }
    .top-actions button:hover, .top-actions label:hover { background:rgba(255,255,255,.18); }
    .top-actions button.primary { background:#e7f5fb; border-color:#e7f5fb; color:#123d52; font-weight:700; }
    .top-actions input { accent-color:#f6c34a; }
    .shell { max-width:1800px; margin:0 auto; padding:10px 16px 0; }
    .compact-guidance {
      display:flex; align-items:center; gap:10px; flex-wrap:wrap; min-height:44px;
      margin-bottom:10px; padding:7px 10px; border:1px solid #ead79a;
      border-radius:8px; background:#fff9e8; font-size:13px;
    }
    .compact-guidance strong { color:#654c00; }
    .legend { display:inline-flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .legend-chip { display:inline-flex; align-items:center; gap:4px; color:#34424e; white-space:nowrap; }
    .legend-dot { width:10px; height:10px; display:inline-block; border-radius:50%; }
    .legend-dot.red { background:var(--red); }
    .legend-dot.blue { background:var(--blue); }
    .legend-dot.yellow { background:var(--yellow); }
    details { border:1px solid var(--line); border-radius:8px; background:#fff; }
    details > summary { cursor:pointer; padding:7px 10px; color:#315c72; font-weight:600; }
    .help { margin-bottom:10px; font-size:13px; }
    .help-content { padding:0 12px 10px; color:#46535f; }
    .help-content p { margin:6px 0; }
    .help-content ul { margin:4px 0 4px 20px; padding:0; }
    .evidence-panel {
      height:calc(100vh - 226px); min-height:480px; padding:10px;
      border:1px solid var(--line); border-radius:10px; background:#fff; box-shadow:var(--shadow);
    }
    .evidence-heading { display:flex; align-items:baseline; justify-content:space-between; gap:10px; margin:0 2px 7px; }
    .evidence-heading h2 { margin:0; font-size:16px; }
    .evidence-heading span { color:var(--muted); font-size:12px; }
    .evidence-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px; height:calc(100% - 29px); min-height:0; }
    .evidence-card { display:flex; flex-direction:column; min-width:0; min-height:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:var(--soft); }
    .evidence-card h3 { flex:0 0 auto; margin:0; padding:6px 10px; color:#314351; font-size:14px; background:#f8fafb; border-bottom:1px solid var(--line); }
    .image-stage { position:relative; flex:1 1 auto; min-height:0; display:flex; align-items:center; justify-content:center; overflow:auto; padding:5px; background:#fff; }
    .image-frame { position:relative; display:inline-block; max-width:100%; max-height:100%; line-height:0; }
    .image-frame img { display:block; max-width:100%; max-height:calc(100vh - 310px); width:auto; height:auto; object-fit:contain; }
    .image-stage .image-frame { cursor:zoom-in; }
    .marker-overlay { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; overflow:visible; }
    .marker-overlay .fragment-a { stroke:var(--red); }
    .marker-overlay .fragment-b { stroke:var(--blue); }
    .marker-overlay .candidate-gap { stroke:var(--yellow); }
    .marker-overlay line { fill:none; stroke-width:3; stroke-linecap:round; opacity:.72; vector-effect:non-scaling-stroke; }
    .marker-overlay .candidate-gap { stroke-width:2.5; stroke-dasharray:3 6; opacity:.78; }
    .marker-overlay circle { stroke:#fff; stroke-width:1.5; vector-effect:non-scaling-stroke; opacity:.88; }
    .marker-overlay .gap-a { fill:var(--red); }
    .marker-overlay .gap-b { fill:var(--blue); }
    .candidate-note { margin-top:8px; }
    .candidate-note textarea { width:100%; min-height:54px; resize:vertical; padding:7px; border:1px solid var(--line); border-radius:6px; }
    .note-status { color:var(--muted); font-size:12px; padding:0 10px 8px; }
    .review-bar {
      position:fixed; left:0; right:0; bottom:0; z-index:60; padding:8px 14px 10px;
      background:rgba(255,255,255,.97); border-top:1px solid #c9d4dd;
      box-shadow:0 -5px 18px rgba(30,48,64,.15); backdrop-filter:blur(6px);
    }
    .review-bar-inner { max-width:1800px; margin:0 auto; }
    .review-bar-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:0 0 5px; color:#4b5d69; font-size:12px; }
    .review-bar-heading strong { color:#173447; font-size:13px; }
    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
    .label-button {
      min-height:63px; padding:7px 9px; border:2px solid #bdc9d2; border-radius:8px;
      background:#f8fafb; color:#1e2d37; text-align:left; transition:background .12s,border-color .12s,transform .12s;
    }
    .label-button:hover { border-color:var(--accent); background:#eef8fc; }
    .label-button.active { border-color:#173447; background:#e2f1f7; box-shadow:inset 0 0 0 2px #fff; }
    .label-button .shortcut { display:inline-block; width:24px; color:#173447; font-size:21px; font-weight:800; vertical-align:middle; }
    .label-button .label-title { font-size:15px; font-weight:700; vertical-align:middle; }
    .label-button .label-code { display:block; margin-left:26px; color:#65747e; font-size:10px; letter-spacing:.01em; }
    .status-line { min-height:18px; margin-top:3px; color:#2c6847; font-size:12px; }
    .modal[hidden] { display:none; }
    .modal { position:fixed; inset:0; z-index:100; display:flex; align-items:stretch; justify-content:center; padding:14px; background:rgba(10,20,28,.78); }
    .modal-dialog { display:flex; flex-direction:column; width:min(1500px,100%); min-height:0; border-radius:10px; overflow:hidden; background:#eef2f4; box-shadow:0 18px 60px rgba(0,0,0,.35); }
    .modal-toolbar { display:flex; align-items:center; gap:9px; flex-wrap:wrap; padding:8px 11px; color:#fff; background:#173447; }
    .modal-toolbar strong { margin-right:auto; }
    .modal-toolbar button, .modal-toolbar label { min-height:32px; padding:5px 9px; border:1px solid rgba(255,255,255,.40); border-radius:6px; background:rgba(255,255,255,.10); color:#fff; }
    .modal-toolbar input { accent-color:#f6c34a; }
    .modal-legend { display:flex; gap:7px; flex-wrap:wrap; padding:5px 11px; color:#41515c; background:#fff; border-bottom:1px solid var(--line); font-size:12px; }
    .zoom-viewport { position:relative; flex:1; min-height:0; overflow:auto; padding:18px; background:#dce3e7; cursor:grab; }
    .zoom-viewport.dragging { cursor:grabbing; }
    .zoom-content { position:relative; display:inline-block; transform-origin:top left; line-height:0; }
    .zoom-content img { display:block; max-width:calc(100vw - 100px); max-height:calc(100vh - 180px); width:auto; height:auto; object-fit:contain; }
    .zoom-content .marker-overlay { position:absolute; inset:0; }
    .modal-footer { display:flex; justify-content:space-between; gap:8px; padding:5px 11px; color:#4c5c67; background:#fff; font-size:12px; }
    @media (max-width:1100px) {
      .topbar { align-items:flex-start; flex-wrap:wrap; }
      .progress { margin-right:0; }
      .top-actions { width:100%; justify-content:flex-start; }
      .evidence-panel { height:calc(100vh - 278px); }
    }
    @media (max-width:760px) {
      body { padding-bottom:216px; }
      .shell { padding:8px; }
      .evidence-panel { height:auto; min-height:0; }
      .evidence-grid { height:auto; grid-template-columns:1fr; }
      .evidence-card { min-height:330px; }
      .label-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .label-button { min-height:58px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><h1>人工作图审核</h1></div>
    <div class="progress" id="progress" aria-live="polite"><strong>候选 1 / 24</strong>已完成 0 / 24 · 待审核 24</div>
    <div class="top-actions">
      <label title="默认关闭；打开后仅显示候选位置标记"><input id="marker-toggle" type="checkbox">显示候选标记</label>
      <button id="fresh-button" type="button" title="保留当前本地会话并开始一个新的空白会话">开始新的更正审核</button>
      <button id="import-button" type="button">导入审核结果</button>
      <button id="export-button" class="primary" type="button">导出审核结果 JSON</button>
      <input id="import-file" type="file" accept="application/json,.json" hidden>
    </div>
  </header>

  <main class="shell">
    <section class="compact-guidance" aria-label="简要审核规则">
      <strong>看得出来才判；看不出来不要猜。</strong>
      <span>先判断红蓝候选本身是否选对。</span>
      <span class="legend" aria-label="候选标记图例">
        <span class="legend-chip"><i class="legend-dot red"></i>红 = Fragment A</span>
        <span class="legend-chip"><i class="legend-dot blue"></i>蓝 = Fragment B</span>
        <span class="legend-chip"><i class="legend-dot yellow"></i>黄 = Candidate gap only; NOT a suggested connection（Gap endpoint A ↔ Gap endpoint B）</span>
      </span>
      <details class="help">
        <summary>查看详细说明</summary>
        <div class="help-content">
          <p>红蓝选错或两条线无关 → <b>候选无效</b>。红蓝选对，并属于实际工程对象且本应连续 → <b>结构连续</b>。</p>
          <p>红蓝选对，但属于尺寸线、尺寸延长线、引出线、文字、表格、图框、标题栏或 revision / legend / drawing-layout rule → <b>注释 / 文字 / 图纸版式</b>。</p>
          <p>即使查看 LOCAL + CONTEXT 仍无法可靠判断 → <b>无法判断</b>。不需要说出具体专业对象名称；如果必须猜专业含义，请选“无法判断”。</p>
          <p>黄色只表示正在判断的候选 gap / region，不表示应该填充或连接。默认图像是干净证据；候选标记可以随时关闭。</p>
        </div>
      </details>
    </section>

    <section class="evidence-panel" aria-label="候选证据">
      <div class="evidence-heading"><h2 id="candidate-heading">候选 1</h2><span>点击任一图像可放大；放大后仍可切换干净 / 标记视图。</span></div>
      <div class="evidence-grid">
        <article class="evidence-card"><h3>LOCAL · 局部证据</h3><div id="local-stage" class="image-stage"></div></article>
        <article class="evidence-card"><h3>CONTEXT · 周边工程上下文</h3><div id="context-stage" class="image-stage"></div></article>
      </div>
    </section>

    <details id="candidate-note-details" class="candidate-note">
      <summary>添加备注（可选）</summary>
      <textarea id="candidate-note" aria-label="当前候选备注" placeholder="只在需要时记录你的判断理由"></textarea>
      <div class="note-status" id="note-status" aria-live="polite"></div>
    </details>
  </main>

  <section class="review-bar" aria-label="分类控制">
    <div class="review-bar-inner">
      <div class="review-bar-heading"><strong>选择一个分类</strong><span>键盘：1 / 2 / 3 / 4　← / → 浏览</span></div>
      <div id="label-grid" class="label-grid">
        <button class="label-button" type="button" data-label="STRUCTURAL_CONTINUATION"><span class="shortcut">1</span><span class="label-title">结构连续</span><span class="label-code">STRUCTURAL_CONTINUATION</span></button>
        <button class="label-button" type="button" data-label="ANNOTATION_OR_GLYPH"><span class="shortcut">2</span><span class="label-title">注释 / 文字 / 图纸版式</span><span class="label-code">ANNOTATION_OR_GLYPH</span></button>
        <button class="label-button" type="button" data-label="AMBIGUOUS"><span class="shortcut">3</span><span class="label-title">无法判断</span><span class="label-code">AMBIGUOUS</span></button>
        <button class="label-button" type="button" data-label="INVALID_FOR_TASK"><span class="shortcut">4</span><span class="label-title">候选无效</span><span class="label-code">INVALID_FOR_TASK</span></button>
      </div>
      <div class="status-line" id="status-line" aria-live="polite"></div>
    </div>
  </section>

  <div id="image-modal" class="modal" hidden role="dialog" aria-modal="true" aria-label="放大图像">
    <div class="modal-dialog">
      <div class="modal-toolbar">
        <strong id="modal-title">候选</strong>
        <label title="只切换本次放大查看"><input id="modal-marker-toggle" type="checkbox">显示候选标记</label>
        <button id="zoom-out" type="button" aria-label="缩小">−</button>
        <button id="zoom-fit" type="button">适合窗口</button>
        <button id="zoom-in" type="button" aria-label="放大">+</button>
        <button id="modal-close" type="button">关闭</button>
      </div>
      <div class="modal-legend">
        <span class="legend-chip"><i class="legend-dot red"></i>红 = Fragment A</span>
        <span class="legend-chip"><i class="legend-dot blue"></i>蓝 = Fragment B</span>
        <span class="legend-chip"><i class="legend-dot yellow"></i>黄 = Candidate gap only; NOT a suggested connection（Gap endpoint A ↔ Gap endpoint B）</span>
      </div>
      <div id="zoom-viewport" class="zoom-viewport"><div id="zoom-content" class="zoom-content"></div></div>
      <div class="modal-footer"><span id="modal-view-kind"></span><span id="modal-zoom-label">100%</span></div>
    </div>
  </div>

  <script>
  "use strict";
  const PACKAGE = __PACKAGE_MANIFEST__;
  const STORAGE_KEY = "draftsman-human-review-v1c:" + PACKAGE.source_manifest_identity.manifest_sha256;
  const HISTORY_PREFIX = STORAGE_KEY + ":history:";
  const ALLOWED_LABELS = Object.freeze(PACKAGE.allowed_human_labels.slice());
  const state = {
    session: null, index: 0, markerToggle: false, busy: false, noteTimer: null,
    modal: null, modalScale: 1, drag: null
  };

  function now() { return new Date().toISOString(); }
  function newSession() {
    const timestamp = now();
    return {
      schema_version: 2,
      session_id: "corrected-review-" + timestamp.replace(/[-:.TZ]/g, "") + "-" + Math.random().toString(36).slice(2, 8),
      session_type: "CORRECTED_HUMAN_REVIEW",
      source_manifest_identity: PACKAGE.source_manifest_identity,
      review_started_at: timestamp,
      review_updated_at: timestamp,
      review_order: PACKAGE.review_order.slice(),
      items: PACKAGE.items.map(function(item) {
        return {
          review_index: item.review_index,
          candidate_id: item.candidate_id,
          human_label: null,
          reviewer_note: null,
          review_status: "PENDING",
          updated_at: timestamp,
          label_history: []
        };
      })
    };
  }
  function sameArray(a, b) { return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(function(value, i) { return value === b[i]; }); }
  function normalizeSession(raw) {
    if (!raw || raw.schema_version !== 2 || raw.session_type !== "CORRECTED_HUMAN_REVIEW") return null;
    if (JSON.stringify(raw.source_manifest_identity) !== JSON.stringify(PACKAGE.source_manifest_identity)) return null;
    if (!sameArray(raw.review_order, PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length !== PACKAGE.items.length) return null;
    const allowedIds = new Set(PACKAGE.review_order);
    const seen = new Set();
    const timestamp = now();
    const items = raw.items.map(function(item) {
      if (!item || !allowedIds.has(item.candidate_id) || seen.has(item.candidate_id)) throw new Error("candidate identity mismatch");
      seen.add(item.candidate_id);
      if (item.human_label !== null && !ALLOWED_LABELS.includes(item.human_label)) throw new Error("label vocabulary mismatch");
      return {
        review_index: item.review_index,
        candidate_id: item.candidate_id,
        human_label: item.human_label === undefined ? null : item.human_label,
        reviewer_note: item.reviewer_note || null,
        review_status: item.human_label ? "REVIEWED" : "PENDING",
        updated_at: item.updated_at || timestamp,
        label_history: Array.isArray(item.label_history) ? item.label_history : []
      };
    });
    if (seen.size !== PACKAGE.review_order.length) return null;
    return Object.assign({}, raw, { items: items, review_updated_at: raw.review_updated_at || timestamp });
  }
  function saveSession() {
    if (!state.session) return;
    state.session.review_updated_at = now();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.session));
  }
  function loadSession() {
    let loaded = null;
    try { loaded = normalizeSession(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")); } catch (error) { loaded = null; }
    state.session = loaded || newSession();
    const firstPending = state.session.items.findIndex(function(item) { return !item.human_label; });
    state.index = firstPending >= 0 ? firstPending : 0;
    saveSession();
  }
  function currentItem() { return state.session.items[state.index]; }
  function packageItem(candidateId) { return PACKAGE.items.find(function(item) { return item.candidate_id === candidateId; }); }
  function counts() {
    const reviewed = state.session.items.filter(function(item) { return Boolean(item.human_label); });
    const result = { completed: reviewed.length, pending: state.session.items.length - reviewed.length };
    ALLOWED_LABELS.forEach(function(label) { result[label] = reviewed.filter(function(item) { return item.human_label === label; }).length; });
    return result;
  }
  function setStatus(message) { document.getElementById("status-line").textContent = message || ""; }
  function renderProgress() {
    const tally = counts();
    document.getElementById("progress").innerHTML = "<strong>候选 " + (state.index + 1) + " / " + PACKAGE.candidate_count + "</strong>已完成 " + tally.completed + " / " + PACKAGE.candidate_count + " · 待审核 " + tally.pending;
    document.getElementById("candidate-heading").textContent = "候选 " + (state.index + 1) + " · " + currentItem().candidate_id;
    if (tally.completed === PACKAGE.candidate_count) setStatus(PACKAGE.candidate_count + " / " + PACKAGE.candidate_count + " 已完成。请导出审核结果 JSON。" );
  }
  function point(value) { return { x:Number(value[0]), y:Number(value[1]) }; }
  function markerSvg(marker) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + marker.width + " " + marker.height);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "marker-overlay");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "候选位置标记：Fragment A、Fragment B、Candidate gap");
    function line(a, b, className) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", "line");
      element.setAttribute("x1", a.x); element.setAttribute("y1", a.y); element.setAttribute("x2", b.x); element.setAttribute("y2", b.y); element.setAttribute("class", className);
      svg.appendChild(element);
    }
    function circle(p, className) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      element.setAttribute("cx", p.x); element.setAttribute("cy", p.y); element.setAttribute("r", "5"); element.setAttribute("class", className); svg.appendChild(element);
    }
    const a0 = point(marker.fragment_a.start), a1 = point(marker.fragment_a.end);
    const b0 = point(marker.fragment_b.start), b1 = point(marker.fragment_b.end);
    const gapA = point(marker.gap_endpoint_a), gapB = point(marker.gap_endpoint_b);
    line(a0, a1, "fragment-a"); line(b0, b1, "fragment-b");
    line(gapA, gapB, "candidate-gap"); circle(gapA, "gap-a"); circle(gapB, "gap-b");
    return svg;
  }
  function imageStage(item, kind) {
    const stage = document.createElement("div");
    stage.className = "image-stage";
    stage.title = "点击放大";
    const frame = document.createElement("div"); frame.className = "image-frame";
    const image = document.createElement("img"); image.alt = kind === "local" ? "LOCAL clean evidence" : "CONTEXT clean evidence";
    image.src = kind === "local" ? item.local_image : item.context_image;
    frame.appendChild(image);
    if (state.markerToggle) frame.appendChild(markerSvg(item.marker[kind]));
    stage.appendChild(frame);
    stage.addEventListener("click", function() { openModal(item, kind, state.markerToggle); });
    return stage;
  }
  function renderEvidence() {
    const item = packageItem(currentItem().candidate_id);
    const local = document.getElementById("local-stage"); const context = document.getElementById("context-stage");
    local.replaceChildren(imageStage(item, "local")); context.replaceChildren(imageStage(item, "context"));
    document.getElementById("marker-toggle").checked = state.markerToggle;
  }
  function renderLabels() {
    const label = currentItem().human_label;
    document.querySelectorAll(".label-button").forEach(function(button) { button.classList.toggle("active", button.dataset.label === label); });
  }
  function renderNote() {
    const note = currentItem().reviewer_note || "";
    document.getElementById("candidate-note").value = note;
    document.getElementById("note-status").textContent = note ? "备注已保存到当前本地审核会话。" : "";
  }
  function render() { renderProgress(); renderEvidence(); renderLabels(); renderNote(); }
  function advanceToNextPending() {
    const total = state.session.items.length;
    for (let offset = 1; offset <= total; offset += 1) {
      const candidateIndex = (state.index + offset) % total;
      if (!state.session.items[candidateIndex].human_label) { state.index = candidateIndex; return; }
    }
  }
  function setLabel(label) {
    if (!ALLOWED_LABELS.includes(label) || state.busy) return;
    const item = currentItem(); const old = item.human_label; const timestamp = now();
    if (old !== label) item.label_history.push({ timestamp:timestamp, old_label:old, new_label:label });
    item.human_label = label; item.review_status = "REVIEWED"; item.updated_at = timestamp;
    saveSession(); render(); setStatus("已保存：" + label + "。正在前往下一个待审核候选。");
    state.busy = true;
    window.setTimeout(function() { advanceToNextPending(); state.busy = false; render(); }, 180);
  }
  function saveCandidateNote() {
    const value = document.getElementById("candidate-note").value.trim();
    currentItem().reviewer_note = value || null; currentItem().updated_at = now(); saveSession();
    document.getElementById("note-status").textContent = value ? "备注已保存到当前本地审核会话。" : "备注已清空。";
  }
  function scheduleNoteSave() { window.clearTimeout(state.noteTimer); state.noteTimer = window.setTimeout(saveCandidateNote, 350); }
  function navigate(delta) { state.index = Math.max(0, Math.min(state.session.items.length - 1, state.index + delta)); render(); }
  function freshCorrectedReview() {
    const hasAnswers = state.session.items.some(function(item) { return item.human_label || item.reviewer_note; });
    if (hasAnswers && !window.confirm("开始新的更正审核？当前本地会话会保留，不会删除。")) return;
    if (hasAnswers) localStorage.setItem(HISTORY_PREFIX + state.session.session_id, JSON.stringify(state.session));
    state.session = newSession(); state.index = 0; saveSession(); render(); setStatus("新的更正审核已开始：0 / " + PACKAGE.candidate_count + "。");
  }
  function downloadJson(filename, value) {
    const blob = new Blob([JSON.stringify(value, null, 2) + "\n"], { type:"application/json" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click();
    window.setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
  }
  function exportResult() {
    saveCandidateNote();
    const exported = now();
    const payload = {
      schema_version: 2,
      session_id: state.session.session_id,
      session_type: "CORRECTED_HUMAN_REVIEW",
      source_manifest_identity: PACKAGE.source_manifest_identity,
      review_started_at: state.session.review_started_at,
      review_exported_at: exported,
      review_order: PACKAGE.review_order.slice(),
      items: state.session.items.map(function(item) { return {
        review_index:item.review_index, candidate_id:item.candidate_id,
        human_label:item.human_label, reviewer_note:item.reviewer_note,
        review_status:item.human_label ? "REVIEWED" : "PENDING",
        updated_at:item.updated_at, label_history:item.label_history
      }; })
    };
    downloadJson("human-review-v1c-" + state.session.session_id + ".json", payload);
    setStatus("审核结果已导出。" );
  }
  function validateImport(raw) {
    if (!raw || raw.schema_version !== 2 || raw.session_type !== "CORRECTED_HUMAN_REVIEW") throw new Error("不是当前更正审核格式；不会导入旧审核包。");
    if (JSON.stringify(raw.source_manifest_identity) !== JSON.stringify(PACKAGE.source_manifest_identity)) throw new Error("审核结果与当前 24 个候选不匹配。");
    if (!sameArray(raw.review_order, PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length !== PACKAGE.candidate_count) throw new Error("审核顺序或候选数量不匹配。");
    const session = newSession(); session.session_id = raw.session_id || session.session_id; session.review_started_at = raw.review_started_at || session.review_started_at;
    raw.items.forEach(function(item) {
      const target = session.items.find(function(candidate) { return candidate.candidate_id === item.candidate_id; });
      if (!target) throw new Error("候选 ID 不匹配。");
      if (item.human_label !== null && !ALLOWED_LABELS.includes(item.human_label)) throw new Error("包含不允许的标签。");
      target.human_label = item.human_label || null; target.reviewer_note = item.reviewer_note || null; target.review_status = target.human_label ? "REVIEWED" : "PENDING"; target.updated_at = item.updated_at || now(); target.label_history = Array.isArray(item.label_history) ? item.label_history : [];
    });
    return session;
  }
  function importResult(event) {
    const file = event.target.files && event.target.files[0]; if (!file) return;
    const reader = new FileReader(); reader.onload = function() {
      try {
        const imported = validateImport(JSON.parse(reader.result));
        if (state.session.items.some(function(item) { return item.human_label; }) && !window.confirm("导入会替换当前更正审核会话；当前会话会先保留在本地历史。继续？")) return;
        localStorage.setItem(HISTORY_PREFIX + state.session.session_id, JSON.stringify(state.session)); state.session = imported; state.index = Math.max(0, state.session.items.findIndex(function(item) { return !item.human_label; })); saveSession(); render(); setStatus("审核结果已导入当前更正审核会话。" );
      } catch (error) { window.alert(error.message || "导入失败。"); }
      event.target.value = "";
    }; reader.readAsText(file, "utf-8");
  }
  function setModalScale(value) { state.modalScale = Math.max(.5, Math.min(4, Math.round(value * 100) / 100)); const content = document.getElementById("zoom-content"); content.style.transform = "scale(" + state.modalScale + ")"; document.getElementById("modal-zoom-label").textContent = Math.round(state.modalScale * 100) + "%"; }
  function renderModal() {
    if (!state.modal) return;
    const item = packageItem(state.modal.item.candidate_id); const marker = item.marker[state.modal.kind]; const content = document.getElementById("zoom-content"); content.replaceChildren();
    const image = document.createElement("img"); image.alt = state.modal.kind === "local" ? "LOCAL enlarged evidence" : "CONTEXT enlarged evidence"; image.src = state.modal.kind === "local" ? item.local_image : item.context_image; content.appendChild(image);
    if (state.modal.marked) content.appendChild(markerSvg(marker));
    document.getElementById("modal-marker-toggle").checked = state.modal.marked;
    document.getElementById("modal-title").textContent = "候选 " + state.modal.item.review_index + " · " + item.candidate_id;
    document.getElementById("modal-view-kind").textContent = state.modal.kind === "local" ? "LOCAL · 局部证据" : "CONTEXT · 周边工程上下文";
    setModalScale(state.modalScale);
  }
  function openModal(item, kind, marked) { state.modal = { item:item, kind:kind, marked:Boolean(marked) }; state.modalScale = 1; document.getElementById("image-modal").hidden = false; renderModal(); }
  function closeModal() { document.getElementById("image-modal").hidden = true; state.modal = null; state.drag = null; }
  function keyHandler(event) {
    const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : "";
    if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return;
    if (state.modal) { if (event.key === "Escape") { event.preventDefault(); closeModal(); } return; }
    if (event.key === "1") setLabel("STRUCTURAL_CONTINUATION");
    else if (event.key === "2") setLabel("ANNOTATION_OR_GLYPH");
    else if (event.key === "3") setLabel("AMBIGUOUS");
    else if (event.key === "4") setLabel("INVALID_FOR_TASK");
    else if (event.key === "ArrowLeft") { event.preventDefault(); navigate(-1); }
    else if (event.key === "ArrowRight") { event.preventDefault(); navigate(1); }
  }
  document.getElementById("marker-toggle").addEventListener("change", function(event) { state.markerToggle = event.target.checked; renderEvidence(); });
  document.getElementById("fresh-button").addEventListener("click", freshCorrectedReview);
  document.getElementById("import-button").addEventListener("click", function() { document.getElementById("import-file").click(); });
  document.getElementById("import-file").addEventListener("change", importResult);
  document.getElementById("export-button").addEventListener("click", exportResult);
  document.querySelectorAll(".label-button").forEach(function(button) { button.addEventListener("click", function() { setLabel(button.dataset.label); }); });
  document.getElementById("candidate-note").addEventListener("input", scheduleNoteSave);
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal-marker-toggle").addEventListener("change", function(event) { if (state.modal) { state.modal.marked = event.target.checked; renderModal(); } });
  document.getElementById("zoom-out").addEventListener("click", function() { setModalScale(state.modalScale - .25); });
  document.getElementById("zoom-in").addEventListener("click", function() { setModalScale(state.modalScale + .25); });
  document.getElementById("zoom-fit").addEventListener("click", function() { setModalScale(1); });
  const viewport = document.getElementById("zoom-viewport");
  viewport.addEventListener("wheel", function(event) { if (!state.modal) return; event.preventDefault(); setModalScale(state.modalScale + (event.deltaY < 0 ? .15 : -.15)); }, { passive:false });
  viewport.addEventListener("pointerdown", function(event) { if (!state.modal || state.modalScale <= 1) return; state.drag = { x:event.clientX, y:event.clientY, left:viewport.scrollLeft, top:viewport.scrollTop }; viewport.classList.add("dragging"); viewport.setPointerCapture(event.pointerId); });
  viewport.addEventListener("pointermove", function(event) { if (!state.drag) return; viewport.scrollLeft = state.drag.left - (event.clientX - state.drag.x); viewport.scrollTop = state.drag.top - (event.clientY - state.drag.y); });
  viewport.addEventListener("pointerup", function() { state.drag = null; viewport.classList.remove("dragging"); });
  viewport.addEventListener("pointercancel", function() { state.drag = null; viewport.classList.remove("dragging"); });
  document.addEventListener("keydown", keyHandler);
  loadSession(); render();
  </script>
</body>
</html>
'''


def render_v1c_html(manifest: Mapping[str, Any]) -> str:
    """Render the self-contained V1C review page."""

    # Prevent an embedded manifest value from terminating the data script.
    payload = _html_manifest_json(manifest).replace("<", "\\u003c")
    return V1C_HTML_TEMPLATE.replace("__PACKAGE_MANIFEST__", payload)


def _v1c_readme() -> str:
    return """人工作图审核包 V1C

这是一个离线、预测盲的 24 项人工作图审核包。双击 review.html 即可打开，不需要 Draftsman、Git、Python 或网络。

默认显示干净的 LOCAL 与 CONTEXT 证据。需要确认候选位置时，打开“显示候选标记”：
红 = Fragment A；蓝 = Fragment B；黄 = Candidate gap only，不是建议连接。

使用键盘 1 / 2 / 3 / 4 或底部固定按钮选择标签。备注和进度保存在本地浏览器存储中；可用“开始新的更正审核”保留当前会话并开始新的空白会话。完成后点击“导出审核结果 JSON”，只发送导出的 JSON 文件。

审核问题：如果人工重新描这张工程图，这两段是否应作为同一个实际工程对象的线连接起来？看得出来才判；看不出来不要猜。

EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
MODEL_EXPOSURE: NONE
REVIEWER_A_DATA_INCLUDED: NO
FULL_SOURCE_DWG_PDF_INCLUDED: NO
"""


def _safe_replace_v1c_directory(path: Path) -> None:
    path = path.resolve()
    expected_parent = path.parents[1] if len(path.parents) > 1 else None
    if path.name != V1C_PACKAGE_NAME or expected_parent is None or expected_parent.name != "local-artifacts" or path.parent.name != "draftsman":
        raise ValueError(f"refusing to replace unexpected V1C package path: {path}")
    if path.exists():
        shutil.rmtree(path)


def validate_v1c_package(package_dir: Path) -> dict[str, Any]:
    """Validate V1C's static/offline and source-minimization invariants."""

    package_dir = Path(package_dir)
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    if manifest.get("package_id") != V1C_PACKAGE_NAME or manifest.get("candidate_count") != 24:
        raise ValueError("V1C package identity or candidate count is invalid")
    if len(manifest.get("items", [])) != 24 or len(manifest.get("review_order", [])) != 24:
        raise ValueError("V1C package must contain exactly 24 ordered items")
    if "reviewer_id" in html or "reviewer_role" in html or "reviewer_identity" in html:
        raise ValueError("V1C primary UI contains removed reviewer metadata")
    if "REVIEWER_A" in html or "review-state.json" in html or "review-export.json" in html:
        raise ValueError("V1C package exposes provisional-review state")
    if "Fragment A" not in html or "Fragment B" not in html or "Candidate gap only; NOT a suggested connection" not in html:
        raise ValueError("V1C package is missing the explicit marker legend")
    if "position:fixed" not in html or "modal-marker-toggle" not in html or "preserveAspectRatio" not in html:
        raise ValueError("V1C package is missing sticky controls or aligned modal markers")
    if "fetch(" in html or "XMLHttpRequest" in html or "<script src=" in html or "<link href=" in html or "http://" in html or "https://" in html:
        # The SVG namespace is created in JavaScript, but there must be no
        # network URL or external resource in the static package.
        if "http://www.w3.org/2000/svg" in html:
            network_free = html.replace("http://www.w3.org/2000/svg", "")
        else:
            network_free = html
        if "http://" in network_free or "https://" in network_free or "fetch(" in network_free or "XMLHttpRequest" in network_free or "<script src=" in network_free or "<link href=" in network_free:
            raise ValueError("V1C package contains an external/network dependency")
    for suffix in (".dwg", ".pdf", ".dxf"):
        if any(path.is_file() for path in package_dir.rglob(f"*{suffix}")):
            raise ValueError(f"V1C package includes a full source document: {suffix}")
    local_count = context_count = 0
    for item in manifest["items"]:
        for key in ("local_image", "context_image"):
            path = package_dir / Path(*item[key].split("/"))
            if not path.is_file():
                raise FileNotFoundError(path)
            if key == "local_image":
                local_count += 1
            else:
                context_count += 1
    return {"candidate_count": 24, "clean_local_count": local_count, "clean_context_count": context_count}


def build_human_review_package_v1c(
    repo_root: Path,
    *,
    output_dir: Path | None = None,
    zip_path: Path | None = None,
    replace: bool = False,
) -> ExpertPackageBuild:
    """Build the V1C package from the frozen E1/Local-D inputs."""

    repo_root = Path(repo_root).resolve()
    e1, candidates, paths = _ensure_frozen_inputs(repo_root)
    package_dir = Path(output_dir or (repo_root / "local-artifacts" / "draftsman" / V1C_PACKAGE_NAME)).resolve()
    final_zip = Path(zip_path or (repo_root / "local-artifacts" / "draftsman" / f"{V1C_PACKAGE_NAME}.zip")).resolve()
    if package_dir.exists():
        if not replace:
            raise FileExistsError(f"package directory exists; pass replace=True: {package_dir}")
        _safe_replace_v1c_directory(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = _package_manifest(e1, candidates, package_dir, paths)
    manifest["schema_version"] = V1C_SCHEMA_VERSION
    manifest["package_id"] = V1C_PACKAGE_NAME
    manifest["reviewer_session_type"] = "CORRECTED_HUMAN_REVIEW"
    manifest["ui_variant"] = "V1C_COMPACT_CORRECTED_REVIEW"
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_dir / "review.html").write_text(render_v1c_html(manifest), encoding="utf-8")
    (package_dir / "README.txt").write_text(_v1c_readme(), encoding="utf-8")
    # Reuse the asset/content validator for image existence and source
    # exclusion, then apply the V1C-specific static/UI checks above.
    validate_built_package(package_dir)
    validate = validate_v1c_package(package_dir)
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
    "V1C_PACKAGE_NAME",
    "V1C_SCHEMA_VERSION",
    "build_human_review_package_v1c",
    "render_v1c_html",
    "validate_v1c_package",
]
