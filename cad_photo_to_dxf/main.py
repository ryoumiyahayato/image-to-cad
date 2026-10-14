from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path
import sys

from app import __version__
from app.version import PRODUCT_NAME


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
        description=f"{PRODUCT_NAME}: convert a photographed printed CAD drawing into an editable DXF."
    )
    parser.add_argument("--version", action="version", version=f"{PRODUCT_NAME} {__version__}")
    parser.add_argument("--headless", action="store_true", help="Run without the GUI")
    parser.add_argument("--input", type=Path, help="Input JPG/PNG for headless mode")
    parser.add_argument("--output", type=Path, default=Path("output/output.dxf"))
    parser.add_argument("--preview", type=Path, default=Path("output/preview.png"))
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
        "--ocr",
        action="store_true",
        help="Run optional production OCR",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def run_headless(args: argparse.Namespace) -> int:
    if args.input is None:
        raise SystemExit("--input is required with --headless")
    from app.core.image_loader import load_image, save_image
    from app.core.perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE, auto_correct, resolve_paper_aspect_ratio, resolve_paper_dimensions_mm
    from app.core.processing import DEFAULT_IMAGE_DPI, ProductionProcessingConfig, ProductionProcessingService
    from app.core.preview import render_final_structure_preview
    from app.core.reporting import write_json_report
    from app.core.scale_calibrator import ScaleCalibration
    from app.export.trace_single_export import export_final_structure_dxf

    progress = None
    if args.verbose:

        def progress(stage: str, fraction: float) -> None:
            print(f"[{fraction * 100:5.1f}%] {stage}", file=sys.stderr)

    geometry = []
    image = load_image(args.input, pdf_geometry_sink=geometry)
    paper_options = dict(
        orientation=args.paper_orientation,
        observed_landscape=image.shape[1] >= image.shape[0],
    )
    aspect = resolve_paper_aspect_ratio(
        args.paper_size, args.paper_width_mm, args.paper_height_mm, **paper_options
    )
    dimensions = resolve_paper_dimensions_mm(
        args.paper_size, args.paper_width_mm, args.paper_height_mm, **paper_options
    )
    correction = auto_correct(image, aspect)
    corrected = (
        correction is not None
        and correction.confidence >= MIN_AUTOMATIC_PAPER_CONFIDENCE
    )
    if not corrected and not args.allow_uncorrected:
        raise ValueError(
            "Paper boundary could not be confirmed; use --allow-uncorrected"
        )
    if corrected:
        image = correction.image
    calibration = None
    if corrected and dimensions is not None:
        calibration = ScaleCalibration(
            (0.0, 0.0), (float(max(1, image.shape[1] - 1)), 0.0), dimensions[0]
        )
    config = ProductionProcessingConfig(source_dpi=DEFAULT_IMAGE_DPI, enable_ocr=args.ocr)
    result = ProductionProcessingService.process_page(
        image, config, progress_callback=progress,
        pdf_geometry=geometry[0] if geometry and not corrected else None,
    )
    structure = result.final_structure
    if structure is None:
        raise RuntimeError("Production processing returned no FinalStructure")
    # Both interfaces serialize the same final geometry.
    warnings = list(structure.warnings)
    export = export_final_structure_dxf(
        structure, args.output, calibration, allow_empty=args.allow_empty
    )
    save_image(args.preview, render_final_structure_preview(structure))
    if args.debug_dir is not None:
        save_image(args.debug_dir / "corrected.png", image)
        save_image(args.debug_dir / "contours.png", structure.contour_binary)
    write_json_report(
        args.report,
        {
            "application_version": __version__,
            "input": str(args.input),
            "structure_id": structure.structure_id,
            "source_size_px": structure.source_size_px,
            "processing_contract": config.payload(),
            "member_counts": {
                key: len(getattr(structure, key))
                for key in (
                    "straight_lines",
                    "arcs",
                    "contours",
                    "texts",
                    "logos",
                    "signatures",
                )
            },
            "warnings": warnings,
            "perspective_applied": corrected,
            "coordinate_space": "paper_mm" if calibration else "pixel",
        },
    )
    print(f"DXF: {export.path}")
    print(f"Editable LINE entities: {export.line_count}")
    print(f"Editable ARC entities: {export.arc_count}")
    print(f"Preview: {args.preview}")
    print(f"Report: {args.report}")
    print(
        "Scale: "
        + (
            f"calibrated, {export.mm_per_pixel:.6f} mm/px"
            if export.calibrated
            else "uncalibrated, 1 pixel = 1 unitless drawing unit"
        )
    )
    if warnings:
        print(f"Warnings: {len(warnings)}")
    return 0


def run_gui() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from app.gui import MainWindow as ProductMainWindow
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is required for GUI mode. Run: pip install -r requirements.txt"
        ) from exc

    app = QApplication(sys.argv)
    app.setApplicationName(f"{PRODUCT_NAME} {__version__}")
    window = ProductMainWindow()
    window.show()
    return app.exec()


def main() -> int:
    args = build_parser().parse_args()
    return run_headless(args) if args.headless else run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
