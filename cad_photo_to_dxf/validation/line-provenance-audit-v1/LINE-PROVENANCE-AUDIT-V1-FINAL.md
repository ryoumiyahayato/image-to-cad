# LINE PROVENANCE AUDIT V1 — FINAL

## Scope and evidence boundary

This bounded audit traces the exact frozen Local-D 24 in fixed human-review order. Local-D used a standalone HoughLinesP detector followed by axis canonicalization, duplicate suppression, a per-orientation cap, geometric pair formation, and candidate deduplication. It did not run LSD, production line consolidation, ownership, fallback, artifact suppression, FinalStructure, or CAD export. Those stages are therefore recorded as `NOT_AVAILABLE`, not inferred.

The prior flat-four export is retained only as `LEGACY_PROVISIONAL_REVIEW`. The checked two-stage runtime package contains no persisted review-result export, so no two-stage answers were invented. Root-cause conclusions come from the reproduced detector lineage, ordered span-support diagnostics, and bounded manual inspection of the generated panels.

PRODUCTION_SEMANTIC_DELTA: NONE

## Evidence availability

- Source evidence traced: 24 / 24
- Raw Hough provenance available: 24 / 24
- Raw LSD provenance available: 0 / 24
- Consolidation provenance available: 0 / 24 (stage not present in Local-D)
- Pairing provenance available: 24 / 24
- Span-support profiles: 24 / 24

## 24-case diagnostic table

| Review # | Candidate ID | Human review observation | Fragment A integrity | Fragment B integrity | Earliest proven/supported failure stage | Primary root cause | Secondary failure | Confidence | Direct continuation still plausible? | Needs production fix? | Notes |
|---:|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `LOCALD-F05-DENNKISE-LOCALC-F05-PDF-DENNKISETSUBI-P1-E803B4F95BE7` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK; note: 原图为疑似表格中的虚折线，并非一条完整的实线 | OBSERVED_INTERRUPTED | OBSERVED_INTERRUPTED | RAW_HOUGH_OUTPUT | RAW_HOUGH_OVERSPAN | PATTERNED_OR_DASHED_STROKE | PROVEN | NO | YES | Raw Hough A/B cross repeated blank intervals; ordered raw support is 0.792/0.772 with a six-sample interruption in B. |
| 2 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ELEC06-P1-567F6C8B5736` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_INTERRUPTED | OBSERVED_CONTINUOUS | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | STRONGLY_SUPPORTED | YES | NO | Both fragments lie on the same note/table rule; the provisional INVALID label is not evidence of a pairing defect. |
| 3 | `LOCALD-F03-AS-BUILT-LOCALC-F03-DWG-HVAC4-MODEL-OVERVIEW-7CC3C6CC3A31` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | STRONGLY_SUPPORTED | YES | NO | Both spans have complete sampled support and form one layout boundary rather than an object-continuation training positive. |
| 4 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P6-E77468440094` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | PROVEN | NO | YES | A/B are source-supported but the gap contains explicit node geometry; a direct bridge would collapse topology. |
| 5 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ELEC06-P1-2ED2C41C18FD` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_INTERRUPTED | OBSERVED_INTERRUPTED | CANDIDATE_PAIR_FORMATION | CANDIDATE_PAIRING_ERROR | NONE | STRONGLY_SUPPORTED | NO | YES | The fragments are individually plausible, but context does not show one underlying stroke through the intervening plan structure. |
| 6 | `LOCALD-F10-ENVIRONM-LOCALC-F10-PDF-ENV-BUREAU-P1-9BC941C1ED6B` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | PROVEN | YES | NO | A/B lie on one dimension/grid rule; this is useful negative evidence, not unsupported geometry. |
| 7 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P12-3C8A7D8EDECB` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | PROVEN | YES | NO | Both fully supported fragments belong to a single schedule row rule. |
| 8 | `LOCALD-F02-HUIHONG-LOCALC-F02-DWG-HVAC10-MODEL-OVERVIEW-296C1A7AD5FD` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | CANDIDATE_PAIRING_ERROR | NONE | PROVEN | NO | YES | A is a boundary of the upper view and B a boundary of the lower view; both primitives are intact but unrelated. |
| 9 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P1-A2F0CA58FE95` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_INTERRUPTED | OBSERVED_INTERRUPTED | RAW_HOUGH_OUTPUT | RAW_HOUGH_OVERSPAN | GLYPH_TEXT_CONTAMINATION | PROVEN | NO | YES | Raw Hough segments traverse text glyphs; raw support is 0.653/0.782 with seven- and four-sample interruptions. |
| 10 | `LOCALD-F02-HUIHONG-LOCALC-F02-DWG-HVAC10-MODEL-OVERVIEW-D3230C9EC8C7` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | STRONGLY_SUPPORTED | NO | YES | The vertical fragments are intact, but an explicit terminal/node occupies the proposed connection. |
| 11 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P8-9570FA0098BC` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | PROVEN | NO | YES | The source-supported horizontal pieces terminate around a filled node; direct straight bridging is not source-faithful. |
| 12 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P8-D2E64AFA0093` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | INTENTIONAL_OPENING_OR_INTERRUPTION | NONE | PLAUSIBLE | NO | YES | Both fragments are fully supported, while the 54 px internal interval is visibly blank; the exact semantic role is not recorded. |
| 13 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-20210416ZUMEN-P4-F1D7431BE281` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | PROVEN | NO | YES | A/B participate in one vertical topology, but the source explicitly records an intermediate connector. |
| 14 | `LOCALD-F05-DENNKISE-LOCALC-F05-PDF-DENNKISETSUBI-P1-3C6994CE79D1` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | RAW_HOUGH_OUTPUT | RAW_HOUGH_OVERSPAN | PATTERNED_OR_DASHED_STROKE | PROVEN | NO | YES | Raw fragment B spans a patterned blank interval; its ordered raw profile has an eight-sample interruption. |
| 15 | `LOCALD-F10-ENVIRONM-LOCALC-F10-PDF-ENV-BUREAU-P8-9EC79D5FF0DF` | LEGACY_PROVISIONAL_REVIEW: AMBIGUOUS | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | NOT_AVAILABLE | INSUFFICIENT_PROVENANCE | NONE | UNRESOLVED | YES | UNRESOLVED | The raster permits both a skewed same-boundary reading and a parallel-boundary pairing error; no vector identity survives. |
| 16 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ARCH10B-P1-E23A10324891` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | PROVEN | YES | NO | Both fully supported fragments lie on one annotation/layout rule. |
| 17 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-20210416ZUMEN-P4-EB69E4B57683` | LEGACY_PROVISIONAL_REVIEW: STRUCTURAL_CONTINUATION | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | PROVEN | NO | YES | The vertical pieces are related but the source requires the recorded connector between them. |
| 18 | `LOCALD-F01-HAIYANG-LOCALC-F01-DWG-HVAC20220110-MODEL-OVERVI-72EBF8E49D52` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | CANDIDATE_PAIRING_ERROR | NONE | PROVEN | NO | YES | A and B are fully supported boundaries from adjacent view frames, separated by the frame/header region. |
| 19 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P1-FA2913866300` | LEGACY_PROVISIONAL_REVIEW: INVALID_FOR_TASK | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_ANNOTATION_HARD_NEGATIVE | NONE | PROVEN | YES | NO | A/B are intact portions of one title-block table rule. |
| 20 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P11-2FDE7E3C99FB` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | STRONGLY_SUPPORTED | NO | YES | The wall/boundary fragments are individually intact, but the gap coincides with explicit intermediate geometry. |
| 21 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P11-730E087EA3B5` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_CONTINUOUS | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | STRONGLY_SUPPORTED | NO | YES | The two source-supported wall-line pieces are separated by a recorded component/opening module. |
| 22 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P12-45D73C6A827D` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | CANDIDATE_PAIR_FORMATION | COMPONENT_OR_NODE_MEDIATED | NONE | STRONGLY_SUPPORTED | NO | YES | A/B remain plausible topology participants, but the source does not support replacing the intermediate structure with a straight bridge. |
| 23 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P6-F64B1FAF8535` | LEGACY_PROVISIONAL_REVIEW: ANNOTATION_OR_GLYPH | OBSERVED_CONTINUOUS | OBSERVED_INTERRUPTED | CANDIDATE_PAIR_FORMATION | MIXED_ROLE_COLLINEAR_PAIRING | NONE | STRONGLY_SUPPORTED | NO | YES | The fragments are near-collinear but transition from object boundary to layout/grid extension at the corner node. |
| 24 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-2026DENNKISETSUBI-P1-FD1646128CF2` | LEGACY_PROVISIONAL_REVIEW: AMBIGUOUS | OBSERVED_INTERRUPTED | OBSERVED_INTERRUPTED | NO_UNSUPPORTED_GEOMETRIC_CLAIM | VALID_DIRECT_OBJECT_CONTINUATION | NONE | PLAUSIBLE | YES | NO | Both long boundary fragments have 0.98 sampled support and a six-pixel gap; dense context prevents PROVEN confidence. |

## Aggregate counts

- RAW_HOUGH_OVERSPAN: 3
- RAW_LSD_OVERSPAN: 0
- RAW_DETECTOR_OVERSPAN_BOTH: 0
- CONSOLIDATION_OVERMERGE: 0
- POST_DETECTION_GEOMETRY_EXTENSION: 0
- CANDIDATE_PAIRING_ERROR: 3
- MIXED_ROLE_COLLINEAR_PAIRING: 1
- INTENTIONAL_OPENING_OR_INTERRUPTION: 1
- COMPONENT_OR_NODE_MEDIATED: 8
- PATTERNED_OR_DASHED_STROKE: 0
- VALID_ANNOTATION_HARD_NEGATIVE: 6
- VALID_DIRECT_OBJECT_CONTINUATION: 1
- GLYPH_TEXT_CONTAMINATION: 0
- REVIEW_ASSET_OR_RENDER_FAILURE: 0
- INSUFFICIENT_PROVENANCE: 1

CASES WITH PRIMITIVE INTEGRITY FAILURE: 3

CASES WITH PURE PAIRING FAILURE: 13

CASES WITH BOTH UPSTREAM + PAIRING FAILURE: 3

VALID HARD NEGATIVES: 6

VALID DIRECT OBJECT CONTINUATIONS: 1

UNRESOLVED: 1

## Engineering decision

NEXT PRODUCTION TARGET: MULTI-STAGE FIX REQUIRED

MODEL BAKE-OFF SHOULD RESUME: NO

The audit does not implement that target. No detector threshold, merge rule, ownership rule, fallback rule, artifact rule, OCR behavior, model inference, or CAD export behavior changed.

## Governance

- MODEL RUN: NO
- MODEL-ASSISTED LABELING: NO
- NEW CANDIDATE MINING: NO
- VALIDATION: NO
- LOCKED_BLIND: 0 / 8
- H1/H2 OPENED: NO
- PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
- Runtime source-derived evidence remains Git-ignored.

## Verification

Focused audit tests: 8 passed. They cover frozen identity/order, detector-family separation, explicit missing provenance, deterministic ordered sampling, production no-op defaults, governance, vocabulary validation, and count closure.

Runtime evidence: `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03\local-artifacts\draftsman\line-provenance-audit-v1`

LINE_PROVENANCE_AUDIT_V1: COMPLETE
