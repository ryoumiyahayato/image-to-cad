# P3B VALIDATION FINAL AUDIT

```text
AUDIT_RECOVERED: YES
EXISTING_HUMAN_AUDIT_RERUN: NO
TOTAL_REVIEWED: 50
READY: 50
EXCLUDED: 0
BAD_NOMINATION_X: 0
UNCLEAR_TARGET_U: 0
SKIPPED: 0
NOMINATION_STRONG: 46
NOMINATION_BORDERLINE: 4
NOMINATION_POOR: 0
SUSPECT_REVIEW_COUNT: 8
VALIDATION_HEALTH: PASS_WITH_REVIEW_SUBSET
TRAIN_SOURCE_OVERLAP: NONE
TRAIN_VALIDATION_LEAKAGE: NONE
BLIND_TOUCHED: NO
TRAINING_DATA_FREEZE: DEFERRED
READY_FOR_COLAB_TRAINING_PREFLIGHT: NO
BACKGROUND_TASKS_CREATED: NO
MODEL_TRAINED: NO
COLAB_STARTED: NO
PRODUCTION_CODE_CHANGED: NO
DXF_CHANGED: NO
OCR_CHANGED: NO
```

| Human class | Count |
|---|---:|
| SINGLE_PHYSICAL_STROKE | 22 |
| TRUE_PARALLEL_STRUCTURE | 18 |
| OTHER | 7 |
| AMBIGUOUS | 3 |

The original one-time audit completed successfully and was recovered without rerunning it or relaunching the UI. Its manifest/state hashes, all grouped counts and full history/undo replay match the final saved state: 50 durable presentations, 72 presentation-log entries, 14 undos, one session, no class before prior V, no zero-source-support Stage 1 and no inconsistent X/U overwrite.

READY=50 describes persisted valid V+class records, not final acceptance of all semantic truth. Final validation acceptance/freeze is deferred pending the bounded subset below. Original answers and audit artifacts remain unchanged.

## Drawing breakdown

| Group | Reviewed / ready | Excluded | Single | Parallel | Other | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| A2-SG-008 | 13 / 13 | 0 | 6 | 4 | 2 | 1 |
| G0R2-22E85E2DB7746A00 | 12 / 12 | 0 | 6 | 5 | 1 | 0 |
| G0R2-4DC97797ABE2CB18 | 12 / 12 | 0 | 6 | 5 | 1 | 0 |
| G0R2-99D5B85436EBB965 | 1 / 1 | 0 | 0 | 0 | 1 | 0 |
| G0R2-F519B357241CAC3A | 12 / 12 | 0 | 4 | 4 | 2 | 2 |

## Source-family breakdown

| Group | Reviewed / ready | Excluded | Single | Parallel | Other | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| AU_GOLDCOAST_OPW_2014_2240 | 12 / 12 | 0 | 6 | 5 | 1 | 0 |
| TW_NHRM_GREEN_ISLAND_MEMORIAL_IMPROVEMENT | 12 / 12 | 0 | 6 | 5 | 1 | 0 |
| US_LOC_HABS_GU0014 | 1 / 1 | 0 | 0 | 0 | 1 | 0 |
| US_LOC_HABS_UT0288 | 12 / 12 | 0 | 4 | 4 | 2 | 2 |
| US_NARA_BUILDING9 | 13 / 13 | 0 | 6 | 4 | 2 | 1 |

## PAIR / SINGLE / CONTROL

| Group | Reviewed / ready | Excluded | Single | Parallel | Other | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| CONTROL | 5 / 5 | 0 | 0 | 0 | 5 | 0 |
| PAIR | 22 / 22 | 0 | 2 | 18 | 0 | 2 |
| SINGLE | 23 / 23 | 0 | 20 | 0 | 2 | 1 |

## Effective DPI

| Group | Reviewed / ready | Excluded | Single | Parallel | Other | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| 110.000000 | 37 / 37 | 0 | 16 | 14 | 5 | 2 |
| UNKNOWN_SOURCE_DPI | 13 / 13 | 0 | 6 | 4 | 2 | 1 |

## Independent nomination audit

All 50 nomination qualities were computed before attaching human classes, using only source pixels, geometry and explicit ROI. Seven selected source pages were re-rendered/re-read, and every crop matched its frozen SHA256 and cache pixels. The post-label-independent-v1 policy is the same accepted policy used for the formal seed: ink threshold 180, 0.5px probes, 1.5px support radius; support, mean/p95 ink distance, endpoints, local tangent alignment, bounds, overlap, length ratio and pair separation stability. No human class entered quality computation.

Controls use supported explicit ROI ink/bounds; line metrics are not applicable. Slight endpoint/extent/alignment defects produce BORDERLINE, not POOR, while target/source identity remains defensible. Source geometry and production P3A are untouched. All 50 class-unannotated contact views and nine expanded source/overlay/context detail views were inspected; generated previews live only in the external regenerable validation cache.

| Human class (reporting only) | Strong | Borderline | Poor |
|---|---:|---:|---:|
| AMBIGUOUS | 3 | 0 | 0 |
| OTHER | 7 | 0 | 0 |
| SINGLE_PHYSICAL_STROKE | 19 | 3 | 0 |
| TRUE_PARALLEL_STRUCTURE | 17 | 1 | 0 |

## Bounded suspect recommendation

Review only these eight in the listed priority order. Three class-4 decisions are valid uncertainty, not errors: retain class 4 if context cannot resolve them. No expected class is assigned; original classes must be hidden before independent re-review. Rank 41 is a semantic boundary concern despite strong ink correspondence, not a poor nomination. No suspect UI/state has been prepared or launched in this task.

| Rank | Sample ID | Saved class (audit only) | Nomination | Review reason |
|---:|---|---|---|---|
| 16 | val-v2-261d3cffb584f26f925431dd | TRUE_PARALLEL_STRUCTURE | NOMINATION_BORDERLINE | PAIR_UNEQUAL_EXTENT |
| 41 | val-v2-1b8fcd9fb4d9b245ca1596c3 | TRUE_PARALLEL_STRUCTURE | NOMINATION_STRONG | NARROW_PAIR_SINGLE_VS_PARALLEL_BOUNDARY: 4.886px separation; heterogeneous archival ink/white gap can be interpreted as boundaries or a stroked run. Confirm the intended source objects with context; do not infer truth from gap alone. |
| 30 | val-v2-1f535f83ca9c190bc7d39fb8 | SINGLE_PHYSICAL_STROKE | NOMINATION_BORDERLINE | PAIR_UNEQUAL_EXTENT |
| 6 | val-v2-047e2c7b3b9ddaad83674cdd | AMBIGUOUS | NOMINATION_STRONG | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced |
| 17 | val-v2-0ef668e8d4a1ddc737649a25 | AMBIGUOUS | NOMINATION_STRONG | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced |
| 33 | val-v2-19fa87d80bb54ff6794f6a51 | AMBIGUOUS | NOMINATION_STRONG | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced |
| 13 | val-v2-115c58721d68b21e3a19687f | SINGLE_PHYSICAL_STROKE | NOMINATION_BORDERLINE | A_LOCAL_TANGENT_ALIGNMENT |
| 36 | val-v2-3d055195c7ff5a95add31627 | SINGLE_PHYSICAL_STROKE | NOMINATION_BORDERLINE | A_LOCAL_TANGENT_ALIGNMENT |

Recommendation: `validation-suspect-review-recommendation.json`. It preserves original rank/ID/V/class, source identities, metrics and reasons. A future re-review must write a separate state. Do not silently resolve disagreement or train on a disputed decision.

## Health and next phase

22 singles/18 parallels, four structurally represented independent families plus a fifth control family, 14% OTHER, no poor source correspondence or leakage; 42 samples outside bounded review (19 singles/16 parallels/7 OTHER), so usable validation needs a small review, not full relabeling or a systemic quality-failure designation.

No existing class is declared wrong or changed. STRONG measures target correspondence, not guaranteed semantic truth. AMBIGUOUS is a valid label and may stay AMBIGUOUS after independent review.

All drawing/family/source-file/crop/sample-ID intersections with the train manifest are empty; the existing verification also checks exact leakage against the full train pool. Frozen split assignments are unchanged; blind-source inventory metadata is never used to open a blind file. Original audits and protected state hashes remain unchanged.

37 PDF samples at effective render DPI 110, 13 TIFF samples with unknown physical DPI. This supports a small bounded initial comparison, not known multi-DPI robustness.

PAIR has 18 parallels, only two singles and two ambiguous cases; report PAIR-only safety/performance separately to detect target-kind shortcuts and do not claim broad paired-stroke recall from two positives.

18 labeled true parallels are adequate for an initial pilot comparison, not a production false-merge safety estimate. A zero-error run would still leave substantial statistical uncertainty; no model metrics have been measured.

Current adjudicated train seed has zero AMBIGUOUS examples. After review, a separate pre-flight must explicitly address four-class training support or a documented abstention policy; do not silently drop validation class 4.

The train seed remains accepted at 94 current labels (38 SINGLE, 20 PARALLEL, 36 OTHER) across 13 drawings / 12 families. Final validation truth and a training-data freeze are DEFERRED. No new training-data freeze manifest or copied final validation truth was created. Existing historical evidence freezes are preserved.

After a separately authorized bounded review and explicit resolution, reassess validation health. Only then consider an exact train/validation data freeze and a separate Colab/training pre-flight. The future pre-flight would verify the requested official Colab MCP source and installation, interactive login, Drive access, checkpoint write/read/resume, staging frozen train/validation only, and a classical Logistic Regression baseline before any CNN decision. None of those actions was performed or scheduled here.

## Evidence hashes

| Protected input | SHA256 |
|---|---|
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\VALIDATION-V2-001-AUDIT.json | 0d8294c97ddcee301cd901140f00b047a293d1113e4ff59a964e66f91efa1383 |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\VALIDATION-V2-001-AUDIT.md | 4156714431e5218201e8356e67f96a832edb9e8becd5c21e7cf004dd80edc483 |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\formal-seed-adjudicated-decisions.jsonl | 2e4bdfe4e8e1d56beae9b238aba210538dcd215230609079d2d236241813043d |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\labels\formal-seed-v2-001.json | 54b405724f2bd7ea20e09327967ff449db56091f106267a4c6d272261449be1d |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\labels\suspect-review-v2-001.json | e3c9bbedf8282f3abf25ae5f2a9dbe24b74d60536914d0fba3089d2e4402e34b |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\labels\validation-v2-001.json | 006d8e3f61c5e1f0909605e534b78aebb12432f8501ed83b06410dc7d6df8c25 |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\split-manifest.json | d354b6604e92a1e6c8a01d10bb61032c2872167188bff4d4b7943b3955b25444 |
| C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\docs\product-fix-p3b\validation-v2-001.jsonl | de5e3b1d8e3f869d79ed67d5248398c6ff2d005b50b58ccbb7f183fa5d743ed2 |

No packages, model training, account connections, Drive mount, Colab session, UI launch, production/DXF/OCR changes, heartbeat, timer, polling, watcher or background job. All 157 production app/test files match the retained snapshot.

NEXT_ACTION: Independent re-review of the eight recommended validation samples only; preserve originals and valid AMBIGUOUS labels, then resolve disagreements explicitly before final freeze/pre-flight

STOP.
