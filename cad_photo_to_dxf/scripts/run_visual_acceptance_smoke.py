from __future__ import annotations

import argparse
from pathlib import Path

from app.image_loader import load_image
from app.processing_contract import ProductionProcessingConfig, ProductionProcessingService
from app.visual_acceptance import write_visual_acceptance_artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one allowed source through production Draftsman and emit human-visible VQA artifacts."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-label", default=None)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-ocr", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    page_index = max(0, int(args.page) - 1)
    visual_source = load_image(
        args.input,
        page_index=page_index,
        pdf_dpi=int(args.dpi),
        grayscale=False,
    )
    processing_source = load_image(
        args.input,
        page_index=page_index,
        pdf_dpi=int(args.dpi),
        grayscale=True,
    )
    config = ProductionProcessingConfig(
        source_dpi=float(args.dpi),
        enable_ocr=not bool(args.no_ocr),
    )
    result = ProductionProcessingService.process_page(processing_source, config)
    structure = result.final_structure
    if structure is None:
        raise RuntimeError("Production processing returned no FinalStructure")
    if visual_source.shape[:2] != processing_source.shape[:2]:
        raise RuntimeError("Visual source and processing source coordinates differ")
    artifacts = write_visual_acceptance_artifacts(
        visual_source,
        structure,
        root=args.output,
        source_label=args.source_label or args.input.name,
    )
    print(f"structure_id={structure.structure_id}")
    print(f"overview={artifacts.overview_path}")
    print(f"overlay={artifacts.overlay_path}")
    print(f"review={artifacts.review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
