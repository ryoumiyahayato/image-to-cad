from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.fixture_validation import (  # noqa: E402
    REQUIRED_FREECAD_VERSION,
    validate_fixture_set,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate real-photo CAD fixture provenance and ground truth."
    )
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("tests/fixtures"),
    )
    parser.add_argument("--minimum", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--freecad-version",
        default=REQUIRED_FREECAD_VERSION,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = validate_fixture_set(
        args.root,
        minimum_required=args.minimum,
        required_freecad_version=args.freecad_version,
    )
    output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
