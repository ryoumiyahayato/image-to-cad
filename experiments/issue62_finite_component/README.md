# Issue 62: whole finite component and strict numerical boundaries

This independent experiment starts at issue 59 result
`28718414afa5b1660c400716be5331d631a42104`. It does not merge main or replace
the valid 436-object drawing. Source pixels, private coordinates, fonts, OCR,
model files, experimental DXFs and private archive links are not in this directory.

The implementation is governed by the [component contract](../../docs/native/ISSUE62_FINITE_COMPONENT_CONTRACT_20261127.md),
[exact arithmetic contract](../../docs/native/ISSUE62_EXACT_WIDTH_CONTRACT_20261127.md),
[independent saved-reader contract](../../docs/native/ISSUE62_INDEPENDENT_READER_CONTRACT_20261127.md),
and the separately frozen [shared-vertex construction amendment](../../docs/native/ISSUE62_SHARED_VERTEX_AMENDMENT_20261127.md).
The amendment preserves the first development failure instead of silently
relabelling an approximate finite intersection as exact contact.

## What this model establishes

`attached_stroke_component.py` samples every directed edge port of each verified
complete source chain, at the existing 6/8/12-pixel spans. It intersects **all**
independent width constraints, including incompatible ones. Other finite bodies,
source cores and noncollinear parts of the same body can exclude contaminated
sections; successful intervals never determine which ports are examined.

Each supported body has one constant half-width across its complete finite
polyline. `attached_stroke_width_exact.py` uses rational squared distances for
normal sections, finite projection, cell membership, strict white bounds,
other-axis clearance and coherent multi-body coverage. Lower bounds are closed;
upper bounds are strict. A closed lower bound equal to a strict upper bound is
empty. No global epsilon or issue 60 diagnostic tolerance is used in these gates.

The joint solver uses a single width vector for all black and white cells.
Black-cell events form a finite monotone feasibility search; every white cell
needs a common exterior witness outside all participating bodies. Missing widths,
unproved neighbor chains, unknown exits and exhausted resources remain pending.
An incompatible constant-width model does not prove that the scan is ambiguous
or that the native centerline is wrong.

Source direction and native segmentation are separate. A retained short native
first segment is allowed when the same source port supplies the unchanged
minimum four-pixel direction chord. All actual finite segments remain in the
cap, bend, white-gap and duplicate checks.

The shared-vertex constructor only adds source-supported vertices to **new
candidate hosts**, retaining every existing vertex and every guest endpoint.
The old construction precision bounds the allowed change; acceptance still
requires exact contact and a complete new source check. A tiny change that
touches a white pixel is refused. It cannot modify a prior formal object.

`finite_component_saved_reader.py` reads the actual saved finite geometry,
recursive members and byte-bound TTF outline enclosures. The independent
`finite_component_source_audit.py` rebuilds its source graph and route assignments
from those saved objects and the original image. It consumes no producer PASS
or claimed target chain. Its positive certificate is `COMPLETE_SOURCE_PASS`;
width model inapplicability, unsupported context, geometry contradiction and
incomplete observation have separate outcomes.

## Reproduction

Use the repository's declared native runtime and isolated writable output paths.
All supplied input paths are read-only. The stage below uses only the old plan's
prior bindings and source scope; it never imports its four proposed paths.

```bash
python experiments/issue62_finite_component/run_source_stage.py \
  --repo . --source /authorized/original.tiff \
  --prior-plan /authorized/original-A-prior-plan.json \
  --baseline-dxf /authorized/valid-436-baseline.dxf \
  --output /absolute/new/source-stage

python experiments/issue62_finite_component/run_probes.py \
  --repo . --output /absolute/new/eight-probes

python experiments/issue62_finite_component/audit_saved_source.py \
  --dxf /authorized/actual-saved.dxf --source /authorized/original.tiff \
  --roi X0 Y0 X1 Y1 --dpi 200 --target-id LOCATOR \
  --expected-source-sha256 ACTUAL_SOURCE_SHA256 \
  --expected-dxf-sha256 ACTUAL_DXF_SHA256 \
  --font-pins /authorized/verified-font-pins.json \
  --output /absolute/new/independent-source-audit.json
```

Repeat `--target-id` for the actual target entities. IDs are file locators, not
source ownership evidence or an expected adoption count. The optional font pins
map actual saved font names to SHA-256 and, if needed, authorized explicit paths.

`LOCAL_CANDIDATES_ONLY.dxf` and `LOCAL_CANDIDATES_WITH_CONTEXT.dxf` use unchanged
source-pixel coordinates and explicitly have no paper-mm or ordinary-output
claim. `NOT_ADOPTED_BASELINE_CONTEXT_REVIEW.dxf` is a paper-mm diagnostic copy of
the valid baseline with candidates on a named NOT_ADOPTED layer. It is for
independent review, not a new ordinary main drawing or four adopted objects.
Original baseline bytes remain unchanged. Save/cold-read receipts are separate
from independent complete-source acceptance.

```bash
python -m pytest \
  cad_photo_to_dxf/tests/test_attached_stroke_width_exact.py \
  cad_photo_to_dxf/tests/test_attached_stroke_component.py \
  cad_photo_to_dxf/tests/test_finite_component_saved_reader.py \
  cad_photo_to_dxf/tests/test_attached_stroke_graph.py \
  cad_photo_to_dxf/tests/test_attached_stroke_contacts.py \
  cad_photo_to_dxf/tests/test_attached_stroke_ink.py -q
```

## Handoff to issue 61

The local experimental plan is
`source-attached-stroke-graph-plan-v3-component-exact`; the agreed joint interface
from issue 61 is `source-attached-stroke-joint-plan-v3`. These are distinct
identities, and neither relabels the two historical v2 schemas.

The integration seam is `materialize_shared_vertices(source, graph, rows, cores)`
followed by `prove_finite_component(source, graph, rows, owner=owner, cores=cores)`
after complete candidate fitting and **before** every source/contact/adoption
gate. Retain the pre-construction geometry and `shared_finite_vertex_construction`;
retain all post-construction `candidate_paths` and the single
`finite_component_responsibility` receipt. Adopted `paths` remain separate.
Endpoint records reference the component receipt by hash. Both the component
and exact-kernel hashes belong in `additional_producer_sha256`.

The issue 61 numeric whitelist must not compare these exact fraction fields with
a float tolerance. Its checkpoint/source stability and all-prior saved-file
acceptance still run separately. Actual saved coordinates can differ from source
candidate coordinates after DXF unit conversion, so source-frame width results
must never be copied to the actual saved geometry without recalculation.

## Validation record

The execution commit and frozen results are recorded in the later result report.
Development results and failed runs are retained privately, including changes
detected while independent modules were still being developed. A code freeze
and stable-source rerun, not an edited earlier receipt, supply the final results.
Real new-object editing is NOT_APPLICABLE if the new stage adopts zero objects.
Synthetic edit files do not substitute for real adoption, ordinary whole-region
generation, CAD GUI, Windows execution or engineer UAT.
