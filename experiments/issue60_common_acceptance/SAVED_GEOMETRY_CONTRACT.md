# Independent saved geometry and editing contract

This checker reads actual files with ezdxf and never imports the attached-stroke
producer, its graph or its verdict. It is one layer of common acceptance; a PASS
does not establish complete source responsibility or authorize adoption.

## Exact content and identity

- Every formal model-space entity must have one unique stable `I2CAD_NATIVE_V2`
  identity. Missing/duplicate identities fail.
- Compare the whole pre-existing entity tag content by stable identity. Keep
  exact binary64 values, XDATA, geometry, widths, text, transforms and display
  attributes. Database entity/owner handles (codes 5/105/330) are explicitly
  excluded because they address the DXF database, not the stable object.
- REVIEW entities are a multiplicity-preserving exact multiset. Named blocks,
  all block members, styles, layers, linetypes and listed units/coordinate header
  fields are exact. Creation times, GUID and handseed are not drawing-content
  tests and are excluded, not silently reported as preserved bytes.
- Actual target LINE/open LWPOLYLINE values must exactly equal the declared
  finite geometry after the writer's documented paper-mm transform. Zero DXF
  bulges use the actual decoded zero default; no numeric tolerance is applied.
  Validate complete vertices/endpoints, width, bulges, closure, elevation,
  extrusion, identity id/kind, layer and nondegeneracy. Declaration agreement is an identity check,
  not proof that the declaration's source interpretation is correct.
- File SHA, sidecar object set and writer identity set are checked independently.
  The binding gate requires independently supplied original source SHA and
  ROI/DPI. Moving the declaration and its own ROI together cannot shift that
  external reference frame. Frozen envelope hashes remain external anchors.

## Independent original-pixel input

Read geometry directly from the saved file, including transformed INSERT
members. Multiple inserts, unknown block extensions/clipping, recursively
referenced blocks and skipped virtual members explicitly remain unresolved;
attached attributes are retained as members. Convert paper mm back to original source coordinates, recording the
transform. Keep curves and finite-width paths as explicitly unsupported shapes;
never turn arcs/bulges into straight chords. Each bound carries a scope and
`coverage_valid` flag. Planar circles/arcs have outward-rounded rational
full-circle bounds. Finite-width, thick, nonplanar, text and other unverified
bounds cannot exclude a nearby source responsibility. Width metadata retains
its stated DXF-mm unit. Bounds never prove a curve intersection.

Only the target object IDs select which objects are being audited. IDs, local
windows and old declarations never specify a correct recovered shape. Actual
source support, white gaps, finite contact and boundary responsibility are
decided by the separate original-pixel reviewer, with its own limitations.

## Editing

Create a fresh independent copy for each whole-entity delete/move. Ordinary
ezdxf save completes in one process; a separate process reopens the files and
checks all non-target formal entities and all REVIEW/blocks/styles/layers.
Moving means every target vertex/end segment follows the same requested
translation; deleting means the target identity and whole entity disappear.
The comparison is exact and never rescales or rounds the neighbors.
For a moved target, the independently translated expected entity is also
serialized and cold-read: optional default tags materialized by an in-memory
transform may be legally omitted on save. This does not relax any coordinate
or attribute value and prevents a serialization-only false failure.

Record these as programmatic saved-file checks, not CAD GUI actions. Old A
geometry can be independently re-audited without claiming a new production
conversion under the numerical-contract code.
