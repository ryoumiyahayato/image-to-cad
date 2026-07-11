from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

import numpy as np

from . import __version__
from .auxiliary_recognition import AuxiliaryRecognitionResult, recognize_auxiliary
from .cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from .dxf_exporter import ExportResult, export_dxf
from .geometry_cleaner import GeometryCleanParams, GeometryCleanReport
from .geometry_normalized import clean_geometry_with_report
from .image_loader import load_image, save_image
from .layer_classifier import (
    ClassificationReport,
    classify_layers_with_report,
)
from .line_detect import LineDetectionParams, LineSegment, detect_lines, render_line_preview
from .perspective import (
    MIN_AUTOMATIC_PAPER_CONFIDENCE,
    PerspectiveResult,
    auto_correct,
    resolve_paper_aspect_ratio,
    resolve_paper_dimensions_mm,
)
from .preprocess import PreprocessParams, preprocess_image_with_stages
from .quality import ImageQualityAssessment, assess_image_quality
from .reporting import REPORT_SCHEMA_VERSION, build_lineage, write_json_report
from .resolution import image_resolution_scale
from .scale_calibrator import ScaleCalibration


class PipelineError(RuntimeError):
    exit_code = 1


class InvalidInputError(PipelineError):
    exit_code = 3


class PaperDetectionError(PipelineError):
    exit_code = 4


class NoLinesDetectedError(PipelineError):
    exit_code = 5


@dataclass
class PipelineResult:
    original: np.ndarray
    corrected: np.ndarray
    binary: np.ndarray
    raw_lines: list[LineSegment]
    lines: list[LineSegment]
    preview: np.ndarray
    export: ExportResult
    preprocess_stages: dict[str, np.ndarray]
    perspective: PerspectiveResult | None
    quality: ImageQualityAssessment
    geometry_report: GeometryCleanReport
    classification_report: ClassificationReport
    auxiliary: AuxiliaryRecognitionResult | None
    report: dict[str, Any]
    report_path: Path | None


def _subprogress(
    callback: ProgressCallback | None,
    prefix: str,
    start: float,
    end: float,
) -> ProgressCallback | None:
    if callback is None:
        return None

    def emit(stage: str, fraction: float) -> None:
        callback(f"{prefix}:{stage}", start + (end - start) * fraction)

    return emit


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path,
    preview_path: str | Path | None = None,
    calibration: ScaleCalibration | None = None,
    preprocess_params: PreprocessParams | None = None,
    detection_params: LineDetectionParams | None = None,
    clean_params: GeometryCleanParams | None = None,
    preserve_hatch: bool = True,
    *,
    report_path: str | Path | None = None,
    debug_dir: str | Path | None = None,
    paper_size: str | None = None,
    paper_orientation: str = "auto",
    custom_paper_width_mm: float | None = None,
    custom_paper_height_mm: float | None = None,
    target_aspect_ratio: float | None = None,
    strict_perspective: bool = False,
    fail_on_empty: bool = False,
    enable_auxiliary: bool = False,
    enable_ocr: bool = False,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> PipelineResult:
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    warnings: list[str] = []
    preprocess_params = preprocess_params or PreprocessParams()
    detection_params = detection_params or LineDetectionParams()
    clean_params = clean_params or GeometryCleanParams()

    checkpoint(cancellation_token)
    report_progress(progress_callback, "load", 0.01)
    original = load_image(input_path)
    quality = assess_image_quality(original, cancellation_token)
    warnings.extend(quality.warnings)
    if quality.likely_blank and strict_perspective:
        raise InvalidInputError("Input image is effectively blank")

    if target_aspect_ratio is None:
        target_aspect_ratio = resolve_paper_aspect_ratio(
            paper_size,
            custom_paper_width_mm,
            custom_paper_height_mm,
            orientation=paper_orientation,
            observed_landscape=original.shape[1] >= original.shape[0],
        )

    paper_dimensions = resolve_paper_dimensions_mm(
        paper_size,
        custom_paper_width_mm,
        custom_paper_height_mm,
        orientation=paper_orientation,
        observed_landscape=original.shape[1] >= original.shape[0],
    )

    checkpoint(cancellation_token)
    report_progress(progress_callback, "perspective", 0.08)
    perspective_result = auto_correct(original, target_aspect_ratio)
    if perspective_result is None:
        if strict_perspective:
            raise PaperDetectionError(
                "Paper boundary could not be detected; use manual corners or --allow-uncorrected"
            )
        corrected = original.copy()
        warnings.append("自动纸张识别失败，已按未校正原图继续处理。")
    elif strict_perspective and (
        perspective_result.confidence < MIN_AUTOMATIC_PAPER_CONFIDENCE
    ):
        raise PaperDetectionError(
            "Paper boundary confidence is too low for strict mode; "
            "confirm four manual corners or use --allow-uncorrected"
        )
    else:
        corrected = perspective_result.image
        warnings.extend(perspective_result.warnings)

    calibration_source = "explicit" if calibration is not None else "uncalibrated"
    coordinate_space = "model_mm" if calibration is not None else "pixel"
    if calibration is None and paper_dimensions is not None and perspective_result is not None:
        calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, corrected.shape[1] - 1)), 0.0),
            float(paper_dimensions[0]),
        )
        calibration_source = "paper_dimensions"
        coordinate_space = "paper_mm"
        warnings.append(
            "导出坐标为纸面毫米（paper_mm），不是原始设计模型尺寸；"
            "恢复 model_mm 必须提供图纸比例或已知实际尺寸。"
        )

    checkpoint(cancellation_token)
    preprocessing = preprocess_image_with_stages(
        corrected,
        preprocess_params,
        cancellation_token=cancellation_token,
        progress_callback=_subprogress(progress_callback, "preprocess", 0.10, 0.32),
    )
    binary = preprocessing.image

    if debug_dir is not None:
        diagnostics = Path(debug_dir)
        diagnostics.mkdir(parents=True, exist_ok=True)
        save_image(diagnostics / "00_corrected.png", corrected)
        for stage_name, stage_image in preprocessing.stages.items():
            save_image(diagnostics / f"{stage_name}.png", stage_image)

    checkpoint(cancellation_token)
    raw_lines = detect_lines(
        binary,
        detection_params,
        cancellation_token=cancellation_token,
        progress_callback=_subprogress(progress_callback, "detect", 0.34, 0.58),
    )
    report_progress(progress_callback, "geometry", 0.60)
    geometry_result = clean_geometry_with_report(
        raw_lines,
        clean_params,
        cancellation_token=cancellation_token,
    )
    if geometry_result.report.merge_pair_limit_reached:
        warnings.append("共线合并达到最大比较次数，部分候选保持未合并状态。")

    checkpoint(cancellation_token)
    report_progress(progress_callback, "classification", 0.72)
    classification_result = classify_layers_with_report(
        geometry_result.lines,
        binary.shape,
        preserve_hatch=preserve_hatch,
        cancellation_token=cancellation_token,
    )
    lines = classification_result.lines
    if not lines and fail_on_empty:
        raise NoLinesDetectedError("No valid line entities were detected")

    auxiliary: AuxiliaryRecognitionResult | None = None
    if enable_auxiliary or enable_ocr:
        auxiliary = recognize_auxiliary(
            binary,
            enable_ocr=enable_ocr,
            cancellation_token=cancellation_token,
            progress_callback=_subprogress(progress_callback, "auxiliary", 0.75, 0.86),
        )
        warnings.extend(auxiliary.warnings)

    checkpoint(cancellation_token)
    preview = render_line_preview(binary, lines)
    if preview_path is not None:
        save_image(preview_path, preview)
    if debug_dir is not None:
        save_image(Path(debug_dir) / "90_line_preview.png", preview)

    report_progress(progress_callback, "export", 0.9)
    export_result = export_dxf(lines, output_path, binary.shape[0], calibration)
    if export_result.skipped_line_count:
        warnings.append(
            f"导出时跳过 {export_result.skipped_line_count} 条无效或零长度线。"
        )

    elapsed = time.perf_counter() - started_clock
    lineage = build_lineage(raw_lines, lines)
    geometry_report = asdict(geometry_result.report)
    geometry_report["resolution_scale"] = float(
        getattr(geometry_result.report, "resolution_scale", 1.0)
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "application_version": __version__,
        "started_at_utc": started_at.isoformat(),
        "duration_seconds": elapsed,
        "input": {
            "path": str(Path(input_path)),
            "shape": list(original.shape),
        },
        "perspective": {
            "applied": perspective_result is not None,
            "automatic": perspective_result.automatic if perspective_result else False,
            "confidence": perspective_result.confidence if perspective_result else 0.0,
            "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
            "corners": perspective_result.corners if perspective_result else None,
            "target_aspect_ratio": target_aspect_ratio,
            "corrected_shape": list(corrected.shape),
        },
        "quality": asdict(quality),
        "parameters": {
            "preprocess": asdict(preprocess_params),
            "line_detection": asdict(detection_params),
            "geometry_cleaning": asdict(clean_params),
            "paper_size": paper_size,
            "paper_orientation": paper_orientation,
            "paper_dimensions_mm": paper_dimensions,
            "strict_perspective": strict_perspective,
            "preserve_hatch": preserve_hatch,
            "auxiliary_enabled": enable_auxiliary or enable_ocr,
            "ocr_enabled": enable_ocr,
        },
        "preprocessing": {
            "stages": {
                name: list(image.shape) for name, image in preprocessing.stages.items()
            },
            "resolution_scale": preprocessing.resolution_scale,
            "debug_directory": str(debug_dir) if debug_dir is not None else None,
        },
        "detection": {
            "raw_line_count": len(raw_lines),
            "resolution_scale": image_resolution_scale(binary.shape),
            "thick_stroke_centering": detection_params.center_thick_strokes,
        },
        "geometry": geometry_report,
        "classification": asdict(classification_result.report),
        "auxiliary": asdict(auxiliary) if auxiliary is not None else None,
        "lineage": lineage,
        "export": {
            "path": str(export_result.path),
            "line_count": export_result.line_count,
            "skipped_line_count": export_result.skipped_line_count,
            "mm_per_pixel": export_result.mm_per_pixel,
            "calibrated": export_result.calibrated,
            "calibration_source": calibration_source,
            "coordinate_space": coordinate_space,
        },
        "warnings": list(dict.fromkeys(warnings)),
        "technical_limits": [
            "严重折叠、局部波浪和复杂非刚性形变不能保证整页误差小于 2%。",
            "取消在原生 OpenCV 或 OCR 单次调用返回后生效，无法安全强制终止调用内部。",
            "HATCH 封闭区域包含关系使用保守的轴对齐边界近似。",
            "OCR、圆弧、尺寸文字和建筑符号仅作为辅助候选。",
            "paper_mm 仅表示打印纸面坐标；未校准图纸比例时不得解释为工程 model_mm。",
            "粗笔画中心化属于保守启发式，墙体边界语义仍需人工复核。",
        ],
    }
    written_report_path: Path | None = None
    if report_path is not None:
        written_report_path = write_json_report(report_path, report)
    report_progress(progress_callback, "complete", 1.0)
    checkpoint(cancellation_token)

    return PipelineResult(
        original=original,
        corrected=corrected,
        binary=binary,
        raw_lines=raw_lines,
        lines=lines,
        preview=preview,
        export=export_result,
        preprocess_stages=preprocessing.stages,
        perspective=perspective_result,
        quality=quality,
        geometry_report=geometry_result.report,
        classification_report=classification_result.report,
        auxiliary=auxiliary,
        report=report,
        report_path=written_report_path,
    )
