# IMAGE TO CAD — PRODUCT FIX P3A

Date: 2026-10-06, Asia/Taipei. Base: `20b2247`.

P3A's bounded implementation and audit are complete. The north-arrow
representation passes; stroke/frame reconstruction remains partial. W03 is
still not product-acceptable.

```text
W03_NORTH_ARROW: GRAPHIC
GRAPHIC_OWNERSHIP: PASS (audited W03 families; bounded morphology)
STROKE_MODEL: PARTIAL
LINEWEIGHT_MAPPING: HAIRLINE=0.13, THIN=0.25, MEDIUM=0.50, THICK=1.00 mm
FALSE_PARALLEL_LINES_REMOVED: W03=0; isolated solid-stroke control=1
TRUE_PARALLEL_LINES_PRESERVED: YES
TITLE_BLOCK: PARTIAL
BORDER: PARTIAL
TABLE_RULES: PARTIAL
P1_REGRESSION: PASS
P2B_REGRESSION: PASS
FOCUSED_TESTS: 59 passed
FULL_TESTS: 586 passed
ARCHITECTURE_REOPEN_REQUIRED: NO
NEXT_FAILURE_FAMILY: TEXT_SEMANTIC_ACCURACY
PRODUCT_CODE_CHANGED: YES (presentation/ownership; no OCR semantic changes)
FINAL_AUTOCAD_RC_STILL_REQUIRED: YES
```

## Bounded implementation

Source morphology recognizes an isolated circular perimeter with a substantial,
anisotropic filled interior and no continuing structural component in its halo.
Small detached adjacent source ink may belong to the same object. The detector
uses no direction-name recognition, template dictionary or W03 coordinates.
Ordinary circle/text and box/text compounds fail the filled-core gate; connected
structural context vetoes graphic ownership.

The orientation object uses the established P2B source-mask/opacity mechanism,
relative PNG packaging and native DXF IMAGE. Its paper background is transparent;
source aspect and placement are retained. One object can be moved, scaled,
saved/reopened and deleted. It does not supply structural topology.

Nineteen normal cross-sections sample each supported native line away from its
ends. At least twelve samples and a stable dark-run width are required. Paper or
grey gaps separate runs. Width is measured in source pixels and converted using
the source DPI, rather than a drawing-coordinate multiplier. A brighter
interior between two darker flanks also separates dark-grey-filled boundaries;
the tests cover fills of grey 170, 50 and 10 as well as white paper. A single
anti-aliased stroke has its darker core inside, so edge antialiasing alone does
not establish a filled-wall trough.

| Vocabulary | CAD lineweight | Meaning in DXF |
| --- | ---: | --- |
| HAIRLINE | 0.13 mm | 13 |
| THIN | 0.25 mm | 25 |
| MEDIUM | 0.50 mm | 50 |
| THICK | 1.00 mm | 100 |

The nearest proportional physical width selects one of these four standard
values. The actual source measurement, DPI, support stability and category
remain in presentation metadata. Native LINE carries the standard lineweight;
P3A_STROKE XDATA records the measurement. Geometry is not offset to imitate
thickness. Unmeasured lines keep their existing presentation.

Two detected edges can become one physical centerline only with matching
extents/direction, isolated endpoints, opposite-edge offsets and a stable,
continuous dark core. A source protection mask or shared node vetoes merging.
The physical width cap rejects broad filled regions. Distance alone never
authorizes this decision. These proposals precede the existing reconciliation;
FinalStructure still consumes the original direct mandatory `commit()` gate.
Committed geometry receives only presentation metadata afterwards.

Compact closed, uniform source-filled regions without nested holes or overlapping
printed-text observations can retain native solid HATCH presentation. Long rules,
text, engineering enclosures and patterned/uneven ink are excluded from this fill
proposal. No structural centerline is invented through a fill.

One FinalStructure and the shared single/document DXF writer remain in use.
Presentation metadata participates in cache identity. Final preview renders
the emitted DXF's lineweight, fills and relative IMAGE assets.

## Preservation and tests

The focused suite includes production-path single-thick-stroke and orientation
tests, opposite-edge source evidence, paper/grey-separated parallels, shared-node
and protection vetoes, a double-line shaft/enclosure with a door opening, exact
heavy/thin table nodes, source scale, native fill, cache identity, document export,
IMAGE operations and translated/scaled/rotated morphology. It also runs the
closed P1 and P2B suites and no-closing/topology invariants.

FOCUSED_TESTS: 59 passed (13.22 s).
FULL_TESTS: 586 passed (105.10 s).
RUFF: PASS.

The production thick-stroke example emits one LINE with 0.50 mm lineweight and
zero residual boundary contours. The production orientation example emits one
GRAPHIC IMAGE and zero structural lines/contours. Real P1 W03 parallel rails,
door opening and XY interruption remain exact in their source fixture. P2B
checks preserve W02 M/SL, E01/W02/W03 logos, signature/name separation,
relative packaging and preview/final parity.

No OCR model, training, language model, text candidate contents or 1-to-7
behavior was edited. ODA's Chinese question marks are not OCR evidence.
P2C is paused; no viewer search, installation or font experiment was performed.

## W03 evidence provenance

Source: `warehouse-electrical-vector.pdf`, page 3, production rasterization at
110 DPI, 4764 × 2729 source pixels. Before: the actual closed P2B W03 DXF and
final preview in `local-artifacts/product-fix-p2b/W03`.

The complete original 206 W03 observations are read without alteration from
the retained-history mapping for `product-uat-20261005/W03/texts.json`:

`C:/Users/agcrf/Desktop/image-to-cad-retained-history/storage-cleanup-20261006/project/instrumented-e03/local-artifacts/product-fix-p1/verified/W03/texts.json`

SHA256: `3b3faa1d7759a244fd1f1aa5c7376fa77dc4299bc3a5a0261d1ef2bce5e31b65`.

An initial replay incorrectly used the 16-observation selected test fixture. Its
native-text preservation assertion failed; that replay is excluded from
acceptance. The complete retained observations replace that evidence input.
No text contents were corrected in response.

Reproduce from `cad_photo_to_dxf` with the shared project Python interpreter:

```powershell
& '..\..\.venv\Scripts\python.exe' '..\docs\product-fix-p3a\validate_w03.py' '<retained W03 texts.json path above>'
```

The runner checks text outside the source-owned graphic, the eight existing
P2B asset hashes, relative paths, DXF audit, cache identity and emitted-DXF
preview parity. Only the source-supported orientation label may change from
independent TEXT to pixels inside the whole GRAPHIC object. This is ownership,
not an OCR content correction.

The full production replay took 866.30 s. After adding the final dark-grey
contrast safeguard, the current rule was replayed on all 851 captured MAIN
inputs from the immutable reconciliation input snapshot. The full 958-input
digest and original source raster SHA256 were verified. Even without a
protection mask there were zero merge proposals and every MAIN input remained
exactly unchanged. Current presentation measurements were then refreshed on
the already verified 842 committed lines through the same production function.
This is a captured-input/presentation replay, not a second full reconstruction.
The geometry authority and its mandatory commit gate were not reopened.

## Real W03 result and ownership audit

The orientation object owns source bbox `(3753,163,123,169)`: circular perimeter,
substantial anisotropic filled core, detached adjacent source letter and no
long structural continuation in its scale-bound neighbourhood. The complete
original foreground becomes one transparent GRAPHIC IMAGE. Nine visible
LWPOLYLINE fragments and the independent native `N` become that one object;
the all-layer census removes fourteen polylines including five hidden source
backup pieces. Its move/scale/save/reopen/delete checks pass.

Other audited families retain their source-supported owners:

| Source family | Ownership and representation | Reason |
| --- | --- | --- |
| Orientation emblem | GRAPHIC OBJECT; one IMAGE | Filled directional emblem, isolated from structural topology |
| Company logo | GRAPHIC OBJECT; existing IMAGE | Whole interleaved visual mark; existing P2B source ownership |
| Seven handwriting signatures | GRAPHIC OBJECT; seven existing IMAGE assets | Source signing fields; printed names remain separate |
| Grid bubbles / circle-text compounds | Native CIRCLE and EDITABLE PRINTED TEXT | Simple bounded engineering compounds; no broad anisotropic filled core |
| Walls, doors, shafts, column boundaries, wiring/dash details | STRUCTURAL GEOMETRY; existing native geometry | Continuation, junctions and enclosure context; no unsupported graphic claim |
| Border, title frame and table rules | STRUCTURAL GEOMETRY with measured lineweight | Source rule family; remains native editable geometry |
| Source text backups | SOURCE REFERENCE; existing disabled layer | Preserved outside the owned orientation object |
| Unsupported/ambiguous residual ink | Existing residual/ARTIFACT handling | No new source-supported ownership claim |

No whole title block was converted to IMAGE. No additional complex stamp or
decorative emblem was automatically inferred from W03. The existing logo and
all seven signature PNG hashes are exactly unchanged. Relative paths resolve
for all nine final IMAGE entities; DXF audit has zero errors.

All 842 native LINE coordinates/order and all 13 CIRCLE centers/radii exactly
match the closed P2B package. The other 197 native TEXT contents, insertions,
heights and widths exactly match. The complete original 206 observation records
retain their original hash; only `N` output ownership changes.

819 lines have accepted measurements and 23 remain unmeasured. The final
counts are THIN=468, MEDIUM=323 and THICK=28; HAIRLINE is available but unused
at this source resolution. Source-width counts are 1 px=468, 2 px=315,
3 px=8, 4 px=13 and 5 px=15. At 110 DPI these correspond to approximately
0.231, 0.462, 0.693, 0.924 and 1.155 mm before bounded quantization.

Strict pixel parity passes between the final preview and the actual source-unit
DXF emitted by the shared writer. Every calibrated DXF entity was independently
checked against that source-unit document, including geometry, layers, colors,
lineweights, text/style and IMAGE bytes. Maximum inverse geometry error is
9.095e-13 source pixels. Directly rasterizing the inverse-scaled inspection copy
differs at 66,403 pixels (maximum intensity delta 179) because CAD transformation
normalizes equivalent TEXT angles and QPainter quantizes infinitesimal changes
at integer pixel coordinates. This inverse-raster comparison is recorded rather
than claimed pixel-identical. The final calibrated DXF is not modified to hide
that difference; comparison panels use the actual source-unit emitted DXF.

## Six source / before CAD / after CAD views

Every panel uses the same source crop and physical scale in all three columns.
Counts below are visible emitted entities intersecting each crop; an extending
entity counts once. `L/P` means LINE/LWPOLYLINE. Complete metadata, source
support and width histograms are in [W03-ACCEPTANCE.json](W03-ACCEPTANCE.json).

| View | Entity type / ownership | Source width → CAD lineweight | Geometry count before → after | Source support |
| --- | --- | --- | --- | --- |
| Full sheet | Mixed native geometry, TEXT, IMAGE | 1–5 px → 0.25/0.50/1.00 mm; 23 uncertain | L842/P3570/C13/T198/I8 → L842/P3561/C13/T197/I9 | Original page and per-line cross-sections |
| North arrow | IMAGE / GRAPHIC OBJECT | Original source pixels retained; CAD weight not applicable | P9/T1 → I1 | Isolated ring, filled directional core and adjacent source ink |
| Title block | Native frame/table geometry; separate TEXT and existing IMAGE | 1–5 px; 23 thick, 16 thin, 12 medium, 8 uncertain LINE | L59/P39/T71/I8 → unchanged | Source frame and internal rule family |
| Thick frame rule | Native LINE / STRUCTURAL GEOMETRY | 5 px ≈ 1.155 mm → 1.00 mm | L5 → L5 | 19 stable normal samples; nearby thin rule remains distinct |
| Thin table rule | Native LINE / STRUCTURAL GEOMETRY | 1 px ≈ 0.231 mm → 0.25 mm | L1/P1/T11 → unchanged | 16 stable samples on an internal horizontal table rule |
| True double wall | Native LINE/LWPOLYLINE / STRUCTURAL GEOMETRY | 1–2 px → 0.25/0.50 mm | L10/P25/T1 → unchanged | Separate source rails, enclosure/door context and P1 fixture |

![Full sheet: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/full-sheet-source-before-after.png)
![North arrow: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/north-arrow-source-before-after.png)
![Title block: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/title-block-source-before-after.png)
![Thick rule: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/thick-rule-source-before-after.png)
![Thin table rule: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/thin-table-rule-source-before-after.png)
![True double wall: source / before CAD / after CAD](../../local-artifacts/product-fix-p3a/true-double-wall-source-before-after.png)

## Remaining P3A visual limits

The thick-rule panel still shows paired native frame-edge geometry around one
source rule. Weighting improves filled appearance but can make that retained
pair too heavy. W03 therefore records **zero** false parallel removals, rather
than counting north-arrow contour removal as a stroke repair. The bounded
isolated-stroke control removes one false edge; shared-node and connected-frame
cases remain conservatively untouched to protect P1 junctions and true walls.

Some residual contour rules still have unmeasured width, incomplete joins or
duplicate boundaries. The title frame, border and tables gain heavy/thin
presentation distinction but do not meet full visual acceptance. Pale-grey
column fills and existing hatching remain imperfect; no W03 region passed the
compact uniform-dark-contour fill gate. Native HATCH is verified by the focused
control, not claimed as a solved W03 fill reconstruction. The 110-DPI source
also limits subpixel physical-width estimates.

These are explicit bounded P3A limitations. The drawing is not accepted as an
RC or a product-acceptable result. No OCR semantic diagnosis is inferred from
font rendering, hollow text or ODA question marks.

Review artifacts: [final W03 DXF](../../local-artifacts/product-fix-p3a/W03/drawing.dxf),
[source-unit CAD comparison DXF](../../local-artifacts/product-fix-p3a/W03/source-unit.dxf),
[focused tests](focused-tests.txt), [full tests](full-tests.txt),
[W03 acceptance log](w03-acceptance.txt) and
[captured-input proof](W03-STROKE-REPLAY.json). The generated replay cache and
large visual files remain in ignored `local-artifacts/product-fix-p3a`.

AutoCAD Desktop remains the final RC target. P3A comparison views are generated
from actual emitted CAD entities by the product renderer; they do not establish
AutoCAD font compatibility or text semantic accuracy.

ARCHITECTURE_REOPEN_REQUIRED: NO.
NEXT_FAILURE_FAMILY: TEXT_SEMANTIC_ACCURACY.
STOP: P3A only. P2C remains paused; P3B has not started.
