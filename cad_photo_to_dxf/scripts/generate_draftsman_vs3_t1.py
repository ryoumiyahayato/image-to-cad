from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import FamilyAuditReference  # noqa: E402
from app.draftsman_vs3_t1 import (  # noqa: E402
    audit_draftsman_vs3_t1_family,
    write_draftsman_vs3_t1_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the shadow-only VS3-T1 family replay."
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
    audits = tuple(
        audit_draftsman_vs3_t1_family(args.source, reference=reference)
        for _ in range(args.replay_runs)
    )
    audit_ids = tuple(item.audit_id for item in audits)
    if len(set(audit_ids)) != 1:
        raise SystemExit("VS3-T1 family replay is not deterministic")
    paths = write_draftsman_vs3_t1_artifacts(
        args.output_dir,
        audit=audits[0],
        replay_audit_ids=audit_ids,
    )
    print(audits[0].summary)
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
