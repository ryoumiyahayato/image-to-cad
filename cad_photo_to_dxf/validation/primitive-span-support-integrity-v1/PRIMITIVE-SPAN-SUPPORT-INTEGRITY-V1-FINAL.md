# PRIMITIVE SPAN SUPPORT INTEGRITY V1 — FINAL

## Code-path scope

The audited Local-D raw primitives were produced by the standalone DEV mining routine whose exact tracked reproducer is `app.line_provenance_audit_v1._raw_hough`: Otsu foreground followed by `cv2.HoughLinesP(threshold=45, minLineLength=28, maxLineGap=3)`. Its output is axis-canonicalized, deduplicated, capped per orientation, and paired. It is not imported by production.

AUDITED_HOUGH_PATH_SCOPE: DEV_ONLY

Production follows `main.py` -> `app.gui_public_release.MainWindow` -> `ProductionProcessingService.process_page` -> `trace_image_optimized` -> `reconstruct_straight_lines` -> `app.line_detect.detect_lines` -> immutable `FinalStructure`. Production uses a separate resolution-scaled Hough detector plus LSD. `_line_support_quality` and `_filter_source_supported_lines` already inspect total centerline support and longest unsupported fraction on a dilated source mask, so production span integrity is PARTIAL, not absent. It does not use this DEV classifier's patterned-stroke and competing-structure states.

PRODUCTION_SPAN_INTEGRITY_ALREADY_PRESENT: PARTIAL

PRODUCTION_OVERSPAN_EQUIVALENCE: UNPROVEN

No existing DEV production fixture directly reproduces the three frozen Local-D raw ancestors through the separate production Hough/LSD path. Production code and semantics are unchanged.

## Remediation

`primitive_span_integrity.py` samples the complete primitive in order, using a perpendicular corridor scaled from locally estimated stroke width. It records centerline/nearby support, nearest-ink distance, contiguous runs, internal collapse extent, repeated gaps, and competing off-axis structure. Only `SPAN_INTEGRITY_SUPPORTED` records may enter ordinary future DEV continuation mining; uncertain and rejected records remain diagnostic evidence. Endpoints are not moved, split points are not invented, and no geometry is manufactured.

The frozen 24 were not remined. Their persisted raw Hough ancestors were evaluated, then the existing direct-continuation result was preserved unless primitive qualification made an otherwise-admissible candidate uncertain or rejected.

## Frozen-24 results

| Review | Candidate | Audit root cause | Raw Hough ancestors | Before span | After span | Span reason | Downstream before | Downstream after | Outcome |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `LOCALD-F05-DENNKISE-LOCALC-F05-PDF-DENNKISETSUBI-P1-E803B4F95BE7` | RAW_HOUGH_OVERSPAN | raw-hough-000092, raw-hough-001179 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_UNCERTAIN | POSSIBLE_PATTERNED_STROKE | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | ROOT_CAUSE_REMEDIATED |
| 2 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ELEC06-P1-567F6C8B5736` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-000820, raw-hough-000328 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 3 | `LOCALD-F03-AS-BUILT-LOCALC-F03-DWG-HVAC4-MODEL-OVERVIEW-7CC3C6CC3A31` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-000028, raw-hough-000043 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 4 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P6-E77468440094` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000081, raw-hough-000331 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 5 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ELEC06-P1-2ED2C41C18FD` | CANDIDATE_PAIRING_ERROR | raw-hough-000425, raw-hough-000100 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 6 | `LOCALD-F10-ENVIRONM-LOCALC-F10-PDF-ENV-BUREAU-P1-9BC941C1ED6B` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-000029, raw-hough-000004 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 7 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P12-3C8A7D8EDECB` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-002068, raw-hough-000131 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 8 | `LOCALD-F02-HUIHONG-LOCALC-F02-DWG-HVAC10-MODEL-OVERVIEW-296C1A7AD5FD` | CANDIDATE_PAIRING_ERROR | raw-hough-000656, raw-hough-000003 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 9 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P1-A2F0CA58FE95` | RAW_HOUGH_OVERSPAN | raw-hough-000204, raw-hough-000079 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_REJECTED | COMPETING_STRUCTURE_IN_SPAN | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | ROOT_CAUSE_REMEDIATED |
| 10 | `LOCALD-F02-HUIHONG-LOCALC-F02-DWG-HVAC10-MODEL-OVERVIEW-D3230C9EC8C7` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000139, raw-hough-000881 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 11 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P8-9570FA0098BC` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000160, raw-hough-000871 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 12 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P8-D2E64AFA0093` | INTENTIONAL_OPENING_OR_INTERRUPTION | raw-hough-000237, raw-hough-000046 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 13 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-20210416ZUMEN-P4-F1D7431BE281` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000050, raw-hough-000558, raw-hough-000039 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 14 | `LOCALD-F05-DENNKISE-LOCALC-F05-PDF-DENNKISETSUBI-P1-3C6994CE79D1` | RAW_HOUGH_OVERSPAN | raw-hough-000085, raw-hough-001230 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_UNCERTAIN | POSSIBLE_PATTERNED_STROKE | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_UNCERTAIN | ROOT_CAUSE_REMEDIATED |
| 15 | `LOCALD-F10-ENVIRONM-LOCALC-F10-PDF-ENV-BUREAU-P8-9EC79D5FF0DF` | INSUFFICIENT_PROVENANCE | raw-hough-000835, raw-hough-000013 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_UNCERTAIN | DIRECT_CONTINUATION_UNCERTAIN | PRESERVED_UNCERTAIN |
| 16 | `LOCALD-F04-XDF-RENO-LOCALC-F04-PDF-ARCH10B-P1-E23A10324891` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-000016, raw-hough-000253 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 17 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-20210416ZUMEN-P4-EB69E4B57683` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000731, raw-hough-000017 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 18 | `LOCALD-F01-HAIYANG-LOCALC-F01-DWG-HVAC20220110-MODEL-OVERVI-72EBF8E49D52` | CANDIDATE_PAIRING_ERROR | raw-hough-000004, raw-hough-000011, raw-hough-000384 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 19 | `LOCALD-F09-JIULONG-LOCALC-F09-PDF-JIULONG-P1-FA2913866300` | VALID_ANNOTATION_HARD_NEGATIVE | raw-hough-000821, raw-hough-000582 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |
| 20 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P11-2FDE7E3C99FB` | COMPONENT_OR_NODE_MEDIATED | raw-hough-001247, raw-hough-000085 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 21 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P11-730E087EA3B5` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000085, raw-hough-001713 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 22 | `LOCALD-F07-SEYA-CUL-LOCALC-F07-PDF-0026-P12-45D73C6A827D` | COMPONENT_OR_NODE_MEDIATED | raw-hough-000126, raw-hough-000054 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 23 | `LOCALD-F08-YANGZIJI-LOCALC-F08-PDF-WAREHOUSE815-P6-F64B1FAF8535` | MIXED_ROLE_COLLINEAR_PAIRING | raw-hough-000090, raw-hough-000513 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_REJECTED | DIRECT_CONTINUATION_REJECTED | PAIRING_REJECTION_PRESERVED |
| 24 | `LOCALD-F06-ONTAKE-V-LOCALC-F06-PDF-2026DENNKISETSUBI-P1-FD1646128CF2` | VALID_DIRECT_OBJECT_CONTINUATION | raw-hough-000191, raw-hough-000823 | SPAN_INTEGRITY_NOT_EVALUATED | SPAN_INTEGRITY_SUPPORTED | CONTINUOUS_SOURCE_SUPPORT | DIRECT_CONTINUATION_ADMISSIBLE | DIRECT_CONTINUATION_ADMISSIBLE | PRESERVED |

## RAW_HOUGH_OVERSPAN evidence

### Case 01

- SOURCE FACT: Raw Hough A/B cross repeated blank intervals; ordered raw support is 0.792/0.772 with a six-sample interruption in B.
- RAW HOUGH BEFORE: raw-hough-000092, raw-hough-001179 entered as ordinary primitives.
- SPAN PROFILE: full ordered profiles and contiguous runs are recorded in the runtime case directory.
- SPAN-INTEGRITY DECISION: SPAN_INTEGRITY_UNCERTAIN / POSSIBLE_PATTERNED_STROKE.
- RAW PRIMITIVE AFTER: no endpoint or geometry rewrite; rejected/uncertain qualification prevents ordinary promotion.
- DOWNSTREAM CANDIDATE EFFECT: DIRECT_CONTINUATION_REJECTED -> DIRECT_CONTINUATION_REJECTED.
- ROOT CAUSE FIXED? YES

### Case 09

- SOURCE FACT: Raw Hough segments traverse text glyphs; raw support is 0.653/0.782 with seven- and four-sample interruptions.
- RAW HOUGH BEFORE: raw-hough-000204, raw-hough-000079 entered as ordinary primitives.
- SPAN PROFILE: full ordered profiles and contiguous runs are recorded in the runtime case directory.
- SPAN-INTEGRITY DECISION: SPAN_INTEGRITY_REJECTED / COMPETING_STRUCTURE_IN_SPAN.
- RAW PRIMITIVE AFTER: no endpoint or geometry rewrite; rejected/uncertain qualification prevents ordinary promotion.
- DOWNSTREAM CANDIDATE EFFECT: DIRECT_CONTINUATION_REJECTED -> DIRECT_CONTINUATION_REJECTED.
- ROOT CAUSE FIXED? YES

### Case 14

- SOURCE FACT: Raw fragment B spans a patterned blank interval; its ordered raw profile has an eight-sample interruption.
- RAW HOUGH BEFORE: raw-hough-000085, raw-hough-001230 entered as ordinary primitives.
- SPAN PROFILE: full ordered profiles and contiguous runs are recorded in the runtime case directory.
- SPAN-INTEGRITY DECISION: SPAN_INTEGRITY_UNCERTAIN / POSSIBLE_PATTERNED_STROKE.
- RAW PRIMITIVE AFTER: no endpoint or geometry rewrite; rejected/uncertain qualification prevents ordinary promotion.
- DOWNSTREAM CANDIDATE EFFECT: DIRECT_CONTINUATION_ADMISSIBLE -> DIRECT_CONTINUATION_UNCERTAIN.
- ROOT CAUSE FIXED? YES

## Controls and sensitivity

- Valid direct object continuation: 1 / 1 preserved.
- Valid annotation hard negatives: 6 / 6 preserved.
- Previous pairing-family rejections: 13 / 13 preserved.
- Insufficient-provenance case remains uncertain: YES.
- Reason counts: `{"COMPETING_STRUCTURE_IN_SPAN": 1, "CONTINUOUS_SOURCE_SUPPORT": 21, "POSSIBLE_PATTERNED_STROKE": 2}`.
- Representative preserved controls are cases 24 (valid object), 02 and 16 (valid annotations), and 15 (uncertain provenance).

Thresholds use span fraction and local stroke widths; the only absolute floor is 2.5 px to suppress sub-pixel/raster noise. Conservative and strict perturbations vary collapse fraction, patterned-support ceilings, and short-span stroke-width extent. All preserve the 3/3 detection, 1/1 positive, 6/6 annotations, and 13/13 pairing rejections.

THRESHOLD SENSITIVITY STABLE: YES

## Boundaries and decision

No LSD evidence was available for the frozen 24 and LSD behavior was not changed. Consolidation provenance was unavailable and consolidation semantics were not changed. No model, OCR classifier, new mining, candidate-specific logic, filename logic, source-family logic, LOCKED_BLIND, or H1/H2 access occurred.

SPAN_INTEGRITY_FIX: SAFE

NEXT TARGET: FRESH_DEV_CANDIDATE_REMINING

MODEL_BAKE_OFF_SHOULD_RESUME: NO

Fresh DEV remining is next because the gate must demonstrate a materially cleaner new candidate pool before any model bake-off. Production span integrity remains a separate audit target if direct evidence is later established.

## Verification

Focused span-integrity, previous admissibility/provenance, source-support lifecycle/preservation, line-integrity, straight-line reconstruction, and geometry-reconstruction tests: 79 passed.

Ruff checks passed for the implementation, evaluator, and focused tests. The evaluator also passed Python bytecode compilation.

## Governance

- USER-SUPPLIED SOURCES: internal development authorized
- PUBLIC REDISTRIBUTION: NOT_AUTHORIZED
- VALIDATION: NO
- LOCKED_BLIND: 0 / 8
- LOCKED_BLIND MANUAL INSPECTION: NO
- H1/H2 OPENED: NO
- MODEL RUN: NO
- NEW CANDIDATE MINING: NO
- Runtime source-derived evidence is Git-ignored.
