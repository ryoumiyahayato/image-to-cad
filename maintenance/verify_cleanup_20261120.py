"""Read-only verification of the 2026-11-20 deletion and recovery contract.

This checks repository preservation, not product recognition quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/project/cleanup_20261120/manifest.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def tree_at(commit: str) -> dict[str, tuple[str, str]]:
    result = {}
    for row in git("ls-tree", "-r", commit).splitlines():
        meta, path = row.split("\t", 1)
        mode, _, sha = meta.split()
        result[path] = (mode, sha)
    return result


def recoverable_refs(sha: str, refs: dict[str, str]) -> list[str]:
    """Find advertised refs containing a historical commit, without moving refs."""
    found = []
    for ref, head in refs.items():
        if ref.endswith("^{}"):
            continue
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, head], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            found.append(ref)
    return sorted(found)


def verify(*, remote: bool = False, strict_current: bool = False) -> dict[str, object]:
    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    current_changes: list[dict[str, str]] = []
    historical = tree_at(record["source_commit"])
    tracked = {}
    for row in git("ls-files", "-s").splitlines():
        meta, path = row.split("\t", 1)
        mode, sha, stage = meta.split()
        if stage != "0":
            failures.append(f"unmerged index: {path}")
        tracked[path] = (mode, sha)
    for item in record["deleted_files"]:
        path = item["path"]
        if historical.get(path) != (item["mode"], item["blob_sha"]):
            failures.append(f"deleted-file historical recovery changed: {path}")
        if path in tracked or (ROOT / path).exists():
            current_changes.append({"path": path, "change": "historically_removed_path_present_now"})
            if strict_current:
                failures.append(f"removed file remains in strict cleanup tree: {path}")
        kept = item.get("retained_identical_path")
        if kept and historical.get(kept, (None, None))[1] != item["blob_sha"]:
            failures.append(f"historical retained duplicate changed: {kept}")
        if kept and strict_current and git("hash-object", "--", kept) != item["blob_sha"]:
            failures.append(f"strict current retained duplicate changed: {kept}")
    for item in record["protected_files"]:
        path = item["path"]
        expected = (item["mode"], item["blob_sha"])
        if historical.get(path) != expected:
            failures.append(f"protected historical snapshot changed: {path}")
        changed = tracked.get(path) != expected or not (ROOT / path).is_file()
        if not changed:
            changed = git("hash-object", "--", path) != item["blob_sha"]
        if changed:
            current_changes.append({"path": path, "change": "current_tree_differs_from_historical_baseline"})
            if strict_current:
                failures.append(f"protected current file changed in strict cleanup mode: {path}")
    summary = json.dumps(record["protected_files"], sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(summary.encode()).hexdigest() != record["protected_manifest_sha256"]:
        failures.append("protected-file ledger digest mismatch")
    for item in record["deleted_branches"]:
        ancestor = git("merge-base", item["sha"], item["recovery_sha"])
        if ancestor != item["sha"]:
            failures.append(f"recovery does not contain ancestor: {item['name']}")
        if git("rev-list", "--count", f"{item['recovery_sha']}..{item['sha']}") != "0":
            failures.append(f"unpreserved unique commits: {item['name']}")
    for path, (mode, _) in tracked.items():
        if mode not in {"100644", "100755"}:
            failures.append(f"unexpected tracked permission/type: {path} {mode}")
        if mode == "100755" and path != "maintenance/history_cleanup.sh":
            failures.append(f"new executable needs review: {path}")
    remote_counts = None
    if remote:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", "origin"], cwd=ROOT,
            text=True, capture_output=True, timeout=45, check=True,
        )
        refs = {ref: sha for sha, ref in (line.split() for line in result.stdout.splitlines())}
        for item in record["deleted_branches"]:
            if f"refs/heads/{item['name']}" in refs:
                failures.append(f"remote deletion not present: {item['name']}")
        recovery = []
        for item in record["after_snapshot"]["branches"]:
            reachable = recoverable_refs(item["sha"], refs)
            recovery.append({"historical_branch": item["name"], "historical_sha": item["sha"],
                             "currently_recoverable_from": reachable})
            if not reachable:
                failures.append(f"historical commit not reachable from fetched current remote refs: {item['name']}")
        if not recoverable_refs(record["source_commit"], refs):
            failures.append("historical file recovery commit has no current remote ref")
        for item in record["retained_original_tags"]:
            if refs.get(item["ref"]) != item["sha"]:
                failures.append(f"original archive tag changed: {item['ref']}")
        remote_counts = {
            "branches": sum(r.startswith("refs/heads/") for r in refs),
            "original_tags_unchanged": len(record["retained_original_tags"]),
            "historical_branch_recovery": recovery,
        }
    return {
        "contract": record["schema"], "passed": not failures,
        "removed_files": len(record["deleted_files"]), "removed_bytes": record["deleted_file_bytes"],
        "historical_protected_files_verified": len(record["protected_files"]) if not failures else None,
        "strict_current_cleanup_mode": strict_current,
        "current_tree_changes_not_historical_data_loss": current_changes,
        "deleted_branches_recoverable": len(record["deleted_branches"]),
        "remote": remote_counts, "failures": failures,
        "scope": "repository preservation only; product remains LOCAL_NO_GO",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="Also read and check current origin refs")
    parser.add_argument("--strict-current", action="store_true",
                        help="Additionally require this cleanup tree to preserve all baseline file bytes")
    args = parser.parse_args()
    report = verify(remote=args.remote, strict_current=args.strict_current)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
