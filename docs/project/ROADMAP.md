# Controlled roadmap

## 当前阶段路线（2026-11-20）

本路线遵守 [原生完整对象基准](NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)，各阶段须用真实输出及对应环境验证。

1. 清理与恢复：保存独有源码，删除已证明冗余分支/文件；本轮实际记录见 [执行账本](CLEANUP_EXECUTED_20261120.md)。
2. 入口整合与完整对象：在独立功能分支迁入可靠算法；新输入无旧缓存运行，文字/框/线/门等同一最终 DXF，按对象双向核查。
3. CAD 编辑：目标 CAD 普通打开、独立编辑、保存和重开；未知及待修仍计入补绘成本。
4. 桌面交付：真实 Windows 构建与干净机验证，长任务、取消、恢复与文件保护成立。
5. 工程师区域验收：同范围同质量修图时间不超过手画一半后，才扩全页及新来源。
6. Android：依赖和真机资源探针通过后选择本地或远程路线；不从 Linux 局部耗时推断手机能力。

## 历史路线快照（SUPERSEDED）

> 下文保留原阶段事实，不再授权当前工作。当前状态和任务见 [PROJECT_STATUS.md](PROJECT_STATUS.md) 与 [CURRENT_TASK.md](CURRENT_TASK.md)。

Only one major problem may be active at a time. Each phase requires an isolated commit and a recoverable checkpoint.

## P0 — Project governance and factual baseline

Status: **completed by the commit containing these documents**

Goal:

- establish long-lived status, UAT, decisions, issues, acceptance, operating protocol, task, roadmap, and checkpoint records;
- distinguish code facts, automated facts, human UAT facts, and hypotheses.

Prohibited:

- production Python changes;
- OCR, DXF geometry, GUI, thresholds, colors, line repair, or regression-baseline changes;
- large DXF/PDF/image/package additions.

Exit conditions:

- all ten governance documents exist;
- internal document links and basic formatting are checked;
- one documentation-only commit is created;
- work stops without beginning P1.

## P1 — Native `TEXT` geometry fitting

Status: **next; not started**

Goal: correct height, width factor, insertion/alignment points, baseline, rotation, and OCR-box/quad fitting while preserving native editability.

Prerequisites:

- P0 complete;
- current text-emission and source-outline contracts frozen;
- three representative real development pages identified.

Prohibited:

- OCR content or threshold changes;
- `text_emit_eligible`, `replacement_safe`, or source-outline contract changes;
- `TRACE_TEXT_SYMBOL` routing changes;
- structure, line repair, logo, signature, PDF export, or color-mode changes.

Exit conditions:

- eligible native `TEXT` count does not decline;
- no systematic oversize text, broad overlap, or table overflow;
- horizontal, 90°, and 270° samples pass;
- per-page geometry reports exist;
- edit-save-close-reopen remains valid;
- full real-page/DXF rerun and user LibreCAD review complete.

## P2 — Ordinary text versus `TRACE_TEXT_SYMBOL`

Status: **deferred until P1 human acceptance**

Goal: reduce ordinary print misrouting in vertical/rotated text, title blocks, dense small text, and signature-adjacent print.

Prohibited:

- setting text-symbol count to zero as a target;
- global OCR-threshold reduction;
- page, coordinate, filename, or text-content hard-coding;
- converting real engineering symbols into text.

Exit conditions:

- ordinary-text misrouting is reduced on every representative category;
- real symbols remain graphics;
- semantic ownership remains unique;
- no P1 geometry regression.

## P3 — Formal and diagnostic display modes

Status: **deferred until P1 and P2 are stable**

Goal: separate production appearance from explicit diagnostic coloring while sharing the same `FinalStructure`.

Prohibited:

- recognition, ownership, entity-type, count, or line-repair changes caused by display mode;
- splitting mixed-language text into individual character entities.

Exit conditions:

- formal mode is default;
- diagnostic mode is explicit;
- only BYLAYER color/visibility differs;
- original and repaired structure are distinguishable;
- entity inventory is identical between modes.

## P4 — Protected local structure repair

Status: **deferred until text placement and protection masks are stable**

Goal: improve frame/table/structure recall only inside validated structural ROI or corridors.

Prohibited:

- full-page close, bridging, endpoint-only connection, infinite extension, or unprotected Hough-gap behavior;
- repair paths crossing text, logos, signatures, or unrelated regions;
- hiding repaired lines among original lines.

Exit conditions:

- repaired lines are isolated in `REPAIRED_STRUCTURE`;
- precision, recall, F1, crossing, protected-object intersection, span, and per-page addition counts are reported;
- safety contracts remain strict even when recall is incomplete.

## P5 — OCR content accuracy

Status: **deferred until geometry and routing are stable**

Goal: improve Chinese, small text, title blocks, low-quality scans, rotation, mixed text, and engineering-number content.

Prohibited:

- combining OCR-content work with geometry or line-repair changes;
- lowering thresholds without independent audit;
- text or page whitelists.

Exit conditions:

- correct, incorrect, missed, low-confidence, and symbol-as-text outcomes are measured separately;
- no geometry, routing, or symbol regression.

## P6 — Full UAT and release candidate

Status: **deferred**

Goal: perform complete per-page and per-DXF automated and LibreCAD acceptance, package checks, and release-candidate review.

Exit conditions:

- every real page and every final DXF has an independent result;
- edit-save-close-reopen, default layers, text geometry, routing, structure, repair, and diagnostic mode pass;
- no old whole-page line failure returns;
- repository state, tag, installer, and portable package are verified;
- the user approves the product result.

No final-release claim is permitted before P6.
