# Issue 62: complete finite component and exact source responsibility

This contract is frozen before running the new component model. It extends the
independent issue 59 branch; it does not authorize a main merge or replace the
436-object valid baseline. Development controls are declared examples, not a
holdout set. The original eight probes remain eight separately rebuilt sources.

## Hypotheses and stopping boundary

1. A locally polluted attachment can have independent width evidence elsewhere
   on the **same complete source chain**. Test every end of every chain edge at
   the existing 6, 8 and 12 source-pixel spans. Preserve all exclusions and
   incompatible sections. Never select sections according to their result.
2. Constant width is a falsifiable submodel, not an assumption about every
   scanned stroke. Each complete finite polyline has one squared half-width in
   a closed-lower/strict-upper interval. Crossing a junction transfers this
   parameter only along the same independently unique continuous source route;
   every independent section on that route must agree. No neighboring stroke
   donates its width. An exact empty intersection stops this submodel with
   `MODEL_NOT_APPLICABLE_CONSTANT_WIDTH`, without asserting wrong CAD geometry
   or non-identifiability of the scan. No piecewise or raster-error parameter is
   introduced after seeing this failure.
3. A joint component needs its other supported finite bodies. Each candidate and
   necessary prior neighbor must have its own source chain, isolated sections
   and finite geometry. Unknown or incompatible neighbors remain explicitly
   unknown; merely being nearby does not authorize their use in a pixel model.
4. A native end segment may be short while the source port provides a sufficiently
   long direction chord. The unchanged 4-pixel source-chord requirement applies
   to the observed source, not to polyline segmentation. Preserve every native
   vertex. This change cannot repair a short or branching source observation.

The physical model is the union of round capsules of the **actual finite straight
segments**. A polyline uses one constant radius across its segments and joins.
It covers open zero-bulge polylines only. Existing direction (20 degrees / 18
degrees margin), whole-route uniqueness, free-end, ownership, contact, text and
positive-length-duplicate gates remain independently required.

## Exact new gates

Inputs are integers or the exact rational value of supplied finite binary64
coordinates. Do not snap saved geometry, round IDs, add epsilon, or use issue 60's
derived-diagnostic whitelist here. Square all distances to avoid square roots
in decision comparisons. Preserve lower and upper inclusivity in serialized
fractions. A lower bound equal to a strict upper bound is EMPTY.

The source threshold remains 128. A black pixel is a closed unit square which
must meet at least one supported finite capsule. A white pixel needs one of its
nine fixed points (corners, edge midpoints, center) strictly outside **all**
capsules, using a single simultaneous vector of widths for the entire window.
This is a conservative compatibility model, not an exact scanner forward model.

Start each body's radius at its independent lower bound. For an uncovered black
cell, branch only at exact cell-to-body squared-distance events still below that
body's strict upper bound. Raising a radius can only remove white witnesses, so
an already swallowed white cell prunes that branch. Exhaust the finite event
search or mark its resource boundary pending; never call a truncated search
infeasible or complete. Retain a feasible width vector and a witness for every
black and white constraint. Parameters may not vary per pixel.

Normal section enumeration, projection, section bounds, exclusion inequalities,
multi-body coverage and short-continuation events use the exact arithmetic
contract in `ISSUE62_EXACT_WIDTH_CONTRACT_20261127.md`. Floats may label diagnostic
distances, never decide the new source gate.

## Whole geometry, finite observation and endpoints

The window contains all target finite geometry plus a border derived from the
fixed maximum section half-span (12 pixels), limited by the existing 240-pixel
component resource envelope. Window growth does not follow the whole page's
connected ink. Preserve all original black cells and white holes in the window.
Only connected components touching a target's actual source chain are relevant
to joint coverage; disconnected ink is retained in the ledger as a neighbor,
never interpreted as a target extension.

A connected boundary exit is acceptable only where a separately supported finite
body crosses the boundary with independently supported source on both sides and
its own valid width interval. Classify genuine free ends, proved shaft exits and
unknown exits separately. Missing body support, a clipped target cap, or an
unexplained connected exit keeps the component pending. No unexplained ink is
hidden by shrinking the window. An unsupported necessary body makes the joint
model unavailable; supported-only residuals are then diagnostics, not a proof
that the target geometry is wrong.

The canonical CAD endpoint convention remains the uniquely source-supported
finite host intersection. Hidden pen travel wholly inside already explained
host/cap ink is the same editing representation. A continuation that explains
original connected ink outside the finite component envelope is an observable
competitor and blocks completion. Enumerate finite outward source-cell events
with the same exact widths and white constraints; a retained competitor is not
new geometry. Unknown directions or a truncated competitor search stay pending.
Physical pen order and invisible subpixel endpoint history are not claimed.

## Evidence interface and independent audit

New model schema: `source-finite-component-responsibility-v1`.
New graph plan schema: `source-attached-stroke-graph-plan-v3-component-exact`.
The producer records its source-file hash, dependency hashes, raw source identity,
complete candidate IDs/finite geometry/source chains, section support/exclusions,
body dependencies, raw black/white ledger, coherent model and exact comparisons,
endpoint source chords/native segments, boundary exits and competition status.

`prove_finite_component(source, graph, rows, *, owner, cores)` is the local model
seam. The graph adapter retains `candidate_paths` before every gate, saves
`finite_component_responsibility` once per component and stores endpoint
references to it. `paths` remains adopted paths only. This seam is available to
issue 61; its upstream stabilization and common numerical certificate remain
separate work. All failed candidates must remain in the plan.

The independent acceptance reads an actual saved DXF and the unchanged source.
It uses fresh source observations and saved finite geometry, never a producer
PASS or claimed target chain as truth. It may share the reviewed exact-distance
kernel, with a distinct reader and source evidence path. Complete source PASS
requires finite geometry support, independent chain/direction evidence, all
necessary widths, coherent whole-component black/white coverage, closed scope,
no observable boundary competitor and all applicable source/contact/context
conditions. A positive example is required; no constant-false certificate and
no blanket flip of the old issue 60 status is acceptable.

Actual TEXT bounds are certified only under the saved-reader's frozen font and
layout subset, with matching font bytes and conservative outline bounds. Related
unknown context stays pending; 61 uncertified text bounds are not 61 conflicts.

## Discriminating development controls and stop conditions

| Claim | Positive control | Falsifier / required outcome |
| --- | --- | --- |
| Same-chain width transfer | Remote isolated sections, polluted local junction | Independent sections disagree: exact model-not-applicable |
| Source direction separate from native segmentation | Long source chord with a retained short first segment | Short or branching source chord: pending |
| Necessary neighbor responsibility | Connected neighbor with independent source/width | Similar unsupported neighbor: unknown, never borrowed coverage |
| Strict arithmetic | Nonempty rational interval | Touching closed/strict bounds: empty, even if float says positive |
| Finite cap convention | Ordinary finite round cap | Observable outward ink / finite short continuation: pending |
| Original white evidence | Genuine white gap and hole preserved | Geometry crosses gap or union swallows hole: reject/pending |
| Complete source certificate | Independently saved positive finite component | Tampered geometry, missing body, source change: no PASS |

Stop when the complete-chain constant-width model is demonstrably inapplicable,
finite support is insufficient, an observable competitor remains, or a declared
resource boundary is reached. Preserve the discriminating witness and identify
the specific missing model condition. Do not tune until four objects pass.

First deliver the real new source stage and actual local saved files. If no
real new objects are adopted, real new-object delete/move is NOT_APPLICABLE.
Synthetic saved edits are separate evidence. An ordinary whole-region result
requires issue 61's stable entry plus joint verification; local candidate DXFs
must be labelled NOT_ADOPTED and cannot replace the valid baseline. GUI, Windows,
engineer UAT and main merge remain NOT_RUN in this independent task.
