# Code-only recovery checkpoint: PANTRY + WALL (2026-11-21)

**Purpose:** preserve two completed, independently scoped local edit/checkpoint tasks in GitHub without interrupting the ongoing `development/native-reconstruction` branch or changing `main`. **Not a release or product acceptance.**

## Provenance

- Recovery branch started at `db4be74c0b9fc80813a8428645f6c172c40c3dec` (development branch history, which includes effective common source/ownership implementation `c73d03f03599ee26ef8d53fc229a3fbaa84b3318`).
- Original local-only PANTRY tool commit: `85b13d99ca45fd64a8cf95c505ef55a138e99b83`; parent `c73d03f`.
- Original local-only WALL tool commit: `e69c92cf213aa3169e0933445a7c0f5c216175a1`; parent `85b13d99`.
- The two **original Git commit objects** are not claimed to exist on remote. This branch preserves their source-only additions as new commits; it does **not** reproduce their commit IDs or pretend they were cherry-picked into the active PR.

## Exact uploaded files

| Repository source path | SHA-256 | Exact Git blob |
|---|---|---|
| `cad_photo_to_dxf/scripts/export_text_checkpoint.py` | `92d29766aa6582c5c34442d128259ebf6253bdbe5703b2f262a0e6304a62622b` | `f4a4c3ebe9a061c90553f339c17d7bdbebf23320` |
| `cad_photo_to_dxf/scripts/export_wall_checkpoint.py` | `4154782365cfa47d3449914ed2eea6b7bc4c47d172a9ef0c8a12e67dd9cef9ee` | `1c7451f6491e71507acc8302a84790357efc5eb1` |
| `cad_photo_to_dxf/scripts/audit_wall_source_residue.py` | `f508bef8327a723737daa6d84b7909fcfb8711d0689b0f2f7663159bf599981e` | `b83c140ff26a8541d6de9902c171210c8122daf0` |

Each source file was read back from GitHub and matched to the actual archived source blob. The general PANTRY domain-repair and wall-grouping modules were already represented by the `c73d03f` history; these three newly added scripts are **checkpoint exporters and read-only source auditors, not additional recognition algorithms**. The existing relevant regression test files are already present in the active development history; they were not duplicated.

## Actual saved local evidence (private Library, not copied into this public repository)

PANTRY:
- `pantry_local_fixed.dxf`, SHA-256 `7199b3dfc3f5e8e6ddbe945185fe7a9d32cceb2763dd5d49686c5837034ea270`.
- 1 native TEXT = PANTRY, 3 LINE, 2 INSERT. Prior domain-repair provenance retained. No new OCR or GUI test in the final local task.

WALL `WALL-dc6587fce5c0`:
- `wall_local_restored.dxf` SHA-256 `06cc510f0eaf680282d2e349a4cd64fb00675986c8bce7a3e95ee7edfb003f44`.
- `wall_local_moved.dxf` SHA-256 `c36f24d45033311232c1a544ac74990731ae2fc42706398125afa59b474dc98b`.
- `wall_local_deleted.dxf` SHA-256 `cf5227bc9c694ae7065c59591ff0b4ff028d0878317305c9bebf48e501dc6c08`.
- Two owned long wall edges; full target INSERT moves by [+12,+8,0] paper mm, or is deleted. Twelve local neighbor objects remain unchanged. All three actual files passed separate-process DXF cold-read (0 audit errors, 0 repairs). Near-source independent prefixes and neighboring wall unresolved ownership were preserved.
- Historical original candidate order / cited `wall_candidate_path_diagnosis.json` are unavailable. Static de-duplication geometry supports a conditional explanation, **not** a historical runtime replay.

## Usage and boundary

These scripts need a verified compatible checkpoint/source ledger and applicable runtime dependencies to reproduce the *local* experiments. No scan, OCR input, model binary, private source, screenshot, actual output DXF, font file, or credential is distributed here. This branch has no newly passed GUI or engineer-time acceptance.

Do not merge into `main` as a product-ready result. Later integrate into the active development PR only after checking current HEAD/dependencies and running focused regression; retain this branch as an offline recovery point until integrated. Then verify the destination commit and retire this redundant branch.

Status: **PANTRY_LOCAL_PASS / WALL_LOCAL_SCRIPT_EDIT_PASS**, overall **LOCAL_NO_GO**. No full-region conversion or actual engineering adoption proven by this checkpoint.
