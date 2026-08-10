# Editable TEXT recovery acceptance

Status: **PASS**

This directory records the non-destructive editable-TEXT recovery from the untouched phase 12 baseline. It contains 33 independent final page/DXF reports: every page of both user source PDFs, every distinct formal regression input and DPI variant, the fixed 240-DPI failure page, and the same-DPI d9fbda7 comparison.

Key results:

- 4394 eligible candidates emitted 4394 native DXF TEXT entities.
- 47 candidates were hard rejected by the unchanged confidence contract; invalid geometry: 0.
- 3726 unsafe source glyph candidates were retained on the default-hidden/frozen backup layer.
- Eligible candidate-owned TRACE_TEXT_SYMBOL objects, semantic conflicts, ownership violations, visible duplicates and DXF audit errors are all zero.
- Windows LibreCAD direct edit/save and ezdxf read-save-read passed with the bundled wqy-unicode LFF.

Start with `completion-status.md`, `before-after-summary.json`, `per-page-index.json`, and `page001-before-after.md`. Each page directory contains routing, geometry, entity audit, four isolated renders, the DXF, and its review.
