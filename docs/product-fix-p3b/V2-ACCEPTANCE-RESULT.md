# P3B V2 UI acceptance — final audit

2026-10-07, Asia/Taipei. **V2_UI_ACCEPTANCE: PASS.** This evaluates nomination/UI clarity from the user's final persisted review. It does not establish class-label accuracy, learned-classifier safety, or permission to train.

```text
TOTAL_REVIEWED: 30
VALID_TARGET: 29
INVALID_NOMINATION: 0
UNCLEAR_TARGET: 1
DIRECT_SKIP_WITHOUT_STAGE0: 0
STAGE1_CLASSES_PRESENT: 25 total; SINGLE_PHYSICAL_STROKE=7,
  TRUE_PARALLEL_STRUCTURE=6, OTHER=12, AMBIGUOUS=0
TRACEABLE_TARGET_RATE: 29 / 30 = 96.67%
V2_UI_ACCEPTANCE: PASS
ZERO_SOURCE_SUPPORT_ENTERED_STAGE1: 0
INCONSISTENT_X_U_OVERWRITES: 0
STAGE1_CLASS_WITHOUT_PRIOR_V: 0
ALL_30_PRESENTATIONS_PERSISTED: YES
FINAL_SAVED_STATE_SCHEMA_VALID: YES
FORMAL_SEED_BATCH_PROPOSAL: 100
FORMAL_SEED_QUEUE_PREPARED: YES
FORMAL_SEED_QUEUE_LAUNCHED: NO
TRAINING_AUTHORIZED: NO
MODEL_TRAINED: NO
PRODUCTION_CODE_CHANGED: NO
DXF_CHANGED: NO
OCR_WORK: NO
VALIDATION_OR_BLIND_SOURCES_OPENED: NO
COLAB_STARTED: NO
NEXT_STEP: later start formal human seed labeling
STOP
```

## Saved evidence and consistency

The audit reads [labels/v2-ui-acceptance.json](labels/v2-ui-acceptance.json), bound to [real-v2-acceptance.jsonl](real-v2-acceptance.jsonl). The state is unchanged, SHA256 `03d210a578ce45a6fc302e9c9000e5cf8d11a271c2614aa90ca649f3a8e31a2c`; the manifest is unchanged, SHA256 `435a779017e88bef35897b84e0496dbb14f98d99f58f2cbe4c19b7cad53e3d72`. Revision 273 equals the 273 durable history records, across two session IDs.

- All **30 unique targets** have persisted Stage-0 decisions and presentations. There are 111 presentation records because the user revisited targets. These revisits are not duplicate dataset nominations.
- Replaying all mutations and **48 undo actions** reproduces the final statuses, classes, skips, cursor and remaining undo stack. There are **16 targets** with an earlier X/U and a later V: 15 earlier X and one earlier U. Their earlier decisions were explicitly undone before the subsequent review. No unexplained overwrite or residual invalid status/class conflict exists. The final saved answers control this acceptance; the report does not infer why the reviewer revised them.
- All **40 historical Stage-1 assignment actions**, including subsequently undone assignments, had an active prior human V and nonzero source support. All 25 final classes have the correct sample digest and valid nomination. Four additional V targets have persisted Stage-1 skips. None is a direct skip without Stage 0.
- The full saved state passes [label-state-v2.schema.json](label-state-v2.schema.json). All 30 completed nomination decisions pass [label-contract-v2.schema.json](label-contract-v2.schema.json). Manifest/sample/label-version hashes, presentation ranks and history ordering also pass semantic checks.
- Source-support checks recomputed from the **30 existing frozen grayscale crops** find no zero-support target. Crop hashes match their manifest. This audit does not reopen validation/blind sources.

The sole final U is `real-v2-08b5dac6329894327618dbf8`, a CONTROL on A2-SG-009 page 1. It retains U with no physical class and counts against the 30-sample denominator. No re-review or relabeling is requested.

## Duplicate burden

The final 30-target queue has **0 exact / 0 near / 0 same-structure repetitions** under the frozen V2 deduplication policy, across 13 drawings with at most three targets each. For comparison, the V1 pilot's first 209 presentations contained four policy-detected repetitions (two near and two same-structure); its control targets also lacked explicit ROIs. V2 preparation removed three near and one same-structure repetition before releasing only the bounded 30-target review. The nomination/UI workload therefore meets this acceptance pass's duplicate-burden criterion. These measurements concern the reviewed queue and policy; they are not a claim that the entire corpus contains no repetitive structures.

## First formal seed queue — proposed 100, prepared but unlaunched

[formal-seed-v2-001.jsonl](formal-seed-v2-001.jsonl) contains **100 fresh train-only nominations**: 60 PAIR, 20 SINGLE and 20 CONTROL. These target-type quotas emphasize the paired-edge decision while retaining single-line and OTHER controls; they do not presume human classes. Thirteen drawings contribute 4–10 targets each. Related sheets retain their original source-family split; the frozen split manifest SHA256 remains `d354b6604e92a1e6c8a01d10bb61032c2872167188bff4d4b7943b3955b25444`.

Every target retains source/page/bbox/DPI/source hash, exact geometry IDs or CONTROL ROI, source-support quality measurements and current deterministic-decision provenance. The accepted V2 display and quality thresholds are retained. Stage 0 is always first; only V enables Stage 1. X/U remain valid rejection/clarity outcomes, and AMBIGUOUS remains a valid Stage-1 class after V. Text/glyph objects are OTHER controls, never structural-line truth by assumption.

Seed deduplication compares candidates against all 30 acceptance targets, excludes their parent nominations, widens same-page proximity/perceptual comparisons to 320 pixels/24 bits, preserves distinct pair-gap/topology safeguards, and suppresses exact raster repeats globally. It removed eight near and two same-structure nominations from the transient pool plus acceptance anchors. The selected batch has no exact raster repeats. Selection cycles sources/target types, uses no human class or model prediction, and caps each drawing at 10.

All seed nomination statuses/classes/provenance start null. **No acceptance or V1 classes are imported.** The proposed label file `labels/formal-seed-v2-001.json` does not exist yet. The separate formal launcher is prepared, with manifest/PASS/split checks, but was not executed. Training authorization remains false in manifests and future saved review records.

Only the 100 selected patch folders are retained externally under `C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/real-v2-formal-seed-001`. Manifests, small audit results, schemas and scripts stay in the checkout; full-page renders and the remaining nomination pool are transient. Regeneration refuses to overwrite a changed manifest or a queue whose human labeling has begun. Preserve source-bound human evidence before any later cache archival/removal.

## Reproduction and verification

From `instrumented-e03`:

```powershell
& ../.venv/Scripts/python.exe -B tools/p3b/audit_acceptance.py
& ../.venv/Scripts/python.exe -B tools/p3b/prepare_seed_v2.py
& ../.venv/Scripts/python.exe -B -m unittest discover -s tools/p3b -p 'test*.py' -v
```

The first command only audits existing crops/state and writes [v2-acceptance-audit.json](v2-acceptance-audit.json). The second prepares assets without launching the UI. [formal-seed-v2-summary.json](formal-seed-v2-summary.json) and [formal-seed-v2-dedup.json](formal-seed-v2-dedup.json) record the batch and selection. The existing acceptance launcher remains restricted to 30; a separate formal-seed mode is bound to the prepared batch.

The formal manifest reproduced byte-identically on a second preparation run, SHA256 `6019f7fb321d924407eb1203260607a18dbb23fddb36a766724c3803b2a9cd37`. All 100 saved raw crops match their hashes and pass recomputed source-support/extent gates. The selected 100 plus 30 acceptance anchors contain zero policy-detected repeats even under the stronger seed policy. The external batch occupies 11,195,967 bytes, including 800 small channel/display/context PNGs. [v2-acceptance-verification.json](v2-acceptance-verification.json) records these checks, frozen evidence hashes, and unchanged production files.

All 25 offline preparation/contract/audit tests pass, including history tampering, class-without-V, zero support, missing presentations, malformed state, stronger deduplication and fresh train-only seed boundaries. Ruff passes. Test evidence: [v2-acceptance-tests.txt](v2-acceptance-tests.txt). The 157 production app/test source hashes match the pre-pilot snapshot. Existing P3A changes remain untouched; P1/P2B/P3A regressions are unchanged/not applicable to this offline preparation. No production training, geometry integration, DXF edit, OCR work or Colab run occurred.
