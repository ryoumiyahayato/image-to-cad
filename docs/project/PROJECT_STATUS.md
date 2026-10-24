2026-10-24 源码同步：五个工作树的提交对象、差异和工作文件已保全并异地恢复核对。候选使用 e5b80f9 的 baseline-runtime，未采用活动 P21-A 入口。隔离保存 Goal01—22 可公开代码，详细真实资料留私有副本。PR #35 保持 Draft；最后检查与未同步文件见 [SOURCE_SYNC_RESULT](SOURCE_SYNC_RESULT_20261024.md)。本轮无新产品收益验收。


# Image to CAD project status

Updated: 2026-10-14. Version: 0.3.0-dev. Development preview; no new release or release tag.

## Product baseline

The synchronization candidate is the actual `instrumented-e03` working tree on `codex/source-support-lifecycle-instrumentation`, based on `20b2247fdfdf90fbe10e6daacffe5e339d19cb13`, including previously uncommitted product work. HEAD alone did not represent the product. The original remote main was `c566d5f59391b851b0bd9e9ad6d999359bfe8282`. Remote-only changes were README translations. The old main is retained at `backup/main-before-local-sync-20261014`.

Current production: normal loader → ProductionProcessingService → image recognition/source ownership/reconciliation → immutable FinalStructure → save/read → existing DXF export → saved-DXF preview. FinalStructure schema 4; trace cache format 11. Optional PDF evidence preserves ordinary raster/scanned input support.

## Verified stage results

| Stage | Current result and scope |
|---|---|
| Architecture | Refactor closed. Existing preservation and retirement records are retained under docs/refactor. |
| P1 | Reproduced duplicate-line and break defects closed for the inspected cases. |
| P2A/P2B | Specific Chinese layout, source-outline ownership, graphic, signature and logo fixes implemented. General native-CAD font/UAT limits remain. |
| P3B | Maintenance only. Existing formal 94/50 split and review records preserved. No training is authorized or started. |
| P4 | Same-track Hough/LSD duplicate observations consolidated; distinct boundaries retained. |
| P5 | Verified PDF/source text reading direction reaches native text. No blanket rotation inference. |
| P6 | USDA scanned-page no-output timeout fixed; per-record route parsing is reused. |
| P7 | Specific USDA foundation-note overlap/source-text ownership fixed. |
| P8 | Closed as EVIDENCE_ONLY. Physical same-source ink does not authorize whole-object merge when cap/node/edit obligations remain unresolved. |
| P9/P9-B | Formal native ARC chain and Tiny House p9 full normal-entry replacement verified; cache, save/reopen, export and preview retain ARC. |
| P9-C | Complex-page layered admission implemented. Complete page context remains available; resource-incomplete evidence fails closed. |
| P9-D | Round-cap presentation and verified integer-canvas mapping errors supported. Tasmanian p3 geometry can pass, but visibility/cap-sharing prevents safe real replacement. No independent-source real ARC success is claimed. |
| P10-A | IMPLEMENTED. USDA p4 has two whole isolated scan strokes restored as LINE, retaining adjacent structure and source coverage. Final normal 240-DPI/OCR run: 160.637 s; 755 LINE, 3815 LWPOLYLINE, 6 CIRCLE, 220 TEXT, 4 IMAGE. Only two former contours differ from the P7 actual DXF. |

P9 policy remains `pdf-simple-arc-evidence-v3-round-cap`. Unsupported clipping, arbitrary cubics and true native anisotropy retain their refusals. P9 is in maintenance; Tasmanian occlusion work is not continued.

P10-A's mechanism reviews rejected LSD white-edge locators against a complete isolated thin source component, fits all station centers without axis snapping, checks caps/foreign ink/protection, then uses existing ownership and reconciliation. It does not merge wall sides, cut mixed contours or alter accepted endpoints. Width is retained through existing CAD lineweight records. See D-012 and [P10-A report](../product-fix-p10a-20261014.md).

## Verification and limits

The P10-A completion record contains 35 directly related passing tests and two bounded fullpage runs. The first run exposed a missing lineweight record; only the final second run is the delivered result. New-process reopen/re-export and native LINE edits persist; DXF audits have zero errors/fixes. LibreCAD was not available, so these checks are not GUI acceptance.

P9-D retained 76 related passing checks and Tiny's saved real ARC. The engineering index distinguishes contract fixtures, real local studies and normal fullpage runs. Historical pass counts are not a new full-repository run.

USDA has no original design CAD truth. Its changes are supported by the scan and known object relationships. Only USDA establishes a scan-positive source; Quanzhou/Tiny provide boundary and ARC guards, not independent scan-positive generalization. No all-page quality or release acceptance is asserted.

Raw PDFs and `local-artifacts` are not distributed. Small tracked region fixtures support portable regression tests. The engineering index retains P1–P10-A records and the synchronization follow-up. Historical DXF inventory records and their Git recovery references remain nonempty and auditable. Font licensing and exact approved-asset checks remain in force.

Synchronization follow-up (2026-10-14): PDFium output pointers use the binding's declared FPDF_BOOL; RapidOCR remains in the source-direction-verified 3.9 range. D-011 schema/cache version assertions and current test doubles are aligned. The remaining Linux exit-134 fault is independently reproduced by PySide6 6.12.0 QPainterPath void calls losing None references. In the same Ubuntu/CPython 3.11.17 environment, Qt/Shiboken 6.11.2 keeps the references and exits normally. Requirements exclude the faulty 6.12 range; normal pytest process exit is still mandatory.

The historical compact snapshot remains unchanged. An archived 20b2247 replay exactly matches it. Current code with only detector-alias consolidation bypassed reproduces every historical LINE payload. The first admission difference is the existing source-bound alias step: six groups remove seven output records, and one group removes one gap-case record. Each has zero unique source-pixel loss, unchanged width and an already-existing keeper geometry. Sample-test geometry remains unchanged. A separate versioned current snapshot retains exact structure/cache/DXF checks plus explicit transition source claims; it passes locally, together with 12 related guards. Linux's 61 related ARC/native/transition checks pass with the compatible Qt pair. D-013 and docs/refactor/preservation-transition-p10a.md record the scope. A clean Linux checkout with Python 3.11.17 and Qt/Shiboken 6.11.2 completed the full suite: 743 passed, 8 skipped in 74.18 seconds, with process exit 0. Preservation, Ruff, four-file mypy and compileall also pass locally. Ruff now explicitly retains the existing 0.12 E4/E7/E9/F policy rather than inheriting expanded 0.17 defaults. Final CI and merge state must be verified on PR #34; local successes alone do not close synchronization.

## Current work

P10-B is authorized but waits for GitHub main synchronization. No independent-source P10-B material processing has started. The existing CURRENT_TASK and NEXT_TASK records govern this pause. P10-A need not be restarted: its documented scope is complete.

[Engineering evidence](ENGINEERING_EVIDENCE_INDEX.jsonl) · [Decisions](DECISIONS.md) · [Historical UAT](REAL_WORLD_UAT.md) · [Refactor closeout](../refactor/closeout-report.md)
