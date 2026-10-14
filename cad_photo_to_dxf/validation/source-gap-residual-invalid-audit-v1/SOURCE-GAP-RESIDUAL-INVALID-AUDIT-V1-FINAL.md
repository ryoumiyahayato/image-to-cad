# Source Gap Residual Invalid Audit V1

Status: `DIAGNOSTIC_ONLY`

This audit covers exactly the two current human-confirmed invalid candidates, followed by six existing pair controls. It uses existing V1.2 selection, eligible-set, straight replay, direct-admissibility, and human-state artifacts only. No candidate was mined, reacquired, relabeled, replaced, or sent to a model.

## Residual cases

### Review index 15 — `FRESH1-6DA3382199DB993085B8`

- Source family/unit: `F01-HAIYANG-2022-ROOT-DWG` / `LOCALC-F01-DWG-HVAC20220110-MODEL-OVERVIEW`
- Geometry: `horizontal`, primitive length `88.0 px`, projected span `88.0 px`; claimed extent `[2121, 276]` → `[2209, 276]`; gap `7 px`; gap endpoints `[2157, 276]` → `[2164, 276]`; fragment A `{'end': [2157, 276], 'start': [2121, 276]}`; fragment B `{'end': [2209, 276], 'start': [2164, 276]}`.
- Upstream trace: span `SPAN_INTEGRITY_SUPPORTED`; axis `PRIMITIVE_AXIS_SUPPORTED`; text/glyph `TEXT_INDEPENDENT`; straight `STRAIGHT_UNCERTAIN`; admissibility `DIRECT_CONTINUATION_ADMISSIBLE`; current eligible `True`.
- Straight evidence: fragment statuses/reasons `[('fragment_a', 'STRAIGHT_UNCERTAIN', 'INSUFFICIENT_EVIDENCE'), ('fragment_b', 'STRAIGHT_UNCERTAIN', 'INSUFFICIENT_STRAIGHT_TRAJECTORY_SUPPORT')]`. Local tangent profile: `{'status': 'NOT_AVAILABLE_IN_EXISTING_ARTIFACTS', 'diagnostic_available': False}`. No tangent profile was synthesized where the existing diagnostic marked it unavailable.
- Lateral/support profile: axis support `0.921348`; centerline support `0.5`; off-axis ink `0.197802`; thickness ratio `1.333333`; local density `0.096984`.
- Trajectory profile: clean score `0.824642`; coherence score `0.095342`; supported runs `2`; unsupported intervals `1`. Direct pair evidence: `DIRECT_CONTINUATION_ADMISSIBLE / CLEAR_DIRECT_TRAJECTORY`, transverse crossings `1`, parallel-run fraction `0.0`, volumetric components `1`, enclosed contours `0`.
- Support identity: the two source primitive IDs are `{'fragment_a': ['raw-hough-001150'], 'fragment_b': ['raw-hough-000801']}`; existing evidence does not establish that the two aligned fragments are the same source stroke through the gap.
- Human observation: primary `INVALID_PRIMITIVE_FOR_GAP_REVIEW`; secondary `[]`. Existing previews support only the generic observation that the claimed continuation enters or coincides with a locally structured region; no semantic object label is inferred.
- Audit assessment: individual primitive validity `UNCERTAIN`; pair validity `REJECTED`. Earliest ideal abstention/rejection stage: `PAIR_ADMISSION`.

### Review index 16 — `FRESH1-EAF5141532787D12AFE2`

- Source family/unit: `F03-AS-BUILT-INSTALL-2020-DWG` / `LOCALC-F03-DWG-HVAC4-MODEL-OVERVIEW`
- Geometry: `vertical`, primitive length `139.0 px`, projected span `139.0 px`; claimed extent `[794, 1969]` → `[794, 2108]`; gap `5 px`; gap endpoints `[794, 2034]` → `[794, 2039]`; fragment A `{'end': [794, 2034], 'start': [794, 1969]}`; fragment B `{'end': [794, 2108], 'start': [794, 2039]}`.
- Upstream trace: span `SPAN_INTEGRITY_SUPPORTED`; axis `PRIMITIVE_AXIS_SUPPORTED`; text/glyph `TEXT_UNCERTAIN`; straight `STRAIGHT_UNCERTAIN`; admissibility `DIRECT_CONTINUATION_ADMISSIBLE`; current eligible `True`.
- Straight evidence: fragment statuses/reasons `[('fragment_a', 'STRAIGHT_UNCERTAIN', 'INSUFFICIENT_EVIDENCE'), ('fragment_b', 'STRAIGHT_SUPPORTED', 'STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED')]`. Local tangent profile: `{'status': 'NOT_AVAILABLE_IN_EXISTING_ARTIFACTS', 'diagnostic_available': False}`. No tangent profile was synthesized where the existing diagnostic marked it unavailable.
- Lateral/support profile: axis support `1.0`; centerline support `1.0`; off-axis ink `0.217949`; thickness ratio `1.0`; local density `0.04029`.
- Trajectory profile: clean score `0.852635`; coherence score `0.081838`; supported runs `1`; unsupported intervals `0`. Direct pair evidence: `DIRECT_CONTINUATION_ADMISSIBLE / CLEAR_DIRECT_TRAJECTORY`, transverse crossings `0`, parallel-run fraction `0.0`, volumetric components `1`, enclosed contours `0`.
- Support identity: the two source primitive IDs are `{'fragment_a': ['raw-hough-000425'], 'fragment_b': ['raw-hough-000943']}`; existing evidence does not establish that the two aligned fragments are the same source stroke through the gap.
- Human observation: primary `INVALID_PRIMITIVE_FOR_GAP_REVIEW`; secondary `['CROSSES_STRUCTURE']`. Existing previews support only the generic observation that the claimed continuation enters or coincides with a locally structured region; no semantic object label is inferred.
- Audit assessment: individual primitive validity `UNCERTAIN`; pair validity `REJECTED`. Earliest ideal abstention/rejection stage: `PAIR_ADMISSION`.


## Primitive validity versus pair validity

The two cases are not evidence that the frozen straight-validity gate is wrong. Case 15 has two `STRAIGHT_UNCERTAIN` fragments. Case 16 has one `STRAIGHT_UNCERTAIN` fragment and one `STRAIGHT_SUPPORTED` fragment, with candidate status still `STRAIGHT_UNCERTAIN`. In both cases, the existing pair/admissibility layer returned `DIRECT_CONTINUATION_ADMISSIBLE / CLEAR_DIRECT_TRAJECTORY`.

Both residuals satisfy the existing short-gap admissibility branch: gap ≤ 11 px, no enclosed contour, no more than two transverse crossing columns, and parallel-run fraction ≤ 0.35. That branch deliberately does not use the connected-component statistic. Case 15 has one transverse crossing column and one volumetric component; case 16 has zero transverse crossing columns and one volumetric component. Therefore “crossing means ignore” is not a safe rule, and the common signal is broader: a short-gap pair can be admitted without deterministic source-stroke identity through the gap.

The best-supported shared failure is **pair-level invalidity despite individually credible or unresolved straight evidence**. The earliest safe intervention point is pair admission, where the system should be allowed to abstain when pre-gap and post-gap source identity is not established. The current artifacts do not provide a generic, deterministic identity/mediation rule that separates these two from all valid crossings, so no pair-level guard is implemented in this task.

## Bounded controls

The comparison set is eight cases total: 2 residual cases + 3 known valid pair controls + 3 known invalid pair/continuation controls.

| Control class | Review | Candidate | Existing human primary | Straight status | Existing measured pair evidence |
|---|---:|---|---|---|---|
| VALID_PAIR | 1 | `FRESH1-AB2943863A535D1044B9` | `CONTINUOUS_SOURCE_STROKE` | `STRAIGHT_SUPPORTED` | gap 40; center 1.0; off-axis 0.033721; cross 0; vol 1; direct `DIRECT_CONTINUATION_ADMISSIBLE` |
| VALID_PAIR | 4 | `FRESH1-51DF39D706DE8C684F10` | `CONTINUOUS_SOURCE_STROKE` | `STRAIGHT_UNCERTAIN` | gap 30; center 1.0; off-axis 0.21292; cross 8; vol 0; direct `DIRECT_CONTINUATION_ADMISSIBLE` |
| VALID_PAIR | 8 | `FRESH1-FF28E80F90C3CFA05A78` | `CONTINUOUS_SOURCE_STROKE` | `STRAIGHT_UNCERTAIN` | gap 33; center 1.0; off-axis 0.045349; cross 2; vol 0; direct `DIRECT_CONTINUATION_ADMISSIBLE` |
| INVALID_PAIR | 3 | `FRESH1-2BF547C27C8497056BA6` | `STRUCTURAL_INTERRUPTION` | `STRAIGHT_UNCERTAIN` | gap 5; center 1.0; off-axis 0.262821; cross 2; vol 1; direct `DIRECT_CONTINUATION_ADMISSIBLE` |
| INVALID_PAIR | 7 | `FRESH1-B7300C5B8E706C736EB1` | `STRUCTURAL_INTERRUPTION` | `STRAIGHT_SUPPORTED` | gap 44; center 0.311111; off-axis 0.01376; cross 0; vol 0; direct `DIRECT_CONTINUATION_ADMISSIBLE` |
| INVALID_PAIR | 11 | `FRESH1-98D0BD1ED4DBB02B9A3A` | `STRUCTURAL_INTERRUPTION` | `STRAIGHT_SUPPORTED` | gap 5; center 0.333333; off-axis 0.288462; cross 2; vol 2; direct `DIRECT_CONTINUATION_ADMISSIBLE` |

The valid controls include a human-confirmed continuous source stroke that crosses structure. The invalid controls show why a generic crossing, component count, gap length, or direct-admissibility result alone cannot be used as a pair rejection rule. Pair identity requires additional geometry-only evidence that is not currently frozen in the admissibility contract.

## Review UI pending navigation

The reusable V1.2 review UI now has a presentation-only `只看未完成` toggle, clickable pending review-index chips, filtered previous/next navigation, a compact `清除本题答案` action, live completed/pending counts, and a clear zero-pending message. Import recomputes the pending list from the imported primary classes. The export schema remains exactly `protocol`, `candidate_set_id`, `candidate_id`, `review_index`, `primary_class`, `secondary_flags`, and `optional_note`; no filter state is exported.

## Decision and governance

- Shared generic failure: `YES`, at the pair/admission layer.
- Pair-level guard: `NO`; evidence is diagnostic but not yet a safe rule.
- Straight-validity gate changed: `NO`.
- Span, axis, text/glyph, and admissibility logic changed: `NO / NO / NO / NO`.
- Candidate-specific exception: `NO`.
- Source-gap replacements/package V1.3: `NO`.
- New candidate mining/source acquisition: `NO`.
- Model/model-assisted labeling: `NO`.
- Production semantic delta: `NONE`.
- Validation: `NO`; locked blind: `0 / 8`; H1/H2 opened: `NO`.

Next target: `PAIR_LEVEL_SOURCE_IDENTITY_EVIDENCE_BEFORE_GUARD_DESIGN`.
