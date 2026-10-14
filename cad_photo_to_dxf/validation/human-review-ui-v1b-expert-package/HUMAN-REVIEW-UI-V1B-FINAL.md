# HUMAN-REVIEW-UI-V1B-EXPERT-PACKAGE

Status: COMPLETE

This checkpoint adds a portable, static, prediction-blind Reviewer-B package
for the exact 24 frozen Local-E1 candidates. Reviewer A remains a separate
provisional observation; no Reviewer-A runtime state or export is used as
package input, copied into the package, or merged with Reviewer B.

## Implemented files

- `cad_photo_to_dxf/app/expert_review_package.py` — reusable package builder,
  clean evidence regeneration, neutral marker metadata, static HTML template,
  package validation, and ZIP creation.
- `cad_photo_to_dxf/tools/build_expert_review_package.py` — one-command package
  generator.
- `cad_photo_to_dxf/tests/test_expert_review_package.py` — focused package,
  asset, blinding, offline, ZIP, and fresh-session tests.

The package builder reads only the frozen E1 manifest/order, the Local-D frozen
candidate set, and the existing unmarked Local-D source renders. The E1 crop
images contain baked-in candidate graphics, so clean LOCAL and CONTEXT images
were regenerated from the same frozen crop boxes and source renders. Candidate
IDs, order, and geometry were not changed.

## Runtime package

Package directory:

`C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\expert-review-package-v1`

ZIP:

`C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\expert-review-package-v1.zip`

The ZIP contains `review.html`, `README.txt`, `manifest.json`, and 24 clean
LOCAL plus 24 clean CONTEXT PNGs. It contains no original DWG, PDF, or DXF.
Opening `review.html` after extraction requires no Draftsman, Python, Git, or
network.

The package starts a new Reviewer-B browser session at 0/24. Browser
localStorage provides local resume/autosave; `导出审核结果 JSON` produces the
authoritative JSON result for return to the project owner. Import validates
schema, manifest identity, and candidate IDs and warns before importing an
already-labeled result from another reviewer.

## Blind review behavior

The default view is CLEAN and shows unobscured source evidence side by side.
MARKED and CLEAN + MARKED COMPARISON are optional view modes. Markers are thin
semi-transparent SVG guides for Fragment A, Fragment B, Gap endpoint A, and
Gap endpoint B; no completed bridge is drawn. A visible legend explains every
marker. The package includes no Reviewer-A labels, notes, history,
completion counts, agreement data, model fields, expected labels, ranking, or
confidence values.

The four exported human-label values are exactly:

- `STRUCTURAL_CONTINUATION`
- `ANNOTATION_OR_GLYPH`
- `AMBIGUOUS`
- `INVALID_FOR_TASK`

Chinese guidance, the neutral primary review question, optional reviewer
identity fields, keyboard shortcuts 1/2/3/4, navigation, notes, zoom/pan,
and result export are included. The result schema represents one reviewer
observation per candidate and does not implement adjudication.

## Verification

Focused automated test:

`C:\Users\agcrf\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest -v tests.test_expert_review_package`

Result: 8 tests passed. The tests cover 24 clean pairs, exact labels, clean
default state, optional markers and legend, Reviewer-A/full-source exclusion,
offline/static resource checks, neutral order/marker geometry, fresh unlabeled
session, and ZIP contents.

The existing reusable review-session test suite also remains unchanged and was
run separately. The actual package was opened in the local in-app browser via
a temporary loopback server because the browser policy blocks direct
`file://` navigation and the bundled Node environment has no Playwright
module. The smoke test verified page identity, 0/24 initial state, both clean
views, marker toggle and legend, comparison mode, zoom to 125%, keyboard label
save/advance, note and reviewer metadata persistence after reload, and JSON
export status. The smoke copy and temporary state were removed afterward; the
distributed package remains at 0/24.

## Governance

```text
EXPERT_REVIEW_PACKAGE: CONTROLLED_EXTERNAL_REVIEW_ONLY
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
PRODUCTION_SEMANTIC_DELTA: NONE
MODEL_RUN: NO
MODEL_ASSISTED_LABELING: NO
GROUND_TRUTH_FROZEN: NO
DATASET_FROZEN: NO
PRODUCTION_GUI_INTEGRATED: NO
VALIDATION: NO
LOCKED_BLIND: 0 / 8
```

Future PySide6 integration can reuse the package manifest vocabulary and
independent-review result schema without reusing the browser presentation or
coupling to production processing code.

DIAGNOSTIC CHECKPOINT: RECORDED BY THE IMPLEMENTATION COMMIT
