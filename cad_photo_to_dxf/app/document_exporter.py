from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile

import ezdxf
from ezdxf import units, zoom

from .auxiliary_recognition import (
    MIN_CIRCLE_EXPORT_CONFIDENCE,
    CircleCandidate,
    TextCandidate,
)
from .dxf_exporter import LAYER_STYLES, MIN_TEXT_EXPORT_CONFIDENCE
from .line_detect import LineSegment
from .scale_calibrator import ScaleCalibration


DOCUMENT_LAYER_STYLES = {
    **LAYER_STYLES,
    "PAGE_FRAME": {"color": 8, "lineweight": 9},
    "PAGE_LABEL": {"color": 7, "lineweight": 9},
}


@dataclass(frozen=True)
class DocumentPage:
    """One reviewed scan page ready to be placed in a combined CAD document."""

    lines: tuple[LineSegment, ...]
    image_width: int
    image_height: int
    calibration: ScaleCalibration | None = None
    circles: tuple[CircleCandidate, ...] = field(default_factory=tuple)
    texts: tuple[TextCandidate, ...] = field(default_factory=tuple)
    raster_path: Path | None = None
    label: str = ""
    source_path: Path | None = None
    source_page: int | None = None


@dataclass(frozen=True)
class DocumentExportResult:
    """Export result compatible with the existing single-page report fields."""

    path: Path
    line_count: int
    mm_per_pixel: float
    calibrated: bool
    skipped_line_count: int = 0
    circle_count: int = 0
    skipped_circle_count: int = 0
    text_count: int = 0
    skipped_text_count: int = 0
    underlay_path: Path | None = None
    dwg_path: Path | None = None
    output_format: str = "DXF"
    page_count: int = 0
    underlay_paths: tuple[Path, ...] = field(default_factory=tuple)


def _valid_circle(circle: CircleCandidate) -> bool:
    values = (*circle.center, circle.radius, circle.confidence)
    return (
        all(isfinite(float(value)) for value in values)
        and circle.radius > 1e-9
        and circle.confidence >= MIN_CIRCLE_EXPORT_CONFIDENCE
    )


def _valid_text(text: TextCandidate) -> bool:
    x, y, width, height = text.bbox
    values = (x, y, width, height, text.confidence)
    return (
        bool(text.text.strip())
        and all(isfinite(float(value)) for value in values)
        and width > 0
        and height > 0
        and text.confidence >= MIN_TEXT_EXPORT_CONFIDENCE
    )


def _page_scale(page: DocumentPage, calibrated_document: bool) -> float:
    if not calibrated_document or page.calibration is None:
        return 1.0
    value = float(page.calibration.mm_per_pixel)
    if not isfinite(value) or value <= 0:
        raise ValueError("Page calibration scale must be positive and finite")
    return value


def _add_page_frame(
    modelspace,
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[object]:
    attributes = {"layer": "PAGE_FRAME"}
    return [
        modelspace.add_line((x, y), (x + width, y), dxfattribs=attributes),
        modelspace.add_line(
            (x + width, y),
            (x + width, y + height),
            dxfattribs=attributes,
        ),
        modelspace.add_line(
            (x + width, y + height),
            (x, y + height),
            dxfattribs=attributes,
        ),
        modelspace.add_line((x, y + height), (x, y), dxfattribs=attributes),
    ]


def export_document_dxf(
    pages: Sequence[DocumentPage],
    output_path: str | Path,
    *,
    include_underlays: bool = True,
    page_gap_ratio: float = 0.06,
) -> DocumentExportResult:
    """Place reviewed pages side by side in one editable DXF model space.

    Every page remains a direct collection of editable entities. A named DXF
    group (``PAGE_001`` and so on) is also created so a whole page can be
    selected without forcing the geometry into a block.
    """

    document_pages = list(pages)
    if not document_pages:
        raise ValueError("At least one document page is required")
    if not 0.0 <= page_gap_ratio <= 1.0:
        raise ValueError("Page gap ratio must be between 0 and 1")
    for page in document_pages:
        if page.image_width <= 0 or page.image_height <= 0:
            raise ValueError("Page image dimensions must be positive")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    calibrated = all(page.calibration is not None for page in document_pages)
    scales = [_page_scale(page, calibrated) for page in document_pages]

    doc = ezdxf.new("R2010", setup=True)
    if calibrated:
        doc.units = units.MM
        doc.header["$MEASUREMENT"] = 1
        doc.header["$INSUNITS"] = units.MM
    else:
        doc.units = 0
        doc.header["$INSUNITS"] = 0
    doc.header["$LUNITS"] = 2
    doc.header["$LWDISPLAY"] = 1

    for layer_name, style in DOCUMENT_LAYER_STYLES.items():
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, **style)

    modelspace = doc.modelspace()
    coordinates: list[tuple[float, float]] = []
    underlay_paths: list[Path] = []
    line_count = 0
    circle_count = 0
    text_count = 0
    skipped_lines = 0
    skipped_circles = 0
    skipped_texts = 0
    x_offset = 0.0

    for index, (page, scale) in enumerate(zip(document_pages, scales), start=1):
        page_width = page.image_width * scale
        page_height = page.image_height * scale
        page_entities: list[object] = []

        if include_underlays and page.raster_path is not None:
            source = Path(page.raster_path)
            if not source.exists():
                raise FileNotFoundError(source)
            target = path.with_name(f"{path.stem}.page-{index:03d}.scan.png").resolve()
            if source.resolve() != target:
                shutil.copy2(source, target)
            underlay_paths.append(target)
            image_def = doc.add_image_def(
                filename=target.name,
                size_in_pixel=(page.image_width, page.image_height),
            )
            doc.set_raster_variables(
                frame=0,
                quality=1,
                units="mm" if calibrated else "none",
            )
            page_entities.append(
                modelspace.add_image(
                    image_def=image_def,
                    insert=(x_offset, 0.0),
                    size_in_units=(page_width, page_height),
                    rotation=0.0,
                    dxfattribs={"layer": "SCAN_UNDERLAY"},
                )
            )

        for line in page.lines:
            values = (line.x1, line.y1, line.x2, line.y2)
            if (
                not all(isfinite(float(value)) for value in values)
                or line.length <= 1e-9
            ):
                skipped_lines += 1
                continue
            start = (
                x_offset + line.x1 * scale,
                (page.image_height - 1 - line.y1) * scale,
            )
            end = (
                x_offset + line.x2 * scale,
                (page.image_height - 1 - line.y2) * scale,
            )
            layer = line.layer if line.layer in DOCUMENT_LAYER_STYLES else "DETAIL"
            page_entities.append(
                modelspace.add_line(start, end, dxfattribs={"layer": layer})
            )
            coordinates.extend((start, end))
            line_count += 1

        for circle in page.circles:
            if not _valid_circle(circle):
                skipped_circles += 1
                continue
            center = (
                x_offset + circle.center[0] * scale,
                (page.image_height - 1 - circle.center[1]) * scale,
            )
            radius = circle.radius * scale
            page_entities.append(
                modelspace.add_circle(
                    center,
                    radius,
                    dxfattribs={"layer": "CIRCLE_CONFIRMED"},
                )
            )
            coordinates.extend(
                (
                    (center[0] - radius, center[1] - radius),
                    (center[0] + radius, center[1] + radius),
                )
            )
            circle_count += 1

        for text in page.texts:
            if not _valid_text(text):
                skipped_texts += 1
                continue
            x, y, width, height = text.bbox
            insert = (
                x_offset + x * scale,
                (page.image_height - 1 - (y + height)) * scale,
            )
            entity = modelspace.add_text(
                text.text.strip(),
                height=max(scale, height * scale * 0.85),
                dxfattribs={"layer": "OCR_TEXT"},
            )
            entity.set_placement(insert)
            page_entities.append(entity)
            coordinates.extend(
                (
                    insert,
                    (insert[0] + width * scale, insert[1] + height * scale),
                )
            )
            text_count += 1

        page_entities.extend(
            _add_page_frame(
                modelspace,
                x_offset,
                0.0,
                page_width,
                page_height,
            )
        )
        label = page.label.strip() or f"Page {index}"
        label_entity = modelspace.add_text(
            label,
            height=max(2.5 * scale, page_height * 0.012),
            dxfattribs={"layer": "PAGE_LABEL"},
        )
        label_entity.set_placement(
            (x_offset, page_height + max(4.0 * scale, page_height * 0.012))
        )
        page_entities.append(label_entity)
        try:
            group = doc.groups.new(f"PAGE_{index:03d}")
            group.extend(page_entities)
        except Exception:
            # Groups improve selection convenience but are not required for a
            # valid editable DXF, so an old ezdxf implementation may omit them.
            pass

        coordinates.extend(
            (
                (x_offset, 0.0),
                (x_offset + page_width, page_height),
            )
        )
        gap = max(20.0 * scale, page_width * page_gap_ratio)
        x_offset += page_width + gap

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

    representative_scale = scales[0] if calibrated and scales else 1.0
    return DocumentExportResult(
        path=path,
        line_count=line_count,
        mm_per_pixel=float(representative_scale),
        calibrated=calibrated,
        skipped_line_count=skipped_lines,
        circle_count=circle_count,
        skipped_circle_count=skipped_circles,
        text_count=text_count,
        skipped_text_count=skipped_texts,
        underlay_path=underlay_paths[0] if underlay_paths else None,
        page_count=len(document_pages),
        underlay_paths=tuple(underlay_paths),
    )
