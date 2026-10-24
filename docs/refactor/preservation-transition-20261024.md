# Reviewed compact preservation transition — 2026-10-24

This is a storage/identity contract migration for PR #35, not a new conversion
algorithm or real-drawing acceptance result.

## Compared revisions

- Prior main: `76b4c8c3ce27daec0d49796ba7737b6197a4c849`.
- Synchronized product candidate: `e4509f7b06e771c0cbf57175fff4c33228bc95b5`.
- Runtime: isolated CPython 3.11.17, NumPy 2.4.6, OpenCV 4.14.0.94,
  ezdxf 1.4.5, Qt/Shiboken 6.11.2, Linux, OCR disabled.
- Inputs: the three existing compact fixtures, unchanged native resolutions
  and default 300-DPI processing configuration; no PDF evidence or model run.

The two revisions were checked out separately and executed in separate
processes using the same environment. The old main reproduced the original
P10-A current baseline exactly. The candidate passed every historical LINE
transition and source-ink obligation before a new baseline was written.

## What actually changed

The algorithm identity changed because the synchronized runtime contains the
subsequent source, display, review and native-area implementations. Reverting
that identity to the P10-A value would misidentify the runtime and cache key.

| Existing input | LINE | Contours | Saved DXF entities, old and new |
|---|---:|---:|---|
| processing-contract-page | 14 | 0 | 14 LINE |
| sample-test | 229 | 145 | 229 LINE, 209 LWPOLYLINE |
| reconciliation-gap-junction | 11 | 0 | 11 LINE |

For all three cases, the complete identity payloads were compared, including
coordinates, widths, source IDs, history, classification, contour point lists,
mask fingerprints, and output-relevant presentation. The saved model-space
entity attributes and LWPOLYLINE vertices were also compared after excluding
run-local handle/owner values. Those drawing records were identical. New
source-reference XDATA is separate metadata; this is not a claim that the DXF
files are byte-identical or have identical XDATA.

Only `sample-test` has an identity-payload difference:

```text
stroke_presentation.closed_scan_curve_records: absent -> []
old structure_id: b8e8623f6848a59cd55a41f36e2ca67d505f2ca16365ffdaa08a30f894360c3a
new structure_id: 7e8f3fe8dcdd8bcdae7b0330f476fab0c88c6bc6f8461c65d48bc3298fe4c757
```

The scan-curve qualification ran with zero checks and no qualified curve on
that sample. Its empty record list is part of the existing observable-identity
payload, hence the new fingerprint. The other two fixture identities did not
change. Additional non-identity provenance records the current processing
algorithm and scan-curve diagnostics. Native fills are empty in all three.

## Contract retained and added

`preservation-baseline.json` and `preservation-current-p10a.json` remain
byte-for-byte unchanged. `preservation-current-20261024.json` is a distinct,
reviewed current contract. It keeps schema 4 and trace cache version 11; no
product configuration or algorithm is changed by this migration.

The checker now requires all of the following:

1. Exact current algorithm, structure-schema and cache-format identities.
2. Exactly the same cases, geometry/output measurements and historical LINE
   transition declarations as the immutable P10-A contract.
3. The actual structure must reproduce the P10-A identity after removing only
   an **empty** `closed_scan_curve_records` entry. A nonempty record, changed
   width, source ID, geometry, mask or other identity field is not excused.
4. Existing approved LINE consolidation still requires original keeper
   geometry, retained source IDs, equal width and zero unique source-ink loss.
5. Exact new current identity/count/coordinate/DXF measurements, valid DXF
   readback and matching cache structure identity.

The `--baseline` regeneration shortcut remains rejected. Negative controls
cover unexpected algorithm/schema/cache changes and a width change that
leaves entity counts unchanged. No assertion was deleted or converted into
a skip. New public native-area controls separately verify trace-adapter,
cache and DXF preservation, and reject missing, empty or recolored native
area payloads against the saved fingerprint.

## Reproduction

From a clean checkout with the runtime and test requirements installed:

```sh
QT_QPA_PLATFORM=offscreen python maintenance/preservation_check.py
cd cad_photo_to_dxf
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_preservation_transition.py tests/test_native_fill_storage_contract.py
```

To reproduce the old control, run the old revision's original checker in a
separate checkout; do not replace the current application's algorithm string.

This contract does not evaluate real OCR, native-PDF migration, GUI editing,
independent sources, whole-drawing quality or human labor savings. Those
evidence boundaries remain unchanged.
