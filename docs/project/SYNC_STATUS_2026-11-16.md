# Image-to-CAD — GitHub sync discrepancy and verified progress (2026-11-16)

**Current state: PARTIAL RECOVERY / GITHUB SOURCE NOT YET SYNCHRONIZED.**

## Actual GitHub state before this recovery

- Repository: `ryoumiyahayato/image-to-cad` (public).
- `main` tip: `81f364fbe4eee1df00dadefabaef0d1a72993e6e`, dated 2026-10-25.
- The four existing `delivery/w02-*` branch tips are also dated 2026-10-25.
- No release was found. Neither the recorded local `main` commit `aa8ee258069943751d6433fd808a934e754b76f1` nor the recorded `2376479dd5142850c64fe24ca7b3316450aa51e3` freeze commit was found on this remote.

## Source material recovered from connected cloud archive

- 2026-11-13: complete *workset ZIP* was located and reconstructed locally (239,528,356 bytes; 1,901 ZIP members). This workset is a recovery reference and was **not** pushed as source code.
- 2026-11-13 through 2026-11-15: Git bundles for online-r2 through online-r9 located; nine archive files including r12 are stored under `recovery/2026-11-16/git-bundles/` on this branch.
- 2026-11-15 r11: the owner's local acceptance note reports the 207 text and four-vertex border separately editable in LibreCAD and a successful cold re-open. Bundle head `0255b355e2378d6050bf7e4498d0e39d92c47cfa` located inside the r11 acceptance ZIP. Original full source chain remains unverified.
- 2026-11-16 r12: recovered bundle tip `92b71cf62902668f14d56b1d8447782a672e7962` from parent `0255b355e2378d6050bf7e4498d0e39d92c47cfa`. Associated private receipt reports 69/69 file byte-size and SHA-256 checks and 22/22 cloud delivery checks, with four updated/added source/test/docs files. Local OCR, LibreCAD, and full-page regression testing were **not** performed for r12.

## Known product defects from the latest supplied UAT analysis

- Clean W01 frame lines can be duplicated and show 1–3-pixel gaps; this is a FinalStructure/DXF issue, not merely export scaling.
- `1` can be recognized as `7` in editable TEXT even at high model confidence; this is a content-level error.
- Some logos/signatures or engineering-symbol boundaries are omitted, recast as printed text, or lose source relationships.
- Source-overlaid Preview is not a reliable representation of the final DXF (some missing/wrong objects remain visible in Preview).
- Five analyzed pages produced valid DXF and allowed limited primitive edits, but this does not satisfy the product's 'minimal post-conversion correction' objective.

## What this commit does / does NOT do

- DOES: store checked bundle files and explicit recovery/sync status on an isolated branch.
- DOES NOT: push the full 2026-11-16 Windows working tree; merge experiments into `main`; assert that GitHub now matches local; silently replace product code; or run regression/GUI tests.

## Required follow-through

1. Restore the authoritative local Windows Git repository and `git status` with worktrees, uncommitted changes, and untracked files.
2. Recover the post-2026-10-25 ancestry through r10/r11, compare the restored trees and source snapshots, then publish the original commit refs to protected/isolated GitHub branches.
3. Verify remote commit SHAs, file hashes, dependencies and CAD acceptance evidence before presenting a merged `main` as the latest version.
4. Continue targeted product fixes rather than resetting architecture or declaring UAT passed.

`main` and existing delivery branches were intentionally not changed by this recovery note.