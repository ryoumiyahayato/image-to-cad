# FRESH DEV CANDIDATE REMINING V1 — FINAL

This report records a deterministic DEV-only remining after DIRECT_CONTINUATION_ADMISSIBILITY_V1 and PRIMITIVE_SPAN_SUPPORT_INTEGRITY_V1. It does not modify production semantics and does not perform human review.

## Pipeline order

SOURCE → DEV raw Hough primitives → SPAN_INTEGRITY_SUPPORTED only → geometric A/B proposal → DIRECT_CONTINUATION_ADMISSIBLE only → duplicate exclusion → deterministic source/geometry diversity selection.

Uncertain and rejected span primitives and direct-continuation pairs remain in ignored runtime audit records and never enter the ordinary admissible pool.

## Funnel

AUTHORIZED ELIGIBLE SOURCE UNITS: 16
SOURCE UNITS ACTUALLY MINED: 16
PAGES / VIEWS CONSIDERED: 16
RAW HOUGH PRIMITIVES: 26201
SPAN_INTEGRITY_SUPPORTED: 22679
SPAN_INTEGRITY_UNCERTAIN: 2412
SPAN_INTEGRITY_REJECTED: 573
RAW PAIR PROPOSALS: 467
DIRECT_CONTINUATION_ADMISSIBLE: 149
DIRECT_CONTINUATION_UNCERTAIN: 0
DIRECT_CONTINUATION_REJECTED: 318
OLD FROZEN EXACT DUPLICATES REMOVED: 0
OLD FROZEN NEAR-DUPLICATES REMOVED: 0
NEW-POOL DUPLICATES REMOVED: 2
FRESH ADMISSIBLE POOL: 147
FRESH REVIEW SET: 24
FRESH_POOL_INSUFFICIENT: NO

## Mechanical OLD LOCAL-D versus FRESH REMINE V1 comparison

| Metric | OLD LOCAL-D | FRESH REMINE V1 |
|---|---:|---:|
| Raw proposal count | 480 | 467 |
| Ordinary admissible count | 225 | 147 |
| Uncertain count | 0 | 0 |
| Rejected count | 96 | 318 |
| Duplicate rate | 0.33125 | 0.004283 |
| Source-family coverage | 10 | 10 |
| Source-unit coverage | 16 | 16 |
| Orientation distribution | `{"horizontal": 15, "vertical": 9}` | `{"horizontal": 12, "vertical": 12}` |
| Gap-length distribution | `{"LONG": 8, "MEDIUM": 11, "SHORT": 5}` | `{"LONG": 10, "MEDIUM": 5, "SHORT": 9}` |

OLD LOCAL-D ordinary admissible count is its tracked 225-record post-dedup pool; its 96 rejected proposals are legacy geometry-filtered records and its retained coverage/distributions are available only for the frozen 24. FRESH REMINE V1 ordinary admissible count is the 147-record post-guard, post-dedup pool; its rejected count is the current direct-continuation rejected count and its coverage/distributions are from the selected 24.

The comparison is mechanical. Before human review, it does not establish semantic precision or accuracy. The fresh path is structurally more selective only in the sense represented by its explicit span/direct status counts and duplicate accounting.

## Frozen set and review package

CANDIDATE SET ID: FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504
SELECTION DIGEST: 5ea8aae98504f6a1c49ac90737f52fc08589d17e175f396163d0e7e4ea281486
SELECTION CODE VERSION: FRESH_DEV_CANDIDATE_REMINING_V1_CODE_1
SOURCE FAMILIES REPRESENTED: 10
SOURCE UNITS REPRESENTED: 16
PDF-DERIVED: 21
DWG-DERIVED: 3
HORIZONTAL: 12
VERTICAL: 12
SELECTION DETERMINISTIC REPLAY: PASS
RUNTIME REVIEW PACKAGE: C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\fresh-dev-candidate-remining-v1\review-package
TRACKED REPORT: C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\cad_photo_to_dxf\validation\fresh-dev-candidate-remining-v1\FRESH-DEV-CANDIDATE-REMINING-V1-FINAL.md

## Governance

- PRODUCTION_SEMANTIC_DELTA: NONE
- SPAN GUARD ACTIVE: YES
- ADMISSIBILITY GUARD ACTIVE: YES
- GUARD WEAKENING: NO
- MACHINE VERDICT EXPOSED TO REVIEWER: NO
- MODEL RUN: NO
- MODEL-ASSISTED LABELING: NO
- MODEL_BAKE_OFF_SHOULD_RESUME: NO
- VALIDATION: NO
- LOCKED_BLIND: 0 / 8
- H1/H2 OPENED: NO
- HUMAN REVIEW: PENDING
- OLD FROZEN CASES REUSED: 0
- OLD NEAR-DUPLICATES REUSED: 0

## Verification

Focused tests: 52 passed, 192 warnings. This includes the fresh remine/freeze/package suite and the existing primitive-span, direct-continuation, line-provenance, and review-package suites. Independent frozen-selection replay: PASS. Runtime review-package validation: PASS.

Source-derived crops, contact sheets, and the static package remain under ignored local-artifacts. No source-derived imagery or human labels are tracked.

FRESH_DEV_CANDIDATE_REMINING_V1: COMPLETE
