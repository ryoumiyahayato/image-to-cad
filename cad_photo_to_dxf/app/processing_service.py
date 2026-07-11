from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .auxiliary_recognition import AuxiliaryRecognitionResult, recognize_auxiliary
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .geometry_cleaner import (
    GeometryCleanParams,
    GeometryCleanReport,
    clean_geometry_with_report,
)
from .layer_classifier import (
    ClassificationReport,
    classify_layers_with_report,
)
from .line_detect import (
    LineDetectionParams,
    LineSegment,
    detect_lines,
    effective_line_detection_params,
    render_line_preview,
)
from .preprocess import PreprocessParams, PreprocessResult, preprocess_image_with_stages


@dataclass(frozen=True)
class ProcessingConfig:
    preprocess: PreprocessParams
    detection: LineDetectionParams
    cleaning: GeometryCleanParams
    preserve_hatch: bool = True
    enable_auxiliary: bool = False
    enable_ocr: bool = False


@dataclass
class ProcessingResult:
    binary: np.ndarray
    preprocess_stages: dict[str, np.ndarray]
    raw_lines: list[LineSegment]
    lines: list[LineSegment]
    geometry_report: GeometryCleanReport
    classification_report: ClassificationReport
    auxiliary: AuxiliaryRecognitionResult | None
    preview: np.ndarray
    effective_detection_params: LineDetectionParams
    detection_resolution_factor: float


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


def process_corrected_image(
    corrected: np.ndarray,
    config: ProcessingConfig,
    *,
    existing_binary: np.ndarray | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingResult:
    """Run the shared post-perspective pipeline used by both CLI and GUI."""
    checkpoint(cancellation_token)
    stages: dict[str, np.ndarray] = {}
    if existing_binary is None:
        preprocessing: PreprocessResult = preprocess_image_with_stages(
            corrected,
            config.preprocess,
            cancellation_token=cancellation_token,
            progress_callback=_subprogress(
                progress_callback,
                "preprocess",
                0.00,
                0.28,
            ),
        )
        binary = preprocessing.image
        stages = preprocessing.stages
    else:
        binary = existing_binary.copy()
        report_progress(progress_callback, "preprocess:reused", 0.28)

    effective_detection, detection_factor = effective_line_detection_params(
        config.detection,
        binary.shape,
    )
    raw_lines = detect_lines(
        binary,
        effective_detection,
        cancellation_token=cancellation_token,
        progress_callback=_subprogress(
            progress_callback,
            "detect",
            0.30,
            0.64,
        ),
    )

    report_progress(progress_callback, "geometry", 0.68)
    geometry = clean_geometry_with_report(
        raw_lines,
        config.cleaning,
        cancellation_token,
    )

    report_progress(progress_callback, "classification", 0.82)
    classification = classify_layers_with_report(
        geometry.lines,
        binary.shape,
        preserve_hatch=config.preserve_hatch,
        cancellation_token=cancellation_token,
    )

    auxiliary: AuxiliaryRecognitionResult | None = None
    if config.enable_auxiliary or config.enable_ocr:
        auxiliary = recognize_auxiliary(
            binary,
            enable_ocr=config.enable_ocr,
            cancellation_token=cancellation_token,
            progress_callback=_subprogress(
                progress_callback,
                "auxiliary",
                0.84,
                0.96,
            ),
        )

    checkpoint(cancellation_token)
    preview = render_line_preview(binary, classification.lines)
    report_progress(progress_callback, "preview", 1.0)
    return ProcessingResult(
        binary=binary,
        preprocess_stages=stages,
        raw_lines=raw_lines,
        lines=classification.lines,
        geometry_report=geometry.report,
        classification_report=classification.report,
        auxiliary=auxiliary,
        preview=preview,
        effective_detection_params=effective_detection,
        detection_resolution_factor=detection_factor,
    )
