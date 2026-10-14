# P3B 13-sample suspect re-review result

```text
TOTAL_REVIEWED: 13
EXACT_AGREEMENT: 12
STAGE0_DISAGREEMENT: 1
STAGE1_DISAGREEMENT: 0
CONFIRMED_TRUE_PARALLEL: 2
CONFIRMED_OTHER: 10
REVISED_TO_SINGLE: 0
REVISED_TO_PARALLEL: 0
REVISED_TO_OTHER: 0
REVISED_TO_AMBIGUOUS: 0
REVISED_TO_X_OR_U: 1
FORMAL_SEED_FINAL_STATUS: NEEDS_ADJUDICATION
RECOMMENDED_NEXT_ACTION: ADJUDICATE DISPUTED SAMPLES ONLY
training_authorized: False
background_tasks_created: False
next_action_started: False
```

## Seed result

```text
TRAINING_READY_LABELS: 94
CONFIRMED_SINGLE: 38
CONFIRMED_TRUE_PARALLEL: 20
CONFIRMED_OTHER: 36
EXCLUDED: 5
ADJUDICATION_REQUIRED: 1
CONFIRMED_AMBIGUOUS: 0
```

Accepted original 82 READY labels plus exact re-review agreements; no disputed old or new class is included. CONFIRMED seed counts do not claim independent re-review of the original 82.

Compared only when both Stage-0 decisions are V; X/U changes are Stage-0 disagreements

Five original exclusions stay excluded. A new X/U that conflicts with original V remains an adjudication case, not a silently resolved exclusion.

## Disputed samples only

| Sample ID | Original rank | Original class | New stage/class | Audit reason |
|---|---:|---|---|---|
| real-48f0cee35570a79663988685 | 40 | TRUE_PARALLEL_STRUCTURE | INVALID_NOMINATION / None | PAIR_UNEQUAL_EXTENT |

Both original and new records remain preserved. No disputed label is training-eligible. No model, validation data, production geometry, DXF, OCR, Colab, Drive, recurring job or background monitor was used. No next action was started. Training still requires user/reviewer approval. STOP.
