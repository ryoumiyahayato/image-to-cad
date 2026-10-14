# HUMAN-REVIEW-UI-V1

Status: COMPLETE

This checkpoint adds a small reusable localhost human-review surface for the
frozen Local-E1 review package. It does not modify candidate identity, E1
metadata, production GUI behavior, or production processing semantics.

## Input and runtime boundaries

- Frozen input manifest:
  `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\cad_photo_to_dxf\validation\user-supplied-human-review-v2-local-e1\human-review-manifest.json`
- Frozen input order:
  `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\cad_photo_to_dxf\validation\user-supplied-human-review-v2-local-e1\review-order.json`
- Review items: 24
- Initial real-session labels: 0
- Mutable state:
  `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\user-supplied-human-review-v2-local-e2\review-state.json`
- Server-side export:
  `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\user-supplied-human-review-v2-local-e2\review-export.json`

The launcher verifies the frozen manifest, deterministic order, and all 48
LOCAL / CONTEXT assets before starting. It refuses non-loopback hosts.

## Implemented files

- `cad_photo_to_dxf/app/human_review_session.py` — generic review-item/session
  contract, exact four-label vocabulary, atomic state persistence, resume,
  label-change history, counts, and label-only export.
- `cad_photo_to_dxf/app/human_review_server.py` — standard-library localhost
  HTTP adapter with safe E1 asset serving and JSON mutation/export endpoints.
- `cad_photo_to_dxf/app/human_review_ui.py` — self-contained vanilla browser
  UI with side-by-side LOCAL / CONTEXT views, responsive layout, modal zoom /
  pan, Chinese guidance, four large label controls, notes, navigation,
  progress counts, autosave, resume, and export.
- `cad_photo_to_dxf/tools/launch_human_review.py` — E1 verification, state
  directory setup, localhost server startup, browser opening, and URL/path
  reporting.
- `cad_photo_to_dxf/tests/test_human_review_session.py` — focused dependency-
  free session, manifest, persistence, export, and HTTP adapter tests.

No source-derived images, DWG/PDF/DXF files, runtime state, or review labels
from this implementation are tracked.

## Launch

From any directory, run the bundled-runtime command:

```text
C:\Users\agcrf\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\cad_photo_to_dxf\tools\launch_human_review.py
```

Use `--no-browser` for a terminal-only server, `--port 0` to select an open
loopback port, or `--check-only` to verify E1 without creating mutable state.

## Prediction-blind behavior

The browser-facing review records expose paired asset URLs, review item IDs,
current human state, and counts by the four allowed labels. They do not expose
or compute predictions, model scores, uncertainty, ranking hints, or prior
model results. The UI never inserts a label into a new session; labels are
written only after a human button or keyboard action.

The review order is the exact order from `review-order.json`. The primary
presentation hides source-family/provenance metadata while preserving the item
ID for traceability.

## Verification

Focused test command:

```text
C:\Users\agcrf\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest -v tests.test_human_review_session
```

Result: 7 tests passed. Coverage includes exact vocabulary enforcement,
invalid-label rejection, initial unlabeled state, save/reload/resume, label
change history, note persistence, completion/pending counts, item identity,
E1 24-item / 48-asset loading, HTTP mutation, and no model fields in the
browser-facing item record.

Additional checks:

- Python compilation passed for the new core, server, UI, launcher, and test.
- `launch_human_review.py --check-only` verified 24 E1 items and 48 assets.
- A temporary localhost smoke session loaded in the Codex in-app browser;
  both image pairs rendered, keyboard `3` saved and advanced to the next
  pending item, a note survived reload, the image modal zoom changed to 125%,
  and `导出审核结果` reported `1/24`.
- The smoke state was removed afterward. The real E2 state directory remains
  absent, so the user’s actual review begins at 0/24.
- `git diff --check` passed.

## Governance

```text
PRODUCTION_SEMANTIC_DELTA: NONE
PRODUCTION GUI INTEGRATED: NO
MODEL RUN: NO
MODEL-ASSISTED LABELING: NO
CANDIDATE MINING: NO
HUMAN LABELS ASSIGNED BY CODE: 0
EXTERNAL NETWORK REQUIRED: NO
VALIDATION: NO
LOCKED_BLIND: 0 / 8
```

The UI is ready for the operator’s manual Local-E2 review. Dataset freeze,
model training, model bake-off, validation, and production integration remain
separate future tasks.
