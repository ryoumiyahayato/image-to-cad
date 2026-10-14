# Structural stroke representation audit D14A

## Scope and integrity

- Base checkpoint: `7e63888902643d8a355e7354b2509a0d66d68452`; branch and worktree verification passed.
- Dataset remained frozen at 28 qualified cases: 18 `STRUCTURAL_CONTINUATION`, 10 `ANNOTATION_OR_GLYPH`, across six mixed-class `SOURCE_GROUP`s. The one ambiguous reserve remained outside fitting.
- The audit re-extracted features only from the 29 existing review pairs through the committed D13B runner. It reused the frozen OpenCV Zoo MobileNetV2 model, `onnx_node!GlobalAveragePool_97`, exact D12D preprocessing and crop slices, and L2-normalized 2,560-dimensional local+context vectors.
- No labels, classifier, threshold, feature, crop, model, PDFs, production code, VALIDATION, or LOCKED_BLIND data were changed or inspected.
- Production semantic delta: **NONE**.

## A. Class separation versus source separation

Cosine distance is `1 - cosine similarity`; smaller values indicate greater similarity.

| Quantity | N | Min | Median | Max |
|---|---:|---:|---:|---:|
| Distance to own structural centroid | 18 | 0.0845 | 0.1157 | 0.1985 |
| Distance to own annotation centroid | 10 | 0.0692 | 0.1183 | 0.2295 |
| Distance to own source-group centroid, pooled | 28 | 0.0439 | 0.0954 | 0.2235 |
| Between source-group centroids | 15 pairs | 0.0580 | 0.0900 | 0.1432 |
| Same class, different source | 167 pairs | 0.1176 | 0.2418 | 0.4678 |
| Different class, same source | 29 pairs | 0.1585 | 0.2647 | 0.4768 |

The global class-centroid distance is only **0.0659**, below the median within-class dispersions (0.1157 and 0.1183). The median between-source centroid distance is **0.0900**, and pooled within-source dispersion (0.0954) is tighter than either within-class median. Source style is therefore at least comparable to class structure at the centroid level.

Class information has not disappeared: different-class/same-source pairs are modestly farther apart at the median than same-class/different-source pairs (0.2647 versus 0.2418). Their broad ranges overlap heavily, however. `CLASS_VS_SOURCE_DOMINANCE` is therefore **MIXED**, not reducible to one magic score.

## B. Cross-source class consistency

Distances below compare each group-class centroid with class centroids formed from the other five sources, so the evaluated source does not contribute to its own reference.

| SOURCE_GROUP | Within-group S/A centroid distance | S→other S | S→other A | A→other A | A→other S |
|---|---:|---:|---:|---:|---:|
| `G0R2-15EE2398726E8037` | 0.2014 | 0.1087 | 0.1099 | 0.1125 | 0.1747 |
| `G0R2-3B970FD759C6026F` | 0.2115 | 0.0865 | 0.1683 | 0.1053 | 0.1288 |
| `G0R2-4A34D1B8D93B1B06` | 0.1672 | 0.0563 | 0.0825 | 0.1494 | 0.1702 |
| `G0R2-6C9464FA73A2A027` | 0.2051 | 0.0508 | 0.1276 | **0.2829** | **0.2190** |
| `G0R2-7E30C7F445081F40` | 0.2154 | 0.0689 | 0.1143 | 0.1082 | 0.1603 |
| `G0R2-C2D095E069663C17` | **0.1198** | 0.0878 | 0.0977 | 0.0630 | 0.1034 |

Five sources' class centroids remain closer to the matching class across other sources. The exception is the sole `G0R2-6C9464FA73A2A027` annotation: it is closer to other-source structural (0.2190) than other-source annotation (0.2829). `G0R2-15EE2398726E8037` structural is nearly equidistant but was classified correctly by a margin of only 0.0012.

`G0R2-C2D095E069663C17` has by far the smallest internal class-centroid distance (0.1198 versus 0.1672–0.2154 elsewhere). Its structural centroid is only narrowly closer to other structural than other annotation (0.0878 versus 0.0977), while its annotation centroid is consistent with other annotations. The weakness is concentrated in structural variation and local class overlap, not wholesale displacement of the entire source.

## C. Leave-one-group centroid shifts

| Excluded SOURCE_GROUP | Structural centroid shift | Annotation centroid shift | Fold errors |
|---|---:|---:|---:|
| `G0R2-15EE2398726E8037` | 0.0004 | 0.0050 | 0 |
| `G0R2-3B970FD759C6026F` | 0.0012 | 0.0042 | 1 |
| `G0R2-4A34D1B8D93B1B06` | 0.0017 | 0.0018 | 0 |
| `G0R2-6C9464FA73A2A027` | 0.0059 | 0.0032 | 1 |
| `G0R2-7E30C7F445081F40` | 0.0009 | 0.0013 | 0 |
| `G0R2-C2D095E069663C17` | 0.0044 | 0.0064 | 3 |

The largest movements coincide with the two sensitive folds, but all shifts are small relative to the 0.0659 class-centroid distance. Excluding a source moves neither global prototype enough to explain the error pattern alone. `CENTROID_SHIFT_SENSITIVITY` is **LOW**; fold sensitivity mainly arises because several samples already sit in the overlapping boundary region.

## D. Five-error audit

Distances to own/opposite centroids use the global class centroids only for diagnosis; predictions and margins are the exact leakage-free D13B whole-source results.

| Candidate | SOURCE_GROUP | Truth → prediction | Dangerous | S cosine | A cosine | Margin | Own/opposite distance | Nearest same class | Nearest opposite class | Category |
|---|---|---|---|---:|---:|---:|---|---|---|---|
| `D11-56D479381BC0` | `G0R2-3B970FD759C6026F` | A → S | YES | 0.8915 | 0.8615 | +0.0300 | 0.1174 / 0.1089 | `C2D0` (0.1786) | `4A34` (0.1258) | `CLASS_OVERLAP` |
| `D11-04999BB49451` | `G0R2-6C9464FA73A2A027` | A → S | YES | 0.7810 | 0.7171 | +0.0638 | 0.2295 / 0.2052 | `15EE` (0.2847) | `6C94` (0.2231) | `SOURCE_STYLE_SHIFT` |
| `D11-3DCBB1695F22` | `G0R2-C2D095E069663C17` | A → S | YES | 0.8502 | 0.8448 | +0.0055 | 0.1250 / 0.1400 | `3B97` (0.1786) | `C2D0` (0.1629) | `CLASS_OVERLAP` |
| `D11-045266CD541A` | `G0R2-C2D095E069663C17` | S → A | NO | 0.7666 | 0.7826 | -0.0160 | 0.1985 / 0.2229 | `4A34` (0.2257) | `7E30` (0.2874) | `ISOLATED_OUTLIER` |
| `D11-6CD1F65F9B09` | `G0R2-C2D095E069663C17` | S → A | NO | 0.8286 | 0.8366 | -0.0081 | 0.1364 / 0.1512 | `C2D0` (0.0546) | `C2D0` (0.1928) | `SOURCE_STYLE_SHIFT` |

Existing crops were inspected only for these five errors. The dimension chain visually resembles a long structural line; the `6C94` layout rule is an annotation outlier embedded in a structural-heavy source; the `C2D0` drawing-panel divider occupies the overlap boundary; the civil roadway boundary is the most distant structural sample from its global centroid; and the trench-profile structural case is very close to a same-source structural peer but weakly transfers when that source is excluded. No case was relabeled.

Error mechanism totals: two `CLASS_OVERLAP`, two `SOURCE_STYLE_SHIFT`, and one `ISOLATED_OUTLIER`. There is no evidence that label ambiguity or the fixed crop definition is the primary shared cause.

### Dangerous-error subtype concentration

The three dangerous cases span three different source groups. Existing human subtypes are two `drawing_layout_rule` cases and one `dimension_chain`; no single recorded subtype accounts for all three. They share a line-dominant visual appearance, but that observation is not introduced as a new subtype. The failures are therefore not attributable to one source, while drawing-layout rules are the plurality (2/3).

## E. Source-count balance diagnostic

Equal-`SOURCE_GROUP` weighting changed the full structural and annotation centroid directions by cosine distances of only 0.00267 and 0.00269. In the six diagnostic folds it changed exactly one of 28 predictions (`D11-6CD1F65F9B09`, from incorrect annotation to correct structural), moving accuracy from 23/28 to 24/28 while leaving all three dangerous false structural errors unchanged.

This counterfactual was not selected as a classifier. It shows that unequal per-source counts have a **LOW** effect on centroid direction and do not explain the safety-critical errors.

## F. Abstention and margin diagnosis

| Outcome bucket | N | Absolute margin min | Median | Max |
|---|---:|---:|---:|---:|
| Correct structural | 16 | 0.0012 | 0.0538 | 0.1008 |
| Correct annotation | 7 | 0.0207 | 0.0560 | 0.0720 |
| Dangerous false structural | 3 | 0.0055 | 0.0300 | 0.0638 |
| Other errors | 2 | 0.0081 | 0.0120 | 0.0160 |
| Ambiguity reserve | 1 | 0.0817 | 0.0817 | 0.0817 |

Absolute margin has only a modest sample correlation with correctness (`r = 0.376`) and the distributions overlap materially. A correct structural case has margin 0.0012, a dangerous error reaches 0.0638, and the ambiguous reserve has a confident-looking 0.0817 margin—larger than every dangerous error and the median of either correct class. Low margin sometimes marks errors, but high margin does not imply semantic certainty and ambiguity is not ranked as uncertain.

Conclusion: **COSINE_MARGIN_NOT_VALID_UNCERTAINTY_PROXY**. The ambiguity reserve is **not** consistent with uncertainty. No threshold was introduced or tested.

## Answers and next data need

- **A:** Class and source effects are mixed. Source centroid separation is somewhat stronger than global class-centroid separation, while a small pairwise class effect remains; the distributions overlap heavily.
- **B:** The five errors comprise genuine visual class overlap (2), source-style displacement (2), and one isolated outlier. Global centroid shift, source-count imbalance, and label/crop ambiguity are not dominant explanations.
- **C:** `G0R2-C2D095E069663C17` remains weak because its two class centroids are unusually close, its structural styles transfer weakly to the other five sources, and one structural civil-line case is an isolated embedding outlier. It is not a whole-source centroid collapse.
- **D:** Dangerous errors do not share one source or one recorded subtype. Two are drawing-layout rules and one is a dimension chain; all are line-dominant hard negatives.
- **E:** Additional cases from the same groups may refine individual subtype estimates, but low prototype shift and low balancing sensitivity show that same-source volume is unlikely to solve cross-source generalization. Broader source style coverage is more important.

`NEXT_DATA_NEED`: **NEW_SOURCE_DIVERSITY_EVENTUALLY_REQUIRED**.

This conclusion does not authorize PDF acquisition. The frozen generic representation remains diagnostic-only and is not ready for production integration.

VALIDATION: **NO**.

LOCKED_BLIND: **0 / 8**.
