"""Compare saved scan entities in source-page coordinates, independently of fitting."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import ezdxf
from ezdxf.disassemble import make_primitive
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.path import make_path
from ezdxf.render.trace import TraceBuilder
import numpy as np

from app.core.dxf_preview import resolve_drawing_fonts
from app.geometry.scan_cleanup import prepare_scan_page
from app.geometry.scan_ownership import emblem_ink, glyph_ink, protected_ink


def _restore_crossing_evidence(source, paper, lines):
    """Check uninterrupted scanline runs reaching outside each OCR observation.

    This source witness is independent of the glyph/geometry fitter. Even a
    glyph ownership regression claiming the entire quad cannot hide a ruled line.
    """
    for line in lines:
        quad = np.asarray(line.quad)
        pad = max(3, int(np.ceil(np.linalg.norm(quad[3]-quad[0]) / 2)))
        x0, y0 = np.maximum(0, np.floor(quad.min(axis=0)).astype(int)-pad)
        x1, y1 = np.minimum(paper.shape[::-1], np.ceil(quad.max(axis=0)).astype(int)+pad+1)
        raw = paper[y0:y1, x0:x1] == 0
        target = source[y0:y1, x0:x1]
        region = np.zeros(raw.shape, np.uint8)
        cv2.fillConvexPoly(region, np.rint(quad - (x0, y0)).astype(np.int32), 1)
        for ink, box, dest in ((raw, region, target), (raw.T, region.T, target.T)):
            for row in np.flatnonzero(box.any(axis=1)):
                hits = np.flatnonzero(box[row])
                edges = np.flatnonzero(np.diff(np.pad(ink[row], 1))).reshape(-1, 2)
                for start, end in edges:
                    if start <= hits[-1] and end > hits[0] and (
                        start <= hits[0]-pad+1 or end >= hits[-1]+pad
                    ):
                        dest[row, start:end] = 255


def source_reference(image, manual, accepted, uncertain):
    """Reconstruct the reference from the aligned source and OCR observations only."""
    binary = prepare_scan_page(image, protected_mask=manual).binary
    graphics = protected_ink(image, binary, manual)
    paper = cv2.bitwise_or(binary, graphics)
    pending = glyph_ink(paper, uncertain)
    glyphs = glyph_ink(paper, accepted) | pending
    source = cv2.subtract(cv2.bitwise_not(paper), glyphs | emblem_ink(image, binary, glyphs))
    _restore_crossing_evidence(source, paper, [*accepted, *uncertain])
    return source, pending


def _source_points(vertices, scale, height):
    return np.array([(v.x / scale, height - v.y / scale) for v in vertices], np.float64)


def _check_text(observed, saved):
    # Match repeated strings by position. Each native entity can satisfy one observation.
    by_content = defaultdict(list)
    for content, corners in saved:
        by_content[content].append(corners)
    missing, misplaced = [], []
    for index, line in enumerate(observed):
        candidates = by_content[line.text]
        if not candidates:
            missing.append(index)
            continue
        box = np.array(line.quad, dtype=np.float32)
        center = box.mean(axis=0)
        best = min(range(len(candidates)), key=lambda i:
                   np.linalg.norm(candidates[i].mean(axis=0) - center))
        corners = candidates.pop(best)
        height = np.linalg.norm(box[3] - box[0])
        # Allow font ascender/descender variation, not a displaced or oversized line.
        tolerance = max(1.0, 0.16 * height)
        baseline = box[1] - box[0]
        width = np.linalg.norm(baseline)
        short_line = width and np.ptp(corners @ (baseline / width)) < width * 0.5
        if short_line or any(cv2.pointPolygonTest(box, tuple(p), True) < -tolerance for p in corners):
            misplaced.append(index)
    return {"expected_lines": len(observed), "native_lines": len(saved),
            "missing_or_changed": missing, "outside_box": misplaced,
            "unexpected_lines": sum(map(len, by_content.values()))}


def check_saved_scan(output, reference, accepted, *, dpi, drawing_scale=1.0):
    source, uncertain = reference
    doc = ezdxf.readfile(output)
    if accepted:
        resolve_drawing_fonts(doc, Path(output).parent)
    drawn = np.zeros_like(source)
    height, width = drawn.shape
    model_per_pixel = 25.4 / dpi * drawing_scale
    saved_text = []
    outside = 0
    for entity in doc.modelspace():
        layer = doc.layers.get(entity.dxf.layer)
        if (layer.is_off() or layer.is_frozen() or entity.dxf.invisible
                or layer.dxf.name.casefold() in {"review_source", "suggest_repair"}):
            continue
        kind = entity.dxftype()
        if kind in ("TEXT", "MTEXT"):
            corners = _source_points(make_primitive(entity).vertices(), model_per_pixel, height)
            if len(corners):
                saved_text.append((decode_dxf_unicode(entity.plain_text()), corners[:4]))
        elif kind in ("LINE", "LWPOLYLINE", "CIRCLE", "ARC"):
            if kind == "LWPOLYLINE" and entity.has_width:
                trace = TraceBuilder.from_polyline(entity)
                faces = trace.faces_wcs(entity.ocs(), entity.dxf.elevation)
                exceeds_page = False
                for face in faces:
                    points = _source_points(face, model_per_pixel, height)
                    exceeds_page |= bool(np.any((points < -0.5)
                                                | (points > (width-0.5, height-0.5))))
                    cv2.fillConvexPoly(drawn, np.rint(points * 16).astype(np.int32),
                                       255, shift=4)
                outside += int(exceeds_page)
                continue
            path = make_path(entity)
            vertices = path.flattening(model_per_pixel * 0.2)
            points = _source_points(vertices, model_per_pixel, height)
            if len(points) < 2:
                continue
            outside += int(np.any((points < -0.5) | (points > (width-0.5, height-0.5))))
            weight = entity.dxf.lineweight
            if weight < 0:
                weight = layer.dxf.lineweight
            if weight < 0:
                weight = doc.header.get("$LWDEFAULT", 25)
            thickness = max(1, round(weight * dpi / 2540))
            cv2.polylines(drawn, [np.rint(points * 16).astype(np.int32)], path.is_closed,
                          255, thickness, shift=4)

    # A one-pixel rasterization tolerance in each direction; never mask a text box.
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    missing = cv2.subtract(source, cv2.dilate(drawn, kernel))
    extra = cv2.subtract(drawn, cv2.dilate(source, kernel))
    geometry = {"source_pixels": cv2.countNonZero(source), "drawn_pixels": cv2.countNonZero(drawn),
                "missing_pixels": cv2.countNonZero(missing), "extra_pixels": cv2.countNonZero(extra),
                "outside_page_entities": outside, "tolerance_px": 1}
    return {"geometry": geometry, "text": _check_text(accepted, saved_text)}, missing | uncertain
