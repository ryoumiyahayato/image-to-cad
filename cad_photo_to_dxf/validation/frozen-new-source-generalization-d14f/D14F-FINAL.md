# D14F frozen new-source generalization

## Outcome

`NEW_SOURCE_GENERALIZATION_SUPPORTED`.

The frozen cosine nearest-class-centroid representation correctly classified
10 of 13 genuinely new-source cases. It reduced the safety-critical
`ANNOTATION_OR_GLYPH -> STRUCTURAL_CONTINUATION` count from 6 for the declared
always-structural baseline to 1, while recovering 5 of 7 structural cases.
Useful class-directed signal survived in H1 and C1, and H2 retained signal but
was mixed because one of its three annotation cases was a dangerous false
structural. The result is not carried only by C1: both H1 and H2 were 3/4.

This is evidence of transfer, not a production performance estimate. There are
only 13 external cases, and H2 contains only one independent structural
positive. No statistical confidence claim is made.

## Fail-closed gates and frozen configuration

The starting worktree was clean at
`4920d12966b8a256678ed1d1f26bd880ec82e9e6` on
`codex/source-support-lifecycle-instrumentation`. The production baseline
remains `3ad0ec4` (`fix: protect credible structure from artifact propagation`).

Committed registries reproduced the required old reference population of 18
structural plus 10 annotation/glyph cases across exactly the six declared
source groups. They also reproduced the D14E test population exactly: H1=4,
H2=4, C1=5; 7 structural plus 6 annotation/glyph, 13 independent qualified
cases total. Candidate identities were unique and matched the frozen D14E set.

The encoder was the frozen OpenCV Zoo MobileNetV2 model
`image_classification_mobilenetv2_2022apr.onnx`, pinned upstream commit
`47534e27c9851bb1128ccc0102f1145e27f23f98`, SHA-256
`C0C3F76D93FA3FD6580652A45618618A220FCED18BABF65774ED169DE0432AD5`.
The verified feature layer was `onnx_node!GlobalAveragePool_97`, shape
1x1280x1x1. Local and context features were concatenated to 2560 dimensions.

Preprocessing was unchanged from D12D/D13B: OpenCV BGR decode, BGR-to-RGB,
direct 256x256 `INTER_LINEAR` resize, center crop `[16:240,16:240]`, division
by 255, ImageNet mean/std normalization, HWC-to-NCHW, and float32. Each
concatenated feature was L2-normalized; unit old-reference features were
averaged by class and each centroid was L2-normalized. All 28 old qualified
cases and no D14E case constructed the two centroids. No abstention, threshold,
calibration, ridge model, adaptation, or competing classifier was used.

## Per-case frozen predictions

The signed raw margin is structural cosine minus annotation cosine. Positive
means a raw structural prediction.

| Candidate | Family | Document/sheet | Human truth | Structural cosine | Annotation cosine | Margin | Raw prediction | Correct | Dangerous false structural |
|---|---|---|---|---:|---:|---:|---|---|---|
| D14E-B891230016C5 | H1 | H1-UT14 / sheet 1 | ANNOTATION_OR_GLYPH | 0.701262 | 0.759215 | -0.057952 | ANNOTATION_OR_GLYPH | YES | NO |
| D14E-F12FEFEB2245 | H1 | H1-NY4 / sheet 1 | ANNOTATION_OR_GLYPH | 0.649529 | 0.672744 | -0.023215 | ANNOTATION_OR_GLYPH | YES | NO |
| D14E-82AF53CB94E1 | H1 | H1-UT14 / sheet 3 | STRUCTURAL_CONTINUATION | 0.742728 | 0.745261 | -0.002533 | ANNOTATION_OR_GLYPH | NO | NO |
| D14E-4ECE70470938 | H1 | H1-NY4 / sheet 2 | STRUCTURAL_CONTINUATION | 0.679746 | 0.649676 | +0.030070 | STRUCTURAL_CONTINUATION | YES | NO |
| D14E-CE792322B81F | H2 | H2 / page 1 | ANNOTATION_OR_GLYPH | 0.682580 | 0.740622 | -0.058042 | ANNOTATION_OR_GLYPH | YES | NO |
| D14E-210F3F812A66 | H2 | H2 / page 3 | STRUCTURAL_CONTINUATION | 0.768834 | 0.750327 | +0.018506 | STRUCTURAL_CONTINUATION | YES | NO |
| D14E-142FAB52579F | H2 | H2 / page 3 | ANNOTATION_OR_GLYPH | 0.805288 | 0.766571 | +0.038717 | STRUCTURAL_CONTINUATION | NO | YES |
| D14E-E3358E708EA3 | H2 | H2 / page 1 | ANNOTATION_OR_GLYPH | 0.536609 | 0.617117 | -0.080509 | ANNOTATION_OR_GLYPH | YES | NO |
| D14E-FA2DB5B68BA2 | C1 | C1 / D.5 | STRUCTURAL_CONTINUATION | 0.800885 | 0.768141 | +0.032744 | STRUCTURAL_CONTINUATION | YES | NO |
| D14E-101604055F6C | C1 | C1 / D.6 | STRUCTURAL_CONTINUATION | 0.794403 | 0.801995 | -0.007592 | ANNOTATION_OR_GLYPH | NO | NO |
| D14E-502CA91496D5 | C1 | C1 / D.7 | STRUCTURAL_CONTINUATION | 0.737966 | 0.725870 | +0.012097 | STRUCTURAL_CONTINUATION | YES | NO |
| D14E-B93CCEEAA320 | C1 | C1 / D.8 | ANNOTATION_OR_GLYPH | 0.732683 | 0.810656 | -0.077973 | ANNOTATION_OR_GLYPH | YES | NO |
| D14E-97391B48B08C | C1 | C1 / D.9 | STRUCTURAL_CONTINUATION | 0.797388 | 0.777864 | +0.019523 | STRUCTURAL_CONTINUATION | YES | NO |

## Family results

Confusion matrices use rows as human truth and columns as raw prediction.

| Family | Correct | Matrix: S->S / S->A / A->S / A->A | Structural precision | Structural recall | Annotation recall | Dangerous A->S | Diagnostic verdict |
|---|---:|---|---:|---:|---:|---:|---|
| H1 historical | 3/4 | 1 / 1 / 0 / 2 | 100.0% | 50.0% | 100.0% | 0 | USEFUL_SEPARATION |
| H2 mechanical | 3/4 | 1 / 0 / 1 / 2 | 50.0% | 100.0% | 66.7% | 1 | MIXED |
| C1 civil | 4/5 | 3 / 1 / 0 / 1 | 100.0% | 75.0% | 100.0% | 0 | USEFUL_SEPARATION |
| **Aggregate** | **10/13** | **5 / 2 / 1 / 5** | **83.3%** | **71.4%** | **83.3%** | **1** | — |

H1 preserved useful separation under the historical raster/archival shift: both
layout-rule negatives were rejected and one of two structural positives was
recovered. The missed structural case prevents a stronger recall conclusion.

H2 preserved real but mixed signal under the mechanical PMI/GD&T shift: both
aligned-glyph negatives were rejected and the sole structural object edge was
recovered, but the dimension witness line became a dangerous false structural.
H2 contains only one independent structural positive, so its observed 100%
structural recall is not robust evidence of structural recall.

C1 preserved useful separation under the independent modern civil shift: its
only annotation case was rejected and three of four structural cases were
recovered. The single annotation sample limits the breadth of that safety
observation.

## Baseline and errors

Always predicting structural on the 13 cases gives 7/13 correct, 53.8%
structural precision, 100% structural recall, 0% annotation recall, and 6
dangerous false structural errors. The frozen classifier gives 10/13 correct,
83.3% structural precision, 71.4% structural recall, 83.3% annotation recall,
and 1 dangerous false structural. It therefore materially reduces the primary
safety error while retaining useful structural signal.

The single dangerous error is `D14E-142FAB52579F` (H2), subtype
`dimension_extension_witness_line`: structural cosine 0.805288, annotation
cosine 0.766571, margin +0.038717. Inspection was limited to its existing
D14E local/context/overlay artifacts. The long, clean, object-adjacent vertical
witness line dominates the crop and resembles a structural edge; dimension
arrows and PMI context are visible but did not outweigh that geometry in the
frozen representation. The human label is unchanged.

Missed recovery opportunities were:

- `D14E-82AF53CB94E1` (H1), structural cosine 0.742728, annotation cosine
  0.745261, margin -0.002533. The archival lower chord lies within dense truss,
  dimension, label, and frame context.
- `D14E-101604055F6C` (C1), structural cosine 0.794403, annotation cosine
  0.801995, margin -0.007592. The roadway edge crosses dense hatch, ticks,
  bearing text, and leader geometry.

Margins are diagnostic only. Neither miss was abstained, recalibrated, or used
to alter the model.

## D14A comparison and decision

D14A's `CLASS_VS_SOURCE_DOMINANCE: MIXED` concern is reduced, not eliminated.
Completely new historical, mechanical, and civil sources all preserved some
class-directed signal. H1 and C1 showed no annotation-to-structural error, and
H2 correctly separated three cases before failing on a domain-specific
dimension witness line. The cross-family 10/13 result and fivefold reduction in
dangerous errors are not attributable only to C1. At the same time, the H2
failure and two narrow-margin structural misses show residual sensitivity to
source style and drawing semantics.

The generic MobileNet direction is worth continuing into a larger,
multi-source DEV dataset. Domain-specific representation work is not justified
yet by this small baseline alone; it remains a later hypothesis if broader DEV
evidence reproduces the mechanical annotation failure. This conclusion does
not justify production integration.

## Governance

- Production semantic delta: none.
- New-source adaptation: none.
- Abstention: none.
- H1/H2 holdout status: preserved; neither enters future fitting or calibration
  absent an explicit redesign.
- C1 untouched baseline: recorded; no D14F fitting or calibration used it.
- Source documents, full pages, VALIDATION, and LOCKED_BLIND inspected: no.
- LOCKED_BLIND exposure: 0 / 8.
- New PDF acquisition: no.
- Ready for production integration: no.
- Next production change candidate: none.
