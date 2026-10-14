# DEV source restoration D10

## Outcome

All seven DEV sources identified by D9 were located in the repository-root
worktree's read-only local artifact store. Every file is an exact match for the
checked-in acquisition manifest by SOURCE_GROUP, filename, byte size, SHA-256,
and PDF page count. Each source was copied, not moved, to the identical project
materialization convention under the current `instrumented-e03` worktree:

`local-artifacts/draftsman/corpus-v1/dev/<SOURCE_GROUP>/<SOURCE_GROUP>.pdf`

The restored files are ignored runtime/data artifacts and were not added to Git.
The repository-root worktree, its index, history, and files were not modified.
No source was downloaded, substituted, rendered, OCRed, or inspected visually.

## Search and safety record

1. The current `instrumented-e03` tree contained no copies of the seven exact
   filenames before restoration.
2. The next prescribed location,
   `C:/Users/agcrf/Desktop/image-to-cad/local-artifacts/draftsman/corpus-v1/dev`,
   contained all seven at their recorded prior materialization paths.
3. Because all seven were exact matches at search stage B, no fallback search of
   other linked worktrees, caches, Git history, Git-LFS, or the internet was
   needed. A read-only `git worktree list` confirmed only the root worktree and
   `instrumented-e03` are linked.
4. The checked-in acquisition manifest supplied the authoritative digest, byte
   size, page count, canonical origin, acquisition state, and rights metadata.
5. Restoration targets were resolved beneath
   `C:/Users/agcrf/Desktop/image-to-cad/instrumented-e03` before copying.

VALIDATION and LOCKED_BLIND paths were not searched or accessed. No Git command
was run against the repository-root worktree to reset, repair, checkout, clean,
switch, or otherwise mutate it.

## Exact source identity and restoration inventory

All prior and restored paths below are relative to their respective repository
worktree roots. Status is `EXACT_MATCH_RESTORED` only because every recorded
identity field matched before and after the copy.

| SOURCE_GROUP | Expected file / source identity | Expected bytes | Expected SHA-256 | Pages | Prior materialization path | Restored path | Status |
|---|---|---:|---|---:|---|---|---|
| G0R2-15EE2398726E8037 | `G0R2-15EE2398726E8037.pdf`; Iga municipal tender drawing set 4291000114 | 2,691,152 | `a50f0ff36426ab1829fa0b43ad4fb73e699e6f197e0ef0692ec0da95a8b18350` | 21 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-15EE2398726E8037/G0R2-15EE2398726E8037.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-3B970FD759C6026F | `G0R2-3B970FD759C6026F.pdf`; Yokohama Hiyoshidai temporary-classroom drawing set | 14,915,670 | `ab5ea063a7fec1c6b3761a8839606671d19e75fc7b6319175abff9ad641c3b77` | 133 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-3B970FD759C6026F/G0R2-3B970FD759C6026F.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-4A34D1B8D93B1B06 | `G0R2-4A34D1B8D93B1B06.pdf`; Zhejiang public electrical drawing set 0C1671 | 45,384,584 | `1c3c71e89aedb022482aeefc62f19d47cdf2c0da2dd4b83c234fc1d0d8620b3e` | 79 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-4A34D1B8D93B1B06/G0R2-4A34D1B8D93B1B06.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-6C9464FA73A2A027 | `G0R2-6C9464FA73A2A027.pdf`; Iga municipal drawing set 2020000378 | 3,089,859 | `6c07c50543f4526d2f8481a65364b9e6878f41031dd19bd67c716ff727fe8a12` | 20 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-6C9464FA73A2A027/G0R2-6C9464FA73A2A027.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-7E30C7F445081F40 | `G0R2-7E30C7F445081F40.pdf`; Kingscliff Ambulance Station electrical-services appendix | 5,487,803 | `b4e5dc7fe177e21e276555a470777cd27b6c2dbe1516d4bac43833f43898e199` | 167 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-7E30C7F445081F40/G0R2-7E30C7F445081F40.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-B441E5911528F402 | `G0R2-B441E5911528F402.pdf`; US Library of Congress HABS FL0790 archive master | 16,796,033 | `d5d415ed7e7236a18d8d2a6ba41668216e0f1147436e430999f7dc71c95f691c` | 79 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-B441E5911528F402/G0R2-B441E5911528F402.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |
| G0R2-C2D095E069663C17 | `G0R2-C2D095E069663C17.pdf`; Bradfield City Centre Stage 2A appendix | 3,013,030 | `8cc87c5a2f476a2310abd2ca759e31a3186823e814aa31e73e899a7d425f0cc6` | 6 | `local-artifacts/draftsman/corpus-v1/dev/G0R2-C2D095E069663C17/G0R2-C2D095E069663C17.pdf` | same relative path under `instrumented-e03` | EXACT_MATCH_RESTORED |

## Provenance and data-rights verification

The source-evidence identity above is separate from data-rights status. The
checked-in acquisition records retain these canonical origins:

| SOURCE_GROUP | Canonical acquisition origin | Governance / redistribution status |
|---|---|---|
| G0R2-15EE2398726E8037 | `https://www.city.iga.lg.jp/cmsfiles/contents/0000004/4892/4291000114zume1.pdf` | public municipal tender PDF; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-3B970FD759C6026F | `https://www.city.yokohama.lg.jp/business/nyusatsu/kakukukyoku/2021/chintai/kyoiku/hiyoshidai-kasetsu.files/0019_20210520.pdf` | public municipal PDF; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-4A34D1B8D93B1B06 | `https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3856/site/attach/0/0c16719b50a445edaef10925c7b14c3d.pdf` | public provincial-government storage; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-6C9464FA73A2A027 | `https://www.city.iga.lg.jp/cmsfiles/contents/0000007/7730/2020000378zumen.pdf` | public municipal tender PDF; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-7E30C7F445081F40 | `https://www.planningportal.nsw.gov.au/part-5/review-environmental-factors-kingscliff-ambulance-station` | public approved-project source; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-B441E5911528F402 | `https://tile.loc.gov/storage-services/master/pnp/habshaer/fl/fl0700/fl0790/data/fl0790data.pdf` | public LOC master with HABS/embedded-source advisory; `ARCHIVE_ADVISORY`; `REDISTRIBUTION_RESTRICTED` |
| G0R2-C2D095E069663C17 | `https://www.planningportal.nsw.gov.au/part-5/bradfield-city-centre-stage-2a-civil-works` | public approved-project source; `RIGHTS_UNCLEAR`; `REDISTRIBUTION_RESTRICTED` |

All seven acquisition records say `REUSED_VERIFIED`, are marked
`evaluation_ready: true`, and have materialization state `EVALUATION_READY`.
Their governance states remain `RIGHTS_UNCLEAR` or `ARCHIVE_ADVISORY`, and all
seven are `REDISTRIBUTION_RESTRICTED`. Restoration enables the already recorded
local evaluation use; it does not grant training, commercial, or redistribution
rights beyond the recorded metadata.

## Lightweight sanity check

After restoration, each destination file was independently re-hashed and parsed
with `pdfinfo`. All seven match the manifest digest and byte size, match their
expected page count, parse successfully, and report `Encrypted: no`. No page was
rendered and no reconstruction, OCR, model, or test suite was run.

The current worktree now has seven materialized DEV SOURCE_GROUP directories at
the expected corpus-v1 path. These are precisely the seven D9 recovery targets;
the three earlier D9 source groups remain represented by their checked-in
diagnostic evidence and were outside this restoration scope. Candidate mining may
resume against the seven restored sources in a separate task.

---

DEV_SOURCE_RESTORATION_D10:
COMPLETE

DIAGNOSTIC CHECKPOINT:
661c3a6ce9d6f74c8c96523b12e57fd7a68b1077

PRODUCTION_SEMANTIC_DELTA:
NONE

EXPECTED MISSING DEV SOURCES:
7

EXACTLY IDENTIFIED:
7

EXACT_MATCH LOCATED:
7

RESTORED:
7

PROBABLE_MATCH_NEEDS_REVIEW:
0

NOT_FOUND:
0

CONFLICTING_IDENTITY:
0

CURRENT MATERIALIZED DEV SOURCE_GROUPS:
7

READY TO RESUME DATASET MINING:
YES

NEW PDF ACQUISITION JUSTIFIED:
NO

IF NO, WHY:
All seven missing allocated DEV sources were recovered as exact manifest matches from existing local storage.

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

GIT STATUS:
diagnostic changes
