# environment-source-page-008-120dpi

- Input: `tests/real_regression/assets/sources/environment-building-scan.pdf`
- Page / DPI: 8 / 120
- FinalStructure: `9d414c97eb2880b788e27af4d0d368fc49553f32006f5b8f78108c7cced74d37`
- OCR candidates: 84
- TEXT eligible / native TEXT: 82 / 82
- Confidence hard rejects: 2
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 70 / 556
- Uncertain candidates / entities: 2 / 10
- TRACE_TEXT_SYMBOL entities: 730
- Maximum center / rotation error: 5.684341886080802e-14 / 0.0
- Width-factor range: 0.72 to 2.1142785065590313
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

- `ocr-019`: `confidence_below_contract` — `3`
- `ocr-050`: `confidence_below_contract` — `8`
