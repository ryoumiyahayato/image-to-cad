# Native TEXT path unification

- Canonical implementation: `ocr_outline_export.add_ocr_outline_blocks`.
- Current single-page export delegates directly to canonical geometry.
- Current document/batch export delegates directly to canonical geometry.
- Legacy `trace_dxf_entities.add_ocr_text_entities` is retained as a compatibility entry point and delegates to canonical geometry.
- Legacy `dxf_exporter.export_dxf` delegates its text segment to canonical geometry.
- Independent reachable `0.82` and `0.85` text-height formulas are no longer used.
