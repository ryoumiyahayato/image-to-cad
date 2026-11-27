# Issue 63: bounded source model contract

Status: frozen before the first Issue 63 real-source adoption run. This is a
new, falsifiable model family. It does not change the historical Issue 62
constant-width contract or turn its failures into passes.

## Three different kinds of equality

1. Existing objects are protected by the complete actual saved entity graph,
   including recursive blocks, attributes, style/resource dependencies, REVIEW
   members, and original numeric values. No rounding or vertex insertion is
   permitted in an old object. Rendering equality is not this protection.
2. New shared contacts use the separate `ISSUE63_JUNCTION_CONTRACT.md`.
   Original guest endpoint values and original new-host vertices remain.
   A representation error is accepted only with an exact source construction
   and its own binary64 rounding interval; there is no general small-is-zero
   rule. All new shared points use one transform cache. Exact contact in the
   actual cold-read DXF is an additional, mandatory check.
3. Raster support is a physical, bounded hypothesis, not coordinate rounding.
   The following width/cap/junction rules have no added half-pixel tolerance.

## Source observations and fixed parameters

All original source-chain ports and the fixed 6, 8 and 12 pixel observations
are enumerated before measurements are evaluated. The minimum source chord
is 4 pixels, minimum independent width sections is 2, and section half-span
is 12 pixels. Independence excludes other finite axes, noncollinear axes of
the same body, and source junction cells. Every eligible section, including
an incompatible section, is retained. No section is selected from the desired
model result. The original 20 degree direction and 18 degree competition
gates remain unchanged.

The model window is the complete target bounding box plus the existing
13-pixel border, limited to a 240-pixel target extent and 131072 cells. Every
black and white cell in this window is recorded. Every actually used
independent section's black and first-white observations is also constrained,
including observations outside the model window. A section's black observations
must be explained by that body, not borrowed from a neighboring body.

Finite prior ports use the separately frozen finite-port influence domain.
An old object's full native identity and historical source binding remain in
the certificate. An accepted finite port is not approval of the old object's
remote chain under this new, narrower model. Every local entry/exit, width,
direction dependency, cap, and considered continuation remains in scope.

## Width family, selected without residual fitting

First calculate and preserve the original whole-chain constant-width receipt.
If all eligible sections have a nonempty common squared half-width interval,
the body's family remains that one constant interval. This selection does not
depend on unexplained target pixels.

If that common intersection is empty, but every individual eligible interval
is nonempty and at least two independent sections exist, use all section
centers as knots of a continuous bounded squared-half-width field. There are
no extra fitted knots. Native vertices split the geometric segments but add
no width degree of freedom. Position along a finite polyline is cumulative
L1 length in original raster coordinates; this is rational and invariant
under collinear subdivision.

For each body, exactly one parameter `alpha` is shared by all its knots:

`r_i^2 = L_i + alpha * (U_i - L_i)`, with `0 <= alpha < 1`.

Here `[L_i, U_i)` is that knot's independently measured squared-half-width
interval. Interpolate squared radius affinely between consecutive knots and
keep the nearest knot's value before the first and after the last knot. Thus
width is continuous and stays inside the neighboring measured bounds. A body
has one scalar parameter, not a separately adjustable residual-pixel radius.
Different bodies may have different parameters; the entire component must
have one simultaneous coherent parameter vector.

The body is the union of discs swept along its actual finite polyline with
this squared-radius field. Ends are the corresponding finite round caps.
Native internal joins use the same continuous field. A junction is the union
of the participating finite bodies. A separately proved raw-ink junction
domain authorizes a contact point; it does not authorize an unbounded ink
patch, add black-cell coverage, or fill a white hole.

## Exact membership and search

For a finite segment `c(t)=a+t*d`, squared radius is affine in `t`.
Point membership minimizes `|p-c(t)|^2-r(t)^2` for `0<=t<=1`.
For a closed pixel cell, split at the exact segment parameters where the
center crosses a cell side and minimize the corresponding squared distance
to the rectangle minus squared radius. Each part is a convex quadratic;
endpoints and any in-range stationary point are evaluated as rational values.
No square root or floating distance decides straight-body membership.

A black cell requires closed intersection with at least one supported finite
body. A white cell requires one of its center/corner/edge-midpoint nine points
to be strictly outside every body under the *same* parameter vector. Separate
per-body white witnesses cannot be combined into a common witness. The nine
point model is a declared raster model, not a recovered scanner point-spread
function or a claim that the entire white cell is empty.

For constant bodies, black coverage events are exact rational thresholds.
For a variable field, monotone coverage thresholds are conservatively bounded
on the predeclared 48-bit dyadic alpha grid. The grid is a search resolution,
not a geometry epsilon. Every accepted parameter vector is checked using the
exact membership predicates above. A feasible solution lying between sampled
thresholds, an exhausted 8192-state search, or a strict-upper boundary that the
grid cannot reach yields PENDING; it is not an impossibility proof.

The strict alpha=1 outer envelope is never an accepted model. If a black cell
does not intersect even that envelope, or touches it only at equality while
all knot intervals have positive width, no admissible alpha<1 can explain
that cell. This exact outer-envelope counterexample is a genuine falsifier
of this family. Its actual cell, bodies, independent bounds and exact costs
are retained. The original constant-model contradiction remains beside it.

## Observable alternatives

Finite continuation tests retain the existing maximum 512 events and
240-pixel reach. They use the same independently bounded field; a continuation
keeps its original endpoint radius beyond the original endpoint. Source
direction, raw original ink, full white constraints and finite neighbors are
retained. Hidden histories yielding the same editing geometry are equivalent.
A changed editable endpoint, real white gap or observable tail is a different
representation. Unenumerated bends or exhausted search remain PENDING.

CIRCLE stays a CIRCLE with its actual saved center and radius. A recovered
historical circle receipt binds identity and is a starting point only. Any
finite arc used in this model needs a new exact support/width receipt and
actual source observations; a chord or a prior PASS is not substitute ink.

## Independent result and limits

New local plan schema: `source-attached-stroke-graph-plan-v4-bounded-source`.
Component schema: `source-finite-component-responsibility-v2-bounded-field`.
Every producer/kernel hash and complete replay field is bound to the new plan.
The independent reader reconstructs direction dependencies, original cyclic
core adjacencies, finite prior certificates and source model from original
material and actual saved geometry. It never inherits a producer PASS.

The original eight probes are rerun with their original source hashes and a
fresh graph/owner/plan each. New small controls discriminate shared contact,
white gap, bounded width, cyclic solid core, finite-port binding and circle
identity. They are development controls, not unseen holdouts.

Real adopted entities, if any, require independent delete/move/save/exit/cold
read with all non-target entities protected. With zero real adoptions these
editing checks are N/A, not PASS. A new contract failure is reported as a
boundary of this implementation; it does not establish intrinsic source
ambiguity, engineering correctness or product acceptance. Main, GUI, Windows,
ordinary-flow integration and engineer timing are separate gates.
