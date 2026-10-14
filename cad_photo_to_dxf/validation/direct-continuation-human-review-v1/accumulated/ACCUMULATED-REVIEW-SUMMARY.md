# Direct Continuation Review V1 — Accumulated Summary

Status: `HUMAN_REVIEW_FROZEN` for Batch 01; Batch 02 is `PENDING`.

## Completed human observations

| Metric | Count |
| --- | ---: |
| Total reviewed | 24 |
| `DIRECT_STRAIGHT_CONTINUATION` | 15 |
| `NOT_DIRECT_STRAIGHT_CONTINUATION` | 9 |
| `INSUFFICIENT_EVIDENCE` | 0 |
| `OBJECT_GEOMETRY` | 8 |
| `ANNOTATION_LAYOUT` | 6 |
| `UNKNOWN_ROLE` | 1 |

Object and annotation counts are planning floors, not statistically sufficient
guarantees. Continue 24-case batches until both completed DIRECT role counts
reach 35. Do not predict the number of batches required.

## Pool and Batch 02

- Frozen fresh pool: `147`
- Remaining after exact Batch-01 exclusion: `123`
- Batch 02 selected: `24 / 24`
- Batch 02 human review: `PENDING`
- Batch 01 candidates reused: `0`
- Batch 01 exact geometry reused: `0`
- Batch 02 deterministic replay: `PASS`

## Historical funnel bookkeeping

- Raw Hough primitives: `26201`
- Span-status total: `25664`
- Not span-evaluated: `537`
- Reason: `orientation_filter_rejected_before_span_evaluation` = `537`
- Unaccounted: `0`
- Status: `COMPLETE`

The 537 records are mechanically explained by the existing telemetry field
`orientation_eligible_raw_hough_primitives` and the existing `_raw_hough`
orientation gate. No Hough mining was rerun and no guard was changed.

## Governance

- Production semantic delta: `NONE`
- Model bake-off should resume: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- New candidate mining: `NO`
