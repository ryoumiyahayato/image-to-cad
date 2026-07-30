# Editable TEXT recovery checkpoint

## Current commit

`185d44b refactor: preserve unsafe source glyphs as hidden text outlines`

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
- Committed the first change set: editable emission no longer
  depends on `replacement_safe`; source suppression still does.
- Added explicit `text_emit_eligible`, `source_outline_suppressible`, and hard
  reject fields to every text-output decision.
- Confirmed the 240 DPI fixed failure page now has 206 eligible candidates and
  exactly 206 native DXF `TEXT` entities. The two non-eligible candidates are
  both rejected only for `confidence_below_contract`.
- Committed the second change set: eligible unsafe source glyphs are
  routed to `SOURCE_TEXT_OUTLINE`, and that layer is default-off in single and
  multi-page DXF exports.
- Reclassified OCR hard rejects as visible `TEXT_FALLBACK_OUTLINE`; truly
  unsupported non-text candidates remain `RESIDUAL_GRAPHIC`.

## Not completed

- Candidate-level semantic ownership.
- Native TEXT geometry fitting.
- Full per-page and per-DXF acceptance.

## Modified files

- Checkpoint evidence only. The production-code worktree is clean after
  commit `185d44b`.

## Tests

- `python -m pytest -q`: 259 passed, 141 warnings, 17.41 seconds.
- Formal text-contract validation: 10/10 documents passed.
- Formal generated-DXF audit: 10/10 passed.
- Existing user-PDF DXF audit: 14/14 passed.
- Commit-1 focused tests: 39 passed, 72 warnings.
- Commit-1 Ruff checks: passed.
- Commit-1 page-001 DXF audit: 0 errors.
- Commit-1 post-commit focused tests: 39 passed, 72 warnings.
- Commit-1 post-commit Ruff checks: passed.
- Commit-2 focused tests: 50 passed, 66 warnings.
- Commit-2 Ruff checks: passed.
- Commit-2 page-001 DXF audit: 0 errors.
- Commit-2 post-commit focused tests: 50 passed, 66 warnings.
- Commit-2 post-commit Ruff checks: passed.

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
the commit-1 intermediate state.

The local commit-2 probe now reports:

- OCR candidates: 208
- `text_emit_eligible`: 206
- native DXF TEXT: 206
- hidden source-outline backup candidates: 169
- `SOURCE_TEXT_OUTLINE` entities: 1393
- `SOURCE_TEXT_OUTLINE` default visible: false
- visible fallback candidates: 2
- `TEXT_FALLBACK_OUTLINE` entities: 535
- fallback layer default visible: true
- residual candidates/entities: 0/0
- `TRACE_TEXT_SYMBOL` entities: 1406
- DXF audit errors: 0

The remaining `TRACE_TEXT_SYMBOL` count is expected at this checkpoint; the
next independent commit must remove eligible-candidate source pixels from that
primary semantic without deleting unrelated structure.

## Next single safe action

Add candidate source/ownership masks to the immutable `FinalStructure` and use
those masks to prevent eligible candidate pixels from being emitted as visible
`TRACE_TEXT_SYMBOL`, while preserving unrelated structural pixels. Do not
alter native TEXT geometry yet.

