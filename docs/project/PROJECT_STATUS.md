# Image-to-CAD project status

Last updated: 2026-07-31

## Repository state

- Repository: `ryoumiyahayato/image-to-cad`
- Active branch: `fix/non-destructive-editable-text`
- Task-start HEAD: `7b5592e249aa9146660caec07ce8fa0293cfdb2e`
- Current pull request: [#23](https://github.com/ryoumiyahayato/image-to-cad/pull/23)
- PR state at P0 inspection: open, not draft, not merged, reported mergeable
- PR base: `main`
- PR head before this documentation commit: `7b5592e249aa9146660caec07ce8fa0293cfdb2e`
- PR scope before P0: 18 commits, 434 changed files, 12,444,529 additions, 169 deletions
- GitHub combined-status entries returned at inspection: none. This is not evidence that CI passed.
- Execution workspace: no local checkout was available in this environment. The repository was inspected and updated through the GitHub connector; local dirty/clean status is therefore not applicable. The remote branch HEAD was checked before the atomic documentation write.

## Product definition

The current version is the **non-destructive editable-text safety baseline**. It is not a final release and not a release candidate.

The most recent preserved architecture and safety baseline is:

- Tag: `baseline/phase12-final-acceptance-2026-07-30`
- Commit: `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba`
- Commit title: `perf: complete final acceptance baseline (phase 12)`

The phase-12 commit exists and the existing repository checkpoint records the tag-to-commit mapping. This P0 task does not move, delete, or recreate the tag.

## Confirmed completed capabilities

1. Large numbers of trusted OCR candidates are emitted as native DXF `TEXT`.
2. `replacement_safe` no longer blocks trusted text emission.
3. Unsafe source glyphs can be retained in `SOURCE_TEXT_OUTLINE`.
4. `SOURCE_TEXT_OUTLINE` is default-off and frozen in the user-inspected DXFs.
5. Native Chinese `TEXT` can be edited in LibreCAD.
6. User edits persisted after save, full close, and reopen in two real DXFs.
7. Overall drawing position and scale are broadly correct in inspected samples.
8. Previous large page-crossing erroneous lines are substantially reduced.
9. The current PDF page can be exported independently.
10. Processed PDF pages can be exported as separate files while preserving page numbers.
11. GUI, cache, and export are intended to consume the same `FinalStructure`.

## Confirmed incomplete capabilities

1. Native `TEXT` height, width factor, insertion point, baseline, alignment, and rotation do not pass real LibreCAD UAT.
2. Many text objects are too large, overlap, or extend beyond table cells and borders.
3. Vertical text, 90°/270° text, title-block small text, and dense table text need routing improvements.
4. Some ordinary printed text remains in `TRACE_TEXT_SYMBOL`.
5. Structural lines and damaged frames remain incomplete.
6. Local automatic line repair is safe but has insufficient recovery recall.
7. Formal output and diagnostic-color output are not yet fully separated.
8. Complete per-page human visual acceptance has not been performed.
9. PR #23 is too broad to treat GitHub mergeability as product readiness.

## Current release judgment

**Blocked.** Automated entity and regression checks establish a valuable safety baseline, but real LibreCAD UAT rejects native-text geometry. Automated reports cannot override that observation.

## Current highest priority

**P1: repair native DXF `TEXT` geometry fitting.**

P1 is limited to text geometry and font metrics. It must not change OCR content, OCR thresholds, text eligibility, source-outline contracts, symbol routing, structure lines, line repair, logo/signature logic, PDF export logic, or diagnostic colors.

## P1B implementation state

- P1B start: `5f7846e00b41913c003f178558a110e6475c0ee0`.
- P1B-1 canonical fit commit: `434209f0ef0e405726cfd6d733d62c7ae0ce8f17`.
- P1B-2 path-unification commit and target-branch HEAD: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`.
- P1B-3 validation PR: #28, Draft and unmerged.

Status: **P1B automated validation blocked**.

The full pytest suite passed with 282 tests. The formal real-document gate then failed for 12 document/DPI configurations covering 10 unique source pages. The committed expectations still encode the old `replacement_safe` downgrade behavior, while the approved current contract requires every eligible candidate to remain native editable `TEXT`. This produces systematic expected/observed differences in editable/fallback counts, contour counts, content hashes and `structure_id` values.

P1B-3 is prohibited from restoring the superseded routing, lowering acceptance criteria, modifying production algorithms, or recording replacement baselines. Therefore PR #28 remains Draft, no success validation commit was created, the target branch remains at `80be85aba985e457bc7bff1e9ece49f50e7a46d2`, and the manual LibreCAD UAT package is not released.

The next safe action is a separately authorized real-regression baseline and acceptance-contract reconciliation. It is not P2. P2 has not started.

## Authoritative records

- [Real-world UAT](REAL_WORLD_UAT.md)
- [Roadmap](ROADMAP.md)
- [Decision log](DECISIONS.md)
- [Issue register](ISSUE_REGISTER.md)
- [Acceptance gates](ACCEPTANCE_GATES.md)
- [Agent operating protocol](AGENT_OPERATING_PROTOCOL.md)
- [Current task](CURRENT_TASK.md)
- [Next task](NEXT_TASK.md)
- [Checkpoint](CHECKPOINT.md)
