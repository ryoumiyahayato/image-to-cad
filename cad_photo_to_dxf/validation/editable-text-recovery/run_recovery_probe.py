from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import json
from math import isfinite
from pathlib import Path
import re
import sys

import cv2
import ezdxf
import numpy as np


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
    return re.sub(r"^PAGE_\d{3}_", "", str(name))


def _entity_source_mask(
    entity: object,
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if entity.dxftype() != "LWPOLYLINE":  # type: ignore[attr-defined]
        return mask
    points = [
        (
            int(round(float(x))),
            int(round(shape[0] - float(y))),
        )
        for x, y in entity.get_points("xy")  # type: ignore[attr-defined]
    ]
    if len(points) < 2:
        return mask
    polygon = np.asarray(points, dtype=np.int32)
    cv2.polylines(
        mask,
        [polygon],
        bool(entity.closed),  # type: ignore[attr-defined]
        255,
        1,
        cv2.LINE_8,
    )
    return mask


def _semantic_observation(structure: object) -> dict[str, object]:
    for observation in structure.observations:  # type: ignore[attr-defined]
        if observation.get("event") == "text_output_contract":
            value = observation.get("semantic_ownership", {})
            return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _angle_error(first: float, second: float) -> float:
    return abs((float(first) - float(second) + 180.0) % 360.0 - 180.0)


def _text_geometry_record(entity: object, index: int) -> dict[str, object]:
    try:
        xdata = entity.get_xdata("OCR_TEXT_GEOMETRY")  # type: ignore[attr-defined]
    except ezdxf.DXFValueError:
        return {
            "entity_index": index,
            "entity_type": entity.dxftype(),  # type: ignore[attr-defined]
            "geometry_contract_present": False,
        }
    strings = [str(tag.value) for tag in xdata if tag.code == 1000]
    values = [float(tag.value) for tag in xdata if tag.code == 1040]
    integers = [int(tag.value) for tag in xdata if tag.code == 1070]
    if len(values) != 10 or len(integers) != 2:
        return {
            "entity_index": index,
            "entity_type": entity.dxftype(),  # type: ignore[attr-defined]
            "geometry_contract_present": False,
            "geometry_xdata_float_count": len(values),
            "geometry_xdata_integer_count": len(integers),
        }
    (
        target_center_x,
        target_center_y,
        target_width,
        target_height,
        rendered_width,
        rendered_height,
        center_error,
        raw_width_factor,
        width_factor,
        target_rotation,
    ) = values
    entity_rotation = float(entity.dxf.rotation)  # type: ignore[attr-defined]
    entity_height = float(entity.dxf.height)  # type: ignore[attr-defined]
    return {
        "entity_index": index,
        "entity_type": entity.dxftype(),  # type: ignore[attr-defined]
        "text": str(entity.dxf.text),  # type: ignore[attr-defined]
        "geometry_contract_present": True,
        "metric_source": (
            strings[0].removeprefix("metric_source=")
            if strings
            else ""
        ),
        "metric_fallback": (
            strings[1].removeprefix("metric_fallback=")
            if len(strings) > 1
            else ""
        ),
        "target_center": [target_center_x, target_center_y],
        "target_width": target_width,
        "target_height": target_height,
        "rendered_width": rendered_width,
        "rendered_height": rendered_height,
        "rendered_to_target_width_ratio": (
            rendered_width / target_width
            if target_width > 0.0
            else None
        ),
        "rendered_to_target_height_ratio": (
            rendered_height / target_height
            if target_height > 0.0
            else None
        ),
        "entity_height_to_target_ratio": (
            entity_height / target_height
            if target_height > 0.0
            else None
        ),
        "center_error": center_error,
        "raw_width_factor": raw_width_factor,
        "width_factor": width_factor,
        "width_factor_clamped": bool(integers[1]),
        "target_rotation": target_rotation,
        "entity_rotation": entity_rotation,
        "rotation_error": _angle_error(
            entity_rotation,
            target_rotation,
        ),
        "finite": all(isfinite(value) for value in values),
    }


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
    editable_mask = structure.editable_text_source_mask
    uncertain_mask = structure.uncertain_text_outline_mask
    general_trace_source = structure.contour_binary < 128
    eligible_owned_trace_source = np.zeros(
        structure.contour_binary.shape,
        dtype=np.uint8,
    )
    uncertain_owned_trace_source = np.zeros(
        structure.contour_binary.shape,
        dtype=np.uint8,
    )
    if editable_mask is not None:
        eligible_owned_trace_source[
            general_trace_source & (editable_mask > 0)
        ] = 255
    if uncertain_mask is not None:
        uncertain_owned_trace_source[
            general_trace_source & (uncertain_mask > 0)
        ] = 255
    eligible_owned_symbol_objects = 0
    uncertain_owned_symbol_objects = 0
    eligible_symbol_geometric_objects = 0
    uncertain_symbol_geometric_objects = 0
    eligible_symbol_geometric_pixels = 0
    uncertain_symbol_geometric_pixels = 0
    for entity in document.modelspace():
        if _base_layer(str(entity.dxf.layer)) != "TRACE_TEXT_SYMBOL":
            continue
        entity_mask = _entity_source_mask(
            entity,
            shape=structure.contour_binary.shape,
        )
        if editable_mask is not None:
            overlap = int(
                np.count_nonzero(
                    (entity_mask > 0) & (editable_mask > 0)
                )
            )
            eligible_symbol_geometric_pixels += overlap
            eligible_symbol_geometric_objects += int(overlap > 0)
            eligible_owned_symbol_objects += int(
                np.any(
                    (entity_mask > 0)
                    & (eligible_owned_trace_source > 0)
                )
            )
        if uncertain_mask is not None:
            overlap = int(
                np.count_nonzero(
                    (entity_mask > 0) & (uncertain_mask > 0)
                )
            )
            uncertain_symbol_geometric_pixels += overlap
            uncertain_symbol_geometric_objects += int(overlap > 0)
            uncertain_owned_symbol_objects += int(
                np.any(
                    (entity_mask > 0)
                    & (uncertain_owned_trace_source > 0)
                )
            )
    semantic_ownership = _semantic_observation(structure)
    candidate_records = list(
        semantic_ownership.get("candidates", [])
    )
    geometry_records = [
        _text_geometry_record(entity, index)
        for index, entity in enumerate(native_texts, start=1)
    ]
    valid_geometry_records = [
        item
        for item in geometry_records
        if item.get("geometry_contract_present") is True
    ]
    height_ratios = [
        float(item["rendered_to_target_height_ratio"])
        for item in valid_geometry_records
        if item.get("rendered_to_target_height_ratio") is not None
    ]
    width_ratios = [
        float(item["rendered_to_target_width_ratio"])
        for item in valid_geometry_records
        if item.get("rendered_to_target_width_ratio") is not None
    ]
    center_errors = [
        float(item["center_error"])
        for item in valid_geometry_records
    ]
    rotation_errors = [
        float(item["rotation_error"])
        for item in valid_geometry_records
    ]
    width_factors = [
        float(item["width_factor"])
        for item in valid_geometry_records
    ]
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
        "eligible_candidate_text_symbol_object_count": (
            eligible_owned_symbol_objects
        ),
        "eligible_candidate_text_symbol_pixel_count": (
            int(cv2.countNonZero(eligible_owned_trace_source))
        ),
        "uncertain_candidate_text_symbol_object_count": (
            uncertain_owned_symbol_objects
        ),
        "uncertain_candidate_text_symbol_pixel_count": (
            int(cv2.countNonZero(uncertain_owned_trace_source))
        ),
        "eligible_candidate_text_symbol_geometric_touch_count": (
            eligible_symbol_geometric_objects
        ),
        "eligible_candidate_text_symbol_geometric_touch_pixels": (
            eligible_symbol_geometric_pixels
        ),
        "uncertain_candidate_text_symbol_geometric_touch_count": (
            uncertain_symbol_geometric_objects
        ),
        "uncertain_candidate_text_symbol_geometric_touch_pixels": (
            uncertain_symbol_geometric_pixels
        ),
        "candidate_primary_semantic_conflict_count": sum(
            not bool(item.get("primary_semantic_unique", False))
            for item in candidate_records
            if isinstance(item, dict)
        ),
        "candidate_source_ownership_violation_count": sum(
            not bool(item.get("source_pixels_conserved", False))
            for item in candidate_records
            if isinstance(item, dict)
        ),
        "fallback_and_text_symbol_conflict_count": (
            uncertain_owned_symbol_objects
        ),
        "semantic_ownership": semantic_ownership,
        "text_geometry": {
            "record_count": len(geometry_records),
            "contract_present_count": len(valid_geometry_records),
            "all_entity_types_TEXT": all(
                item.get("entity_type") == "TEXT"
                for item in geometry_records
            ),
            "metric_sources": dict(
                Counter(
                    str(item.get("metric_source", "missing"))
                    for item in geometry_records
                )
            ),
            "metric_fallbacks": dict(
                Counter(
                    str(item.get("metric_fallback", "missing"))
                    for item in geometry_records
                )
            ),
            "width_factor_clamped_count": sum(
                bool(item.get("width_factor_clamped", False))
                for item in valid_geometry_records
            ),
            "minimum_width_factor": (
                min(width_factors) if width_factors else None
            ),
            "maximum_width_factor": (
                max(width_factors) if width_factors else None
            ),
            "minimum_rendered_to_target_height_ratio": (
                min(height_ratios) if height_ratios else None
            ),
            "maximum_rendered_to_target_height_ratio": (
                max(height_ratios) if height_ratios else None
            ),
            "minimum_rendered_to_target_width_ratio": (
                min(width_ratios) if width_ratios else None
            ),
            "maximum_rendered_to_target_width_ratio": (
                max(width_ratios) if width_ratios else None
            ),
            "maximum_center_error": (
                max(center_errors) if center_errors else None
            ),
            "maximum_rotation_error": (
                max(rotation_errors) if rotation_errors else None
            ),
            "records": geometry_records,
        },
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
        and payload["eligible_candidate_text_symbol_object_count"] == 0
        and payload["candidate_primary_semantic_conflict_count"] == 0
        and payload["candidate_source_ownership_violation_count"] == 0
        and payload["fallback_and_text_symbol_conflict_count"] == 0
        and len(valid_geometry_records) == len(native_texts)
        and all(
            item.get("entity_type") == "TEXT"
            and item.get("finite") is True
            and float(item["width_factor"]) >= 0.72
            and abs(
                float(item["rendered_to_target_height_ratio"])
                - 1.0
            )
            <= 1e-6
            and float(item["center_error"]) <= 1e-6
            and float(item["rotation_error"]) <= 1e-6
            for item in valid_geometry_records
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
