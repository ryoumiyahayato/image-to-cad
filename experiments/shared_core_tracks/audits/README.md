# Independent cardinal source eligibility audit

This is a read-only diagnostic for budget-abstained source manifests.
It does not import the recovery proposal, call a geometry fitter, create a CAD
entity, change the producer's 512-band budget, or authorize source retirement.

## What it checks

The audit independently enumerates original-bitonal cardinal bands using
complete run-containment queries and one-dimensional interval arithmetic.
It applies the frozen source requirements: exact exclusive sections, retained
superset cores and guards, at least two exclusive intervals, and **every**
exclusive interval independently meeting 12 consecutive native sections,
2 mm and aspect ratio 8 after collars. It also uses the frozen standard width
table and source-only conflict selection.

The implementation does not allocate a complete tile mask for every proposed
band. Compact source runs are reconstructed arithmetically for comparison with
saved manifests.

A passing source requirement is only a necessary condition. The diagnostic
does not test actual pen geometry, continuous topology, joint contact,
source-to-CAD export or editing benefit.

## Fixed two-stage procedure

1. `compare` reads the already saved complete source manifests, verifies input
   and output hashes, and independently compares all source descriptors,
   interval arithmetic, run ledgers and source-only decisions.
2. Freeze the audit script, original input manifest, original producer summary
   and successful comparison report by SHA-256.
3. `budget` requires that freeze, then examines the previously budget-abstained
   sources exactly once. A run-start file uses exclusive creation so the same
   diagnostic output directory cannot silently replay this stage.

The original producer results remain unchanged: their status is still
`SOURCE_BAND_BUDGET`. A separate conclusion may exclude them by the frozen
source necessary conditions. That does not become an additional producer pass
or a recovered candidate.

## Invocation

Use a fresh diagnostic output directory. All source paths are explicit CLI
arguments; the script contains no fixed workspace paths or private source
coordinates.

```bash
python audit_source_eligibility.py --phase compare \
  --inputs INPUT_DIRECTORY --results SAVED_PRODUCER_DIRECTORY \
  --output NEW_AUDIT_DIRECTORY

python audit_source_eligibility.py --phase budget \
  --inputs INPUT_DIRECTORY --results SAVED_PRODUCER_DIRECTORY \
  --output NEW_AUDIT_DIRECTORY --freeze AUDIT_FREEZE_JSON
```

`INPUT_DIRECTORY/manifest.json` supplies frozen input metadata, hashes and
source arrays. `SAVED_PRODUCER_DIRECTORY/summary.json` supplies the immutable
producer result paths and hashes. The freeze JSON must contain:

- `audit_script_sha256`
- `input_manifest_sha256`
- `producer_summary_sha256`
- `reference_comparison_sha256`

This audit version deliberately requires **44** completed reference parents
and **5** budget-abstained parents. Those are evidence cardinalities, not
source-location rules or adjustable geometry thresholds. A different cohort
needs a separately reviewed audit version; do not edit the frozen script
while reusing its previous comparison result.

The supplied manifests are trusted, pre-reviewed, hash-bound project evidence.
This command-line diagnostic is not an untrusted-manifest ingestion service.
It uses Python's POSIX `resource` module; its measured runtime is Linux.
Public source consists only of this script and README; original NPZ data,
coordinates, detailed source runs and private reports belong in the separate
private evidence delivery.

## Evidence and interpretation

The completed reference comparison matched 44 parents, 4,755 enumerated bands
and 43,734 source-run fields, with zero differences. The subsequent
source-only diagnosis completely enumerated 5,935 bands across the five
budget-abstained parents and found zero source-eligible bands. This closes the
budget uncertainty **for this frozen cardinal contract only**. It does not
exclude slanted, curved, differently parameterized or manually reviewed
representations.

No producer, pen renderer, optimizer or full-page conversion was run by this
audit. No DXF was created, and no local CAD task arises from this diagnostic.

Before using any result, check its per-case `differences`, input hashes and
`source_input_arrays_unchanged`; nonempty differences invalidate its conclusion.
The observed delivery has no such differences. The script's source-only
summary does not substitute for independent production adoption checks.

