# Git commit sequence

## Preserved baseline

- `6f5f693` is still tagged
  `baseline/phase12-final-acceptance-2026-07-30`.
- The repair branch was created from current HEAD `aa1e7cd`.

## Completed commits

1. `625dcd9 test: record editable-text UAT failure evidence`
2. `6cabd4c test: capture editable-text recovery baseline`
3. `f26a7b8 fix: decouple editable text emission from outline suppression`
4. `dd772f4 test: verify editable text emission decoupling`
5. `185d44b refactor: preserve unsafe source glyphs as hidden text outlines`

## Planned commits

1. `test: verify hidden source glyph outlines`
2. `fix: enforce candidate-level text semantic ownership`
3. `fix: fit native text geometry to OCR bounds`
4. Final validation evidence commit, only after every page passes.

No commit may update a real-regression expected baseline.
