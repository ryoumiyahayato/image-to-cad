from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.draftsman_vs1 import run_draftsman_vs1, write_vs1_artifacts  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the shadow-only Draftsman VS1 evidence/logical/CAD-IR package."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-document-id", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--expected-logical-count", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=2)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.replay_runs < 2:
        raise SystemExit("--replay-runs must be at least 2")
    results = tuple(
        run_draftsman_vs1(
            args.source,
            source_document_id=args.source_document_id,
            page_number=args.page,
            expected_logical_entity_count=args.expected_logical_count,
        )
        for _ in range(args.replay_runs)
    )
    replay_identities = tuple(result.replay_identity() for result in results)
    if len(set(replay_identities)) != 1:
        raise SystemExit("VS1 replay identities are not deterministic")
    result = results[0]
    if not result.quality.passed:
        raise SystemExit(f"VS1 quality gate failed: {result.quality.to_dict()}")
    paths = write_vs1_artifacts(
        args.output_dir,
        source_path=args.source,
        result=result,
        replay_identities=replay_identities,
    )
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
