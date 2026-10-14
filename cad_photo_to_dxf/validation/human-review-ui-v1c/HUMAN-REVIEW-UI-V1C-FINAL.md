# HUMAN REVIEW UI V1C

## Outcome

V1C is complete as a focused usability correction to the reusable portable
human-review package.  The implementation uses the same frozen 24 E1/Local-D
candidates and clean source-render evidence.  It does not read, copy, merge,
or overwrite the existing Reviewer-A provisional state.

The distributed runtime package is intentionally static and prediction-blind:

- package: `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\human-review-package-v1c`
- ZIP: `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\human-review-package-v1c.zip`
- real package initial state: 0 / 24 labels
- package source disclosure: 24 clean LOCAL views, 24 clean CONTEXT views, and marker geometry only
- full DWG/PDF/DXF source files: not included

## Implementation

Tracked implementation files:

- `cad_photo_to_dxf/app/human_review_v1c_package.py`
  - V1C-specific static HTML variant and package builder
  - reuses the existing frozen E1/Local-D asset/clean-crop pipeline
  - separate corrected-review storage namespace
  - no reviewer identity or reviewer-role controls
  - compact collapsible help and candidate-note control
  - fixed bottom four-label control bar
  - static JSON export/import for the corrected review session
- `cad_photo_to_dxf/tools/build_human_review_package_v1c.py`
  - reproducible package launcher
- `cad_photo_to_dxf/tests/test_human_review_v1c_package.py`
  - focused package, UI, marker, offline, and fresh-session invariants

The V1C browser state is stored under a package/manifest-specific localStorage
key.  “开始新的更正审核” archives the current corrected session under a
separate local history key before creating a new blank session; it does not
delete the earlier session.  The old Reviewer-A state/export hashes remained
unchanged during the build:

- `review-state.json`: `167FE8714E1B91AAF7FE9259E0D8F207C39038119BAA9BFE4AB146751A315AA0`
- `review-export.json`: `A1102F909ABE267FFA0CC0F58A533E7D48235D08992A29EDCA5E313F7E6DB671`

## Review workflow correction

The primary page now keeps the repeated action in view:

1. inspect clean LOCAL and CONTEXT evidence;
2. optionally enable candidate markers;
3. choose label 1 / 2 / 3 / 4;
4. continue to the next pending candidate.

The four exact labels remain unchanged.  The fixed bottom control bar stays
visible while the evidence area is inspected.  Reviewer ID, reviewer role,
reviewer-level note, and an introductory metadata step were removed.  The
candidate note is behind a compact optional disclosure control.

The compact legend states:

- red = Fragment A;
- blue = Fragment B;
- yellow = candidate gap only, not a suggested connection; its endpoints are
  the gap endpoints being evaluated.

The longer explanations remain available under “查看详细说明” and are
collapsed by default.

## Enlarged marker behavior

Clean PNGs are never modified.  When enabled, markers are generated as an
SVG overlay from the manifest’s intrinsic image coordinates.  The enlarged
viewer places the clean image and SVG in the same positioned wrapper, and
scales/translates that wrapper for zoom and pan.  This keeps Fragment A,
Fragment B, and the dashed candidate-gap indicator aligned with the source
through zoom, scroll/pan, resize, and fit-to-window.

The global marker toggle controls the state used when opening an image.  The
enlarged viewer also has its own “显示候选标记” toggle, so clean and marked
views can be compared without closing the viewer.

## Verification

Focused automated checks passed:

- V1C package tests: 8 passed
- existing V1B package and generic review-session regression tests: 15 passed
- Python compilation of the V1C module and launcher: passed
- built package: 24 candidates, 24 clean LOCAL, 24 clean CONTEXT
- generated ZIP: package-only contents; no source DWG/PDF/DXF and no review state/export

A temporary copy was served from loopback for browser smoke testing because
the configured browser backend does not permit direct `file://` navigation.
The visible checks covered page identity, 24-item blank state, side-by-side
evidence, marker toggle, clean/marked enlarged LOCAL and CONTEXT views,
zoom/pan alignment behavior, keyboard label action, candidate-note autosave,
reload resume, and JSON export.  Browser console errors were empty.  The
temporary server, copy, and smoke-test labels were removed; the distributed
package remains blank.

No model, OCR semantic classifier, candidate miner, adjudication, or dataset
freeze ran.  No production PySide6 integration or production semantic code
changed.

PRODUCTION_SEMANTIC_DELTA: NONE

EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
