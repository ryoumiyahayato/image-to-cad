from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import ezdxf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.image_loader import load_image  # noqa: E402
from app.processing_contract import (  # noqa: E402
    ProductionProcessingConfig,
    ProductionProcessingService,
)
from app.text_output_contract import (  # noqa: E402
    text_output_decisions,
    text_output_summary,
)
from app.trace_single_export import (  # noqa: E402
    export_final_structure_dxf,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--dpi", type=float, required=True)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _base_layer(name: str) -> str:
    parts = str(name).split("_", 3)
    if (
        len(parts) == 4
        and parts[0] == "PAGE"
        and parts[1].isdigit()
    ):
        return parts[3]
    return str(name)


def main() -> int:
    args = _parser().parse_args()
    image = load_image(
        args.input.resolve(),
        page_index=args.page - 1,
        pdf_dpi=float(args.dpi),
        grayscale=True,
    )
    result = ProductionProcessingService.process_page(
        image,
        ProductionProcessingConfig(
            source_dpi=float(args.dpi),
            enable_ocr=True,
        ),
    )
    structure = result.final_structure
    if structure is None:
        raise AssertionError("Production processing returned no FinalStructure")
    structure.assert_valid()

    dxf_path = args.dxf.resolve()
    dxf_path.parent.mkdir(parents=True, exist_ok=True)
    export = export_final_structure_dxf(structure, dxf_path)
    document = ezdxf.readfile(dxf_path)
    audit = document.audit()
    layer_counts: Counter[str] = Counter(
        _base_layer(str(entity.dxf.layer))
        for entity in document.modelspace()
    )
    decisions = text_output_decisions(structure.texts)
    summary = text_output_summary(structure.texts)
    native_texts = list(document.modelspace().query("TEXT"))
    payload = {
        "schema_version": 1,
        "input": str(args.input.resolve()),
        "page": int(args.page),
        "dpi": float(args.dpi),
        "source_shape": [int(value) for value in image.shape],
        "structure_id": structure.structure_id,
        "dxf": str(dxf_path),
        "summary": summary.payload(),
        "native_TEXT_count": len(native_texts),
        "export_TEXT_count": int(export.text_count),
        "export_source_text_outline_candidate_count": int(
            export.source_text_outline_count
        ),
        "native_TEXT_matches_eligible": (
            len(native_texts)
            == int(export.text_count)
            == int(summary.text_emit_eligible_count)
        ),
        "layer_entity_counts": dict(sorted(layer_counts.items())),
        "layer_visibility": {
            str(layer.dxf.name): not layer.is_off()
            for layer in document.layers
        },
        "dxf_audit_error_count": len(audit.errors),
        "hard_rejected_candidates": [
            {
                "candidate_id": f"ocr-{index + 1:03d}",
                "text": str(decision.candidate.text),
                "bbox": [
                    int(value) for value in decision.candidate.bbox
                ],
                "reason": decision.hard_reject_reason,
            }
            for index, decision in enumerate(decisions)
            if not decision.text_emit_eligible
        ],
        "decisions": [
            {
                "candidate_id": f"ocr-{index + 1:03d}",
                **decision.payload(),
            }
            for index, decision in enumerate(decisions)
        ],
    }
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(output_path)
    return 0 if (
        payload["native_TEXT_matches_eligible"]
        and payload["dxf_audit_error_count"] == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
