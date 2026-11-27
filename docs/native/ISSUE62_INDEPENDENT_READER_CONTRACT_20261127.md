# Issue 62: independent saved geometry and source acceptance

Frozen before the new saved-reader development controls and real-material run.
This contract supplements `ISSUE62_FINITE_COMPONENT_CONTRACT_20261127.md`.
It introduces a new reader identity; it does not reinterpret issue 60's results.

## Inputs and independence

The reader opens the actual saved DXF bytes and an externally specified source
frame. The source image is separately reopened and hashed before source
acceptance. Optional expected hashes are checked against bytes, never copied
into an approval field. No producer PASS, target chain, adoption count, or
claimed ownership becomes an independent observation. XDATA supplies a stable
object locator only. Missing or duplicated formal identities are recorded and
block complete acceptance; their geometry is retained as context.

The paper-to-source affine map uses the exact rational value of the saved
binary64 coordinates and the existing binary64 `25.4 / dpi` scale. Fractions
are preserved for exact decisions; display floats are not another tolerance.
The external ROI and DPI must be finite and valid. Actual drawing units must be
millimetres. A different frame, font, source, or DXF creates a different receipt.

All actual finite LINE and open zero-bulge, zero-width LWPOLYLINE vertices remain
in order, including short first segments and bends. Curves are never replaced
by endpoint chords. Unsupported width, elevation, extrusion, thickness, closed
paths, and zero-length segments remain explicit. Block members are transformed
from the actual saved INSERT. Every skipped transform, recursive reference,
multiple INSERT, clipping extension, or resource boundary remains unresolved;
partial enumeration cannot become complete source acceptance.

A planar, straight, zero-width closed polyline has a conservative vertex-box
context enclosure, including its closing segment. It still cannot become an
open finite source body. Lack of a responsibility model does not invalidate an
independently available geometric enclosure.

## Certified text subset

TEXT context can have a conservative outline enclosure only when all of these
conditions are checked from the saved entity and verified font bytes:

- left/baseline alignment, zero rotation, zero oblique and generation flags;
- planar positive height and width, without thickness or extrusion changes;
- literal single-line text without DXF formatting/control escapes;
- one explicit font binding with matching SHA-256, no system fallback, no big
  font, and a character-map entry for every character;
- an ordinary scalable font decoded by the bound fontTools/ezdxf renderer, with
  positive finite cap height and complete finite contours.

The font is opened from the already hashed bytes in a new TTFont/TTFontRenderer,
not from a path-keyed global font cache. The renderer's raw Bezier control-point
convex hull encloses its complete decoded outline. Exact rational scaling by
the saved height and width, baseline correction, insertion and source affine
produces a conservative source enclosure; only its displayed binary64 bounds
are rounded outwards. The receipt records font and decoder identity and the
layout conditions. This is an outline enclosure for that frozen font/layout
model, not an OCR result, hinting model, or guarantee about arbitrary CAD font
substitution.

Unsupported text is unknown context. A certified enclosure disjoint from the
local observation window is excluded locally. An intersecting certified
enclosure is possible related context, not an asserted ink conflict. An
uncertified extent cannot be excluded by an approximate box; it stays unknown
until a conservative enclosure or separate source separation is established.
Consequently a count of uncertified TEXT entities is never reported as a count
of conflicts.

## Independent source evidence and statuses

The next acceptance layer rebuilds a fresh source graph and matches all its
edges against actual saved finite bodies. Candidate locations may reduce the
search scope but never supply the matched source route as truth. Every edge
must have unique applicable ownership, a continuous finite route, unchanged
direction gates, independently observed width sections and endpoint evidence.
Nearby bodies must independently meet the same conditions before explaining
component ink. Ambiguous routes and unsupported necessary bodies remain
pending.

Complete source PASS requires all of: actual finite support, an independently
unique complete route, every required exact width interval, a simultaneous
whole-component black/white witness, justified exits/free ends, exact finite
contact and duplicate checks, no observable boundary competitor, and resolved
relevant context. It may reuse the reviewed exact arithmetic kernel only after
independent saved-geometry reading and source reconstruction.

The reader alone never emits `COMPLETE_SOURCE_PASS`. A proved empty constant
width interval is `MODEL_NOT_APPLICABLE_CONSTANT_WIDTH`; it does not prove that
the saved geometry is wrong or that the scan is intrinsically ambiguous.
Insufficient evidence, unsupported layout, unknown exits and exhausted resource
budgets remain specifically pending. A genuine geometric contradiction is
reported with its finite witness. Invisible travel inside already explained
host ink uses the frozen finite-host-intersection editing convention; physical
pen history is not claimed.

## Falsifiers and resource boundary

Development controls must include actual saved positive geometry and font
bounds, changed saved geometry/source bytes, missing necessary body, wrong font
hash, missing glyph, changed layout, a curved/finite-width member, duplicate or
missing identity, and a skipped block instance. A nearby unknown must block
complete acceptance; a proven distant text bound must not invent a conflict.

The reader limits block depth to 16, emitted members to 100000 and literal text
to 4096 characters. Exceeding a limit leaves an explicit unresolved record.
The source kernel keeps its separately declared bounds. No omitted member,
truncated competitor search, or partial constraint ledger counts as complete.
Private coordinates, identifiers, fonts and source images remain outside Git.

The independent route matcher uses the existing 1.5-pixel candidate and 2-pixel
prior-body source-distance limits, all graph edges, and the unchanged 20-degree
continuation / 18-degree margin tests at all three source spans. At most 32
finite bodies and 32 route edges per body are accepted by this local matcher.
Every original core adjacency is retained; at most 64 simple core walks and
8192 walk states are enumerated. The first independent positive subset covers
tree cores with no internal source endpoint or original white hole; a cyclic
core is explicitly pending in this reader even when a producer has a separate
cycle proof. This is a declared acceptance subset, not an asserted source error.

### Bounded-neighbor clarification before the final frozen replay

The first saved development probe retained an unresolved remote prior-body end
outside the target observation window. Requiring that remote end's next object
would expand the neighboring network beyond this task. The local certificate
therefore covers every target end, every relevant original cell and each
necessary finite shaft through its proved window exits. A necessary prior
body's terminal outside that window is explicitly marked out of scope; it is
not newly certified as a free end or attachment. Its actual finite geometry,
entire assigned source route and all independent width constraints are still
checked. The kernel must independently prove the same shaft's source on both
sides of each window exit. Missing or ambiguous exits remain pending.

Also, the observed thinning node is a direction locator, not the center of a
physical round cap. A free target uses the observed free-node identity, the
unmodified connected cap measured from the actual saved endpoint with the
existing three-pixel forward cap bound, and the simultaneous finite union.
The edge-to-finite-geometry distance limit remains unchanged. An extra
endpoint-to-thinning-node coincidence test is not part of this source model.
The first development receipts are preserved under their original code hashes.

Positive-length source support is reported separately for targets and necessary
prior context. A remote prior segment's exact white crossing is retained as a
dependency failure, not reported as a contradiction of the new target geometry.
Any such unresolved dependency prevents complete acceptance. Route/context
failures or a proved empty complete-chain width stop before the joint model and
continuation search; a partial set of independently reconstructed bodies cannot
establish complete feasibility or exclude competitors.
