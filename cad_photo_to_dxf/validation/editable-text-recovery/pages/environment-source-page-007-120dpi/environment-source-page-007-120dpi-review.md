# environment-source-page-007-120dpi

- Input: `tests/real_regression/assets/sources/environment-building-scan.pdf`
- Page / DPI: 7 / 120
- FinalStructure: `3c356efe50ad6a065e8940d4fef396febfbe20ffa7c2164f76a442f648bbda3a`
- OCR candidates: 155
- TEXT eligible / native TEXT: 151 / 151
- Confidence hard rejects: 4
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 138 / 1220
- Uncertain candidates / entities: 4 / 29
- TRACE_TEXT_SYMBOL entities: 1057
- Maximum center / rotation error: 0.0 / 0.0
- Width-factor range: 0.72 to 3.175862068965517
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

- `ocr-043`: `confidence_below_contract` — `③`
- `ocr-044`: `confidence_below_contract` — `③`
- `ocr-071`: `confidence_below_contract` — `O`
- `ocr-090`: `confidence_below_contract` — `③`
