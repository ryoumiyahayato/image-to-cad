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

Raw PDFs and `local-artifacts` are not distributed. Small tracked region fixtures support portable regression tests. The current engineering index has 47 retained entries through P10-A. Historical DXF inventory records and their Git recovery references remain nonempty and auditable. Font licensing and exact approved-asset checks remain in force.

## Current work

New feature work is paused for GitHub main synchronization. The existing CURRENT_TASK and NEXT_TASK records govern this pause. After synchronization, P10-A need not be restarted: its documented scope is complete. Further P10 or other feature work needs a new user instruction.

[Engineering evidence](ENGINEERING_EVIDENCE_INDEX.jsonl) · [Decisions](DECISIONS.md) · [Historical UAT](REAL_WORLD_UAT.md) · [Refactor closeout](../refactor/closeout-report.md)
