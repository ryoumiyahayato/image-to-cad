# Issue 62 — exact whole-source-chain width contract

Frozen before implementation on 2026-11-27. This document refines the numerical
width rules of `ATTACHED_INK_CONTRACT_20261127.md`; it does not authorize changing
source pixels, source IDs, native coordinates, direction thresholds, or existing
formal objects. The issue 60 allowance for derived diagnostic floats is outside
this contract.

## Model and scope

One complete, finite, open, piecewise straight native polyline has one constant
nonnegative half-width. Its rendered geometric model is the union of finite
round capsules for all its segments, at that same half-width. A verified source
chain supplies the provenance for that complete polyline. Width observations may
travel across a junction only with that verified chain and a complete finite
component check. A local absence of independent sections does not establish an
absence on the complete source chain.

The producer must enumerate every directed source port belonging to that chain
and the fixed 6, 8 and 12 pixel observations at each port. It must retain all
observations, including duplicated, contaminated, insufficient and incompatible
ones, with the reason for exclusion. Source direction needs a chord of at least
4 pixels; a short first native segment is preserved and does not replace that
source chord. Distinct projections onto the actual finite native geometry define
distinct section locations. At least two independent sections are required.
Selection by target ID, position, requested adoption count or successful width
agreement is prohibited.

The fixed section half-span is 12 pixels. A section crossing a source boundary,
a forbidden junction core or another finite axis inside the pre-existing
separation bound is not independent. The other-axis set includes noncollinear
finite segments of the same polyline; a nearby bend cannot provide independent
straight-arm width evidence. Collinear segments of the same body share its
axis and constant radius. Both strict white sides must be observed.
All eligible independent sections constrain the **same** width. An empty exact
intersection is `CONSTANT_WIDTH_MODEL_INAPPLICABLE`, including equality at an
open upper endpoint. It is not evidence that native geometry is necessarily
wrong or that the image has been proved to admit multiple CAD interpretations.
No piecewise width or adaptive expansion is introduced by this contract.

## Exact numbers and interval topology

Integer pixels stay integers. A finite supplied binary64 native coordinate is
interpreted as its exact binary rational value; it is not rounded to a nearby
integer, decimal or snapped vertex. Rational JSON records use decimal strings
for numerator and positive denominator. Floating values, when included for
display, have an `_approx` suffix and never determine a comparison.

Let a selected native segment have endpoints `a`, `b`, direction `d = b-a`,
unnormalized normal `n = (-d_y,d_x)`, and `D = n·n > 0`. Project a source sample
exactly onto the finite segment, obtaining a rational point `q`; an independent
section requires a strictly interior projection. A section is the finite normal
segment `{q+t*n : t²*D <= 12²}`. Its closed unit pixel cells are enumerated by
rational line/box clipping and a squared comparison, without approximating a
square root or using a geometry epsilon. Boundary touching cells are included.

For a cell centered at integer `c`, put `u(c)=n·(c-q)` and
`h=(|n_x|+|n_y|)/2`. The black cells connected to the source ink at `q` give
`L=max(0, max_black(|u|-h))`. The first observed white cell on each normal side
gives `U=min_first_white(|u|+h)`. The half-width squared interval is exactly

`[L²/D, U²/D)`.

Its lower endpoint is closed because touching a black cell is allowed. Its upper
endpoint is open because a white cell must retain a point strictly outside the
ink model. All section intervals are intersected by rational maximum and minimum.
The result is nonempty exactly when `max(lower) < min(upper)`. Equality is empty.
This remains exact for different native segment directions; no common square
root or floating tolerance is needed.

The existing other-axis clearance rule is strict:
`distance > 2*upper_half_width + sqrt(1/2)`. Writing `s=distance²`, `u=upper²`
and `v=s-4*u-1/2`, it is equivalent to `v>0 and v²>8*u`. These are exact rational
comparisons. Equality fails independence. The selected segment must also have
an interior projection and its complete source chain must exclude contaminating
cores and other applicable finite paths.

## Finite component responsibilities

Exact geometric helpers measure squared distance to actual finite segments and
closed unit pixel cells. Black-cell coverage is `distance² <= radius²`. A white
cell is accepted only if at least one of its four corners, four edge midpoints
or center is strictly outside **every** participating finite capsule:
`distance² > radius²` for each polyline. Equality is not a white witness. Every
polyline uses one radius for the entire component model; per-cell width choices
are prohibited.

This finite nine-point white rule is a deliberately sufficient raster model; it
does not claim to enumerate every point in a continuous white cell or recover
hidden physical pen travel. A failure of this witness rule is model rejection,
not an independent proof of scan ambiguity. Caps, bends and tails are checked
against finite geometry. Neighbor participants need their own complete source
and width evidence. Unproved neighbors and unexplained component exits remain
pending; an enlarged window cannot silently reclassify them as background.

The component solver freezes a bounding box of the complete target geometry
plus 13 pixels (the 12 pixel section span plus one cell), at most 131072 window
cells and at most 8192 width-event states. Natural window exits require their
own finite-source accounting; clipping is not evidence of closure. Exhaustion
means `RESOURCE_LIMIT_PENDING`; it cannot produce an acceptance. Any complete component containing an unexplained black
cell, an unaccounted white gap/hole, or an unproved exit remains pending.

## Falsification and stopping

The numerical primitive tests must include an actual positive interval, an exact
black touch, a strict white touch, a positive rational interval smaller than a
binary64 ULP, closed-cell/finite-cap cases, and an incompatible pair whose lower
bound equals its strict upper bound. Structural tests must additionally cover
remote same-chain sections, retained short native segments, proved/unproved
neighbors, true tails, holes and gaps. Positive and negative raster cases must
use the same frozen predicates.

The supplied private coordinator counterexample is retained in private evidence,
not copied into public source. It reports a floating interval width of
`4.6407322429331543e-14` pixels. Its integer normal has squared length 873;
the shared twice-numerator is 117, so both exact half-width squared endpoints
are `117²/(4*873) = 1521/388`. The exact interval is empty because the upper
endpoint is open. A generic authored strip pair tests the same open-bound
equality without embedding target coordinates, source pixels or IDs.

Stop for a specific recorded reason: insufficient independent evidence, exact
constant-width contradiction, unproved source continuation/neighbor, incomplete
finite component coverage, failed strict white witness, or finite resource
exhaustion. Do not search additional scales or select a compatible subset after
a contradiction. Reproductions must keep the original rejection and use actual
saved DXF/native geometry and original source pixels; producer PASS flags are
not substitutes for independent evidence.
