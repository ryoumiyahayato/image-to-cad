# P3B VALIDATION SUSPECT REVIEW FINAL

```text
TOTAL_REVIEWED: 8
EXACT_AGREEMENT: 6
STAGE0_DISAGREEMENT: 0
STAGE1_DISAGREEMENT: 2
CONFIRMED_SINGLE: 3
CONFIRMED_TRUE_PARALLEL: 2
CONFIRMED_OTHER: 0
CONFIRMED_AMBIGUOUS: 1
REVISED_TO_SINGLE: 0
REVISED_TO_TRUE_PARALLEL: 2
REVISED_TO_OTHER: 0
REVISED_TO_AMBIGUOUS: 0
REVISED_TO_X_OR_U: 0
VALIDATION_FINAL_STATUS: PASS
DISPUTED_REMAINING: 0
FINAL_VALIDATION_SINGLE: 22
FINAL_VALIDATION_TRUE_PARALLEL: 20
FINAL_VALIDATION_OTHER: 7
FINAL_VALIDATION_AMBIGUOUS: 1
FINAL_VALIDATION_EXCLUDED: 0
TRAINING_DATA_FREEZE: READY
READY_FOR_COLAB_TRAINING_PREFLIGHT: YES
TRAIN_VALIDATION_LEAKAGE: NONE
BLIND_TOUCHED: NO
MODEL_TRAINED: NO
COLAB_STARTED: NO
BACKGROUND_TASKS_CREATED: NO
```

Stage-1 disagreement is compared only when both Stage-0 answers are V. X/U changes are Stage-0 disagreement. Every new complete decision is current under the user's explicit rule; no disagreement has been silently discarded.

## Disagreements

| Rank | Sample ID | Original decision | New/current decision | Review reason |
|---:|---|---|---|---|
| 17 | val-v2-0ef668e8d4a1ddc737649a25 | VALID_TARGET / AMBIGUOUS | VALID_TARGET / TRUE_PARALLEL_STRUCTURE | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced |
| 33 | val-v2-19fa87d80bb54ff6794f6a51 | VALID_TARGET / AMBIGUOUS | VALID_TARGET / TRUE_PARALLEL_STRUCTURE | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 using available context; uncertainty is not an error and no class is forced |

Both historical records remain unchanged. Current adjudication: `validation-adjudicated-decisions.jsonl`. Exact freeze: `TRAINING-DATA-FREEZE.json`, with immutable current-truth snapshots, original/re-review state and manifest hashes, sample IDs, distributions, source-family splits, effective DPI, exclusions and ambiguity policy. No blind files were opened.

## AMBIGUOUS training policy

Technically preferable initial route: **A — three-class baseline plus abstention policy**.

The 94 accepted train labels contain no AMBIGUOUS examples. Ambiguity here reflects unresolved source interpretation rather than a consistently observed fourth physical structure. An initial three-class baseline avoids an unsupported learned fourth class; four-class learning requires genuine train ambiguity evidence (route B), never fabricated balance.

Every human AMBIGUOUS label remains in frozen validation truth. Evaluate these separately as ambiguity/abstention cases alongside unambiguous classification, with all-sample coverage and failure reporting; never remap class 4 to another class or silently remove it.

Low confidence is not guaranteed to detect human ambiguity or wrong high-confidence predictions. Evaluate abstention on the independent ambiguous subset; report its small size. Threshold selection must avoid fitting to these eight review answers. This recommendation requires later explicit training authorization and leaves production safety vetoes intact.

Do not fabricate a learned/calibrated AMBIGUOUS probability from a three-class model; any later API abstention mapping must be explicitly documented.

Accepted train labels: 94; excluded train: 6. Final included validation: 50; excluded validation: 0.

READY_FOR_COLAB_TRAINING_PREFLIGHT means the data are frozen and ready for a separate authorized infrastructure/policy/checkpoint-resume check, not authorization to install/connect/train. Later authorization is still required. No production/DXF/OCR code or outputs changed; all 157 production app/test files match the retained snapshot.

NEXT_ACTION: Separate explicitly authorized Colab/training pre-flight; no training now

STOP.
