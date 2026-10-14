# Image to CAD preservation evidence

The historical generation provenance of `preservation-baseline.json` is
**UNPROVEN / UNKNOWN**. Its first Git addition was
`26ad39e44755473c29723ece07efd3f3209f814c`. Addition time and reproduced equality
cannot establish which code snapshot originally generated it. Keep the file:
`maintenance/preservation_check.py` checks current compact regression values
against it, not independently established historical PRE execution.

Subsequent verification in `historical-verification-20261005` rebuilt PRE
evidence using actual `git archive` exports of
`4a8031eb14ec136ab71cbe3c66a7a46e1198d1af` and
`fb42639d87aac71a20aa6bbd0ed218d540b84833`, executing each in a separate Python
process. The modern ProductionProcessingService exactly matched for
`processing-contract-page`, `sample-test` and `reconciliation-gap-junction`
with the same inputs, 300 DPI, OCR off and the same processing options.

Measured matches include page dimensions, every straight-line coordinate,
contour points and hierarchy, text/logo/signature objects, masks, provenance,
structure IDs, cache keys/digests, raw NPZ arrays and DXF geometry (excluding
file-local handles/owners). ezdxf audit errors and fixes were zero. These
OCR-off inputs have empty text collections. The evidence is bounded to these
inputs/settings and cannot prove all OCR output or mathematical equivalence
for all engineering drawings.

[historical-verification-summary.json](historical-verification-summary.json)
retains the necessary small results. Neither runtime nor tests read the
external verification directory or this summary. No manifest or new gate was
introduced. Git revisions identify developer snapshots, not product versions.

Independent verification also reproduced the current scan-underlay export:
one LINE, one TEXT and one linked scan IMAGE, with an underlay file and zero
audit errors. The gap was regression coverage; the closeout test now invokes
the current `export_final_structure_dxf` API with `raster_image` and checks all
of these results, including the linked image filename.

`TEST_ONLY_PRODUCTION_MODULE` means a Python implementation module inside
`cad_photo_to_dxf/app` that is unreachable from every supported production
entry but imported/used by tests. Package initializers and files in `tests/`
are excluded. The current count is zero. The six supported diagnostics are
`debug_bundle`, `observability`, `performance_observability`,
`source_support_lifecycle`, `trace_verification` and `visual_acceptance`;
their explicit command, GUI entry or runtime opt-in makes them
`OPTIONAL_PRODUCTION_DIAGNOSTICS`, not test-only modules.
