# INPUT-FIDELITY-D1

This diagnostic traces fixed DEV-space regions through the real production entry
point, `ProductionProcessingService.process_page`. It records the actual arrays
and candidate masks passed between preprocessing, OCR, line detection, filtering,
geometry processing, and canonical `FinalStructure` assembly.

The observer is read-only. A test binds an observed run to the same canonical
structure ID and geometry as an unobserved run. The artifact builder also rejects
any input whose material path is not under `corpus-v1/dev`.

## D1 findings

- A clear thick source stroke enters preprocessing intact. Edge proposal capture
  shows the two sides of that stroke, followed by centered fragments. The first
  visible loss in the selected ROI is the candidate eligibility rule requiring
  `length >= 10 * width`; the later text-like filter removes more.
- A continuous thin rule is missed by the native line channel, but residual
  contour tracing preserves it in `FinalStructure`. This is not an end-to-end
  visual break.
- The original case-3 target annotation at x=1285 was invalidated during the P2
  fix audit: only 54 of 371 target rows have binary foreground within a
  seven-pixel corridor, with a 102-row unsupported gap. The actually continuous
  rule at x=1322/1323 has binary support on 362 of 371 rows and produces twelve
  Hough/LSD candidates. D2 subsequently qualified the complete 518-row target
  at x=1322 and showed that contour fallback does not preserve it in the final
  structure. The invalid x=1285 annotation still cannot justify a detector
  change; the corrected target is tracked separately as D2-001.
- In the selected line-near-text case, text protection removes a duplicate line
  candidate but leaves another source-supported candidate continuous through the
  final structure.
- The selected Chinese label remains clear in the actual OCR input. RapidOCR,
  promotion, and `FinalStructure` all preserve the correct Unicode text. Only the
  VQA raster renderer replaces those CJK glyphs with question marks, so this is a
  render-only defect rather than OCR corruption.

Generated source crops, stage arrays, screenshots, and reports live only under
the Git-ignored `local-artifacts/draftsman/input-fidelity-d1` tree.
