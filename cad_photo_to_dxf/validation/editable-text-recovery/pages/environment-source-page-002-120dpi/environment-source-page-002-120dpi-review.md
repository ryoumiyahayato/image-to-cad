# environment-source-page-002-120dpi

- Input: `tests/real_regression/assets/sources/environment-building-scan.pdf`
- Page / DPI: 2 / 120
- FinalStructure: `43c9e47e3daac8f6ff523aad25cd5baf5caaabdda185d5419af75c81b315a1e5`
- OCR candidates: 118
- TEXT eligible / native TEXT: 112 / 112
- Confidence hard rejects: 6
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 104 / 793
- Uncertain candidates / entities: 6 / 18
- TRACE_TEXT_SYMBOL entities: 1084
- Maximum center / rotation error: 0.0 / 0.0
- Width-factor range: 0.72 to 2.2877642279887755
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

- `ocr-023`: `confidence_below_contract` — `③`
- `ocr-042`: `confidence_below_contract` — `③`
- `ocr-057`: `confidence_below_contract` — `工`
- `ocr-058`: `confidence_below_contract` — `③`
- `ocr-059`: `confidence_below_contract` — `③`
- `ocr-087`: `confidence_below_contract` — `③`
