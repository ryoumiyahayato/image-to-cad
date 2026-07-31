# Native DXF TEXT code paths

Three creators exist. Canonical: `ocr_outline_export._candidate_quad` -> `_font_strategy` -> `_line_placement_from_quad` -> `_add_text_entity` -> `add_ocr_outline_blocks`. It fits exact LFF visible height, computes raw width factor, then clamps `[0.72,4.0]`. `trace_single_export` and `trace_document_export` both call it.

Legacy 1: `trace_dxf_entities.add_ocr_text_entities` uses height `0.82`, heuristic widths, clamp `[0.20,4.0]`, bottom-left placement. Legacy 2: `dxf_exporter.export_dxf` uses bbox height `0.85`, no width fit or rotation.

GUI preview uses FinalStructure but `preview_renderer` does not render native TEXT geometry. SOURCE_TEXT_OUTLINE is separately exported and does not enter canonical sizing. The DXF lacks exact original bbox/quad, so records reconstruct it from geometry XDATA.
