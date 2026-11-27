# Issue 63: finite raw-ink contact domains and shared saved vertices

This contract is frozen before the new construction and real adoption runs.
It governs new attached candidates only. It does not change existing formal
objects, source pixels, the width/raster model, or the 20-degree continuation,
18-degree competition and 4-pixel source-direction gates. The issue 62 v1
constructor and its failed receipts remain historical evidence.

## Three separate decisions

1. An existing formal object's geometry, identity and resources remain subject
   to exact old-object protection. This constructor cannot edit such an object.
2. A new contact must be represented by the same binary64 vertex in each new
   participant, transformed with the same operation sequence and serialized
   with the same value. Actual saved geometry must have exact zero contact
   distance. No source-domain proof substitutes for that saved-file check.
3. Original-ink responsibility still needs the separately frozen whole-component
   width, cap, junction, black/white, neighbor and competition model. Permission
   to place one contact point does not authorize all black cells near it.

## Pointwise finite original-ink domain

The original skeleton node is a topological locator. Its closed-cell bounding
rectangle is a finite *search bound*, without padding or dilation. The rectangle
alone grants no permission. This first domain covers a three-external-arm
attachment with one independently unique continuous host pair and one guest.
Every original node pixel, adjacency and incident arm is retained.

For the given guest endpoint to be in the domain, fresh observations must show:

- exactly the original three external arms, bound to one guest and the two
  sides of the same finite host; neither a missing nor an extra arm is ignored;
- a unique continuous host pair at all existing 6/8/12-pixel observations, all
  alternative pairs recorded, unchanged direction/competition/separation gates;
- complete same-source guest/host chains and source samples, without importing
  producer approval flags;
- the original core's finite bound, no internal source endpoint and no enclosed
  original white component; the original adjacency is not rewritten;
- the proposed point lies in the finite locator rectangle and in original black
  closed cells, and each of the three original arm necks has an exact straight
  black-cell connection to that point;
- a strictly interior point of the complete finite host: host endpoints are
  never extended, and an internal shared vertex remains an internal point;
- finite original-black support for the actual guest and host segments.

Thus an ink point outside the skeleton node's own cells can be supported, but a
white point, wrong arm, unsupported near point, hidden internal endpoint, hole,
outside-host point or competing direction does not obtain a certificate.
The domain is evaluated for actual exact coordinates, including rational source
coordinates reconstructed from a saved DXF. It does not round those coordinates.
The proof records the point's containing cells, all spoke cells, all source arms,
all raw core adjacencies and a hash of the observed source patch. No entire
connected component is relabeled as a junction responsibility area.

## Exact construction with a derived representation bound

Construction uses the fixed longest original source chord at the guest port,
and each actual finite host segment. Their line intersection is computed with
rational arithmetic, including finite projection and ray direction. The supplied
guest endpoint must be the correctly rounded nearest binary64 value of that
exact intersection in **both coordinates**. Correct rounding is proved using
the exact midpoint interval between that binary64 number and its two adjacent
binary64 numbers, with round-to-nearest/ties-to-even endpoint inclusivity.

There is no fixed distance tolerance. The permitted representation difference is
the exact half-ULP interval derived from the actual coordinate value. The
record includes the exact intersection, actual coordinate, midpoint bounds and
exact error. A different nearby value, even if much smaller than 1e-7 pixels,
fails this representation certificate. This requirement does not assert that
every historical floating solve produced a correctly rounded point; unsupported
historical constructions remain pending.

For each supported attachment, insert the *unchanged guest endpoint* as a vertex
of its **new candidate host**, even when it was exactly on the host line before
unit conversion. This makes an originally implicit incidence explicit in the
file representation. Preserve every original host vertex, every guest endpoint,
short segment, true bend and free end. Multiple guests on one original segment
are sorted by their exact finite projection; equal-projection conflicts,
zero-length results and resource overflow refuse the whole construction.

All affected and previously exact contacts are inserted together. Recompute new
candidate IDs from the complete resulting geometry and update host references;
record old/new IDs and all pre-construction geometry. Check all finite segments
and complete source/core fits again. Failure returns original rows unchanged.
All whole-component source, duplicate and prior-contact gates run afterwards.

The shared source-to-paper mapper memoizes the unmodified binary64 source point
and uses the ordinary operation sequence `(x-x0)*(25.4/dpi)`,
`(y1-y)*(25.4/dpi)`. It does not snap points, change units or alter old objects.
Mapped shared points reuse one exact pair of binary64 output values. The actual
ordinary exporter and independently reopened DXF still supply the final contact
check; a cache receipt alone cannot certify saved output.

## APIs and evidence identities

- `prove_finite_junction_domain(source, graph, node_id, guest, host, end_index)`
  recomputes the pointwise source-domain proof. It accepts exact rational
  `representation_exact_points` when supplied by the independent saved reader.
- `materialize_shared_vertices_v2(source, graph, rows, cores=None)` returns
  `(new_rows, receipt)`. `cores` is compatibility input only; producer PASS flags
  never determine the new domain. The implementation reconstructs observations.
- `SharedCoordinateTransform(roi, dpi)` is a callable mapper; reuse one instance
  across the new finite component's ordinary output objects.

Schemas are new: `source-finite-junction-domain-v1` and
`source-supported-new-candidate-shared-vertex-construction-v2`. Producer and exact
kernel hashes bind these receipts. Neither is a whole-source adoption certificate.

## Required falsifiers and stopping boundary

Use authored source graphs, not private coordinates in tests. Include a black
contact outside the skeleton's closed cells, a point on white or without the
required guest source, a wrong pair or extra arm, a point outside the finite host,
an internal end/white hole, an incorrectly rounded near point, and non-axis-aligned
multiple guests sharing one host. Actual saved and cold-read positive geometry
must preserve all original vertices and exact incidences. Changed saved endpoints
and a genuine white gap must remain observable failures.

Stop on missing source, inconsistent topology, incorrect rounding, non-unique
finite intersection, white-cell crossing, unsupported core or resource boundary.
The new contact construction cannot erase issue 62's constant-width counterexample
or declare the six disputed cells jointly explained. Those are separate model
decisions with their own raw witnesses.
