# Perception V2-A: multi-source DEV dataset protocol and acquisition plan

## Decision

This document freezes the planning protocol for one bounded, source-diverse
`STRUCTURAL-STROKE PERCEPTION V2` DEV dataset. It authorizes no acquisition,
rendering, labeling, inference, training, production integration, VALIDATION
use, or LOCKED_BLIND exposure. Acquisition may begin only in a separately
authorized `PERCEPTION-V2-B` task.

The dataset is development evidence for honest representation and decision
method comparisons. It is not intended to estimate final production accuracy.
The planned center is nine additional source families and 92 independent
qualified cases, inside the frozen target bounds of 8-10 families and 80-120
cases. The planned allocation is 44 structural and 48 annotation/glyph cases.
Counts are targets, not permission to manufacture balance or admit duplicates.

## Closed exploration and immutable baseline

D5-D14 exploration remains closed. This task does not reopen Hough/LSD root
cause diagnosis, handcrafted morphology, generic bridge/snap heuristics, or
D12-D14 MobileNet feasibility experiments.

`STRUCTURAL-STROKE REFERENCE BASELINE V1` is frozen exactly as follows:

| Component | Frozen value |
|---|---|
| Encoder | OpenCV Zoo MobileNetV2 `image_classification_mobilenetv2_2022apr.onnx` |
| Upstream commit | `47534e27c9851bb1128ccc0102f1145e27f23f98` |
| SHA-256 | `C0C3F76D93FA3FD6580652A45618618A220FCED18BABF65774ED169DE0432AD5` |
| Feature layer | `onnx_node!GlobalAveragePool_97` |
| Feature | 1,280 local + 1,280 context = 2,560 concatenated |
| Classifier | cosine nearest class centroid |
| Abstention | `NONE` |
| New-source reference result | 10/13; one dangerous false structural among six annotation cases |

V1 is not modified or rerun in V2-A. Every later V2 experiment must explicitly
declare deviations in encoder, layer, preprocessing, crop, normalization,
feature construction, classifier, fitting data, calibration, or rejection.

## Dataset units

`SOURCE_FAMILY` is a materially independent combination of organization or
publisher or drafting vendor, discipline, drafting convention, visual
generation process, vector/raster/scan origin, typography, dimensioning style,
line-weight hierarchy, title/revision/layout convention, and degradation
characteristics. Different filenames or projects alone do not create families.
Multiple documents may belong to one family.

`DOCUMENT` is one acquired drawing file, or one inseparable drawing set with a
single document identity, whose source and rights provenance are recorded.

`CANDIDATE` is one uniquely identified proposed continuation ambiguity. A
diagnostic, non-learned mechanism may propose it; proposal does not establish
its semantic label.

`INDEPENDENT QUALIFIED CASE` is a human-reviewed, task-valid candidate whose
evidence supports a qualified label and whose `INDEPENDENCE_CLUSTER_ID` is not
already counted. `AMBIGUOUS` cases are valid qualified material for review and
uncertainty analysis but do not contribute to either class floor.

## Independence and count accounting

Every candidate must have an `INDEPENDENCE_CLUSTER_ID`. The same cluster must
cover candidates that are merely another gap on the same physical line,
another segment of the same dimension chain, another copy of one title border,
another repeated grid line, another duplicate symbol/detail, another sheet
from a near-identical repeated template, or another rendering of one original.
Only one qualified member of such a cluster may contribute to the headline
independent count.

Every family and aggregate report must separately track:

- `RAW_CANDIDATES`
- `HUMAN_REVIEWED`
- `QUALIFIED`
- `INDEPENDENT_QUALIFIED`
- `NEAR_DUPLICATE_EXCLUDED`

Only `INDEPENDENT_QUALIFIED` counts toward 80-120. Excluded candidates retain
their cluster relationship for audit. No quota may be filled with
near-duplicates. A single family may not exceed 20% of the frozen independent
qualified corpus; at the minimum total of 80 this is at most 16 cases.

Family admission requires at least two meaningful independence axes. At least
one must be drafting convention, document generation process, scan/raster
degradation, typography/layout system, dimensioning convention, line-weight
convention, or organization/vendor template. Discipline alone is insufficient.
A civil document visually duplicating C1 does not become useful merely because
it comes from a new project.

## Frozen labels

| Label | Definition |
|---|---|
| `STRUCTURAL_CONTINUATION` | A competent human can establish from source and context that detector fragments belong to one genuine engineering structural/object/profile stroke. |
| `ANNOTATION_OR_GLYPH` | The apparent continuation belongs to annotation-derived content. |
| `AMBIGUOUS` | Existing source/context evidence is insufficient to decide safely. |
| `INVALID_FOR_TASK` | The candidate does not actually test the target continuation ambiguity. |

Ambiguous cases must not be relabeled to force balance. `INVALID_FOR_TASK` is
accounted for as human-reviewed but is not qualified.

## Frozen hard-negative taxonomy

The initial annotation/glyph taxonomy is:

1. `dimension_extension_witness_line`
2. `dimension_chain`
3. `leader_marker`
4. `drawing_layout_rule`
5. `aligned_text_glyph_stroke`
6. `table_legend_revision_title_rule`

`OTHER_LINE_DOMINANT_ANNOTATION` may be used only when a genuinely new,
reusable subtype is discovered and its rationale is recorded. It must not
silently become a collection of one-off labels.

For every subtype, record independent case count, source-family count,
discipline coverage, and—in later evaluation—dangerous false structural count.
The four priority subtypes are witness/extension lines, dimension chains,
leaders, and drawing-layout rules. Each should aim for at least five independent
cases spanning at least two source families. These are development targets, not
scientifically certified statistical requirements.

## Source-family planning matrix

The slots below identify missing diversity rather than real documents. No
source search or assignment occurred in V2-A.

| Slot | Priority | Discipline | Target style / generation difference | Why needed | Structural | Annotation | Priority hard negatives | Documents | Independent qualified | Intended role | Preferred rights |
|---|---|---|---|---|---:|---:|---|---:|---:|---|---|
| `SF-V2-01` | P0 | Dense mechanical fabrication / assembly / PMI | Clean vector, independent vendor, dense GD&T/PMI, compact typography, strong line hierarchy | Exercise known witness-line risk independently of H2 | 6 | 6 | witness, dimension chain, leader | 2 | 12 | `TRAIN_POOL` | PD, CC0, CC BY, permission |
| `SF-V2-02` | P0 | Architectural / building | CAD/BIM vector, wall hierarchy, ticks, grids, leaders, distinct office template | Add building conventions unlike current families | 5 | 5 | witness, dimension chain, layout rule | 2 | 10 | `DEV_COMPARISON` | PD, CC0, CC BY, permission |
| `SF-V2-03` | P0 | Electrical installation / power layout | Vector/mixed plans with conductors/trays, callouts, leaders, distinct typography | Separate installation geometry from line-dominant annotation | 4 | 6 | leader, glyph stroke, layout rule | 2 | 10 | `TRAIN_POOL` | PD, CC0, CC BY, permission |
| `SF-V2-04` | P1 | Electrical control / schematic | Digitally generated symbol/connection-dense schematic with cross-references and tables | Challenge glyph/connection confusion | 4 | 6 | layout rule, glyph stroke, table/title rule | 2 | 10 | `TRAIN_POOL` | PD, CC0, CC BY, permission |
| `SF-V2-05` | P0 | Civil / site / profile | Independent template, stationing, dimensions, and line hierarchy unlike C1 | Add real civil diversity rather than C1 duplication | 6 | 4 | witness, dimension chain, leader | 2 | 10 | `INTERNAL_HOLDOUT_CANDIDATE` | PD, CC0, CC BY, permission |
| `SF-V2-06` | P1 | P&ID / process / instrumentation | Rights-compatible vector/high-quality raster with process lines, tags, leaders, legends | Add process semantics and tag/leader negatives | 4 | 6 | leader, glyph stroke, table/title rule | 2 | 10 | `TRAIN_POOL` | PD, CC0, CC BY, permission |
| `SF-V2-07` | P1 | Historical engineering, distinct from H1 | Different organization, reproduction lineage, lettering, object type, and archival degradation | Test degradation transfer without reusing H1 | 6 | 4 | layout rule, dimension chain, table/title rule | 2 | 10 | `INTERNAL_HOLDOUT_CANDIDATE` | PD, CC0, CC BY, permission |
| `SF-V2-08` | P0 | Modern engineering; discipline selected to fill admitted gaps | Real scan/photocopy with skew, contrast loss, compression/noise; not a derived version of another admitted original | Isolate modern reproduction degradation | 5 | 5 | witness, dimension chain, layout rule | 2 | 10 | `DEV_COMPARISON` | PD, CC0, CC BY, permission |
| `SF-V2-09` | P1 | Table/legend/revision-heavy multidisciplinary set | Clean vector, schedule/title/revision-heavy, independent template and typography | Systematically cover layout and table rules | 4 | 6 | layout rule, table/title rule, glyph stroke | 2 | 10 | `TRAIN_POOL` | PD, CC0, CC BY, permission |

Each row has at least two meaningful independence axes, detailed in
`source-family-plan.json`. Actual admission must verify them rather than assume
the slot description proves independence. P&ID is optional if no rights-safe
source fits; a substitute must close comparable missing visual and annotation
diversity and preserve the overall gates.

Where naturally available, each family targets at least three independent
cases of each main class. A valuable family that naturally supplies one class
well may remain if the limitation is recorded, aggregate and cross-family class
coverage remain adequate, and no balance is manufactured.

## Bounded acquisition plan

The normal first-iteration budget is 18-24 documents, with a hard maximum of
24 and a per-family cap of three. Prefer one to three useful documents per
family; the matrix plans two per family. Reaching a cap does not authorize
weak, duplicative, or rights-uncertain material. Stop acquiring within a family
as soon as it supplies sufficient independent visual and subtype diversity.
Stop the entire acquisition early if all dataset success criteria are met
before 120 cases. Do not collect toward the maximum for its own sake.

## Source-evidence provenance

Every acquired document requires a machine-readable record conforming to
`provenance-schema.json`, including:

- `SOURCE_FAMILY_ID`, `DOCUMENT_ID`, title, publisher/organization, drafting
  vendor if known, discipline, and era/date;
- landing-page URL, final binary URL, access timestamp, original filename,
  MIME type, byte size, and SHA-256;
- page/sheet count and identifiers, vector/raster/mixed classification, and
  generation process;
- duplicate, mirror, same-original, derived-render, and related-template
  relationships;
- a style-independence rationale and at least two enumerated independence axes;
- ordered render transformation history with tools, parameters, and input and
  output hashes;
- candidate ID, page/sheet ID, crop coordinates and coordinate space,
  `INDEPENDENCE_CLUSTER_ID`, proposal mechanisms, and review artifact paths.

This evidence record does not constitute rights approval.

## Data-rights provenance and gate

Every document separately requires a record conforming to
`rights-schema.json`: copyright owner, publisher, license/status, license URL,
public-domain basis when applicable, commercial-use status, raw retention,
derived crop retention, label retention, ML training/evaluation status,
redistribution, attribution and share-alike obligations, reviewer, review date,
evidence/restrictions, and disposition.

Allowed dispositions are `PUBLIC_DOMAIN`, `CC0`, `CC_BY`,
`EXPLICIT_PERMISSION`, `RIGHTS_REVIEW_REQUIRED`, and `REJECTED`. The preferred
usable dispositions are the first four. Public downloadability is not rights
approval. `RIGHTS_REVIEW_REQUIRED` material is quarantined and may not enter
labeling, model development, or a retained derived-crop dataset until resolved.
`REJECTED` material is not admitted.

## Candidate proposal and prediction-blind labeling

Diagnostic non-learned mechanisms such as Hough/LSD gaps, collinearity,
source/binary support, geometric context, and already-available text/dimension
proximity may propose candidates. They may not assign semantic labels. Dataset
generation must not redesign production `detect_lines`.

The mandatory order for the first-pass labels of every family is:

1. Acquire and rights-admit source.
2. Select pages.
3. Generate candidate proposals.
4. Freeze candidate IDs.
5. Generate review crops.
6. Human-label prediction-blind.
7. Freeze the human registry.
8. Only then allow model evaluation.

Reviewers must not see V1 predictions, model scores, embedding distances,
margins, uncertainty, or model-error rankings. Each routine review case has a
local source crop, broader context crop, and fragment/gap overlay. A
source-support/binary overlay is optional only when genuinely needed. Full PDFs
need not be reopened routinely. Insufficient context yields `AMBIGUOUS`.

Label-quality review must verify label definitions, evidence sufficiency,
candidate identity, cluster assignment, and subtype consistency. Any unresolved
material disagreement or insufficient evidence triggers
`LABEL_QUALITY_INSUFFICIENT`; counts must not override it.

## Split and holdout governance

All splitting occurs at `SOURCE_FAMILY`, never crop or document level. Related
documents from one template/vendor stay in one family. No family may cross fit
and held-out evaluation.

Of the nine planned new families, seven are intended for model development
(five `TRAIN_POOL` and two `DEV_COMPARISON`) and at least two genuinely
independent families are reserved as `INTERNAL_HOLDOUT_CANDIDATE`. The final
family assignments are frozen only after admission and before model work; slot
roles state intent without claiming actual sources already exist.

H1 historical and H2 mechanical remain permanent reference holdouts. Their
D14F measurements are permanent reference measurements. H1/H2 must never be
used for fitting, classifier or representation selection, calibration,
thresholding, uncertainty development, or hyperparameter tuning.

VALIDATION is not used. LOCKED_BLIND remains `0 / 8` runtime exposure and has
not been manually inspected. No future V2 source family is allocated to either.

### C1 recommendation

Recommendation: `ELIGIBLE_FOR_LATER_DEV_ADAPTATION`.

C1's untouched baseline is already durably recorded, and its mixed/vector civil
style can provide useful adaptation evidence after the new-source protocol is
in operation. This recommendation does not move C1, authorize fitting with it,
or alter its current governance. A separate explicit governance-change task
must assess family leakage, document the exact new role, and freeze the change
before C1 enters DEV adaptation.

## Dataset freeze and model comparison

No model comparison begins until document admission, candidate IDs, labels,
independence clusters, exclusions, provenance, rights, and whole-family splits
are frozen. Later comparisons may include V1, a stronger pretrained encoder, a
learned lightweight classifier, a small domain-adapted representation,
explicit text/dimension context evidence, hybrid visual/context evidence, and
later domain-knowledge evidence. No winner is preselected. Every candidate is
reported against exactly the same source-family splits.

`COSINE_MARGIN_NOT_VALID_UNCERTAINTY_PROXY` is the governing uncertainty
result. Uncertainty/rejection is a separate track from raw classification; one
hand-tuned cosine threshold is not a V2 plan. A future rejection strategy must
report accepted structural precision and recall, dangerous false structural
count, annotation recall, abstention/rejection rate, per-family behavior, and
ambiguous-case behavior.

## Dataset construction stop rule

Construction stops only when all of the following are true:

- 8-10 independent source families, or a documented equivalent diversity;
- 80-120 independent qualified cases;
- at least 35 `STRUCTURAL_CONTINUATION` and 35 `ANNOTATION_OR_GLYPH`;
- both main classes represented broadly across families without manufactured
  per-family balance;
- at least six hard-negative subtypes;
- each priority subtype has multi-family coverage and aims for at least five
  independent cases across at least two families;
- no family exceeds 20% of independent qualified cases;
- rights and source provenance are complete;
- near-duplicate and cluster accounting are complete;
- the prediction-blind human registry is frozen; and
- at least two internal new-family holdouts remain preserved.

If these are all satisfied before 120 cases, stop early.

## Explicit shortfall states

The acceptable fail-closed outcomes are:

- `INSUFFICIENT_SOURCE_DIVERSITY`
- `HARD_NEGATIVE_COVERAGE_GAP`
- `RIGHTS_BLOCKED`
- `CLASS_COVERAGE_GAP`
- `NEAR_DUPLICATE_DOMINANCE`
- `SOURCE_FAMILY_LEAKAGE_RISK`
- `PROVENANCE_INCOMPLETE`
- `LABEL_QUALITY_INSUFFICIENT`

Do not lower admission, independence, rights, or label standards to hit counts.

## Knowledge and eventual production boundaries

No knowledge pack is built in V2-A. General perception asks, “What does the
visual evidence resemble?” Domain knowledge asks, “What does that evidence
mean in this discipline?” Knowledge may contribute evidence, reject or qualify
hypotheses, or raise human review. It must not manufacture unsupported geometry,
bypass source support, or directly mutate `FinalStructure`.

The eventual architecture remains documentation only:

```text
source evidence
  -> detector fragments
  -> continuation hypothesis
  -> visual semantic evidence
  -> optional domain evidence
  -> evidence arbitration
  -> ACCEPT / REJECT / AMBIGUOUS
  -> source-supported accepted result
  -> normal reconstruction
  -> FinalStructure
```

`FinalStructure` remains sole authority. Perception remains advisory evidence.
No production code, detector, Hough/LSD, consolidation, ownership, fallback,
artifact suppression, `SourceSupportLifecycle`, `FinalStructure`, CAD, GUI,
MobileNet integration, model dependency, or production behavior is changed.

## V2-A disposition

The DEV dataset protocol, family-slot plan, source provenance schema, and
rights schema are frozen and ready to govern a separately authorized V2-B
acquisition. V2-A acquired no sources and ran no model. It is not ready for a
model bake-off or production integration.
