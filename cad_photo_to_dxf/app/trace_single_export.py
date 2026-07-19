from __future__ import annotations

from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom
import numpy as np

from .dxf_exporter import ExportResult, LAYER_STYLES
from .image_loader import save_image
from .raster_trace import TracePath
from .scale_calibrator import ScaleCalibration
from .trace_dxf_entities import add_exact_trace_entities


def export_exact_trace_dxf(
    trace_paths: tuple[TracePath, ...],
    output_path: str | Path,
    image_height: int,
    calibration: ScaleCalibration | None = None,
    *,
    drawing_multiplier: float = 1.0,
    trace_color: int = 7,
    raster_image: np.ndarray | None = None,
    raster_output_path: str | Path | None = None,
) -> ExportResult:
    if image_height <= 0:
        raise ValueError("Image height must be greater than zero")
    if not trace_paths:
        raise ValueError("At least one exact trace path is required")
    multiplier = float(drawing_multiplier)
    if not isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Drawing multiplier must be positive and finite")
    paper_scale = calibration.mm_per_pixel if calibration is not None else 1.0
    scale = float(paper_scale) * multiplier
    if not isfinite(scale) or scale <= 0:
        raise ValueError("Trace export scale must be positive and finite")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010", setup=True)
    if calibration is not None:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
    else:
        doc.units = 0
        doc.header["$INSUNITS"] = 0
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1
    styles = {
        **LAYER_STYLES,
        "TRACE_OUTLINE": {"color": 7, "lineweight": 0},
        "TRACE_FILL": {"color": 7, "lineweight": 0},
    }
    for layer_name, style in styles.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    coordinates: list[tuple[float, float]] = []
    underlay_path: Path | None = None
    if raster_image is not None:
        if raster_image.size == 0 or raster_image.ndim not in (2, 3):
            raise ValueError("Raster underlay must be a non-empty image")
        raster_height, raster_width = raster_image.shape[:2]
        if raster_height != image_height:
            raise ValueError("Raster underlay height does not match trace coordinates")
        underlay_path = (
            Path(raster_output_path)
            if raster_output_path is not None
            else path.with_name(f"{path.stem}.scan.png")
        ).resolve()
        if underlay_path.parent != path.resolve().parent:
            raise ValueError("Raster underlay must be saved beside the DXF")
        save_image(underlay_path, raster_image)
        image_def = doc.add_image_def(
            filename=underlay_path.name,
            size_in_pixel=(int(raster_width), int(raster_height)),
        )
        doc.set_raster_variables(
            frame=0,
            quality=1,
            units="mm" if calibration is not None else "none",
        )
        modelspace.add_image(
            image_def=image_def,
            insert=(0.0, 0.0),
            size_in_units=(raster_width * scale, raster_height * scale),
            rotation=0.0,
            dxfattribs={"layer": "SCAN_UNDERLAY"},
        )
        coordinates.extend(
            ((0.0, 0.0), (raster_width * scale, raster_height * scale))
        )

    (
        trace_path_count,
        trace_vertex_count,
        _trace_entities,
        trace_coordinates,
    ) = add_exact_trace_entities(
        modelspace,
        trace_paths,
        transform=lambda x, y: (x * scale, (image_height - y) * scale),
        color=trace_color,
    )
    coordinates.extend(trace_coordinates)

    if coordinates:
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        doc.header["$EXTMIN"] = (min(xs), min(ys), 0.0)
        doc.header["$EXTMAX"] = (max(xs), max(ys), 0.0)
        try:
            zoom.extents(modelspace, factor=1.03)
        except Exception:
            pass

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
        path=path,
        line_count=0,
        mm_per_pixel=scale,
        calibrated=calibration is not None,
        trace_path_count=trace_path_count,
        trace_vertex_count=trace_vertex_count,
        drawing_scale=multiplier,
        underlay_path=underlay_path,
    )
