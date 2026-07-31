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
