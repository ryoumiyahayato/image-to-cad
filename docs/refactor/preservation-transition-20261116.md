# Reviewed compact preservation transition — 2026-11-16

This is the explicit compatibility contract for the already synchronized r13
runtime in PR #36. It changes maintenance checks and their tests, not production
processing or exporters. It is not a new conversion-quality or target-CAD
acceptance result.

## Compared revisions and unchanged inputs

- Existing main: `81f364fbe4eee1df00dadefabaef0d1a72993e6e`.
- Synchronized r13 runtime: `d5c05642de7150b254ccccafb8716bf7dfbab503`.
- Separate immutable checkouts and processes, the same CPython 3.12.14 runtime,
  NumPy 2.3.5, OpenCV 4.13.0 and ezdxf 1.4.4; OCR disabled, default 300 DPI,
  no PDF evidence, the same three existing compact inputs at native resolution.
- Network system calls were denied before importing the runtime; telemetry was
  disabled before importing ONNX Runtime. No model download or service inference
  was used for this comparison.

The old main reproduced **every field** of the existing 2026-10-24 compact
baseline exactly in this environment. Both revisions passed the historical LINE
consolidation/source-ink checks. All application source hashes stayed unchanged
during each execution. The version migration was written only after inspecting
the complete identity payloads, cached masks and actual saved DXFs.

## The finite changes actually observed

| Existing input | Final LINE / contours | Old saved DXF | r13 saved DXF |
| --- | ---: | --- | --- |
| processing-contract-page | 14 / 0 | 14 LINE | identical 14 LINE |
| sample-test | 229 / 145 | 229 LINE, 209 LWPOLYLINE | 229 LINE, 195 LWPOLYLINE, 14 HATCH |
| reconciliation-gap-junction | 11 / 0 | 11 LINE | identical 11 LINE |

The two synthetic fixtures have identical complete structure identities and
saved drawing records. On `sample-test`, only the following identity fields
change: the contour-mask hash, the outer contour's four coordinates, and the
point lists of fourteen degenerate raster runs. Every other identity field is
exactly equal, including LINE coordinates, widths and layers,
all remaining contour coordinates and hierarchy, preview/text masks, and
output-relevant presentation. The historical identity does **not** include all
LINE source fields. A separate raw-cache and restored-dataclass comparison proves
that source IDs, history, confidence and classification fields are also unchanged.
The new sample identity is
`62263d27ff70fc2067a8277b5d046d8adfe3c700e3b080c82e8e00ebcdd9e310`.

### Original dark edge restored

The old artifact filter erased a nine-pixel outer band without independent
evidence that the image extent was a physical paper edge. The r13 filter requires
that evidence before applying edge/corner erasure. The actual difference is
**exactly the nine-pixel band: 55,476 original dark pixels restored, zero old
black pixels deleted, zero differences inside the band**. The original JPEG's
grayscale values at all restored pixels are 67–76; none are source white.
The outer contour moves from `(9,9)…(1840,1240)` to the actual image extent
`(0,0)…(1849,1249)`. This does not infer an engineering border or paper boundary.

### Degenerate raster runs retain their actual source cells

The old tracer replaced one- or two-point contours by artificial four-corner
bounding boxes. The synchronized tracer retains the actual source pixel indices.
The exporter emits those unresolved cells as visible solid HATCH members. The
fourteen changed runs occupy **63 source cells**. Each actual saved HATCH was
checked against its source endpoints, closed linear boundary, exact cell set,
layer visibility, color, elevation, extrusion and `RASTER_INK_SOURCE` tags.
There are no added white cells or lost black cells in these run footprints.

This is a source-preserving fallback representation, not a claim that a HATCH is
an adopted editable centerline or that the whole drawing is now satisfactory.

### Actual saved-DXF comparison

On `sample-test`, 15 old members are replaced by 15 new members: one outer
LWPOLYLINE and fourteen source HATCHes. **The other 423 saved entities retain
complete semantic records and order**, including all 229 LINEs and their source
references. Only the verified global structure-version value in P16 LINE XDATA
is normalized for comparison; other source metadata is compared unchanged.
Handles/owners are run-local bookkeeping and are not interpreted as geometry.

Three layer definitions are added by the synchronized exporter:
`UNRESOLVED_RASTER_INK`, `STAMP_OVERLAY` and `SIGNING_SHARED_INK`.
`RASTER_INK_SOURCE` is added to the sample's APPID table. The sample's active
viewport height changes from 1267.93 to 1286.47 to frame the restored outer extent;
its center is unchanged. Other table entries, all nonvolatile header values and
all block definitions are preserved. Each export audits without errors/fixes
and its cache restores the exact current structure identity.

## Checks that remain strict

The original `preservation-baseline.json`, `preservation-current-p10a.json` and
`preservation-current-20261024.json` are byte-for-byte unchanged. The new files are
distinct reviewed contracts:

- [Current exact measurements](preservation-current-20261116.json).
- [Every permitted mask/contour change](preservation-raster-transition-20261116.json).
- [Complete LINE source ledger](preservation-line-sources-20261116.json).

The checker requires the exact current algorithm identity, schema 4 and trace
cache 11. Case coverage and all historical LINE transition declarations remain
unchanged. The current measurements must equal the preceding baseline except
for the specifically reviewed sample identity and saved raster entity counts.
The original sample JPEG is bound by SHA-256.

For the P10-A identity check, a temporary assertion-only projection reverses
exactly the reviewed changes: the actual mask must have the recorded current
SHA-256; clearing only the recorded nine-pixel band must produce the recorded
old SHA-256; each of the fifteen actual path point lists must exactly match its
recorded new value before substituting its recorded old value. The hierarchy is
not changed. The prior empty `closed_scan_curve_records` normalization remains
the only permitted metadata normalization. The projected **whole** structure
must then reproduce the original P10-A identity.

That projection is never exported, cached, or used by the product. A changed
width, unlisted contour, mask pixel, hierarchy or nonempty curve record
is not excused by the migration. LINE consolidation still requires its original
keeper geometry, retained source IDs, equal width and zero unique source-ink
loss. New exact trace reconstruction and saved-HATCH cell checks prevent a
count-only match from hiding source loss or a displaced filled run.

Independent mutation review identified an older checker limitation before this
change was published: altering only `sample-test`'s LINE source ID left its
structure identity unchanged and passed the keeper-only transition check because
that case has no approved LINE consolidations. The old evidence is retained;
the identity is not retroactively claimed to cover that field.

The new separate LINE ledger binds all eleven dataclass fields and the actual
source-list order for **all three cases**, including source IDs, history,
confidence and classification confidence/reasons. The two compared revisions'
raw `lines_json` cache records and restored objects agree exactly. Every current
measurement checks the complete in-memory ledger, raw saved-cache field presence
and ledger, and restored-cache ledger. This guard does not depend on the
geometry identity or on whether a case had a P10-A LINE consolidation.

Negative controls retain the wrong algorithm/schema/cache, wrong keeper and
same-count width failures. Added controls reject a one-pixel run extension,
one missing original border pixel, a white original source pixel falsely used
as restoration evidence, and a shifted HATCH that keeps its entity count, size
and source tags. They also reject a crossing boundary with the same four corner
vertices, white true-color overrides, invisible entities and transparency.
Additional source controls change an ID, history, confidence or classification
while keeping the geometry and structure identity identical, and remove a
default-valued field from raw cache metadata. The complete ledger rejects each.

`--baseline` still refuses regeneration. No previous report is overwritten and
no production threshold or raster decision is changed by this compatibility fix.

## Reproduction

With runtime and test requirements installed:

```sh
QT_QPA_PLATFORM=offscreen python maintenance/preservation_check.py
cd cad_photo_to_dxf
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_preservation_transition.py tests/test_raster_trace.py
```

For an old-version control, execute its own original checker in a separate
checkout. Do not replace the current algorithm string or rewrite an old baseline.
The private comparison evidence includes the exact old/new DXFs, complete
identity payloads, masks/caches, app-source inventories and semantic difference
records. This compact compatibility gate does not establish OCR accuracy,
independent-source generalization, LibreCAD editing, DWG roundtrips or human
time savings.
