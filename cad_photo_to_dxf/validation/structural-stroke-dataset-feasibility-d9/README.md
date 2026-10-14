# Structural stroke dataset feasibility D9

## Decision

The existing source-visible DEV evidence in this worktree is **not sufficient for
a defensible prototype**, and D9 cannot yet determine whether the full already
allocated DEV corpus would be sufficient after mining. The authoritative split
contains 15 independent DEV source groups. The acquisition manifest says ten had
previously reached `EVALUATION_READY`, but the corresponding
`local-artifacts/draftsman/corpus-v1/dev` directory is absent from this worktree.
Five groups were never materialized. Checked-in source-visible diagnostics cover
only `A2-SG-009`, `A2-SG-022`, and `G0R2-3560D9BEBEAA3543`.

The qualified target pool therefore remains seven structural continuations from
two source groups, four annotation/glyph hard negatives from one source group,
and one genuinely ambiguous source case. `G0R2-3560D9BEBEAA3543` supplies useful
structural and intentional-opening controls, but no checked-in fragmented-pair
candidate suitable for this task. Holding out `A2-SG-009` leaves no hard
negatives; using it for training leaves no independently sourced hard-negative
test. A source-group split is impossible.

This is a materialization/mining blocker, not evidence that genuinely new PDFs
must already be acquired. First restore the seven previously materialized DEV
sources inside this worktree (without using the forbidden parent worktree), mine
them with a fixed label-blind proposal policy, and perform human source review.
Only if that pass still fails the source-group gate should new documents be
acquired.

No VALIDATION source was used. LOCKED_BLIND was neither opened, rendered, OCRed,
inspected, mined, nor executed. No model was trained and no production code or
behavior was changed.

## Human labeling rubric fixed before counting

The question is: "Can a competent human, viewing the candidate-aligned region and
sufficient surrounding source context, determine whether the apparent
continuation is a real engineering structural stroke or annotation/glyph
structure?"

- `STRUCTURAL_CONTINUATION`: visible source context supports one physical
  structural stroke across the detector gap. Mere collinearity is insufficient.
- `ANNOTATION_OR_GLYPH`: visible context associates the apparent stroke with a
  dimension/extension chain, arrow, tick, leader, text, digit, marker, or glyph.
- `AMBIGUOUS`: damage, clipping, overlapping roles, or conflicting/insufficient
  source evidence prevents a confident semantic label. Do not force a class.
- `INVALID_FOR_TASK`: the case does not test a fragmented-pair structural versus
  annotation/glyph ambiguity.

Detector and handcrafted measurements may nominate a region only. They may not
provide its label. The counts below retain only prior source-visible human
qualifications; D5/D6/D7 feature outcomes are not labels.

## Existing DEV source-group inventory

`Prior materialization` is copied from the checked-in acquisition manifest;
`available here` means that source-visible evidence exists in this worktree.
Unknown candidate content is not inferred from drawing-family metadata.

| SOURCE_GROUP | Drawing type | Source status already known | Degradation already known | Structural candidates? | Dimension/text hard negatives? | Candidate diversity | Existing artifacts available here? | New replay required? |
|---|---|---|---|---|---|---|---|---|
| A2-SG-009 | historical other-electrical plan | native JPEG; confirmed raster | degraded archival scan | yes: thin H/V fragmented rules | yes: dimension/text-like chains | degraded, thin, horizontal/vertical, nodes, text adjacency | yes: D1/D2/D5-D7 reports and D5 contact sheet; raw corpus file absent | yes, only to expand beyond qualified seed |
| A2-SG-010 | historical panel schedule | native raster image per split registry | unknown | unassessed | unassessed | unassessed | no; never materialized | blocked pending materialization/rights review |
| A2-SG-022 | electrical as-built, lighting/power | PDF; vector/raster status unknown | unknown/cleaner control | yes: thick horizontal boundary | none qualified | thick/thin structural, multi-bay | yes: D1/D2/D5-D7 reports; raw PDF absent | yes, to mine annotation candidates |
| G0R2-15EE2398726E8037 | Japanese municipal other-electrical set | 21-page PDF; status unknown | unknown | unassessed | unassessed | potentially multi-page | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-3560D9BEBEAA3543 | Taiwanese single-line plan set | 47-page PDF; status unknown | unknown/clean control | no qualified fragmented pair; intact control only | no qualified hard negative | thin structure, text/symbol adjacency, intentional openings | D1/D2 full-page diagnostic metadata only; raw PDF absent | yes, to nominate target pairs |
| G0R2-3B970FD759C6026F | Japanese lighting/low-voltage/panel set | 133-page PDF; status unknown | unknown | unassessed | unassessed | potentially broad type/page diversity | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-4A34D1B8D93B1B06 | Chinese lighting/power set | 79-page PDF; status unknown | unknown | unassessed | unassessed | potentially broad type/page diversity | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-53C88494D6CE893C | Australian other-electrical plan | PDF expected | unknown | unassessed | unassessed | unassessed | no; never materialized | blocked pending materialization/rights review |
| G0R2-6C9464FA73A2A027 | Japanese fire-alarm/lighting/low-voltage/panel set | 20-page PDF; status unknown | unknown | unassessed | unassessed | potentially broad annotation diversity | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-7E30C7F445081F40 | Australian electrical-services appendix | 167-page PDF; status unknown | unknown | unassessed | unassessed | potentially broad type/page diversity | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-AFE53C2A00EB7D8F | Australian lighting/power plan | PDF expected | unknown | unassessed | unassessed | unassessed | no; never materialized | blocked pending materialization/rights review |
| G0R2-B441E5911528F402 | historical HABS other-electrical set | 79-page mixed PDF | archival; degradation unqualified | unassessed | unassessed | likely historical/style/degradation diversity | manifest says previously materialized; unavailable here | yes after restoration |
| G0R2-C2D095E069663C17 | Australian lighting/power appendix | 6-page PDF; status unknown | unknown | unassessed | unassessed | potentially modern clean diversity | manifest says previously materialized; unavailable here | yes after restoration |
| SGC-008 | US panel-schedule/power set | vector PDF expected | unknown | unassessed | unassessed | unassessed | no; never materialized | blocked pending materialization/rights review |
| SGC-024 | US power set | vector PDF expected | unknown | unassessed | unassessed | unassessed | no; never materialized | blocked pending materialization/rights review |

Inventory result: 15 DEV registry groups inventoried; 10 are recorded as prior
`EVALUATION_READY`, 5 as not materialized, and only 3 have checked-in diagnostics
that permit any source-semantic assessment in this worktree. Registry allocation,
page count, and drawing-family metadata are not candidate labels.

## Qualified candidate registry

Coordinates are `[x1,y1,x2,y2]` in the recorded page coordinate system. The local
reference for A2-SG-009 candidates is the representative
`../detection-fragmentation-d5/discovery-contact-sheet.png`; broader numeric
context is in `../multiscale-structural-evidence-d7/diagnostic-report.json`.
`D2-006` and `D2-R02` reference their D2 registry ROIs. The exact paired-view D8
training crops were not materialized, so these are seed labels, not ready-made
training examples. Detector fragment IDs were not persisted by the D5-D7
diagnostics and are explicitly recorded as unavailable.

| Case | SOURCE_GROUP | Label | Source coordinates | Human-semantic reason | Local / broader reference | Detector fragment IDs |
|---|---|---|---|---|---|---|
| D2-001 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[1322,481,1322,998]` | visually verified upper-plan rule; same structural identity/endpoints | D2 ROI `[1210,440,260,620]`; D7 local/meso/wide measurements | unavailable |
| D5-UL-01 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[1405,578,1405,736]` | vertical axis joins structural junctions through a circular node | D5 contact sheet; D7 context record | unavailable |
| D5-UL-02 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[1475,649,1475,737]` | vertical rule lies between explicit structural nodes | D5 contact sheet; D7 context record | unavailable |
| D5-UR-01 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[2217,1152,2329,1152]` | horizontal structural axis between explicit circular nodes | D5 contact sheet; D7 context record | unavailable |
| D5-UR-02 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[2282,1083,2392,1083]` | horizontal structural rule terminates at an outer-wall junction | D5 contact sheet; D7 context record | unavailable |
| D5-UR-03 | A2-SG-009 | STRUCTURAL_CONTINUATION | `[2814,693,2814,824]` | vertical building rule continues through a structural node | D5 contact sheet; D7 context record | unavailable |
| D2-006 | A2-SG-022 | STRUCTURAL_CONTINUATION | `[2860,1586,5500,1586]` | source-verified thick upper building boundary across multiple bays | D2 ROI `[2700,1450,3000,300]`; D7 context record | unavailable |
| D5-TEXT-UL-01 | A2-SG-009 | ANNOTATION_OR_GLYPH | `[807,1000,914,1000]` | source context identifies the apparent line with dimension/text structure | D5 contact sheet; D7 context record | unavailable |
| D5-TEXT-UL-02 | A2-SG-009 | ANNOTATION_OR_GLYPH | `[1108,1007,1242,1007]` | source context identifies the apparent line with dimension/text structure | D5 contact sheet; D7 context record | unavailable |
| D5-TEXT-UL-03 | A2-SG-009 | ANNOTATION_OR_GLYPH | `[872,887,976,887]` | source context identifies the apparent line with dimension/text structure | D5 contact sheet; D7 context record | unavailable |
| D5-TEXT-UR-01 | A2-SG-009 | ANNOTATION_OR_GLYPH | `[2601,1000,2732,1000]` | source context identifies the apparent line with dimension/text structure | D5 contact sheet; D7 context record | unavailable |
| D2-R02 | A2-SG-009 | AMBIGUOUS | `[270,1500,270,2300]` | scan/tape damage prevents reliable continuity and identity judgment | D2 ROI `[150,1400,430,980]`; no paired context crop | unavailable |

The following controls are `INVALID_FOR_TASK` and excluded from class counts:
`D2-005` (intact no-regression line, no natural detector gap), `D2-R01` (target
mismatch), `D2-R04` (intentional openings/symbol boundary), and the three
synthetic blank/double-rule controls. They remain useful future gates.

## Counts and diversity gate

| SOURCE_GROUP | Structural | Hard annotation/glyph | Ambiguous | Invalid controls | Pool share (qualified 3-class) |
|---|---:|---:|---:|---:|---:|
| A2-SG-009 | 6 | 4 | 1 | 1 | 11/12 (91.7%) |
| A2-SG-022 | 1 | 0 | 0 | 1 | 1/12 (8.3%) |
| G0R2-3560D9BEBEAA3543 | 0 | 0 | 0 | 1 | 0/12 |
| Other 12 allocated DEV groups | unassessed | unassessed | unassessed | unassessed | not counted |

- Independent source groups containing positives: **2**.
- Independent source groups containing hard negatives: **1**.
- Independent source groups containing both: **1**.
- Qualified label distribution: **7 structural / 4 hard negative / 1 ambiguous**.
- Hard-negative distribution: all four are dimension/text-like cases from the
  same degraded archival drawing; there is no independent drafting-style,
  language, scan-quality, or document-origin coverage.
- Drawing/scanning diversity in the qualified pool: one degraded historical
  raster electrical drawing plus one cleaner thick/thin as-built PDF drawing.
  No qualified modern vector, historical HABS, East-Asian annotation-style, or
  clean dimension-chain hard-negative source exists.
- Dominance: `A2-SG-009` supplies 91.7% of the three-class pool and 100% of hard
  negatives and ambiguous examples.

## Prototype sufficiency

Raw crop count cannot repair this source imbalance. There is no legal complete
SOURCE_GROUP split that leaves hard negatives on both sides. The current pool is
also missing independent hard-negative styles, degradation diversity within each
class, and ready paired local/context crops. Therefore:

- cross-source train/test split possible: **NO**;
- current source-visible DEV labels sufficient for prototype: **NO**;
- ready to build prototype: **NO**.

The seven unavailable-but-previously-materialized DEV groups could change this
answer. Because they were not source-visible here, D9 must not call them positive,
negative, ambiguous, or invalid. Feasibility for the *full existing allocated DEV
corpus* is therefore blocked pending restoration and human qualification.

## Missing evidence families and conditional acquisition requirement

No new-document acquisition is authorized or proven necessary yet. The immediate
requirement is to restore and mine the seven already allocated, previously
materialized DEV sources. If that pass remains insufficient, acquire independent
DEV origins targeted at these gaps rather than generic "more PDFs":

| Conditional source family | Why needed |
|---|---|
| clean electrical plans with dense dimension/extension chains and arrow/tick markers | hard-negative diversity and same-page positive/negative coverage |
| degraded scanned architectural/electrical plans with still-legible structural identity | positive and hard-negative degradation diversity |
| historical blueprints from independent origins/drafting standards | degradation and style diversity beyond A2-SG-009 |
| modern vector plans with mixed text/line annotation layouts | clean hard-negative and renderer/style control |
| plans containing both thin structural rules and thick wall/boundary strokes | positive width/style diversity without class/source confounding |
| independent English and East-Asian drafting conventions | annotation/glyph and language/layout diversity |

Every future acquisition record must separately retain: canonical URL/origin;
license/usage terms; research-use and commercial-use status; redistribution
status; and whether local-only use is required. These rights fields must not be
used as source-evidence labels. Most current public-document DEV records have
unclear reuse terms and restricted redistribution, so a data-rights review is
required before any future training or redistribution.

## Governance and evidence trail

Inputs used were the DEV-only portions of the authoritative split and acquisition
manifest, plus checked-in D1/D2/D5/D6/D7/D8 DEV diagnostic reports. The existing
D5 contact sheet was reused; no new crop set was generated. No source was fetched,
no PDF was rendered, no OCR was run, and no candidate was auto-labeled.

---

STRUCTURAL_STROKE_DATASET_D9:
BLOCKED

DIAGNOSTIC CHECKPOINT:
a589c6bb5491e7c070aeb848df84a829a0003a61

PRODUCTION_SEMANTIC_DELTA:
NONE

DEV SOURCE_GROUPS INSPECTED:
3

SOURCE_GROUPS WITH STRUCTURAL POSITIVES:
2

SOURCE_GROUPS WITH HARD ANNOTATION/GLYPH NEGATIVES:
1

SOURCE_GROUPS WITH BOTH:
1

QUALIFIED STRUCTURAL POSITIVES:
7

QUALIFIED HARD NEGATIVES:
4

AMBIGUOUS:
1

CROSS-SOURCE TRAIN/TEST SPLIT POSSIBLE:
NO

CURRENT DEV SUFFICIENT FOR PROTOTYPE:
NO

NEW PDF ACQUISITION REQUIRED:
NO

IF YES, REQUIRED SOURCE FAMILIES:
N/A; first restore and mine seven already allocated DEV sources, then use the conditional families above only if still insufficient

DATA-RIGHTS REVIEW REQUIRED:
YES

READY TO BUILD PROTOTYPE:
NO

NEXT PRODUCTION CHANGE CANDIDATE:
NONE

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

GIT STATUS:
diagnostic changes
