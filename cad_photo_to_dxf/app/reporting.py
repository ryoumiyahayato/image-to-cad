from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np


REPORT_SCHEMA_VERSION = "1.2"

DEFAULT_TECHNICAL_LIMITS = (
    "paper_mm 仅表示打印纸面坐标；恢复工程设计尺寸必须使用已知尺寸或图纸比例校准。",
    "严重折叠、局部波浪和复杂非刚性形变不能保证整页误差小于 2%。",
    "取消在原生 OpenCV 或 OCR 单次调用返回后生效，无法安全强制终止调用内部。",
    "HATCH 封闭区域包含关系使用保守的轴对齐边界近似。",
    "OCR、圆弧、尺寸文字和建筑符号仅作为辅助候选。",
)


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_json_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Write a UTF-8 JSON report atomically."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(
        json.dumps(_json_value(report), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return output_path


def build_lineage(
    raw_lines: Iterable[Any],
    final_lines: Iterable[Any],
) -> dict[str, Any]:
    """Build bidirectional raw-source to final-entity lineage."""
    raw_source_ids: list[str] = []
    for line in raw_lines:
        raw_source_ids.extend(str(item) for item in getattr(line, "source_ids", ()))
    raw_source_ids = sorted(set(raw_source_ids))

    final_entities: list[dict[str, Any]] = []
    source_to_final: dict[str, list[str]] = {
        source_id: [] for source_id in raw_source_ids
    }
    for index, line in enumerate(final_lines, start=1):
        entity_id = f"LINE-{index:06d}"
        source_ids = sorted(
            set(str(item) for item in getattr(line, "source_ids", ()))
        )
        operations = list(
            dict.fromkeys(str(item) for item in getattr(line, "history", ()))
        )
        final_entities.append(
            {
                "entity_id": entity_id,
                "layer": getattr(line, "layer", "DETAIL"),
                "source_ids": source_ids,
                "operations": operations,
                "classification_confidence": float(
                    getattr(line, "classification_confidence", 1.0)
                ),
                "classification_reasons": list(
                    getattr(line, "classification_reasons", ())
                ),
                "geometry": {
                    "start": [float(line.x1), float(line.y1)],
                    "end": [float(line.x2), float(line.y2)],
                    "width_px": float(line.width),
                },
            }
        )
        for source_id in source_ids:
            source_to_final.setdefault(source_id, []).append(entity_id)

    dropped = sorted(
        source_id for source_id, entity_ids in source_to_final.items() if not entity_ids
    )
    return {
        "raw_source_count": len(raw_source_ids),
        "final_entity_count": len(final_entities),
        "source_to_final": source_to_final,
        "dropped_source_ids": dropped,
        "final_entities": final_entities,
    }


def build_processing_report(
    *,
    application_version: str,
    started_at_utc: str,
    duration_seconds: float,
    input_path: str | Path | None,
    input_shape: Iterable[int] | None,
    perspective: dict[str, Any],
    quality: Any,
    parameters: dict[str, Any],
    preprocess_stages: dict[str, np.ndarray],
    debug_directory: str | Path | None,
    raw_lines: Iterable[Any],
    final_lines: Iterable[Any],
    geometry_report: Any,
    classification_report: Any,
    auxiliary: Any,
    export_result: Any,
    calibration_source: str,
    warnings: Iterable[str] = (),
    technical_limits: Iterable[str] = DEFAULT_TECHNICAL_LIMITS,
) -> dict[str, Any]:
    """Build the single report schema used by CLI and GUI exports."""
    raw_line_list = list(raw_lines)
    final_line_list = list(final_lines)
    unit_name = str(getattr(export_result, "unit_name", "pixel_unit"))
    coordinate_mode = str(
        getattr(export_result, "coordinate_mode", "pixel_units")
    )
    scale_per_pixel = float(getattr(export_result, "mm_per_pixel", 1.0))
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "application_version": application_version,
        "started_at_utc": started_at_utc,
        "duration_seconds": float(duration_seconds),
        "input": {
            "path": str(input_path) if input_path is not None else None,
            "shape": list(input_shape) if input_shape is not None else None,
        },
        "perspective": perspective,
        "quality": quality,
        "parameters": parameters,
        "preprocessing": {
            "stages": {
                name: list(image.shape) for name, image in preprocess_stages.items()
            },
            "debug_directory": (
                str(debug_directory) if debug_directory is not None else None
            ),
        },
        "detection": {
            "raw_line_count": len(raw_line_list),
        },
        "geometry": geometry_report,
        "classification": classification_report,
        "auxiliary": auxiliary,
        "lineage": build_lineage(raw_line_list, final_line_list),
        "export": {
            "path": str(getattr(export_result, "path")),
            "line_count": int(getattr(export_result, "line_count")),
            "skipped_line_count": int(
                getattr(export_result, "skipped_line_count", 0)
            ),
            "scale_per_pixel": scale_per_pixel,
            "mm_per_pixel": scale_per_pixel if unit_name == "mm" else None,
            "calibrated": bool(getattr(export_result, "calibrated", False)),
            "calibration_source": calibration_source,
            "coordinate_mode": coordinate_mode,
            "unit_name": unit_name,
            "is_engineering_model_scale": coordinate_mode == "model_mm",
        },
        "warnings": list(dict.fromkeys(str(item) for item in warnings)),
        "technical_limits": list(technical_limits),
    }
    return _json_value(report)
