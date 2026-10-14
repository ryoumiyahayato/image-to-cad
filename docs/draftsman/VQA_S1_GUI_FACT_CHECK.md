# VQA-S1 GUI / EXE Fact Check

## Existing application

1. **GUI stack:** PySide6 / Qt Graphics View. `ImageCanvas` provides full-resolution raster display, wheel zoom, drag pan and level-of-detail preview.
2. **GUI entry:** `cad_photo_to_dxf/main.py` constructs `app.gui_public_release.MainWindow`, whose inheritance chain retains the guarded production document window.
3. **Image/PDF loading:** `app.image_loader.load_image` handles JPG/PNG and rendered PDF pages. The active GUI loads PDF pages at a bounded processing DPI and keeps the page index and paper size with the document state.
4. **Previous preview:** the existing `original_canvas` and `detected_canvas` were separate tabs. The CAD tab used `app.preview_renderer.render_final_structure_preview` after exact tracing.
5. **Production call:** the active GUI invokes `ProductionProcessingService.process_page`, which runs the optimized trace and attaches a validated immutable `FinalStructure`.
6. **DXF consumption:** single-page export calls `export_final_structure_dxf(structure, ...)`; document export carries the same `FinalStructure` in `DocumentPage`.
7. **Renderer availability:** a canonical preview renderer already existed, but there was no source/final/overlay workbench, human verdict, issue tagging or overview artifact.
8. **Windows EXE:** `cad_photo_to_dxf.spec` builds `dist/CADPhotoToDXF/CADPhotoToDXF.exe`; Inno Setup packaging is defined in `installer/cad_photo_to_dxf.iss`.
9. **Canonical identity:** GUI preview records `_preview_structure_id = structure.structure_id`; export refuses to continue when that ID differs from the active structure.
10. **Duplicate-computation risk:** the active exact GUI/export path already shares one `FinalStructure`. Older compatibility GUI layers contain line-preview code, but `main.py` selects the final public-release chain rather than those legacy endpoints.

## VQA-S1 integration

The new `视觉验收` tab is part of the existing public `MainWindow`. It renders source, final reconstruction and overlay directly from the active `FinalStructure`, rejects coordinate mismatches, and synchronizes zoom/pan. Layer toggles change display only; they do not mutate canonical entities or reconstruction behavior.

Every run writes Git-ignored runtime evidence under `local-artifacts/draftsman/visual-acceptance/<run-id>/`: original, reconstruction, overlay, overview, human review and developer details. Developer details bind every displayed entity to the `FinalStructure` ID, source region and available upstream IDs/provenance. The normal interface translates unverified semantic state into plain Chinese; raw details remain collapsed.

## Actual runs

- Golden plumbing: `environment-page-003.png`, 3818 canonical display entities. Source, reconstruction and overlay shared one page coordinate system.
- Real DEV: `A2-SG-009.jpg`, 5842 canonical display entities. Page extent and the four plan locations aligned, while large portions of faint upper-page structure and multiple text details were absent or weak in the current final output. VQA-S1 intentionally did not alter reconstruction to improve this result.

The native Windows app launched successfully. The available Computer Use surface exposed browser tabs only and no native application window, so safe automated mouse UAT was unavailable. The same native PySide6 `MainWindow` was therefore instantiated for the real DEV run and captured with the integrated `视觉验收` tab visible. A human verdict remains pending for the user.

## Scope guards

- Only tracked Golden and `A2-SG-009` DEV material were used.
- VALIDATION and LOCKED_BLIND material were not opened, rendered, processed or inspected.
- The runtime writer fails closed when `corpus_split=LOCKED_BLIND`.
- Draftsman reconstruction semantics were not changed.
- Production semantic delta: `NONE`.
