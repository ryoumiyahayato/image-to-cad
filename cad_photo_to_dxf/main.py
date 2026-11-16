from __future__ import annotations

import argparse
from dataclasses import asdict
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
    parser.add_argument("--input", type=Path, help="Input JPG/PNG/TIFF/PDF for headless mode")
    parser.add_argument(
        "--source-dpi", type=_positive_finite_float,
        help="Actual aligned scan DPI, or requested PDF render DPI before the pixel limit",
    )
    parser.add_argument(
        "--original-scan", type=Path,
        help="Aligned, native-resolution bitonal TIFF with embedded DPI",
    )
    parser.add_argument(
        "--blank-paper", type=int, nargs=4, action="append", default=[],
        metavar=("X0", "Y0", "X1", "Y1"),
        help="Independently reviewed blank paper on the input pixel grid",
    )
    parser.add_argument(
        "--crop", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
        help="Export a half-open rectangle on the actual rendered pixel grid, in page coordinates",
    )
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
    parser.add_argument(
        '--experimental-compound-strokes', action='store_true',
        help='Trial: recover source-supported partial strokes with a verified original scan',
    )
    parser.add_argument(
        "--experimental-native-source-region-manifest", type=Path,
        help="Trial: select one complete native source component using a content-bound JSON manifest",
    )
    return parser


def run_headless(args: argparse.Namespace) -> int:
    if args.input is None:
        raise SystemExit("--input is required with --headless")
    is_pdf = args.input.suffix.lower() == ".pdf"
    if (args.original_scan is not None or (args.crop is not None and not is_pdf)) and args.source_dpi is None:
        raise SystemExit("Raster --crop and --original-scan require --source-dpi")
    if args.blank_paper and args.original_scan is None:
        raise SystemExit("--blank-paper requires --original-scan")
    if is_pdf and args.original_scan is not None:
        raise ValueError("--original-scan requires an aligned raster input")
    source_region_json = None
    source_region_path = getattr(args, "experimental_native_source_region_manifest", None)
    if source_region_path is not None:
        if is_pdf or args.original_scan is None or args.source_dpi is None:
            raise ValueError("Source region selection requires raster --source-dpi and --original-scan")
        if getattr(args, "experimental_compound_strokes", False):
            raise ValueError("Source region and compound stroke trials are separate")
        from app.geometry.source_region_selection import (
            MAX_MANIFEST_BYTES, canonical_source_region_selection,
        )

        with source_region_path.open("rb") as stream:
            raw_selection = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_selection) > MAX_MANIFEST_BYTES:
            raise ValueError("Source region selection exceeds the manifest byte budget")
        source_region_json = canonical_source_region_selection(raw_selection.decode("utf-8"))
    from app.core.image_loader import load_image, pdf_page_size_mm, processing_pdf_dpi, save_image
    from app.core.perspective import MIN_AUTOMATIC_PAPER_CONFIDENCE, auto_correct, resolve_paper_aspect_ratio, resolve_paper_dimensions_mm
    from app.core.processing import DEFAULT_IMAGE_DPI, ProductionProcessingConfig, ProductionProcessingService
    from app.core.preview import render_final_structure_preview
    from app.core.reporting import write_json_report
    from app.core.scale_calibrator import ScaleCalibration
    from app.core.structure import metadata_to_jsonable
    from app.export.trace_single_export import export_final_structure_dxf

    progress = None
    if args.verbose:

        def progress(stage: str, fraction: float) -> None:
            print(f"[{fraction * 100:5.1f}%] {stage}", file=sys.stderr)

    geometry = []
    pdf_renders = []
    aligned = args.source_dpi is not None or is_pdf
    render_options = {}
    if is_pdf:
        render_options["pdf_dpi"] = (
            args.source_dpi if args.source_dpi is not None
            else processing_pdf_dpi(pdf_page_size_mm(args.input, 0))
        )
    image = load_image(
        args.input, pdf_geometry_sink=geometry,
        grayscale=aligned, pdf_render_sink=pdf_renders, **render_options,
    )
    pdf_render = pdf_renders[0] if pdf_renders else None
    source_crop = tuple(args.crop) if args.crop is not None else None
    confirmed_noise = None
    original_scan_features = None
    registered = None
    dust_report = {"status": "NO_ORIGINAL_SCAN"}
    if args.original_scan is not None:
        from app.core.cancellation import report_progress
        from app.geometry.scan_dust import (
            authorize_scan_dust,
            extract_original_scan_features,
            load_original_scan,
            register_original_scan,
        )

        report_progress(progress, "original-scan-load", 0.0)
        original, dpi, load_status = load_original_scan(args.original_scan)
        registration_status = "NOT_RUN"
        if original is not None and dpi is not None:
            report_progress(progress, "original-scan-registration", 0.005)
            registered, registration_status = register_original_scan(
                image, original, args.source_dpi, dpi,
            )
        if registered is not None and source_crop is not None:
            report_progress(progress, "original-scan-features", 0.01)
            original_scan_features = extract_original_scan_features(registered, source_crop)
            original_scan_features["original"] = str(args.original_scan)
            if args.blank_paper:
                report_progress(progress, "original-scan-dust-authorization", 0.015)
        confirmed_noise = authorize_scan_dust(image, registered, args.blank_paper)
        if registered is None:
            status = load_status if original is None else registration_status
            authorization_status = "UNVERIFIED_ORIGINAL"
        elif confirmed_noise is None:
            status = authorization_status = "NO_REVIEWED_BLANK_PAPER"
        else:
            status = registration_status
            authorization_status = "MASK_COMPUTED"
        dust_report = {
            "status": status, "original": str(args.original_scan),
            "original_dpi": dpi, "reviewed_blank_paper": args.blank_paper,
            "load_status": load_status,
            "registration_status": registration_status,
            "feature_status": "EXTRACTED" if original_scan_features is not None else "NOT_RUN",
            "sampling_source": "native_tiff_pixels" if original_scan_features is not None else "input_raster",
            "authorization_status": authorization_status,
            "authorized_input_pixels": int(confirmed_noise.sum()) if confirmed_noise is not None else 0,
        }
        del original
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
    correction = None if aligned else auto_correct(image, aspect)
    corrected = (
        correction is not None
        and correction.confidence >= MIN_AUTOMATIC_PAPER_CONFIDENCE
    )
    if not corrected and not aligned and not args.allow_uncorrected:
        raise ValueError(
            "Paper boundary could not be confirmed; use --allow-uncorrected"
        )
    if corrected:
        image = correction.image
    calibration = None
    if pdf_render is not None:
        calibration = ScaleCalibration.for_paper(pdf_render.size_px, pdf_render.page_size_mm)
    elif aligned:
        calibration = ScaleCalibration.for_raster_dpi(image.shape[:2][::-1], args.source_dpi)
    elif corrected and dimensions is not None:
        calibration = ScaleCalibration.for_paper(
            image.shape[:2][::-1], dimensions, corners_at_centers=True,
        )
    config = ProductionProcessingConfig(
        source_dpi=pdf_render.render_dpi if pdf_render else args.source_dpi or DEFAULT_IMAGE_DPI,
        enable_ocr=args.ocr,
        experimental_compound_strokes=getattr(args, "experimental_compound_strokes", False),
        experimental_native_source_region_manifest=source_region_json,
    )
    result = ProductionProcessingService.process_page(
        image, config, progress_callback=progress,
        pdf_geometry=geometry[0] if geometry and not corrected else None,
        confirmed_noise=confirmed_noise, source_crop=source_crop,
        original_scan_features=original_scan_features, registered_original_scan=registered,
        original_scan_requested=args.original_scan is not None,
    )
    structure = result.final_structure
    if structure is None:
        raise RuntimeError("Production processing returned no FinalStructure")
    # Both interfaces serialize the same final geometry.
    warnings = list(structure.warnings)
    if dust_report.get("authorization_status") == "UNVERIFIED_ORIGINAL":
        warnings.append(f"Original scan unavailable as evidence ({dust_report['status']}); used input raster.")
    export = export_final_structure_dxf(
        structure, args.output, calibration, allow_empty=args.allow_empty
    )
    save_image(args.preview, render_final_structure_preview(structure))
    if args.debug_dir is not None:
        if source_crop is not None:
            left, top, right, bottom = source_crop
            image = image[top:bottom, left:right]
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
                **{
                    key: len(getattr(structure, key))
                    for key in ("straight_lines", "arcs", "contours", "texts", "signatures")
                },
                "logos": export.logo_count,
                "independent_signature_blocks": export.signature_count,
                "engineering_graphics": sum(
                    region.visual_kind == "engineering_graphic" for region in structure.logos
                ),
            },
            "warnings": warnings,
            "perspective_applied": corrected,
            "coordinate_space": "paper_mm" if calibration else "pixel",
            "paper_mm_per_pixel_xy": (
                (calibration.mm_per_pixel, calibration.vertical_mm_per_pixel)
                if calibration else None
            ),
            "pdf_render": asdict(pdf_render) if pdf_render else None,
            "scan_dust": dust_report,
            "scan_classification": metadata_to_jsonable(
                structure.provenance.get("scan_classification", {})
            ),
            "signing_source": metadata_to_jsonable(
                structure.provenance.get("raster_signing", {})
            ),
            "local_filled_marks": metadata_to_jsonable(
                structure.provenance.get("stroke_presentation", {}).get("local_filled_marks", ())
            ),
            "scanned_title_rows": metadata_to_jsonable(
                structure.provenance.get("scanned_title_rows", ())
            ),
            "scanned_glyph_review": metadata_to_jsonable(
                structure.provenance.get("scanned_glyph_review", ())
            ),
            "observed_frame_recovery": metadata_to_jsonable(
                structure.provenance.get("observed_frame_recovery", {})
            ),
            "observed_open_stroke_recovery": metadata_to_jsonable(
                structure.provenance.get("observed_open_stroke_recovery", {})
            ),
            'compound_stroke_recovery': metadata_to_jsonable(
                structure.provenance.get('compound_stroke_recovery', {})
            ),
            **({
                "explicit_source_region_recovery": metadata_to_jsonable(
                    structure.provenance.get("explicit_source_region_recovery", {})
                ),
                "source_structure_id": structure.source_structure_id,
            } if source_region_json is not None else {}),
            "boxed_label_source_members": metadata_to_jsonable(
                structure.provenance.get("boxed_label_source_members", {})
            ),
            "engineering_enclosures": metadata_to_jsonable(
                structure.provenance.get("engineering_enclosures", ())
            ),
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
            f"paper, {export.mm_per_pixel:.6f} × {calibration.vertical_mm_per_pixel:.6f} mm/px"
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
