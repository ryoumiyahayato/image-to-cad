#!/usr/bin/env bash
set -euo pipefail

CONFIRMATION_PHRASE="REWRITE_IMAGE_TO_CAD_HISTORY"

if [[ "${HISTORY_REWRITE_CONFIRM:-}" != "$CONFIRMATION_PHRASE" ]]; then
  cat >&2 <<EOF
Refusing to rewrite history.
Set HISTORY_REWRITE_CONFIRM=$CONFIRMATION_PHRASE only inside an approved mirror clone.
EOF
  exit 2
fi

if [[ "$(git rev-parse --is-bare-repository)" != "true" ]]; then
  echo "Run this script only in a fresh --mirror clone, not a working tree." >&2
  exit 2
fi

if [[ -z "${VERIFIED_BACKUP_BUNDLE:-}" || ! -f "$VERIFIED_BACKUP_BUNDLE" ]]; then
  echo "VERIFIED_BACKUP_BUNDLE must point to an existing verified backup bundle." >&2
  exit 2
fi

if ! command -v git-filter-repo >/dev/null 2>&1 && ! git filter-repo --help >/dev/null 2>&1; then
  echo "git-filter-repo is required." >&2
  exit 2
fi

report_dir="${HISTORY_CLEANUP_REPORT_DIR:-../history-cleanup-report}"
mkdir -p "$report_dir"

{
  echo "repository=$(pwd)"
  echo "started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "backup_bundle=$VERIFIED_BACKUP_BUNDLE"
  echo "backup_sha256=$(sha256sum "$VERIFIED_BACKUP_BUNDLE" | awk '{print $1}')"
  echo "head_refs_before=$(git for-each-ref --format='%(refname) %(objectname)' | wc -l)"
  git count-objects -vH
} | tee "$report_dir/before.txt"

git for-each-ref --format='%(refname) %(objectname)' > "$report_dir/refs-before.txt"
git bundle verify "$VERIFIED_BACKUP_BUNDLE" |& tee "$report_dir/backup-verify.txt"

filter_args=(
  --force
  --invert-paths
  --path cad_photo_to_dxf/dist
  --path cad_photo_to_dxf/build
  --path cad_photo_to_dxf/output
  --path cad_photo_to_dxf/installer/output
  --path cad_photo_to_dxf/__pycache__
  --path cad_photo_to_dxf/app/__pycache__
  --path output.dxf
  --path cad_photo_to_dxf/version_info.txt
  --path-glob '*.pyc'
)

if command -v git-filter-repo >/dev/null 2>&1; then
  git-filter-repo "${filter_args[@]}"
else
  git filter-repo "${filter_args[@]}"
fi

for forbidden in \
  'cad_photo_to_dxf/dist/' \
  'cad_photo_to_dxf/build/' \
  'cad_photo_to_dxf/output/' \
  'cad_photo_to_dxf/installer/output/' \
  '__pycache__/' \
  '.pyc' \
  'output.dxf' \
  'cad_photo_to_dxf/version_info.txt'; do
  if git rev-list --objects --all | grep -F "$forbidden" > "$report_dir/forbidden-match.txt"; then
    echo "Forbidden historical path remains: $forbidden" >&2
    exit 1
  fi
done
rm -f "$report_dir/forbidden-match.txt"

git fsck --full --strict |& tee "$report_dir/fsck.txt"
git for-each-ref --format='%(refname) %(objectname)' > "$report_dir/refs-after.txt"

{
  echo "completed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "head_refs_after=$(git for-each-ref --format='%(refname) %(objectname)' | wc -l)"
  git count-objects -vH
} | tee "$report_dir/after.txt"

cat <<EOF
History rewrite completed locally and has NOT been pushed.
Review $report_dir, compare intended tags/branches, verify source builds, then follow maintenance/HISTORY_CLEANUP.md during the announced maintenance window.
EOF
