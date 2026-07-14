from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path
import sys

from app import __version__


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a photographed printed CAD drawing into an editable DXF."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--headless", action="store_true", help="Run without the GUI")
    parser.add_argument("--input", type=Path, help="Input JPG/PNG for headless mode")
    parser.add_argument("--output", type=Path, default=Path("output/output.dxf"))
    parser.add_argument("--preview", type=Path, default=Path("output/preview.png"))
    parser.add_argument("--min-line-length", type=_positive_int, default=35)
    parser.add_argument("--threshold-strength", type=int, default=12)
    parser.add_argument(
        "--no-hatch",
        action="store_true",
        help="Drop only high-confidence hatch lines; uncertain candidates are retained",
    )
    parser.add_argument(
        "--paper-size",
        type=str.upper,
        choices=("UNKNOWN", "A0", "A1", "A2", "A3", "A4", "LETTER", "LEGAL"),
        default="UNKNOWN",
    )
    parser.add_argument(
        "--paper-orientation",
        choices=("auto", "portrait", "landscape"),
        default="auto",
    )
    parser.add_argument("--paper-width-mm", type=_positive_finite_float)
    parser.add_argument("--paper-height-mm", type=_positive_finite_float)
    parser.add_argument(
        "--allow-uncorrected",
        action="store_true",
        help="Continue when the paper boundary cannot be detected",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow a successful empty DXF when no lines are detected",
    )
    parser.add_argument("--report", type=Path, default=Path("output/report.json"))
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument(
        "--auxiliary",
        action="store_true",
        help="Detect review-only circles and symbols",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Run optional review-only OCR",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def run_headless(args: argparse.Namespace) -> int:
    if args.input is None:
        raise SystemExit("--input is required with --headless")
    from app.geometry_cleaner import GeometryCleanParams
    from app.line_detect import LineDetectionParams
    from app.pipeline import run_pipeline
    from app.preprocess import PreprocessParams

    progress = None
    if args.verbose:

        def progress(stage: str, fraction: float) -> None:
            print(f"[{fraction * 100:5.1f}%] {stage}", file=sys.stderr)

    result = run_pipeline(
        input_path=args.input,
        output_path=args.output,
        preview_path=args.preview,
        preprocess_params=PreprocessParams(threshold_strength=args.threshold_strength),
        detection_params=LineDetectionParams(min_line_length=args.min_line_length),
        clean_params=GeometryCleanParams(
            min_line_length=max(5, args.min_line_length * 0.45)
        ),
        preserve_hatch=not args.no_hatch,
        report_path=args.report,
        debug_dir=args.debug_dir,
        paper_size=args.paper_size,
        paper_orientation=args.paper_orientation,
        custom_paper_width_mm=args.paper_width_mm,
        custom_paper_height_mm=args.paper_height_mm,
        strict_perspective=not args.allow_uncorrected,
        fail_on_empty=not args.allow_empty,
        enable_auxiliary=args.auxiliary or args.ocr,
        enable_ocr=args.ocr,
        progress_callback=progress,
    )
    print(f"DXF: {result.export.path}")
    print(f"Editable LINE entities: {result.export.line_count}")
    print(f"Preview: {args.preview}")
    print(f"Report: {result.report_path}")
    print(
        "Scale: "
        + (
            f"calibrated, {result.export.mm_per_pixel:.6f} mm/px"
            if result.export.calibrated
            else "uncalibrated, 1 pixel = 1 unitless drawing unit"
        )
    )
    if result.report.get("warnings"):
        print(f"Warnings: {len(result.report['warnings'])}")
    return 0


def run_gui() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from app.gui_state_guard import MainWindow
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is required for GUI mode. Run: pip install -r requirements.txt"
        ) from exc

    app = QApplication(sys.argv)
    app.setApplicationName(f"CAD Photo to DXF {__version__}")
    window = MainWindow()
    window.show()
    return app.exec()


def main() -> int:
    args = build_parser().parse_args()
    if not args.headless:
        return run_gui()
    try:
        return run_headless(args)
    except ValueError as exc:
        print(f"Invalid arguments: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"Input not found: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        from app.cancellation import ProcessingCancelled
        from app.pipeline import PipelineError

        if isinstance(exc, ProcessingCancelled):
            print("Processing cancelled", file=sys.stderr)
            return 130
        if isinstance(exc, PipelineError):
            print(str(exc), file=sys.stderr)
            return exc.exit_code
        print(f"Processing failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
