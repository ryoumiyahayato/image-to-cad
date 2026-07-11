from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units
import numpy as np

from .auxiliary_recognition import MIN_CIRCLE_EXPORT_CONFIDENCE, CircleCandidate
from .line_detect import LineSegment
from .scale_calibrator import ScaleCalibration


@dataclass(frozen=True)
class ExportResult:
    path: Path
    line_count: int
    mm_per_pixel: float
    calibrated: bool
    skipped_line_count: int = 0
    circle_count: int = 0
    skipped_circle_count: int = 0


LAYER_STYLES = {
    "OUTLINE": {"color": 1, "lineweight": 50},
    "WALL_OR_FRAME": {"color": 3, "lineweight": 25},
    "GRID_OR_AXIS": {"color": 5, "lineweight": 13},
    "HATCH": {"color": 6, "lineweight": 9},
    "HATCH_CANDIDATE": {"color": 4, "lineweight": 9},
    "DETAIL": {"color": 7, "lineweight": 9},
    "CIRCLE_CONFIRMED": {"color": 2, "lineweight": 18},
}


def filter_exportable_circles(
    circles: Sequence[CircleCandidate],
) -> list[CircleCandidate]:
    """Return the exact candidates eligible to become DXF CIRCLE entities."""
    valid: list[CircleCandidate] = []
    for circle in circles:
        values = (
            float(circle.center[0]),
            float(circle.center[1]),
            float(circle.radius),
            float(circle.confidence),
        )
        if (
            all(isfinite(value) for value in values)
            and circle.radius > 1e-9
            and circle.confidence >= MIN_CIRCLE_EXPORT_CONFIDENCE
        ):
            valid.append(circle)
    return valid


def export_dxf(
    lines: list[LineSegment],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    circles: list[CircleCandidate] | None = None,
) -> ExportResult:
    """Export editable LINE entities and explicitly confirmed CIRCLE entities.

    Uncalibrated coordinates remain unitless. A DXF is declared millimetres only
    when a paper- or model-space calibration was supplied.
    """
    if int(image_height) <= 0:
        raise ValueError("Image height must be greater than zero")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    calibrated = calibration is not None
    scale = calibration.mm_per_pixel if calibrated else 1.0
    if not isfinite(float(scale)) or scale <= 0:
        raise ValueError("Export scale must be a positive finite number")

    doc = ezdxf.new("R2010", setup=True)
    if calibrated:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
    else:
        # DXF $INSUNITS value 0 means unitless. This prevents CAD software from
        # interpreting raw pixel coordinates as physical millimetres.
        doc.units = 0
        doc.header["$INSUNITS"] = 0
    doc.header["$LUNITS"] = 2

    for layer_name, style in LAYER_STYLES.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    valid_lines: list[LineSegment] = []
    coordinates: list[tuple[float, float]] = []
    for line in lines:
        values = np.array([line.x1, line.y1, line.x2, line.y2], dtype=float)
        if not np.isfinite(values).all() or line.length <= 1e-9:
            continue
        # Image Y grows downward; CAD Y grows upward.
        start = (line.x1 * scale, (image_height - 1 - line.y1) * scale)
        end = (line.x2 * scale, (image_height - 1 - line.y2) * scale)
        layer = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        modelspace.add_line(start, end, dxfattribs={"layer": layer})
        valid_lines.append(line)
        coordinates.extend((start, end))

    requested_circles = list(circles or [])
    valid_circles = filter_exportable_circles(requested_circles)
    for circle in valid_circles:
        center = (
            circle.center[0] * scale,
            (image_height - 1 - circle.center[1]) * scale,
        )
        radius = circle.radius * scale
        modelspace.add_circle(
            center,
            radius,
            dxfattribs={"layer": "CIRCLE_CONFIRMED"},
        )
        coordinates.extend(
            (
                (center[0] - radius, center[1] - radius),
                (center[0] + radius, center[1] + radius),
            )
        )

    if coordinates:
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        doc.header["$EXTMIN"] = (min(xs), min(ys), 0.0)
        doc.header["$EXTMAX"] = (max(xs), max(ys), 0.0)
    else:
        doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
        doc.header["$EXTMAX"] = (0.0, 0.0, 0.0)

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp.dxf",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        doc.saveas(temporary_path)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return ExportResult(
        path,
        len(valid_lines),
        float(scale),
        calibrated,
        skipped_line_count=len(lines) - len(valid_lines),
        circle_count=len(valid_circles),
        skipped_circle_count=len(requested_circles) - len(valid_circles),
    )
