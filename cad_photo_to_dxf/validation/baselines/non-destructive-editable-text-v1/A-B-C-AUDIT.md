# P1B-R2 A → B → C audit

- A: `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba` — phase 12 architecture/safety history
- B: `5f7846e00b41913c003f178558a110e6475c0ee0` — editable-text recovery, before width fix
- C: `80be85aba985e457bc7bff1e9ece49f50e7a46d2` — width fix and path unification
- Coverage: 12 document/DPI configurations over 10 independent real pages

## A → B classification

| Configuration | Native TEXT | Fallback outline | SOURCE_TEXT_OUTLINE | TRACE_TEXT_SYMBOL | Classification |
|---|---:|---:|---:|---:|---|
| environment-plan-page-003-150dpi | 23 → 154 | 131 → 0 | 0 → 1382 | 1189 → 1196 | approved editable-text routing/derived changes |
| environment-scan-page-001-120dpi | 10 → 139 | 129 → 1 | 0 → 1311 | 1164 → 1206 | approved editable-text routing/derived changes |
| environment-scan-page-002-120dpi | 5 → 97 | 92 → 2 | 0 → 672 | 1201 → 1284 | approved editable-text routing/derived changes |
| environment-scan-page-004-120dpi | 22 → 157 | 135 → 0 | 0 → 1284 | 1149 → 1232 | approved editable-text routing/derived changes |
| environment-scan-page-008-120dpi | 12 → 77 | 65 → 6 | 0 → 521 | 753 → 781 | approved editable-text routing/derived changes |
| environment-scan-page-014-120dpi | 12 → 150 | 138 → 0 | 0 → 1362 | 1105 → 1206 | approved editable-text routing/derived changes |
| perspective-sample-plan | 0 → 2 | 2 → 0 | 0 → 27 | 99 → 100 | approved editable-text routing/derived changes |
| warehouse-index-page-001-150dpi | 36 → 89 | 53 → 2 | 0 → 851 | 3 → 5 | approved editable-text routing/derived changes |
| warehouse-index-page-001-300dpi | 35 → 83 | 48 → 0 | 0 → 728 | 151 → 154 | approved editable-text routing/derived changes |
| warehouse-index-page-001-600dpi | 32 → 88 | 56 → 1 | 0 → 960 | 66 → 74 | approved editable-text routing/derived changes |
| warehouse-plan-page-003-72dpi | 36 → 166 | 130 → 1 | 0 → 891 | 730 → 730 | approved editable-text routing/derived changes |
| warehouse-system-page-002-72dpi | 41 → 143 | 102 → 2 | 0 → 888 | 567 → 558 | approved editable-text routing/derived changes |

A → B allows eligible text to become native TEXT, replacement-safe gating to stop blocking TEXT, unsafe source glyphs to remain in SOURCE_TEXT_OUTLINE, additional editable TEXT, and reduced fallback outline. Stable page transform, structural-line metrics, logo and signature protections were required.

## B → C classification

| Configuration | Semantic | Geometry | Non-text | Symbols | Source outline | Protected content | Page transform | Full structure ID |
|---|---|---|---|---|---|---|---|---|
| environment-plan-page-003-150dpi | same | changed | same | same | same | same | same | same |
| environment-scan-page-001-120dpi | same | changed | same | same | same | same | same | same |
| environment-scan-page-002-120dpi | same | changed | same | same | same | same | same | same |
| environment-scan-page-004-120dpi | same | changed | same | same | same | same | same | same |
| environment-scan-page-008-120dpi | same | changed | same | same | same | same | same | same |
| environment-scan-page-014-120dpi | same | changed | same | same | same | same | same | same |
| perspective-sample-plan | same | changed | same | same | same | same | same | same |
| warehouse-index-page-001-150dpi | same | changed | same | same | same | same | same | same |
| warehouse-index-page-001-300dpi | same | changed | same | same | same | same | same | same |
| warehouse-index-page-001-600dpi | same | changed | same | same | same | same | same | same |
| warehouse-plan-page-003-72dpi | same | changed | same | same | same | same | same | same |
| warehouse-system-page-002-72dpi | same | changed | same | same | same | same | same | same |

B → C allows only `text_geometry_hash` changes: height, width factor, rotation, insertion, alignment and predicted visible bounds. `full_structure_id` is recorded but is not an independent equality gate; any change must be attributable to the allowed geometry partition.

## Partition hash contract

- `text_semantic_hash`: candidate ID, OCR text, confidence, eligibility, entity type and semantic layer; must remain equal B → C.
- `text_geometry_hash`: height, width factor, rotation, insertion, alignment and predicted visible bounds; may change B → C.
- `non_text_structure_hash`, `text_symbol_hash`, `source_outline_hash`, `protected_content_hash` and `page_transform_hash`: must remain equal B → C.
- Protected sub-hashes separately cover Logo, signature, residual and uncertain content; all remained equal.
- Input fixture hashes are checked against the B source tree; the phase 12 manifest file is not read from the current working tree as historical input.

Result: A → B passed approved classification; B → C passed all prohibited-partition gates.

## Versioned evidence storage

The Git baseline stores compact page summaries (`schema_version=1`) and a
compact contract manifest (`schema_version=3`). Runtime auditing still reads
the complete A, B, and C reports and DXF entities before writing those
summaries. The summaries retain the partition hashes, protected sub-hashes,
counts, decisions, source anchors, raw-evidence SHA-256, record count, and
regeneration command, but do not store entity vertices, text geometry arrays,
or repeated A/B/C payloads.

The complete raw page evidence and replay inputs are indexed by
`raw-evidence-manifest.json` in the external P1B-R2 recovery package. Each
raw file has an original SHA-256 and deterministic gzip SHA-256; daily
contract validation does not require that external package. Re-running the
documented build command with `--raw-evidence-dir` regenerates the full raw
evidence from the same fixtures and reports.
