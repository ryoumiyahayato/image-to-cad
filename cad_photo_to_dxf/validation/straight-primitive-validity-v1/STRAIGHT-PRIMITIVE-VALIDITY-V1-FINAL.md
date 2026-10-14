# STRAIGHT PRIMITIVE VALIDITY V1 — FINAL

`SOURCE_GAP_REVIEW_V1_1_STATUS: PAUSED_PRIMITIVE_VALIDITY`

## Decision

A generic DEV-only gate is justified. It reuses the prior local trajectory, lateral offset, tangent, continuity, and support-run diagnostics. Rejection requires a strong full-extent failure: a material unsupported run, a width-normalized piecewise offset, a sustained scale-aware lateral drift with tangent mismatch, or an abrupt trajectory identity switch. Mild drift and noisy evidence remain `STRAIGHT_UNCERTAIN`.

The current replacement is rejected without using its identity, coordinates, source family, filename, or semantic class. Its two fragments show maximum sustained lateral drift of about 14.4% and 9.6% of claimed length; one profile also switches between incompatible local support levels. This is consistent with a global straight fit through a curved contour rather than a stable straight ridge.

Intersections are not failures by themselves. The gate follows the associated ridge and preserves continuous straight trajectories through crossings, filled nodes, tables, title blocks, grids/dimensions, and a synthetic straight symbol edge.

## Bounded case audit (16 cases)

| candidate_id | human observation | trajectory stability | max lateral drift | tangent stability | support identity | text status | straight-validity status | eligibility before | eligibility after | failure family |
|---|---|---|---|---|---|---|---|---|---|---|
| `FRESH1-91191386DC95E23BEDAC` | INVALID_PRIMITIVE_FOR_GAP_REVIEW: local straight fit across a curved graphical boundary | credible_min=0.250; support_min=1.000 | 6.500px; fraction=0.144 | p95_max=21.0deg | switches=1; runs_max=1 | TEXT_UNCERTAIN | STRAIGHT_REJECTED | ELIGIBLE_AFTER_TEXT_GUARD | INELIGIBLE_STRAIGHT_REJECTED | CURVED_CONTOUR_STRAIGHT_FIT |
| `FRESH1-316D125FE4861584BE02` | NOT_DIRECT_STRAIGHT_CONTINUATION / 显而易见的问题把多尖段的线段识别成了一条完整的直线这个也是绘图中最容易出现的一个问题也是现在必须得解决的一个问题之一现在的话呢训练一下也差不多了 | credible_min=1.000; support_min=0.977 | 4.500px; fraction=0.035 | p95_max=35.2deg | switches=0; runs_max=2 | TEXT_INDEPENDENT | STRAIGHT_REJECTED | ELIGIBLE_AFTER_TEXT_GUARD | INELIGIBLE_STRAIGHT_REJECTED | PIECEWISE_OFFSET_COLLAPSE |
| `FRESH1-392CD01D96A8D10C5946` | NOT_DIRECT_STRAIGHT_CONTINUATION / 这个两个识别的线段中间还有就是相当于本身所处的位置中有一些间断这两个并不应该放在同一个线上 | credible_min=0.875; support_min=1.000 | 2.000px; fraction=0.057 | p95_max=34.6deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_UNCERTAIN | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | INSUFFICIENT_EVIDENCE |
| `FRESH1-403904F4EF20126F9D7D` | NOT_DIRECT_STRAIGHT_CONTINUATION / 经典案例折线之间有这个符号F | credible_min=1.000; support_min=1.000 | 1.111px; fraction=0.021 | p95_max=24.9deg | switches=0; runs_max=1 | TEXT_UNCERTAIN | STRAIGHT_UNCERTAIN | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | INSUFFICIENT_EVIDENCE |
| `FRESH1-41E989458A189A3DADA3` | NOT_DIRECT_STRAIGHT_CONTINUATION | credible_min=1.000; support_min=1.000 | 1.000px; fraction=0.005 | p95_max=23.4deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_UNCERTAIN | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | INSUFFICIENT_EVIDENCE |
| `FRESH1-4966D4412392002C19C2` | VISIBLE_SEPARATE_SEGMENTS / CROSSES_STRUCTURE, BOUNDARY_POSITION_CHANGES, ENDPOINT_ANOMALY | credible_min=0.250; support_min=0.632 | 8.500px; fraction=0.131 | p95_max=52.3deg | switches=2; runs_max=3 | TEXT_INDEPENDENT | STRAIGHT_REJECTED | ELIGIBLE_AFTER_TEXT_GUARD | INELIGIBLE_STRAIGHT_REJECTED | INSUFFICIENT_STRAIGHT_TRAJECTORY_SUPPORT |
| `FRESH1-33163D6DB78308987FD9` | DIRECT_STRAIGHT_CONTINUATION / ANNOTATION_LAYOUT / 非常标准的图片的边线因为这个纸张的post而导致了一些的识别问题而且你还能够看到就这个蓝线旁边的这个还有一条黑线实际上也因为这个破损导致了它没有办法把它识别成调完整的直线 | credible_min=1.000; support_min=0.964 | 0.100px; fraction=0.001 | p95_max=5.7deg | switches=0; runs_max=5 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-24BCF545F595AC67795A` | DIRECT_STRAIGHT_CONTINUATION / OBJECT_GEOMETRY | credible_min=1.000; support_min=1.000 | 0.668px; fraction=0.012 | p95_max=2.9deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-3CF03111AF3D7D733A74` | DIRECT_STRAIGHT_CONTINUATION / ANNOTATION_LAYOUT | credible_min=1.000; support_min=1.000 | 0.000px; fraction=0.000 | p95_max=0.0deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-2DBF66108AA424A95F6E` | DIRECT_STRAIGHT_CONTINUATION / ANNOTATION_LAYOUT | credible_min=1.000; support_min=1.000 | 0.767px; fraction=0.003 | p95_max=4.9deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-25E38770B7F837BE0915` | DIRECT_STRAIGHT_CONTINUATION / OBJECT_GEOMETRY | credible_min=1.000; support_min=1.000 | 0.911px; fraction=0.017 | p95_max=17.6deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-4497ADEE7DB5D798A893` | DIRECT_STRAIGHT_CONTINUATION / OBJECT_GEOMETRY / 还是比较经典的案例但是呢我必须得说它底下这个什么呃选项这个玩意儿它容易遮挡那个备注在最后说明一下马上可能到时候还要把这个呃对应审计的这个内容给调整修改一下 | credible_min=1.000; support_min=0.975 | 1.000px; fraction=0.011 | p95_max=11.7deg | switches=0; runs_max=3 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-2329D538A065BFC7E0D8` | DIRECT_STRAIGHT_CONTINUATION / ANNOTATION_LAYOUT | credible_min=1.000; support_min=1.000 | 0.500px; fraction=0.010 | p95_max=21.2deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-2B13FEF419461264C185` | DIRECT_STRAIGHT_CONTINUATION / ANNOTATION_LAYOUT / 我必须说明一下他这边的这个蓝线的识别把线段延伸到了旁边这个标点符号的1上这个是有很明显的这个识别上的错误和问题的 | credible_min=1.000; support_min=0.949 | 0.479px; fraction=0.013 | p95_max=21.7deg | switches=0; runs_max=2 | TEXT_INDEPENDENT | STRAIGHT_UNCERTAIN | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | INSUFFICIENT_EVIDENCE |
| `FRESH1-AB2943863A535D1044B9` | CONTINUOUS_SOURCE_STROKE / CROSSES_STRUCTURE | credible_min=1.000; support_min=1.000 | 0.000px; fraction=0.000 | p95_max=7.0deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_SUPPORTED | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | STRAIGHT_SOURCE_TRAJECTORY_CONFIRMED |
| `FRESH1-51DF39D706DE8C684F10` | CONTINUOUS_SOURCE_STROKE | credible_min=1.000; support_min=1.000 | 0.000px; fraction=0.000 | p95_max=22.5deg | switches=0; runs_max=1 | TEXT_INDEPENDENT | STRAIGHT_UNCERTAIN | ELIGIBLE_AFTER_TEXT_GUARD | ELIGIBLE_UNCHANGED | INSUFFICIENT_EVIDENCE |

## Frozen 147 replay

Straight statuses: supported 82, uncertain 41, rejected 24. Text rejection overlaps 6 straight rejections. The composed DEV path has 120 eligible candidates; 18 are newly ineligible after preserving prior text rejections.

Previously human-reviewed among newly rejected: 4. Current repaired source-gap 16: retained valid 10, uncertain 3, rejected 3.

## Safety and scope

- Old valid direct control: 1 / 1; old valid annotation controls: 6 / 6.
- Fresh human-direct controls: 9 / 9; fresh human-direct annotation controls: 6 / 6.
- Span, axis, and text/glyph guard algorithms are unchanged. Admissibility thresholds are unchanged; only DEV composition is extended before pair formation.
- No remine, model run, package regeneration, production change, endpoint change, continuity guard, or semantic exception was introduced.
- Focused verification: 105 passed: straight validity 15, coherence/span 31, axis/text 39, admissibility 8, DEV remining 12; Ruff passed for new files; compileall passed.

## Next target

`FROZEN147_NEWLY_INELIGIBLE_STRAIGHT_REJECTED_AUDIT`. Do not resume source-gap review, Batch-03, or model bake-off before that frozen-pool review is resolved.
