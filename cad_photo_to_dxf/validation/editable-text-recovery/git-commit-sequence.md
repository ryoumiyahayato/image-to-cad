# Git commit sequence

## Preserved baseline

- `6f5f693` is still tagged
  `baseline/phase12-final-acceptance-2026-07-30`.
- The repair branch was created from current HEAD `aa1e7cd`.

## Completed commits

1. `625dcd9 test: record editable-text UAT failure evidence`
2. `6cabd4c test: capture editable-text recovery baseline`
3. `f26a7b8 fix: decouple editable text emission from outline suppression`

## Planned commits

1. `test: verify editable text emission decoupling`
2. `refactor: preserve unsafe source glyphs as hidden text outlines`
3. `fix: enforce candidate-level text semantic ownership`
4. `fix: fit native text geometry to OCR bounds`
5. Final validation evidence commit, only after every page passes.

No commit may update a real-regression expected baseline.
