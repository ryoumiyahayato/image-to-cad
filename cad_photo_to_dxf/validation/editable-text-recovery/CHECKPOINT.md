# Editable TEXT recovery checkpoint

## Current commit

`6cabd4c test: capture editable-text recovery baseline`

Branch: `fix/non-destructive-editable-text`

Phase 12 baseline:
`baseline/phase12-final-acceptance-2026-07-30` ->
`6f5f69329aabf0bd3a7eda84baf66eb1959bdcba`

## Completed

- Verified the phase 12 tag still points to the original phase 12 commit.
- Created the dedicated repair branch from the current repository HEAD.
- Committed only `validation/uat-page001-failure/`.
- Preserved existing `tmp/` content without modification or staging.
- Recorded the product and implementation contract in this directory.
- Captured the complete pre-change unit-test result: 259 passed, 0 failed.
- Re-ran the formal text-contract set: 10/10 unique real pages passed.
- Audited all 10 newly generated formal-set DXFs.
- Audited all 14 existing user-PDF DXFs without modifying them.
- Recorded per-DXF TEXT, fallback-outline, text-symbol, residual and audit
  counts.
- Implemented the first change set locally: editable emission no longer
  depends on `replacement_safe`; source suppression still does.
- Added explicit `text_emit_eligible`, `source_outline_suppressible`, and hard
  reject fields to every text-output decision.
- Confirmed the 240 DPI fixed failure page now has 206 eligible candidates and
  exactly 206 native DXF `TEXT` entities. The two non-eligible candidates are
  both rejected only for `confidence_below_contract`.

## Not completed

- Commit and post-commit verification of editable TEXT emission and
  outline-suppression decoupling.
- Hidden unsafe source-glyph backup layer.
- Candidate-level semantic ownership.
- Native TEXT geometry fitting.
- Full per-page and per-DXF acceptance.

## Modified files

- `app/text_output_contract.py`
- `app/content_ownership.py`
- `app/ocr_outline_export.py`
- `app/trace_single_export.py`
- `app/trace_document_export.py`
- `tests/test_text_output_contract.py`
- `tests/test_ocr_layout.py`
- validation probe and commit-1 evidence under
  `validation/editable-text-recovery/`

## Tests

- `python -m pytest -q`: 259 passed, 141 warnings, 17.41 seconds.
- Formal text-contract validation: 10/10 documents passed.
- Formal generated-DXF audit: 10/10 passed.
- Existing user-PDF DXF audit: 14/14 passed.
- Commit-1 focused tests: 39 passed, 72 warnings.
- Commit-1 Ruff checks: passed.
- Commit-1 page-001 DXF audit: 0 errors.

## Per-page status

See:

- `before/text-contract.json`
- `before/formal-dxf-inventory.json`
- `before/user-pdf-dxf-inventory.json`

The 240 DPI fixed failure page remains:

- OCR candidates: 208
- native TEXT: 37
- fallback candidates: 169
- residual candidates: 2
- `TRACE_TEXT_SYMBOL` entities: 1406
- DXF audit errors: 0

The local commit-1 probe now reports:

- OCR candidates: 208
- `text_emit_eligible`: 206
- native DXF TEXT: 206
- `source_outline_suppressible`: 37
- unsafe source-outline backups required: 169
- confidence hard rejects: 2
- invalid geometry rejects: 0
- DXF audit errors: 0

Unsafe source glyphs are still visible through the general trace layers in
this intermediate state. Moving them to hidden `SOURCE_TEXT_OUTLINE` is the
next, separate commit.

## Next single safe action

Commit the first change set as
`fix: decouple editable text emission from outline suppression`, then rerun
the same focused tests. Do not start hidden source-outline routing unless the
post-commit tests pass.

