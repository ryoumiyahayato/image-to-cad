from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

import numpy as np

from . import __version__
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
    PerspectiveResult,
    auto_correct,
    resolve_paper_aspect_ratio,
    resolve_paper_dimensions_mm,
)
from .preprocess import PreprocessParams
from .processing_service import ProcessingConfig, process_corrected_image
from .quality import ImageQualityAssessment, assess_image_quality
from .reporting import build_processing_report, write_json_report
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
                "Paper boundary could not be detected with sufficient confidence; "
                "use manual corners or --allow-uncorrected"
            )
        corrected = original.copy()
        warnings.append("自动纸张识别失败或置信度不足，已按未校正原图继续处理。")
    else:
        corrected = perspective_result.image
        warnings.extend(perspective_result.warnings)

    coordinate_mode = "model_mm" if calibration is not None else "pixel_units"
    calibration_source = "known_dimension" if calibration is not None else "uncalibrated"
    if calibration is not None:
        warnings.append("模型尺寸由用户提供的已知长度校准；仍需用独立尺寸复核。")
    if calibration is None and paper_dimensions is not None and perspective_result is not None:
        calibration = ScaleCalibration(
            (0.0, 0.0),
            (float(max(1, corrected.shape[1] - 1)), 0.0),
            float(paper_dimensions[0]),
        )
        coordinate_mode = "paper_mm"
        calibration_source = "paper_dimensions"
        warnings.append(
            "当前导出为 paper-space 纸面毫米坐标，不是原始工程 model-space 设计尺寸。"
        )
        warnings.append("纸面比例由纸张外边界推导；角点必须准确落在纸张外缘。")
    elif calibration is None:
        warnings.append("当前导出为无单位像素坐标；未声明毫米或工程真实尺寸。")

    checkpoint(cancellation_token)
    processing = process_corrected_image(
        corrected,
        ProcessingConfig(
            preprocess=preprocess_params,
            detection=detection_params,
            cleaning=clean_params,
            preserve_hatch=preserve_hatch,
            enable_auxiliary=enable_auxiliary,
            enable_ocr=enable_ocr,
        ),
        cancellation_token=cancellation_token,
        progress_callback=_subprogress(progress_callback, "processing", 0.10, 0.86),
    )
    binary = processing.binary
    raw_lines = processing.raw_lines
    lines = processing.lines
    auxiliary = processing.auxiliary

    if processing.geometry_report.merge_pair_limit_reached:
        warnings.append("共线合并达到最大比较次数，部分候选保持未合并状态。")
    if auxiliary is not None:
        warnings.extend(auxiliary.warnings)
    if not lines and fail_on_empty:
        raise NoLinesDetectedError("No valid line entities were detected")

    if preview_path is not None:
        save_image(preview_path, processing.preview)
    if debug_dir is not None:
        diagnostics = Path(debug_dir)
        diagnostics.mkdir(parents=True, exist_ok=True)
        save_image(diagnostics / "00_corrected.png", corrected)
        for stage_name, stage_image in processing.preprocess_stages.items():
            save_image(diagnostics / f"{stage_name}.png", stage_image)
        save_image(diagnostics / "90_line_preview.png", processing.preview)

    report_progress(progress_callback, "export", 0.90)
    export_result = export_dxf(
        lines,
        output_path,
        binary.shape[0],
        calibration,
        coordinate_mode=coordinate_mode,
    )
    if export_result.skipped_line_count:
        warnings.append(
            f"导出时跳过 {export_result.skipped_line_count} 条无效或零长度线。"
        )

    elapsed = time.perf_counter() - started_clock
    report = build_processing_report(
        application_version=__version__,
        started_at_utc=started_at.isoformat(),
        duration_seconds=elapsed,
        input_path=input_path,
        input_shape=original.shape,
        perspective={
            "applied": perspective_result is not None,
            "automatic": perspective_result.automatic if perspective_result else False,
            "confidence": perspective_result.confidence if perspective_result else 0.0,
            "corners": perspective_result.corners if perspective_result else None,
            "target_aspect_ratio": target_aspect_ratio,
            "corrected_shape": list(corrected.shape),
        },
        quality=quality,
        parameters={
            "preprocess": asdict(preprocess_params),
            "line_detection_requested": asdict(detection_params),
            "line_detection_effective": asdict(
                processing.effective_detection_params
            ),
            "line_detection_resolution_factor": (
                processing.detection_resolution_factor
            ),
            "geometry_cleaning": asdict(clean_params),
            "paper_size": paper_size,
            "paper_orientation": paper_orientation,
            "paper_dimensions_mm": paper_dimensions,
            "preserve_hatch": preserve_hatch,
            "auxiliary_enabled": enable_auxiliary or enable_ocr,
            "ocr_enabled": enable_ocr,
        },
        preprocess_stages=processing.preprocess_stages,
        debug_directory=debug_dir,
        raw_lines=raw_lines,
        final_lines=lines,
        geometry_report=processing.geometry_report,
        classification_report=processing.classification_report,
        auxiliary=auxiliary,
        export_result=export_result,
        calibration_source=calibration_source,
        warnings=warnings,
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
        preview=processing.preview,
        export=export_result,
        preprocess_stages=processing.preprocess_stages,
        perspective=perspective_result,
        quality=quality,
        geometry_report=processing.geometry_report,
        classification_report=processing.classification_report,
        auxiliary=auxiliary,
        report=report,
        report_path=written_report_path,
    )
