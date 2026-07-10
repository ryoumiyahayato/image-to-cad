from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf import units

from .line_detect import LineSegment
from .scale_calibrator import ScaleCalibration


@dataclass(frozen=True)
class ExportResult:
    path: Path
    line_count: int
    mm_per_pixel: float
    calibrated: bool


LAYER_STYLES = {
    "OUTLINE": {"color": 1, "lineweight": 50},
    "WALL_OR_FRAME": {"color": 3, "lineweight": 25},
    "GRID_OR_AXIS": {"color": 5, "lineweight": 13},
    "HATCH": {"color": 6, "lineweight": 9},
    "DETAIL": {"color": 7, "lineweight": 9},
}


def export_dxf(
    lines: list[LineSegment],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
) -> ExportResult:
    """Export independently editable LINE entities to a DXF R2010 document."""
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
    for line in lines:
        # Image Y grows downward; CAD Y grows upward.
        start = (line.x1 * scale, (image_height - line.y1) * scale)
        end = (line.x2 * scale, (image_height - line.y2) * scale)
        layer = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        modelspace.add_line(start, end, dxfattribs={"layer": layer})

    doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
    doc.saveas(path)
    return ExportResult(path, len(lines), scale, calibration is not None)
