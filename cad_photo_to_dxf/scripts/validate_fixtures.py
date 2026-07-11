from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.fixture_benchmark import run_fixture_benchmark  # noqa: E402
from app.fixture_validation import (  # noqa: E402
    REQUIRED_FREECAD_VERSION,
    validate_fixture_set,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate real-photo CAD fixture provenance and ground truth. "
            "When --minimum is greater than zero, qualifying fixtures are also "
            "processed and compared with their ground-truth DXF files."
        )
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
        "--benchmark-output-dir",
        type=Path,
        default=Path("output/fixture-benchmarks"),
    )
    parser.add_argument(
        "--freecad-version",
        default=REQUIRED_FREECAD_VERSION,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    qualification = validate_fixture_set(
        args.root,
        minimum_required=args.minimum,
        required_freecad_version=args.freecad_version,
    )

    benchmarks = []
    if args.minimum > 0 and qualification.passed:
        for fixture in qualification.fixtures:
            if fixture.passed:
                benchmarks.append(
                    run_fixture_benchmark(
                        fixture.fixture_directory,
                        args.benchmark_output_dir,
                    )
                )

    benchmark_required = args.minimum > 0
    benchmark_passed = (
        not benchmark_required
        or (
            len(benchmarks) >= args.minimum
            and all(result.passed for result in benchmarks)
        )
    )
    passed = qualification.passed and benchmark_passed
    report = qualification.to_dict()
    report["benchmark_required"] = benchmark_required
    report["benchmark_passed"] = benchmark_passed
    report["benchmarks"] = [result.to_dict() for result in benchmarks]
    report["passed"] = passed

    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
