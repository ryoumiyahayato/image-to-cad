"""Static browser UI for the reusable local human-review session."""

from __future__ import annotations


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Draftsman · 本地人工审核</title>
  <style>
    :root {
      color-scheme: dark;
      --ink: #eef3f7;
      --muted: #9aa8b8;
      --faint: #6e7e90;
      --bg: #0b1118;
      --panel: #121b25;
      --panel-strong: #182432;
      --panel-soft: #0f1720;
      --line: rgba(176, 199, 218, 0.16);
      --line-strong: rgba(176, 199, 218, 0.27);
      --blue: #77b9ff;
      --blue-deep: #2b78c8;
      --green: #6fd3b2;
      --amber: #f1b96c;
      --rose: #ef8d98;
      --violet: #b9a2ff;
      --shadow: 0 24px 60px rgba(0, 0, 0, 0.24);
      font-family: "Segoe UI", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif;
    }

    * { box-sizing: border-box; }
    html { min-width: 320px; background: var(--bg); }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 0%, rgba(49, 107, 160, 0.2), transparent 34rem),
        radial-gradient(circle at 100% 24%, rgba(110, 74, 136, 0.12), transparent 32rem),
        var(--bg);
    }
    body.modal-open { overflow: hidden; }
    button, textarea { font: inherit; }
    button { color: inherit; }
    button:focus-visible, textarea:focus-visible, img:focus-visible {
      outline: 2px solid var(--blue);
      outline-offset: 3px;
    }

    .app-shell { width: min(1680px, calc(100% - 40px)); margin: 0 auto; padding: 26px 0 44px; }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 24px;
      padding-bottom: 22px;
      border-bottom: 1px solid var(--line);
    }
    .brand-lockup { display: flex; align-items: flex-start; gap: 14px; }
    .brand-mark {
      display: grid;
      width: 42px;
      height: 42px;
      place-items: center;
      border: 1px solid rgba(119, 185, 255, 0.65);
      border-radius: 13px;
      color: var(--blue);
      background: linear-gradient(145deg, rgba(119, 185, 255, 0.2), rgba(119, 185, 255, 0.02));
      box-shadow: 0 0 0 5px rgba(119, 185, 255, 0.04);
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.08em;
    }
    .eyebrow { margin: 0 0 5px; color: var(--blue); font-size: 11px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(22px, 2.8vw, 34px); line-height: 1.08; letter-spacing: -0.04em; }
    .subtitle { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
    .progress-panel { min-width: 310px; text-align: right; }
    .progress-index { color: var(--ink); font-size: 22px; font-weight: 700; letter-spacing: -0.04em; }
    .progress-label { color: var(--muted); font-size: 12px; }
    .progress-track { height: 5px; margin-top: 12px; overflow: hidden; border-radius: 99px; background: rgba(255,255,255,0.08); }
    .progress-fill { width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--blue), var(--green)); transition: width 180ms ease; }

    .guidance {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
      gap: 16px;
      margin: 22px 0 18px;
    }
    .guidance-card {
      padding: 17px 19px;
      border: 1px solid var(--line);
      border-radius: 17px;
      background: rgba(18, 27, 37, 0.72);
      box-shadow: var(--shadow);
    }
    .guidance-card.primary { border-color: rgba(119, 185, 255, 0.3); background: linear-gradient(135deg, rgba(40, 84, 126, 0.34), rgba(18, 27, 37, 0.78)); }
    .guidance-kicker { margin: 0 0 8px; color: var(--faint); font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
    .guidance-quote { margin: 0; color: #ffffff; font-size: clamp(17px, 2vw, 23px); font-weight: 700; line-height: 1.35; letter-spacing: -0.025em; }
    .guidance-copy { margin: 9px 0 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
    .guidance-copy strong { color: var(--ink); font-weight: 600; }
    details summary { cursor: pointer; color: var(--blue); font-size: 13px; font-weight: 700; }
    details[open] summary { margin-bottom: 10px; }
    .guidance-list { display: grid; gap: 8px; margin: 0; padding-left: 18px; color: var(--muted); font-size: 12px; line-height: 1.55; }
    .guidance-list strong { color: var(--ink); }

    .review-meta { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 0 0 12px; }
    .candidate-id { min-width: 0; overflow: hidden; color: var(--ink); font-family: Consolas, "Courier New", monospace; font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
    .candidate-status { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; color: var(--muted); font-size: 12px; }
    .status-chip { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,0.04); }
    .status-chip.saved { color: var(--green); border-color: rgba(111, 211, 178, 0.35); }
    .status-chip.pending { color: var(--amber); border-color: rgba(241, 185, 108, 0.32); }
    .status-chip.error { color: var(--rose); border-color: rgba(239, 141, 152, 0.4); }

    .viewer-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .viewer-panel { min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: var(--panel); box-shadow: var(--shadow); }
    .viewer-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 13px 16px; border-bottom: 1px solid var(--line); }
    .viewer-heading h2 { margin: 0; font-size: 12px; letter-spacing: 0.13em; text-transform: uppercase; }
    .viewer-heading span { color: var(--faint); font-size: 11px; }
    .image-frame { display: grid; min-height: min(57vh, 690px); place-items: center; padding: 18px; background: #080d13; }
    .review-image { display: block; width: 100%; height: min(54vh, 650px); object-fit: contain; cursor: zoom-in; image-rendering: auto; }
    .image-fallback { display: none; max-width: 340px; padding: 20px; color: var(--rose); text-align: center; font-size: 13px; line-height: 1.6; }
    .image-fallback.visible { display: block; }
    .viewer-caption { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 16px 13px; color: var(--faint); font-size: 11px; }
    .zoom-hint { color: var(--blue); }
    body.view-local .viewer-grid { grid-template-columns: minmax(0, 1fr); }
    body.view-local .viewer-panel.context-panel, body.view-context .viewer-panel.local-panel { display: none; }
    body.view-context .viewer-grid { grid-template-columns: minmax(0, 1fr); }

    .review-controls { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.72fr); gap: 16px; margin-top: 16px; }
    .decision-panel, .note-panel { padding: 17px; border: 1px solid var(--line); border-radius: 18px; background: rgba(18, 27, 37, 0.86); box-shadow: var(--shadow); }
    .section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 13px; }
    .section-heading h2 { margin: 0; font-size: 14px; letter-spacing: -0.01em; }
    .section-heading span { color: var(--faint); font-size: 11px; }
    .label-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
    .label-button {
      min-height: 78px;
      padding: 11px 10px;
      border: 1px solid var(--line-strong);
      border-radius: 13px;
      color: var(--ink);
      background: var(--panel-soft);
      cursor: pointer;
      text-align: left;
      transition: border-color 130ms ease, background 130ms ease, transform 130ms ease;
    }
    .label-button:hover { transform: translateY(-1px); border-color: var(--blue); background: var(--panel-strong); }
    .label-button.selected { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(119, 185, 255, 0.16); background: rgba(43, 120, 200, 0.22); }
    .label-button:disabled { cursor: wait; opacity: 0.62; }
    .label-key { display: inline-grid; width: 22px; height: 22px; place-items: center; margin-bottom: 8px; border-radius: 7px; color: #091017; background: var(--blue); font-size: 12px; font-weight: 800; }
    .label-button.annotation .label-key { background: var(--amber); }
    .label-button.ambiguous .label-key { background: var(--violet); }
    .label-button.invalid .label-key { background: var(--rose); }
    .label-title { display: block; font-size: 13px; font-weight: 700; line-height: 1.25; }
    .label-token { display: block; margin-top: 5px; color: var(--faint); font-family: Consolas, "Courier New", monospace; font-size: 9px; line-height: 1.25; overflow-wrap: anywhere; }
    .label-counts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 13px; color: var(--muted); font-size: 11px; }
    .label-count { padding: 5px 8px; border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,0.025); }
    .label-count strong { margin-left: 3px; color: var(--ink); font-weight: 800; }
    .note-panel textarea { display: block; width: 100%; min-height: 124px; resize: vertical; padding: 12px; border: 1px solid var(--line-strong); border-radius: 12px; color: var(--ink); background: #0b121a; font-size: 13px; line-height: 1.55; }
    .note-panel textarea::placeholder { color: #68798a; }
    .note-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; }
    .save-note, .export-button, .nav-button, .view-button, .modal-button {
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      color: var(--ink);
      background: rgba(255,255,255,0.05);
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
    }
    .save-note { padding: 9px 13px; }
    .save-note:hover, .export-button:hover, .nav-button:hover, .view-button:hover, .modal-button:hover { border-color: var(--blue); background: rgba(119, 185, 255, 0.12); }
    .save-status { color: var(--muted); font-size: 11px; }
    .save-status.error { color: var(--rose); }
    .navigation { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 16px; }
    .nav-button { min-width: 128px; padding: 12px 16px; }
    .nav-button.primary { border-color: rgba(119, 185, 255, 0.4); color: var(--blue); }
    .nav-hint { color: var(--faint); font-size: 11px; text-align: center; }
    .utility-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
    .view-button, .export-button { padding: 8px 11px; }
    .view-button.active { border-color: var(--blue); color: var(--blue); background: rgba(119, 185, 255, 0.1); }
    .export-button { margin-left: auto; border-color: rgba(111, 211, 178, 0.38); color: var(--green); }
    .completion-banner { display: none; margin-top: 16px; padding: 15px 17px; border: 1px solid rgba(111, 211, 178, 0.42); border-radius: 14px; color: var(--green); background: rgba(39, 117, 95, 0.14); font-size: 15px; font-weight: 700; }
    .completion-banner.visible { display: block; }
    .footer-note { margin-top: 22px; color: var(--faint); font-size: 11px; line-height: 1.6; }

    .modal { position: fixed; inset: 0; z-index: 10; display: none; padding: 22px; background: rgba(4, 7, 11, 0.88); backdrop-filter: blur(7px); }
    .modal.open { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; }
    .modal-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .modal-title { min-width: 0; overflow: hidden; color: var(--ink); font-family: Consolas, "Courier New", monospace; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
    .modal-tools { display: flex; align-items: center; gap: 7px; }
    .modal-button { min-width: 34px; padding: 7px 10px; }
    .zoom-readout { min-width: 52px; color: var(--muted); font-size: 11px; text-align: center; }
    .zoom-viewport { min-height: 0; overflow: auto; border: 1px solid var(--line); border-radius: 16px; background: #05080b; cursor: grab; }
    .zoom-viewport.dragging { cursor: grabbing; }
    .zoom-canvas { display: grid; min-width: 100%; min-height: 100%; place-items: center; padding: 28px; }
    .zoom-image { display: block; max-width: none; max-height: none; transform-origin: center center; user-select: none; }

    @media (max-width: 980px) {
      .app-shell { width: min(100% - 24px, 760px); padding-top: 16px; }
      .topbar, .review-meta { align-items: flex-start; flex-direction: column; }
      .progress-panel { width: 100%; min-width: 0; text-align: left; }
      .guidance, .review-controls { grid-template-columns: minmax(0, 1fr); }
      .progress-track { margin-top: 8px; }
      .candidate-status { justify-content: flex-start; }
    }
    @media (max-width: 720px) {
      .app-shell { width: min(100% - 18px, 560px); padding-bottom: 24px; }
      .guidance { margin-top: 16px; }
      .viewer-grid { grid-template-columns: minmax(0, 1fr); }
      .image-frame { min-height: 36vh; padding: 10px; }
      .review-image { height: 34vh; }
      .label-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .navigation { flex-wrap: wrap; }
      .nav-hint { order: -1; width: 100%; }
      .export-button { margin-left: 0; }
      .modal { padding: 10px; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true">▱</div>
        <div>
          <p class="eyebrow">Draftsman / local review</p>
          <h1>工程线段人工审核</h1>
          <p class="subtitle">只依据图纸证据作判断；标签来自你的操作，不来自模型。</p>
        </div>
      </div>
      <div class="progress-panel" aria-live="polite">
        <div class="progress-index" id="progress-index">候选 — / —</div>
        <div class="progress-label" id="progress-label">正在加载审核会话…</div>
        <div class="progress-track" aria-hidden="true"><div class="progress-fill" id="progress-fill"></div></div>
      </div>
    </header>

    <section class="guidance" aria-label="审核指导">
      <div class="guidance-card primary">
        <p class="guidance-kicker">先看证据，再作选择</p>
        <p class="guidance-quote">看得出来才判；看不出来就选“无法可靠判断”，不要猜。</p>
        <p class="guidance-copy">你不需要知道电气或工程对象的专业名称。关键问题是：<strong>如果人工重新描这张图，这两段是否应该作为同一个实际工程对象的线连接起来？</strong></p>
      </div>
      <div class="guidance-card">
        <details open>
          <summary>四种选择的实际含义</summary>
          <ul class="guidance-list">
            <li><strong>结构连续：</strong>两段属于同一个实际工程对象或安装对象的连续线，例如设备轮廓、管线、电缆 / 线路路径、安装对象边界、构件边缘，或因扫描 / 检测造成的断线。</li>
            <li><strong>注释 / 文字 / 图框：</strong>说明性、标注性或版式内容，例如尺寸线、尺寸延长线、leader、文字笔画、表格线、标题栏、图框、revision / legend。</li>
            <li><strong>无法可靠判断：</strong>即使查看 LOCAL + CONTEXT 仍无法可靠判断；不要猜专业含义，必须依赖专业知识时也可以选此项。</li>
            <li><strong>候选无效：</strong>两条无关线被配对、crop 错位、转换丢失、图片损坏、上下文不足，或候选生成明显错误。</li>
          </ul>
        </details>
      </div>
    </section>

    <main id="review-shell" hidden>
      <div class="review-meta">
        <div class="candidate-id" id="candidate-id">—</div>
        <div class="candidate-status">
          <span class="status-chip" id="item-status">待审核</span>
          <span class="status-chip" id="current-label">尚未选择</span>
        </div>
      </div>

      <section class="viewer-grid" aria-label="候选图像">
        <article class="viewer-panel local-panel">
          <div class="viewer-heading"><h2>LOCAL VIEW / 局部</h2><span>碎片与间隙</span></div>
          <div class="image-frame">
            <img class="review-image" id="local-image" alt="候选局部图" tabindex="0">
            <div class="image-fallback" id="local-fallback">LOCAL 图像无法读取。请保留该候选并在备注中说明。</div>
          </div>
          <div class="viewer-caption"><span>显示原始审核 crop，不改变图像内容</span><span class="zoom-hint">点击放大</span></div>
        </article>
        <article class="viewer-panel context-panel">
          <div class="viewer-heading"><h2>CONTEXT VIEW / 上下文</h2><span>周边工程语境</span></div>
          <div class="image-frame">
            <img class="review-image" id="context-image" alt="候选上下文图" tabindex="0">
            <div class="image-fallback" id="context-fallback">CONTEXT 图像无法读取。请保留该候选并在备注中说明。</div>
          </div>
          <div class="viewer-caption"><span>用于判断结构、标注、文字或版式关系</span><span class="zoom-hint">点击放大</span></div>
        </article>
      </section>

      <section class="review-controls" aria-label="审核控制">
        <div class="decision-panel">
          <div class="section-heading"><h2>选择一个审核结果</h2><span>快捷键 1–4</span></div>
          <div class="label-grid">
            <button class="label-button structural" data-label="STRUCTURAL_CONTINUATION" type="button"><span class="label-key">1</span><span class="label-title">结构连续</span><span class="label-token">STRUCTURAL_CONTINUATION</span></button>
            <button class="label-button annotation" data-label="ANNOTATION_OR_GLYPH" type="button"><span class="label-key">2</span><span class="label-title">注释 / 文字 / 图框</span><span class="label-token">ANNOTATION_OR_GLYPH</span></button>
            <button class="label-button ambiguous" data-label="AMBIGUOUS" type="button"><span class="label-key">3</span><span class="label-title">无法可靠判断</span><span class="label-token">AMBIGUOUS</span></button>
            <button class="label-button invalid" data-label="INVALID_FOR_TASK" type="button"><span class="label-key">4</span><span class="label-title">候选无效</span><span class="label-token">INVALID_FOR_TASK</span></button>
          </div>
          <div class="label-counts" aria-live="polite">
            <span class="label-count">结构连续 <strong data-count-for="STRUCTURAL_CONTINUATION">0</strong></span>
            <span class="label-count">注释 / 文字 / 图框 <strong data-count-for="ANNOTATION_OR_GLYPH">0</strong></span>
            <span class="label-count">无法可靠判断 <strong data-count-for="AMBIGUOUS">0</strong></span>
            <span class="label-count">候选无效 <strong data-count-for="INVALID_FOR_TASK">0</strong></span>
          </div>
        </div>
        <div class="note-panel">
          <div class="section-heading"><h2>审核备注</h2><span>可选 · 自动保存</span></div>
          <textarea id="reviewer-note" maxlength="4000" placeholder="记录你希望在后续复核中看到的中性说明…"></textarea>
          <div class="note-footer"><span class="save-status" id="save-status">状态：已连接</span><button class="save-note" id="save-note" type="button">保存备注</button></div>
        </div>
      </section>

      <div class="navigation">
        <button class="nav-button" id="previous-button" type="button">← 上一个</button>
        <div class="nav-hint">← / → 切换 · 输入备注时快捷键不会触发</div>
        <button class="nav-button primary" id="next-button" type="button">下一个 →</button>
      </div>
      <div class="utility-row">
        <span class="progress-label">视图：</span>
        <button class="view-button active" data-view="side" type="button">并排</button>
        <button class="view-button" data-view="local" type="button">仅 LOCAL</button>
        <button class="view-button" data-view="context" type="button">仅 CONTEXT</button>
        <button class="export-button" id="export-button" type="button">导出审核结果</button>
      </div>

      <div class="completion-banner" id="completion-banner" role="status">24 / 24 已完成。请导出结果，并由操作者明确启动后续冻结任务。</div>
      <p class="footer-note">此页面仅在本机运行。关闭浏览器后，已保存的审核结果会从本地 review-state.json 恢复；不会上传图片，也不会调用模型或外部服务。</p>
    </main>
  </div>

  <div class="modal" id="image-modal" role="dialog" aria-modal="true" aria-label="放大图像">
    <div class="modal-header">
      <div class="modal-title" id="modal-title">—</div>
      <div class="modal-tools">
        <button class="modal-button" id="zoom-out" type="button" aria-label="缩小">−</button>
        <span class="zoom-readout" id="zoom-readout">100%</span>
        <button class="modal-button" id="zoom-in" type="button" aria-label="放大">＋</button>
        <button class="modal-button" id="zoom-reset" type="button">重置</button>
        <button class="modal-button" id="modal-close" type="button" aria-label="关闭">关闭</button>
      </div>
    </div>
    <div class="zoom-viewport" id="zoom-viewport">
      <div class="zoom-canvas"><img class="zoom-image" id="modal-image" alt="放大审核图像"></div>
    </div>
  </div>

  <script>
    (() => {
      "use strict";
      const LABEL_NAMES = {
        STRUCTURAL_CONTINUATION: "结构连续",
        ANNOTATION_OR_GLYPH: "注释 / 文字 / 图框",
        AMBIGUOUS: "无法可靠判断",
        INVALID_FOR_TASK: "候选无效"
      };
      const state = { session: null, index: 0, noteTimer: null, noteDirty: false, busy: false };
      const $ = (selector) => document.querySelector(selector);
      const $$ = (selector) => Array.from(document.querySelectorAll(selector));

      function currentItem() { return state.session && state.session.items[state.index]; }
      function setSaveStatus(text, kind = "") {
        const node = $("#save-status");
        node.textContent = text;
        node.className = `save-status ${kind}`.trim();
      }
      function setError(error) {
        console.error(error);
        setSaveStatus(`状态：${error.message || "请求失败"}`, "error");
      }
      async function request(path, options = {}) {
        const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        return payload;
      }
      function renderCounts() {
        const counts = state.session.counts;
        $("#progress-label").textContent = `已完成 ${counts.completed} · 待审核 ${counts.pending}`;
        $("#progress-fill").style.width = `${counts.total ? (counts.completed / counts.total) * 100 : 0}%`;
        $("#completion-banner").classList.toggle("visible", counts.pending === 0);
        $$(`[data-count-for]`).forEach((node) => { node.textContent = counts.by_label[node.dataset.countFor] ?? 0; });
      }
      function render() {
        const item = currentItem();
        if (!item) return;
        $("#review-shell").hidden = false;
        $("#progress-index").textContent = `候选 ${item.review_index} / ${state.session.items.length}`;
        $("#candidate-id").textContent = item.item_id;
        $("#item-status").textContent = item.review_status === "REVIEWED" ? "已保存" : "待审核";
        $("#item-status").className = `status-chip ${item.review_status === "REVIEWED" ? "saved" : "pending"}`;
        $("#current-label").textContent = item.human_label ? `已保存：${LABEL_NAMES[item.human_label]}` : "尚未选择";
        $("#current-label").className = `status-chip ${item.human_label ? "saved" : "pending"}`;
        $("#local-image").src = item.local_image_url;
        $("#context-image").src = item.context_image_url;
        $("#local-image").alt = `候选 ${item.review_index} LOCAL 局部图`;
        $("#context-image").alt = `候选 ${item.review_index} CONTEXT 上下文图`;
        $("#reviewer-note").value = item.reviewer_note || "";
        state.noteDirty = false;
        $$(".label-button").forEach((button) => {
          const selected = button.dataset.label === item.human_label;
          button.classList.toggle("selected", selected);
          button.setAttribute("aria-pressed", String(selected));
          button.disabled = state.busy;
        });
        $("#previous-button").disabled = state.index <= 0;
        $("#next-button").disabled = state.index >= state.session.items.length - 1;
        renderCounts();
      }
      function updateSession(payload) {
        if (payload.session) state.session = payload.session;
        if (payload.item && state.session) {
          const index = state.session.items.findIndex((item) => item.item_id === payload.item.item_id);
          if (index >= 0) state.session.items[index] = { ...state.session.items[index], ...payload.item };
        }
      }
      async function saveNote(silent = false) {
        if (!state.session || !state.noteDirty) return;
        const item = currentItem();
        const note = $("#reviewer-note").value;
        try {
          const payload = await request(`/api/items/${encodeURIComponent(item.item_id)}/note`, { method: "POST", body: JSON.stringify({ note }) });
          updateSession(payload);
          state.noteDirty = false;
          if (!silent) setSaveStatus("状态：备注已保存");
        } catch (error) {
          setError(error);
          throw error;
        }
      }
      function pendingAfter(index) {
        for (let offset = 1; offset <= state.session.items.length; offset += 1) {
          const candidateIndex = (index + offset) % state.session.items.length;
          if (state.session.items[candidateIndex].review_status === "PENDING") return candidateIndex;
        }
        return -1;
      }
      async function chooseLabel(label) {
        if (state.busy || !state.session) return;
        state.busy = true;
        $$(".label-button").forEach((button) => { button.disabled = true; });
        try {
          await saveNote(true);
          const item = currentItem();
          const payload = await request(`/api/items/${encodeURIComponent(item.item_id)}/label`, { method: "POST", body: JSON.stringify({ label }) });
          updateSession(payload);
          state.busy = false;
          render();
          setSaveStatus(`状态：已保存「${LABEL_NAMES[label]}」`);
          await new Promise((resolve) => setTimeout(resolve, 240));
          const next = pendingAfter(state.index);
          if (next >= 0) { state.index = next; render(); }
        } catch (error) {
          state.busy = false;
          render();
          setError(error);
        }
      }
      async function move(delta) {
        if (!state.session || state.busy) return;
        try { await saveNote(true); } catch (_) { return; }
        const next = Math.max(0, Math.min(state.session.items.length - 1, state.index + delta));
        if (next !== state.index) { state.index = next; render(); }
      }
      function openModal(src, title) {
        $("#modal-image").src = src;
        $("#modal-title").textContent = title;
        modalScale = 1;
        updateModalScale();
        $("#image-modal").classList.add("open");
        document.body.classList.add("modal-open");
        $("#modal-close").focus();
      }
      function closeModal() { $("#image-modal").classList.remove("open"); document.body.classList.remove("modal-open"); }
      let modalScale = 1;
      function updateModalScale() {
        $("#modal-image").style.transform = `scale(${modalScale})`;
        $("#zoom-readout").textContent = `${Math.round(modalScale * 100)}%`;
      }
      function adjustModalScale(amount) { modalScale = Math.max(0.5, Math.min(4, modalScale + amount)); updateModalScale(); }
      function setView(view) {
        document.body.classList.remove("view-local", "view-context");
        if (view !== "side") document.body.classList.add(`view-${view}`);
        $$(".view-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
      }
      async function exportReview() {
        try {
          const payload = await request("/api/export", { method: "POST", body: "{}" });
          const blob = new Blob([JSON.stringify(payload.export, null, 2)], { type: "application/json;charset=utf-8" });
          const link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = "review-export.json";
          link.click();
          URL.revokeObjectURL(link.href);
          setSaveStatus(`状态：审核结果已导出（${payload.export.counts.completed}/${payload.export.counts.total}）`);
        } catch (error) { setError(error); }
      }
      function isTypingTarget(target) { return target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT" || target.isContentEditable); }

      $("#local-image").addEventListener("click", () => openModal($("#local-image").src, `${currentItem().item_id} · LOCAL`));
      $("#context-image").addEventListener("click", () => openModal($("#context-image").src, `${currentItem().item_id} · CONTEXT`));
      $("#local-image").addEventListener("error", () => $("#local-fallback").classList.add("visible"));
      $("#context-image").addEventListener("error", () => $("#context-fallback").classList.add("visible"));
      $("#local-image").addEventListener("load", () => $("#local-fallback").classList.remove("visible"));
      $("#context-image").addEventListener("load", () => $("#context-fallback").classList.remove("visible"));
      $$(".label-button").forEach((button) => button.addEventListener("click", () => chooseLabel(button.dataset.label)));
      $("#previous-button").addEventListener("click", () => move(-1));
      $("#next-button").addEventListener("click", () => move(1));
      $("#save-note").addEventListener("click", () => saveNote(false).catch(() => {}));
      $("#reviewer-note").addEventListener("input", () => {
        state.noteDirty = true;
        setSaveStatus("状态：备注待保存");
        clearTimeout(state.noteTimer);
        state.noteTimer = setTimeout(() => saveNote(true).catch(() => {}), 650);
      });
      $("#export-button").addEventListener("click", exportReview);
      $$(".view-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
      $("#modal-close").addEventListener("click", closeModal);
      $("#zoom-in").addEventListener("click", () => adjustModalScale(0.25));
      $("#zoom-out").addEventListener("click", () => adjustModalScale(-0.25));
      $("#zoom-reset").addEventListener("click", () => { modalScale = 1; updateModalScale(); });
      $("#zoom-viewport").addEventListener("wheel", (event) => { event.preventDefault(); adjustModalScale(event.deltaY < 0 ? 0.1 : -0.1); }, { passive: false });
      let drag = null;
      $("#zoom-viewport").addEventListener("pointerdown", (event) => { drag = { x: event.clientX, y: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop }; event.currentTarget.classList.add("dragging"); event.currentTarget.setPointerCapture(event.pointerId); });
      $("#zoom-viewport").addEventListener("pointermove", (event) => { if (!drag) return; event.currentTarget.scrollLeft = drag.left - (event.clientX - drag.x); event.currentTarget.scrollTop = drag.top - (event.clientY - drag.y); });
      $("#zoom-viewport").addEventListener("pointerup", (event) => { drag = null; event.currentTarget.classList.remove("dragging"); });
      $("#zoom-viewport").addEventListener("pointercancel", (event) => { drag = null; event.currentTarget.classList.remove("dragging"); });
      document.addEventListener("keydown", (event) => {
        if ($("#image-modal").classList.contains("open")) { if (event.key === "Escape") closeModal(); return; }
        if (isTypingTarget(event.target)) {
          if (event.ctrlKey && event.key === "Enter" && event.target === $("#reviewer-note")) { event.preventDefault(); saveNote(false).catch(() => {}); }
          return;
        }
        if (["1", "2", "3", "4"].includes(event.key)) { event.preventDefault(); chooseLabel(["STRUCTURAL_CONTINUATION", "ANNOTATION_OR_GLYPH", "AMBIGUOUS", "INVALID_FOR_TASK"][Number(event.key) - 1]); }
        else if (event.key === "ArrowLeft") { event.preventDefault(); move(-1); }
        else if (event.key === "ArrowRight") { event.preventDefault(); move(1); }
      });

      request("/api/session").then((payload) => {
        state.session = payload.session;
        const firstPending = state.session.items.findIndex((item) => item.review_status === "PENDING");
        state.index = firstPending >= 0 ? firstPending : 0;
        render();
      }).catch((error) => {
        setError(error);
        $("#progress-label").textContent = "审核会话加载失败";
      });
    })();
  </script>
</body>
</html>
"""


def render_review_page() -> str:
    """Return the self-contained local review page."""

    return HTML_PAGE


__all__ = ["HTML_PAGE", "render_review_page"]
