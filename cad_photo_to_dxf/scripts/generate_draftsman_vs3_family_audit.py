from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import (  # noqa: E402
    FamilyAuditReference,
    audit_electrical_family,
    write_family_audit_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen VS3 rule against its full reference family."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=2)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.replay_runs < 2:
        raise SystemExit("--replay-runs must be at least 2")
    reference = FamilyAuditReference.load(args.reference)
    results = tuple(
        audit_electrical_family(args.source, reference=reference)
        for _ in range(args.replay_runs)
    )
    audit_ids = tuple(item.audit_id for item in results)
    if len(set(audit_ids)) != 1:
        raise SystemExit("Family audit replay is not deterministic")
    result = results[0]
    paths = write_family_audit_artifacts(
        args.output_dir,
        source_path=args.source,
        result=result,
        replay_audit_ids=audit_ids,
    )
    print(result.summary.to_dict())
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
