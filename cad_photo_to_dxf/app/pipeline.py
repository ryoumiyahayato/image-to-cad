from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .dxf_exporter import ExportResult, export_dxf
from .geometry_cleaner import GeometryCleanParams, clean_geometry
from .image_loader import load_image, save_image
from .layer_classifier import classify_layers
from .line_detect import LineDetectionParams, LineSegment, detect_lines, render_line_preview
from .perspective import auto_correct
from .preprocess import PreprocessParams, preprocess_image
from .scale_calibrator import ScaleCalibration


@dataclass
class PipelineResult:
    original: np.ndarray
    corrected: np.ndarray
    binary: np.ndarray
    lines: list[LineSegment]
    preview: np.ndarray
    export: ExportResult


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path,
    preview_path: str | Path | None = None,
    calibration: ScaleCalibration | None = None,
    preprocess_params: PreprocessParams | None = None,
    detection_params: LineDetectionParams | None = None,
    clean_params: GeometryCleanParams | None = None,
    preserve_hatch: bool = True,
) -> PipelineResult:
    original = load_image(input_path)
    perspective_result = auto_correct(original)
    corrected = perspective_result.image if perspective_result is not None else original.copy()
    binary = preprocess_image(corrected, preprocess_params)
    raw_lines = detect_lines(binary, detection_params)
    cleaned = clean_geometry(raw_lines, clean_params)
    lines = classify_layers(cleaned, binary.shape, preserve_hatch=preserve_hatch)
    preview = render_line_preview(binary, lines)
    if preview_path is not None:
        save_image(preview_path, preview)
    result = export_dxf(lines, output_path, binary.shape[0], calibration)
    return PipelineResult(original, corrected, binary, lines, preview, result)
