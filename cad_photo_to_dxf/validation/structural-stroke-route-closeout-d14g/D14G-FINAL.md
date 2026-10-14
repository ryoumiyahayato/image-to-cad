# D14G structural-stroke perception route closeout

## Engineering decision

The D5-D14 investigation is classified as **EXPLORATORY PHASE COMPLETE**, not
`PROBLEM SOLVED`.

The root cause is understood, the safe boundary of handcrafted continuation
logic is established, a useful new visual evidence source has been identified,
and transfer to genuinely new source families has been demonstrated. The
production solution remains incomplete. The next development direction is a
bounded, source-diverse DEV dataset followed by honest comparisons against the
frozen reference baseline. No production integration or dataset expansion is
authorized by this closeout.

The formal development conclusions are:

| Question | Decision |
|---|---|
| Is visual semantic perception worth continuing? | **YES** |
| Is generic MobileNet already production-ready? | **NO** |
| Is a domain-specific representation already justified? | **NOT_YET** |
| Is a larger multi-source DEV dataset justified? | **YES** |
| Is production integration justified now? | **NO** |

These distinctions are intentional. Evidence of useful transfer justifies
further development; it does not establish production performance, calibrated
uncertainty, or safe reconstruction behavior.

## Established root cause

Source and processing-binary evidence can remain continuous while
`detect_lines` Hough/LSD emits endpoint-bounded fragments. The detector union
therefore contains real uncovered intervals before recentering, proposal
capping, consolidation, eligibility, ownership, or `FinalStructure`.

D2-001 and D2-006 demonstrate this mechanism across more than one source.
D2-006 also shows that consolidation can improve coverage without repairing
the full loss. The root cause is not generic source absence, global
preprocessing failure, the 5,000-segment cap, consolidation alone, or
`FinalStructure` mutation. This diagnosis is closed and should not be reopened
without contradictory evidence.

## Boundaries of failed or insufficient routes

D6 found that the existing downstream text, ownership, fallback, and topology
evidence could not safely resolve seven qualified structural continuations
against four hard dimension/text lookalikes. Both classes remained operationally
ambiguous; downstream survival was not a valid semantic discriminator.

D7 found no robust handcrafted separation across local, meso, and wide
morphology. Axial persistence and long-range support carried partial signal,
but their ranges overlapped. Width stability, drift, occupancy, off-axis
complexity, anisotropy, and related measurements also overlapped or changed
direction. Genuine dimension, text, and annotation structures can be connected,
collinear, persistent, and line-dominant in the same ways as real structure.

Therefore source continuity plus collinearity is necessary evidence for a
continuation hypothesis but is insufficient semantic authorization to accept
one. Generic bridge/snap heuristics would reproduce the known unsafe overlap
and are not a recommended route.

## New perception evidence from D12-D14

D12 and D13 showed that a frozen OpenCV Zoo MobileNetV2 pooled representation
contains useful `STRUCTURAL_CONTINUATION` versus `ANNOTATION_OR_GLYPH` signal.
In D13B, the six-source 28-case leave-one-source-group-out aggregate was 23/28:
84.2% structural precision, 88.9% structural recall, 70.0% annotation recall,
and three dangerous false structural predictions. Signal survived every fold,
but family behavior remained source-sensitive.

D14A diagnosed `CLASS_VS_SOURCE_DOMINANCE: MIXED`. Source style was comparable
to class structure, while class-directed information remained. Global centroid
shift sensitivity and source-count balance effects were low, so merely adding
more crops from the same sources was unlikely to solve transfer. Correct and
incorrect cosine margins overlapped materially.

D14F was the first frozen exposure to 13 prediction-blind cases from genuinely
new historical, mechanical, and civil source families. It produced:

| Scope | Correct | Structural precision | Structural recall | Annotation recall | Dangerous false structural |
|---|---:|---:|---:|---:|---:|
| H1 historical | 3/4 | 100.0% | 50.0% | 100.0% | 0 |
| H2 mechanical | 3/4 | 50.0% | 100.0% | 66.7% | 1 |
| C1 civil | 4/5 | 100.0% | 75.0% | 100.0% | 0 |
| **Aggregate** | **10/13** | **83.3%** | **71.4%** | **83.3%** | **1** |

The always-structural comparator would produce six dangerous errors among the
six annotation cases. Reducing that count from six to one while recovering
five of seven structural cases demonstrates transferable class signal. H1 and
H2 each achieved 3/4, so the result was not carried only by C1. The sample is
small, and H2 has only one structural positive; it is evidence of transfer, not
a production performance estimate.

D14F's generalization verdict, preserved here, is
`NEW_SOURCE_GENERALIZATION_SUPPORTED`.

## Structural-Stroke Reference Baseline V1

The current frozen diagnostic configuration is designated:

**STRUCTURAL-STROKE REFERENCE BASELINE V1**

| Component | Frozen definition |
|---|---|
| Encoder | OpenCV Zoo MobileNetV2 `image_classification_mobilenetv2_2022apr.onnx` |
| Upstream commit | `47534e27c9851bb1128ccc0102f1145e27f23f98` |
| SHA-256 | `C0C3F76D93FA3FD6580652A45618618A220FCED18BABF65774ED169DE0432AD5` |
| Feature layer | `onnx_node!GlobalAveragePool_97` |
| Feature shape | 1,280 local + 1,280 context = 2,560 concatenated dimensions |
| Classifier | cosine nearest class centroid |
| Abstention | `NONE` |
| D13B whole-source reference | 23/28; 3 dangerous false structural |
| D14F new-source reference | 10/13; 1 dangerous false structural among 6 annotation cases |

This is an immutable comparison definition and a reference measurement, not a
production dependency. Future experiments must declare any changed encoder,
layer, preprocessing, crop, normalization, classifier, training set, or
rejection rule and must compare honestly with V1. They must not silently
redefine V1 after seeing results.

## Primary unsolved safety failure

The strongest current hard-negative concern is line-dominant annotation that
visually resembles object structure. Priority examples are dimension extension
and witness lines, dimension chains, leaders, drawing-layout rules, and similar
annotation-derived long straight strokes.

D14F's only dangerous new-source error, `D14E-142FAB52579F`, is an H2 mechanical
`dimension_extension_witness_line`. It is an important future data and
evaluation target because its long, clean, object-adjacent geometry resembles
a structural edge. It must not be addressed with a one-case special rule.
Future work must test the broader failure family across independent sources and
annotation conventions.

## Uncertainty remains unsolved

`COSINE_MARGIN_NOT_VALID_UNCERTAINTY_PROXY` remains the governing result.

- Correct and incorrect absolute-margin distributions overlap.
- A dangerous D13B error reached a larger margin than some correct cases.
- The ambiguity reserve received a confident-looking margin.
- D13B's train-only threshold abstained on 8/10 held-out cases, accepted no
  structural case, and still failed to reject the ambiguity reserve.

Consequently V1 has no accepted abstention mechanism. Future development needs
a different uncertainty or rejection strategy evaluated on independent data.
Another hand-tuned cosine cutoff is not the solution.

## Next DEV dataset principle and bounded scale

The next dataset must prioritize **SOURCE FAMILY DIVERSITY**, not volume from
the six existing sources and not simply more positive lines. Hard negatives
remain first-class examples.

One bounded development iteration should target:

- approximately **8-10 additional source families**;
- approximately **80-120 independent qualified cases** in total;
- at least **35 structural and 35 annotation/glyph cases** overall, with both
  classes represented in every admitted source family and a target of at least
  three independent examples of each class per family where the source permits;
- at least **six hard-negative subtypes**, with priority coverage for dimension
  witness/extension lines, dimension chains, leaders, drawing-layout rules,
  aligned glyph/text strokes, and one additional source-discovered line-dominant
  subtype;
- for each of the four priority line-dominant annotation subtypes, a target of
  at least five independent cases spanning at least two source families;
- no single source family dominating the corpus; repeated crops from one
  drawing must remain clustered for splitting and independence accounting.

The additional families should deliberately cover mechanical dimension/PMI
conventions, degraded raster and archival styles, independent civil/profile
conventions, electrical and installation styles, additional organizations or
vendors, different vector/raster generation processes, and varied typography,
title, and dimension conventions.

These numbers are bounded **development targets**, not statistically certified
production sample requirements and not universal accuracy gates. They are large
enough to test source and hard-negative diversity in one iteration without
prescribing hundreds of PDFs. Acquisition, labeling, and dataset creation are
outside D14G.

## Holdout and data governance

H1 historical and H2 mechanical remain `NEW-SOURCE HOLDOUTS`. Their D14F
measurements are permanent reference results unless a later explicit governance
redesign says otherwise. They must not enter fitting, classifier selection,
calibration, or rejection development merely because their predictions have
been exposed.

C1's untouched baseline has been recorded. C1 may become DEV adaptation
material only in a separate, explicit task that states the governance change;
D14G does not make that change.

`VALIDATION` remains untouched. `LOCKED_BLIND` remains 0/8.

## Staged future development

### Stage 1: source-diverse labels

Build the bounded multi-source DEV set under an explicit protocol while
preserving Reference Baseline V1 unchanged. Freeze candidate identities and
human labels before model comparison, track physical/source independence, and
report each source family and hard-negative subtype separately.

### Stage 2: compare representations and decision methods

Only after Stage 1 is frozen, evaluate whether a stronger classifier or visual
representation improves on V1. Candidate evidence sources may include a better
pretrained visual encoder, a small domain-adapted representation, a learned
classifier, explicit dimension/text context evidence, or domain-knowledge
evidence. No winner is preselected. The data must determine whether generic
features remain adequate or domain adaptation becomes justified.

Uncertainty/rejection must be evaluated as a distinct safety capability, not
inferred from cosine margin. Comparisons must include dangerous false structural
errors, structural recovery, per-family stability, per-subtype behavior, and
paired regression controls.

## General perception and domain knowledge

General perception should primarily answer: **What does this local/context
visual evidence resemble?** Its evidence states may include structural
continuation, annotation/glyph, or ambiguous visual evidence.

Domain knowledge may later answer: **What would this stroke mean in this
engineering discipline?** It may contribute dimension semantics, conductor
semantics, wall/object role, topology expectations, or symbol conventions. It
may support, reject, or qualify a hypothesis, or raise it for human review.

Domain knowledge must not manufacture geometry unsupported by source evidence.
A knowledge pack must never bypass source support or directly write into
`FinalStructure`.

## Intended eventual integration shape

No integration is implemented here. The intended responsibility chain is:

```text
source evidence
  -> detector fragments
  -> continuation hypothesis
  -> visual semantic evidence
  -> optional domain evidence
  -> evidence arbitration
  -> ACCEPT / REJECT / AMBIGUOUS
  -> accepted and source-supported result may enter normal reconstruction
  -> FinalStructure remains sole authority
```

The perception model is advisory evidence. It must never directly mutate
`FinalStructure` or CAD, and `AMBIGUOUS` must remain a valid non-mutating result.

## Future production entry gates

Production integration cannot begin until future DEV evidence demonstrates all
of the following:

1. Cross-source-family stability, reported by family rather than hidden in an
   aggregate.
2. Explicit measurement and audit of dangerous
   `ANNOTATION_OR_GLYPH -> STRUCTURAL_CONTINUATION` errors.
3. Robust coverage of line-dominant and other hard-negative subtypes across
   independent source families.
4. An uncertainty/rejection mechanism demonstrably better than current cosine
   margin, including ambiguous cases and retained structural utility.
5. Deterministic provenance from model input and version through evidence,
   arbitration, and final decision.
6. A source-support invariant that prevents direct unsupported geometry
   creation.
7. Paired positive and negative regression controls covering recovery and
   unsafe bridging.
8. Human-visible reconstruction improvement on representative drawings.
9. No unacceptable regression on existing good cases, including fragmentation
   controls and currently preserved structure.

No universal accuracy threshold is declared. Candidate numerical gates may be
predeclared in a future protocol, but they are engineering acceptance targets
to be validated against the new dataset, not scientifically established
constants.

## Closeout state

| Decision | State |
|---|---|
| Root cause understood | YES |
| Handcrafted route boundary established | YES |
| New visual evidence source identified | YES |
| New-source transfer demonstrated | YES |
| Production solution complete | NO |
| Next development direction known | YES |
| Exploratory phase | COMPLETE |
| Ready for production integration | NO |

Production semantic delta: `NONE`. Next production change candidate: `NONE`.
No model, threshold, dataset, knowledge pack, production code, VALIDATION, or
LOCKED_BLIND asset was created, modified, run, or inspected in D14G.
