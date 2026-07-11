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


REQUIRED_VECTOR_CATEGORIES = {
    "flat_scan",
    "mild_perspective",
    "severe_perspective",
    "blur_shadow_fold",
    "hidden_paper_edge",
    "multi_resolution",
    "portrait_landscape",
    "mixed_geometry",
    "original_cad_dimensions",
}
REQUIRED_REJECTION_CATEGORIES = {"non_paper_negative"}
REQUIRED_RELEASE_CATEGORIES = (
    REQUIRED_VECTOR_CATEGORIES | REQUIRED_REJECTION_CATEGORIES
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate real-photo CAD fixture provenance and ground truth. "
            "When --minimum is greater than zero, all required capture categories "
            "must be represented by the correct fixture outcome and every qualifying "
            "fixture is executed against its declared acceptance policy."
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

    vector_categories: set[str] = set()
    rejection_categories: set[str] = set()
    for fixture in qualification.fixtures:
        if not fixture.passed:
            continue
        if fixture.expected_outcome == "vectorized_dxf":
            vector_categories.update(fixture.fixture_categories)
        elif fixture.expected_outcome == "paper_rejected":
            rejection_categories.update(fixture.fixture_categories)

    missing_vector_categories = sorted(
        REQUIRED_VECTOR_CATEGORIES - vector_categories
    )
    missing_rejection_categories = sorted(
        REQUIRED_REJECTION_CATEGORIES - rejection_categories
    )
    missing_categories = sorted(
        set(missing_vector_categories) | set(missing_rejection_categories)
    )
    category_coverage_required = args.minimum > 0
    category_coverage_passed = (
        not category_coverage_required or not missing_categories
    )

    benchmarks = []
    if args.minimum > 0 and qualification.passed and category_coverage_passed:
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
    passed = qualification.passed and category_coverage_passed and benchmark_passed
    report = qualification.to_dict()
    report["category_coverage_required"] = category_coverage_required
    report["required_vector_categories"] = sorted(REQUIRED_VECTOR_CATEGORIES)
    report["required_rejection_categories"] = sorted(
        REQUIRED_REJECTION_CATEGORIES
    )
    report["covered_vector_categories"] = sorted(vector_categories)
    report["covered_rejection_categories"] = sorted(rejection_categories)
    report["covered_categories"] = sorted(
        vector_categories | rejection_categories
    )
    report["missing_vector_categories"] = missing_vector_categories
    report["missing_rejection_categories"] = missing_rejection_categories
    report["missing_categories"] = missing_categories
    report["category_coverage_passed"] = category_coverage_passed
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
