from __future__ import annotations

import argparse
from pathlib import Path
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a photographed printed CAD drawing into an editable DXF MVP."
    )
    parser.add_argument("--headless", action="store_true", help="Run without the GUI")
    parser.add_argument("--input", type=Path, help="Input JPG/PNG for headless mode")
    parser.add_argument("--output", type=Path, default=Path("output/output.dxf"))
    parser.add_argument("--preview", type=Path, default=Path("output/preview.png"))
    parser.add_argument("--min-line-length", type=int, default=35)
    parser.add_argument("--threshold-strength", type=int, default=12)
    parser.add_argument("--no-hatch", action="store_true", help="Drop probable hatch lines")
    return parser


def run_headless(args: argparse.Namespace) -> int:
    if args.input is None:
        raise SystemExit("--input is required with --headless")
    from app.geometry_cleaner import GeometryCleanParams
    from app.line_detect import LineDetectionParams
    from app.pipeline import run_pipeline
    from app.preprocess import PreprocessParams

    result = run_pipeline(
        input_path=args.input,
        output_path=args.output,
        preview_path=args.preview,
        preprocess_params=PreprocessParams(threshold_strength=args.threshold_strength),
        detection_params=LineDetectionParams(min_line_length=args.min_line_length),
        clean_params=GeometryCleanParams(min_line_length=max(5, args.min_line_length * 0.45)),
        preserve_hatch=not args.no_hatch,
    )
    print(f"DXF: {result.export.path}")
    print(f"Editable LINE entities: {result.export.line_count}")
    print(f"Preview: {args.preview}")
    print("Scale: uncalibrated, 1 pixel = 1 drawing millimetre unit")
    return 0


def run_gui() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from app.gui import MainWindow
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is required for GUI mode. Run: pip install -r requirements.txt"
        ) from exc

    app = QApplication(sys.argv)
    app.setApplicationName("CAD Photo to DXF MVP")
    window = MainWindow()
    window.show()
    return app.exec()


def main() -> int:
    args = build_parser().parse_args()
    return run_headless(args) if args.headless else run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
