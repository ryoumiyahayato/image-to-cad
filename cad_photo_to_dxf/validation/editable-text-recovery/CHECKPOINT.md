# Editable TEXT recovery checkpoint

## Current commit

`66a17d7 fix: enforce candidate-level text semantic ownership`

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
- Built candidate-level source masks from existing character boxes, OCR quads,
  or bbox fallback and intersected them with exact source-ink ownership.
- Routed eligible unsafe glyph pixels only to the hidden
  `SOURCE_TEXT_OUTLINE` backup and hard-rejected text pixels only to visible
  `TEXT_FALLBACK_OUTLINE`.
- Removed both semantic outline masks from the general contour input before
  `TRACE_TEXT_SYMBOL`/`TRACE_CURVE` classification.
- Preserved the text semantic masks in the immutable `FinalStructure`, the
  processing and GUI rebuild paths, the trace cache, and single/multi-page
  DXF export.
- Confirmed candidate primary-semantic uniqueness and exact source-pixel
  conservation on the 240 DPI fixed failure page.
- Committed candidate-level semantic ownership as isolated commit `66a17d7`.

## Not completed

- Native TEXT geometry fitting.
- Full per-page and per-DXF acceptance.

## Modified files

- Checkpoint evidence only. The production-code worktree is clean after
  commit `66a17d7`.

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
- Commit-3 focused tests: 37 passed, 72 warnings.
- Commit-3 Ruff checks: passed.
- Commit-3 page-001 DXF audit: 0 errors.
- Commit-3 page-001 candidate-owned eligible/fallback
  `TRACE_TEXT_SYMBOL` objects: 0/0.
- Commit-3 page-001 primary semantic conflicts: 0.
- Commit-3 page-001 source ownership violations: 0.
- Commit-3 post-commit focused tests: 37 passed, 72 warnings.
- Commit-3 post-commit Ruff checks: passed.

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

The local commit-3 probe now reports:

- OCR candidates: 208
- `text_emit_eligible`: 206
- native DXF TEXT: 206
- hidden source-outline backup candidates: 169
- confidence hard rejects / visible fallback candidates: 2/2
- eligible candidate-owned `TRACE_TEXT_SYMBOL` objects/pixels: 0/0
- fallback candidate-owned `TRACE_TEXT_SYMBOL` objects/pixels: 0/0
- candidate primary semantic conflicts: 0
- candidate source ownership violations: 0
- fallback/text-symbol conflicts: 0
- DXF audit errors: 0
- `SOURCE_TEXT_OUTLINE` default visible: false

Thirteen `TRACE_TEXT_SYMBOL` polyline boundaries geometrically touch an
eligible candidate mask edge after vector rasterization (123 boundary pixels),
but their candidate-owned source-pixel count is zero. This adjacency is
recorded separately and is not removed because it may be unrelated table or
symbol geometry.

## Next single safe action

Inspect the existing native TEXT placement and LFF metric code, then add
focused geometry tests for quad center, measured height/width, rotation,
Unicode/editability, and DXF read-modify-save-read before changing production
geometry. Preserve the current page coordinate transform and do not alter OCR
thresholds or any other product scope.
