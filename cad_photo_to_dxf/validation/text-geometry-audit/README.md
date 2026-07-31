# P1A native DXF TEXT geometry read-only audit

Audit base: `242d7a487f5936477a90c63c478492d42d73b6c7`; branch `fix/non-destructive-editable-text`. Production code, tests, thresholds and baselines were not changed.

## Pages

- `environment-scan-page-001-120dpi` — low-quality scan.
- `environment-plan-page-003-150dpi` — dense title/table page.
- `warehouse-system-page-002-72dpi` — clear digital PDF.

| Page | TEXT | clamped | median width ratio | P90 | max | boundary crossings | rotations |
|---|---:|---:|---:|---:|---:|---:|---|
| `environment-scan-page-001-120dpi` | 139 | 120 | 1.312 | 2.928 | 8.092 | 33 | {'0': 138, 'arbitrary': 1} |
| `environment-plan-page-003-150dpi` | 154 | 129 | 1.309 | 4.026 | 7.439 | 41 | {'0': 153, 'arbitrary': 1} |
| `warehouse-system-page-002-72dpi` | 143 | 97 | 1.384 | 1.969 | 3.835 | 20 | {'0': 143} |

Overall: 436 TEXT, 346 width-factor clamps and 94 predicted extra boundary crossings. Height ratio is effectively 1.0.

## Findings

1. Oversize, overlap and table overflow share one first cause: `_MIN_READABLE_WIDTH_FACTOR = 0.72`; narrow targets need smaller raw factors but output is centered at 0.72.
2. SOURCE_TEXT_OUTLINE is not used for formal TEXT size.
3. Canonical height has no fixed 0.78/0.82 coefficient; legacy creators still use 0.82 and 0.85.
4. Current single and batch FinalStructure export share `add_ocr_outline_blocks`; three TEXT creators exist in the repository.
5. Program metrics and DXF STYLE target the same bundled `wqy-unicode.lff`; live user-machine resolution is not observable here.
6. Automation missed the defect because a test explicitly expects rendered width to exceed target below 0.72, and GUI preview does not render native DXF TEXT geometry.
7. No native 90°/270° sample exists in the current 12-DXF evidence; vertical routing/orientation remains unverified.
8. Eligible TEXT count can remain unchanged in P1B.

## Limitations

The current CI artifact omits source rasters, so panel 1 is explicitly a derived proxy. Exact original OCR bbox/quad is not persisted in final DXF; CSV/JSON reconstructs it from target XDATA and transform.

See `code-paths.md`, `font-metrics.md`, `review-samples.md`, `failure-categories.json` and `p1b-recommendation.md`. No P1B change was made.
