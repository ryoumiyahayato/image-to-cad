from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

import ezdxf
import numpy as np
from scipy.spatial import cKDTree

from .fixture_validation import validate_fixture_directory
from .pipeline import run_pipeline
from .scale_calibrator import ScaleCalibration


@dataclass(frozen=True)
class DxfLine:
    start: tuple[float, float]
    end: tuple[float, float]
    layer: str

    @property
    def length(self) -> float:
        return math.hypot(
            self.end[0] - self.start[0],
            self.end[1] - self.start[1],
        )

    @property
    def midpoint(self) -> tuple[float, float]:
        return (
            (self.start[0] + self.end[0]) / 2.0,
            (self.start[1] + self.end[1]) / 2.0,
        )

    @property
    def angle_degrees(self) -> float:
        angle = math.degrees(
            math.atan2(
                self.end[1] - self.start[1],
                self.end[0] - self.start[0],
            )
        )
        return angle % 180.0


@dataclass(frozen=True)
class GeometryMetrics:
    candidate_line_count: int
    ground_truth_line_count: int
    endpoint_hausdorff: float
    sampled_hausdorff: float
    maximum_angle_error_degrees: float
    scale_relative_error: float
    candidate_layer_counts: dict[str, int]


@dataclass(frozen=True)
class FixtureBenchmarkResult:
    fixture_directory: Path
    fixture_id: str | None
    passed: bool
    errors: tuple[str, ...]
    metrics: GeometryMetrics | None
    output_dxf: Path | None
    report_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fixture_directory"] = str(self.fixture_directory)
        value["output_dxf"] = str(self.output_dxf) if self.output_dxf else None
        value["report_path"] = str(self.report_path) if self.report_path else None
        return value


def read_dxf_lines(path: str | Path) -> list[DxfLine]:
    document = ezdxf.readfile(path)
    lines: list[DxfLine] = []
    for entity in document.modelspace().query("LINE"):
        start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
        end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= 1e-9:
            continue
        lines.append(
            DxfLine(
                start=start,
                end=end,
                layer=str(entity.dxf.layer),
            )
        )
    return lines


def _symmetric_hausdorff(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) == 0 or len(right) == 0:
        return math.inf
    right_tree = cKDTree(right)
    left_tree = cKDTree(left)
    left_to_right = right_tree.query(left, k=1)[0]
    right_to_left = left_tree.query(right, k=1)[0]
    return max(float(np.max(left_to_right)), float(np.max(right_to_left)))


def _sample_lines(lines: list[DxfLine], samples_per_line: int = 17) -> np.ndarray:
    if not lines:
        return np.empty((0, 2), dtype=float)
    fractions = np.linspace(0.0, 1.0, samples_per_line)
    samples: list[np.ndarray] = []
    for line in lines:
        start = np.asarray(line.start, dtype=float)
        end = np.asarray(line.end, dtype=float)
        samples.append(start[None, :] + fractions[:, None] * (end - start)[None, :])
    return np.vstack(samples)


def _angle_difference(left: float, right: float) -> float:
    difference = abs(left - right) % 180.0
    return min(difference, 180.0 - difference)


def _bounding_diagonal(lines: list[DxfLine]) -> float:
    if not lines:
        return 0.0
    points = np.asarray(
        [point for line in lines for point in (line.start, line.end)],
        dtype=float,
    )
    extent = np.max(points, axis=0) - np.min(points, axis=0)
    return float(np.linalg.norm(extent))


def compare_dxf_lines(
    candidate: list[DxfLine],
    ground_truth: list[DxfLine],
) -> GeometryMetrics:
    candidate_endpoints = np.asarray(
        [point for line in candidate for point in (line.start, line.end)],
        dtype=float,
    ).reshape((-1, 2))
    truth_endpoints = np.asarray(
        [point for line in ground_truth for point in (line.start, line.end)],
        dtype=float,
    ).reshape((-1, 2))
    endpoint_hausdorff = _symmetric_hausdorff(candidate_endpoints, truth_endpoints)
    sampled_hausdorff = _symmetric_hausdorff(
        _sample_lines(candidate),
        _sample_lines(ground_truth),
    )

    maximum_angle_error = math.inf
    if candidate and ground_truth:
        truth_midpoints = np.asarray(
            [line.midpoint for line in ground_truth],
            dtype=float,
        )
        tree = cKDTree(truth_midpoints)
        maximum_angle_error = 0.0
        for line in candidate:
            _distance, index = tree.query(np.asarray(line.midpoint), k=1)
            maximum_angle_error = max(
                maximum_angle_error,
                _angle_difference(
                    line.angle_degrees,
                    ground_truth[int(index)].angle_degrees,
                ),
            )

    candidate_diagonal = _bounding_diagonal(candidate)
    truth_diagonal = _bounding_diagonal(ground_truth)
    if truth_diagonal <= 1e-9:
        scale_relative_error = math.inf
    else:
        scale_relative_error = abs(candidate_diagonal / truth_diagonal - 1.0)

    layer_counts: dict[str, int] = {}
    for line in candidate:
        layer_counts[line.layer] = layer_counts.get(line.layer, 0) + 1

    return GeometryMetrics(
        candidate_line_count=len(candidate),
        ground_truth_line_count=len(ground_truth),
        endpoint_hausdorff=endpoint_hausdorff,
        sampled_hausdorff=sampled_hausdorff,
        maximum_angle_error_degrees=maximum_angle_error,
        scale_relative_error=scale_relative_error,
        candidate_layer_counts=layer_counts,
    )


def _calibration_from_manifest(manifest: dict[str, Any]) -> ScaleCalibration | None:
    if manifest.get("coordinate_mode") != "model_mm":
        return None
    reference = manifest.get("calibration_reference")
    if not isinstance(reference, dict):
        raise ValueError("model_mm fixture requires calibration_reference")
    start = reference.get("start_px")
    end = reference.get("end_px")
    length_mm = reference.get("length_mm")
    if (
        not isinstance(start, list)
        or len(start) != 2
        or not isinstance(end, list)
        or len(end) != 2
        or isinstance(length_mm, bool)
        or not isinstance(length_mm, (int, float))
    ):
        raise ValueError("calibration_reference is invalid")
    return ScaleCalibration(
        (float(start[0]), float(start[1])),
        (float(end[0]), float(end[1])),
        float(length_mm),
    )


def _maximum_corner_error(
    actual: object,
    expected: object,
) -> float:
    if actual is None:
        return math.inf
    actual_array = np.asarray(actual, dtype=float)
    expected_array = np.asarray(expected, dtype=float)
    if actual_array.shape != (4, 2) or expected_array.shape != (4, 2):
        return math.inf
    return float(np.max(np.linalg.norm(actual_array - expected_array, axis=1)))


def run_fixture_benchmark(
    fixture_directory: str | Path,
    output_root: str | Path,
) -> FixtureBenchmarkResult:
    fixture = Path(fixture_directory)
    qualification = validate_fixture_directory(fixture)
    if not qualification.passed:
        return FixtureBenchmarkResult(
            fixture,
            qualification.fixture_id,
            False,
            tuple(f"qualification: {error}" for error in qualification.errors),
            None,
            None,
            None,
        )

    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    fixture_id = str(manifest["id"])
    output_directory = Path(output_root) / fixture_id
    output_directory.mkdir(parents=True, exist_ok=True)
    output_dxf = output_directory / "candidate.dxf"
    preview_path = output_directory / "preview.png"
    report_path = output_directory / "processing-report.json"
    errors: list[str] = []

    try:
        calibration = _calibration_from_manifest(manifest)
        paper = manifest["paper"]
        pipeline_result = run_pipeline(
            input_path=fixture / manifest["source_file"],
            output_path=output_dxf,
            preview_path=preview_path,
            calibration=calibration,
            report_path=report_path,
            debug_dir=output_directory / "debug",
            paper_size=str(paper["size"]),
            paper_orientation=str(paper["orientation"]),
            strict_perspective=True,
            fail_on_empty=True,
            enable_auxiliary=True,
        )
    except Exception as exc:
        return FixtureBenchmarkResult(
            fixture,
            fixture_id,
            False,
            (f"pipeline failed: {exc}",),
            None,
            output_dxf if output_dxf.exists() else None,
            report_path if report_path.exists() else None,
        )

    expected_mode = manifest["coordinate_mode"]
    if pipeline_result.export.coordinate_mode != expected_mode:
        errors.append(
            "coordinate mode mismatch: "
            f"expected {expected_mode}, got {pipeline_result.export.coordinate_mode}"
        )

    corner_error = _maximum_corner_error(
        pipeline_result.perspective.corners if pipeline_result.perspective else None,
        manifest["expected_corners_px"],
    )
    corner_tolerance = float(manifest.get("corner_tolerance_px", 10.0))
    if corner_error > corner_tolerance:
        errors.append(
            f"paper corner error {corner_error:.6f}px exceeds {corner_tolerance:.6f}px"
        )

    candidate_lines = read_dxf_lines(output_dxf)
    truth_lines = read_dxf_lines(fixture / manifest["ground_truth_file"])
    metrics = compare_dxf_lines(candidate_lines, truth_lines)

    expected_entities = manifest["expected_entities"]
    if not (
        int(expected_entities["line_min"])
        <= metrics.candidate_line_count
        <= int(expected_entities["line_max"])
    ):
        errors.append(
            f"candidate LINE count {metrics.candidate_line_count} is outside expected range"
        )

    for layer, expected_range in manifest["expected_layers"].items():
        actual = metrics.candidate_layer_counts.get(layer, 0)
        if not int(expected_range["min"]) <= actual <= int(expected_range["max"]):
            errors.append(f"layer {layer} count {actual} is outside expected range")

    tolerances = manifest["tolerances"]
    checks = (
        (
            "endpoint Hausdorff",
            metrics.endpoint_hausdorff,
            float(tolerances["endpoint_mm"]),
        ),
        (
            "angle",
            metrics.maximum_angle_error_degrees,
            float(tolerances["angle_degrees"]),
        ),
        (
            "scale",
            metrics.scale_relative_error,
            float(tolerances["scale_relative"]),
        ),
        (
            "sampled Hausdorff",
            metrics.sampled_hausdorff,
            float(tolerances["hausdorff_mm"]),
        ),
    )
    for label, actual, maximum in checks:
        if not math.isfinite(actual) or actual > maximum:
            errors.append(f"{label} error {actual:.6f} exceeds {maximum:.6f}")

    return FixtureBenchmarkResult(
        fixture_directory=fixture,
        fixture_id=fixture_id,
        passed=not errors,
        errors=tuple(errors),
        metrics=metrics,
        output_dxf=output_dxf,
        report_path=report_path,
    )
