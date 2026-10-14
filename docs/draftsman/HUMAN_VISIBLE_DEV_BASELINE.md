# Human-visible DEV baseline

Status: **COMPLETE**

This baseline records the first five-source, human-visible run through the production
Draftsman path and the VQA-S1 workbench. It is observation evidence, not a quality
metric and not ground-truth accuracy. No reconstruction semantics were changed.

## Scope

- Five independent, materialized `DEV` source groups were processed.
- Each run used `ProductionProcessingService`, its canonical `FinalStructure`, and
  the integrated PySide6 `MainWindow` visual-acceptance tab.
- Every run produced `original.png`, `reconstructed.png`, `overlay.png`,
  `visual_acceptance_overview.png`, and a captured workbench window.
- `VALIDATION` was not used.
- `LOCKED_BLIND` was not opened, rendered, inspected, or executed; runtime remains
  `0 / 8`.
- Production semantic delta: `NONE`.

## Human-visible results

| DEV SOURCE_GROUP | Verdict | Missing | Extra | Wrong connection | Position/scale | Text | Symbol | Main visible observation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `A2-SG-009` | FAIL | Yes | No evidence | No evidence | No evidence | Yes | No evidence | Upper faint structures and many text details are absent; the four main plan locations remain aligned. |
| `A2-SG-022` | PARTIAL | Yes | No evidence | No evidence | No evidence | Yes | No evidence | Main building and site geometry align, while faint landscape lines and text detail are missing. |
| `G0R2-3560D9BEBEAA3543` | PARTIAL | Yes | Yes | No evidence | No evidence | Yes | No evidence | Major geometry aligns, but text is frequently garbled and some fine details are omitted or overdrawn. |
| `G0R2-7E30C7F445081F40` | FAIL | Yes | No evidence | No evidence | No evidence | Yes | No evidence | The dominant aerial/site raster is not reconstructed; page-frame alignment is retained. |
| `G0R2-B441E5911528F402` | PARTIAL | No clear evidence | No evidence | No evidence | No evidence | Yes | No evidence | Historical plan linework is broadly positioned correctly, with dense and visibly inaccurate text reconstruction. |

## Common failure families

`CONTENT_RECALL_FAILURE` is supported by four independent DEV source groups:
`A2-SG-009`, `A2-SG-022`, `G0R2-3560D9BEBEAA3543`, and
`G0R2-7E30C7F445081F40`.

`TEXT_RECONSTRUCTION_FAILURE` is supported by all five independent DEV source
groups.

These families are recorded only. No algorithm change is part of this baseline.

## Runtime evidence

The Git-ignored baseline manifest and contact sheet are stored in
`local-artifacts/draftsman/human-visible-dev-baseline-v1/`. The five source run IDs
are:

- `20260909T134921Z-A2-SG-009-jpg-33172d9bb3`
- `20260909T141228Z-A2-SG-022-pdf-193b8193a3`
- `20260909T141619Z-G0R2-3560D9BEBEAA3543-pdf-79c37f7d56`
- `20260909T142011Z-G0R2-7E30C7F445081F40-pdf-0c5ab51ffc`
- `20260909T142127Z-G0R2-B441E5911528F402-pdf-a3ed8fbb77`

The Windows EXE UAT remains `PARTIAL` because of the previously identified font
asset packaging issue. This did not block the native PySide6 `MainWindow` runs.
