# Project checkpoint

Recorded: 2026-07-31

- Repository: `ryoumiyahayato/image-to-cad`
- Target branch: `fix/non-destructive-editable-text`
- P1B start: `5f7846e00b41913c003f178558a110e6475c0ee0`
- P1B-1: `434209f0ef0e405726cfd6d733d62c7ae0ce8f17`
- P1B-2 / current target HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`
- P1B-3 PR: #28, Draft, open, not merged
- Validation run: `30631003176`; job: `91157062020`
- Phase-12 baseline tag was not moved, deleted, or recreated

## P1B-3 result

Status: **P1B automated validation blocked**.

- Full pytest: 282 passed, 0 failed, 9.29 seconds.
- Formal real-document regression: 12 document/DPI configurations, 10 unique source pages, all configurations rejected by committed expectations.
- Common mismatch: baselines require `replacement_unsafe` editable candidates to become fallback outlines; current approved contract emits all eligible candidates as native editable `TEXT`.
- Ruff, compileall, all-DXF read-save-read, actual `346 -> 0` DXF audit, new-boundary-crossing audit and releasable manual-UAT packaging were not executed because the mandatory formal gate stopped the workflow.
- No production code, algorithm, threshold, routing, structure behavior, baseline, color, PDF behavior, or `FinalStructure` was changed in P1B-3.
- No third success commit named `test: validate fitted text geometry on every page` was created.
- PR #28 must remain Draft and must not be merged.
- Current state is not `Awaiting user LibreCAD UAT`.

Evidence is under `cad_photo_to_dxf/validation/text-geometry-fit/`.

## Next single safe operation

Authorize a separate real-regression baseline and acceptance-contract reconciliation task to decide how the pre-P0 fallback expectations should relate to the approved non-destructive editable-text contract. Do not begin P2 and do not release the LibreCAD UAT package before that conflict is resolved and P1B-3 is rerun.
