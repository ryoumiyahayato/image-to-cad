# Editable TEXT recovery checkpoint

## Current commit

`c7269b1 test: validate editable text recovery on every page`

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
- Replaced the fixed 0.78 TEXT height and heuristic baseline offset with
  measured LFF visible bounds, metric-centered placement, and exact OCR
  quad-derived width, height, center and rotation.
- Added an explicit, auditable Qt tight-bounds fallback for installations where
  the bundled LibreCAD LFF is unavailable.
- Added `OCR_TEXT_GEOMETRY` XDATA to every native TEXT with metric source,
  target bounds, rendered bounds, center error, rotation and width factor.
- Added focused Chinese, English, digit, punctuation, rotated-text,
  read-modify-save-read and multi-page coordinate tests.
- Confirmed the project and installed LibreCAD `wqy-unicode.lff` files are
  byte-identical.
- Opened the generated DXF in the target Windows LibreCAD, edited one native
  TEXT directly, saved it, and confirmed with ezdxf that the entity and Unicode
  content remained editable TEXT after another read-save-read cycle.
- Strengthened `SOURCE_TEXT_OUTLINE` to both off and frozen because the target
  LibreCAD rewrites the negative off color when saving but preserves freeze.
- Committed the isolated native TEXT geometry change as `fc6cd80`.
- Re-ran the focused geometry and contract tests against the committed tree;
  all 32 passed and Ruff reported no issues.
- Inventoried 27 independent acceptance runs: every page of both user source
  PDFs, every distinct formal real-regression input/DPI variant, the 240-DPI
  fixed failure page, and the perspective-photo page.
- Added a resumable validation harness which writes the required routing,
  geometry, entity, layer-isolated render, default-view, DXF and review
  artifacts independently for every run.
- Ran the perspective-photo smoke page. It passed all 16 page-local checks,
  retained exactly 172 protected straight lines, left its forbidden open-space
  annotation at zero added pixels, emitted 2/2 eligible native TEXT entities,
  hid both unsafe source-outline backups, and passed DXF edit/save/re-read.
- Corrected the validation inventory after proving that five formal environment
  PNG fixtures are not byte-identical to direct renders of the same PDF pages;
  those fixtures are now independent runs rather than aliases.
- Completed 33/33 independent final page/DXF validations:
  every page of both user source PDFs, all distinct formal input/DPI variants,
  the 240-DPI fixed failure page, and a 300-DPI same-input comparison with the
  historical `d9fbda7` DXF.
- Across all final pages, 4,441 OCR candidates produced 4,394 eligible native
  TEXT entities and 47 confidence-only uncertain outlines. Invalid-geometry
  rejects, residual OCR candidates, eligible candidate-owned text-symbol
  objects, semantic conflicts, ownership violations, visible duplicates, and
  DXF audit errors are all zero.
- Confirmed current 300-DPI page-001 editability is not lower than `d9fbda7`:
  219 native TEXT versus 214. Current straight-line output is 651 versus the
  historical 986, so the old whole-page line overproduction is not restored.
- Ran the complete unit suite: 272 passed. Ran Ruff against application, tests
  and recovery validation code: passed.
- Committed all 33 independent page/DXF reports and the full validation harness
  as `c7269b1`.
- Re-read, saved and re-read every one of the 50 DXFs created or retained by
  this task: 33 final pages, 10 before snapshots, 3 intermediate checkpoints
  and 4 verification/LibreCAD checkpoints. All 50 passed.
- Generated the required final delivery files: README, implementation
  contract, before/after summary, per-page index, page-001 comparison,
  entity-type audit, semantic-ownership audit, JUnit results, Git sequence and
  completion status.
- The final completion report evaluates every required condition as PASS.

## Not completed

- Commit the verified final aggregate delivery reports, record the post-commit
  Git status, and stop.

## Modified files

- Final aggregate reports, final-delivery builder encoding/index corrections,
  report-builder logs, Git status evidence, and this checkpoint. No production
  code is modified.

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
- Commit-4 focused tests: 32 passed, 120 warnings.
- Commit-4 Ruff checks: passed.
- Commit-4 page-001 DXF audit: 0 errors.
- Commit-4 page-001 geometry XDATA: 206/206 native TEXT entities.
- Commit-4 page-001 LFF metric fallback count: 0.
- Commit-4 page-001 rendered-height ratio: 1.0 within floating-point tolerance.
- Commit-4 page-001 maximum center/rotation error: 0.0/0.0.
- Commit-4 LibreCAD edit-save and ezdxf read-save-read audit: passed.
- Commit-4 post-commit focused tests: 32 passed, 120 warnings.
- Commit-4 post-commit Ruff checks: passed.
- Full-validation harness PyCompile: passed.
- Full-validation harness Ruff: passed.
- Full-validation manifest inventory: exactly 27 unique run IDs.
- Perspective full-page smoke acceptance: passed in 10.876 seconds.
- Full final-page acceptance: 33/33 passed.
- Full final-DXF page-local read/edit/save/read: 33/33 passed.
- Aggregate candidates / eligible native TEXT: 4,441 / 4,394.
- Aggregate confidence hard rejects / invalid geometry: 47 / 0.
- Aggregate eligible text-symbol / semantic conflicts / ownership violations:
  0 / 0 / 0.
- Full unit tests: 272 passed, 195 warnings.
- Full Ruff check: passed.
- Task DXF read-save-read inventory: 50/50 passed.
- Final completion checks: 13/13 passed.

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

The local commit-4 probe now reports:

- OCR candidates: 208
- `text_emit_eligible`: 206
- native DXF TEXT: 206
- confidence hard rejects / invalid geometry rejects: 2/0
- eligible candidate-owned `TRACE_TEXT_SYMBOL` objects/pixels: 0/0
- primary semantic conflicts / ownership violations: 0/0
- native entity types: 206 TEXT, no glyph polylines
- LFF visible-bounds metric records: 206
- LFF metric fallbacks: 0
- rendered glyph height / OCR target height: 1.0
- TEXT center error / rotation error: 0.0/0.0
- width factor range: 0.72 to 3.1758620689655164
- width factors below 0.60: 0
- DXF audit errors: 0
- `SOURCE_TEXT_OUTLINE`: off and frozen

The anti-compression lower bound is intentionally applied when OCR content and
its clipped geometry are inconsistent. Those cases remain native TEXT and may
extend beyond the target box rather than being squeezed into an unreadable
width. The per-entity raw and applied width factors are retained in geometry
XDATA and will be listed in the full per-page reports.

The first full-validation page now reports:

- run: `perspective-sample-plan-096dpi`
- OCR candidates / eligible / native TEXT: 2 / 2 / 2
- hidden source-outline backup candidates / entities: 2 / 27
- eligible candidate-owned `TRACE_TEXT_SYMBOL` objects/pixels: 0 / 0
- primary semantic conflicts / ownership violations: 0 / 0
- default-visible duplicate representations: 0
- native TEXT geometry and editable read-save-read: passed
- formal straight lines: 172 observed / 172 expected
- forbidden connection added pixels: 0
- DXF audit errors: 0

The fixed 240-DPI failure page now reports:

- OCR candidates: 208
- eligible/native TEXT: 206/206
- confidence hard rejects: 2
- invalid geometry rejects: 0
- hidden source-outline backup candidates: 169
- eligible candidate-owned text-symbol / semantic conflicts: 0/0
- visible duplicate representations / DXF audit errors: 0/0

The same page at the historical saved-DXF resolution reports:

- current 300-DPI OCR candidates / eligible/native TEXT: 219/219/219
- `d9fbda7` native TEXT: 214
- current / historical straight lines: 651/986
- both DXF audits: 0 errors

## Next single safe action

Commit only the verified final delivery reports and checkpoint evidence. Then
record the post-commit Git status and stop. Do not begin colors, automatic line
repair, Logo/signature work, OCR threshold changes, baseline recording or any
other task.
