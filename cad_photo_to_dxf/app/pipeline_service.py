from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .auxiliary_recognition import AuxiliaryRecognitionResult, recognize_auxiliary
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .geometry_cleaner import GeometryCleanParams, GeometryCleanReport
from .geometry_normalized import clean_geometry_with_report
from .layer_classifier import ClassificationReport, classify_layers_with_report
from .line_detect import LineDetectionParams, LineSegment, detect_lines, render_line_preview
from .preprocess import PreprocessParams, PreprocessResult, preprocess_image_with_stages
from .resolution import image_resolution_scale
from .topology import (
    IntersectionSplitReport,
    TopologyValidationReport,
    build_topology,
)


@dataclass
class VectorizationResult:
    binary: np.ndarray
    preprocess_stages: dict[str, np.ndarray]
    raw_lines: list[LineSegment]
    lines: list[LineSegment]
    geometry_report: GeometryCleanReport
    intersection_split_report: IntersectionSplitReport
    topology_report: TopologyValidationReport
    classification_report: ClassificationReport
    auxiliary: AuxiliaryRecognitionResult | None
    preview: np.ndarray
    preprocess_resolution_scale: float
    detection_resolution_scale: float
    geometry_resolution_scale: float
    warnings: tuple[str, ...]


def _subprogress(
    callback: ProgressCallback | None,
    prefix: str,
    start: float,
    end: float,
) -> ProgressCallback | None:
    if callback is None:
        return None

    def emit(stage: str, fraction: float) -> None:
        callback(f"{prefix}:{stage}", start + (end - start) * float(fraction))

    return emit


class PipelineService:
    """One core image-to-vector path shared by GUI and CLI."""

    @staticmethod
    def preprocess(
        image: np.ndarray,
        params: PreprocessParams | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PreprocessResult:
        return preprocess_image_with_stages(
            image,
            params,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )

    @staticmethod
    def vectorize(
        corrected_image: np.ndarray,
        *,
        existing_binary: np.ndarray | None = None,
        preprocess_params: PreprocessParams | None = None,
        detection_params: LineDetectionParams | None = None,
        clean_params: GeometryCleanParams | None = None,
        preserve_hatch: bool = True,
        enable_auxiliary: bool = False,
        enable_ocr: bool = False,
        cancellation_token: CancellationToken | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> VectorizationResult:
        if corrected_image is None or corrected_image.size == 0:
            raise ValueError("Corrected image must not be empty")
        preprocess_params = preprocess_params or PreprocessParams()
        detection_params = detection_params or LineDetectionParams()
        clean_params = clean_params or GeometryCleanParams()
        warnings: list[str] = []

        checkpoint(cancellation_token)
        stages: dict[str, np.ndarray] = {}
        if existing_binary is None:
            preprocessing = PipelineService.preprocess(
                corrected_image,
                preprocess_params,
                cancellation_token=cancellation_token,
                progress_callback=_subprogress(progress_callback, "preprocess", 0.0, 0.25),
            )
            binary = preprocessing.image
            stages = preprocessing.stages
            preprocess_scale = preprocessing.resolution_scale
        else:
            if existing_binary.size == 0:
                raise ValueError("Existing binary image must not be empty")
            binary = existing_binary.copy()
            preprocess_scale = image_resolution_scale(binary.shape)
            report_progress(progress_callback, "preprocess:reuse", 0.25)

        checkpoint(cancellation_token)
        raw_lines = detect_lines(
            binary,
            detection_params,
            cancellation_token=cancellation_token,
            progress_callback=_subprogress(progress_callback, "detect", 0.27, 0.58),
        )

        report_progress(progress_callback, "geometry", 0.62)
        geometry = clean_geometry_with_report(
            raw_lines,
            clean_params,
            cancellation_token,
        )
        geometry_scale = float(getattr(geometry.report, "resolution_scale", 1.0))
        if geometry.report.merge_pair_limit_reached:
            warnings.append("共线合并达到最大比较次数，部分候选保持未合并状态。")

        checkpoint(cancellation_token)
        report_progress(progress_callback, "topology", 0.72)
        topology = build_topology(
            geometry.lines,
            intersection_tolerance=max(0.5, 0.75 * geometry_scale),
            endpoint_tolerance=max(0.25, 0.5 * geometry_scale),
            gap_tolerance=max(2.0, clean_params.snap_distance * geometry_scale),
            max_pair_checks=clean_params.max_pair_checks,
            cancellation_token=cancellation_token,
        )
        if topology.split_report.pair_limit_reached:
            warnings.append("交点分割达到最大比较次数，拓扑验证可能不完整。")
        if topology.validation_report.exact_duplicate_lines:
            warnings.append(
                f"拓扑验证仍发现 {topology.validation_report.exact_duplicate_lines} 条完全重复线。"
            )
        if topology.validation_report.unresolved_interior_intersections:
            warnings.append(
                "拓扑验证发现未解析的内部交叉点："
                f"{topology.validation_report.unresolved_interior_intersections}。"
            )
        if topology.validation_report.small_gap_pairs:
            warnings.append(
                f"拓扑验证发现 {topology.validation_report.small_gap_pairs} 组悬空小间隙。"
            )

        checkpoint(cancellation_token)
        report_progress(progress_callback, "classification", 0.82)
        classification = classify_layers_with_report(
            topology.lines,
            binary.shape,
            preserve_hatch=preserve_hatch,
            cancellation_token=cancellation_token,
        )

        auxiliary: AuxiliaryRecognitionResult | None = None
        if enable_auxiliary or enable_ocr:
            report_progress(progress_callback, "auxiliary", 0.90)
            auxiliary = recognize_auxiliary(
                binary,
                enable_ocr=enable_ocr,
                cancellation_token=cancellation_token,
            )
            warnings.extend(auxiliary.warnings)

        checkpoint(cancellation_token)
        preview = render_line_preview(binary, classification.lines)
        report_progress(progress_callback, "preview", 1.0)
        return VectorizationResult(
            binary=binary,
            preprocess_stages=stages,
            raw_lines=raw_lines,
            lines=classification.lines,
            geometry_report=geometry.report,
            intersection_split_report=topology.split_report,
            topology_report=topology.validation_report,
            classification_report=classification.report,
            auxiliary=auxiliary,
            preview=preview,
            preprocess_resolution_scale=preprocess_scale,
            detection_resolution_scale=image_resolution_scale(binary.shape),
            geometry_resolution_scale=geometry_scale,
            warnings=tuple(dict.fromkeys(warnings)),
        )
