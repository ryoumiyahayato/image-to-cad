from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

import numpy as np

from .auxiliary_recognition import AuxiliaryRecognitionResult
from .cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from .dxf_exporter import ExportResult, export_dxf
from .geometry_cleaner import GeometryCleanParams, GeometryCleanReport
from .image_loader import load_image, save_image
from .layer_classifier import ClassificationReport
from .line_detect import LineDetectionParams, LineSegment
from .perspective import (
    MIN_AUTOMATIC_PAPER_CONFIDENCE,
    PerspectiveResult,
    auto_correct,
    resolve_paper_aspect_ratio,
    resolve_paper_dimensions_mm,
)
from .pipeline_service import PipelineService
from .preprocess import PreprocessParams
from .quality import ImageQualityAssessment, assess_image_quality
from .report_builder import ReportBuilder
from .reporting import write_json_report
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
    perspective_applied = False
    rejected_low_confidence = False
    if perspective_result is None:
        if strict_perspective:
            raise PaperDetectionError(
                "Paper boundary could not be detected; use manual corners or --allow-uncorrected"
            )
        corrected = original.copy()
        warnings.append("自动纸张识别失败，已按未校正原图继续处理。")
    elif perspective_result.confidence < MIN_AUTOMATIC_PAPER_CONFIDENCE:
        if strict_perspective:
            raise PaperDetectionError(
                "Paper boundary confidence is too low for strict mode; "
                "confirm four manual corners or use --allow-uncorrected"
            )
        corrected = original.copy()
        rejected_low_confidence = True
        warnings.extend(perspective_result.warnings)
        warnings.append(
            "自动纸张候选置信度不足，未应用透视变换；已按原图继续处理。"
        )
    else:
        corrected = perspective_result.image
        perspective_applied = True
        warnings.extend(perspective_result.warnings)

    calibration_source = "explicit" if calibration is not None else "uncalibrated"
    coordinate_space = "model_mm" if calibration is not None else "pixel"
    if calibration is None and paper_dimensions is not None and perspective_applied:
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

    vectorization = PipelineService.vectorize(
        corrected,
        preprocess_params=preprocess_params,
        detection_params=detection_params,
        clean_params=clean_params,
        preserve_hatch=preserve_hatch,
        enable_auxiliary=enable_auxiliary,
        enable_ocr=enable_ocr,
        cancellation_token=cancellation_token,
        progress_callback=_subprogress(progress_callback, "vectorize", 0.10, 0.86),
    )
    warnings.extend(vectorization.warnings)
    binary = vectorization.binary
    raw_lines = vectorization.raw_lines
    lines = vectorization.lines
    preview = vectorization.preview
    if not lines and fail_on_empty:
        raise NoLinesDetectedError("No valid line entities were detected")

    if debug_dir is not None:
        diagnostics = Path(debug_dir)
        diagnostics.mkdir(parents=True, exist_ok=True)
        save_image(diagnostics / "00_corrected.png", corrected)
        for stage_name, stage_image in vectorization.preprocess_stages.items():
            save_image(diagnostics / f"{stage_name}.png", stage_image)
        save_image(diagnostics / "90_line_preview.png", preview)
    if preview_path is not None:
        save_image(preview_path, preview)

    checkpoint(cancellation_token)
    report_progress(progress_callback, "export", 0.90)
    export_result = export_dxf(lines, output_path, binary.shape[0], calibration)
    if export_result.skipped_line_count:
        warnings.append(
            f"导出时跳过 {export_result.skipped_line_count} 条无效或零长度线。"
        )

    elapsed = time.perf_counter() - started_clock
    report = ReportBuilder.build(
        input_path=input_path,
        original_shape=original.shape,
        corrected_shape=corrected.shape,
        perspective={
            "candidate_detected": perspective_result is not None,
            "applied": perspective_applied,
            "automatic": perspective_result.automatic if perspective_result else False,
            "confidence": perspective_result.confidence if perspective_result else 0.0,
            "minimum_strict_confidence": MIN_AUTOMATIC_PAPER_CONFIDENCE,
            "corners": perspective_result.corners if perspective_result else None,
            "target_aspect_ratio": target_aspect_ratio,
            "rejected_low_confidence": rejected_low_confidence,
        },
        quality=quality,
        parameters={
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
        preprocess_stages=vectorization.preprocess_stages,
        preprocess_resolution_scale=vectorization.preprocess_resolution_scale,
        detection_resolution_scale=vectorization.detection_resolution_scale,
        thick_stroke_centering=detection_params.center_thick_strokes,
        raw_lines=raw_lines,
        lines=lines,
        geometry_report=vectorization.geometry_report,
        geometry_resolution_scale=vectorization.geometry_resolution_scale,
        classification_report=vectorization.classification_report,
        auxiliary=vectorization.auxiliary,
        export_result=export_result,
        calibration_source=calibration_source,
        coordinate_space=coordinate_space,
        warnings=warnings,
        started_at_utc=started_at,
        duration_seconds=elapsed,
        debug_directory=debug_dir,
    )
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
        preprocess_stages=vectorization.preprocess_stages,
        perspective=perspective_result,
        quality=quality,
        geometry_report=vectorization.geometry_report,
        classification_report=vectorization.classification_report,
        auxiliary=vectorization.auxiliary,
        report=report,
        report_path=written_report_path,
    )
