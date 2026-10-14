# FORMAL-SEED-V2-001 FINAL REPORT

2026-10-07, Asia/Taipei. One manual foreground recovery task. The cancelled heartbeat remains absent.

**FORMAL_SEED_HEALTH: PASS_WITH_REVIEW_SUBSET.** Recommend **B. REVIEW SMALL SUSPECT SUBSET**: 13 nominations, prioritizing three true-parallel decisions. This recommendation is not launched or prepared as another labeling run. No training is authorized.

```text
HEARTBEAT_STATUS: NOT_PRESENT
TOTAL_REVIEWED: 100
VALID_TARGET: 95
INVALID_NOMINATION: 4
UNCLEAR_TARGET: 1
SINGLE_PHYSICAL_STROKE: 38
TRUE_PARALLEL_STRUCTURE: 21
OTHER: 36
AMBIGUOUS: 0
VALID_BUT_UNCLASSIFIED: 0
SKIPPED: 0
NO_STAGE0_STATUS: 0
NOMINATION_STRONG: 82
NOMINATION_BORDERLINE: 13
NOMINATION_POOR: 0
TRAINING_READY_LABELS: 82
REVIEW_RECOMMENDED: 13
EXCLUDED: 5
FORMAL_SEED_HEALTH: PASS_WITH_REVIEW_SUBSET
RECOMMENDED_NEXT_ACTION: B. REVIEW SMALL SUSPECT SUBSET
SIMPLIFIED_FUTURE_UI_JUSTIFIED: YES
SUSPECT_REVIEW_QUEUE: 13
BACKGROUND_TASKS_CREATED: NO
TRAINING_AUTHORIZED: NO
NEXT_ACTION_STARTED: NO
STOP
```

## Frozen human evidence

Manifest SHA256: `6019f7fb321d924407eb1203260607a18dbb23fddb36a766724c3803b2a9cd37`.

Label-state SHA256: `54b405724f2bd7ea20e09327967ff449db56091f106267a4c6d272261449be1d`.

All 100 reviewed; 385 durable history records and revision 385, with 24 undo actions and 201 remaining undo events. Full schema/history/manifest/sample-digest checks pass, with zero class-before-V or inconsistent X/U overwrite. The saved human answers and frozen copies remain byte-identical.

No acceptance sample IDs overlap the formal queue. All final classes have fresh formal human source-review provenance after Stage 0; replay starts from empty state and reproduces every final record. Some underlying nomination IDs also exist in V1, which is source identity reuse, not class import. No V1 or acceptance decisions were copied.

[formal-seed-freeze.json](formal-seed-freeze.json) records preserved identities; the frozen manifest/state are in `frozen/formal-seed-v2-001`. `audit_formal_seed.py` was run manually exactly once in this task. Its distribution-only PASS is refined here using the independent correspondence findings and the reviewer's reliability feedback.

## Independent nomination quality

Source crops were recomputed from 17 pages of the 13 frozen TRAIN drawings and verified against source/crop hashes and cached pixels. Candidate/source correspondence was recomputed before attaching human answers. No class is used as a quality input. Ten class-unannotated source/overlay contact sheets were visually inspected; no intended target was shifted or redrawn.

Unlike the queue gate's interpolated distance lookup, this audit samples every 0.5 source pixel and uses exact Euclidean nearest-dark-pixel distances (threshold 180) plus tangent probes ±3 pixels. Edge coordinates may lie slightly outside a filled stroke; 1.5-pixel support tolerance avoids treating ordinary edge sampling as a bad nomination. These are pixel distances, not physical-width ground truth.

Strong line correspondence requires support ≥98%, mean distance ≤1.1px, p95 ≤1.5px, endpoint and tangent alignment ≥95%, in-bounds displayed extents, pair length ratio ≥0.85, and separation range ≤1px. Borderline retains identifiable source objects with weaker alignment/support or unequal extents. Poor requires substantial unsupported/misaligned geometry, e.g. support <60%, mean >2.5px, tangent alignment <50%, severely missing bounds, or no defensible common pair extent. Slightly imperfect endpoints alone do not cause exclusion.

Per-sample metrics include source support, mean/p95 distance, endpoint support, tangent agreement, bounds, pair overlap, length ratio and separation range/std/mean in [formal-seed-correspondence-audit.jsonl](formal-seed-correspondence-audit.jsonl). CONTROL has no line geometry: line metrics are explicitly not applicable, and its ROI bounds/source ink are evaluated instead. Bounded local candidates are not required to cover the entire page-wide rule; unequal partner extents are a review flag, not proof the human class is wrong.

Among the 95 labeled V samples: **82 strong / 13 borderline / 0 poor**. All 13 borderline samples are PAIRs. The five human X/U nominations are excluded regardless of what pixel support measures, and are not included in that 95-sample quality denominator. READY is a derived source-correspondence eligibility flag, not a claim of perfect physical-class accuracy or permission to train.

| Human class | READY | REVIEW_RECOMMENDED |
|---|---:|---:|
| SINGLE_PHYSICAL_STROKE | 38 | 0 |
| TRUE_PARALLEL_STRUCTURE | 18 | 3 |
| OTHER | 26 | 10 |
| AMBIGUOUS | 0 | 0 |

Original human V/X/U and classes are untouched. Any future AMBIGUOUS evidence stays ambiguous and is never a positive SINGLE/TRUE_PARALLEL example.

## Human distribution and source/DPI breakdown

PAIR_SINGLE_COUNT: 22; PAIR_TRUE_PARALLEL_COUNT: 21; PAIR_OTHER_COUNT: 16; PAIR_AMBIGUOUS_COUNT: 0. The remaining PAIR has human X.

### target_kind

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | Skip | V unclassified | Ready | Review | Exclude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 20 | 19 | 0 | 1 | 3 | 0 | 16 | 0 | 0 | 0 | 19 | 0 | 1 |
| PAIR | 60 | 59 | 1 | 0 | 22 | 21 | 16 | 0 | 0 | 0 | 46 | 13 | 1 |
| SINGLE | 20 | 17 | 3 | 0 | 13 | 0 | 4 | 0 | 0 | 0 | 17 | 0 | 3 |

### source_drawing_id

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | Skip | V unclassified | Ready | Review | Exclude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A2-SG-009 | 10 | 8 | 1 | 1 | 2 | 6 | 0 | 0 | 0 | 0 | 6 | 2 | 2 |
| A2-SG-022 | 10 | 10 | 0 | 0 | 4 | 6 | 0 | 0 | 0 | 0 | 9 | 1 | 0 |
| G0R2-15EE2398726E8037 | 5 | 5 | 0 | 0 | 0 | 1 | 4 | 0 | 0 | 0 | 5 | 0 | 0 |
| G0R2-3560D9BEBEAA3543 | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 | 4 | 6 | 0 |
| G0R2-3B970FD759C6026F | 9 | 9 | 0 | 0 | 8 | 0 | 1 | 0 | 0 | 0 | 9 | 0 | 0 |
| G0R2-4A34D1B8D93B1B06 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 0 | 4 | 0 | 0 |
| G0R2-6C9464FA73A2A027 | 9 | 9 | 0 | 0 | 4 | 1 | 4 | 0 | 0 | 0 | 7 | 2 | 0 |
| G0R2-7E30C7F445081F40 | 8 | 6 | 2 | 0 | 1 | 1 | 4 | 0 | 0 | 0 | 6 | 0 | 2 |
| G0R2-B441E5911528F402 | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 4 | 0 | 0 |
| G0R2-C2D095E069663C17 | 8 | 8 | 0 | 0 | 4 | 1 | 3 | 0 | 0 | 0 | 8 | 0 | 0 |
| environment-building | 9 | 9 | 0 | 0 | 5 | 3 | 1 | 0 | 0 | 0 | 9 | 0 | 0 |
| sample-plan-photo | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| warehouse-electrical | 9 | 8 | 1 | 0 | 5 | 1 | 2 | 0 | 0 | 0 | 6 | 2 | 1 |

### source_family_id

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | Skip | V unclassified | Ready | Review | Exclude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AU_NSW_P5_2023_61 | 8 | 6 | 2 | 0 | 1 | 1 | 4 | 0 | 0 | 0 | 6 | 0 | 2 |
| AU_NSW_P5_2024_93 | 8 | 8 | 0 | 0 | 4 | 1 | 3 | 0 | 0 | 0 | 8 | 0 | 0 |
| CAN_BELLEVILLE_SCHOOL_ARCHIVE | 10 | 8 | 1 | 1 | 2 | 6 | 0 | 0 | 0 | 0 | 6 | 2 | 2 |
| CN_ZHEJIANG_PUBLIC_ELECTRICAL_0C1671 | 4 | 4 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 0 | 4 | 0 | 0 |
| JP_IGA_2020000378 | 9 | 9 | 0 | 0 | 4 | 1 | 4 | 0 | 0 | 0 | 7 | 2 | 0 |
| JP_IGA_4291000114 | 5 | 5 | 0 | 0 | 0 | 1 | 4 | 0 | 0 | 0 | 5 | 0 | 0 |
| JP_YOKOHAMA_HIYOSHIDAI_TEMP_CLASSROOM | 9 | 9 | 0 | 0 | 8 | 0 | 1 | 0 | 0 | 0 | 9 | 0 | 0 |
| TW_NTPC_INDIGENOUS_HOME_STANDARD_2016 | 10 | 10 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 | 4 | 6 | 0 |
| UK_BANBURY_TRAMWAY_ASBUILT | 10 | 10 | 0 | 0 | 4 | 6 | 0 | 0 | 0 | 0 | 9 | 1 | 0 |
| US_LOC_HABS_FL0790 | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 4 | 0 | 0 |
| sample-plan-photo | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| user-project-haiyang | 18 | 17 | 1 | 0 | 10 | 4 | 3 | 0 | 0 | 0 | 15 | 2 | 1 |

### source_dpi

| Group | Reviewed | V | X | U | Single | Parallel | Other | Ambiguous | Skip | V unclassified | Ready | Review | Exclude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 110 | 81 | 78 | 3 | 0 | 29 | 14 | 35 | 0 | 0 | 0 | 68 | 10 | 3 |
| 240 | 4 | 4 | 0 | 0 | 3 | 0 | 1 | 0 | 0 | 0 | 3 | 1 | 0 |
| UNKNOWN — original raster physical DPI not available | 15 | 13 | 1 | 1 | 6 | 7 | 0 | 0 | 0 | 0 | 11 | 2 | 2 |

PDF/source-derived rasters retain their effective 110 or 240 DPI. The 15 unknown-DPI samples are original raster sources; requested rendering DPI is not substituted for unknown physical DPI.

## OTHER ownership and future workflow

| Category | Count |
|---|---:|
| TEXT_OR_DIGIT | 33 |
| COMPOUND_SYMBOL | 2 |
| GRAPHIC_OBJECT | 1 |
| FILL_OR_HATCH | 0 |
| ARTIFACT_OR_NOISE | 0 |
| OTHER_OTHER | 0 |

Manual taxonomy examines the nominated object, not every object visible in the crop. The two compound symbols are #10 (boxed code within circular legend) and #81 (boxed stylized mark near branding); the graphic object is #49 (annotation stamp frame). The remaining 33 are visible text/digit/glyph targets. No OCR recognition or semantic accuracy work was performed. Per-sample evidence is in [formal-seed-other-ownership.jsonl](formal-seed-other-ownership.jsonl); these categories do not replace the saved OTHER classes.

The queue imposed substantial avoidable interaction: 33% of all presentations were obvious text/digit targets requiring V → OTHER, and 36% were outside the two structural classes. Actual category-specific time was not measured; some OTHER examples remain useful hard negatives, so these counts do not mean every such decision was wasted.

**SIMPLIFIED_FUTURE_UI_JUSTIFIED: YES, with safeguards.** A future 1=one line, 2=two structural lines, 3=non-target, 4=source-class ambiguity, X=bad nomination workflow can reduce unnecessary two-stage interaction. Geometry quality must remain separately checked and recorded. X must never stand in for source ambiguity, and insufficient visualization must retain a distinct unclear-target disposition (U or equivalent). Only trusted, explicit source ownership may pre-filter text/graphics; do not blanket-filter by proximity to text boxes or exclude table/frame rules and mixed boundaries. Keep a small diverse curated OTHER set for safety evaluation. No simplified UI or ownership filter was implemented.

## Seed health and one recommended next action

82 source-supported labels remain nominally ready (38 SINGLE, 18 TRUE_PARALLEL, 26 OTHER). Thirteen bounded PAIR nominations have imperfect endpoint/tangent support or unequal extents, including three TRUE_PARALLEL decisions. Recheck that subset before training; do not redo the 100 or treat slight overlay defects as human class errors.

The human seed has 38 SINGLE and 21 TRUE_PARALLEL labels across 10/9 drawings and 9/8 families respectively. The 82 READY labels include 18 source-supported true parallels, sufficient for a small exploratory baseline after acceptance, rather than a validated model or precise safety estimate. OTHER is 37.9% of labeled V samples; no catastrophic class imbalance is evident. Thirteen drawings and twelve source families are represented, with maximum drawing/family shares 10%/18%. X/U is 5%, at the previous nomination-quality threshold. No new systemic floating/missing-geometry family was found.

Three borderline true-parallel labels are not automatically invalid: both rails are visible, but their extents differ. Confirming them could restore the full 21-class support. Zero AMBIGUOUS labels and the concentration of 12/21 true parallels in two A2 archives remain coverage limitations; do not invent ambiguous examples or expand training in this task.

**B. REVIEW SMALL SUSPECT SUBSET** is the only recommended next action. Confirm the three structural decisions first, then the ten source-supported OTHER nominations with imperfect endpoint/tangent support or unequal extents. Do not repeat all 100. The nominal READY/REVIEW flags are approximate source-correspondence assessments; they do not accuse the reviewer of errors. Independent validation labeling is deferred until that bounded review is accepted. No next-action UI, dataset or validation batch was started.

### Recommended 13 samples (not a launched review queue)

| Original rank | Sample ID | Drawing | Saved class | Review reason |
|---:|---|---|---|---|
| 1 | real-40651c8f7456a8fcd456ef80 | A2-SG-009 | TRUE_PARALLEL_STRUCTURE | PAIR_UNEQUAL_EXTENT |
| 40 | real-48f0cee35570a79663988685 | A2-SG-009 | TRUE_PARALLEL_STRUCTURE | PAIR_UNEQUAL_EXTENT |
| 65 | real-9d5e486edda4bc3978792245 | A2-SG-022 | TRUE_PARALLEL_STRUCTURE | PAIR_UNEQUAL_EXTENT |
| 4 | real-602f15f56aa19daaa5968f38 | G0R2-3560D9BEBEAA3543 | OTHER | B_ENDPOINT_SUPPORT, B_LOCAL_TANGENT_ALIGNMENT, PAIR_UNEQUAL_EXTENT |
| 46 | real-35237b3af343941bd896f3f6 | G0R2-6C9464FA73A2A027 | OTHER | A_LOCAL_TANGENT_ALIGNMENT, PAIR_UNEQUAL_EXTENT |
| 66 | real-6b47221a7d0b06d16aba5e46 | G0R2-3560D9BEBEAA3543 | OTHER | A_LOCAL_TANGENT_ALIGNMENT, B_LOCAL_TANGENT_ALIGNMENT |
| 68 | real-b5d026c19f431084528841a6 | G0R2-6C9464FA73A2A027 | OTHER | B_LOCAL_TANGENT_ALIGNMENT, PAIR_UNEQUAL_EXTENT |
| 72 | real-4f65fa426b2669dde99dad93 | warehouse-electrical | OTHER | B_LOCAL_TANGENT_ALIGNMENT, PAIR_UNEQUAL_EXTENT |
| 75 | real-8f5fb67c351941da87125e40 | G0R2-3560D9BEBEAA3543 | OTHER | B_LOCAL_TANGENT_ALIGNMENT |
| 81 | real-67ee997bf7c474f2493f123b | warehouse-electrical | OTHER | B_LOCAL_TANGENT_ALIGNMENT |
| 84 | real-9753827163aa0491a3566080 | G0R2-3560D9BEBEAA3543 | OTHER | PAIR_UNEQUAL_EXTENT |
| 93 | real-b6e833e0e89bef821a51d5b3 | G0R2-3560D9BEBEAA3543 | OTHER | PAIR_UNEQUAL_EXTENT |
| 100 | real-c7d4e7b292d5f55400eca8ea | G0R2-3560D9BEBEAA3543 | OTHER | B_LOCAL_TANGENT_ALIGNMENT |

[formal-seed-suspect-review-recommendation.json](formal-seed-suspect-review-recommendation.json) binds this recommendation to the frozen state. It contains no new geometry or human answers.

No heartbeat, timer, watcher, scheduler, polling loop or background task was created. No training, ML installation, Colab/Drive access, validation/blind source access, production code, DXF or OCR changes occurred. Training remains forbidden until this audit and seed distribution are accepted by the user/reviewer. STOP.
