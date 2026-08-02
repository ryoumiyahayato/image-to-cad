# Project checkpoint

Recorded: 2026-07-31

- Branch: `fix/non-destructive-editable-text`
- P1B start: `5f7846e00b41913c003f178558a110e6475c0ee0`
- P1B-1 commit: `434209f0ef0e405726cfd6d733d62c7ae0ce8f17`
- Phase-12 baseline tag remains untouched.

## P1B-2

All reachable native TEXT creation entry points now delegate to `ocr_outline_export.add_ocr_outline_blocks`. The legacy trace compatibility function no longer owns an independent 0.82 height/heuristic-width implementation. The generic DXF exporter no longer owns an independent 0.85 bbox-height implementation. Focused tests compare entity type, content, height, width factor, rotation, and insertion.

## Next safe operation

Run P1B-3 full validation and produce the per-page/manual-UAT package. Do not begin P2.

## P1B-R2 immutable-anchor reconciliation

Status: **Editable-text regression contract reconciled using immutable commit/blob anchors; P1B-3 rerun required.**

- Coordination PR: #30
- Working branch: `agent/editable-text-regression-contract-v1-r2`
- Start HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`
- Baseline source (B): `5f7846e00b41913c003f178558a110e6475c0ee0`
- Phase-12 anchor (A): `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba`
- Phase-12 manifest: `cad_photo_to_dxf/tests/real_regression/manifest.json`
- Phase-12 manifest blob: `533ae15afcef24dd4444f9acc3d504bbd94d9c87`
- Recorded legacy tag: `baseline/phase12-final-acceptance-2026-07-30`; `tag_ref_status=absent`
- New baseline: `cad_photo_to_dxf/validation/baselines/non-destructive-editable-text-v1/`
- Coverage: 12 document/DPI configurations over 10 independent real pages
- Production algorithms changed: no
- Next operation: rerun P1B-3; P2 has not started.
