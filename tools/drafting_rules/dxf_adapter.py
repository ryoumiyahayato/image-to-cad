"""Read saved DXFs; reuse the production LFF metrics, never approximate fonts."""
from __future__ import annotations

import hashlib
import json
from math import cos, sin, radians, isfinite
from pathlib import Path

import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str, allow_nan=False).encode()).hexdigest()


def tags(entity):
    return [(tag.code, str(tag.value)) for tag in TagCollector.dxftags(entity)]


def snapshot(path):
    # audit() can repair; inspect a separate instance and reject repairs.
    audit = ezdxf.readfile(path).audit()
    if audit.errors or audit.fixes:
        raise ValueError(f"DXF audit needs repairs: {Path(path).name}")
    doc = ezdxf.readfile(path)
    entities = {}
    simple = {"TEXT", "MTEXT", "LINE", "LWPOLYLINE", "ARC", "CIRCLE", "SOLID", "POINT"}
    for e in doc.modelspace():
        layer = doc.layers.get(e.dxf.layer)
        kind = e.dxftype()
        resources = [tags(layer)]
        ltype = e.dxf.get("linetype", "BYLAYER")
        if ltype.upper() == "BYLAYER":
            ltype = layer.dxf.linetype
        if ltype in doc.linetypes:
            resources.append(tags(doc.linetypes.get(ltype)))
        supported = kind in simple
        if kind in {"TEXT", "MTEXT"}:
            resources.append(tags(doc.styles.get(e.dxf.style)))
        # BLOCK, IMAGE, HATCH, dimensions and other resource graphs need their
        # own adapter. Unchanged outer tags cannot prove unchanged contents.
        item = dict(kind=kind, layer=e.dxf.layer,
                    visible=not (layer.is_off() or layer.is_frozen() or e.dxf.get("invisible", 0)),
                    supported=supported, fingerprint=digest([tags(e), resources]))
        if kind in {"TEXT", "MTEXT"}:
            item["text"] = e.dxf.text if kind == "TEXT" else e.plain_text()
            item["bounds"] = lff_bounds(e, doc) if kind == "TEXT" else None
        if kind == "LINE" and e.dxf.start.z == e.dxf.end.z == 0:
            item["segments"] = [[e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y]]
        elif kind == "LWPOLYLINE" and not e.dxf.elevation:
            points = list(e.get_points("xyb"))
            if not any(p[2] for p in points):
                pairs = list(zip(points, points[1:]))
                if e.closed and len(points) > 1:
                    pairs.append((points[-1], points[0]))
                item["segments"] = [[a[0], a[1], b[0], b[1]] for a, b in pairs]
        entities[e.dxf.handle] = item
    # DXF unit changes invalidate every numerical position, even unchanged tags.
    for item in entities.values():
        item["fingerprint"] = digest([item["fingerprint"], doc.units])
    return entities


def lff_bounds(entity, doc):
    """Exact ink bounds for the packaged font and a deliberately narrow TEXT set.

    Other fonts, missing glyphs, alignment modes and arbitrary rotations abstain.
    No width inferred from character count and no cached export geometry trusted.
    """
    try:
        from app.ocr.librecad_lff import (
            LIBRECAD_FONT_FILENAME, librecad_font_available, librecad_text_metrics,
        )
    except ImportError:
        return None  # The pure checker can still inspect strings and members.

    d = entity.dxf
    style = doc.styles.get(d.style)
    rotation = d.get("rotation", 0)
    if (style.dxf.font != LIBRECAD_FONT_FILENAME or not librecad_font_available()
            or style.dxf.get("bigfont", "") or style.dxf.get("width", 1) != 1
            or style.dxf.get("oblique", 0) or style.dxf.get("flags", 0)
            or style.dxf.get("generation_flags", 0)
            or d.get("halign", 0) or d.get("valign", 0)
            or d.get("oblique", 0) or d.get("text_generation_flag", 0)
            or tuple(d.get("extrusion", (0, 0, 1))) != (0, 0, 1)
            or d.insert.z != 0 or abs(rotation / 90 - round(rotation / 90)) > 1e-9
            or "\\" in d.text or "%%" in d.text or not d.text.strip()):
        return None
    height, width = d.height, d.get("width", 1)
    if not all(isfinite(v) for v in [height, width, rotation, *d.insert]) or height <= 0 or width <= 0:
        return None
    metrics = librecad_text_metrics(d.text)
    if metrics.fallback_glyph_count:
        return None
    c, s = cos(radians(rotation)), sin(radians(rotation))
    points = []
    for x, y in ((metrics.min_x, metrics.min_y), (metrics.max_x, metrics.min_y),
                 (metrics.max_x, metrics.max_y), (metrics.min_x, metrics.max_y)):
        x, y = x * height / metrics.em_height * width, y * height / metrics.em_height
        points.append((d.insert.x + c * x - s * y, d.insert.y + s * x + c * y))
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]
