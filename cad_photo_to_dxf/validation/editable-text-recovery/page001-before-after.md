# page-001 before/after

## Fixed 240-DPI failure

| Metric | Phase 12 before | Current |
|---|---:|---:|
| OCR candidates | 208 | 208 |
| text_emit_eligible | not recorded separately | 206 |
| Native DXF TEXT | 37 | 206 |
| replacement-unsafe source candidates | 169 | 169 hidden backups |
| Visible uncertain candidates | 169 | 2 |
| Residual OCR candidates | 2 | 0 |
| Eligible candidates in TRACE_TEXT_SYMBOL | not candidate-audited | 0 |
| Candidate semantic conflicts | not candidate-audited | 0 |
| Duplicate visible representations | not candidate-audited | 0 |
| DXF audit errors | 0 | 0 |

Every one of the 206 eligible candidates emits
exactly one native `TEXT`. The 169
unsafe source glyphs are retained only on the default-hidden and frozen
`SOURCE_TEXT_OUTLINE` layer.

## Candidates without native TEXT

- `ocr-048`: `confidence_below_contract` — `3`
- `ocr-083`: `confidence_below_contract` — `③`

Both candidates are hard-rejected only by the unchanged
`confidence_below_contract` rule. No candidate is rejected for replacement
safety, connected-component extent, nearby ink, or incomplete ownership.

## Same-DPI comparison with d9fbda7

The historical saved DXF at `d9fbda7` is a 300-DPI run, so
it is compared with the current 300-DPI run rather than with the 240-DPI fixed
failure sample.

| Metric | d9fbda7 300 DPI | Current 300 DPI |
|---|---:|---:|
| Native DXF TEXT | 214 | 219 |
| TRACE_STRAIGHT | 986 | 651 |
| DXF audit errors | 0 | 0 |

Current editable TEXT count is not lower (219 >=
214), while the old whole-page line
overproduction is not restored (651 <
986).
