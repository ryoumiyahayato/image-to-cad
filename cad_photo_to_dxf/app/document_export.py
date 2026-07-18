from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom
import numpy as np

from .dxf_exporter import LAYER_STYLES
from .image_loader import save_image
from .line_detect import LineSegment


@dataclass(frozen=True)
class DocumentPage:
    """One scan page plus optional reviewed vectors in page pixel coordinates."""

    page_number: int
    raster: np.ndarray
    page_size_mm: tuple[float, float]
    lines: tuple[LineSegment, ...] = ()
    vector_size_px: tuple[int, int] | None = None
    label: str = ""


@dataclass(frozen=True)
class DocumentExportResult:
    path: Path
    page_count: int
    line_count: int
    underlay_paths: tuple[Path, ...]
    layout_names: tuple[str, ...]


def _safe_layout_name(page_number: int) -> str:
    return f"PAGE-{page_number:03d}"


def _add_page_entities(
    layout,
    image_def,
    page: DocumentPage,
    *,
    origin: tuple[float, float],
) -> int:
    raster_height, raster_width = page.raster.shape[:2]
    page_width_mm, page_height_mm = page.page_size_mm
    origin_x, origin_y = origin
    layout.add_image(
        image_def=image_def,
        insert=(origin_x, origin_y),
        size_in_units=(page_width_mm, page_height_mm),
        rotation=0.0,
        dxfattribs={"layer": "SCAN_UNDERLAY"},
    )
    vector_width, vector_height = page.vector_size_px or (raster_width, raster_height)
    scale_x = page_width_mm / max(float(vector_width), 1.0)
    scale_y = page_height_mm / max(float(vector_height), 1.0)
    exported = 0
    for line in page.lines:
        values = np.array((line.x1, line.y1, line.x2, line.y2), dtype=float)
        if not np.isfinite(values).all() or line.length <= 1e-9:
            continue
        start = (
            origin_x + line.x1 * scale_x,
            origin_y + (vector_height - 1 - line.y1) * scale_y,
        )
        end = (
            origin_x + line.x2 * scale_x,
            origin_y + (vector_height - 1 - line.y2) * scale_y,
        )
        layer = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        layout.add_line(start, end, dxfattribs={"layer": layer})
        exported += 1
    return exported


def export_scan_document(
    pages: Iterable[DocumentPage],
    output_path: str | Path,
    *,
    modelspace_gap_mm: float = 25.0,
) -> DocumentExportResult:
    """Export all scan pages into one DXF with one paper-space layout per page.

    The original rendered scan is the visual source of truth. Reviewed vectors are
    overlaid when available. Pages are also stacked vertically in model space so
    CAD programs that ignore paper-space layouts still expose the whole document.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = units.MM
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1
    for layer_name, style in LAYER_STYLES.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    underlays: list[Path] = []
    layout_names: list[str] = []
    line_count = 0
    model_y = 0.0

    page_count = 0
    for index, page in enumerate(pages, start=1):
        page_count += 1
        if page.page_number <= 0:
            raise ValueError("Page numbers must be positive")
        if page.raster.ndim not in (2, 3) or page.raster.size == 0:
            raise ValueError(f"Page {page.page_number} has no raster image")
        page_width_mm, page_height_mm = page.page_size_mm
        if page_width_mm <= 0 or page_height_mm <= 0:
            raise ValueError(f"Page {page.page_number} has invalid paper dimensions")

        scan_path = path.with_name(f"{path.stem}.page-{page.page_number:03d}.scan.png")
        save_image(scan_path, page.raster)
        underlays.append(scan_path)
        raster_height, raster_width = page.raster.shape[:2]
        image_def = doc.add_image_def(
            filename=scan_path.name,
            size_in_pixel=(int(raster_width), int(raster_height)),
            name=f"SCAN_PAGE_{page.page_number:03d}",
        )

        layout_name = _safe_layout_name(page.page_number)
        if layout_name in doc.layouts:
            layout = doc.layouts.get(layout_name)
        else:
            layout = doc.layouts.new(layout_name)
        layout.page_setup(
            size=(page_width_mm, page_height_mm),
            margins=(0.0, 0.0, 0.0, 0.0),
            units="mm",
            rotation=0,
        )
        line_count += _add_page_entities(layout, image_def, page, origin=(0.0, 0.0))
        layout_names.append(layout_name)

        _add_page_entities(
            modelspace,
            image_def,
            page,
            origin=(0.0, model_y),
        )
        model_y += page_height_mm + max(0.0, float(modelspace_gap_mm))

    if page_count == 0:
        raise ValueError("At least one document page is required")

    doc.set_raster_variables(frame=0, quality=1, units="mm")
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

    return DocumentExportResult(
        path=path,
        page_count=page_count,
        line_count=line_count,
        underlay_paths=tuple(underlays),
        layout_names=tuple(layout_names),
    )
