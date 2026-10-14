# warehouse-source-page-002-072dpi

- Input: `tests/real_regression/assets/sources/warehouse-electrical-vector.pdf`
- Page / DPI: 2 / 72
- FinalStructure: `189a5f3012f5cf0835ff4f1df276d94ace4d48ab8cb1b2c6ef7d012d19e4f774`
- OCR candidates: 145
- TEXT eligible / native TEXT: 143 / 143
- Confidence hard rejects: 2
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 102 / 888
- Uncertain candidates / entities: 2 / 5
- TRACE_TEXT_SYMBOL entities: 558
- Maximum center / rotation error: 2.2737367544323206e-13 / 0.0
- Width-factor range: 0.72 to 1.8898756660746006
- Overall: PASS

## Acceptance checks

- PASS `native_TEXT_count_equals_text_emit_eligible_count`
- PASS `replacement_unsafe_does_not_downgrade_eligible_text`
- PASS `eligible_candidate_enters_TRACE_TEXT_SYMBOL_count_is_zero`
- PASS `candidate_primary_semantic_conflict_count_is_zero`
- PASS `candidate_source_pixel_ownership_is_conserved`
- PASS `fallback_and_text_symbol_conflict_count_is_zero`
- PASS `unsafe_source_outline_backup_is_default_hidden`
- PASS `no_duplicate_visible_text_representation`
- PASS `every_OCR_TEXT_layer_entity_is_native_TEXT`
- PASS `native_TEXT_geometry_contract_passes`
- PASS `DXF_audit_error_count_is_zero`
- PASS `DXF_read_save_read_and_edit_passes`
- PASS `preview_and_DXF_consumed_same_FinalStructure`
- PASS `formal_structure_and_protection_audit_passes`
- PASS `OCR_threshold_contract_recorded_unchanged`
- PASS `baseline_was_not_updated`

## Candidates without native TEXT

- `ocr-110`: `confidence_below_contract` — `G`
- `ocr-111`: `confidence_below_contract` — `R`
