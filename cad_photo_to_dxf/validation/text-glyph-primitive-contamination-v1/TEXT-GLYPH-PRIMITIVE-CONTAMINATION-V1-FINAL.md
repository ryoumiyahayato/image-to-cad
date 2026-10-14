# TEXT / GLYPH PRIMITIVE CONTAMINATION V1 — FINAL

Status: `SOURCE_GAP_REVIEW_V1_STATUS: PAUSED_UPSTREAM_CONTAMINATION`.

## Root cause

The frozen DEV miner replayed raw Hough primitives and applied span, axis, and direct-continuation guards, but bypassed the existing text-protection/ownership path. The earliest actionable omission was immediately after axis support and before pair formation. Production text filtering exists, while OCR ownership is later and unavailable to the standalone DEV miner. The failure is therefore mixed ownership timing plus a DEV fallback/bypass and weak admission composition; it is not a Hough-only defect.

The implemented DEV guard reuses the existing deterministic text-region evidence, intersects its coarse rectangles with component ink, and asks whether credible axial support survives text-owned-pixel subtraction. A single masked component is uncertain, not rejected. Multi-component glyph chains with no independent support are rejected. No source pixels are erased.

## Bounded 20-case audit

| Case | Candidate ID | Source family | Human observation | Primitive geometry | Text-mask overlap | Non-text support | Text components | Post-text-removal support | Text-support status | Current eligibility | Eligibility after guard | Failure family | Confidence |
|---|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---|
| SOURCE_GAP_01 | `FRESH1-AB2943863A535D1044B9` | F09-JIULONG-FIRE-ELECTRICAL | NOT_AVAILABLE | A [615, 524]->[615, 580]; B [615, 620]->[615, 715] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | NONE | STRONGLY_SUPPORTED |
| SOURCE_GAP_02 | `FRESH1-9BB32E8680E08F3ED86C` | F05-DENNKISETSUBI-STANDALONE-PDF | NOT_AVAILABLE | A [336, 738]->[336, 788]; B [336, 793]->[336, 837] | 1.000 | 0.000 | 2 | 0.000 | TEXT_UNCERTAIN | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | TEXT_MASK_AMBIGUITY | CONSERVATIVE |
| SOURCE_GAP_03 | `FRESH1-2BF547C27C8497056BA6` | F06-ONTAKE-VISITOR-CENTER-ELECTRICAL | NOT_DIRECT_STRAIGHT_CONTINUATION / None | A [2212, 814]->[2212, 916]; B [2212, 921]->[2212, 952] | 0.000 | 0.961 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | NONE | STRONGLY_SUPPORTED |
| SOURCE_GAP_04 | `FRESH1-51DF39D706DE8C684F10` | F04-XDF-RENOVATION-REVIEW-PDF | NOT_AVAILABLE | A [1282, 1198]->[1330, 1198]; B [1360, 1198]->[1419, 1198] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_05 | `FRESH1-847714DB8B47800A7342` | F01-HAIYANG-2022-ROOT-DWG | NOT_AVAILABLE | A [2106, 136]->[2166, 136]; B [2172, 136]->[2202, 136] | 1.000 | 0.000 | 2 | 0.000 | TEXT_UNCERTAIN | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | TEXT_MASK_AMBIGUITY | CONSERVATIVE |
| SOURCE_GAP_06 | `FRESH1-6E1D7A515EF8BC7293A3` | F07-SEYA-CULTURAL-CENTER-ELECTRICAL | NOT_AVAILABLE | A [2313, 658]->[2359, 658]; B [2390, 658]->[2445, 658] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | NONE | STRONGLY_SUPPORTED |
| SOURCE_GAP_07 | `FRESH1-B7300C5B8E706C736EB1` | F08-YANGZIJIANG-WAREHOUSE-ELECTRICAL | NOT_AVAILABLE | A [501, 430]->[545, 430]; B [589, 430]->[634, 430] | 1.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_08 | `FRESH1-FF28E80F90C3CFA05A78` | F02-HUIHONG-2019-HASHED-DWG | NOT_AVAILABLE | A [2285, 992]->[2285, 1020]; B [2285, 1053]->[2285, 1109] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | NONE | STRONGLY_SUPPORTED |
| SOURCE_GAP_09 | `FRESH1-BD17A756658C48E6DE5F` | F10-ENVIRONMENTAL-BUREAU-MAIN-BUILDING | NOT_AVAILABLE | A [616, 462]->[616, 518]; B [616, 552]->[616, 590] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | NONE | STRONGLY_SUPPORTED |
| SOURCE_GAP_10 | `FRESH1-FC529FBBABD1C203BAD8` | F05-DENNKISETSUBI-STANDALONE-PDF | NOT_AVAILABLE | A [1851, 1346]->[1851, 1377]; B [1851, 1384]->[1851, 1445] | 0.000 | 0.875 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_11 | `FRESH1-98D0BD1ED4DBB02B9A3A` | F09-JIULONG-FIRE-ELECTRICAL | NOT_AVAILABLE | A [614, 1544]->[679, 1544]; B [684, 1544]->[754, 1544] | 1.000 | 0.818 | 2 | 0.871 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_12 | `FRESH1-82EE2790BE71525F9762` | F07-SEYA-CULTURAL-CENTER-ELECTRICAL | NOT_AVAILABLE | A [1324, 1348]->[1324, 1391]; B [1324, 1422]->[1324, 1479] | 0.114 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_13 | `FRESH1-DAF59F989A2B0C8E453B` | F07-SEYA-CULTURAL-CENTER-ELECTRICAL | NOT_AVAILABLE | A [1324, 1348]->[1324, 1391]; B [1324, 1422]->[1324, 1456] | 0.114 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_14 | `FRESH1-4F58534C04C2C40E9E25` | F07-SEYA-CULTURAL-CENTER-ELECTRICAL | NOT_AVAILABLE | A [2075, 128]->[2075, 159]; B [2076, 174]->[2076, 325] | 0.000 | 1.000 | 0 | 1.000 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_15 | `FRESH1-4966D4412392002C19C2` | F09-JIULONG-FIRE-ELECTRICAL | NOT_AVAILABLE | A [1120, 451]->[1120, 528]; B [1122, 535]->[1122, 600] | 0.359 | 0.439 | 1 | 0.980 | TEXT_INDEPENDENT | ELIGIBLE_IN_FROZEN_147 | ELIGIBLE_UNCHANGED | INDEPENDENT_LINE_SUPPORT_THROUGH_TEXT | STRONGLY_SUPPORTED |
| SOURCE_GAP_16 | `FRESH1-EDC71A4759AD64EDCE78` | F09-JIULONG-FIRE-ELECTRICAL | NOT_AVAILABLE | A [1457, 1068]->[1488, 1068]; B [1493, 1068]->[1548, 1068] | 1.000 | 0.000 | 8 | 0.000 | TEXT_REJECTED | ELIGIBLE_IN_FROZEN_147 | INELIGIBLE_TEXT_REJECTED | GLYPH_ONLY_SUPPORT | PROVEN |
| FROZEN147_TEXT_CONTROL_01 | `FRESH1-3896FDF95885929AF0BE` | F04-XDF-RENOVATION-REVIEW-PDF | NOT_DIRECT_STRAIGHT_CONTINUATION / None | A [2010, 1724]->[2081, 1724]; B [2086, 1724]->[2132, 1724] | 1.000 | 0.000 | 5 | 0.000 | TEXT_REJECTED | ELIGIBLE_IN_FROZEN_147 | INELIGIBLE_TEXT_REJECTED | GLYPH_ONLY_SUPPORT | PROVEN |
| FROZEN147_TEXT_CONTROL_02 | `FRESH1-43C5461340B4AE31E3E7` | F04-XDF-RENOVATION-REVIEW-PDF | NOT_DIRECT_STRAIGHT_CONTINUATION / None | A [2035, 1738]->[2082, 1738]; B [2087, 1738]->[2133, 1738] | 1.000 | 0.000 | 5 | 0.000 | TEXT_REJECTED | ELIGIBLE_IN_FROZEN_147 | INELIGIBLE_TEXT_REJECTED | GLYPH_ONLY_SUPPORT | PROVEN |
| FROZEN147_TEXT_CONTROL_03 | `FRESH1-F958CAC7F42997D179E6` | F05-DENNKISETSUBI-STANDALONE-PDF | NOT_AVAILABLE | A [1002, 910]->[1052, 910]; B [1057, 910]->[1138, 910] | 1.000 | 0.000 | 15 | 0.000 | TEXT_REJECTED | ELIGIBLE_IN_FROZEN_147 | INELIGIBLE_TEXT_REJECTED | GLYPH_ONLY_SUPPORT | PROVEN |
| FROZEN147_TEXT_CONTROL_04 | `FRESH1-46A7C918A98FDBD54AA7` | F06-ONTAKE-VISITOR-CENTER-ELECTRICAL | NOT_AVAILABLE | A [1925, 626]->[1976, 626]; B [1982, 626]->[2019, 626] | 1.000 | 0.000 | 8 | 0.000 | TEXT_REJECTED | ELIGIBLE_IN_FROZEN_147 | INELIGIBLE_TEXT_REJECTED | GLYPH_ONLY_SUPPORT | PROVEN |

## Existing mechanism audit

- `text_protection.py`: deterministic component/group mask consumed by production line filtering; bypassed by the DEV frozen-pool miner before this fix.
- `content_ownership.py`: OCR/text ownership is authoritative but late; it is not present in standalone Local-D mining.
- `source_support_lifecycle.py`: records production provenance and fallback, but the standalone miner never instantiated it.
- `fresh_dev_candidate_remining_v1.py`: now composes span -> axis -> text/glyph integrity -> pair/admissibility. Prior rejections cannot be upgraded and `TEXT_REJECTED` primitives cannot be paired.

## Frozen-pool re-evaluation

- Frozen 147: independent 125, uncertain 13, rejected 9.
- Newly ineligible: 9; source families: `{"F04-XDF-RENOVATION-REVIEW-PDF": 2, "F05-DENNKISETSUBI-STANDALONE-PDF": 1, "F06-ONTAKE-VISITOR-CENTER-ELECTRICAL": 2, "F09-JIULONG-FIRE-ELECTRICAL": 4}`.
- Previously human-reviewed among newly ineligible: 4.
- Bounded audit: 5 confirmed text-derived, 2 uncertain/contaminated, and 13 legitimate independent controls.
- Source-gap 16 audited: 16 / 16; invalid primitives: 1.
- The six-way source-gap taxonomy assumes a valid primitive. That assumption is unsafe. Upstream filtering is the primary defense; any later UI should fail closed with `INVALID_PRIMITIVE_FOR_GAP_REVIEW`.

## Safety controls

- Old valid direct object: 1 / 1.
- Old valid annotation controls: 6 / 6.
- Fresh human-direct controls: 9 / 9.
- Fresh human-direct annotation controls: 6 / 6.
- Real line through text, table border, title-block border, dimension line, and grid line synthetic safety: PASS.
- Existing span, axis, and admissibility rejection semantics remain monotonic. Production semantic delta: NONE.

## Engineering decision

A. Earliest stage: DEV raw primitive admission after axis integrity and before pair formation.

B. Existing text/ownership evidence available early enough: `PARTIAL` (deterministic text mask yes; final OCR ownership no).

C. Primary failure: mixed causes — ownership timing, DEV fallback bypass, and weak admission composition.

D. Generic text/glyph primitive-integrity guard justified: `YES`.

E. Current SOURCE_GAP_REVIEW_V1 contains invalid primitives: `YES`.

F. Freeze current SOURCE_GAP_REVIEW_V1 results: `NO`.

G. Resume Batch-03: `NO`.

H. Resume model bake-off: `NO`.

## Governance

No remine, replacement package, model run, model-assisted labeling, validation, locked-blind inspection, H1/H2 access, source-continuity guard, or endpoint guard occurred. Source-derived imagery remains below Git-ignored `local-artifacts`.

Next target: deterministically remove the rejected primitive candidates from SOURCE_GAP_REVIEW_V1 and, in a later authorized task, replace them from the unchanged frozen 147 pool before restarting human review.
