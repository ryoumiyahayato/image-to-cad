# PRIMITIVE AXIS SUPPORT INTEGRITY V1 — FINAL

BASE CHECKPOINT: `eda4432663b47a50207cea7c12e43d9076e83682`

## 1. Human observation

The completed Batch-02 export contains human diagnostic judgments and optional notes. They were preserved byte-for-byte as input and were not treated as root-cause truth or runtime rules. The observation under investigation was that a thin hollow/double-edge structure can be represented by a synthetic line through its white center, and that other long primitives may cross separate or locally non-straight structures.

BATCH02 REVIEW EXPORT SHA-256: `d00d7d7f2738fea4adb87c604962b399c5db156d4e57269c4b573dec25c8c75a`

HUMAN LABELS MODIFIED: NO

## 2. Measured raster evidence

The previous span gate samples a blurred Otsu mask inside a scale-aware corridor. Its `centerline_supported_fraction` is diagnostic only; decisions are driven by nearby corridor support. In the confirmed family, blur/corridor tolerance bridges the narrow white center. Raw grayscale/Otsu sampling on the exact Hough trajectory instead shows low on-axis ink together with persistent, approximately symmetric ink flanks.

Reviewed cases: 24 across 10 source families. Symmetric-flank/center-void candidate decisions: 1. Human-rejected members of that measured family: 1. Fresh human-direct controls preserved: 9 / 9; human-not-direct cases filtered as rejected or uncertain: 7 / 15.

The runtime `axis-flank-profiles.json` records every raw ancestor's endpoints, length, orientation, Hough provenance, raw on-axis support, broad support, left/right flank support, center-to-flank contrast, continuity runs, and unsupported-axis intervals. The evidence contact sheet and cross-section plot are deliberately capped at six representative cases.

## 3. Inferred root cause

The DEV Local-D detector thresholds a 3×3-blurred source before Hough detection, and the span qualifier accepts support anywhere in a corridor sized from the estimated stroke width. For narrow hollow structures, both operations can make flanking boundaries appear to support the synthetic center trajectory. This is a geometric evidence conflation: BROAD_CORRIDOR_SUPPORT was not separated from ON_AXIS_DIRECT_SUPPORT and persistent paired FLANK_SUPPORT.

This inference is limited to the measured DEV path. Production uses a separate resolution-scaled Hough/LSD reconstruction and dilated support checks; exact production equivalence was not demonstrated.

PRODUCTION_AXIS_SUPPORT_EQUIVALENCE: UNPROVEN

## 4. Implemented safeguard

`primitive_axis_support_integrity.py` builds a deterministic raw-raster profile over the complete primitive span. It separates exact raw on-axis ink, paired left/right flanks, and the existing blur-tolerant broad corridor. A primitive is rejected for `SYMMETRIC_FLANK_WITH_CENTER_VOID` only when the center void and both flanks persist over most of the span, broad support remains high, raw axis support remains low, and the flanks are darker than the center. A Hough trajectory that lies on either of two real nearby engineering edges retains high direct-axis support and is preserved.

The guard is composed after span integrity. Either guard can reject or make a primitive uncertain; neither can upgrade the other. Only jointly supported records remain eligible for ordinary future DEV continuation mining. Geometry, endpoints, split points, production reconstruction, ownership/fallback, source-support lifecycle, and artifact suppression are unchanged.

No candidate ID, filename, source family, semantic class, OCR, model output, or human label participates in runtime classification.

## Fresh reviewed-case re-evaluation

| Review | Candidate | Human direct decision | Human role | Reviewer note | Original primitive | Axis status | Axis profile (direct min/median; broad min; symmetric void max) | Flank profile (left/right min) | Guard reason | Downstream changed |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | `FRESH1-2329D538A065BFC7E0D8` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.057/0.083 | DIRECT_AXIS_SUPPORT | NO |
| 2 | `FRESH1-460EC32409A8589C1D04` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_REJECTED | 0.025/0.025; 1.000; 0.966 | 0.990/0.750 | SYMMETRIC_FLANK_WITH_CENTER_VOID | YES |
| 3 | `FRESH1-2FF08EDFC754E290D7A4` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 我注明一下这个地方它不能识别成一条线因为这个应该是这个纸张扫描时候带来的这个痕迹是这个纸的边缘 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.594/0.731; 1.000; 0.000 | 0.156/0.328 | POSSIBLE_PATTERNED_AXIS_SUPPORT | YES |
| 4 | `FRESH1-24BCF545F595AC67795A` | DIRECT_STRAIGHT_CONTINUATION | OBJECT_GEOMETRY | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.000/0.455 | DIRECT_AXIS_SUPPORT | NO |
| 5 | `FRESH1-25AEF7268BE5D867D9D9` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.065/0.219 | DIRECT_AXIS_SUPPORT | NO |
| 6 | `FRESH1-2BF547C27C8497056BA6` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.837/0.897; 1.000; 0.140 | 0.465/0.029 | NOISY_OR_DEGRADED_AXIS_SUPPORT | YES |
| 7 | `FRESH1-3896FDF95885929AF0BE` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.703/0.768; 0.958; 0.270 | 1.000/0.917 | POSSIBLE_PATTERNED_AXIS_SUPPORT | YES |
| 8 | `FRESH1-3CF03111AF3D7D733A74` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.000/1.000 | DIRECT_AXIS_SUPPORT | NO |
| 9 | `FRESH1-48FEEEE4479EF194E24A` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.882/0.941; 1.000; 0.053 | 0.545/0.091 | DIRECT_AXIS_SUPPORT | NO |
| 10 | `FRESH1-7ABB59DA99C32EC5A90A` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 虚线 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.886/0.886; 1.000; 0.000 | 0.068/0.068 | DIRECT_AXIS_SUPPORT | NO |
| 11 | `FRESH1-2DBF66108AA424A95F6E` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.941/0.971; 1.000; 0.059 | 0.471/1.000 | DIRECT_AXIS_SUPPORT | NO |
| 12 | `FRESH1-392CD01D96A8D10C5946` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 这个两个识别的线段中间还有就是相当于本身所处的位置中有一些间断这两个并不应该放在同一个线上 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 1.000/0.571 | DIRECT_AXIS_SUPPORT | NO |
| 13 | `FRESH1-3025B9264AEDC21BE849` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 这是两个表格中的不能放在一块 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.568/0.289 | DIRECT_AXIS_SUPPORT | NO |
| 14 | `FRESH1-33163D6DB78308987FD9` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | 非常标准的图片的边线因为这个纸张的post而导致了一些的识别问题而且你还能够看到就这个蓝线旁边的这个还有一条黑线实际上也因为这个破损导致了它没有办法把它识别成调完整的直线 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.951/0.972; 0.961; 0.000 | 0.883/0.000 | DIRECT_AXIS_SUPPORT | NO |
| 15 | `FRESH1-49234CBA9EF19ACA2B93` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 这个错误太明显了我就不吸收了这个很明显是两个logo中间的空缺它识别成了这地方可以补齐 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.000/0.000 | DIRECT_AXIS_SUPPORT | NO |
| 16 | `FRESH1-859781346221E86E039A` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 文字 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.533/0.567; 0.933; 0.100 | 0.900/0.600 | POSSIBLE_PATTERNED_AXIS_SUPPORT | YES |
| 17 | `FRESH1-25E38770B7F837BE0915` | DIRECT_STRAIGHT_CONTINUATION | OBJECT_GEOMETRY | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.140/0.605 | DIRECT_AXIS_SUPPORT | NO |
| 18 | `FRESH1-2B13FEF419461264C185` | DIRECT_STRAIGHT_CONTINUATION | ANNOTATION_LAYOUT | 我必须说明一下他这边的这个蓝线的识别把线段延伸到了旁边这个标点符号的1上这个是有很明显的这个识别上的错误和问题的 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.925/0.943; 0.981; 0.038 | 0.868/0.264 | DIRECT_AXIS_SUPPORT | NO |
| 19 | `FRESH1-316D125FE4861584BE02` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 显而易见的问题把多尖段的线段识别成了一条完整的直线这个也是绘图中最容易出现的一个问题也是现在必须得解决的一个问题之一现在的话呢训练一下也差不多了 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.955/0.968; 0.981; 0.030 | 0.821/0.776 | DIRECT_AXIS_SUPPORT | NO |
| 20 | `FRESH1-32A5E8ACFF9E3D6BF8E7` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 这两个线不相干中间的加了一个零件它们两个不应该连在一块 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.600/0.800; 1.000; 0.400 | 0.008/0.008 | NOISY_OR_DEGRADED_AXIS_SUPPORT | YES |
| 21 | `FRESH1-403904F4EF20126F9D7D` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | 经典案例折线之间有这个符号F | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 1.000/1.000; 1.000; 0.000 | 0.500/0.724 | DIRECT_AXIS_SUPPORT | NO |
| 22 | `FRESH1-41E989458A189A3DADA3` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.903/0.952; 1.000; 0.097 | 0.244/0.890 | DIRECT_AXIS_SUPPORT | NO |
| 23 | `FRESH1-43C5461340B4AE31E3E7` | NOT_DIRECT_STRAIGHT_CONTINUATION | — | — | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_UNCERTAIN | 0.750/0.779; 0.958; 0.083 | 0.692/0.875 | POSSIBLE_PATTERNED_AXIS_SUPPORT | YES |
| 24 | `FRESH1-4497ADEE7DB5D798A893` | DIRECT_STRAIGHT_CONTINUATION | OBJECT_GEOMETRY | 还是比较经典的案例但是呢我必须得说它底下这个什么呃选项这个玩意儿它容易遮挡那个备注在最后说明一下马上可能到时候还要把这个呃对应审计的这个内容给调整修改一下 | SPAN_INTEGRITY_SUPPORTED | PRIMITIVE_AXIS_SUPPORTED | 0.942/0.962; 0.975; 0.033 | 0.433/0.325 | DIRECT_AXIS_SUPPORT | NO |

## Generic controlled patterns and compatibility

The focused synthetic suite covers: solid stroke; blurred stroke; noisy/scanned stroke; thin hollow rectangle/double-edge band; two parallel lines with the proposed axis between them; narrow hollow box in the orthogonal orientation; dashed/patterned stroke; perpendicular crossing; nearby text; small collinear degradation; intentional gap; skew/anti-aliasing; two nearby engineering edges with the proposed axis on one real edge; and a wide thick stroke. Horizontal and vertical hollow/solid cases are included.

Previous frozen-24 span guard safe: YES. Previous RAW_HOUGH_OVERSPAN detections: 3 / 3. Previous pairing/admissibility rejections preserved: 13 / 13.

Valid direct object controls supported by the new axis guard: 1 / 1. Valid annotation controls supported: 6 / 6.

## 5. Remaining uncertainty

Human NOT_DIRECT decisions include multiple causal families; an axis guard is not expected to resolve semantic pairing errors, table-to-table gaps, logos, text, fan/door symbols, or all curved/intermediate structures. `PRIMITIVE_AXIS_UNCERTAIN` intentionally blocks ordinary DEV promotion without asserting a semantic cause. The thresholds remain conservative and should be rechecked if source resolution or detector rasterization changes materially.

Production-axis equivalence remains unproven because this task did not route the reviewed raw ancestors through the production detector. No production change was made.

## Verification and governance

AXIS_SUPPORT_FIX: SAFE

TESTS: 121 passed, 48 warnings; focused axis/span/admissibility/review-accumulation/fresh-remine/source-support/line-integrity/reconstruction suite. Ruff focused checks passed. Compileall passed.

- PRODUCTION_SEMANTIC_DELTA: NONE
- CANDIDATE_SPECIFIC_EXCEPTIONS: NO
- MODEL_RUN: NO
- MODEL_ASSISTED_LABELING: NO
- NEW_CANDIDATE_MINING: NO
- VALIDATION: NO
- LOCKED_BLIND: 0 / 8
- H1/H2_OPENED: NO
- Runtime source-derived evidence is Git-ignored.

NEXT TARGET: REVIEW_AXIS_UNCERTAIN_FAMILIES_WITHOUT_WEAKENING_THE_GUARD
