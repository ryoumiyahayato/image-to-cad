from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .dxf_exporter import ExportResult
from .line_detect import LineSegment
from .reporting import REPORT_SCHEMA_VERSION, build_lineage


TECHNICAL_LIMITS = [
    "严重折叠、局部波浪和复杂非刚性形变不能保证整页误差小于 2%。",
    "取消在原生 OpenCV 或 OCR 单次调用返回后生效，无法安全强制终止调用内部。",
    "HATCH 封闭区域包含关系使用保守的轴对齐边界近似。",
    "圆形只有在达到置信度阈值并经人工确认后才导出；圆弧和建筑符号仍需人工复核。",
    "OCR TEXT 只导出高置信度候选，字符内容、位置和字体仍需人工校对。",
    "疑似文字区域会阻止局部短线进入 CAD，但复杂符号和细小结构可能仍需手动修正。",
    "扫描底图使用外部 IMAGE 引用，不嵌入 DXF/DWG；CAD 文件与 .scan.png 必须一起移动。",
    "DWG 输出依赖用户本机安装的 ODA File Converter；DXF 是本程序的原生输出。",
    "paper_mm 仅表示打印纸面坐标；未校准图纸比例时不得解释为工程 model_mm。",
    "粗笔画中心化属于保守启发式，墙体边界语义仍需人工复核。",
]


def _to_dict(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    return value


class ReportBuilder:
    """Build the one machine-readable report schema used by GUI and CLI."""

    @staticmethod
    def build(
        *,
        input_path: str | Path | None,
        original_shape: tuple[int, ...] | list[int] | None,
        corrected_shape: tuple[int, ...] | list[int] | None,
        perspective: dict[str, Any] | None,
        quality: Any,
        parameters: dict[str, Any],
        preprocess_stages: dict[str, Any],
        preprocess_resolution_scale: float,
        detection_resolution_scale: float,
        thick_stroke_centering: bool,
        raw_lines: list[LineSegment],
        lines: list[LineSegment],
        geometry_report: Any,
        geometry_resolution_scale: float,
        classification_report: Any,
        auxiliary: Any,
        export_result: ExportResult,
        calibration_source: str,
        coordinate_space: str,
        warnings: list[str] | tuple[str, ...],
        confirmed_circles: list[Any] | tuple[Any, ...] = (),
        intersection_split_report: Any = None,
        topology_report: Any = None,
        started_at_utc: datetime | str | None = None,
        duration_seconds: float | None = None,
        debug_directory: str | Path | None = None,
    ) -> dict[str, Any]:
        if started_at_utc is None:
            started_value = datetime.now(timezone.utc).isoformat()
        elif isinstance(started_at_utc, datetime):
            started_value = started_at_utc.isoformat()
        else:
            started_value = str(started_at_utc)

        if intersection_split_report is None:
            intersection_split_report = getattr(
                geometry_report,
                "intersection_split_report",
                None,
            )
        if topology_report is None:
            topology_report = getattr(geometry_report, "topology_report", None)

        geometry = _to_dict(geometry_report) or {}
        if isinstance(geometry, dict):
            geometry["resolution_scale"] = float(geometry_resolution_scale)

        normalized_perspective = dict(perspective or {})
        normalized_perspective.setdefault("applied", False)
        normalized_perspective.setdefault("automatic", False)
        normalized_perspective.setdefault("confidence", 0.0)
        normalized_perspective.setdefault("corners", None)
        normalized_perspective["corrected_shape"] = (
            list(corrected_shape) if corrected_shape is not None else None
        )

        calibrated_mm_per_pixel = (
            float(export_result.mm_per_pixel) if export_result.calibrated else None
        )
        drawing_units_per_pixel = float(export_result.mm_per_pixel)

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "application_version": __version__,
            "started_at_utc": started_value,
            "duration_seconds": duration_seconds,
            "input": {
                "path": str(input_path) if input_path is not None else None,
                "shape": list(original_shape) if original_shape is not None else None,
                "pdf_page": parameters.get("pdf_page"),
            },
            "perspective": normalized_perspective,
            "quality": _to_dict(quality),
            "parameters": parameters,
            "preprocessing": {
                "stages": {
                    name: list(image.shape) if hasattr(image, "shape") else image
                    for name, image in preprocess_stages.items()
                },
                "resolution_scale": float(preprocess_resolution_scale),
                "debug_directory": (
                    str(debug_directory) if debug_directory is not None else None
                ),
            },
            "detection": {
                "raw_line_count": len(raw_lines),
                "resolution_scale": float(detection_resolution_scale),
                "thick_stroke_centering": bool(thick_stroke_centering),
                "text_region_protection": bool(
                    parameters.get("protect_text_regions", False)
                ),
            },
            "geometry": geometry,
            "topology": {
                "intersection_splitting": _to_dict(intersection_split_report),
                "validation": _to_dict(topology_report),
            },
            "classification": _to_dict(classification_report),
            "auxiliary": _to_dict(auxiliary),
            "lineage": build_lineage(raw_lines, lines),
            "export": {
                "path": str(export_result.path),
                "output_format": export_result.output_format,
                "dwg_path": (
                    str(export_result.dwg_path)
                    if export_result.dwg_path is not None
                    else None
                ),
                "underlay_path": (
                    str(export_result.underlay_path)
                    if export_result.underlay_path is not None
                    else None
                ),
                "line_count": export_result.line_count,
                "skipped_line_count": export_result.skipped_line_count,
                "circle_count": export_result.circle_count,
                "skipped_circle_count": export_result.skipped_circle_count,
                "confirmed_circles": [_to_dict(item) for item in confirmed_circles],
                "text_count": export_result.text_count,
                "skipped_text_count": export_result.skipped_text_count,
                "mm_per_pixel": calibrated_mm_per_pixel,
                "drawing_units_per_pixel": drawing_units_per_pixel,
                "calibrated": export_result.calibrated,
                "calibration_source": calibration_source,
                "coordinate_space": coordinate_space,
            },
            "warnings": list(dict.fromkeys(str(item) for item in warnings if item)),
            "technical_limits": list(TECHNICAL_LIMITS),
        }
