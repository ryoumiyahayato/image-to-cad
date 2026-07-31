# Current task

**P1B-3: full native DXF TEXT geometry validation and manual-UAT prerequisite.**

Branch: `fix/non-destructive-editable-text`  
P1B start HEAD: `5f7846e00b41913c003f178558a110e6475c0ee0`  
P1B-1: `434209f0ef0e405726cfd6d733d62c7ae0ce8f17`  
P1B-2 / target branch HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`  
Validation PR: #28 (`agent/p1b-full-validation-stage3`)

Status: **P1B automated validation blocked**.

The full pytest suite completed with 282 passed tests. The mandatory formal real-document regression then failed for all 12 document/DPI configurations covering 10 unique source pages. The checked-in expectations still require `replacement_unsafe` candidates to be downgraded to fallback outlines, while the approved current contract explicitly states that `replacement_safe` is not a native `TEXT` output gate.

P1B-3 did not modify production code, OCR thresholds, text eligibility, routing, structures, PDF behavior, colors, `FinalStructure`, or regression baselines. PR #28 remains Draft and unmerged. The LibreCAD UAT package is not released.

The next single safe operation is an explicitly authorized, separate real-regression baseline and acceptance-contract reconciliation task. It is not P2. P2 is not authorized.
