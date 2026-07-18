from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Iterable, Sequence

import ezdxf
from ezdxf import units, zoom
import numpy as np

from .dxf_exporter import ExportResult, LAYER_STYLES
from .image_loader import load_image, pdf_page_size_mm, save_image
from .line_detect import LineSegment


@dataclass(frozen=True)
class DocumentPage:
    """One scan-backed CAD sheet.

    Images are loaded lazily from ``source_path`` when ``image`` is omitted.  A
    PDF page keeps its physical page dimensions so every sheet can be placed in
    millimetres without pretending that printed scale is model scale.
    """

    page_number: int
    source_path: Path
    image: np.ndarray | None = None
    lines: tuple[LineSegment, ...] = ()
    page_size_mm: tuple[float, float] | None = None
    label: str | None = None


@dataclass(frozen=True)
class DocumentLayout:
    page_number: int
    label: str
    insert: tuple[float, float]
    size: tuple[float, float]
    scale: float
    image_height: int
    underlay_path: Path


ProgressCallback = Callable[[str, float], None]


def _safe_layout_name(page_number: int, label: str) -> str:
    clean = "".join(character if character.isalnum() else "_" for character in label)
    clean = clean.strip("_")[:180]
    return f"PAGE_{page_number:03d}_{clean}" if clean else f"PAGE_{page_number:03d}"


def _write_document(
    doc: ezdxf.document.Drawing,
    path: Path,
) -> None:
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


def _add_page_entities(
    layout,
    *,
    image_def,
    insert: tuple[float, float],
    size_mm: tuple[float, float],
    image_height: int,
    scale: float,
    lines: Sequence[LineSegment],
    add_frame: bool,
) -> tuple[int, list[tuple[float, float]]]:
    x0, y0 = insert
    width_mm, height_mm = size_mm
    layout.add_image(
        image_def=image_def,
        insert=(x0, y0),
        size_in_units=(width_mm, height_mm),
        rotation=0.0,
        dxfattribs={"layer": "SCAN_UNDERLAY"},
    )
    coordinates = [(x0, y0), (x0 + width_mm, y0 + height_mm)]
    if add_frame:
        layout.add_lwpolyline(
            [
                (x0, y0),
                (x0 + width_mm, y0),
                (x0 + width_mm, y0 + height_mm),
                (x0, y0 + height_mm),
            ],
            close=True,
            dxfattribs={"layer": "PAGE_FRAME"},
        )

    valid_count = 0
    for line in lines:
        values = np.asarray((line.x1, line.y1, line.x2, line.y2), dtype=float)
        if not np.isfinite(values).all() or line.length <= 1e-9:
            continue
        start = (
            x0 + line.x1 * scale,
            y0 + (image_height - 1 - line.y1) * scale,
        )
        end = (
            x0 + line.x2 * scale,
            y0 + (image_height - 1 - line.y2) * scale,
        )
        layer_name = line.layer if line.layer in LAYER_STYLES else "DETAIL"
        layout.add_line(start, end, dxfattribs={"layer": layer_name})
        valid_count += 1
        coordinates.extend((start, end))
    return valid_count, coordinates


def export_scan_document(
    pages: Iterable[DocumentPage],
    output_path: str | Path,
    *,
    pdf_dpi: int = 200,
    page_gap_mm: float = 25.0,
    progress_callback: ProgressCallback | None = None,
) -> ExportResult:
    """Export many scan pages into one DXF and one paper-space layout per page.

    The model space contains a vertical sheet stack for users who work only in
    model space.  Each sheet is also repeated in a dedicated paper-space layout,
    which is the natural representation after DXF -> DWG conversion.

    Raster pages are saved losslessly as PNG files beside the DXF.  The scan is
    the visual source of truth; vectors are optional reviewed overlays.
    """

    page_list = list(pages)
    total = len(page_list)
    if not page_list:
        raise ValueError("At least one page is required")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isfinite(page_gap_mm) or page_gap_mm < 0:
        raise ValueError("Page gap must be a finite non-negative number")

    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.header["$INSUNITS"] = units.MM
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1

    styles = dict(LAYER_STYLES)
    styles.setdefault("PAGE_FRAME", {"color": 8, "lineweight": 9})
    styles.setdefault("PAGE_LABEL", {"color": 7, "lineweight": 9})
    for layer_name, style in styles.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    # Resolve physical page sizes without rendering all sheets.  Large-format
    # PDFs can exceed 200 MB per page at 300 DPI, so page rasters are loaded and
    # released one at a time during the export loop.
    page_sizes: list[tuple[float, float]] = []
    for page in page_list:
        size_mm = page.page_size_mm
        if size_mm is None and page.source_path.suffix.lower() == ".pdf":
            size_mm = pdf_page_size_mm(page.source_path, page.page_number - 1)
        if size_mm is None and page.image is not None:
            height, width = page.image.shape[:2]
            size_mm = (width * 25.4 / 150.0, height * 25.4 / 150.0)
        if size_mm is None:
            raise ValueError(
                f"Page {page.page_number} needs PDF dimensions or a raster image"
            )
        width_mm, height_mm = float(size_mm[0]), float(size_mm[1])
        if width_mm <= 0 or height_mm <= 0:
            raise ValueError(f"Page {page.page_number} has invalid dimensions")
        page_sizes.append((width_mm, height_mm))

    # First page is at the top of the model-space stack.
    total_height = sum(size[1] for size in page_sizes) + page_gap_mm * (total - 1)
    y_cursor = total_height
    modelspace = doc.modelspace()
    all_coordinates: list[tuple[float, float]] = []
    valid_line_count = 0
    skipped_line_count = 0
    underlay_paths: list[Path] = []

    for index, page in enumerate(page_list):
        if progress_callback is not None:
            progress_callback(
                f"写入第 {page.page_number} 页",
                index / max(total, 1) * 0.95,
            )
        image = page.image
        if image is None:
            image = load_image(
                page.source_path,
                page_index=max(0, page.page_number - 1),
                pdf_dpi=pdf_dpi,
            )
        if image.size == 0 or image.ndim not in (2, 3):
            raise ValueError(f"Page {page.page_number} has no usable raster image")
        height, width = image.shape[:2]
        size_mm = page_sizes[index]
        width_mm, height_mm = size_mm
        scale = width_mm / max(float(width), 1.0)
        underlay_path = path.with_name(
            f"{path.stem}.page-{page.page_number:03d}.scan.png"
        ).resolve()
        save_image(underlay_path, image)
        y_cursor -= height_mm
        insert = (0.0, y_cursor)
        image_def = doc.add_image_def(
            filename=underlay_path.name,
            size_in_pixel=(int(width), int(height)),
        )
        doc.set_raster_variables(frame=0, quality=1, units="mm")
        count, coordinates = _add_page_entities(
            modelspace,
            image_def=image_def,
            insert=insert,
            size_mm=size_mm,
            image_height=height,
            scale=scale,
            lines=page.lines,
            add_frame=True,
        )
        label = page.label or f"Page {page.page_number}"
        modelspace.add_text(
            label,
            height=max(3.5, min(width_mm, height_mm) * 0.012),
            dxfattribs={"layer": "PAGE_LABEL"},
        ).set_placement((insert[0], insert[1] + height_mm + 4.0))
        valid_line_count += count
        skipped_line_count += len(page.lines) - count
        all_coordinates.extend(coordinates)
        underlay_paths.append(underlay_path)

        paper = doc.layouts.new(_safe_layout_name(page.page_number, label))
        paper.page_setup(
            size=size_mm,
            margins=(0.0, 0.0, 0.0, 0.0),
            units="mm",
            scale=(1.0, 1.0),
            name="scan_sheet",
        )
        _add_page_entities(
            paper,
            image_def=image_def,
            insert=(0.0, 0.0),
            size_mm=size_mm,
            image_height=height,
            scale=scale,
            lines=page.lines,
            add_frame=False,
        )
        y_cursor -= page_gap_mm

    if all_coordinates:
        xs = [point[0] for point in all_coordinates]
        ys = [point[1] for point in all_coordinates]
        doc.header["$EXTMIN"] = (min(xs), min(ys), 0.0)
        doc.header["$EXTMAX"] = (max(xs), max(ys), 0.0)
        try:
            zoom.extents(modelspace, factor=1.02)
        except Exception:
            pass

    _write_document(doc, path)
    if progress_callback is not None:
        progress_callback("完成", 1.0)
    return ExportResult(
        path=path,
        line_count=valid_line_count,
        mm_per_pixel=1.0,
        calibrated=True,
        skipped_line_count=skipped_line_count,
        underlay_path=underlay_paths[0],
        underlay_paths=tuple(underlay_paths),
        page_count=len(page_list),
        output_format="DXF",
    )
