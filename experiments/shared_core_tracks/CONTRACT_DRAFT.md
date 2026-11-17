# Cardinal shared-core tracks — independent research contract v1

Status: **RESEARCH ONLY; NOT REGISTERED IN ANY PRODUCTION EXPORTER.**

This module tests a narrow source-geometric class: one horizontal or vertical
constant-width black band that passes through retained shared regions and has
at least two independently sufficient exclusive intervals. It changes no r13
threshold, existing short/long compound contract, source-region contract,
production entry, cache identity or DXF writer.

## Purpose and limitations

The source itself proposes the band before any pen check. A skeleton branch
point is not a node decision or a source-retirement authorization. The proposal
does not use skeleton owners, fitted residuals, historical failing coordinates,
expected symbols, manual truth or reference solutions.

The first version supports **cardinal directions only**. Slanted strokes,
curves, arbitrary direction-field pairing and general compound-object recovery
are not implemented. A repeated cross-section does not establish a historical
stroke or an engineering object. Text, logos, signatures and manually protected
sources retain their whole-parent guards; this module cannot discover an
unknown text/logo role from the same bitmap by assertion.

All results record:

- `geometric_contact = OBSERVED_SOURCE_ONLY`
- `historical_object_identity = NOT_PROVEN`
- `electrical_semantics = NOT_INFERRED`
- `full_object_movable = false`
- `production_retirement_authorized = false`

A LINE crossing a retained core overlaps that source. Editing the LINE leaves
the core and guard in place; it is not an independently movable complete
original drawing object.

## API

```python
recover_shared_core_tracks(
    gray, component, foreign=None, *,
    native_gray=None, native_scale=None, dpi=100.0,
    binary=None, visible_binary=None, protected_masks=(),
) -> dict
```

`gray`, `binary` and `visible_binary` are matching two-dimensional working
`uint8` arrays. `component` is a matching boolean complete parent mask.
`foreign` and each protection mask use nonzero for unavailable source.
`native_gray` is the complete matching bitonal original tile; the isotropic
integer scale is 2–16 and `dpi` is working DPI.

The caller must supply actual `binary` and `visible_binary`. Their absence
returns `SOURCE_STATE_REQUIRED`; the method does not silently assume current,
unclaimed source. No input array or DXF is modified.

Before original-source registration succeeds, a rejection has
`no_mutation=true` and no native source/residual ledger. That is a whole-parent
abstention, not an empty emitted source. After registration, the result carries
complete native source and residual runs even when every proposal is rejected.

## Whole-parent preconditions

The method checks all of these before proposing bands:

1. Correct shapes/dtypes, finite positive DPI and bounded tile/source sizes.
2. The parent is a complete internal 8-connected component of actual
   `gray < 254`; it does not meet the working tile boundary.
3. Every parent source pixel remains dark in current `binary` and unclaimed in
   `visible_binary`. Any overlap with a foreign/protection mask rejects the
   whole parent.
4. Original pixels are only 0/255, have the declared integer ratio, and match
   the working observation after BOX sampling (at most one gray level,
   foreground mask exactly equal), following the existing registration rule.
5. The native parent is the original-black subset of the repeated working
   parent. It contains complete native connected components and does not meet
   the native tile boundary. A working component may contain multiple original
   components; they remain separate source, and no white gap is bridged.

Protection includes every passed mask, regardless of which proposed band would
otherwise avoid it. Source arrays are hashed and checked unchanged.

## Source-only proposal

For a horizontal candidate, each original-native column is decomposed into
complete contiguous black runs `[lo, hi)`. Vertical candidates use the same
operation after transposing the source.

A repeated exact run proposes that exact normal interval. A station belongs to
the band only if **every original pixel** in `[lo, hi)` is black. Any white
pixel breaks the band; no morphological closing, interpolation or bridge is
performed. Every maximal consecutive all-black span is recorded.

Within that span:

- An **exclusive station** has an actual complete contiguous run exactly
  `[lo, hi)`.
- A **shared/unknown station** has a strict superset run containing the band.
  Its extra width could be a branch, a crossing, a single-pixel side spur or
  another unresolved structure. The method does not decide which.
- The entire parent's source in a shared station is retained, not just the
  part inside the band. Its source-defined guard also retains the entire
  parent at those stations.
- Exact exclusive intervals and all source runs are logged. A single-pixel
  side spur changes the complete run and therefore enters retained shared/
  unknown source even if thinning would give no branch node.

A candidate needs at least two exclusive intervals and a shared region. Every
exclusive interval must independently meet the requirements below; an internal
short interval rejects the **whole** track. It is never deleted or skipped to
join two other eligible intervals.

## Fixed width, guards and exclusive retirement

Let native source width be `w = hi-lo`, integer scale `s`, and working DPI
`d`. The standard lineweight is the nearest member of the unchanged r13 pen
table, with lower code breaking exact distance ties. Its native width is
`p = code*d*s/2540`.

The fixed collar is:

```text
c = max(2*s, w + sqrt(0.5)*s, p + sqrt(0.5)*s)
```

This includes the old pen-based collar and is at least as conservative using the
original source width. Shared station intervals are expanded in station
coordinates by `ceil(c+w/2)`. This is a retained-source guard, not a node-merge
distance; two nearby cores remain separately logged, and overlapping guards
simply remove retirement eligibility.

For an exclusive source station interval `[a,b)`, only integer stations
strictly inside

```text
(a + w/2 + c, b - 1 - w/2 - c)
```

can enter its fixed retirement domain. Shared guards are excluded before
fitting. All other original exclusive cells remain visible collar source.
The complete run at each eligible station is included; a pen test cannot pick
only its conveniently covered black pixels.

Each resulting exclusive interior must be one continuous interval and have:

- At least **12 distinct consecutive original-native cross-sections**.
- At least **2 mm** between its first and last retired station centers.
- Native effective length divided by original width at least **8**.

Evidence from separate short arms is not summed to meet any of these limits.
Original width must remain in the r13 width range. Nearest standard pen edge
shift must be at most **0.25 working pixel**.

## Source conflict selection is frozen before fitting

All proposed bands, exclusive runs, core runs, guards, collars, retirement
runs, fixed widths and source rejection reasons are produced first.

Eligible bands are ordered by descending original band span, then axis and
source bounds. A track is selected only if its fixed retirement does not
overlap an earlier retirement or a prior mandatory-retention promise, and its
own mandatory-retention promise does not overlap an earlier retirement.

This resolves the literal whole-column preservation rule for a cross: a
horizontal track can preserve an entire vertical branch column, preventing a
vertical track from later retiring that promised source. This first version
may recover only one direction.

The resulting manifest and source hashes are bound by SHA-256 **before** pen
checks. A failed selected track does not promote a previously rejected
conflicting alternative. No repeated fitting or search for a passing subset
occurs.

## One phase-fixed LINE check

For horizontal band station range `[start,stop)`:

```text
normal coordinate = (lo + hi - 1)/2
longitudinal endpoints = start + w/2, stop - 1 - w/2
```

Vertical coordinates are transposed. These values use original cell phase and
source width; there is no optimizer. Each endpoint's remaining source collar
stays visible. Working center coordinates are
`(native_center + 0.5)/scale - 0.5`.

The entire band is observed black, including retained cores; the centerline
does not cross a native white gap. The single chosen width and endpoints are
then checked without changing the frozen retirement:

- Source-to-pen and pen-to-source sampled boundary error at most **one native
  pixel**, using the existing distance helpers.
- Round, butt and square caps evaluated at the complete original tile's pixel
  centers, without epsilon or clipping away relevant bounds.
- Every retired source center covered by **its own** pen for every cap.
- Residual source plus pen preserves all original black/white centers.
- No foreign/protected pixel-center contacts.
- The pen stays inside the audited native tile.

A two-vertex LINE has no internal join. Thus three caps are the three distinct
geometries; changing round/mitre/bevel join labels adds no new geometry. The
result does not pretend to have exercised a multi-vertex nine-style curve.

## Mandatory subsequent independent checks

Passing the method's own source and center checks creates only a
`RESEARCH_CANDIDATE`. The result explicitly retains
`continuous_geometry_and_joint_contact_status =
NOT_YET_INDEPENDENTLY_VALIDATED`.

Independent review must still check full continuous ink/paper correspondence,
foreign and protected source-cell contacts, every allowed residual/core
interface, combined candidate contact, true short-spur source retention,
holes/white gaps, DXF saved geometry, complete backups and non-target
preservation. No existing exporter accepts this new contract.

## Outputs and finite budgets

The result exposes:

- `source_proposal_manifest` and `proposal_manifest_sha256`.
- `source_proposed_bands`, including every source reason and fixed selection.
- `candidates` with native/working points, actual standard lineweight, complete
  retired/source/core/guard/collar runs and per-cap audit.
- `decisions`, including source rejection and pen-check rejection separately.
- Complete native parent/residual runs and pixel counts after binding.
- Input-unchanged and exact source-partition assertions.

Runs are native-tile-local `(y,x0,x1)`, half-open and canonical via r13
`_runs`. Resource limits are 100,000 working pixels, 1,000,000 native pixels,
8,192 working parent pixels, 4,096 section keys, 512 proposed bands and
2,000,000 candidate-key/station checks. Exceeding a budget abstains on the
whole parent; it does not use a partial candidate list.

## Implementation freeze

First independent-control freeze:

- Method file: `proposal.py`
- SHA-256:
  `0b357583d7a2f0aa39267307a782e82aec5890bc633df979526bf67257d5279d`

A diagnostic-ledger correction preceded this freeze: early abstention no
longer publishes an empty residual ledger, and candidates explicitly report
their fixed retired pixel count. No actual source was processed by this
implementation task. Whether the class has a useful real positive remains
unknown; **NO_GO is an acceptable outcome**.

