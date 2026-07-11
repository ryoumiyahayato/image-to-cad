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


REQUIRED_RELEASE_CATEGORIES = {
    "flat_scan",
    "mild_perspective",
    "severe_perspective",
    "blur_shadow_fold",
    "hidden_paper_edge",
    "non_paper_negative",
    "multi_resolution",
    "portrait_landscape",
    "mixed_geometry",
    "original_cad_dimensions",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate real-photo CAD fixture provenance and ground truth. "
            "When --minimum is greater than zero, all required capture categories "
            "must be represented and qualifying fixtures are processed against "
            "their ground-truth DXF files."
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


def _fixture_categories(manifest_path: Path) -> set[str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    categories = manifest.get("fixture_categories") if isinstance(manifest, dict) else None
    if not isinstance(categories, list):
        return set()
    return {item for item in categories if isinstance(item, str)}


def main() -> int:
    args = build_parser().parse_args()
    qualification = validate_fixture_set(
        args.root,
        minimum_required=args.minimum,
        required_freecad_version=args.freecad_version,
    )

    covered_categories: set[str] = set()
    for fixture in qualification.fixtures:
        if fixture.passed:
            covered_categories.update(
                _fixture_categories(fixture.fixture_directory / "manifest.json")
            )
    missing_categories = sorted(REQUIRED_RELEASE_CATEGORIES - covered_categories)
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
    report["covered_categories"] = sorted(covered_categories)
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
