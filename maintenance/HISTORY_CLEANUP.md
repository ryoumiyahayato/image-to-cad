# Historical artifact cleanup procedure

This procedure rewrites every affected commit, branch and tag. It is intentionally separate from the audit-remediation pull request and must not be run casually.

## Preconditions

All items must be recorded in issue #10 before execution:

1. Merge and verify the clean-tree remediation.
2. Announce a merge and tag freeze.
3. Record every collaborator who must reclone afterward.
4. Export legitimate GitHub Release assets and their SHA-256 hashes outside Git history.
5. Create a fresh mirror clone and a full backup bundle.
6. Verify the backup bundle before filtering.
7. Review the exact removal paths in `maintenance/history_cleanup.sh`.
8. Record repository size and all refs before the rewrite.

## Prepare an isolated mirror and backup

```bash
git clone --mirror git@github.com:ryoumiyahayato/image-to-cad.git image-to-cad-cleanup.git
cd image-to-cad-cleanup.git
git bundle create ../image-to-cad-before-filter.bundle --all
git bundle verify ../image-to-cad-before-filter.bundle
sha256sum ../image-to-cad-before-filter.bundle > ../image-to-cad-before-filter.bundle.sha256
```

Copy the bundle and checksum to storage that is independent from the repository and verify the copied checksum.

## Run the guarded local rewrite

Install `git-filter-repo`, then run:

```bash
export VERIFIED_BACKUP_BUNDLE="$(pwd)/../image-to-cad-before-filter.bundle"
export HISTORY_REWRITE_CONFIRM=REWRITE_IMAGE_TO_CAD_HISTORY
bash ../working-copy/maintenance/history_cleanup.sh
```

The script:

- refuses to run in a normal working tree;
- refuses to run without the exact confirmation phrase;
- refuses to run without an existing verified backup bundle;
- removes the approved generated paths from all refs;
- checks that the forbidden paths no longer occur in any rewritten object list;
- runs strict `git fsck`;
- records refs and object sizes before and after;
- does not push anything.

## Verify before any remote update

From a fresh non-bare clone of the rewritten mirror:

```bash
git clone image-to-cad-cleanup.git verification-clone
cd verification-clone
python -m pip install -r cad_photo_to_dxf/requirements.txt "pytest>=8,<9" "ruff>=0.9,<1"
cd cad_photo_to_dxf
python -m pytest -q
python -m compileall -q app scripts main.py
python -m ruff check .
python scripts/check_repository_hygiene.py ..
```

Also verify:

- intended branches and tags still exist;
- application version and release provenance remain coherent;
- a Windows build and installer smoke test pass from the rewritten commit;
- fixed-version FreeCAD import evidence passes;
- GitHub Release assets remain available outside rewritten Git objects.

## Remote maintenance window

Only after the recorded review and approval:

1. Disable merges and tag creation.
2. Inform collaborators that old commit IDs will become obsolete.
3. Force-update only the approved rewritten branches and tags.
4. Re-enable protection and required checks.
5. Create a fresh clone from GitHub and repeat source, Windows and FreeCAD verification.
6. Record repository size after GitHub garbage collection has had time to run.
7. Require every collaborator and deployment environment to reclone; do not merge old clones back into the rewritten history.

No automated workflow in this repository performs the force-push. The final remote update remains an explicit maintenance action because accidental execution would invalidate all existing clones and commit references.
