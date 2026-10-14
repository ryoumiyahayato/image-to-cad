# Image to CAD architecture simplification evidence

Draftsman is a former/internal codename.

Evidence correction (2026-10-05): the retained preservation-baseline.json has
UNPROVEN / UNKNOWN historical generation provenance. Its first Git addition was
26ad39e44755473c29723ece07efd3f3209f814c; this does not establish which snapshot
generated it. The compact matches recorded below are current regression
observations, not independently established PRE evidence. Genuine PRE evidence
was subsequently rebuilt from independent git archive snapshots (4a8031 vs
fb42639), in separate Python processes. See historical-evidence.md and
historical-verification-summary.json for the bounded three-input exact match.
This is not proof for all OCR output or all engineering drawings.

Starting branch: `codex/source-support-lifecycle-instrumentation`.
Starting HEAD: `4a8031eb14ec136ab71cbe3c66a7a46e1198d1af`; clean.
Read all sixteen supplied audit files, including both full CSV datasets.
No parent checkout maintenance or index operations performed.

## A — retired disconnected code

The exact deletion list is in `phase-a-deleted.json`. AST import closure from
`main` and the package initializer excludes every deleted file; reverse closure
also retires their exclusively bound tests and offline generators. Packaging
uses neither shadow architecture nor historical review server. Kept package
initializer and version: contrary to the audit these are used by main/spec.
Kept production whole-object ownership: it is distinct from shadow IR.

Validation: 17 processing/cache/page-export regressions passed; runtime import
closure, offscreen GUI construction/show/close, and CLI help smoke passed.

## B — shared production processing

Headless now calls ProductionProcessingService.process_page and exports its
FinalStructure. Input correction and scale selection stay at the interface.
No second preprocess/detect/clean pipeline was added. V1-only threshold,
minimum-length, hatch, auxiliary knobs are explicitly reported as retired.
OCR is still opt-in for CLI. The CLI report now describes FinalStructure.
Legacy modules cannot yet be removed: dormant GUI ancestor methods still
import them; retirement follows removal of those methods in C.

Recorded native sample and processing/reconciliation fixture geometry, member
counts, page size, DXF entity counts and cache roundtrips in
preservation-baseline.json, together with legacy output. The historical source
of this capture cannot be established; the original claim that it was captured
before changing the engine is unproven.
CLI smoke exports 21 lines from the existing processing fixture, matching the
GUI service. Legacy output differences are retained in the baseline for review.
15 processing and export regressions passed.

Git commit triggered automatic shared-repository maintenance and emitted an
index/repack error after successfully creating A. No repair was attempted.
All subsequent writes disable auto maintenance using command-local options.

## C — single desktop window

Inventory is in gui-method-inventory.json. Removed every application ancestor
class and all superseded processing overrides. One MainWindow inherits Qt
directly; document/cache, review, processing and controls contain its methods
as ordinary functions bound directly (no forwarding methods or mixin chain).
Controls are constructed once with current labels/defaults. Removed invisible
cross-file queue, historical parameter widgets and their unreachable methods.
MainWindow owns state and Qt worker lifetime, rather than a new large coordinator.
Updated current GUI tests to the active window. Retired the obsolete consolidated
milestone suite and replaced inheritance/source snapshot tests with current
entry and UI behavior checks. Verified startup, cache invalidation, scale,
OCR review, page export and visual acceptance.

Reproduced an existing unchanged paint-review save losing straight lines: its
bare RasterTraceResult omitted them. Unchanged save now retains the identical
FinalStructure; a regression asserts object identity and exported LINE count.
Changed raster edits retain their existing raster retrace behavior.

## D — one final assembly

Processing configuration is passed to the original optimized-trace assembly.
Removed the service's full unpack/copy/repack and identity recomputation.
GUI applies the authoritative fields and renders the preview once; removed
ancestor display churn and cleared-line shadow state. Cache deserialization and
actual text edits still construct new structures because their content changes.
Final structure performance events now occur once, not twice.

The audit's second ownership pass is not assumed redundant: it processes newly
admitted reconciliation restorations, updates residual ownership and fails
closed on a veto. Its necessity is investigated separately in F.

## E — construction boundaries

LineSegment rejects nonfinite/bool coordinates and nonpositive width at
construction. copy uses dataclasses.replace. Zero-length detector candidates
remain legal until algorithm filtering: minimum lengths are policy thresholds,
not an object-shape invariant. FinalStructure now detaches/freezes masks,
collections and metadata and validates at __post_init__, including direct
construction and replace. Removed repeated validation in preview/export/cache
consumers. Cache keys validate identifiers/page/DPI at construction; one digest
function serves both hash domains. No validation service was introduced.

Audit-family dispositions: finiteness -> constructor; length -> necessary
algorithm thresholds; image dimensions -> independent public array boundaries;
type/subclass checks -> GUI chain check removed, parsed external metadata still
needs shape checking; SHA format -> one function; junction authority -> external
contract trust boundary; cancellation -> long-running operation checkpoints,
not duplicate validation. Enum and reconciliation acceptance rules stay intact.

22 constructor/config/performance/immutability checks passed. Larger focused
suite: 99 passed, 11 failed; rerunning with the exact starting LineSegment code
reproduced the same 11 historical V1-ledger expectation failures (48 other
reconciliation tests passed). Reconciliation source was unchanged. K will
update stale ledger assertions without altering geometry semantics.

## F — representations

The complete 15-row source/target/call-site/purpose table is representations.md.
One metadata-only transform is retired; all remaining transitions have distinct
domain, algorithm, identity or serialization roles. Ownership masks filter exact
vector proposals; they never reconstruct rounded vectors. Extracted one coherent
assignment/reconciliation function, retaining source and veto semantics.
10 ownership tests passed, including an invalid new commitment veto case.
All three preservation inputs have exact baseline structural/geometry/cache/DXF
parity after D/E/F.

## G — optional diagnostics

Observation/lifecycle imports are type-only or lazy inside enabled diagnostic
branches. Diagnostic images/payloads are detached before dispatch. Removed the
lifecycle-derived artifact protection decision: enabling observation can no
longer change that filter's output. The default algorithm is unchanged.
25 observability/lifecycle/artifact/visual acceptance tests passed. The synthetic
damaged-scan case now also asserts instrumented/uninstrumented output equality.
Visual acceptance is generated on selecting its existing tab, not on every
processing/cache/text-review return. Default output is Documents/CADPhotoToDXF;
the explicit output-root override remains. GUI no longer invokes Git to stamp
diagnostics. No runtime local-artifacts directory is required.

## H — reconciliation preservation

The complete top-level inventory is reconciliation-inventory.csv. Production
calls ReconciliationLedger.observe_main/observe_late_restoration/reconcile and
ReconciliationResult.assert_complete/commit_consumption/assert_consumed_same.
Moved 24 exact geometry/interval/serialization primitives into
reconciliation_geometry.py (380 LOC); no formulas or acceptance rules changed.
Removed a one-use artifact dictionary helper and two repeated commit checks.
Core certification, source scope, interval coverage, endpoint obligations and
transaction proofs remain: they reject invalid commitments in production.
The closed V1 projection is still a current serialized ledger contract, and
LEGACY_RESTORATION_ACCEPTED identifies an active restoration route, not dead
compatibility. No such path was removed on its name alone. Observer/debug
plumbing was already detached in G; no uncalled algorithm branch was inferred
from an AST alone. All eight requested categories were evaluated; remaining
ledger serialization/proofs are required by commit validation and cache identity.
118 focused safety/gap/performance tests passed. Three representative inputs
again have exact structural, line, cache and export parity. Updated one invalid
numeric fixture to expect rejection at construction rather than downstream.
The 5,800-line core remains complex because removing its proofs would alter the
production acceptance boundary without equivalent evidence.

## I — one entity serializer

Single-page and streaming document exports now call write_page_entities, the
same concrete serializer for committed lines, contours, text and signature
assets. Semantic mask-to-contour conversion is shared; it is serialization of
an existing mask, not line reconciliation. File/units/page-layout orchestration
remain separate because single uncalibrated images and scaled PDF page stacks
have distinct format requirements. Low-level export_exact_trace_dxf is retained
as the actual single document writer and supports direct typed geometry tests.
Current GUI and CLI supply FinalStructure. The streaming API still accepts
explicit DocumentPage geometry for existing callers; it never cleans/merges it.
Removed dormant V1 GUI export dispatch and 13 V1/dependent modules (exact list
in phase-i-retired.json). Removed 37 V1-only test groups while retaining current
perspective/preprocess/resolution tests in mixed modules. 54 export/text/signature/
core/resolution checks passed; all three representative inputs retain exact
structure/geometry/cache/DXF parity.

## J — responsibility packages and zero cycles

Used git mv for the module relocation recorded in module-moves.json. Split
TracePath from raster algorithms and FinalStructure from its builder. The
read-only member binding resolver depends on the model, not its builder.
Retired the object proposal/compiler API with no production callers, replacing
producer/future-design tests with two frozen consumer fixtures; five cache/
identity/preview/export reader tests passed. Import SCCs including TYPE_CHECKING
and optional edges are now zero. Application scope is core/geometry/ocr/export/
gui/diagnostics; root contains only package/version. Font/DWG/source/authority
paths account for the extra package level, and packaging import was updated.
Offscreen GUI show/close succeeded; 14 GUI/binding/action checks passed. Added
actual window export-action dispatch verification, which exposed and fixed a
missing binding import left by C. All three preservation inputs again have
exact structure/geometry/cache/export parity after the data-model separation.
K removes the remaining disconnected diagnostic/review harnesses and stale tests.


## K — current regression suite and supported commands

Retired disconnected historical diagnostics, audit generators, future-design
schemas, V1 OCR/raster orchestration and bound tests. Exact file retirements
are phase-k-retired.json. Preserved the explicit current DXF validator, debug
capture, smoke generator and visual acceptance commands. Retained current
source reconciliation and gap tests; corrected eleven stale V1 ledger expectations
that were reproduced on the original baseline to assert the existing closed
projection and route snapshots without weakening source geometry safety.
Mixed modules retain current perspective, OCR backend and UI behavior tests.
Retired the oversized-box assertion belonging to the removed old OCR entry,
old historical contact-sheet assertion and test-only OCR forwarding API.
One-off migration scripts and accidentally staged smoke outputs were removed.

CI/release now use the actual three-input production preservation check instead
of removed V1/FS2 benchmark runners. Release provenance records its generated
preservation JSON; it no longer reads the retired benchmark files. Updated
packaging authority data and responsibility paths. GUI image and headless
configuration both use the established 240 DPI setting (the public service's
existing default of 300 DPI remains). A current CLI regression captures the
actual shared service result and compares report IDs/sizes, preview and DXF.
A fresh-process regression blocks Git/network/local-artifact access and checks
installed OCR sessions actually use CPU without CUDA/TensorRT.

Final full suite: 527 passed. Representative native service outputs retain exact
structure IDs, member counts, every line coordinate, cache identity and DXF
entity counts. CLI comparison against the captured V1 output is recorded in
cli-comparison.json: processing fixture 20->21 lines; sample 545->152 lines plus
123 contours; gap fixture 12->12. Corrected page dimensions are unchanged for
all three actual CLI comparisons; all text counts are zero in these OCR-off
inputs. These are explained V1 retirement differences, not changes to the
preserved native production algorithm. No new product capabilities were added.


## Post-refactor small closeout

The retired V1 flags were removed from argparse and active script callers; no
legacy algorithm was restored. The static Junction JSON resources now reside
in app/geometry_rules; their bytes and serialized semantics are unchanged.
TEST_ONLY_PRODUCTION_MODULES counts app Python implementation modules with no
supported production entry but test use, excluding initializers and tests/
files. Its current value is zero. The six supported diagnostics (debug_bundle,
observability, performance_observability, source_support_lifecycle,
trace_verification, visual_acceptance) are OPTIONAL_PRODUCTION_DIAGNOSTICS.
Current closeout validation is recorded separately in closeout-report.md.
