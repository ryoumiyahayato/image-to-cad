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


def verify(*, remote: bool = False) -> dict[str, object]:
    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    tracked = {}
    for row in git("ls-files", "-s").splitlines():
        meta, path = row.split("\t", 1)
        mode, sha, stage = meta.split()
        if stage != "0":
            failures.append(f"unmerged index: {path}")
        tracked[path] = (mode, sha)
    for item in record["deleted_files"]:
        path = item["path"]
        if path in tracked or (ROOT / path).exists():
            failures.append(f"removed file remains: {path}")
        kept = item.get("retained_identical_path")
        if kept and git("hash-object", "--", kept) != item["blob_sha"]:
            failures.append(f"retained duplicate changed: {kept}")
    for item in record["protected_files"]:
        path = item["path"]
        if tracked.get(path) != (item["mode"], item["blob_sha"]):
            failures.append(f"protected index changed: {path}")
        if not (ROOT / path).is_file() or git("hash-object", "--", path) != item["blob_sha"]:
            failures.append(f"protected working file changed: {path}")
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
        for item in record["after_snapshot"]["branches"]:
            if item["name"] == record["working_branch"]:
                continue  # This branch advances with the reviewed cleanup commits.
            if refs.get(f"refs/heads/{item['name']}") != item["sha"]:
                failures.append(f"retained remote head changed: {item['name']}")
        for item in record["retained_original_tags"]:
            if refs.get(item["ref"]) != item["sha"]:
                failures.append(f"original archive tag changed: {item['ref']}")
        remote_counts = {
            "branches": sum(r.startswith("refs/heads/") for r in refs),
            "original_tags_unchanged": len(record["retained_original_tags"]),
        }
    return {
        "contract": record["schema"], "passed": not failures,
        "removed_files": len(record["deleted_files"]), "removed_bytes": record["deleted_file_bytes"],
        "protected_files_unchanged": len(record["protected_files"]) if not failures else None,
        "deleted_branches_recoverable": len(record["deleted_branches"]),
        "remote": remote_counts, "failures": failures,
        "scope": "repository preservation only; product remains LOCAL_NO_GO",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="Also read and check current origin refs")
    args = parser.parse_args()
    report = verify(remote=args.remote)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
