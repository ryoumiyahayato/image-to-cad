# VQA-S1 — GUI Human Visual Acceptance Workbench

## Purpose

VQA-S1 adds a human-visible acceptance surface to the existing Windows/PySide6 application. It does **not** change Draftsman reconstruction semantics.

The workbench is intentionally simple:

- original source rendering;
- final reconstruction rendered from the current `FinalStructure`;
- same-coordinate overlay;
- linked zoom/pan;
- whole-page human verdict (`PASS`, `PARTIAL`, `FAIL`);
- simple visible-problem tags;
- normalized cursor coordinates;
- automatic `visual_acceptance_overview.png` and `human_review.json` under `local-artifacts/draftsman/visual-acceptance/`.

## GUI / EXE fact check

The product GUI is PySide6/Qt and is launched by `cad_photo_to_dxf/main.py` through `app.gui_public_release.MainWindow`. The existing application already owns `ImageCanvas` instances for source and CAD preview, and `ImageCanvas` already supports full-resolution pan/zoom.

`FinalStructure` remains the canonical page state. The existing exact-release path builds and stores `_final_structure`, renders GUI preview from that object, persists the same object in trace cache, and the single-page export path verifies `_preview_structure_id == FinalStructure.structure_id` before calling the final-structure DXF exporter.

VQA-S1 therefore reuses this contract rather than inventing a second reconstruction pipeline.

## Deliberate limits

- VQA-S1 does not run or modify Draftsman algorithms to improve screenshots.
- LOCKED_BLIND sources must not be opened, rendered, processed, or manually inspected.
- Validation sources are not needed for VQA-S1 plumbing.
- Page-level `FinalStructure.warnings` are displayed as a count. They are **not** drawn as fake spatial warning boxes because the current warning contract does not provide trustworthy page regions.
- Category rectangles are review annotations only. They do not alter CAD geometry.
- DXF/DWG editability remains a separate native-CAD UAT gate.
- HTML export is not required for VQA-S1; the existing Windows GUI is the primary review surface.

## Human acceptance rule

For future reconstruction-effect claims, automated tests and metrics are supporting evidence only. A visual change should also produce a human-visible comparison from the same final page structure. If a reviewer can see an obvious reconstruction error, the visual improvement is not accepted merely because automated checks pass.

## Local artifacts

Runtime screenshots and reviews are written below:

`local-artifacts/draftsman/visual-acceptance/`

This root is already ignored by Git. Source drawings and generated visual artifacts must not be committed.

## Native UAT still required

The implementation can be validated by CI for importability and pure rendering contracts, but completion of VQA-S1 requires one Windows-native run on an allowed real DEV source. That run should verify:

1. the `视觉验收` tab opens in the packaged application;
2. original/reconstruction/overlay use the same page coordinates;
3. zoom/pan linkage is usable;
4. human verdict/problem tags persist;
5. `visual_acceptance_overview.png` is generated;
6. no LOCKED_BLIND source is touched.
