from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Iterable


GENERATED_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".agents",
    "build",
    "dist",
}
GENERATED_DIRECTORY_PREFIXES = {
    "output",
    "installer/output",
    "packaging/output",
    "test-output",
    "validation-diagnostics",
}
GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".dxf",
}
GENERATED_FILENAMES = {
    "preview.png",
}
ALLOWED_GENERATED_PREFIXES = {
    "tests/fixtures/expected",
    "tests/fixtures/ground_truth",
}


@dataclass(frozen=True)
class HygieneFinding:
    path: str
    reason: str
    size_bytes: int


def _tracked_files(repository_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def _is_under(path: PurePosixPath, prefix: str) -> bool:
    parts = PurePosixPath(prefix).parts
    return path.parts[: len(parts)] == parts


def inspect_tracked_files(
    repository_root: Path,
    tracked_files: Iterable[str],
    *,
    maximum_file_size_bytes: int = 20 * 1024 * 1024,
) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    for raw_path in tracked_files:
        normalized = raw_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        absolute = repository_root / Path(*relative.parts)
        size = absolute.stat().st_size if absolute.is_file() else 0

        if any(_is_under(relative, prefix) for prefix in ALLOWED_GENERATED_PREFIXES):
            if size > maximum_file_size_bytes:
                findings.append(
                    HygieneFinding(
                        normalized,
                        "allowed fixture exceeds tracked-file size limit",
                        size,
                    )
                )
            continue

        reason: str | None = None
        if any(part in GENERATED_DIRECTORY_NAMES for part in relative.parts):
            reason = "generated or local-only directory is tracked"
        elif any(_is_under(relative, prefix) for prefix in GENERATED_DIRECTORY_PREFIXES):
            reason = "generated output directory is tracked"
        elif relative.suffix.lower() in GENERATED_SUFFIXES:
            reason = "generated output file is tracked"
        elif relative.name.lower() in GENERATED_FILENAMES:
            reason = "generated preview file is tracked"
        elif relative.name.endswith(".report.json"):
            reason = "generated processing report is tracked"
        elif size > maximum_file_size_bytes:
            reason = "tracked file exceeds repository size limit"

        if reason is not None:
            findings.append(HygieneFinding(normalized, reason, size))

    return sorted(findings, key=lambda item: (item.reason, item.path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail when generated artifacts or unexpectedly large files are tracked."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--maximum-file-size-mib",
        type=float,
        default=20.0,
    )
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.repository_root.resolve()
    maximum = int(args.maximum_file_size_mib * 1024 * 1024)
    if maximum <= 0:
        raise SystemExit("Maximum file size must be greater than zero")

    findings = inspect_tracked_files(
        root,
        _tracked_files(root),
        maximum_file_size_bytes=maximum,
    )
    payload = {
        "repository_root": str(root),
        "maximum_file_size_bytes": maximum,
        "finding_count": len(findings),
        "passed": not findings,
        "findings": [asdict(item) for item in findings],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
