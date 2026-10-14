# Direct Continuation Review V1 — Batch 01 Final

Status: `HUMAN_REVIEW_FROZEN`

This file records human review observations from the completed
`DIRECT_CONTINUATION_REVIEW_V1` export. They are not perfect ground truth,
production truth, or engineering semantic truth. Human decisions and notes
are preserved in `batch-01-review-record.json` without relabeling.

## Frozen identity

- Candidate set: `FRESH-DEV-CANDIDATE-REMINING-V1-5EA8AAE98504`
- Fresh remining checkpoint: `93438db2978d45d2fdc4022f82f52cac18ded831`
- Review records: `24`
- Candidate-set digest: `5ea8aae98504f6a1c49ac90737f52fc08589d17e175f396163d0e7e4ea281486`
- Original export SHA-256: `057b420ad4a2f9a07c371e274b14feb841b4a484a1938ffd611900e393368727`
- Tracked review-record SHA-256: `76ec610ed97b2446b1b03f69b715f2c8c3e15380ec1900b7356037ba52f276e0`
- Source mapping digest: `41ffff12d27cf9d9aa9836c3c32f2f4683e276c974f85b53d56f3fe9deccb19b`
- A/B geometry digest: `97627f5715e2e52fa946901b36a4b769bdea82bf19a590daf213f6debccff84c`
- Prior review-package manifest digest: `6494714cd19cb1b3fb00751f72ad1482f6b4388765d245b90d24981934311efe`
- Freeze code checkpoint: `88f44c161db11d9cb38c751374bbf5df0a13b074`
- Review completion timestamp in source export: not present

## Human counts

| Observation | Count |
| --- | ---: |
| `DIRECT_STRAIGHT_CONTINUATION` | 15 |
| `NOT_DIRECT_STRAIGHT_CONTINUATION` | 9 |
| `INSUFFICIENT_EVIDENCE` | 0 |
| `OBJECT_GEOMETRY` among DIRECT | 8 |
| `ANNOTATION_LAYOUT` among DIRECT | 6 |
| `UNKNOWN_ROLE` among DIRECT | 1 |

The role observations remain useful downstream but difficult borderline cases
are not silently corrected. The direct-continuation judgment is the primary
human signal.

## Downstream set semantics

DIRECT cases are eligible for the separate object-vs-annotation perception
dataset only through Stage 2. NOT_DIRECT cases remain hard-negative regression
examples and are not reinterpreted as annotation labels.

## Governance

- Production semantic delta: `NONE`
- New candidate mining: `NO`
- Model run or model-assisted labeling: `NO`
- Validation: `NO`
- Locked blind: `0 / 8`
- H1/H2 opened: `NO`
- Labels modified: `NO`
- Public redistribution: `NOT_AUTHORIZED`
