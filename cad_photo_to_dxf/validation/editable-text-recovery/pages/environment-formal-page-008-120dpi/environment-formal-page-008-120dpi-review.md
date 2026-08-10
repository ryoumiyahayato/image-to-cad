# environment-formal-page-008-120dpi

- Input: `tests/real_regression/assets/environment-scan-page-08-120dpi.png`
- Page / DPI: 8 / 120
- FinalStructure: `bf4429c38b55955be52f86659ad9793aea2a5e12d2ffd59c290a8ac7e25249da`
- OCR candidates: 83
- TEXT eligible / native TEXT: 77 / 77
- Confidence hard rejects: 6
- Invalid geometry rejects: 0
- Hidden source-outline backup candidates / entities: 65 / 521
- Uncertain candidates / entities: 6 / 30
- TRACE_TEXT_SYMBOL entities: 781
- Maximum center / rotation error: 5.684341886080802e-14 / 0.0
- Width-factor range: 0.72 to 1.5623821746882511
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

- `ocr-032`: `confidence_below_contract` — `6`
- `ocr-036`: `confidence_below_contract` — `G`
- `ocr-048`: `confidence_below_contract` — `0`
- `ocr-052`: `confidence_below_contract` — `6`
- `ocr-055`: `confidence_below_contract` — `6`
- `ocr-083`: `confidence_below_contract` — `Q`
