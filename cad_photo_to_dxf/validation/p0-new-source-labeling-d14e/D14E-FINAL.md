# D14E P0 new-source blind mining and labeling

## Outcome

`PARTIAL`.

H1 and C1 met their independent qualified-case targets. H2 produced four, not
six, independent qualified cases within the frozen 7-candidate mechanical
review pool. Two H2 proposals followed rendered gray face-shading bands and
were `INVALID_FOR_TASK`; a second gap in the same feature-index title was
excluded as a near-duplicate. The label standard and independence rule were
not relaxed to manufacture the missing two cases.

The resulting prediction-blind dataset has 13 independent qualified cases:
7 `STRUCTURAL_CONTINUATION` and 6 `ANNOTATION_OR_GLYPH`. Every new source
family contains both classes. This is sufficient for a small frozen D14F
generalization measurement, with the explicit limitation that H2 has only one
independent structural positive.

## Fail-closed source verification

The worktree verification passed at base checkpoint
`e98a3c8f74d0412ac8e16401f34febb810885686` on branch
`codex/source-support-lifecycle-instrumentation`, with a clean starting tree.

All 11 acquired files were re-hashed and size-checked against
`../p0-controlled-acquisition-d14d/acquisition-registry.json` before rendering:

- HAER UT-14: four admitted measured-drawing TIFFs matched.
- HAER NY-4: five admitted measured-drawing TIFFs matched.
- NIST FTC 6 Rev D: the admitted three-page PDF matched.
- FHWA WFL Plan/Profile: the admitted 21-page PDF matched.
- Every source binary remained Git-ignored.

No source was downloaded, repaired, replaced, or transformed in place.

## Prediction-blind controls

- No MobileNet, embedding, cosine, ridge, confidence, margin, uncertainty, or
  other learned-model code was run.
- No prior prediction was inspected during page selection, proposal selection,
  or labeling.
- H1 and H2 remain new-source holdouts. C1 remains untouched DEV baseline
  material until its first frozen D14F result is durably recorded.
- Candidate proposal used only grayscale rendering, thresholding, probabilistic
  Hough fragments, collinearity, bounded gap/span checks, and fixed geometric
  deduplication.
- Semantic labels were assigned only after the representative candidate
  registry and review artifacts were frozen.

## Page and sheet selection

The tracked `page-selection.json` was written before candidate generation.

| Family/document | Pages or sheets mined | Selection basis |
|---|---:|---|
| H1 HAER UT-14 | 4 | Entire admitted measured-drawing set |
| H1 HAER NY-4 | 5 | Entire admitted measured-drawing set |
| H2 NIST FTC 6 Rev D | 3 | Entire admitted mechanical drawing |
| C1 FHWA WFL | 6 | D.5-D.10, the first contiguous six-sheet plan/profile run |
| **Total** | **18** | At the specified maximum, without model output |

C1 D.5-D.10 were selected from document structure and low-resolution overview
evidence because they contain plan/profile roadway geometry together with
grids, stationing, leaders, dimensions, and sheet-layout rules. Guidance and
tabulation-only pages were excluded.

## Rendering and proposal generation

HAER master TIFFs were converted to grayscale and aspect-preserving Lanczos
downsampled to a maximum dimension of 2200 pixels. H2 and C1 selected PDF pages
were rendered by Poppler in grayscale at 150 DPI. Local source crops, broader
context crops, and fragment/gap overlays were generated under the Git-ignored
runtime root:

`local-artifacts/draftsman/new-source-p0-d14/D14E/`

A pre-label QA check found that an initial draft had reused the 60-DPI overview
cache. That draft was discarded before semantic labeling. The helper was fixed
to key page renders by DPI, and the durable registry contains only the corrected
150-DPI PDF coordinates and artifacts.

| Document | Raw geometric proposals | Frozen representatives |
|---|---:|---:|
| HAER UT-14 | 1,140 | 7 |
| HAER NY-4 | 1,038 | 7 |
| NIST FTC 6 | 259 | 7 |
| FHWA WFL D.5-D.10 | 506 | 7 |
| **Total** | **2,943** | **28** |

The fixed reduction used page round-robin selection plus orientation and coarse
location clustering. It prevented dense frames and repeated grid regions from
consuming the representative budget. The 28-case registry is below the hard
cap of 30.

## Human review

Sixteen candidates were semantically reviewed, below the hard cap of 24. Review
stopped once H1 and C1 met their targets and every frozen H2 representative had
been resolved. Unreviewed frozen representatives were not assigned labels.

| Order | Candidate | Family | Label | Independent | Diagnostic note |
|---:|---|---|---|---|---|
| 1 | D14E-B891230016C5 | H1 | ANNOTATION_OR_GLYPH | yes | UT-14 drawing-frame rule |
| 2 | D14E-F12FEFEB2245 | H1 | ANNOTATION_OR_GLYPH | yes | NY-4 drawing-frame rule |
| 3 | D14E-82AF53CB94E1 | H1 | STRUCTURAL_CONTINUATION | yes | UT-14 lower chord/deck member |
| 4 | D14E-4ECE70470938 | H1 | STRUCTURAL_CONTINUATION | yes | NY-4 truss lower chord |
| 5 | D14E-CE792322B81F | H2 | ANNOTATION_OR_GLYPH | yes | Aligned feature-index title glyphs |
| 6 | D14E-D8266A189086 | H2 | INVALID_FOR_TASK | no | Gray face-shading band |
| 7 | D14E-210F3F812A66 | H2 | STRUCTURAL_CONTINUATION | yes | Front-face object edge across slot |
| 8 | D14E-10740DFB9AE5 | H2 | ANNOTATION_OR_GLYPH | no | Near-duplicate of order 5 |
| 9 | D14E-7EAB23F9DB29 | H2 | INVALID_FOR_TASK | no | Gray face-shading band |
| 10 | D14E-142FAB52579F | H2 | ANNOTATION_OR_GLYPH | yes | Dimension witness/extension line |
| 11 | D14E-E3358E708EA3 | H2 | ANNOTATION_OR_GLYPH | yes | Aligned footer text glyphs |
| 12 | D14E-FA2DB5B68BA2 | C1 | STRUCTURAL_CONTINUATION | yes | D.5 roadway plan edge |
| 13 | D14E-101604055F6C | C1 | STRUCTURAL_CONTINUATION | yes | D.6 roadway plan edge |
| 14 | D14E-502CA91496D5 | C1 | STRUCTURAL_CONTINUATION | yes | D.7 curved roadway edge |
| 15 | D14E-B93CCEEAA320 | C1 | ANNOTATION_OR_GLYPH | yes | D.8 sheet/panel boundary |
| 16 | D14E-97391B48B08C | C1 | STRUCTURAL_CONTINUATION | yes | D.9 profile-grade line |

Detailed rationales and physical independence clusters are frozen in
`human-labels.json`.

## Qualified label matrix

Counts below include only independent qualified cases. The H2 duplicate is not
counted as qualified independent evidence.

| Family | Structural | Annotation/glyph | Ambiguous | Invalid | Independent qualified | Target |
|---|---:|---:|---:|---:|---:|---|
| H1 | 2 | 2 | 0 | 0 | 4 | MET |
| H2 | 1 | 3 | 0 | 2 | 4 | PARTIAL |
| C1 | 4 | 1 | 0 | 0 | 5 | MET |
| **Total** | **7** | **6** | **0** | **2** | **13** | **PARTIAL** |

One additional H2 annotation case was semantically clear but excluded as a
near-duplicate. No ambiguous case was encountered in the 16 reviewed items.

## Rights and provenance continuity

D14D source-evidence and data-rights records remain authoritative. Every
candidate carries family, document, document SHA-256 or document-set digest,
page/sheet identity, render transformation, exact coordinates, crop boxes, and
runtime artifact paths linked back to the acquisition registry. No contrary
rights notice appeared during the bounded visual review. Rights status remains
`PASS`.

## D14F readiness and limits

`READY FOR D14F FROZEN NEW-SOURCE GENERALIZATION TEST: YES`.

The later test can measure all 13 independent cases because each of H1, H2, and
C1 supplies both qualified semantic classes and none has been prediction
exposed. D14F must report each family separately and must not hide H2's small
one-structural/three-annotation matrix in an aggregate. The two missing H2 cases
must not be sourced automatically; they are a recorded D14E shortfall.

## Governance

- Production semantic delta: none.
- Source documents or bulk rendered images tracked: no.
- New PDF acquisition: no.
- Model run or prediction exposure: no.
- H1/H2 holdout contamination: no.
- VALIDATION inspected: no.
- LOCKED_BLIND runtime exposure: 0 / 8; manual inspection: no.
- Ready for production integration: no.
- Next production change candidate: none.
