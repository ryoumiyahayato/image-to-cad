# environment-source-page-005-120dpi

- Input: `tests/real_regression/assets/sources/environment-building-scan.pdf`
- Page / DPI: 5 / 120
- FinalStructure: `7ab0d9bb4534322f9bd6027beada853f1ff6eea71550c24f2aac9300afd7b51c`
- OCR candidates: 150
- TEXT eligible / native TEXT: 150 / 150
- Confidence hard rejects: 0
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 130 / 1144
- Uncertain candidates / entities: 0 / 0
- TRACE_TEXT_SYMBOL entities: 1118
- Maximum center / rotation error: 0.0 / 0.0
- Width-factor range: 0.72 to 4.0
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

- None.
