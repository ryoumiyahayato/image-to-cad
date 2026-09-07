from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_family_audit import FamilyAuditReference  # noqa: E402
from app.draftsman_vs3_u1 import (  # noqa: E402
    audit_draftsman_vs3_u1_family,
    write_draftsman_vs3_u1_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the shadow-only VS3-U1 replay")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=2)
    args = parser.parse_args()
    if args.replay_runs < 2:
        raise SystemExit("--replay-runs must be at least 2")
    reference = FamilyAuditReference.load(args.reference)
    audits = tuple(
        audit_draftsman_vs3_u1_family(args.source, reference=reference)
        for _ in range(args.replay_runs)
    )
    if len({item.audit_id for item in audits}) != 1:
        raise SystemExit("VS3-U1 replay is not deterministic")
    paths = write_draftsman_vs3_u1_artifacts(
        args.output_dir,
        source=args.source,
        audit=audits[0],
        replay_audit_ids=tuple(item.audit_id for item in audits),
    )
    print(dict(audits[0].summary))
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
