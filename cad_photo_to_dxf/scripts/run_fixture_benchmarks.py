from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.fixture_benchmark import run_fixture_benchmark  # noqa: E402
from app.fixture_validation import validate_fixture_set  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run photographed CAD fixtures and compare generated DXF to ground truth."
    )
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("tests/fixtures"),
    )
    parser.add_argument("--minimum", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("output/fixture-benchmarks"))
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    qualification = validate_fixture_set(
        args.root,
        minimum_required=args.minimum,
    )
    fixture_results = []
    if qualification.passed:
        for fixture in qualification.fixtures:
            if fixture.passed:
                fixture_results.append(
                    run_fixture_benchmark(
                        fixture.fixture_directory,
                        args.output_dir,
                    )
                )

    benchmark_passed = (
        qualification.passed
        and len(fixture_results) >= args.minimum
        and all(result.passed for result in fixture_results)
    )
    report = {
        "passed": benchmark_passed,
        "qualification": qualification.to_dict(),
        "benchmarks": [result.to_dict() for result in fixture_results],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report is None:
        print(output)
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 0 if benchmark_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
