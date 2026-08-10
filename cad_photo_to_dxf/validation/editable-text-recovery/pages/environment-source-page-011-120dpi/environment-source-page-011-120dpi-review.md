# environment-source-page-011-120dpi

- Input: `tests/real_regression/assets/sources/environment-building-scan.pdf`
- Page / DPI: 11 / 120
- FinalStructure: `9a5afaeb1bd94a552d356de00dc7756ce8f0e3c650795204d9f594c1000b9b09`
- OCR candidates: 164
- TEXT eligible / native TEXT: 161 / 161
- Confidence hard rejects: 3
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 144 / 1105
- Uncertain candidates / entities: 3 / 14
- TRACE_TEXT_SYMBOL entities: 986
- Maximum center / rotation error: 2.842170943040401e-14 / 0.0
- Width-factor range: 0.72 to 3.705172413793103
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

- `ocr-056`: `confidence_below_contract` — `S`
- `ocr-083`: `confidence_below_contract` — `S`
- `ocr-108`: `confidence_below_contract` — `11`
