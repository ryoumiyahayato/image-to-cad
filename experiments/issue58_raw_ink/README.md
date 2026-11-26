# Route B: finite original-ink band candidates

This **non-default experimental candidate generator** tests whether finite
geometry can be proposed directly from original ink without using the existing
source graph as its discovery entrance. It does not modify production code,
call OCR, modify source pixels, or grant source-ownership/adoption approval.
The model is frozen in `FREEZE.json` before the first real-source run.

## Model

1. Threshold the supplied unmodified grayscale image at the existing 128 ink
   boundary. Estimate a local width as twice the median positive local maximum
   of the original-ink Euclidean distance transform. This is an image-derived
   scale, not a target location, expected stroke count, or template.
2. Apply deterministic probabilistic Hough nomination to original black pixels.
   A one-pixel offset grid and one-degree angular grid specify candidate
   sampling resolution, not acceptance tolerances. Votes need two estimated
   widths; finite seeds need four widths (at least six pixels). The Hough gap
   allowance is zero. Hough endpoints do not prove actual stroke endpoints.
3. For every nominated axis, inspect a band with half-width 1.25 estimated
   widths. Recenter its normal offset using the median raw support around the
   finite seed. Divide the band into projection sections of sqrt(2) pixels so
   adjacent source-pixel centers cannot jump a section. Connect sections only
   through actual adjacent original black pixels. Each section retains its
   separate connected components.
4. Enumerate all maximal paths in that directed section graph. This allows
   bent pixel paths within each band and retains alternative branches around
   holes or forks. It is independent of the production skeleton, junction
   pairing, and tracer. A section path is represented by one clearance-weighted
   original-pixel geodesic, **not every possible pixel walk in a thick stroke**.
   The original support sets, side contacts, section splits, and white holes
   remain in the receipt.
5. Mark endpoints as crop censored, band/attachment unresolved, lateral-contact
   unresolved, or a finite-cap candidate. A finite cap is not a completeness
   certificate. Original holes are retained as unresolved loop responsibility;
   no hole is filled, no loop is discarded by an adoption decision.

The constants describe this first candidate search envelope. Four widths is a
proposal length floor; 1.25 widths is a proposal corridor scale. Neither has been
calibrated as a universal recovery threshold. Their limitations must be assessed
on new cases separately. The known private drawing is a development sample,
not a holdout set.

## Bounded search and rejection

The model keeps all nominated axes and all maximal section branch sequences
within explicit resource limits. If an axis has more than 256 paths, **all its
candidates are withheld** and the resource refusal is recorded. More than 512
axes or 4,096 candidate paths withholds the result. There is no unreported top-k
winner. Duplicate identical source paths may share multiple nominated seeds;
competing paths remain separate.

Every candidate is unapproved. The module deliberately returns zero adopted or
complete recovered objects until a separate verifier proves finite boundaries,
source ownership, preservation, native geometry support, and edit isolation.
An 8-adjacent black-pixel path is **not** a proof that every closed pixel cell of
a vector segment is black. Corner cells and independent native geometry require
separate validation. Finding candidates does not by itself satisfy issue #58.

## Reproduction

Dependencies: Python 3.12, NumPy, SciPy, Pillow, and OpenCV. The executed version
records its Python/OpenCV/NumPy identities and source/policy hashes in each JSON
receipt. Source file identity and original crop identity are separate.

```sh
python experiments/issue58_raw_ink/candidates.py \
  --input /private/source.tiff \
  --roi X0 Y0 X1 Y1 \
  --output /private/run/raw_candidates.json
python experiments/issue58_raw_ink/test_candidates.py
```

The rectangle is an explicit experiment selection; its edges are never treated
as actual object boundaries. Do not publish the private JSON receipt, source
pixels, source paths, or private drawing links in the public repository.

The eight synthetic checks cover a real white stripe, censored boundary, wrong
attachment, competing branches, preserved white holes, curved candidate paths,
explicit resource refusal, and exact deterministic replay. They test candidate
behavior and refusals, not successful reconstruction of the real four strokes.

## One controlled seed-model alternative

`candidates_v2.py` keeps the v1 band/branch/path/refusal engine byte-for-byte and
changes only axis nomination. Every original black pixel votes at every one-degree
orientation on the same one-pixel rho grid. All equal 3×3 accumulator maxima above
the finite-length vote floor are retained. A peak must also contain an original
8-connected component within a half-width seed band spanning at least four
estimated widths. Neither neighboring seed discovery nor Hough voting removes
pixels. This explicitly tests the first model's greedy/probabilistic seed omission.
It does not add an object template or a preferred case angle.

`FREEZE_V2.json` binds this model and its unchanged v1 engine. The first execution
under the 512-axis budget is kept even if it stops for resources. The separate
`run_v2_budget.py` entry point supports an explicitly declared axis budget; its
receipt reports original/effective policy hashes and all producer hashes. This
allows every nominated axis to be processed without selecting a convenient
subset. `RESOURCE_FREEZE_V2_1024.json` records the declared budget before that
replay. The per-axis branch and total candidate caps stay unchanged.

```sh
python experiments/issue58_raw_ink/candidates_v2.py \
  --input /private/source.tiff --roi X0 Y0 X1 Y1 \
  --output /private/run/raw_candidates_v2.json
python experiments/issue58_raw_ink/run_v2_budget.py \
  --input /private/source.tiff --roi X0 Y0 X1 Y1 \
  --maximum-seed-axes 1024 --output /private/run/raw_candidates_v2_budget.json
python experiments/issue58_raw_ink/test_candidates_v2.py
```

V2 adds three source-independent checks: all three synthetic slanted strokes
remain nominated in the presence of a crossing line, a genuine white gap still
partitions paths, and identical input/model replay identically. Real candidate
counts, complete-object status and source ownership must still be independently
audited; the generator never adopts these paths.

## Evidence schema correction after the initial freeze

The initial models and their original freeze files are preserved in commit
`23e5e07fb830a844f3855ac04c5b865783b4a843`. Those source hashes bind the original
receipts, not later source files. The subsequent metadata-only correction retains
**every axis explanation** when identical source paths are deduplicated:
`axis_evidence_variants` contains each axis's support pixels, side contacts,
original holes, endpoint descriptions, section sequence and seed provenance.
The earlier top-level fields are explicitly representative only. A matching
source path is not proof that its different axis explanations agree on ownership.
The correction must reproduce the same candidate identities and source paths;
`FREEZE_EVIDENCE_V3.json` binds its source files before that real replay.

**Loop limitation:** an original white hole is recorded and preserved, but this
model does not construct an explicit local return-stroke/loop geometry. A
section-sequence alternative around a hole remains a candidate interpretation;
its shortest raw-pixel representative cannot claim full responsibility for both
sides of a loop. A small cycle in a derived skeleton is not taken as a raw white
hole and does not enter this model as ground truth.
