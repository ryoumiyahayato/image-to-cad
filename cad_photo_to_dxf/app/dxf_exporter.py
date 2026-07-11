from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf import units
import numpy as np

from .line_detect import LineSegment
from .scale_calibrator import ScaleCalibration


COORDINATE_MODES = {"pixel_units", "paper_mm", "model_mm"}


@dataclass(frozen=True)
class ExportResult:
    path: Path
    line_count: int
    mm_per_pixel: float
    calibrated: bool
    coordinate_mode: str
    unit_name: str
    skipped_line_count: int = 0


LAYER_STYLES = {
    "OUTLINE": {"color": 1, "lineweight": 50},
    "WALL_OR_FRAME": {"color": 3, "lineweight": 25},
    "GRID_OR_AXIS": {"color": 5, "lineweight": 13},
    "HATCH": {"color": 6, "lineweight": 9},
    "HATCH_CANDIDATE": {"color": 4, "lineweight": 9},
    "DETAIL": {"color": 7, "lineweight": 9},
}


def export_dxf(
    lines: list[LineSegment],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    coordinate_mode: str | None = None,
) -> ExportResult:
    """Export independently editable LINE entities to a DXF R2010 document."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scale = calibration.mm_per_pixel if calibration is not None else 1.0
    mode = coordinate_mode or ("model_mm" if calibration is not None else "pixel_units")
    if mode not in COORDINATE_MODES:
        raise ValueError(f"Unknown coordinate mode: {mode}")
    if mode in {"paper_mm", "model_mm"} and calibration is None:
        raise ValueError(f"Coordinate mode {mode} requires a scale calibration")
    if mode == "pixel_units" and calibration is not None:
        raise ValueError("Pixel coordinate mode cannot use a millimetre calibration")

    doc = ezdxf.new("R2010", setup=True)
    if mode == "pixel_units":
        doc.units = units.UNITLESS
        doc.header["$MEASUREMENT"] = 0
        doc.header["$INSUNITS"] = units.UNITLESS
        unit_name = "pixel_unit"
    else:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
        unit_name = "mm"
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
        coordinate_mode=mode,
        unit_name=unit_name,
        skipped_line_count=len(lines) - len(valid_lines),
    )
