# Editable TEXT recovery validation

This directory records the non-destructive OCR editable-TEXT recovery.

The acceptance target is candidate-level:

- every `text_emit_eligible=true` OCR candidate emits exactly one native DXF
  `TEXT`;
- source-outline suppression is decided independently;
- unsafe source glyphs are retained on the hidden
  `SOURCE_TEXT_OUTLINE` layer;
- hard-rejected or invalid OCR remains visible as uncertain/fallback outline;
- an eligible candidate contributes no primary `TRACE_TEXT_SYMBOL` semantic;
- every generated DXF and every source page is audited independently.

The phase 12 baseline tag and the real-regression manifests are immutable
inputs. This task does not record or accept a new regression baseline.

