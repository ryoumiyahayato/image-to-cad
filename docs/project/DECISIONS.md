# Decision log

## D-001 — Never restore full-page topology modification

Status: accepted

Full-page morphological close, generic gap bridging, endpoint-only connection, unlimited extension, or equivalent topology changes are prohibited. Repair may occur only inside validated structural ROI/corridors with full-path protection checks.

## D-002 — Separate text emission from source-glyph suppression

Status: accepted

`text_emit_eligible` determines whether trusted OCR becomes native DXF `TEXT`. `source_outline_suppressible` determines whether original source glyph pixels can be hidden. `replacement_safe` must not block trusted text emission.

## D-003 — Native text may not regress to outlines or images

Status: accepted

Geometry, font, routing, and display improvements must preserve editable native `TEXT`. Visual similarity is not a valid reason to convert text into `LWPOLYLINE`, images, `HATCH`, or glyph outlines.

## D-004 — Source outlines are hidden evidence, not final typography

Status: accepted

Unsafe original glyphs are retained in default-off, frozen `SOURCE_TEXT_OUTLINE`. The layer may be rough. It must not be the formal visible text and must not inflate native-text geometry through contaminated outer bounds.

## D-005 — Diagnostic color is a display mode

Status: accepted

Diagnostic colors are useful for quality review, but formal output remains the default. Formal and diagnostic modes share one `FinalStructure`; color and visibility may change, but entity types, ownership, OCR routing, counts, and repair decisions may not.

## D-006 — Text geometry precedes text routing and structure repair

Status: accepted

P1 text geometry must be stabilized and accepted before P2 symbol routing and P4 line repair. Text placement and protection masks are prerequisites for safe structure recovery.

## D-007 — Every page and every final DXF is accepted independently

Status: accepted

A global average or a single-page success cannot hide a failed page. Automated page/DXF reports and human sampling must state exact coverage.

## D-008 — Human LibreCAD evidence outranks broad automated PASS labels

Status: accepted

When automated results and user observations conflict, record the conflict, preserve both evidence classes, and investigate. Do not replace human failure with an automated success claim.

## D-009 — One major issue per task

Status: accepted

Each task uses one isolated commit, a 20–45 minute recoverable checkpoint where practical, explicit modification boundaries, acceptance criteria, and a stop condition. Recommendations are not executed automatically.

## D-010 — Phase 12 remains an immutable safety baseline

Status: accepted

`baseline/phase12-final-acceptance-2026-07-30` at `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba` is an architecture/safety baseline, not a final product release. It must not be moved or overwritten to make later results appear better.

## D-011 — Optional native ARC members and atomic residual replacement

Status: accepted (P9, 2026-10-13)

`FinalStructure.arcs` contains accepted circular curves. Centers and radii use source pixels; source Y points down, angular Y points up, and signed sweeps preserve source traversal. Zero/full-circle sweeps are rejected. PDF proposals remain separate from final members.

FinalStructure schema is 4; trace cache format is 11. Format 10/schema 3 records verify their original integrity identity, then read with empty arcs. New records require the ARC field. ARC geometry, source references and replacement relationships participate in existing integrity checks. The result cache key distinguishes optional PDF evidence by input content, page, render DPI and evidence policy. External version remains `0.3.0-dev`.

The normal PDF loader captures bounded evidence before closing its page/bitmap. It derives the actual page-to-pixel transform from the rendered canvas, including CropBox and rotation, and composes object/Form matrices. Limits are 4096 page objects, 16 proposals and 16385 numeric samples per curve. Ordinary images and image-only PDFs keep the existing path.

Only complete, visible, opaque, continuous, butt-cap, stroke-only single cubics can supply ARC evidence. Clipping, inherited clipping, dashes, fills, nonuniform transforms and unresolved/noncircular shapes are refused. The circular check uses endpoint tangents, both endpoint radii, monotone sweep and full-segment samples with a between-sample bound. Its tolerance is at most 0.10 raster pixel and 8% of stroke width. Floating PDF coordinates remain a precision limit; this is not an exact recovery of author CAD parameters.

Replacement requires complete residual contour members, source-pixel coverage and edge-range checks. Text, logo, signature, symbol, hierarchy, interior LINE claims and exact shared CAD nodes can veto it. Every non-white antialias sample is native stroke evidence; existing prepared foreground defines upstream ownership. ARC insertion, contour suppression, hierarchy rebinding and the replacement record form one immutable commit. Repeated commits do not duplicate members. Retained LINEs are not moved, extended, merged or deleted. P4/P8 protections remain.

Existing cache, single/document DXF export, preview, summaries and review consumers carry ARC. DXF uses native ARC; preview uses that emitted entity set. Bounds include interior cardinal extrema. Invalid data or nonuniform output transforms fail explicitly. The frozen `draftsman_output_v1` composite namespace is not expanded; combining it with ARC is refused. ELLIPSE, SPLINE, DIMENSION, curve splitting, model 1:1 scale and non-default UserUnit validation remain outside this change.

Tiny p9 was processed once. Its initial ARC decision exposed a gray-254 antialias classification error. After fixing that error, only the ARC stage was resumed from the same saved pre-ARC structure. The corrected stage accepted exterior contour 132 and replaced its three DXF polyline pieces with one ARC. This staged completion is recorded separately from a fresh uninterrupted run of the corrected code. No second whole-page recognition was run. LibreCAD GUI verification remains unperformed.


#### D-011 follow-up: P9-B normal-entry verification (2026-10-13)

The unchanged final P9 code completed a fresh Tiny p9 conversion from the original PDF through the normal loader and ProductionProcessingService, at 240 DPI with OCR and source reconciliation. Exterior contour 132 was accepted without snapshot replay. Its three DXF polylines became one ARC; all other same-run entity content was preserved. A new process reopened the saved result and its paper calibration, then exported the same entities. Editing a temporary ARC copy survived save/read with zero audit errors.

Five preselected independent-source curves were checked. Tasmanian p3 and Southern p5 return PAGE_OBJECT_BUDGET under the existing loader limit. The four Tasmanian curves also use round caps and a nonuniform rendered transform; the Southern curve has clipping and fails endpoint radii. No protection or budget was relaxed. Cross-source replacement remains unverified; no unnecessary independent fullpage trace was run. LibreCAD GUI validation remains NOT_RUN. Schema 4, cache 11 and product version 0.3.0-dev are unchanged. See product-p9b-arc-cross-source-20261013 and the appended engineering index records.


#### D-011 follow-up: P9-C layered native admission (2026-10-14)

The previous 4096 limit counted all recursively expanded page objects and returned before path screening. It is superseded by separate budgets: 32768 objects, eight Form levels (truncation is detected), 256 segments before a long-path skip, 512 cheap support checks, 64 numeric attempts plus at most 16 candidate validation refits, 16 proposals/local renders, one million pixels per local render and four million pixels total. The five-second extraction deadline is cooperative between PDFium calls; restoration is unconditional. Shallow wrapper/list storage observed on the real pages is about 0.4 MB; it excludes nested Python objects and native PDF allocations. This is not a global PDF memory limit.

Full traversal is required for the complete isolated-render context. Noncandidate text, image, fill and other paths remain in the original source render and state snapshot. Partial traversal produces no candidates. Candidate work limits retain independently complete proofs and label the remainder NOT_EVALUATED. Original drawing order and active states are preserved. Existing circle, cap, clip, ownership and node conditions remain.

The v2 layered policy and all budgets participate in the existing processing key. Deterministic limited coverage is explicit; changing budgets invalidates its key. Timeout/unavailable analysis is saved with its member set but without a reusable processing key. Schema 4, cache 11 and product version 0.3.0-dev remain unchanged.

Final-code normal loading visited 6249 Tasmanian p3 objects and 6012 Southern p5 objects. Their 45/48 open single cubics received support-stage decisions: round caps/nonuniform rendered mapping, or clipping. Neither page yielded eligible candidates. This does not validate their circle or final member/node proof. No new wholepage conversion was run. Tiny local ARC-stage geometry matches P9-B, bathroom visibility still rejects, USDA remains an empty-evidence fallback, and 58 related checks pass. See product-p9c-native-admission-20261013 and the appended engineering records.


#### D-011 follow-up: P9-D round caps and integer canvas mapping (2026-10-14)

Keep the composed native object/Form similarity check at 1e-6. A nonuniform page-to-bitmap mapping can proceed only when actual bitmap dimensions equal the renderer's ceil(page size * scale), and removing those measured canvas-rounding factors recovers the nominal orthogonal scale at 1e-6. This identifies the mapping's origin; it does not modify coordinates or grant circle eligibility. Fit the actual transformed control points at the unchanged min(0.10 px, 8% stroke width) tolerance. Endpoint displacement, endpoint tangent direction, curvature sign and a whole-segment Bernstein angular-sign bound are checked. Radial sampling retains its conservative between-sample bound and floating-point limits. Final DXF transforms still require a similarity.

Support round caps only on the existing open, single, continuous, opaque, stroke-only cubic subset. PDF cap 1 extends the centerline with semicircles of half the stroke width ([PDF 32000-1, 8.4.3.3](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf)). After the existing source visibility check, render the complete original context with only this path off. Any other non-white source ink in either mapped cap neighborhood vetoes it. Reserve both renders and their pixels in the unchanged P9-C budgets. Interruption restores the original active states and leaves the candidate NOT_EVALUATED.

Accepted round ARC members retain cap style, mapped stroke-width bounds and the full centerline error. The nearest positive ISO DXF lineweight must bound the round stroke boundary displacement to half a source pixel, separately from the tighter circle tolerance. The bound adds the centerline error and the mapped disk radius difference; it includes both caps and does not average away anisotropy. Actual paper scale is checked again before writing. Source cap foreground must belong to the replaced members. Retained LINE/contour cap claims, mixed members, protections and exact-node conflicts veto the whole replacement. There are no auxiliary cap circles, contour splitting or endpoint movement.

Use native DXF ARC and lineweight. Preserve checked cap/paper-scale metadata in P9_ARC XDATA; the saved-DXF preview uses round ends and the saved entity's actual lineweight. No global end-style change is made. [Autodesk documents rounded object ends by default and plot-style overrides](https://help.autodesk.com/cloudhelp/2024/ENU/DWGTrueView/files/GUID-1778B6B5-3356-4CA8-912A-794EC0C56D71.htm); this is not evidence that every CAD renderer or custom plot style displays identical caps. LibreCAD is unavailable in the checked installation locations and PATH, so native GUI verification remains NOT_RUN.

Policy v3-round-cap invalidates the old round-cap rejection cache. Schema 4/cache 11 remain. Optional round fields participate in the existing ARC payload and identity; default butt fields are omitted so prior schema-4 ARC identities still verify. Old data reads as butt. Old readers cannot silently interpret new round members because their constructor rejects the new fields. Existing save/read, single/document export and preview carry the fields; unsupported output scale fails explicitly.

Tasmanian p3: all 45 structural cubics received geometry checks; 13 passed geometry, 32 failed the existing endpoint-radius/scale condition. Nine then failed source visibility, three failed shared-cap source ink, and one was NOT_EVALUATED at the local render budget. The four requested objects pass geometry but first fail visibility; their final member/node proof was not run. There are no qualified Tasmanian candidates or replacements. No fullpage conversion was warranted. An isolated round contract fixture replaced one polyline with one native ARC and survived a new-process cache reopen, re-export, saved-DXF preview and parameter edit. It is an artificial contract, not an independent real drawing success. Tiny local regression preserves the P9-B ARC and all remaining entity content; bathroom, Southern and USDA retain their refusals/fallback. The 76 directly related checks pass. Overall P9-D is PARTIAL; see product-p9d-round-cap-20261014 and the appended engineering records. External version remains 0.3.0-dev.


## D-012 — Isolated thin scan components may propose native LINE members

Status: accepted (P10-A, 2026-10-14)

Only discarded LSD white-edge locators may trigger the bounded scan review. A complete isolated prepared-source component must independently establish every station, local contrast, width, free fitted trajectory, caps and lack of foreign source or candidate obligations. A fresh source root then enters the existing ownership and reconciliation chain; discarded locators are references, not accepted CAD members being merged. No contour is directly deleted and no accepted endpoint is moved. Connected or mixed carriers remain residual. Exact source width uses existing lineweight records; grey-paper strokes cannot silently fall back to unweighted output.

FinalStructure schema 4 and cache format 11 are unchanged. Processing identity adds isolated-scan-stroke-v1. Budgets are 512 local component checks, 64 station reviews, 65536 pixels per crop, 1000000 total crop pixels and 32 neighbouring candidates. Incomplete/resource-limited evidence keeps old content. USDA physical p4 produces two native LINE replacements; independent-source scan positives are not established. See local-artifacts/product-p10a-scan-regularization-20261014/REPORT.md.

## D-013 — Native runtime compatibility and versioned compact preservation

Status: accepted (PR #34 closeout, 2026-10-14)

Retain CPython 3.11 CI and its single complete pytest process. Linux PySide6/Shiboken 6.12.0 void wrappers lose one owned None reference per call: 256 QPainterPath.moveTo calls lose 256 references, and 8000 calls reproduce exit 134 without product code. With only the Qt binding pair changed to 6.11.2, the same interpreter/calls retain the reference count and exit normally. Requirements therefore exclude 6.12; the paired Shiboken version follows PySide6's exact dependency. A subprocess regression checks ownership and ordinary teardown. RapidOCR remains in its independently verified 3.9 range. No geometry policy or interpreter upgrade masks the fault.

Keep the original compact snapshot and D-010 reference immutable. Authorized, source-proven behavior changes use a separate versioned current snapshot with algorithm/schema/cache identity and exact member/cache/DXF checks. The P10-A snapshot accounts for every old LINE difference and checks that each suppressed observation has no unique source ink outside its unchanged keeper. Missing independent geometry, changed source ownership or unreviewed additions fail. See docs/refactor/preservation-transition-p10a.md. This does not change frozen geometry contracts, the 94/50 split, P10-A's real-source findings or P10-B's paused status.
