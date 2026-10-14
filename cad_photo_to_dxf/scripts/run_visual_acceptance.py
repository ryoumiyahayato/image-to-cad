from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.processing import ProductionProcessingConfig, ProductionProcessingService  # noqa: E402 - project bootstrap
from app.gui import MainWindow  # noqa: E402 - project bootstrap
from app.core.image_loader import load_image  # noqa: E402 - project bootstrap
from app.diagnostics.visual_acceptance import current_git_commit  # noqa: E402 - project bootstrap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the production page path and create a visual acceptance overview."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--corpus-split", choices=("GOLDEN", "DEV"), required=True)
    parser.add_argument("--page-label", default="single page")
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="One-based PDF page number; ignored for image sources.",
    )
    parser.add_argument("--source-dpi", type=float, default=240.0)
    parser.add_argument("--no-ocr", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_path = args.source.resolve()
    if args.page <= 0:
        raise SystemExit("--page must be a positive one-based page number")
    if source_path.suffix.lower() == ".pdf":
        image = load_image(
            source_path,
            page_index=args.page - 1,
            pdf_dpi=max(1, int(round(args.source_dpi))),
            grayscale=True,
        )
    else:
        image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Could not read source image: {source_path}")
    result = ProductionProcessingService.process_page(
        image,
        ProductionProcessingConfig(
            source_dpi=args.source_dpi,
            enable_ocr=not args.no_ocr,
        ),
    )
    structure = result.final_structure
    if structure is None:
        raise AssertionError("Production processing returned no FinalStructure")

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1900, 1000)
    run = window.visual_acceptance.set_result(
        image,
        structure,
        source_label=source_path.name,
        page_label=args.page_label,
        commit=current_git_commit(PROJECT_ROOT.parent),
        output_root=args.output_root.resolve(),
        corpus_split=args.corpus_split,
    )
    window.tabs.setCurrentWidget(window.visual_acceptance)
    window.show()
    application.processEvents()
    widget_screenshot = run.directory / "visual_acceptance_workbench.png"
    if not window.grab().save(str(widget_screenshot), "PNG"):
        raise OSError("Could not save visual acceptance workbench screenshot")
    window.close()
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "final_structure_id": run.structure_id,
                "entity_count": run.entity_count,
                "overview": str(run.overview_path),
                "workbench_screenshot": str(widget_screenshot),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
