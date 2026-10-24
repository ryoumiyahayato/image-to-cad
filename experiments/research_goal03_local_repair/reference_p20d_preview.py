from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import ezdxf
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTransform

from app.core.structure import FinalStructure
from app.core.cancellation import checkpoint
from app.export.trace_single_export import export_final_structure_dxf
from app.ocr.librecad_lff import librecad_text_metrics, librecad_text_path


def render_source_reference(structure: FinalStructure) -> np.ndarray:
    """Explicit source reference; never the default CAD result preview."""
    if structure.preview_binary is None:
        raise ValueError('This structure has no source reference')
    return structure.preview_binary.copy()


def render_final_structure_preview(structure: FinalStructure, *, text_review=None, roi=None, output_scale=1.0, cancellation_token=None) -> np.ndarray:
    """Rasterize the actual emitted DXF and its relative IMAGE assets.

    Export's entity/layer/binding decisions are the authority. Source pixels
    (including the hidden text backup) cannot mask an absent or changed object.
    No alternate preview representation is inferred from the source binary.
    """
    with TemporaryDirectory(prefix='image-to-cad-preview-') as folder:
        output = Path(folder) / 'preview.dxf'
        export_final_structure_dxf(structure, output, allow_empty=True, text_review=text_review,
                                         cancellation_token=cancellation_token)
        checkpoint(cancellation_token)
        return render_emitted_dxf_preview(ezdxf.readfile(output), output.parent,
            structure.source_size_px, roi=roi, output_scale=output_scale,
            cancellation_token=cancellation_token)


class PreparedDxfPreview:
    """One worker-owned emitted document; replaces assets on journal change."""
    def __init__(self):
        self.key = None
        self.folder = None
        self.doc = None

    def close(self):
        self.doc = None
        self.key = None
        if self.folder is not None:
            self.folder.cleanup()
            self.folder = None

    def render(self, structure, *, text_review, key, roi, output_scale,
               cancellation_token):
        if key != self.key:
            self.close()
            folder = TemporaryDirectory(prefix='image-to-cad-preview-')
            try:
                output = Path(folder.name)/'preview.dxf'
                export_final_structure_dxf(structure, output, allow_empty=True,
                    text_review=text_review, cancellation_token=cancellation_token)
                cancellation_token.checkpoint()
                doc = ezdxf.readfile(output)
            except BaseException:
                folder.cleanup()
                raise
            self.folder, self.doc, self.key = folder, doc, key
        cancellation_token.checkpoint()
        return render_emitted_dxf_preview(self.doc, Path(self.folder.name),
            structure.source_size_px, roi=roi, output_scale=output_scale,
            cancellation_token=cancellation_token)


def render_emitted_dxf_preview(doc, asset_directory: Path, source_size, *, roi=None,
                               output_scale=1.0, units_per_source_pixel=1.0,
                               cancellation_token=None) -> np.ndarray:
    """Render actual DXF entities into a source-coordinate ROI.

    Pixel-unit preview exports use units_per_source_pixel=1. Formal millimetre
    exports require their ExportResult.mm_per_pixel, never an inferred extent.
    ROI is (left, top, width, height) in source pixels; output_scale only controls
    raster resolution and does not change the scene coordinate contract.
    """
    source_width, source_height = source_size
    unit = float(units_per_source_pixel)
    density = float(output_scale)
    if not np.isfinite([unit, density]).all() or unit <= 0 or density <= 0:
        raise ValueError('Preview coordinate scales must be positive and finite')
    left, top, roi_width, roi_height = roi or (0, 0, source_width, source_height)
    if not np.isfinite([left, top, roi_width, roi_height]).all() or min(roi_width, roi_height) <= 0:
        raise ValueError('Preview ROI must be finite and nonempty')
    raster_width, raster_height = max(1, int(np.ceil(roi_width*density))), max(1, int(np.ceil(roi_height*density)))
    height = source_height*unit
    image = np.full((raster_height, raster_width, 3), 255, np.uint8)
    canvas = QImage(image.data, raster_width, raster_height, int(image.strides[0]), QImage.Format.Format_BGR888)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(density/unit, density/unit)
    painter.translate(-left*unit, -top*unit)
    painter.setPen(QPen(QColor('black'), 1.0))
    images = []
    try:
        for entity in doc.modelspace():
            checkpoint(cancellation_token)
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
            painter.setPen(QPen(QColor('black'), pen_width*unit))
            if kind == 'LINE':
                a, b = entity.dxf.start, entity.dxf.end
                path.moveTo(a.x, height-a.y)
                path.lineTo(b.x, height-b.y)
            elif kind == 'LWPOLYLINE':
                if entity.has_xdata('P20_NATIVE_STROKE'):
                    native_pen_width = float(entity.dxf.const_width)
                    if not np.isfinite(native_pen_width) or native_pen_width <= 0:
                        raise ValueError('Invalid native source polyline width')
                    pen = QPen(QColor(*(entity.rgb or (0, 0, 0))), native_pen_width)
                    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    pen.setMiterLimit(10)
                    painter.setPen(pen)
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
        checkpoint(cancellation_token)
        # Cull IMAGE placements before decoding; warp/composite only this ROI.
        insert, u, v = entity.dxf.insert, entity.dxf.u_pixel, entity.dxf.v_pixel
        iw, ih = entity.dxf.image_size.x, entity.dxf.image_size.y
        corners = [(insert.x+u.x*x+v.x*y, height-insert.y-u.y*x-v.y*y)
                   for x, y in ((0,0),(iw,0),(0,ih),(iw,ih))]
        xs, ys = zip(*corners)
        if (max(xs) < left*unit or min(xs) > (left+roi_width)*unit
                or max(ys) < top*unit or min(ys) > (top+roi_height)*unit):
            continue
        filename = entity.image_def.dxf.filename
        asset = asset_directory / filename
        rgba = cv2.imdecode(np.fromfile(asset, np.uint8), cv2.IMREAD_UNCHANGED)
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError(f'Final IMAGE asset is not RGBA: {filename}')
        insert, u, v = entity.dxf.insert, entity.dxf.u_pixel, entity.dxf.v_pixel
        image_height = rgba.shape[0]
        matrix = np.array([[u.x, -v.x, insert.x+v.x*image_height-left*unit],
                           [-u.y, v.y, height-insert.y-v.y*image_height-top*unit]], np.float64)
        matrix *= density/unit
        foreground = rgba[:, :, :3].astype(np.float32) * (rgba[:, :, 3:4]/255.)
        alpha = cv2.warpAffine(rgba[:, :, 3].astype(np.float32)/255., matrix, (raster_width, raster_height))[:, :, None]
        ink = cv2.warpAffine(foreground, matrix, (raster_width, raster_height))
        image = np.clip(image*(1-alpha)+ink, 0, 255).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
