# Mandatory real-document regression set

This directory is the non-optional content regression gate for the production
trace pipeline. It is separate from synthetic unit tests and from
`tests/fixtures`, whose stricter CAD-ground-truth qualification policy serves a
different release benchmark.

## Current scope

- 12 full-pipeline fixture runs;
- 10 distinct source pages;
- 3 independent source documents;
- 2 retained original PDFs plus the repository perspective image;
- 5 deliberately low-resolution full-page scan renders;
- explicit 150, 300 and 600 DPI runs;
- OCR, structure analysis, `FinalStructure` preview, DXF export, DXF audit and
  region-level content audit on every run.

The 300 and 600 DPI entries repeat warehouse PDF page 1 only to test physical
resolution behavior. They do not increase `minimum_unique_pages`; the distinct
page gate is calculated from `(source_document, page.number)`.

## Sources and authorization boundary

| Source record | Kind | Pages used | Authorization |
| --- | --- | --- | --- |
| `sample-plan-photo` | repository-supplied perspective raster | 1 | internal project regression only |
| `environment-building-scan-pdf` | 14-page paper scan; one full-page image per PDF page | 1, 2, 3, 4, 8, 14 | internal project regression only |
| `warehouse-electrical-vector-pdf` | 7-page digital vector PDF | 1, 2, 3 | internal project regression only |

The user supplied these project documents and explicitly requested a real
document regression set. That instruction authorizes internal use for this
task; it does **not** establish public redistribution rights. Every manifest
entry therefore sets `redistribution_allowed` to `false`, and public release is
blocked until the rights holder confirms it.

The perspective JPEG has no camera EXIF. Its visible page perspective is useful
for the requested photo path, but its capture hardware is unverified. The
manifest and acceptance notes preserve that limitation rather than inventing
mobile-device provenance.

## Coverage contract

The manifest requires all of the following labels and rejects the complete set
if any label disappears:

1. digital-generated PDF;
2. low-quality scan;
3. perspective photo path;
4. landscape drawing;
5. portrait drawing;
6. dense text;
7. complex table;
8. broken frame;
9. broken table lines;
10. signature adjacent to text;
11. wordmark Logo;
12. graphic Logo;
13. leaders and arrows;
14. dimensions;
15. short and double lines;
16. dashed and dash-dot lines;
17. page without a populated title block;
18. high-resolution large page;
19. 150 DPI;
20. 300 DPI;
21. 600 DPI;
22. mixed Chinese, English and numbers.

`perspective-sample-plan` supplies the “no populated title block” case: it has
an empty lower grid but no populated semantic title block. This distinction is
recorded because the page must not be treated as a known title-block template.

## Per-fixture metadata

Every document entry contains:

- the exact source input and SHA-256;
- the retained original file and SHA-256;
- internal-use authorization and release restriction;
- source page, render DPI, orientation and source kind;
- text regions that must remain;
- labelled real breaks that need repair, when present;
- regions where new connections are forbidden;
- Logo and signature regions, when present;
- at least one key ROI;
- minimum accepted object/pixel presence;
- human acceptance notes.

Empty annotation lists mean “not present on this page”, not “not audited”. The
set-level validator requires non-empty break, forbidden-connection, Logo and
signature annotations somewhere in the corpus. Every page must have at least
one text-preservation region and one key ROI.

## Content audit

The runner creates source and final foreground masks, rasterizes
`FinalStructure` object types, and audits every annotated bounding box. It
checks:

- required foreground and object-type presence;
- added foreground in forbidden-connection regions;
- source and final foreground pixel counts;
- per-type pixels for outlines, lines, text, Logo and signature;
- exact content-audit SHA-256;
- exact structure, preview and exported DXF metrics.

Logo/signature regions may currently accept `preserved_foreground` or
`outline` while declaring a semantic target in the review note. This is an
explicit baseline finding, not a claim that ownership is already correct.
Later ownership phases must update the expected semantic type together with
before/after evidence.

The forbidden-region limits were recorded from the first complete run. A later
run may add fewer pixels but cannot add more without failing. Exact
`content_audit_sha256` also makes any region-level change visible.

## Commands

Run the mandatory gate from `cad_photo_to_dxf`:

```powershell
python scripts/run_real_document_regression.py `
  --manifest tests/real_regression/manifest.json `
  --output output/ci/real-document-regression.json `
  --artifacts output/ci/real-document-regression
```

Bootstrap a proposed baseline only into a different local file:

```powershell
python scripts/run_real_document_regression.py `
  --manifest tests/real_regression/manifest.json `
  --output output/ci/baseline-observation.json `
  --artifacts output/ci/baseline-observation `
  --record-baseline-to output/ci/proposed-manifest.json
```

The input manifest cannot be overwritten by this option. CI never invokes
baseline-recording mode. A proposed manifest must be reviewed, installed as a
normal code change, and then pass the strict command without the option.

## Hard CI failures

The run fails when the corpus is empty or below 10 unique pages, a required
category/DPI is missing, a source/original file cannot be loaded, a hash
changes, OCR is disabled, a skip/xfail control appears, an annotation is
invalid, any pipeline stage raises, the DXF audit fails, or expected content
changes. Exceptions are retained in the report for observability but always
produce a non-zero exit status.

The 600 DPI page is intentionally expensive. It must not be silently
downsampled, skipped or replaced by a thumbnail to shorten CI.
