# HUMAN REVIEW TWO-STAGE V1

## Outcome

The two-stage protocol is complete as a separate successor package to V1C.
V1C remains the predecessor UI and its tracked/runtime package was not
rewritten.  The new package uses the same frozen 24 candidates, neutral order,
clean LOCAL/CONTEXT evidence, optional markers, enlarged image viewer, and
offline static architecture.

Runtime package:

- `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\human-review-two-stage-v1`
- `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\human-review-two-stage-v1.zip`

The generated package contains 24 clean LOCAL views and 24 clean CONTEXT
views, no full DWG/PDF/DXF sources, no human review result, and no model
fields or predictions.  Its new session starts at 0 / 24.

## Protocol

The exported human observation is now:

`Stage 1 pair relationship -> Stage 2 line role (only when SAME_STROKE) -> derived legacy compatibility label`

Stage 1 has exactly:

- `SAME_STROKE`: Fragment A and Fragment B appear to be two portions of one underlying original stroke/path.
- `WRONG_PAIRING`: A and B may both lie on real lines but are not pieces of the same underlying stroke, including separate parallel lines.
- `INSUFFICIENT_EVIDENCE`: LOCAL + CONTEXT, including enlargement, do not support a reliable pairing decision.

Stage 2 is rendered only after `SAME_STROKE` and has exactly:

- `OBJECT_GEOMETRY`: actual engineering/install object geometry;
- `ANNOTATION_LAYOUT`: correctly paired explanatory/layout material such as dimensions, extension/witness lines, leaders, glyphs, tables, title blocks, frames, legends, revisions, or drawing-layout rules;
- `UNKNOWN_ROLE`: same stroke is plausible, but its role cannot be determined reliably.

The raw fields are first-class and remain separate in browser state and JSON:

- `stage1_pair_relation`
- `stage2_line_role`
- `derived_legacy_label`

The compatibility derivation is deterministic and non-authoritative:

| Raw observation | Derived legacy label |
| --- | --- |
| `SAME_STROKE` + `OBJECT_GEOMETRY` | `STRUCTURAL_CONTINUATION` |
| `SAME_STROKE` + `ANNOTATION_LAYOUT` | `ANNOTATION_OR_GLYPH` |
| `SAME_STROKE` + `UNKNOWN_ROLE` | `AMBIGUOUS` |
| `WRONG_PAIRING` | `INVALID_FOR_TASK` |
| `INSUFFICIENT_EVIDENCE` | `AMBIGUOUS` |

The reviewer never directly chooses a legacy flat-four value.  Stage 2 is
forced to `null` for `WRONG_PAIRING` and `INSUFFICIENT_EVIDENCE`.

## Implementation

Tracked implementation files:

- `cad_photo_to_dxf/app/human_review_two_stage_v1.py`
  - reuses the V1C shell and clean-crop/marker pipeline;
  - provides the new protocol UI, storage namespace, session schema, mapping,
    autosave, import/export, and fresh-session action;
  - keeps SVG markers in intrinsic image coordinates for normal and enlarged
    clean/marked views.
- `cad_photo_to_dxf/tools/build_human_review_two_stage_v1.py`
  - reproducible package launcher.
- `cad_photo_to_dxf/tests/test_human_review_two_stage_v1.py`
  - focused vocabulary, gating, mapping, offline, marker, package, and legacy
    preservation checks.

Two-stage browser storage is namespaced separately from V1C and all previous
flat-four sessions.  Existing historical review state/export files were not
read for labels, imported, overwritten, or deleted.  They remain provisional
and non-authoritative.

## Verification

Focused automated checks passed:

- two-stage package tests: 8 passed;
- V1C package tests: 8 passed;
- existing V1B package and generic review-session regression tests: 15 passed;
- Python compilation of the two-stage module, launcher, and tests: passed;
- package build: 24 candidates, 24 clean LOCAL, 24 clean CONTEXT;
- generated ZIP: package-only contents with no DWG/PDF/DXF or review state/export.

A temporary loopback browser session was used because the configured frontend
Browser plugin was not available and direct `file://` navigation is blocked by
the in-app browser.  The rendered smoke test verified:

1. fresh session shows 0 / 24 with only the three Stage-1 buttons;
2. `SAME_STROKE` reveals Stage 2;
3. `OBJECT_GEOMETRY` advances and derives `STRUCTURAL_CONTINUATION`;
4. `WRONG_PAIRING` skips Stage 2 and derives `INVALID_FOR_TASK`;
5. `INSUFFICIENT_EVIDENCE` skips Stage 2 and derives `AMBIGUOUS`;
6. clean evidence, optional markers, enlarged marker toggle, zoom, and pan
   remain available;
7. export status appears, reload resumes the three temporary decisions, and
   a fresh-session reset returns to 0 / 24;
8. browser console errors/warnings were empty.

The temporary server, package copies, and smoke-test state were removed.  The
real generated package remains blank and ready for human review.

No model, OCR semantic classifier, candidate miner, adjudication, dataset
freeze, validation, or production GUI integration ran.

PRODUCTION_SEMANTIC_DELTA: NONE

LEGACY_FLAT_FOUR_REVIEWS: PRESERVED_AS_PROVISIONAL
REVIEW_PROTOCOL: TWO_STAGE_HUMAN_REVIEW_V1
EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
