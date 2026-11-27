# Issue 62: finite shared-vertex construction amendment

This amendment is frozen after the first synthetic development run and before
applying the new model to the real source. The original contract and first
development failure are retained. It changes candidate construction only; the
constant-width physical model, strict white bounds, source direction gates and
existing valid drawing remain unchanged.

## Observed reason

The first complete-component positive control has coherent independent widths,
finite black/white coverage and closed shaft exits. One guest endpoint computed
by the existing floating intersection is not mathematically on its host segment.
Its distance is tiny but positive. A source-model PASS cannot relabel that fact
as an exact saved CAD contact. Merely using the old 1e-7 coordinate comparison
would leave this mismatch in the actual finite geometry.

## Construction, before all new acceptance checks

Only a **new candidate host** may receive an additional vertex at an already
source-supported guest endpoint. No prior formal object or guest point changes.
Every original host vertex is retained, with its original value and order.

The unique guest/host attachment must already be established by the existing
complete source-route decomposition and independently supported original core.
The guest endpoint must lie in that core's closed original pixel cells. Its
exact projection onto the original finite host segment must have `0 < t < 1`.
An endpoint beyond the finite host is never a reason to extend that host.

The exact point-to-host distance must not exceed the existing 1e-7 pixel
construction precision. This is only a maximum **permitted construction change**,
not a contact epsilon: after construction the new gate requires exact zero
distance. Points already exactly on the host need no insertion unless another
insertion changes their original segment: then they too become retained shared
vertices, so fixing one attachment cannot break another attachment. Equality and
duplicate removal use exact values only. Multiple inserted points on a segment
must have strictly increasing exact projection parameters; ambiguous ordering,
zero-length new segments or resource overflow is pending.

All resulting host segments must meet only original closed black cells, using
exact segment/cell clipping. Even an arbitrarily small change can touch a white
half-pixel boundary, so its small size never bypasses this check. The complete
source chain and every retained core encoding must still lie within the existing
finite native-fit bound. Entire-component width, caps, coherent black/white model,
companions, old/new contacts and duplicate checks run **after** construction.
New candidate IDs derive from the resulting geometry; old IDs are not patched.

The producer records pre-construction geometry, exact distances and parameters,
inserted vertices, resulting geometry and IDs. The independent acceptance reads
the actual newly saved geometry and reconstructs source evidence anew. Prior A
source/edit results and pre-construction geometry checks are not inherited.

## Required falsifiers

Normal non-axis-aligned finite contacts must become exact shared contacts while
retaining all old vertices. A near point with no independent core, a projection
outside the finite host, a point beyond the construction bound, competing points
at the same projection, and any new white-cell crossing must refuse construction.
The real right-stroke strict-empty constant-width witness remains a negative
control; inserting a host vertex cannot authorize incompatible guest widths.

This is a finite-geometry representation repair, not a proof of pen history or
a new adoption. Any subsequent source or saved-file failure still leaves the
whole component pending.
