# Structural stroke prototype D12D — final feasibility

## Encoder and feature provenance

- Encoder: OpenCV Zoo MobileNetV2 `image_classification_mobilenetv2_2022apr.onnx`
- OpenCV Zoo commit: `47534e27c9851bb1128ccc0102f1145e27f23f98`
- Source: `https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx`
- License: Apache-2.0
- SHA256: `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5`
- OpenCV import: PASS (`opencv-python-headless` 4.14.0; model was a real 13,964,571-byte ONNX file, not a Git LFS pointer)
- Frozen feature layer: `onnx_node!GlobalAveragePool_97`, shape `1 x 1280 x 1 x 1`
- Feature representation: 1,280-dimensional pooled embedding per view; 2,560-dimensional concatenated local-plus-context representation

No ONNX weights or runtime artifacts are tracked by this report.

## Results

- Fixed held-out raw cosine: 6 / 6 correct.
- Fixed held-out dangerous false structural: 0 / 4 negatives.
- Whole-`SOURCE_GROUP` folds: 17 / 20 correct.
- Whole-source structural precision: 84.6%.
- Whole-source structural recall: 91.7%.
- Whole-source dangerous false structural: 2.
- Useful source groups: 5 / 6.
- Weak fold: `G0R2-C2D095E069663C17`.

## Abstention and ambiguity reserve

Abstention was not calibrated. The attempted threshold rejected all six fixed
held-out samples despite the underlying raw cosine ranking being 6 / 6 correct,
while the single ambiguity-reserve case was not rejected and was assigned to a
supervised class. This is the opposite of useful selective behavior, so no
confidence or deployment claim is supported. The ambiguity-only source group
remains a diagnostic reserve and is not forced into either training class.

## Verdict

`CROSS_SOURCE_SIGNAL_DETECTED`.

The perception hypothesis is promising, but the labeled dataset is too small
for stable decision boundaries or confidence calibration. This is a diagnostic
prototype result only.

Production semantic delta: none.

VALIDATION: no.

LOCKED_BLIND: 0 / 8.
