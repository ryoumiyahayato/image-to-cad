# P3B labeling contract V2

Updated 2026-10-07, Asia/Taipei. The user's two-stage contract supersedes V1's class-only workflow and the earlier proposal to reuse quality-passing pilot labels directly. The persisted 30-target review now passes UI/nomination acceptance; see [V2-ACCEPTANCE-RESULT.md](V2-ACCEPTANCE-RESULT.md). This is not model or training-seed acceptance.

```text
V1_SAVED_LABELS: 145
V1_TRAINING_AUTHORIZED: 0
V1_STATUS: PILOT_V1_UNVERIFIED
V2_TWO_STAGE_CONTRACT: READY
V2_UI: READY
INVALID_NOMINATION_STATUS: IMPLEMENTED
UNCLEAR_TARGET_STATUS: IMPLEMENTED
V2_30_SAMPLE_REVIEW_READY: YES
V2_HUMAN_ACCEPTANCE: PASS (29/30 VALID_TARGET; 96.67%)
FORMAL_SEED_QUEUE: PREPARED; 100 fresh train targets; NOT_LAUNCHED
PRODUCTION_CODE_CHANGED: NO
MODEL_TRAINED: NO
NEXT_STEP: later start the proposed 100-target formal human seed batch
STOP
```

## Stage 0: nomination validity

Every reviewed sample first receives exactly one status. A not-yet-reviewed sample has no Stage-0 record, rather than a guessed status.

| Key/status | Meaning | Class keys |
| --- | --- | --- |
| **V — VALID_TARGET** | You can identify the exact nominated source object(s), and the geometry/ROI has a defensible correspondence to those objects. | Enables 1–4. |
| **X — INVALID_NOMINATION** | Unsupported/floating member, no matching source object, wrong object, spatial misalignment, broken extent or a pair that does not correspond to the source. | Disabled; any previous physical class is removed from the separate V2 decision state. |
| **U — UNCLEAR_TARGET** | The target cannot be determined because the display/overlay is absent, merged, insufficient or ambiguous. | Disabled. |

The automatic queue-quality gate only filters extraction failures. **Passing it does not assign VALID_TARGET.** Only the reviewer's V action creates that status. The store checks the status and its sample digest before accepting a class; pressing 1–4 before V does nothing to the saved labels. Explicit zero-support nominations cannot be marked V by the store. X/U are saved as nomination decisions, not silently turned into OTHER/AMBIGUOUS.

## Stage 1: physical class

Only human-confirmed VALID_TARGET samples can receive:

1. **SINGLE_PHYSICAL_STROKE:** one intended physical/document structural or rule stroke, potentially represented by its two raster edges.
2. **TRUE_PARALLEL_STRUCTURE:** two distinct source-supported structural boundaries that must remain separate.
3. **OTHER:** an explicit, validly nominated source object exists, but it is text/glyph, fill, hatch, graphic, artifact or another non-target object.
4. **AMBIGUOUS:** the target itself is explicit and valid, but its physical class cannot be reliably determined from source/context.

“No source line exists there” is X, never 3 or 4. “I cannot tell what the system nominated” is U, never 4. No expected class, old pilot decision, model prediction or machine validity result is shown as an answer in the UI.

## Exact target display

The UI shows **PAIR / SINGLE / CONTROL**. Pair A is red, B is blue, with 3-screen-pixel paths, visible endpoint dots and separate A1/A2/B1/B2 labels. Single paths are explicitly highlighted and labeled. Controls have an exact connected-ink bounding rectangle and a crosshair outside their pixels. It never asks the reviewer to infer “central ink.” Narrow paths whose overlays would overlap use alternating red/blue display dashes on the unchanged coordinates; 4×/8× zoom shows both raw source pixels and the precise overlaid paths. Display dashes are styling, not a source-ink or geometry modification.

**C** opens source context; **D** opens optional grayscale/geometry/nearest-dark-ink support with pixel distances. Green support dots and distance numbers aid inspection and do not assign any class/status. **F4/F8** or the zoom buttons open 4×/8× local source and target views. **SPACE** skips and **BACKSPACE** undoes. Supplementary windows name their sample and close when advancing, so stale context cannot be mistaken for the next target.

Every presentation, cursor, nomination decision, skip, class and undo is written incrementally using flushed/fsynced atomic JSON replacement. Skips and cursor now survive restart; the append-only review history records session ID and exact queue rank, including revisits/undo. X/U and V are separate from physical class in the label state. Completed decisions use [label-contract-v2.schema.json](label-contract-v2.schema.json); the full persisted state uses [label-state-v2.schema.json](label-state-v2.schema.json), with history/identity/source-support constraints checked by the acceptance auditor.

## Frozen pilot and new files

`labels/local-labels.json` is unchanged byte-for-byte, SHA256:

`1ea4314aa4bd6f58266205e750a92076dc866cbbc2b04bd59b2d9e379868a624`.

Its bound V1 manifest SHA256 is:

`a33a88cdeff760fcb5a360997e723cdf708d5500fb52ce829e9068cf3cf79678`.

`labels/PILOT_LABELS_V1.json` and `labels/PILOT_V1_UNVERIFIED.json` are byte-identical preservation copies. [pilot-freeze.json](pilot-freeze.json) marks all 145 unverified and unauthorized. [pilot-label-disposition.json](pilot-label-disposition.json) retains each original human decision and records automated triage:

| Triage category | Saved labels | Interpretation |
| --- | ---: | --- |
| PILOT_V1_RETAINABLE_CANDIDATE | 37 | Candidate/crop identity unchanged and automated quality checks pass; human Stage 0 is still missing. |
| PILOT_V1_INVALID_NOMINATION | 60 | Strong unsupported-member or severe extent flags; these are quarantine triage, not a guessed human intention. |
| PILOT_V1_UNCLEAR_TARGET | 0 | No saved label falls in the missing-overlay controls; those were left unlabeled. |
| PILOT_V1_NEEDS_HUMAN_REVIEW | 48 | Borderline/support/endpoint/clipping quality issues need review. |

**None of these 145 is training-authorized**, including the 37 retainable candidates. The old human classes are not prefilled in V2. The new UI refuses V1 manifests/label files; benchmark label ingestion refuses the V1 schema; research training commands refuse data without explicit training authorization before importing ML dependencies. This task does not ask the user to relabel all 145. Any later revalidation should begin with unchanged, explicit, quality-passing candidates, retain the original decision separately, and use a fresh human Stage-0 decision.

## Thirty-sample acceptance only

[real-v2-acceptance.jsonl](real-v2-acceptance.jsonl) contains exactly **30** candidates from the same **13 train drawings**, at most three per drawing: 12 PAIR, 4 SINGLE and 14 CONTROL. All start with no Stage-0 status/class and `training_authorized=false`. No validation or blind source was opened. V1 source crops/manifests were not overwritten. External patches are under `C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/real-v2`.

Source-support filtering, full bounded endpoints, matched local extents, and drawing-local geometry/perceptual deduplication are documented in [PILOT-AUDIT.md](PILOT-AUDIT.md). These are dataset-quality operations; production P3A rules and DXF geometry are untouched. New local extents/component ROIs receive new identities, so they never inherit a V1 class silently.

Run [launch-labeling.ps1](launch-labeling.ps1) from PowerShell. It now opens only this V2 acceptance set and saves to **`labels/v2-ui-acceptance.json`**, leaving the 145-label file unchanged. For UI acceptance without physical labeling, press **V then SPACE** for a clear valid target. X/U advance after recording the nomination failure. Class decisions after V are optional at this stage and still do not authorize training.

The frozen human acceptance threshold remains **29/30** targets (≥95%) with defensible source correspondence, understandable V/X/U choices, no Stage-1 entry from zero support and materially reduced duplicate burden. The final human state has **29 V / 0 X / 1 U**, with all 30 presentations persisted and no policy-detected duplicates. All 48 undo actions replay consistently. Earlier X/U decisions revised after explicit undo/review are preserved in the history; none was silently promoted. Stage-1 classes are optional for this acceptance and do not determine the result.

## Prepared first formal seed batch — not launched

[formal-seed-v2-001.jsonl](formal-seed-v2-001.jsonl) contains **100** new, unlabeled quality-gated train nominations: **60 PAIR / 20 SINGLE / 20 CONTROL**, from 13 drawings with a maximum of 10 per drawing. These counts describe nominated targets, not presumed physical classes. All 30 acceptance parent nominations are excluded; the 25 acceptance classes and all 145 quarantined V1 classes are not copied.

The accepted Stage-0/Stage-1 keys, source views, endpoint/ROI display and source-support gates are unchanged. Stronger seed deduplication expands the same-drawing/page comparison radius from 192 to 320 source pixels and the perceptual threshold from 20 to 24 bits, retaining distinct gap/topology safeguards. It compares against acceptance targets as well as the pool, and suppresses exact raster repeats across drawings/types. Selection cycles drawings and target types without model predictions or human-class lookup. Existing train/validation/blind drawing and family boundaries remain byte-identical.

The default acceptance launcher still opens only the original 30. A separate [launch-formal-seed-v2.ps1](launch-formal-seed-v2.ps1) is prepared for a later start and uses a new label file, `labels/formal-seed-v2-001.json`. The formal UI mode verifies the current PASS, frozen split hash and prepared manifest hash. **This launcher has not been executed; that label file does not yet exist.** All training authorization remains false.

Regenerate the bounded queue with `../.venv/Scripts/python.exe -B tools/p3b/prepare_seed_v2.py` from the checkout. Only the 100 selected patch folders are stored under the external `image-to-cad-p3b-cache/real-v2-formal-seed-001`; the full pool remains transient. Once labeling begins, the preparation script refuses to rewrite its assets. [formal-seed-v2-summary.json](formal-seed-v2-summary.json) records identities, source access, deduplication and cache lifecycle.

Validation: preparation and V2 contract tests cover floating partner rejection, extent/clipping checks, all three nomination statuses, class-before-V refusal, zero-support refusal, invalidating a prior class, persistent skip/cursor/undo, V1 preservation/consumer refusal, A/B colors, pixel zoom, duplicate/source protection, and the exact 30-source-boundary set. Test logs are [v2-preparation-tests.txt](v2-preparation-tests.txt) and [v2-contract-tests.txt](v2-contract-tests.txt). Final hashes and checks are in [pilot-v2-verification.json](pilot-v2-verification.json).

No production source/test file, DXF output, OCR observation, validation/blind source or Colab state was changed. No model was trained. STOP.
