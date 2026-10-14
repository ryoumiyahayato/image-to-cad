# Structural stroke perception design D8

## Decision

The minimum new perception task is a selective, candidate-conditioned, two-view
classification task. Given an already proposed pair of fragmented line candidates,
the unchanged source grayscale, and the unchanged processing binary, it determines
whether the source context supports one of three advisory states:
`STRUCTURAL_CONTINUATION`, `ANNOTATION_OR_GLYPH`, or `AMBIGUOUS`.

This is deliberately not a page parser. It does not read text, segment a page,
infer topology, reconstruct a line, or decide final ownership. Its only purpose is
to supply the missing broader-context evidence demonstrated by D5/D6/D7.

The current DEV evidence is not sufficient to build an honest prototype. There
are only seven qualified positive candidates across two source groups and four
hard dimension/text negatives from one source group. A cross-source evaluation
of the hard-negative distinction is therefore impossible today. The design is
complete, but data qualification must precede implementation.

## Narrow task contract

### Unit of inference

One example consists of:

- exactly two existing line fragments proposed by the current detector or
  consolidation stage;
- their stable candidate IDs and source-support IDs;
- the gap and common-axis hypothesis already computed from those fragments;
- a local view identifying the exact pair and gap; and
- a wider view containing enough surrounding drafting context to expose
  dimension markers, nearby text/glyph layout, repeated dimension chains, and
  neighboring engineering geometry.

The classifier answers only: "What kind of source context surrounds this proposed
continuation?" It does not answer whether a line should be drawn.

### Exact input representation

The minimum representation is option E implemented as two paired instances of
option C: **local and broader-context crops, each containing grayscale, binary
support, and a candidate overlay**.

Before cropping, rotate the candidate coordinate frame so the hypothesized common
axis is horizontal and order the fragments left-to-right. Record the complete
inverse transform so every pixel remains traceable to source coordinates. Let
`g` be the inner-endpoint gap, `w` the median detected fragment width (at least one
pixel), and `L` the outer-endpoint span of the pair in that normalized frame.

The two views are deterministic:

1. **Local view:** include the pair's outer-endpoint span plus axial padding
   `p = max(g, 16w)` on each side. Use transverse half-height
   `max(12w, 0.20(L + 2p))`. This view exposes the exact gap, both fragments,
   immediate endpoints, nearby arrowheads/nodes, and local crossings.
2. **Context view:** use the same center and orientation, with both dimensions
   four times the local view. Clip at page boundaries and pad outside the page.
   This view exposes longer axial persistence, repeated dimension intervals,
   associated text placement, and neighboring drawing geometry. If decisive
   context remains outside this view, the sample must be labeled `AMBIGUOUS`; the
   crop must not be expanded by looking at the answer.

Letterbox the local view to 256 by 128 pixels and the context view to 256 by 256
pixels without changing aspect ratio. Use bilinear interpolation only for
grayscale and nearest-neighbor interpolation for masks. Each view has three
channels:

- channel 0: source grayscale, normalized by fixed page-level robust intensity
  statistics recorded with the example;
- channel 1: unchanged binary foreground support (`1` for source ink); and
- channel 2: categorical candidate overlay (`0` background, `1/3` first
  fragment, `2/3` hypothesized gap corridor, `1` second fragment), resampled only
  with nearest-neighbor interpolation.

The gap corridor in channel 2 identifies the question; it is not asserted source
ink and cannot become geometry. Source-group ID, page filename, downstream result,
current owner, and final-fate fields are provenance only and must never be model
features.

### Representation comparison

| Candidate | Assessment |
|---|---|
| A. Raw grayscale crop | Preserves tone and scan damage but does not identify which of many nearby strokes is the candidate. Insufficient. |
| B. Grayscale plus binary | Adds the detector's support basis but still leaves the target pair implicit. Insufficient in dense regions. |
| C. Grayscale, binary, candidate overlay | Minimal sufficient representation for the local question, because it preserves source appearance while identifying the pair and proposed gap. |
| D. Local plus larger crop | Required by D7, but both crops still need explicit candidate conditioning. |
| E. Multi-scale paired inputs | Recommended minimum when instantiated as two C-style views. More than two scales is not justified yet. |

Raw grayscale is retained because thresholding can erase faint arrowheads, glyph
parts, and scan evidence. Binary support is retained because the advisory must be
anchored to the same source support seen by the pipeline. The overlay is retained
because the crop can contain many plausible axes. The wider view is mandatory
because D7 found material overlap in every tested local/meso/wide handcrafted
scalar family.

## Context requirement

Broader context is required. The model should be allowed to see, as pixels rather
than pre-decided semantic features:

- the local gap neighborhood and the two fragment endpoints;
- longer context on both sides of the candidate axis;
- arrowheads, ticks, extension lines, leaders, and other dimension markers;
- nearby text/glyph placement even when OCR cannot read it;
- repeated, regularly spaced dimension-chain structure; and
- neighboring walls, nodes, bays, or other engineering geometry that makes a
  structural interpretation credible.

This is a task definition, not an assumption that all of those cues will be
available or decisive. Absence, clipping, damage, or conflict among them is a
reason to abstain. No OCR transcript, symbol identity, topology graph, or page
semantic map is required for the first capability.

## Labels and annotation rules

### `STRUCTURAL_CONTINUATION`

Assign only when the visible source supports that both fragments belong to the
same physical drafting stroke or boundary and the broader context is structural.
At least one positive contextual cue must be visible beyond mere collinearity,
such as continuation through compatible structural nodes/bays, consistent
relationship to neighboring engineering geometry, or clearly shared structural
endpoints. The source must not show that the pair is a dimension line, extension
line, leader, text stroke, or glyph component. Source damage may be present only
if it does not make identity or continuity uncertain.

### `ANNOTATION_OR_GLYPH`

Assign only when the proposed pair visibly belongs to annotation: a dimension or
extension chain, arrow/tick/leader construction, text baseline or glyph stroke,
or a repeated annotation layout. Legible OCR is not required, but the contextual
association must be visible. A line crossing or touching text is not enough by
itself; a genuine structural line near text remains structural if its identity is
otherwise clear.

### `AMBIGUOUS`

Assign when source resolution, crop coverage, occlusion, scan damage, overlapping
roles, or conflicting cues prevent a reliable choice between the other labels.
Also assign it when the two fragments may not share one source identity, when a
candidate is neither a structural continuation nor annotation/glyph, or when two
independent reviewers disagree after viewing both crops and the source-coordinate
location. `AMBIGUOUS` is a real label, not discarded data.

Annotation should be performed independently by two reviewers using only DEV
source evidence and candidate geometry. Agreement produces a label; disagreement
is adjudicated only when source-visible evidence resolves it, otherwise the final
label remains `AMBIGUOUS`. Each record should retain reviewer labels, confidence,
and a short evidence code (`STRUCTURAL_CONTEXT`, `DIMENSION_MARKERS`,
`TEXT_LAYOUT`, `SOURCE_DAMAGE`, `INSUFFICIENT_CONTEXT`, or `ROLE_CONFLICT`). If a
reviewer cannot assign a label from source evidence, the system must not infer one
from the failed D5/D6/D7 heuristics.

## Training target and abstention

Train a three-class conditional distribution over the label set, retaining
`AMBIGUOUS` as an explicit target. At inference, apply a separately calibrated
selective-decision layer:

- emit `SUPPORTED_STRUCTURAL` only when the calibrated structural probability
  and its margin over annotation satisfy a source-held-out operating point;
- emit `REJECTED_ANNOTATION` only when annotation confidence satisfies its
  source-held-out operating point; and
- emit `AMBIGUOUS` for low maximum confidence, small class margin, model/checkpoint
  disagreement, detected distribution shift, clipped required context, or an
  explicit ambiguous-class prediction.

The structural operating point must be precision-oriented because a false
structural result could encourage unsupported geometry. No numeric probability
threshold is proposed: current data cannot justify one. Calibration and threshold
selection must use source groups excluded from fitting, never crops randomly held
out from the same page.

## DEV dataset feasibility

Only checked-in DEV diagnostic registries and reports were used for this count.
No VALIDATION source was used and LOCKED_BLIND was neither executed nor inspected.
The authoritative corpus allocates 15 DEV source groups, but allocation is not the
same as candidate annotation. The known continuation inventory is:

| Role | Count | Source-group coverage | Suitability |
|---|---:|---:|---|
| Qualified fragmented structural positives | 7 | 2 (`A2-SG-009`, `A2-SG-022`) | Usable seed labels: six thin cases and one mixed thick/thin case. |
| Hard dimension/text negatives | 4 | 1 (`A2-SG-009`) | Usable seed labels, but unusable for cross-source hard-negative evaluation. |
| Explicit ambiguous source cases | 1 | 1 (`A2-SG-009`) | `D2-R02`, where source damage prevents a reliable continuity/identity label. |
| Real easy/rejection controls | 3 | 2 | `D2-R01`, `D2-R04`, and `D5-TEXT-UR-02`; useful for contract checks, not substitutes for hard negatives. |
| Intact structural no-regression control | 1 | 1 (`A2-SG-022`) | `D2-005`; gate case, not a fragmented-pair training positive. |
| Synthetic blank/double-rule controls | 3 | synthetic | Gate-only; exclude from training and source-diversity counts. |

All eleven D7 structural/hard-negative candidates are ambiguous to the existing
handcrafted evidence, but that is not their annotation label: seven have
source-qualified structural identity and four have source-qualified
dimension/text identity. Counting them again as `AMBIGUOUS` would erase the very
supervision the new task needs.

This inventory is insufficient for a prototype claim. In particular, holding out
`A2-SG-009` leaves no hard negatives for training, while training on it leaves no
independent hard-negative source for testing. The 15-group DEV allocation makes a
future source-group split possible only after additional DEV pages are acquired
where needed, candidate pairs are generated without label-dependent filtering,
and humans qualify structural, hard-negative, and ambiguous examples.

### Sample construction

Positive construction must start from independently human-qualified continuous
source structures for which the existing detector emits two or more fragments.
Enumerate candidate pairs using a fixed, label-blind proposal policy, then label
from the source views. Include thin, thick, faint, damaged-but-legible, horizontal,
and vertical cases, but do not create extra samples by sliding many overlapping
crops over one stroke.

Hard negatives must be mined from the same proposal policy and include dimension
lines, extension lines, arrow/tick neighborhoods, leader lines, text baselines,
and individual glyph strokes that resemble the positive geometry. Same-page hard
negatives are valuable because they prevent page style from becoming the class
signal. Easy negatives should cover target mismatch, intentional openings,
parallel rules, and blank gaps. Ambiguous samples must come from genuine reviewer
uncertainty, damage, clipping, or role conflict; do not manufacture ambiguity by
corrupting otherwise clear examples.

Do not auto-label from collinearity, corridor occupancy, persistence, width,
anisotropy, text-mask overlap, ownership, or any weighted combination of D5/D6/D7
features. Those measurements may nominate unlabeled candidates for review, but
they cannot supply ground truth.

### Avoiding source-specific overfitting

- Assign train, calibration, and test partitions by `source_group_id` before crop
  generation. Pages, neighboring crops, candidate fragments, and derived same-source
  variants must stay together.
- Deduplicate overlapping candidate pairs and all pairs derived from the same
  physical stroke before counting examples.
- Balance sampling by source group rather than raw crop count; cap contributions
  from any page or repeated dimension chain.
- Include structural and annotation examples from the same sources whenever
  possible, so scan tone, language, title-block style, and renderer do not encode
  the label.
- Exclude filenames, IDs, page positions, downstream ownership, final fate, and
  D5/D6/D7 result fields from model inputs.
- Use only geometry-preserving augmentations consistent with drafting semantics.
  Do not use augmentation to claim new independent samples or source diversity.

## Lightweight model-family analysis

| Family | Small-data tolerance | Uncertainty/calibration | Deployment and inspection | Assessment |
|---|---|---|---|---|
| Small CNN trained from scratch | Poor with the present source count | Simple to calibrate but likely overconfident | Fast and local; saliency is available | Too data-hungry and prone to learning page style from the current inventory. |
| Small patch transformer trained from scratch | Poor | Can expose attention but calibration still needs held-out sources | Local deployment is possible but unnecessary complexity | Not justified for the first prototype. |
| Pretrained lightweight visual encoder plus shallow head | Best of these for a small qualified corpus | Frozen or lightly tuned encoder supports simple post-hoc calibration and checkpoint comparison | Fast, offline-capable, reproducible, and easy to retrain | Recommended starting family after data sufficiency. |
| Multi-scale dual-branch classifier trained end-to-end | Matches the input semantics | Can combine local and context uncertainty | More parameters and more overfit risk | Defer; first test shared encoder weights with shallow two-view fusion. |

The recommended future family is a compact pretrained visual encoder shared by
both views, with pooled local/context embeddings concatenated into a shallow
three-class head. Start with the encoder frozen and train only the fusion/head;
unfreeze only if cross-source evidence shows underfitting. Use deterministic
preprocessing, fixed model/evidence versions, calibrated probabilities, and a
reject option. This recommendation is conditional on obtaining sufficient DEV
labels; no model should be trained in D8.

## Advisory-only integration contract

The evidence should be computed after raw detection and existing thick-fragment
consolidation have produced a candidate pair, but before the current text-filter
boundary can erase candidate identity. It enters a continuation-hypothesis ledger
owned by `SourceSupportLifecycle`, linked to both fragment candidate IDs and the
registered source support.

Conceptually:

`fragment pair + source support + perception evidence -> continuation hypothesis state`

The lifecycle evidence record must contain:

- stable `evidence_id`, `model_id`, model/checkpoint digest, preprocessing version,
  and calibration ID;
- source-group/page provenance, source-support IDs, candidate IDs, source-space
  region, crop geometry, forward/inverse transforms, and input-content hashes;
- three calibrated class probabilities, predicted label, uncertainty/abstention
  reasons, and any distribution-shift flag;
- the requesting stage and exact decision consumer;
- the resulting advisory state (`SUPPORTED_STRUCTURAL`, `REJECTED_ANNOTATION`, or
  `AMBIGUOUS`); and
- every downstream consumer plus final fate, ownership, promoted geometry IDs,
  FinalStructure ID, terminal reason, and any instrumentation gap.

Allowed influence is intentionally narrow:

- `SUPPORTED_STRUCTURAL` may preserve the pair and its source-support identity as
  a continuation hypothesis for later validation, or route it to review. It may
  contribute confidence to an existing candidate-preservation decision.
- `REJECTED_ANNOTATION` may reject the continuation hypothesis or route it toward
  annotation handling. It must not delete source pixels or settle ownership by
  itself.
- `AMBIGUOUS` preserves provenance and leaves current production behavior
  unchanged; it may route the case to review.

The evidence must never directly draw a CAD line, merge fragments unconditionally,
bridge blank source regions, override direct damage evidence, bypass content
ownership, suppress graphic fallback, or bypass FinalStructure construction and
validation. `FinalStructure` remains the sole reconstruction authority. If the
model is missing, mismatched, non-deterministic, out of distribution, or unable to
load, the fail-closed result is `AMBIGUOUS` and current behavior continues.

## Future prototype gate

No production integration is allowed until a prototype passes all of the
following on DEV with source-group isolation:

1. Partition before cropping; no source group, page, physical stroke, repeated
   dimension chain, or overlapping crop may cross train/calibration/test.
2. Demonstrate structural-continuation precision strong enough for the asymmetric
   unsupported-geometry risk, with confidence intervals and an explicit abstention
   rate. Set the numeric operating point only after seeing sufficient held-out DEV
   counts.
3. Report the full three-class confusion matrix, calibration error/reliability,
   coverage-versus-risk curve, and hard dimension/text negative false-support rate.
4. Evaluate hard negatives from more than one held-out source group; same-source
   crop splits do not satisfy this gate.
5. Preserve `D2-005` exactly: no new bridge, duplicate CAD line, noise, ownership
   change, or FinalStructure change.
6. Show measurable improvement potential on `D2-006` by producing stable advisory
   structural evidence, while still requiring the ordinary source, damage,
   ownership, and FinalStructure checks before any geometry can survive.
7. Reject or abstain on blank-gap, parallel-rule, continuous double-rule,
   intentional-opening, target-mismatch, and glyph/dimension controls. No generic
   bridge behavior is permitted.
8. Demonstrate that no output creates unsupported geometry and that direct damage
   evidence remains a veto regardless of model confidence.
9. Replay identical inputs with identical model and preprocessing digests and
   obtain byte-stable evidence records and advisory states.
10. Audit every evaluated case through source region, prediction, consumer, and
    final fate in `SourceSupportLifecycle`, including all abstentions and failures.

The current inventory fails gates 1 and 4 for the hard-negative distinction, so
the prototype is not ready to build. The next work should be a DEV-only candidate
annotation/counting pass across additional source groups, not model training and
not a production semantic change.

---

STRUCTURAL_STROKE_PERCEPTION_D8:
COMPLETE

DIAGNOSTIC CHECKPOINT:
008ddaed2de1158ecb8da960cc7ec24b431e2b79

PRODUCTION_SEMANTIC_DELTA:
NONE

TASK DEFINITION:
Given an existing fragmented-line candidate pair and paired local/broader source views, selectively classify its context as structural continuation, annotation/glyph, or ambiguous advisory evidence.

LABEL SET:
STRUCTURAL_CONTINUATION, ANNOTATION_OR_GLYPH, AMBIGUOUS

MINIMUM INPUT:
Candidate-aligned local and 4x context crops, each with normalized source grayscale, unchanged binary support, and a categorical fragment/gap overlay.

BROADER CONTEXT REQUIRED:
YES

CURRENT DEV DATA SUFFICIENT FOR PROTOTYPE:
NO

ESTIMATED POSITIVE SAMPLE COUNT:
7 qualified fragmented candidates across 2 source groups

ESTIMATED HARD NEGATIVE COUNT:
4 dimension/text candidates from 1 source group

AMBIGUOUS SAMPLE COUNT:
1 explicitly source-ambiguous case (plus 11 semantically labeled cases ambiguous only to existing handcrafted evidence)

RECOMMENDED MODEL FAMILY:
Compact pretrained visual encoder with shared local/context weights and a shallow calibrated three-class fusion head, conditional on additional DEV labels

ADVISORY-ONLY INTEGRATION POINT:
Continuation-hypothesis evidence in SourceSupportLifecycle after detection/consolidation and before text filtering, with FinalStructure retaining sole geometry authority

CROSS-SOURCE SPLIT POSSIBLE:
NO

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
