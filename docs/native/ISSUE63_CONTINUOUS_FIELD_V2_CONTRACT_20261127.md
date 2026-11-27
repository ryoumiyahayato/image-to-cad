# Issue 63 — fixed independent knot field, explicit v3 family

The module remains `bounded_stroke_field_v2.py` so callers retain a stable
integration point. Its field identity is now
`source-bounded-continuous-squared-width-field-v3-independent-knots` and its
union identity is `coherent-bounded-finite-union-v3-independent-knots`.
This is a declared family revision, not a reinterpretation of earlier results.
The original constant-width receipts, v1 field results, coordinator's frozen
five-body/two-cell outer-bound counterexample, and first one-alpha v2 checkpoint
remain unchanged under their original source and producer identities.

The first one-alpha v2 checkpoint failed clean symmetric and monotone width
controls. Conservative exact alpha lower bounds from required black cells,
together with a white cell whose nine allowed witnesses were already covered
at those lower bounds, prove a contradiction for that coupled family. An
independent-knot family avoids the unnecessary coupling. This does not by itself
prove capability, source completeness or any real adoption; those require their
own executed receipts.

## Independent calibration and fixed finite parameters

Every original eligible section is retained. At least two independently
measured sections must have individually nonempty squared-half-width intervals
`[L_i,U_i)`. The old constant intersection and receipt are recomputed and checked.
A nonempty intersection preserves a constant subfamily; it never deletes the
continuous family.

1. Each independently measured section center is a fixed knot with its own
   original interval `[L_i,U_i)`.
2. Finite endpoints, actual direction changes of the native polyline, and
   separately source-proved junction coordinates are fixed additional knots.
   Their interval is `[min_i L_i,max_i U_i)`, computed from all independent
   sections before looking at unexplained component cells.
3. Every knot has its own parameter `0 <= alpha_k < 1` and squared radius
   `r_k^2 = L_k + alpha_k (U_k-L_k)`. There is one complete finite parameter
   vector for all bodies and all observations. No residual pixel creates a
   new knot, interval or parameter.
4. Squared radius interpolates affinely in cumulative L1 length along actual
   finite native geometry. Exact collinear storage vertices add no free knot.
   All geometry vertices split sweep pieces, retaining exact coordinates.
   Every piece endpoint stores fixed nonnegative rational knot weights with
   exact sum one. Adjacent pieces share identical radius expressions.
5. Each finite endpoint has a round cap with that endpoint's selected radius.
   There is no separate junction blob, unbounded line, half-pixel expansion or
   residual-derived radius. The independently observed global range is a
   declared transfer hypothesis, not a measured scanner kernel or a permission
   to grow arbitrary ink at a junction.

All section intervals and actual coordinates constrain the family. The product
of fixed knot intervals gives a finite, independently calibrated range. Piece
slope enclosures are derived from the fixed interpolation coefficients and the
same product box. Supplying a junction coordinate merely satisfies incidence;
its fresh independent source-domain proof is a separate caller obligation.
Changing finite source geometry requires new source measurement and saved-byte
checks. Moving old section indices to a different geometry is not remeasurement.

## One complete observation model

Each closed black source pixel must intersect at least one allowed finite body.
Each white cell must retain at least one common strictly outside point from the
predeclared nine-point set: center, edge midpoints and corners. The same point
must be outside every participating body. These are the inherited declared
pixel observation predicates, not a claim about a calibrated scanner process.

All window black/white cells, each eligible independent section's own black
cells, and all actually measured white cells from every section, including
ineligible sections and cells outside the window, constrain the same complete
vector. A section black cell must be covered by its own body. The solver adds
observations retained by each field and combines explicit caller observations
using canonical exact-cell/role deduplication. Component-black and own-section
roles remain separate receipts. No producer PASS substitutes for original
section measurements, current source independence or saved-geometry evidence.

A native circle remains an actual circle, never a chord approximation. It has
one constant squared-radius parameter in its independently measured radial
interval. Conservative radical interval enclosures merely bound candidate
parameters. The circle's own eligible black sections and every actual white
observation still undergo exact native-circle membership tests. Its black
responsibility is restricted to the authorized original ring cells, and all
white queries must lie inside its independently authorized finite query domain.
A query outside that domain is PENDING; a whole unseen circle is never silently
added to the union. Exact circle tests eliminate radicals algebraically.

Source completeness is an additional gate. A broad endpoint cap may explain a
few black pixels while still failing the source's independent continuation,
branch, endpoint, finite-neighbor or white-gap obligations. An unassigned source
arm cannot be accepted because the width union covers it. A model PASS alone
never licenses editing a complete object or adopting a new saved object.

## Exact evaluation, proposals and decisions

The selected straight-body profile uses exact rational squared radii and the
existing finite swept-disc quadratic minimizer. The selected circle uses exact
native radial predicates. A PASS records every canonical black assignment,
every common white witness, all parameter identities, the complete exact
parameter vector and the selected knot squared radii. Each successful numerical
candidate is replayed completely with these exact predicates.

Constant-subfamily candidates are tried first. An embedded old section-profile
candidate may also be tried. An old solver PASS only supplies candidate radii;
it cannot bypass the complete new exact evaluation. SciPy SLSQP may propose
independent-knot vectors using piecewise gradients. Floating-point tolerances,
proposal margins and optimizer success/failure have no acceptance authority.
Every accepted float proposal is first encoded as an exact rational value and
all strict parameter bounds and all observations are checked again.

Failure to find a candidate after finite optimizer/search attempts is PENDING.
The numerical proposer has explicit resource limits: at most 512 parameters,
100,000 unique queries, 1,000,000 conservatively counted quadratic pieces and
4,000,000 dense Jacobian entries. Query limits are checked while constructing
the index, before large arrays are allocated. Its `max_states` argument is an
actual hard bound on new numerical oracle evaluations, including line-search
calls. Cached reads do not consume another evaluation. At a resource bound, a
best available candidate may still pass complete exact replay; otherwise the
result remains PENDING. These limits constrain computation, not the declared
mathematical family.
Only an exact black counterexample outside every permitted strict upper envelope
establishes `NO_MODEL_BLACK_OUTSIDE_ALL_STRICT_BOUNDED_ENVELOPES`. This conclusion
is restricted to the declared finite geometry, knot bounds, circle ownership and
observations. It is not physical impossibility or a statement about all models.
A closed upper circle envelope is a conservative impossibility filter; ambiguous
upper equality is retained rather than rejected by approximate radicals.

## Stable interfaces

`build_width_field(points, width, *, junction_points=())` returns a v3 field.
Its knots have `parameter_index` and `parameter_id`; each piece has
`start_knot_weights` and `end_knot_weights`, lists of
`{knot_index, weight}` with exact rational weights.

`prepare_field(field)` returns only the lower/upper product-box envelope for
scope and strict upper-bound diagnostics. Passing a common alpha to that envelope
is not evaluation of a selected independent-knot vector.

`evaluate_vector(black_cells, white_cells, bodies, parameter_vector,
*, owned_black_constraints=())` rebuilds and exactly checks one vector.
`solve_bounded_union` keeps the same black/white/bodies/owned-constraint interface.
A successful result has `parameter_layout`, `parameter_vector`,
`selected_squared_half_widths`, `black_witnesses` (including `body_ids`) and
`white_witnesses`. The flat vector follows body order, then each body's fixed
knot path order. A circle contributes one parameter. Canonical body IDs and
unambiguous actual circle child/source aliases are recorded in the layout.

`extend_endpoint_field(field, end, point)` accepts `end=0` or `end=-1` (also
`start`/`end`). It copies the field and appends one diagnostic piece, using
exactly the original endpoint's knot expression at both new piece ends.
Original pieces, observations, knot bounds and parameter identities are unchanged.
It adds no parameter. The result is explicitly `DIAGNOSTIC_NOT_NATIVE` and may
only test an independently established directed source continuation under the
same black/white/own constraints. It is not a replacement native object.

## Checkpoint and adoption boundary

The second small checkpoint uses unchanged authored pixels, finite geometry and
fixed section positions for clean constant/symmetric/monotone controls, real
short/long tails, wedge/block, and white-gap/hole controls. Wedge and block names
do not predetermine a model verdict. Field feasibility and complete-source
responsibility are reported separately. All original measured section whites
are explicit in the new checkpoint's observations. Frozen real geometry is a
conditional capability check; newly shared geometry must be remeasured later.

Component schema remains `source-finite-component-responsibility-v2-bounded-field`.
Plan schema remains `source-attached-stroke-graph-plan-v4-bounded-source`.
The real source stage, independent saved-byte replay, deletion/movement checks,
and non-target protection remain separate required evidence. Old-object
protection and the existing 20/18-degree source gates are unchanged.
