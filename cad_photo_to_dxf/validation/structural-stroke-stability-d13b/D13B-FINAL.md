# Structural stroke stability retest D13B

## Governance and integrity

- Re-anchor verification: **PASS**. `4ad6a72d93d0e1631c2961e1c2ca79a47b0ae7d4` is an ancestor of authoritative D13A checkpoint `669e72ff0e7a4b04d3c60927039ff948a37aca5f`. The intervening commit adds only the D13A report and label registry.
- Production semantic delta: **NONE**.
- Committed D11+D13A registries reproduce exactly 18 `STRUCTURAL_CONTINUATION`, 10 `ANNOTATION_OR_GLYPH`, 1 `AMBIGUOUS`, and 7 `INVALID_FOR_TASK`, with unique candidate IDs.
- Fixed split: 18 TRAIN samples (13 structural, 5 annotation/glyph); 10 HELD OUT samples (5 structural, 5 annotation/glyph). The ambiguous case remained outside all fitting.
- No VALIDATION or LOCKED_BLIND data was inspected.

## Frozen representation

- Encoder: OpenCV Zoo MobileNetV2 `image_classification_mobilenetv2_2022apr.onnx`, OpenCV Zoo commit `47534e27c9851bb1128ccc0102f1145e27f23f98`.
- Model SHA256: `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5`.
- Runtime: OpenCV 4.14.0. Frozen layer `onnx_node!GlobalAveragePool_97`, 1,280 values per view and 2,560 concatenated local+context values.
- D12D preprocessing was retained exactly: OpenCV BGR decode; BGR-to-RGB; direct 256x256 `INTER_LINEAR` resize; `[16:240,16:240]` center crop; divide by 255; ImageNet mean/std normalization; HWC-to-NCHW; float32.
- D12D view extraction was retained exactly: local review-pair slice `[42:422,0:450]`, context slice `[42:422,450:900]`, followed by concatenation.
- Primary classifier: frozen cosine nearest class centroid. No feature, model, layer, crop, distance, or hyperparameter search was performed.
- As a reproduction check, the same runtime and D12D runner reproduced the recorded D12D results: fixed raw 6/6 and whole-source raw 17/20.

## Fixed held-out raw separation

Raw cosine classification, without abstention, was **7/10 correct**.

| Metric | Result |
|---|---:|
| Structural precision | 100.0% |
| Structural recall | 40.0% |
| Annotation/glyph recall | 100.0% |
| Dangerous false structural | 0 |

Confusion matrix (rows are truth, columns are prediction):

|  | Structural | Annotation/glyph |
|---|---:|---:|
| Structural | 2 | 3 |
| Annotation/glyph | 0 | 5 |

The expanded fixed split preserves perfect annotation safety in this sample, but structural recall falls sharply. Raw separation therefore persists but is not balanced or stable enough for a deployment claim.

## Leave-one-SOURCE_GROUP-out stability

| SOURCE_GROUP | N | S | A | Correct | S precision | S recall | A recall | Dangerous false S |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `G0R2-15EE2398726E8037` | 3 | 1 | 2 | 3/3 | 100.0% | 100.0% | 100.0% | 0 |
| `G0R2-3B970FD759C6026F` | 4 | 2 | 2 | 3/4 | 66.7% | 100.0% | 50.0% | 1 |
| `G0R2-4A34D1B8D93B1B06` | 4 | 3 | 1 | 4/4 | 100.0% | 100.0% | 100.0% | 0 |
| `G0R2-6C9464FA73A2A027` | 7 | 6 | 1 | 6/7 | 85.7% | 100.0% | 0.0% | 1 |
| `G0R2-7E30C7F445081F40` | 3 | 2 | 1 | 3/3 | 100.0% | 100.0% | 100.0% | 0 |
| `G0R2-C2D095E069663C17` | 7 | 4 | 3 | 4/7 | 66.7% | 50.0% | 66.7% | 1 |

Aggregate: **23/28 correct** (82.1%); structural precision 84.2%; structural recall 88.9%; annotation/glyph recall 70.0%; dangerous false structural 3.

Aggregate confusion matrix:

|  | Structural | Annotation/glyph |
|---|---:|---:|
| Structural | 16 | 2 |
| Annotation/glyph | 3 | 7 |

The signal survives all six folds and is materially safer than the structural-majority rule, which would create 10 dangerous false structural errors. It nevertheless remains source-sensitive: annotation recall ranges from 0% to 100%, and the two weakest folds contain a dangerous error each.

### Prior weak group

`G0R2-C2D095E069663C17` is **PARTIALLY_RECOVERED**: 4/7 correct versus D12D's 1/3, with 50.0% structural recall, 66.7% annotation recall, and one dangerous false structural. The larger frozen sample shows useful cases but not useful group-level separation overall.

## Training-only abstention attempt

The one predeclared method used internal leave-one-TRAIN-`SOURCE_GROUP`-out margins only. Its threshold rule was:

`max(minimum absolute margin among correct internal predictions, maximum structural-side margin among annotation cases, 0)`

The resulting frozen threshold was `0.06118963046827641`. It abstained on 8/10 external held-out cases. The two accepted cases were correctly predicted annotations; no structural case was accepted. The ambiguity reserve was also accepted as structural. This repeats the D12D failure mode of severe over-abstention without rejecting the ambiguous case.

Status: **ABSTENTION_NOT_CALIBRATABLE**. The threshold is recorded for reproducibility, not endorsed as calibrated.

## Ambiguity reserve sanity check

After classifier and threshold freezing, `D11-1F8BD71FD23F` was predicted `STRUCTURAL_CONTINUATION`: structural cosine `0.8188046763`, annotation cosine `0.7370830942`, margin `0.0817215821`, abstain **NO**. One ambiguous case does not validate calibration.

## D12D to D13B comparison

| Measure | D12D (20 qualified) | D13B (28 qualified) | Classification |
|---|---:|---:|---|
| Fixed held-out raw | 6/6 (100.0%) | 7/10 (70.0%) | DEGRADED |
| Whole-source raw | 17/20 (85.0%) | 23/28 (82.1%) | STABLE |
| Whole-source structural precision | 84.6% | 84.2% | STABLE |
| Whole-source structural recall | 91.7% | 88.9% | STABLE |
| Whole-source annotation recall | 75.0% | 70.0% | STABLE |
| Whole-source dangerous false structural | 2/8 annotations | 3/10 annotations | STABLE, CONCERNING |
| `G0R2-C2D095E069663C17` | 1/3 | 4/7, partially recovered | IMPROVED |
| Abstention | 6/6 abstained; ambiguity accepted | 8/10 abstained; ambiguity accepted | STABLE FAILURE MODE |

Small denominators do not support strong claims from the percentage changes. The expanded result preserves aggregate separation and five relatively useful folds, but the fixed held-out structural-recall drop, one weak group, zero annotation recall in another group, and 3/10 dangerous annotation errors demonstrate material source sensitivity.

## Verdict

**CROSS_SOURCE_SIGNAL_PROMISING_BUT_UNSTABLE**.

The exact frozen D12D representation continues to show useful cross-source signal after independent label expansion. It does not meet a stable, calibrated, or production-safe standard. More labeled DEV cases are justified before any model or calibration development. No new PDF acquisition is required now, and no production integration should begin.

READY FOR PRODUCTION INTEGRATION: **NO**.

VALIDATION: **NO**.

LOCKED_BLIND: **0 / 8**.
