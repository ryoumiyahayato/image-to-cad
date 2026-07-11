from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def export_dxf(
    lines: list[LineSegment],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    circles: list[CircleCandidate] | None = None,
) -> ExportResult:
    """Export editable LINE entities and explicitly confirmed CIRCLE entities.

    Circle confidence is rechecked at the file boundary. This prevents callers
    from bypassing the GUI review gate by passing a weak raw candidate directly.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scale = calibration.mm_per_pixel if calibration is not None else 1.0

    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = units.MM
    doc.header["$LUNITS"] = 2

    for layer_name, style in LAYER_STYLES.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    valid_lines: list[LineSegment] = []
    valid_circles: list[CircleCandidate] = []
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

    requested_circles = circles or []
    for circle in requested_circles:
        values = np.array(
            [circle.center[0], circle.center[1], circle.radius, circle.confidence],
            dtype=float,
        )
        if (
            not np.isfinite(values).all()
            or circle.radius <= 1e-9
            or circle.confidence < MIN_CIRCLE_EXPORT_CONFIDENCE
        ):
            continue
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
        valid_circles.append(circle)
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

    temporary = path.with_name(f".{path.name}.tmp")
    doc.saveas(temporary)
    temporary.replace(path)
    return ExportResult(
        path,
        len(valid_lines),
        scale,
        calibration is not None,
        skipped_line_count=len(lines) - len(valid_lines),
        circle_count=len(valid_circles),
        skipped_circle_count=len(requested_circles) - len(valid_circles),
    )
