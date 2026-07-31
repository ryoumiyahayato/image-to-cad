# P1B-3 automated validation blocker

Status: **P1B automated validation blocked**.

## Facts

- Full pytest: 282 passed, 0 failed, 9.29 seconds.
- Formal real-document regression: 12 configurations, 10 unique source pages, all configurations failed.
- The pipeline stages themselves completed for the reported pages, including OCR, structure analysis, preview, content audit and DXF export.
- The mandatory comparison gate then rejected the results.

## Common failure pattern

The committed expectations encode the old rule that candidates with `replacement_safe == false` are downgraded from native editable `TEXT` to fallback outlines. The current approved contract explicitly states that `replacement_safe` must not become a `TEXT` emission gate.

Representative examples:

- `environment-scan-page-001-120dpi`: expected 10 editable texts and 129 replacement-unsafe fallbacks; observed 139 editable texts and no replacement-unsafe downgrades.
- `environment-plan-page-003-150dpi`: expected 23 editable texts and 131 fallbacks; observed 154 editable texts and 0 fallbacks.
- `warehouse-system-page-002-72dpi`: expected 41 editable texts and 102 replacement-unsafe fallbacks; observed 143 editable texts and only the two confidence-rejected fallbacks.

Because those objects change from outlines to native text, the old contour counts, content hashes and structure IDs also differ. These differences cannot be accepted or hidden inside P1B-3, but reverting the current routing would violate the approved P0/P1 contract.

## Required handling

Under the P1B-3 task contract:

1. keep PR #28 Draft;
2. do not merge it;
3. do not change production algorithms;
4. do not lower the gate;
5. do not record new baselines;
6. do not release the LibreCAD UAT package;
7. do not start P2.

## Recommended independent task

Authorize a separate **real-regression baseline and acceptance-contract reconciliation** task. It must determine, with explicit user authorization, whether the formal expectations should be migrated to the already-approved non-destructive editable-text policy. That work must remain separate from text geometry and must not alter OCR or geometry behavior merely to force historical hashes to match.
