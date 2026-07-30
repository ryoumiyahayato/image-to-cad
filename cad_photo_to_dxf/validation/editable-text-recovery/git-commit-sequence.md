# Git commit sequence

## Preserved baseline

- `6f5f693` is still tagged
  `baseline/phase12-final-acceptance-2026-07-30`.
- The repair branch was created from current HEAD `aa1e7cd`.

## Completed commits

1. `625dcd9 test: record editable-text UAT failure evidence`

## Planned commits

1. `test: capture editable-text recovery baseline`
2. `fix: decouple editable text emission from outline suppression`
3. `refactor: preserve unsafe source glyphs as hidden text outlines`
4. `fix: enforce candidate-level text semantic ownership`
5. `fix: fit native text geometry to OCR bounds`
6. Final validation evidence commit, only after every page passes.

No commit may update a real-regression expected baseline.
