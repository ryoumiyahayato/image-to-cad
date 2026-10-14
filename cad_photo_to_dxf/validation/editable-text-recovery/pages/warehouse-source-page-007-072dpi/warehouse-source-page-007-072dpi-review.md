# warehouse-source-page-007-072dpi

- Input: `tests/real_regression/assets/sources/warehouse-electrical-vector.pdf`
- Page / DPI: 7 / 72
- FinalStructure: `e3f6f1f5a9dd3dbe9ae0d9217721a916467878d2f7d995375d8bbee63c297cc2`
- OCR candidates: 127
- TEXT eligible / native TEXT: 126 / 126
- Confidence hard rejects: 1
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 107 / 642
- Uncertain candidates / entities: 1 / 1
- TRACE_TEXT_SYMBOL entities: 753
- Maximum center / rotation error: 0.0 / 0.0
- Width-factor range: 0.72 to 3.418462643678161
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

- `ocr-078`: `confidence_below_contract` — `核`
