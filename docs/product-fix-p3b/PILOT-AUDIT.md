# P3B pilot audit and nomination-quality correction

2026-10-06, Asia/Taipei. V1 human labeling is stopped. The subsequent two-stage user instruction takes precedence: **all 145 saved labels are PILOT_V1_UNVERIFIED, with zero training authorization**. This is a candidate/workflow audit, not a completed seed.

```text
PILOT_REVIEWED: 209 distinct presented positions, reconstructed in V1 order
PILOT_SAVED: 145
PILOT_UNLABELED_OR_SKIPPED: 64 (63 earlier; current sample 209 unacted)
LABELABLE_RATE: NOT_ESTABLISHED; saved/presented proxy 69.38%; automated gate eligibility 19.62%
CANDIDATE_MISALIGNMENT: 46 / 209 = 22.01% (quality flags)
PARTNER_EDGE_MISSING_OR_FLOATING: 43 / 209 = 20.57% (quality flags)
SEVERE_EXTENT_MISMATCH: 61 / 209 = 29.19% (quality flags)
NO_EXPLICIT_TARGET: 47 / 209 = 22.49% (verified missing-target controls)
TARGET_CLIPPED: 74 / 209 = 35.41% (full nominated endpoints outside displayed margin)
DUPLICATE_EXACT: 0
DUPLICATE_NEAR: 2 / 209 = 0.96% (conservative local policy)
SAME_STRUCTURE_REPETITIONS: 2 / 209 = 0.96% (conservative local policy)
GENUINELY_AMBIGUOUS: NOT_ESTABLISHED; 0 saved AMBIGUOUS labels, no human Stage-0-certified ambiguity
OTHER_UI_FAILURE: pair members use one red mask without A/B or endpoint labels (159 pair presentations affected)
ROOT_CAUSE: loose nomination geometry and implicit controls entered a class-only UI without a nomination-validity contract
PILOT_LABELS_RETAINED: 0 trusted labels
PILOT_LABELS_QUARANTINED: 145
REAL_V2_CANDIDATES: 30, acceptance-only
UI_V2_READY: YES
V2_30_50_SAMPLE_ACCEPTANCE_READY: YES, limited to 30 by latest user instruction
PRODUCTION_CODE_CHANGED: NO
MODEL_TRAINED: NO
NEXT_STEP: user reviews only 30 V2 candidates under Stage 0 then Stage 1
STOP
```

## Exact pilot boundary and preservation

The user confirmed stopping at **Sample 209/769, 145 saved, one continuous session without closing/reopening**. V1 ordering is deterministic: group by drawing, retain each group's manifest order, interleave alphabetically sorted drawings by within-group index. The frozen manifest hash matches the label file. Last saved rank is 207; rank 208 is unlabeled, and rank 209 was displayed when the user stopped. Thus the distinct encountered window is positions 1–209, with 63 earlier skipped/left-unlabeled positions and one current unlabeled position. We do not call the current displayed target a completed skip. V1 did not persist presentation events/skips/cursor, so any transient undo/revisit event counts cannot be reconstructed from the file. The confirmed continuous-session position supports the distinct window; it does not fabricate a chronological event log.

[pilot-review-manifest.jsonl](pilot-review-manifest.jsonl) records all 209 IDs, ranks, drawings/pages, nomination types, saved class or explicit unlabeled status, candidate geometry, source-crop hash, visible overlay availability and quality diagnostics. It references the original unchanged V1 records. The audit is independent of human classes: nomination checks read source ink/geometry and never use the saved class to decide whether a target is correct.

Original labels: SHA256 `1ea4314aa4bd6f58266205e750a92076dc866cbbc2b04bd59b2d9e379868a624`; 145 decisions, with 84 TRUE_PARALLEL_STRUCTURE, 44 SINGLE_PHYSICAL_STROKE, 17 OTHER, 0 AMBIGUOUS. Bound V1 manifest: `a33a88cdeff760fcb5a360997e723cdf708d5500fb52ce829e9068cf3cf79678`. Preservation copies and quarantine status are in [pilot-freeze.json](pilot-freeze.json). No decision was deleted, reset, relabeled or reused as V2 truth.

## Independent source/display inspection

All 209 source/overlay pairs were inspected in [pilot-contact-sheets](pilot-contact-sheets). Raw source crops were additionally verified against a fresh read of the frozen train source and their recorded pixel hash, so nomination defects are not hidden by evaluating against a mismatched raster. Representative visual findings include:

| Queue rank | Observable problem |
| --- | --- |
| 13, 26, 61, 208 | Source crop contains text/ink but no bounded nominated object or target overlay. The user must guess what was intended. |
| 45 | Red vertical candidate lies visibly in source background. Its saved SINGLE class is preserved, but cannot certify an actual physical stroke. |
| 51, 64, 90, 116, 168 | A member deviates from source rails/hatch strokes or its partner is unsupported; a class-only answer cannot express this defect. |
| 24, 53, 77, 101, 194 | Nominated full extents do not fit the displayed patch or pair lengths mismatch. Seeing a local line segment does not establish the entire candidate identity. |
| 18/44, 14/27 | Repeated table/plan neighborhoods create burden even when exact crop hashes differ. Different source structure must not be removed solely because its drafting style resembles another. |

Counts in the summary are **overlapping source-quality flags**, not mutually exclusive inferred reasons for human skips. The conservative gate intentionally flags more than only visually obvious failures. A flag does not relabel the source or assert the reviewer's intent. The exact subset of earlier skipped/current candidates has: 47 missing overlays, 6 A-misalignment flags, 5 floating/missing-partner flags, 9 extent flags, 7 clipped-target flags, and 6 endpoint/local-alignment flags. Four unlabeled candidates pass the automated gate; their human reasons remain unknown. Genuine source ambiguity cannot be established from a missing/invalid target or lack of a class decision. No automatic AMBIGUOUS label was created.

Saved/presented 145/209 = 69.38% is only a pilot response rate. It is **not** validated labelability or accuracy. Only 41/209 pass the corrected automated display/support gate (19.62%), including 37 labeled and four unlabeled cases. Passing cannot certify human VALID_TARGET. After the later contract change, even those 37 remain unverified and training-unauthorized.

## Quality measurements and HUMAN_QUEUE_ELIGIBLE

[quality.py](../../tools/p3b/quality.py) is offline dataset code and imports no production merge function. Full original source rasters are read only from frozen train IDs. Metrics include each member's source-support ratio, unsupported fraction, mean/median/p95 distance to dark ink, endpoint support, local tangent alignment and in-bounds ratio; pair overlap length, length ratio, and separation range/std/mean. A/B metrics have distinct names, including `A_SOURCE_SUPPORT_RATIO`, `B_SOURCE_SUPPORT_RATIO`, `A_MEAN_DISTANCE_TO_DARK_INK`, `B_MEAN_DISTANCE_TO_DARK_INK`, `PAIR_OVERLAP_LENGTH`, `PAIR_LENGTH_RATIO`, `PAIR_SEPARATION_STABILITY`, `ENDPOINT_SUPPORT` and `LOCAL_INK_ALIGNMENT`.

Dark ink is source grayscale ≤180. Exact Euclidean distance is sampled along each segment, using bilinear lookup, approximately once per source pixel (bounded at 8,192 samples). Support means distance ≤1.25 px. Endpoints use the minimum supported fraction in each terminal five-sample band. Local alignment checks that source support continues along the tangent at ±3 px instead of only touching an isolated crossing. Pair separation is measured at 19 positions over its projected overlap.

Queue eligibility requires for each member: ≥90% support, mean distance ≤1.0 px, p95 ≤2.0 px, endpoint support ≥75%, and local alignment ≥75%. Pairs require overlap ≥32 px, length ratio ≥0.70 and separation range ≤1.5 px. Full displayed geometry endpoints must lie at least 12 pixels inside the 256-pixel source crop. Controls require an explicit target ROI with at least four dark source pixels, contained with an eight-pixel margin. Missing ROI/cardinality or clipping rejects the nomination. These deliberately conservative limits filter obvious extraction failure; they do **not** establish physical class, valid structural ownership or a production action.

V2 reuses only unchanged targets that pass the queue gate. Source-supported long/mismatched candidates may instead be trimmed to a common bounded **offline nomination** extent (maximum 180 px), then independently rechecked. Unsupported geometry is not shifted onto some unrelated source object. Controls receive an explicit connected-ink ROI. Any changed bbox/geometry/ROI gets a new sample identity and no inherited class. Source and production CAD remain untouched. No P3A heuristic merge rule was added.

## Duplicate audit and queue correction

V1 extraction did exact raw crop SHA suppression plus 80-pixel center spacing. Center spacing did not identify repeated portions of the same long rule, and changing text/neighborhood pixels defeated exact hashes. dHash/perceptual suppression existed only in the future active-learning selector; it was **not used by the initial human queue**, which explains why its presence in the old plan did not protect this pilot.

[queue_dedup.py](../../tools/p3b/queue_dedup.py) compares within a drawing/page and target type. It rejects exact crop duplicates; repeated shared geometry in a 192-pixel neighborhood; and local 256-bit difference-hash neighbors (distance ≤20) with similar angle, pair gap and local edge complexity. Different pair gaps/topology and independent source origins are retained. [pilot-duplicate-audit.json](pilot-duplicate-audit.json) identifies two near duplicates and two same-structure repeats among the 209, leaving 205 under this conservative policy. This is a lower-bound policy audit, not a claim to measure every subjective repeated-table/title experience.

V2 internal nominations: 574 pass quality after explicit local-target construction; dedup removes **0 exact, 3 near and 1 same-structure repeat**, leaving **570 internal unique proposals**. These are transient preparation counts, not a released human queue or generated dataset. Only **30** were materialized/queued, round-robin over 13 drawings with a maximum of three each and target-type variety. The 30 are 12 PAIR, 4 SINGLE and 14 CONTROL. No more patches or a large labeling round were generated. The source-diversity cap additionally reduces repeated-style burden that local dedup intentionally avoids conflating with actual duplicates. Human confirmation of burden reduction is still pending.

## Quarantine and acceptance

[pilot-label-disposition.json](pilot-label-disposition.json) triages every original decision: 37 PILOT_V1_RETAINABLE_CANDIDATE, 60 PILOT_V1_INVALID_NOMINATION, 0 PILOT_V1_UNCLEAR_TARGET among saved labels, and 48 PILOT_V1_NEEDS_HUMAN_REVIEW. The invalid bucket flags strong unsupported/severe-extent evidence; borderline failures go to review. All records also say PILOT_V1_UNVERIFIED and `training_authorized=false`. No heuristic certifies VALID_TARGET, and no old class is automatically copied into the new set. There is no request to redo all 145 now.

V2 has explicit red/blue paths, endpoint dots/labels, exact control ROI rectangles, local 4×/8× raw/annotated pixel zoom, and optional nearest-ink distance diagnostics. The user first chooses V/X/U; only V enables classes 1–4. Invalid/unclear nominations never become OTHER or AMBIGUOUS. Presentation/status/skip/cursor/undo persistence fixes the missing V1 audit trail. Full details and launch instructions are in [LABELING-CONTRACT-V2.md](LABELING-CONTRACT-V2.md).

Latest acceptance target supersedes the earlier 90%/30–50 proposal: **at least 29/30 explicitly traceable valid source targets (≥95%)**, understandable Stage 0, zero unsupported Stage-1 entries and materially reduced duplicate burden. Automated gates and visual preparation do not establish user acceptance. Only the user reviews this 30-sample set before any further work.

Storage: real-v1 and its labels remain intact. Only the separate external `real-v2` cache receives the 30 source/overlay/context/diagnostic patches. Small manifests, quarantine metadata and representative/contact-sheet evidence stay in docs; no whole-page arrays/NPZ datasets are persisted. Existing `.gitignore`/`.ignore` and source files are unchanged. Production app/test hashes are checked before/after; no validation/blind source, model training, Colab connection, OCR observation or DXF output was touched.

Verification and reproducible entry points: `tools/p3b/pilot_audit.py --position 209`, `tools/p3b/prepare_v2.py`, `tools/p3b/test_preparation.py`, and `tools/p3b/test_contract_v2.py`. Frozen pilot identity refuses changes, V2 preparation refuses silently overwriting a reviewed set, and training/benchmark ingestion reject V1 truth. See [pilot-v2-verification.json](pilot-v2-verification.json) and the V2 test logs. STOP.
