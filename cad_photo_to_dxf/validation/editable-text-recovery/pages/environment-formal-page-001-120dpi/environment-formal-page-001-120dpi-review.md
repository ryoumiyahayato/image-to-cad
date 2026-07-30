# environment-formal-page-001-120dpi

- Input: `tests/real_regression/assets/environment-scan-page-01-120dpi.png`
- Page / DPI: 1 / 120
- FinalStructure: `6cfee7631e221619f3dde0b430c86df394667d4c63e2a09ade2a3702364f0a81`
- OCR candidates: 140
- TEXT eligible / native TEXT: 139 / 139
- Confidence hard rejects: 1
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 129 / 1311
- Uncertain candidates / entities: 1 / 3
- TRACE_TEXT_SYMBOL entities: 1206
- Maximum center / rotation error: 0.0 / 0.0
- Width-factor range: 0.72 to 1.436002834868887
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

- `ocr-050`: `confidence_below_contract` — `S`
