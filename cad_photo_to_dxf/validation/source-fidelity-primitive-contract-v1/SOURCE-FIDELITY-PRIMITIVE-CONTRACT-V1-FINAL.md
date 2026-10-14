# Source Fidelity Primitive Contract V1 — Final

BASE CHECKPOINT: `231e091585ad54f1e8fdfd0e3b7c3ca2e1ee3570`

PRODUCTION SEMANTIC DELTA: `NONE`

This is a contract and evidence audit. It freezes human observations and evaluates existing DEV diagnostics without changing reconstruction, eligibility, the human-review UI, or `FinalStructure`. `FinalStructure` remains the single reconstruction authority; this audit does not introduce a competing CIR.

## Authoritative primitive contract

LOW-LEVEL PRIMITIVE RULE: **Source-visible stroke extents are preserved as geometry.** Separate visible strokes remain separate low-level primitives unless credible source/context evidence under explicit reconstruction logic supports restoration of a damaged or missing interval.

PERIODICITY: **Periodicity alone does not authorize destructive merging.** Collinear, regularly spaced, or visually patterned fragments must not become one continuous solid primitive merely because they resemble a dashed CAD linetype.

LOGICAL GROUPING: **A later semantic/grouping layer may express `PATTERN_GROUP`, `LOGICAL_DASHED_LINE`, `ALIGNED_SEGMENT_GROUP`, or `SHARED_SOURCE_OBJECT` without deleting or replacing the source-faithful component segments.** No grouping architecture is implemented here.

DEGRADATION: **Credible restoration of scan dropout, paper damage, broken ink, or other known raster degradation remains allowed, but requires separate evidence.** This contract is not an `any gap => always split` rule.

COLLINEARITY: **Collinearity does not prove primitive identity.**

CROSSING: **Crossing local structure does not automatically terminate primitive identity.** A visibly continuous core stroke remains one source primitive through a crossing.

The unresolved engineering problem is to distinguish: (1) one genuinely continuous source stroke; (2) degradation obscuring one continuous stroke; (3) intentional patterned/segmented geometry; (4) structural termination followed by restart; and (5) different boundaries alternately supporting one global fit. Ink near an axis is not enough.

## Frozen review evidence

- Protocol: `PRIMITIVE_INTEGRITY_REVIEW_V1`
- Candidate set: `FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504-PRIMITIVE-INTEGRITY-748C5A4B61CD`
- Selection digest: `748c5a4b61cde3fb0ce5c754d000498275e06cdb9ae87263d7af0f0d4a47f94a`
- Source export SHA-256: `0e9597c5516c49113f37701f2441ba7a7befd39fdbd12e4bea3a73ae98b5b987`
- Completeness: `16 / 16`
- Human labels modified: `NO`
- Primary counts: valid single straight primitive 10; multiple/offset segments 4; endpoint overshoot 1; other primitive mismatch 1; foreign-stroke capture 0; insufficient evidence 0.

The labels are observations about primitive fidelity over the claimed extent. They are not automatic runtime truth, object/annotation labels, semantic grouping judgments, or professional engineering classifications.

## Existing patterned-stroke assumption audit

### Span integrity

`primitive_span_integrity.py` recognizes `POSSIBLE_PATTERNED_STROKE` and classifies the synthetic periodic pattern as `SPAN_INTEGRITY_UNCERTAIN`, not supported. Only supported records enter ordinary future DEV continuation mining. The older report field `periodic_pattern_safety: PASS` means patterned evidence was preserved as uncertain rather than collapsed into a centerline-support failure or rejected as another family. It does **not** mean a patterned source should be emitted as one continuous low-level primitive.

This portion is compatible with the clarified contract, subject to threshold limits: Review 13's short visible interruption remains below the material-gap thresholds and is classified supported.

### Axis integrity

`primitive_axis_support_integrity.py` recognizes `POSSIBLE_PATTERNED_AXIS_SUPPORT` and the dashed-pattern test requires `PRIMITIVE_AXIS_UNCERTAIN` (or noisy/degraded uncertainty), not support. Only jointly span/axis-supported records remain eligible for ordinary future DEV mining. `patterned_stroke_safety: PASS` therefore means the dashed control is preserved as an uncertain diagnostic case rather than mistaken for a hollow-center rejection. It is not authority to bridge intentional gaps.

This portion is compatible in intent, but Review 13 again falls below the current material-gap/cadence thresholds and is classified supported.

### Coherence and crossing controls

The coherence suite rejects two separated on-axis lines and distributed independent short lines, while preserving a continuous stroke through a perpendicular crossing or local symbol. These tests align with the clarified contract and with Review 8.

### Direct-continuation admissibility

The partial conflict is in the DEV pair-admissibility assumption. `test_admissibility_decision_and_reason_are_deterministic` constructs two distinct collinear source fragments with a clear 20-pixel blank interval and explicitly requires `DIRECT_CONTINUATION_ADMISSIBLE / CLEAR_DIRECT_TRAJECTORY`. `test_valid_object_and_continuous_annotation_are_not_semantically_filtered` preserves the same empty-gap behavior. Neither supplies independent evidence that the interval is scan/paper degradation.

That behavior is semantically outdated for low-level source geometry. An empty, unobstructed, collinear gap is not positive degradation evidence. The current test remains unchanged because no safe replacement classifier is demonstrated: changing the assertion without a generic intentional-gap-versus-degradation signal would either fail the current implementation or disable legitimate damage restoration.

EXISTING PATTERNED-STROKE ASSUMPTION CONFLICT: `PARTIAL`

SEMANTICALLY OUTDATED TESTS FOUND: `YES`

## Frozen 16 diagnostic join

Existing diagnostic functions were run unchanged on each review record's claimed start-to-end geometry. The frozen 147-pool pair decision supplies current eligibility. These are diagnostic observations only; no candidate eligibility changed.

Abbreviations: `S` supported, `U` uncertain, `R` rejected. The measurement tuple is coherence continuity / longest disjoint fraction / center-offset range in stroke widths / tangent p95 degrees, followed by endpoint status and reason.

| Review | Candidate ID | Human primary | Secondary flags | Span | Axis | Coherence measurements | Endpoint measurements | Current eligibility | Diagnostic mismatch summary |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `FRESH1-316D125FE4861584BE02` | `MULTIPLE_OR_OFFSET_SEGMENTS` | multiple, foreign, crossing | S | S | U direction; 0.652 / 0.038 / 4.83w / 32.1° | U identity; gap-tail 0.042, width 9.67 | admissible | Direction and identity instability are visible, but span/axis/admissibility still accept. |
| 2 | `FRESH1-2BF547C27C8497056BA6` | `MULTIPLE_OR_OFFSET_SEGMENTS` | multiple, crossing | S | S; cadence observed | U direction; 0.886 / 0.043 / 3.65w / 34.7° | U identity; width 13.0 | admissible | Explicit structural interruptions remain hidden by dense collinear support. |
| 3 | `FRESH1-4497ADEE7DB5D798A893` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | crossing | S | S | S; 0.962 / 0.006 / 2.00w / 9.6° | U identity | admissible | Core diagnostics agree; endpoint ambiguity alone is not failure. |
| 4 | `FRESH1-33163D6DB78308987FD9` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 0.953 / 0.011 / 0.50w / 3.4° | U insufficient | admissible | Core diagnostics agree. |
| 5 | `FRESH1-9EA3C91753BCB75F3C3B` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 1.000 / 0.000 / 1.00w / 4.6° | U insufficient | admissible | Core diagnostics agree. |
| 6 | `FRESH1-9FC98ED192F6BC59B8A7` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 0.984 / 0.000 / 3.69w / 5.4° | U identity | admissible | Core diagnostics agree; endpoint ambiguity overlaps a valid case. |
| 7 | `FRESH1-A5AC051A1FE6345BF242` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 0.994 / 0.000 / 3.50w / 0.0° | U identity | admissible | Core diagnostics agree; terminal width alone is unsafe. |
| 8 | `FRESH1-AB2943863A535D1044B9` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | crossing | S | S | S; 1.000 / 0.000 / 3.00w / 0.0° | U identity | admissible | Negative control passes: a continuous stroke remains valid through local structure. |
| 9 | `FRESH1-C657B684CE259ECAFB9C` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 1.000 / 0.000 / 0.00w / 0.0° | U insufficient | admissible | Core diagnostics agree. |
| 10 | `FRESH1-91B55E0A36DB80262006` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 0.963 / 0.000 / 4.35w / 13.4° | U identity | admissible | Endpoint identity ambiguity overlaps a valid case. |
| 11 | `FRESH1-8E7790E578C3E072DFF7` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 1.000 / 0.000 / 0.49w / 4.0° | U insufficient | admissible | Core diagnostics agree. |
| 12 | `FRESH1-4EEE2937A498A9FE051F` | `ENDPOINT_OVERSHOOT` | — | S | S | U insufficient; 0.944 / 0.005 / 4.90w / 5.3° | U identity; gap-tail 0.046 | admissible | Human overshoot is not independently confirmed by current endpoint evidence. |
| 13 | `FRESH1-9BB32E8680E08F3ED86C` | `MULTIPLE_OR_OFFSET_SEGMENTS` | crossing | S | S | S; 0.940 / 0.036 / 0.00w / 0.0° | U insufficient | admissible | Patterned-fragment contract anchor is a current false negative across all primitive diagnostics. |
| 14 | `FRESH1-F18CEDA77DCF47A4DB08` | `VALID_SINGLE_STRAIGHT_PRIMITIVE` | — | S | S | S; 0.902 / 0.000 / 3.00w / 18.5° | U insufficient | admissible | Core diagnostics agree. |
| 15 | `FRESH1-83DFE0F6BE9016CC7844` | `OTHER_PRIMITIVE_MISMATCH` | multiple, crossing | R competing structure | U patterned | R disjoint; 0.628 / 0.194 / 5.17w / 47.4° | U foreign; offset 2.0w | admissible | Measurements support a disjoint/boundary-switch hypothesis; they do not relabel the human primary. |
| 16 | `FRESH1-585E8520AB511B998A25` | `MULTIPLE_OR_OFFSET_SEGMENTS` | crossing | S | S | S; 0.921 / 0.045 / 1.50w / 11.0° | U identity | admissible | Irregular interruptions and nearby linework are masked by approximately collinear ink. |

Join completeness:

- Frozen 16 joined to span diagnostics: `YES` (15 supported, 1 rejected).
- Frozen 16 joined to axis diagnostics: `YES` (15 supported, 1 uncertain).
- Frozen 16 joined to coherence diagnostics: `YES` (12 supported, 3 uncertain, 1 rejected).
- Frozen 16 joined to endpoint diagnostics: `YES` (16 uncertain; none independently confirmed by a safe rejection result).
- Frozen 16 joined to admissibility: `YES` (16 frozen-pool admissible; no eligibility changed).

## Failure-family analysis

Human labels are observations. Family assignments below require source facts and/or independent measurements; uncertain hypotheses are not promoted to runtime truth.

- `STRUCTURAL_INTERRUPTION_COLLAPSE`: **CONFIRMED** for Review 2 by explicit hollow/structural interruption evidence. The current dense-support diagnostics miss it.
- `PATTERNED_FRAGMENT_COLLAPSE`: **CONFIRMED** for Review 13 by repeated visible source fragments and the corrected human decision. The 4% interruption falls below current thresholds.
- `IRREGULAR_FRAGMENT_COLLAPSE`: **SUPPORTED** by Review 16's irregular structural interruptions and multiple/offset observation, but the existing diagnostics do not isolate a generic signal.
- `PIECEWISE_OFFSET_COLLAPSE`: **SUPPORTED** by Review 1's 4.83-stroke-width center-offset range plus excessive local direction change, and by Review 15's disjoint trajectory; no single-family causal boundary is established.
- `SOURCE_BOUNDARY_SWITCH`: **SUPPORTED** for Review 15 by rejected span/coherence, a 5.17-stroke-width offset range, and disjoint local trajectory. It remains a diagnostic hypothesis, not a relabel to `FOREIGN_STROKE_CAPTURE`.
- `ENDPOINT_OVERSHOOT`: **SUPPORTED**, not independently confirmed, for Review 12. The human observation is accompanied only by uncertain endpoint identity evidence that overlaps valid controls.

The four `MULTIPLE_OR_OFFSET_SEGMENTS` cases are not one clean measured family. Review 13 and Review 16 are particularly important false negatives: current proximity/coherence evidence can be high while source primitive identity is still wrong.

## Guard decision

No generic source-stroke-continuity guard is justified now. Review 13 and Review 16 evade current signals; a gap-only guard would disable legitimate damage restoration; and the valid Review 8 crossing must remain safe. A production or DEV runtime guard would currently require either candidate-specific exceptions or an unsupported assumption about whether blank space is intentional or degraded.

No separate endpoint rejection guard is justified now. Review 12 remains uncertain, while identity/width/junction endpoint signals also appear in valid Reviews 3, 6, 7, 8, and 10. Endpoint evidence expansion remains useful, but not as the immediate primary target.

CURRENT SPAN GUARD CHANGED: `NO`

CURRENT AXIS GUARD CHANGED: `NO`

CURRENT ADMISSIBILITY GUARD CHANGED: `NO`

GENERIC SOURCE-STROKE-CONTINUITY GUARD: `NO`

GENERIC ENDPOINT GUARD: `NO`

## Required engineering decision

A. Clarified contract conflicts with an existing DEV patterned-stroke assumption: **PARTIAL**. Span/axis/coherence handling is conservative, but clear-gap direct-continuation admissibility lacks degradation evidence and Review 13 demonstrates the false-negative boundary.

B. Existing tests semantically outdated: **YES**. The clear-empty-gap admissibility expectations are outdated under the low-level contract. They remain unchanged pending a safe replacement signal.

C. Generic source-stroke-continuity guard justified now: **NO**.

D. Separate endpoint guard justified now: **NO**.

E. More targeted human evidence needed: **YES**.

F. Ordinary Batch-03 should resume now: **NO**.

G. Model bake-off should resume: **NO**.

NEXT TARGET: **A — targeted source-gap review design**, explicitly stratifying intentional patterned gaps, structural terminations/restarts, credible scan/paper degradation, continuous crossings, and boundary-switch cases. This task does not create that package.

## Governance and verification

- No production code or reconstruction semantics changed.
- No DEV guard or eligibility rule changed.
- No UI V2 file changed.
- No source-derived image, PDF, DWG, screenshot, or model is tracked.
- New candidate mining: `NO`.
- New human review package: `NO`.
- Model run: `NO`; model-assisted labeling: `NO`; model bake-off: `NO`.
- Validation: `NO`; locked blind: `0 / 8`; locked-blind manual inspection: `NO`; H1/H2 opened: `NO`.
- User-supplied source imagery: internal development authorized; public redistribution not authorized.
- Focused verification: `61 passed in 39.65s` across the contract-freeze test and the existing primitive span, primitive axis, primitive coherence/endpoint, and direct-continuation admissibility suites.
