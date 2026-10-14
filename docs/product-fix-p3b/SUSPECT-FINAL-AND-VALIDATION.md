# P3B suspect adjudication and independent validation launch

The completed 13-sample re-review passed schema, source/sample/manifest binding,
presentation and history/undo replay. The current user explicitly authorized its
complete, internally valid decisions to become the current adjudicated view.
Original answers, frozen evidence and independent re-review answers remain
unchanged. The earlier `SUSPECT-REVIEW-V2-001-RESULT` remains a historical report
under the previous unresolved-disagreement rule; it is superseded for current
status by `FORMAL-SEED-FINAL-STATUS.json` and
`formal-seed-adjudicated-decisions.jsonl`.

```text
SUSPECT_REVIEW_RESULT: COMPLETE_VALID_ADJUDICATED
TOTAL_REVIEWED: 13
EXACT_AGREEMENT: 12
STAGE0_DISAGREEMENT: 1
STAGE1_DISAGREEMENT: 0
CONFIRMED_SINGLE: 0
CONFIRMED_TRUE_PARALLEL: 2
CONFIRMED_OTHER: 10
REVISED_TO_SINGLE: 0
REVISED_TO_TRUE_PARALLEL: 0
REVISED_TO_OTHER: 0
REVISED_TO_AMBIGUOUS: 0
REVISED_TO_X_OR_U: 1
```

Stage-1 disagreement compares classes only when both Stage-0 decisions are V.

| Sample ID | Original rank | Original decision | Re-review/current decision | Correspondence reason |
|---|---:|---|---|---|
| real-48f0cee35570a79663988685 | 40 | V / TRUE_PARALLEL_STRUCTURE | X / no class | PAIR_UNEQUAL_EXTENT |

The difference is retained explicitly. Its current resolution is
`ADJUDICATED_RE_REVIEW_ACCEPTED`; it is excluded from the usable seed.

```text
FORMAL_SEED_FINAL_STATUS: PASS
FINAL_READY_SINGLE: 38
FINAL_READY_TRUE_PARALLEL: 20
FINAL_READY_OTHER: 36
FINAL_AMBIGUOUS: 0
FINAL_EXCLUDED: 6
FINAL_TRAINING_READY_TOTAL: 94
DRAWINGS: 13
SOURCE_FAMILIES: 12
DISPUTED_REMAINING: 0
```

The structural classes together have 58 examples; neither is represented by
only a handful. OTHER is 36/94 (38.3%) and does not dominate the usable seed.
Six nominations are excluded, including the new X. The 82 previously accepted
READY records and twelve confirmed re-review records comprise the usable 94.
All retained borderline correspondence cases were explicitly reviewed.
Nomination quality and source diversity are adequate to begin independent
validation labeling, not evidence of classifier safety or production readiness.
No model training is authorized.

Glyph/digit/text/symbol/graphic internal strokes remain OTHER regardless of
their local parallel appearance. They are never reinterpreted as structural
truth.

## Validation queue and provenance

```text
FUTURE_OTHER_PREFILTER: READY
VALIDATION_BATCH_PREPARED: YES
VALIDATION_BATCH_SIZE: 50
VALIDATION_UI_LAUNCHED: YES
PAIR: 22
SINGLE: 23
CONTROL: 5
BLIND_TOUCHED: NO
MODEL_TRAINED: NO
COLAB_STARTED: NO
BACKGROUND_TASKS_CREATED: NO
PRODUCTION_CODE_CHANGED: NO
DXF_CHANGED: NO
OCR_CHANGED: NO
```

Queue: `validation-v2-001.jsonl`. Separate human state:
`labels/validation-v2-001.json`. Plan, page selection, source ownership evidence,
asset hashes and frozen input identity: `validation-v2-001-plan.json`.

| Drawing | Source family | Samples | Nomination pages |
|---|---|---:|---|
| A2-SG-008 | US_NARA_BUILDING9 | 13 | 1 |
| G0R2-22E85E2DB7746A00 | TW_NHRM_GREEN_ISLAND_MEMORIAL_IMPROVEMENT | 12 | 9, 21, 30 |
| G0R2-4DC97797ABE2CB18 | AU_GOLDCOAST_OPW_2014_2240 | 12 | 19 |
| G0R2-99D5B85436EBB965 | US_LOC_HABS_GU0014 | 1 | 1, non-target control only |
| G0R2-F519B357241CAC3A | US_LOC_HABS_UT0288 | 12 | 49, 55 |

Only frozen validation groups were opened. A foreground low-resolution overview
exposed 146 pages of these five validation documents to select drawing contexts;
nomination extraction used eight pages. No blind source was opened, rendered,
hashed or labeled. Historical train labels were used only to establish train
PASS; they and predictions are absent from the validation presentation and
nomination selection.

The source-blind nomination, local alignment and frozen V2 quality gates were
reused without changing production P3A. Selection balances source/target-type
coverage, not inferred physical classes or model errors. All fifty raw/overlay
targets were visually inspected before sealing. Context includes walls,
enclosures, openings, junctions, table and frame rules. Five source-diverse
controls retain non-target coverage; the archival photo-list text page supplies
one control only. No physical validation class has been preassigned.

Effective render DPI is 110 for 37 PDF samples. Thirteen native TIFF samples
have unknown physical DPI. This initial batch does not yet establish robustness
across multiple known DPIs; scan DPI is not invented to claim such coverage.

The glyph prefilter removes candidates only when all their nominated members
are supported almost entirely by **exclusive source-native text ink**. A temporary
in-memory no-text render measures ink contribution; it does not edit/save the
source. Ink remaining dark after text removal, including structural boundaries
crossing text, is not owned by glyphs. Invisible OCR contributes no ownership.
Spatial text-box proximity and raster image-object membership are never used.
Available explicit text ownership occurs on three selected native-PDF pages;
other scanned-page ownership remains unknown and unfiltered. No candidate in
this gated extraction pool met the exclusive-glyph removal test; do not claim
bulk removal that did not occur. The inspected batch avoids obvious glyph-pair
flooding and retains only five curated controls. Explicit trusted graphic
ownership was not available on these sources; no new graphic/OCR inference was
introduced.

Whole drawing/family/source separation and global exact input leakage checks
passed against the train pool. Deduplication used the accepted stronger
320-pixel/24-bit local threshold while protecting distinct pair gaps/topology;
one exact and one near repetition were removed from the 494-candidate pool.
The final 50 contain no exact/near duplicate nominations under that policy.
Source SHA256, every displayed asset and crop pixels are checked before launch
and resume. Original formal-seed and suspect state hashes remain unchanged.

## Human workflow and manual completion

The visible controls are:

- 1: one physical line.
- 2: two real structural lines.
- 3: not a line-structure target, including text/digits/glyphs/symbols/graphics/fills.
- 4: target is clear, but physical class is genuinely uncertain.
- X: bad nomination.
- U: unclear target display.

Pressing 1–4 asserts a clear, source-supported nominated target. Internally the
UI persists Stage-0 V **before** persisting Stage-1 class; both records retain
human, sample, source and manifest provenance. X/U never acquire a physical
class. A crash between the two saves leaves V incomplete and resumable. Every
presentation, cursor, status, class, deliberate skip and undo is immediately
saved with atomic replacement and fsync. Close pauses; reopen resumes the same
queue/state. No V1 or acceptance labels are imported.

PAIR A/B colors/endpoints, 4x/8x zoom, context and source-support diagnostics use
the accepted visualization. Neither train labels nor model predictions appear.
SPACE is only a deliberate incomplete skip; it must not become a routine path.

The 50-sample interactive UI was actually launched in the foreground. At the
end it offers **Finish & audit**, a human-invoked one-time audit button. There is
no timer, polling loop, watcher, recurring task or automatic training. Closing
without that button preserves answers; the same audit can be invoked manually:

```powershell
../.venv/Scripts/python.exe -B tools/p3b/validation_review.py --audit
```

The audit refuses incomplete or inconsistent state. It reports reviewed/ready/
excluded, the four classes, drawings/families, DPI and per-source/type breakdowns
in `VALIDATION-V2-001-AUDIT.json/.md`, then stops. Training requires a later
explicit instruction.

Resume only this frozen batch:

```powershell
../.venv/Scripts/python.exe -B tools/p3b/validation_review.py --launch
```

Run from the `instrumented-e03` checkout; do not open a second copy while its UI
is running. All generated raster/channel/preview data are outside the checkout
in `C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/validation-v2-001`. Preserve this
batch's asset identity while labeling; regenerable preview/cache data are not
permanent Git arrays. Manifests, scripts, labels and small audit results remain
in the project.

Verification: five new ownership/split/direct-key/crash/resume tests passed,
including an explicit glyph intersected by a real source boundary; nine existing
V2 contract tests passed. Ruff passed on affected tooling. All 157 production
app/test files match the retained production snapshot. P1/P2B/P3A regressions:
unchanged, no production output rerun. STOP after human validation audit.
