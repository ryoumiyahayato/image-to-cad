from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import ezdxf
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTransform

from app.core.structure import FinalStructure
from app.export.trace_single_export import export_final_structure_dxf
from app.ocr.librecad_lff import librecad_text_metrics, librecad_text_path


def render_source_reference(structure: FinalStructure) -> np.ndarray:
    """Explicit source reference; never the default CAD result preview."""
    if structure.preview_binary is None:
        raise ValueError('This structure has no source reference')
    return structure.preview_binary.copy()


def render_final_structure_preview(structure: FinalStructure) -> np.ndarray:
    """Rasterize the actual emitted DXF and its relative IMAGE assets.

    Export's entity/layer/binding decisions are the authority. Source pixels
    (including the hidden text backup) cannot mask an absent or changed object.
    No alternate preview representation is inferred from the source binary.
    """
    with TemporaryDirectory(prefix='image-to-cad-preview-') as folder:
        output = Path(folder) / 'preview.dxf'
        export_final_structure_dxf(structure, output, allow_empty=True)
        return render_emitted_dxf_preview(ezdxf.readfile(output), output.parent,
                                          structure.source_size_px)


def render_emitted_dxf_preview(doc, asset_directory: Path, source_size) -> np.ndarray:
    """Source-coordinate raster for the entity types emitted by our writer."""
    width, height = source_size
    image = np.full((height, width, 3), 255, np.uint8)
    canvas = QImage(image.data, width, height, int(image.strides[0]), QImage.Format.Format_BGR888)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor('black'), 1.0))
    images = []
    try:
        for entity in doc.modelspace():
            layer = doc.layers.get(entity.dxf.layer)
            if layer.is_off() or layer.is_frozen():
                continue
            kind = entity.dxftype()
            if kind == 'IMAGE':
                images.append(entity)
                continue
            path = QPainterPath()
            pen_width = 1.
            arc_cap = Qt.PenCapStyle.FlatCap
            if entity.has_xdata('P3A_STROKE'):
                tags = entity.get_xdata('P3A_STROKE')
                weight = entity.dxf.lineweight
                if weight == -1:
                    weight = layer.dxf.lineweight
                pen_width = max(.1, weight/100*float(tags[2].value)/25.4)
            if entity.has_xdata('P9_ARC'):
                tags = entity.get_xdata('P9_ARC')
                pen_width = max(.1, float(tags[1].value))
                if len(tags) >= 5 and tags[3].value == 'round':
                    paper_scale = float(tags[4].value)
                    if not np.isfinite(paper_scale) or paper_scale <= 0:
                        raise ValueError('Invalid emitted round ARC scale')
                    weight = entity.dxf.lineweight
                    if weight == -1:
                        weight = layer.dxf.lineweight
                    pen_width = weight/100/paper_scale
                    if not np.isfinite(pen_width) or pen_width <= 0:
                        raise ValueError('Invalid emitted round ARC width')
                    arc_cap = Qt.PenCapStyle.RoundCap
            painter.setPen(QPen(QColor('black'), pen_width))
            if kind == 'LINE':
                a, b = entity.dxf.start, entity.dxf.end
                path.moveTo(a.x, height-a.y)
                path.lineTo(b.x, height-b.y)
            elif kind == 'LWPOLYLINE':
                points = tuple(entity.get_points('xy'))
                if not points:
                    continue
                path.moveTo(points[0][0], height-points[0][1])
                for x, y in points[1:]:
                    path.lineTo(x, height-y)
                if entity.closed:
                    path.closeSubpath()
            elif kind == 'CIRCLE':
                center, radius = entity.dxf.center, entity.dxf.radius
                path.addEllipse(QPointF(center.x, height-center.y), radius, radius)
            elif kind == 'ARC':
                pen = painter.pen()
                pen.setCapStyle(arc_cap)
                painter.setPen(pen)
                center, radius = entity.dxf.center, entity.dxf.radius
                start, end = entity.dxf.start_angle, entity.dxf.end_angle
                if radius <= 0 or not np.isfinite([center.x, center.y, radius, start, end]).all():
                    raise ValueError('Invalid emitted ARC')
                sweep = (end-start) % 360
                if sweep == 0:
                    raise ValueError('Emitted ARC must have a nonzero sweep')
                rect = (center.x-radius, height-center.y-radius, 2*radius, 2*radius)
                path.arcMoveTo(*rect, start)
                path.arcTo(*rect, start, sweep)
            elif kind == 'TEXT':
                metrics = librecad_text_metrics(entity.dxf.text)
                transform = QTransform()
                insert = entity.dxf.insert
                transform.translate(insert.x, height-insert.y)
                transform.rotate(-entity.dxf.rotation)
                scale = entity.dxf.height / metrics.em_height
                transform.scale(scale*entity.dxf.width, scale)
                path = transform.map(librecad_text_path(entity.dxf.text))
            elif kind == 'HATCH':
                for boundary in entity.paths:
                    points = boundary.vertices
                    path.moveTo(points[0][0], height-points[0][1])
                    for x, y, _bulge in points[1:]:
                        path.lineTo(x, height-y)
                    path.closeSubpath()
                red, green, blue = entity.rgb or (0, 0, 0)
                painter.fillPath(path, QColor(red, green, blue))
                continue
            else:
                raise ValueError(f'Final preview has no renderer for emitted {kind}')
            painter.drawPath(path)
    finally:
        painter.end()
    for entity in images:
        filename = entity.image_def.dxf.filename
        asset = asset_directory / filename
        rgba = cv2.imdecode(np.fromfile(asset, np.uint8), cv2.IMREAD_UNCHANGED)
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError(f'Final IMAGE asset is not RGBA: {filename}')
        insert, u, v = entity.dxf.insert, entity.dxf.u_pixel, entity.dxf.v_pixel
        raster_height = rgba.shape[0]
        matrix = np.array([[u.x, -v.x, insert.x+v.x*raster_height],
                           [-u.y, v.y, height-insert.y-v.y*raster_height]], np.float64)
        foreground = rgba[:, :, :3].astype(np.float32) * (rgba[:, :, 3:4]/255.)
        alpha = cv2.warpAffine(rgba[:, :, 3]/255., matrix, (width, height))[:, :, None]
        ink = cv2.warpAffine(foreground, matrix, (width, height))
        image = np.clip(image*(1-alpha)+ink, 0, 255).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
