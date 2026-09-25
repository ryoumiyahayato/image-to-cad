"""Build the two-stage human-review protocol package.

This module is a protocol-specific successor to the V1C portable UI.  It
reuses V1C's clean evidence and image-coordinate marker implementation while
making the raw human observation explicit:

``pair relationship -> line role -> derived legacy compatibility label``.

The old flat-four review sessions are never read or rewritten by this module.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from .expert_review_package import (
    ExpertPackageBuild,
    _ensure_frozen_inputs,
    _html_manifest_json,
    _package_manifest,
    _zip_package,
    validate_built_package,
)
from .human_review_v1c_package import V1C_HTML_TEMPLATE


TWO_STAGE_SCHEMA_VERSION = 3
TWO_STAGE_PACKAGE_NAME = "human-review-two-stage-v1"
REVIEW_PROTOCOL = "TWO_STAGE_HUMAN_REVIEW_V1"
STAGE1_VALUES: tuple[str, ...] = (
    "SAME_STROKE",
    "WRONG_PAIRING",
    "INSUFFICIENT_EVIDENCE",
)
STAGE2_VALUES: tuple[str, ...] = (
    "OBJECT_GEOMETRY",
    "ANNOTATION_LAYOUT",
    "UNKNOWN_ROLE",
)
LEGACY_LABELS: tuple[str, ...] = (
    "STRUCTURAL_CONTINUATION",
    "ANNOTATION_OR_GLYPH",
    "AMBIGUOUS",
    "INVALID_FOR_TASK",
)


TWO_STAGE_GUIDANCE = r'''    <section class="compact-guidance" aria-label="两阶段审核规则">
      <strong>看得出来才判；看不出来不要猜。</strong>
      <span>第一步只判断：红蓝是不是同一条原始线的两个片段？</span>
      <span class="legend" aria-label="候选标记图例">
        <span class="legend-chip"><i class="legend-dot red"></i>红 = Fragment A</span>
        <span class="legend-chip"><i class="legend-dot blue"></i>蓝 = Fragment B</span>
        <span class="legend-chip"><i class="legend-dot yellow"></i>黄 = 当前候选 Gap；只表示正在判断这里，不表示应该连接</span>
      </span>
      <details class="help">
        <summary>查看详细说明</summary>
        <div class="help-content">
          <p><b>第一步：红色 Fragment A 和蓝色 Fragment B，是否合理地代表同一条原始线的两个片段？</b></p>
          <p>同一条线 → <b>SAME_STROKE</b>。两条不同线、平行线或错误配对 → <b>WRONG_PAIRING</b>。看不清、分辨率不足、上下文不足或有多种合理解释 → <b>INSUFFICIENT_EVIDENCE</b>。</p>
          <p>红蓝都落在真实线上，但只是两条平行线时，选择 <b>WRONG_PAIRING</b>；不要求其中一段必须是错误线。</p>
          <p><b>第二步只在 SAME_STROKE 后出现：</b>实际工程对象 / 安装对象 → <b>OBJECT_GEOMETRY</b>；尺寸线、尺寸延长线、引出线、文字、表格、标题栏、图框或 revision / legend / drawing-layout rule → <b>ANNOTATION_LAYOUT</b>；无法确定用途 → <b>UNKNOWN_ROLE</b>。</p>
          <p>正确配对的尺寸、表格或其他注释线仍然是 SAME_STROKE + ANNOTATION_LAYOUT，不是 WRONG_PAIRING。你不需要说出具体专业对象名称。</p>
          <p>黄色只表示正在判断的候选 gap / region，不表示建议填充或连接。</p>
        </div>
      </details>
    </section>
'''


TWO_STAGE_REVIEW_BAR = r'''  <section class="review-bar" aria-label="两阶段分类控制">
    <div class="review-bar-inner">
      <div class="review-bar-heading"><strong id="stage-heading">第一步：判断红蓝候选配对</strong><span id="stage-shortcut">键盘：1 / 2 / 3　← / → 浏览</span></div>
      <div id="stage1-grid" class="label-grid protocol-grid">
        <button class="label-button" type="button" data-stage1="SAME_STROKE"><span class="shortcut">1</span><span class="label-title">同一条线的两个片段</span><span class="label-code">SAME_STROKE</span></button>
        <button class="label-button" type="button" data-stage1="WRONG_PAIRING"><span class="shortcut">2</span><span class="label-title">候选配对错误</span><span class="label-code">WRONG_PAIRING</span></button>
        <button class="label-button" type="button" data-stage1="INSUFFICIENT_EVIDENCE"><span class="shortcut">3</span><span class="label-title">证据不足 / 看不清</span><span class="label-code">INSUFFICIENT_EVIDENCE</span></button>
      </div>
      <div id="stage2-grid" class="label-grid protocol-grid" hidden>
        <button class="label-button" type="button" data-stage2="OBJECT_GEOMETRY"><span class="shortcut">1</span><span class="label-title">实际工程对象 / 安装对象</span><span class="label-code">OBJECT_GEOMETRY</span></button>
        <button class="label-button" type="button" data-stage2="ANNOTATION_LAYOUT"><span class="shortcut">2</span><span class="label-title">注释 / 尺寸 / 文字 / 版式</span><span class="label-code">ANNOTATION_LAYOUT</span></button>
        <button class="label-button" type="button" data-stage2="UNKNOWN_ROLE"><span class="shortcut">3</span><span class="label-title">无法确定用途</span><span class="label-code">UNKNOWN_ROLE</span></button>
      </div>
      <div class="status-line" id="status-line" aria-live="polite"></div>
    </div>
  </section>
'''


TWO_STAGE_SCRIPT = r'''  <script>
  "use strict";
  const PACKAGE = __PACKAGE_MANIFEST__;
  const REVIEW_PROTOCOL = "TWO_STAGE_HUMAN_REVIEW_V1";
  const STORAGE_KEY = "draftsman-human-review-two-stage-v1:" + PACKAGE.source_manifest_identity.manifest_sha256;
  const HISTORY_PREFIX = STORAGE_KEY + ":history:";
  const STAGE1_VALUES = Object.freeze(["SAME_STROKE", "WRONG_PAIRING", "INSUFFICIENT_EVIDENCE"]);
  const STAGE2_VALUES = Object.freeze(["OBJECT_GEOMETRY", "ANNOTATION_LAYOUT", "UNKNOWN_ROLE"]);
  const state = { session:null, index:0, markerToggle:false, busy:false, noteTimer:null, modal:null, modalScale:1, drag:null };

  function now() { return new Date().toISOString(); }
  function newSession() {
    const timestamp = now();
    return {
      schema_version:3, review_protocol:REVIEW_PROTOCOL,
      session_id:"two-stage-review-" + timestamp.replace(/[-:.TZ]/g, "") + "-" + Math.random().toString(36).slice(2, 8),
      source_manifest_identity:PACKAGE.source_manifest_identity,
      review_started_at:timestamp, review_updated_at:timestamp,
      review_order:PACKAGE.review_order.slice(),
      items:PACKAGE.items.map(function(item) { return {
        review_index:item.review_index, candidate_id:item.candidate_id,
        stage1_pair_relation:null, stage2_line_role:null, derived_legacy_label:null,
        reviewer_note:null, review_status:"PENDING", updated_at:timestamp, history:[]
      }; })
    };
  }
  function sameArray(a,b) { return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(function(value,i) { return value === b[i]; }); }
  function deriveLegacy(stage1, stage2) {
    if (stage1 === "WRONG_PAIRING") return "INVALID_FOR_TASK";
    if (stage1 === "INSUFFICIENT_EVIDENCE") return "AMBIGUOUS";
    if (stage1 !== "SAME_STROKE") return null;
    if (stage2 === "OBJECT_GEOMETRY") return "STRUCTURAL_CONTINUATION";
    if (stage2 === "ANNOTATION_LAYOUT") return "ANNOTATION_OR_GLYPH";
    if (stage2 === "UNKNOWN_ROLE") return "AMBIGUOUS";
    return null;
  }
  function isComplete(item) { return Boolean(item.stage1_pair_relation) && (item.stage1_pair_relation !== "SAME_STROKE" || Boolean(item.stage2_line_role)); }
  function normalizeSession(raw) {
    if (!raw || raw.schema_version !== 3 || raw.review_protocol !== REVIEW_PROTOCOL) return null;
    if (JSON.stringify(raw.source_manifest_identity) !== JSON.stringify(PACKAGE.source_manifest_identity)) return null;
    if (!sameArray(raw.review_order, PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length !== PACKAGE.items.length) return null;
    const allowedIds = new Set(PACKAGE.review_order); const seen = new Set(); const timestamp = now();
    const items = raw.items.map(function(item) {
      if (!item || !allowedIds.has(item.candidate_id) || seen.has(item.candidate_id)) throw new Error("candidate identity mismatch");
      seen.add(item.candidate_id);
      const stage1 = item.stage1_pair_relation || null; const stage2 = item.stage2_line_role || null;
      if (stage1 !== null && !STAGE1_VALUES.includes(stage1)) throw new Error("Stage 1 vocabulary mismatch");
      if (stage2 !== null && !STAGE2_VALUES.includes(stage2)) throw new Error("Stage 2 vocabulary mismatch");
      if (stage1 !== "SAME_STROKE" && stage2 !== null) throw new Error("Stage 2 is only valid after SAME_STROKE");
      return {
        review_index:item.review_index, candidate_id:item.candidate_id,
        stage1_pair_relation:stage1, stage2_line_role:stage2,
        derived_legacy_label:deriveLegacy(stage1,stage2), reviewer_note:item.reviewer_note || null,
        review_status:isComplete({stage1_pair_relation:stage1,stage2_line_role:stage2}) ? "REVIEWED" : "PENDING",
        updated_at:item.updated_at || timestamp, history:Array.isArray(item.history) ? item.history : []
      };
    });
    if (seen.size !== PACKAGE.review_order.length) return null;
    return Object.assign({}, raw, {items:items, review_updated_at:raw.review_updated_at || timestamp});
  }
  function saveSession() { if (!state.session) return; state.session.review_updated_at=now(); localStorage.setItem(STORAGE_KEY, JSON.stringify(state.session)); }
  function loadSession() {
    let loaded=null; try { loaded=normalizeSession(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")); } catch(error) { loaded=null; }
    state.session=loaded || newSession(); const firstPending=state.session.items.findIndex(function(item) { return !isComplete(item); }); state.index=firstPending >= 0 ? firstPending : 0; saveSession();
  }
  function currentItem() { return state.session.items[state.index]; }
  function packageItem(candidateId) { return PACKAGE.items.find(function(item) { return item.candidate_id === candidateId; }); }
  function counts() {
    const result={completed:0,pending:0,SAME_STROKE:0,WRONG_PAIRING:0,INSUFFICIENT_EVIDENCE:0,OBJECT_GEOMETRY:0,ANNOTATION_LAYOUT:0,UNKNOWN_ROLE:0};
    state.session.items.forEach(function(item) {
      if (isComplete(item)) result.completed += 1; else result.pending += 1;
      if (item.stage1_pair_relation) result[item.stage1_pair_relation] += 1;
      if (item.stage1_pair_relation === "SAME_STROKE" && item.stage2_line_role) result[item.stage2_line_role] += 1;
    }); return result;
  }
  function setStatus(message) { document.getElementById("status-line").textContent=message || ""; }
  function renderProgress() {
    const tally=counts();
    document.getElementById("progress").innerHTML="<strong>候选 " + (state.index+1) + " / " + PACKAGE.candidate_count + "</strong>已完成 " + tally.completed + " / " + PACKAGE.candidate_count + " · 待审核 " + tally.pending + "<br>第一步：同一线 " + tally.SAME_STROKE + " · 错配 " + tally.WRONG_PAIRING + " · 证据不足 " + tally.INSUFFICIENT_EVIDENCE + "<br>第二步：对象 " + tally.OBJECT_GEOMETRY + " · 注释 " + tally.ANNOTATION_LAYOUT + " · 用途未知 " + tally.UNKNOWN_ROLE;
    document.getElementById("candidate-heading").textContent="候选 " + (state.index+1) + " · " + currentItem().candidate_id;
  }
  function point(value) { return {x:Number(value[0]),y:Number(value[1])}; }
  function markerSvg(marker) {
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"); svg.setAttribute("viewBox","0 0 " + marker.width + " " + marker.height); svg.setAttribute("preserveAspectRatio","none"); svg.setAttribute("class","marker-overlay"); svg.setAttribute("role","img"); svg.setAttribute("aria-label","候选位置标记：Fragment A、Fragment B、Candidate gap");
    function line(a,b,className) { const element=document.createElementNS("http://www.w3.org/2000/svg","line"); element.setAttribute("x1",a.x); element.setAttribute("y1",a.y); element.setAttribute("x2",b.x); element.setAttribute("y2",b.y); element.setAttribute("class",className); svg.appendChild(element); }
    function circle(p,className) { const element=document.createElementNS("http://www.w3.org/2000/svg","circle"); element.setAttribute("cx",p.x); element.setAttribute("cy",p.y); element.setAttribute("r","5"); element.setAttribute("class",className); svg.appendChild(element); }
    const a0=point(marker.fragment_a.start),a1=point(marker.fragment_a.end),b0=point(marker.fragment_b.start),b1=point(marker.fragment_b.end),gapA=point(marker.gap_endpoint_a),gapB=point(marker.gap_endpoint_b);
    line(a0,a1,"fragment-a"); line(b0,b1,"fragment-b"); line(gapA,gapB,"candidate-gap"); circle(gapA,"gap-a"); circle(gapB,"gap-b"); return svg;
  }
  function imageStage(item,kind) {
    const stage=document.createElement("div"); stage.className="image-stage"; stage.title="点击放大"; const frame=document.createElement("div"); frame.className="image-frame"; const image=document.createElement("img"); image.alt=kind === "local" ? "LOCAL clean evidence" : "CONTEXT clean evidence"; image.src=kind === "local" ? item.local_image : item.context_image; frame.appendChild(image); if (state.markerToggle) frame.appendChild(markerSvg(item.marker[kind])); stage.appendChild(frame); stage.addEventListener("click",function() { openModal(item,kind,state.markerToggle); }); return stage;
  }
  function renderEvidence() { const item=packageItem(currentItem().candidate_id); document.getElementById("local-stage").replaceChildren(imageStage(item,"local")); document.getElementById("context-stage").replaceChildren(imageStage(item,"context")); document.getElementById("marker-toggle").checked=state.markerToggle; }
  function renderProtocolControls() {
    const item=currentItem(); const same=item.stage1_pair_relation === "SAME_STROKE"; const stage2Visible=same;
    document.getElementById("stage1-grid").hidden=false; document.getElementById("stage2-grid").hidden=!stage2Visible;
    document.getElementById("stage-heading").textContent=stage2Visible ? "第二步：判断这条线承担的角色" : "第一步：判断红蓝候选配对";
    document.getElementById("stage-shortcut").textContent=stage2Visible ? "键盘：1 / 2 / 3　← / → 浏览" : "键盘：1 / 2 / 3　← / → 浏览";
    document.querySelectorAll("[data-stage1]").forEach(function(button) { button.classList.toggle("active",button.dataset.stage1 === item.stage1_pair_relation); });
    document.querySelectorAll("[data-stage2]").forEach(function(button) { button.classList.toggle("active",button.dataset.stage2 === item.stage2_line_role); });
    if (same && !item.stage2_line_role) setStatus("第一步已保存。请完成第二步；不确定用途时选择 UNKNOWN_ROLE。");
  }
  function renderNote() { const note=currentItem().reviewer_note || ""; document.getElementById("candidate-note").value=note; document.getElementById("note-status").textContent=note ? "备注已保存到当前本地审核会话。" : ""; }
  function render() { renderProgress(); renderEvidence(); renderProtocolControls(); renderNote(); }
  function advanceToNextPending() { const total=state.session.items.length; for (let offset=1; offset<=total; offset += 1) { const candidateIndex=(state.index+offset)%total; if (!isComplete(state.session.items[candidateIndex])) { state.index=candidateIndex; return; } } }
  function recordHistory(item,oldStage1,oldStage2) { item.history.push({timestamp:now(),old_stage1_pair_relation:oldStage1,new_stage1_pair_relation:item.stage1_pair_relation,old_stage2_line_role:oldStage2,new_stage2_line_role:item.stage2_line_role,derived_legacy_label:item.derived_legacy_label}); }
  function finishAndAdvance(message) { saveSession(); render(); setStatus(message); state.busy=true; window.setTimeout(function() { advanceToNextPending(); state.busy=false; render(); },180); }
  function setStage1(value) {
    if (!STAGE1_VALUES.includes(value) || state.busy) return; const item=currentItem(); const oldStage1=item.stage1_pair_relation; const oldStage2=item.stage2_line_role; item.stage1_pair_relation=value; item.stage2_line_role=value === "SAME_STROKE" ? (oldStage1 === "SAME_STROKE" ? oldStage2 : null) : null; item.derived_legacy_label=deriveLegacy(item.stage1_pair_relation,item.stage2_line_role); item.review_status=isComplete(item) ? "REVIEWED" : "PENDING"; item.updated_at=now(); if (oldStage1 !== item.stage1_pair_relation || oldStage2 !== item.stage2_line_role) recordHistory(item,oldStage1,oldStage2); saveSession(); render(); if (value === "SAME_STROKE") setStatus(item.stage2_line_role ? "SAME_STROKE 已保存。可修改第二步用途。" : "SAME_STROKE 已保存，请选择第二步用途。"); else finishAndAdvance("已保存 " + value + "；已自动推导兼容标签 " + item.derived_legacy_label + "。");
  }
  function setStage2(value) {
    if (!STAGE2_VALUES.includes(value) || state.busy || currentItem().stage1_pair_relation !== "SAME_STROKE") return; const item=currentItem(); const oldStage1=item.stage1_pair_relation; const oldStage2=item.stage2_line_role; item.stage2_line_role=value; item.derived_legacy_label=deriveLegacy(item.stage1_pair_relation,item.stage2_line_role); item.review_status="REVIEWED"; item.updated_at=now(); if (oldStage2 !== value) recordHistory(item,oldStage1,oldStage2); finishAndAdvance("已保存 " + value + "；已推导兼容标签 " + item.derived_legacy_label + "。");
  }
  function saveCandidateNote() { const value=document.getElementById("candidate-note").value.trim(); currentItem().reviewer_note=value || null; currentItem().updated_at=now(); saveSession(); document.getElementById("note-status").textContent=value ? "备注已保存到当前本地审核会话。" : "备注已清空。"; }
  function scheduleNoteSave() { window.clearTimeout(state.noteTimer); state.noteTimer=window.setTimeout(saveCandidateNote,350); }
  function navigate(delta) { if (delta > 0 && !isComplete(currentItem())) { setStatus("请先完成当前阶段，再前进。"); return; } state.index=Math.max(0,Math.min(state.session.items.length-1,state.index+delta)); render(); }
  function freshTwoStageReview() { const hasAnswers=state.session.items.some(function(item) { return item.stage1_pair_relation || item.stage2_line_role || item.reviewer_note; }); if (hasAnswers && !window.confirm("开始新的两阶段审核？当前本地会话会保留，不会删除。")) return; if (hasAnswers) localStorage.setItem(HISTORY_PREFIX + state.session.session_id,JSON.stringify(state.session)); state.session=newSession(); state.index=0; saveSession(); render(); setStatus("新的两阶段审核已开始：0 / " + PACKAGE.candidate_count + "。"); }
  function downloadJson(filename,value) { const blob=new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"}); const url=URL.createObjectURL(blob); const anchor=document.createElement("a"); anchor.href=url; anchor.download=filename; anchor.click(); window.setTimeout(function() { URL.revokeObjectURL(url); },1000); }
  function exportResult() { saveCandidateNote(); const exported=now(); const payload={schema_version:3,review_protocol:REVIEW_PROTOCOL,session_id:state.session.session_id,source_manifest_identity:PACKAGE.source_manifest_identity,review_order:PACKAGE.review_order.slice(),review_started_at:state.session.review_started_at,review_exported_at:exported,items:state.session.items.map(function(item) { return {review_index:item.review_index,candidate_id:item.candidate_id,stage1_pair_relation:item.stage1_pair_relation,stage2_line_role:item.stage2_line_role,derived_legacy_label:item.derived_legacy_label,reviewer_note:item.reviewer_note,review_status:isComplete(item) ? "REVIEWED" : "PENDING",updated_at:item.updated_at,history:item.history}; })}; downloadJson("human-review-two-stage-v1-" + state.session.session_id + ".json",payload); setStatus("两阶段审核结果已导出。"); }
  function validateImport(raw) { if (!raw || raw.schema_version !== 3 || raw.review_protocol !== REVIEW_PROTOCOL) throw new Error("不是当前两阶段审核格式；不会导入旧平面四标签结果。"); if (JSON.stringify(raw.source_manifest_identity) !== JSON.stringify(PACKAGE.source_manifest_identity)) throw new Error("审核结果与当前 24 个候选不匹配。"); if (!sameArray(raw.review_order,PACKAGE.review_order) || !Array.isArray(raw.items) || raw.items.length !== PACKAGE.candidate_count) throw new Error("审核顺序或候选数量不匹配。"); const session=newSession(); session.session_id=raw.session_id || session.session_id; session.review_started_at=raw.review_started_at || session.review_started_at; raw.items.forEach(function(item) { const target=session.items.find(function(candidate) { return candidate.candidate_id === item.candidate_id; }); if (!target) throw new Error("候选 ID 不匹配。"); if (item.stage1_pair_relation !== null && !STAGE1_VALUES.includes(item.stage1_pair_relation)) throw new Error("Stage 1 标签不允许。"); if (item.stage2_line_role !== null && !STAGE2_VALUES.includes(item.stage2_line_role)) throw new Error("Stage 2 标签不允许。"); if (item.stage1_pair_relation !== "SAME_STROKE" && item.stage2_line_role !== null) throw new Error("非 SAME_STROKE 项目的 Stage 2 必须为空。"); target.stage1_pair_relation=item.stage1_pair_relation || null; target.stage2_line_role=item.stage2_line_role || null; target.derived_legacy_label=deriveLegacy(target.stage1_pair_relation,target.stage2_line_role); target.reviewer_note=item.reviewer_note || null; target.review_status=isComplete(target) ? "REVIEWED" : "PENDING"; target.updated_at=item.updated_at || now(); target.history=Array.isArray(item.history) ? item.history : []; }); return session; }
  function importResult(event) { const file=event.target.files && event.target.files[0]; if (!file) return; const reader=new FileReader(); reader.onload=function() { try { const imported=validateImport(JSON.parse(reader.result)); if (state.session.items.some(function(item) { return !isComplete(item) && (item.stage1_pair_relation || item.reviewer_note); }) && !window.confirm("导入会替换当前两阶段会话；当前会话会先保留在本地历史。继续？")) return; localStorage.setItem(HISTORY_PREFIX + state.session.session_id,JSON.stringify(state.session)); state.session=imported; state.index=Math.max(0,state.session.items.findIndex(function(item) { return !isComplete(item); })); saveSession(); render(); setStatus("两阶段审核结果已导入。"); } catch(error) { window.alert(error.message || "导入失败。"); } event.target.value=""; }; reader.readAsText(file,"utf-8"); }
  function setModalScale(value) { state.modalScale=Math.max(.5,Math.min(4,Math.round(value*100)/100)); const content=document.getElementById("zoom-content"); content.style.transform="scale(" + state.modalScale + ")"; document.getElementById("modal-zoom-label").textContent=Math.round(state.modalScale*100) + "%"; }
  function renderModal() { if (!state.modal) return; const item=packageItem(state.modal.item.candidate_id); const content=document.getElementById("zoom-content"); content.replaceChildren(); const image=document.createElement("img"); image.alt=state.modal.kind === "local" ? "LOCAL enlarged evidence" : "CONTEXT enlarged evidence"; image.src=state.modal.kind === "local" ? item.local_image : item.context_image; content.appendChild(image); if (state.modal.marked) content.appendChild(markerSvg(item.marker[state.modal.kind])); document.getElementById("modal-marker-toggle").checked=state.modal.marked; document.getElementById("modal-title").textContent="候选 " + state.modal.item.review_index + " · " + item.candidate_id; document.getElementById("modal-view-kind").textContent=state.modal.kind === "local" ? "LOCAL · 局部证据" : "CONTEXT · 周边工程上下文"; setModalScale(state.modalScale); }
  function openModal(item,kind,marked) { state.modal={item:item,kind:kind,marked:Boolean(marked)}; state.modalScale=1; document.getElementById("image-modal").hidden=false; renderModal(); }
  function closeModal() { document.getElementById("image-modal").hidden=true; state.modal=null; state.drag=null; }
  function keyHandler(event) { const tag=event.target && event.target.tagName ? event.target.tagName.toLowerCase() : ""; if (tag === "input" || tag === "textarea" || event.target.isContentEditable) return; if (state.modal) { if (event.key === "Escape") { event.preventDefault(); closeModal(); } return; } if (event.key === "ArrowLeft") { event.preventDefault(); navigate(-1); return; } if (event.key === "ArrowRight") { event.preventDefault(); navigate(1); return; } const stage2Active=currentItem().stage1_pair_relation === "SAME_STROKE" && !currentItem().stage2_line_role; if (event.key === "1") stage2Active ? setStage2("OBJECT_GEOMETRY") : setStage1("SAME_STROKE"); else if (event.key === "2") stage2Active ? setStage2("ANNOTATION_LAYOUT") : setStage1("WRONG_PAIRING"); else if (event.key === "3") stage2Active ? setStage2("UNKNOWN_ROLE") : setStage1("INSUFFICIENT_EVIDENCE"); }
  document.getElementById("marker-toggle").addEventListener("change",function(event) { state.markerToggle=event.target.checked; renderEvidence(); });
  document.getElementById("fresh-button").addEventListener("click",freshTwoStageReview); document.getElementById("import-button").addEventListener("click",function() { document.getElementById("import-file").click(); }); document.getElementById("import-file").addEventListener("change",importResult); document.getElementById("export-button").addEventListener("click",exportResult);
  document.querySelectorAll("[data-stage1]").forEach(function(button) { button.addEventListener("click",function() { setStage1(button.dataset.stage1); }); }); document.querySelectorAll("[data-stage2]").forEach(function(button) { button.addEventListener("click",function() { setStage2(button.dataset.stage2); }); });
  document.getElementById("candidate-note").addEventListener("input",scheduleNoteSave); document.getElementById("modal-close").addEventListener("click",closeModal); document.getElementById("modal-marker-toggle").addEventListener("change",function(event) { if (state.modal) { state.modal.marked=event.target.checked; renderModal(); } }); document.getElementById("zoom-out").addEventListener("click",function() { setModalScale(state.modalScale-.25); }); document.getElementById("zoom-in").addEventListener("click",function() { setModalScale(state.modalScale+.25); }); document.getElementById("zoom-fit").addEventListener("click",function() { setModalScale(1); });
  const viewport=document.getElementById("zoom-viewport"); viewport.addEventListener("wheel",function(event) { if (!state.modal) return; event.preventDefault(); setModalScale(state.modalScale + (event.deltaY < 0 ? .15 : -.15)); },{passive:false}); viewport.addEventListener("pointerdown",function(event) { if (!state.modal || state.modalScale <= 1) return; state.drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop}; viewport.classList.add("dragging"); viewport.setPointerCapture(event.pointerId); }); viewport.addEventListener("pointermove",function(event) { if (!state.drag) return; viewport.scrollLeft=state.drag.left-(event.clientX-state.drag.x); viewport.scrollTop=state.drag.top-(event.clientY-state.drag.y); }); viewport.addEventListener("pointerup",function() { state.drag=null; viewport.classList.remove("dragging"); }); viewport.addEventListener("pointercancel",function() { state.drag=null; viewport.classList.remove("dragging"); }); document.addEventListener("keydown",keyHandler);
  loadSession(); render();
  </script>
'''


def render_two_stage_html(manifest: Mapping[str, Any]) -> str:
    """Apply protocol-specific markup/script to the preserved V1C shell."""

    html = V1C_HTML_TEMPLATE.replace("<title>人工作图审核</title>", "<title>两阶段人工作图审核</title>")
    html = html.replace("开始新的更正审核", "开始新的两阶段审核")
    html = html.replace(
        '    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }',
        '    .label-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }\n    .protocol-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }\n    .protocol-grid[hidden] { display:none; }',
    )
    guidance_start = html.index('    <section class="compact-guidance"')
    evidence_start = html.index('    <section class="evidence-panel"', guidance_start)
    html = html[:guidance_start] + TWO_STAGE_GUIDANCE + html[evidence_start:]
    bar_start = html.index('  <section class="review-bar"')
    modal_start = html.index('  <div id="image-modal"', bar_start)
    html = html[:bar_start] + TWO_STAGE_REVIEW_BAR + html[modal_start:]
    script_start = html.index('  <script>\n')
    script_end = html.index('  </script>', script_start) + len('  </script>\n')
    html = html[:script_start] + TWO_STAGE_SCRIPT + html[script_end:]
    payload = _html_manifest_json(manifest).replace("<", "\\u003c")
    return html.replace("__PACKAGE_MANIFEST__", payload)


def _two_stage_readme() -> str:
    return """两阶段人工作图审核包 V1

这是一个离线、预测盲的 24 项两阶段人工作图审核包。双击 review.html 即可打开，不需要 Draftsman、Git、Python 或网络。

第一步：判断红色 Fragment A 与蓝色 Fragment B 是否是同一条原始线的两个片段：SAME_STROKE、WRONG_PAIRING、INSUFFICIENT_EVIDENCE。
第二步：仅在 SAME_STROKE 后判断线的角色：OBJECT_GEOMETRY、ANNOTATION_LAYOUT、UNKNOWN_ROLE。

导出的 JSON 同时保存原始两阶段判断和单独的 derived_legacy_label 兼容字段。旧平面四标签结果不会自动导入。

EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
MODEL_EXPOSURE: NONE
LEGACY_FLAT_FOUR_REVIEWS: PRESERVED_AS_PROVISIONAL
FULL_SOURCE_DWG_PDF_INCLUDED: NO
"""


def _safe_replace_two_stage_directory(path: Path) -> None:
    path = path.resolve()
    if path.name != TWO_STAGE_PACKAGE_NAME or path.parent.name != "draftsman" or path.parent.parent.name != "local-artifacts":
        raise ValueError(f"refusing to replace unexpected two-stage package path: {path}")
    if path.exists():
        shutil.rmtree(path)


def validate_two_stage_package(package_dir: Path) -> dict[str, Any]:
    """Validate protocol, static/offline, and source-minimization invariants."""

    package_dir = Path(package_dir)
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    html = (package_dir / "review.html").read_text(encoding="utf-8")
    if manifest.get("package_id") != TWO_STAGE_PACKAGE_NAME or manifest.get("candidate_count") != 24:
        raise ValueError("two-stage package identity or candidate count is invalid")
    if manifest.get("schema_version") != TWO_STAGE_SCHEMA_VERSION or manifest.get("review_protocol") != REVIEW_PROTOCOL:
        raise ValueError("two-stage protocol identity is invalid")
    if manifest.get("stage1_values") != list(STAGE1_VALUES) or manifest.get("stage2_values") != list(STAGE2_VALUES):
        raise ValueError("two-stage vocabulary is invalid")
    if len(manifest.get("items", [])) != 24 or len(manifest.get("review_order", [])) != 24:
        raise ValueError("two-stage package must contain exactly 24 ordered items")
    for token in ("SAME_STROKE", "WRONG_PAIRING", "INSUFFICIENT_EVIDENCE", "OBJECT_GEOMETRY", "ANNOTATION_LAYOUT", "UNKNOWN_ROLE", "stage1_pair_relation", "stage2_line_role", "derived_legacy_label"):
        if token not in html:
            raise ValueError(f"two-stage package is missing {token}")
    if "data-label=" in html or "reviewer_id" in html or "reviewer_role" in html or "REVIEWER_A" in html:
        raise ValueError("two-stage package exposes legacy direct controls or old review identity")
    if "review-state.json" in html or "review-export.json" in html:
        raise ValueError("two-stage package exposes mutable legacy review files")
    if "Stage 2 is only valid after SAME_STROKE" not in html and "stage2_line_role !== null" not in html:
        raise ValueError("two-stage package does not guard Stage 2 pairing")
    external = html.replace("http://www.w3.org/2000/svg", "")
    if "fetch(" in external or "XMLHttpRequest" in external or "<script src=" in external or "<link href=" in external or "http://" in external or "https://" in external:
        raise ValueError("two-stage package contains an external/network dependency")
    for suffix in (".dwg", ".pdf", ".dxf"):
        if any(path.is_file() for path in package_dir.rglob(f"*{suffix}")):
            raise ValueError(f"two-stage package includes a full source document: {suffix}")
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


def build_human_review_two_stage_v1(
    repo_root: Path,
    *,
    output_dir: Path | None = None,
    zip_path: Path | None = None,
    replace: bool = False,
) -> ExpertPackageBuild:
    """Build the separate two-stage package from frozen E1/Local-D inputs."""

    repo_root = Path(repo_root).resolve()
    e1, candidates, paths = _ensure_frozen_inputs(repo_root)
    package_dir = Path(output_dir or (repo_root / "local-artifacts" / "draftsman" / TWO_STAGE_PACKAGE_NAME)).resolve()
    final_zip = Path(zip_path or (repo_root / "local-artifacts" / "draftsman" / f"{TWO_STAGE_PACKAGE_NAME}.zip")).resolve()
    if package_dir.exists():
        if not replace:
            raise FileExistsError(f"package directory exists; pass replace=True: {package_dir}")
        _safe_replace_two_stage_directory(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = _package_manifest(e1, candidates, package_dir, paths)
    manifest["schema_version"] = TWO_STAGE_SCHEMA_VERSION
    manifest["package_id"] = TWO_STAGE_PACKAGE_NAME
    manifest["reviewer_session_type"] = "TWO_STAGE_HUMAN_REVIEW"
    manifest["review_protocol"] = REVIEW_PROTOCOL
    manifest["stage1_values"] = list(STAGE1_VALUES)
    manifest["stage2_values"] = list(STAGE2_VALUES)
    manifest["legacy_labels"] = list(LEGACY_LABELS)
    manifest["legacy_mapping"] = {
        "SAME_STROKE+OBJECT_GEOMETRY": "STRUCTURAL_CONTINUATION",
        "SAME_STROKE+ANNOTATION_LAYOUT": "ANNOTATION_OR_GLYPH",
        "SAME_STROKE+UNKNOWN_ROLE": "AMBIGUOUS",
        "WRONG_PAIRING": "INVALID_FOR_TASK",
        "INSUFFICIENT_EVIDENCE": "AMBIGUOUS",
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_dir / "review.html").write_text(render_two_stage_html(manifest), encoding="utf-8")
    (package_dir / "README.txt").write_text(_two_stage_readme(), encoding="utf-8")
    validate_built_package(package_dir)
    validate = validate_two_stage_package(package_dir)
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
    "REVIEW_PROTOCOL",
    "STAGE1_VALUES",
    "STAGE2_VALUES",
    "TWO_STAGE_PACKAGE_NAME",
    "TWO_STAGE_SCHEMA_VERSION",
    "build_human_review_two_stage_v1",
    "render_two_stage_html",
    "validate_two_stage_package",
]
