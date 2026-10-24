"""Review existing TEXT with separate string and source-layout permissions."""

from __future__ import annotations

from dataclasses import replace
from math import cos, sin, radians, hypot
from pathlib import Path
from tempfile import TemporaryDirectory
import base64

import cv2
import ezdxf
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPolygonF,
    QTransform,
)

from app.export.ocr_outline_export import (
    NativeTextPlacement,
    _librecad_text_extent,
    _normalised_content,
    native_text_placement,
)
from app.ocr.librecad_lff import LIBRECAD_STYLE_NAME, librecad_text_path

REVIEW_EXPORT_VERSION = "snapshot-text-review-v1"
FIXED_LAYOUT_COLLISION_VERSION = "fixed-text-glyph-collision-v2"


def polygon(points):
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in points]))
    path.closeSubpath()
    return path


def visible_corners(placement):
    g, m = placement.geometry, placement.metrics
    angle = radians(g.rotation)
    c, s = cos(angle), sin(angle)
    sx = g.character_height / m.em_height * g.width_factor
    sy = g.character_height / m.em_height
    return tuple(
        (g.insert[0] + c * x * sx - s * y * sy, g.insert[1] + s * x * sx + c * y * sy)
        for x, y in (
            (m.min_x, m.min_y),
            (m.max_x, m.min_y),
            (m.max_x, m.max_y),
            (m.min_x, m.max_y),
        )
    )


def fixed_text_placement(candidate, content, *, transform, doc=None):
    """Measure the new string with the ORIGINAL height/width/insert/rotation."""
    original = native_text_placement(candidate, transform=transform, doc=doc)
    if original is None:
        raise ValueError("Original TEXT has no placement")
    metrics = _librecad_text_extent(content, style_name=LIBRECAD_STYLE_NAME)
    if (
        original.metrics.metric_source != "librecad-lff-visible-bounds"
        or original.metrics.fallback_reason
        or metrics.fallback_reason
        or metrics.metric_source != "librecad-lff-visible-bounds"
    ):
        raise ValueError("Exact packaged LFF glyph metrics are unavailable")
    g = original.geometry
    corners = visible_corners(NativeTextPlacement(content, metrics, g))
    center = (sum(p[0] for p in corners) / 4, sum(p[1] for p in corners) / 4)
    geometry = replace(
        g,
        rendered_width=metrics.width
        * g.character_height
        / metrics.em_height
        * g.width_factor,
        rendered_height=metrics.height * g.character_height / metrics.em_height,
        center_error=hypot(
            center[0] - g.target_center[0], center[1] - g.target_center[1]
        ),
        metric_source=metrics.metric_source,
        metric_fallback_reason=None,
    )
    return NativeTextPlacement(content, metrics, geometry)


def source_anchored_text_placement(candidate, content, quad, *, transform, doc=None):
    """Fit to independently evidenced, explicitly approved source ink bounds."""
    placement = native_text_placement(
        replace(
            candidate,
            text=content,
            quad=tuple(tuple(p) for p in quad),
            display_quad=None,
        ),
        transform=transform,
        doc=doc,
    )
    if (
        placement is None
        or placement.metrics.fallback_reason
        or placement.metrics.metric_source != "librecad-lff-visible-bounds"
    ):
        raise ValueError("Exact packaged LFF glyph metrics are unavailable")
    if not 0.5 <= placement.geometry.width_factor <= 2.0:
        raise ValueError(
            "Source fit requires an unsupported width factor; manual layout is required"
        )
    return placement


def glyph_footprint(placement):
    """Exact packaged LFF paths, conservatively stroked by one source pixel."""
    g, m = placement.geometry, placement.metrics
    matrix = QTransform()
    matrix.translate(*g.insert)
    matrix.rotate(g.rotation)
    matrix.scale(
        g.character_height / m.em_height * g.width_factor,
        -g.character_height / m.em_height,
    )
    path = matrix.map(librecad_text_path(placement.content))
    stroke = QPainterPathStroker()
    stroke.setWidth(1.0)
    return stroke.createStroke(path)


class ReviewLayoutGuard:
    """Conservative clear-space check against the actual emitted CAD objects.

    Constructed once per opened snapshot, never OCRs or reparses source masks on
    each edit. All coordinates below are unscaled CAD source units (+Y up).
    String-only proposals retain the original placement. Source-layout proposals
    require a separate native-region proof and confirmation. Other CAD objects
    are retained; unresolved collisions require manual layout review.
    """

    def __init__(self, structure):
        from app.export.trace_single_export import export_final_structure_dxf

        self.structure = structure
        self.height = structure.source_size_px[1]
        self.obstacles = []
        self.unknown = set()
        self._source_support_cache = {}
        self._glyph_cache = {}
        # Export is the authority for layer visibility, suppression and binding.
        with TemporaryDirectory(prefix="image-to-cad-review-layout-") as folder:
            path = Path(folder) / "baseline.dxf"
            export_final_structure_dxf(structure, path, allow_empty=True)
            doc = ezdxf.readfile(path)
            from app.core.member_binding import resolve_draftsman_output
            from app.ocr.text_output_contract import accepted_ocr_texts

            resolved = resolve_draftsman_output(structure)
            allowed = (
                set(resolved.emitted_indices("texts"))
                if resolved is not None
                else set(range(len(structure.texts)))
            )
            index_by_candidate = {
                id(candidate): index for index, candidate in enumerate(structure.texts)
            }
            selected = tuple(c for i, c in enumerate(structure.texts) if i in allowed)
            # The formal consumer collapses duplicates and sorts reading order.
            # Its entity order is not the original OCR candidate tuple order.
            emitted = [index_by_candidate[id(c)] for c in accepted_ocr_texts(selected)]
            self.emitted_indices = set(emitted)
            text_index = 0
            for entity in doc.modelspace():
                layer = doc.layers.get(entity.dxf.layer)
                if layer.is_off() or layer.is_frozen():
                    continue
                kind = entity.dxftype()
                owner = None
                p = QPainterPath()
                filled = False
                width = 1.0
                weight = entity.dxf.get("lineweight", -1)
                if weight == -1:
                    weight = layer.dxf.lineweight
                if entity.has_xdata("P3A_STROKE"):
                    dpi = float(entity.get_xdata("P3A_STROKE")[2].value)
                    width = max(width, weight / 100 * dpi / 25.4)
                if kind == "LWPOLYLINE":
                    width = max(width, entity.dxf.const_width)
                if kind == "TEXT":
                    owner = emitted[text_index]
                    text_index += 1
                    placement = native_text_placement(
                        structure.texts[owner], transform=self.transform
                    )
                    p = polygon(visible_corners(placement))
                    filled = True
                elif kind == "LINE":
                    p.moveTo(entity.dxf.start.x, entity.dxf.start.y)
                    p.lineTo(entity.dxf.end.x, entity.dxf.end.y)
                elif kind == "LWPOLYLINE":
                    points = list(entity.get_points("xy"))
                    if points:
                        p.moveTo(*points[0])
                        for point in points[1:]:
                            p.lineTo(*point)
                        if entity.closed:
                            p.closeSubpath()
                elif kind in {"CIRCLE", "ARC"}:
                    c, r = entity.dxf.center, entity.dxf.radius
                    if entity.has_xdata("P9_ARC"):
                        width = max(width, float(entity.get_xdata("P9_ARC")[1].value))
                    r += width / 2
                    # The full disk is a conservative exclusion for ARC too.
                    p.addEllipse(QPointF(c.x, c.y), r, r)
                    filled = True
                elif kind == "HATCH":
                    for boundary in entity.paths:
                        if not hasattr(boundary, "vertices"):
                            self.unknown.add("HATCH edge path")
                            continue
                        p = p.united(
                            polygon([(x, y) for x, y, *_ in boundary.vertices])
                        )
                    filled = True
                elif kind == "IMAGE":
                    a, u, v = entity.dxf.insert, entity.dxf.u_pixel, entity.dxf.v_pixel
                    w, h = entity.dxf.image_size.x, entity.dxf.image_size.y
                    p = polygon(
                        [
                            (a.x, a.y),
                            (a.x + u.x * w, a.y + u.y * w),
                            (a.x + u.x * w + v.x * h, a.y + u.y * w + v.y * h),
                            (a.x + v.x * h, a.y + v.y * h),
                        ]
                    )
                    filled = True
                else:
                    self.unknown.add(kind)
                if not p.isEmpty():
                    if not filled:
                        stroker = QPainterPathStroker()
                        # At least the one-pixel source stroke, including caps.
                        stroker.setWidth(width)
                        p = stroker.createStroke(p)
                    self.obstacles.append((owner, p, p.boundingRect()))
            if text_index != len(emitted):
                raise ValueError("Cannot bind emitted TEXT objects to this snapshot")

    def transform(self, x, y):
        return float(x), self.height - float(y)

    def _glyph_path(self, index, placement):
        key = (
            index,
            placement.content,
            tuple(placement.geometry.insert),
            placement.geometry.character_height,
            placement.geometry.width_factor,
            placement.geometry.rotation,
        )
        if key not in self._glyph_cache:
            self._glyph_cache[key] = glyph_footprint(placement)
        return self._glyph_cache[key]

    def check(self, index, content, active_texts=None, active_layouts=None):
        result = {
            "state": "NEEDS_LAYOUT_REVIEW",
            "reason": "",
            "export_version": REVIEW_EXPORT_VERSION,
            "collision_version": FIXED_LAYOUT_COLLISION_VERSION,
        }
        try:
            if index not in self.emitted_indices:
                raise ValueError(
                    "Candidate is not an emitted native TEXT in this snapshot"
                )
            if (
                content != _normalised_content(content)
                or not content
                or any(ord(c) < 32 for c in content)
            ):
                raise ValueError(
                    "Only a nonempty normalized single-line TEXT is supported"
                )
            if len(content.encode("utf-8")) > 250:
                raise ValueError(
                    "String exceeds the compatible DXF line-provenance byte limit"
                )
            original = self.structure.texts[index]
            placement = fixed_text_placement(
                original, content, transform=self.transform
            )
            result["geometry"] = placement.geometry.payload()
            proposal = polygon(visible_corners(placement))
            proposed_glyphs = self._glyph_path(index, placement)
            legal = polygon(placement.geometry.transformed_quad)
            tolerance = QPainterPathStroker()
            tolerance.setWidth(1e-6)
            legal = legal.united(tolerance.createStroke(legal))
            if not legal.contains(proposal):
                raise ValueError(
                    "New glyph bounds exceed the original legal display quad"
                )
            page = polygon(
                [
                    (0, 0),
                    (self.structure.source_size_px[0], 0),
                    self.structure.source_size_px,
                    (0, self.height),
                ]
            )
            if not page.contains(proposal):
                raise ValueError("New glyph bounds exceed the source page")
            if self.unknown:
                raise ValueError(
                    "Unmeasured CAD objects: " + ", ".join(sorted(self.unknown))
                )
            for owner, obstacle, bounds in self.obstacles:
                if owner == index:
                    continue
                if owner is not None:
                    content_other = (active_texts or {}).get(owner)
                    quad = (active_layouts or {}).get(owner)
                    if quad:
                        other = source_anchored_text_placement(
                            self.structure.texts[owner],
                            content_other,
                            quad,
                            transform=self.transform,
                        )
                    elif content_other:
                        other = fixed_text_placement(
                            self.structure.texts[owner],
                            content_other,
                            transform=self.transform,
                        )
                    else:
                        other = native_text_placement(
                            self.structure.texts[owner], transform=self.transform
                        )
                    if (
                        other.metrics.fallback_reason
                        or other.metrics.metric_source != "librecad-lff-visible-bounds"
                    ):
                        raise ValueError("Neighbor TEXT has unmeasured glyphs")
                    # Adjacent source rows can have overlapping extents without
                    # overlapping strokes (e.g. ascenders beside descenders).
                    # Match the source-layout consumer's complete LFF paths.
                    if proposed_glyphs.intersects(self._glyph_path(owner, other)):
                        raise ValueError(
                            "New glyphs intersect neighboring TEXT strokes"
                        )
                    continue
                if proposal.boundingRect().intersects(bounds) and proposal.intersects(
                    obstacle
                ):
                    raise ValueError(
                        "New glyph bounds intersect another visible CAD object"
                    )
            result.update(
                state="PASS",
                reason="Exact LFF bounds fit original quad; glyphs clear neighboring TEXT and bounds clear other CAD objects",
            )
        except (ValueError, RuntimeError, IndexError) as exc:
            result["reason"] = str(exc)
        return result

    def _is_preserved_source(self, obstacle, suggestion):
        """Whole existing footprint, inside unique native ink support only.

        This identifies an overlap to RETAIN. It confers no source ownership,
        replacement or deletion rights. Mixed roots/lines/other ink fail closed.
        """
        proof = suggestion["evidence"]["proof"]
        box = proof["support_box"]
        x0, y0, x1, y1 = box
        matrix = QTransform(1, 0, 0, -1, -x0, self.height - y0)
        local = matrix.map(obstacle)
        bounds = local.boundingRect()
        if (
            bounds.left() < 0
            or bounds.top() < 0
            or bounds.right() > x1 - x0
            or bounds.bottom() > y1 - y0
        ):
            return False
        key = suggestion["suggestion_uuid"]
        support = self._source_support_cache.get(key)
        if support is None:
            encoded = base64.b64decode(proof["source_only_support_png"], validate=True)
            support = cv2.imdecode(
                np.frombuffer(encoded, np.uint8), cv2.IMREAD_GRAYSCALE
            )
            if support is None or support.shape != (y1 - y0, x1 - x0):
                raise ValueError("Invalid native source support")
            self._source_support_cache[key] = support
        image = QImage(x1 - x0, y1 - y0, QImage.Format.Format_Grayscale8)
        image.fill(0)
        painter = QPainter(image)
        painter.fillPath(local, QColor(255, 255, 255))
        painter.end()
        pixels = np.frombuffer(image.constBits(), np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )[:, : image.width()]
        mask = pixels != 0
        return bool(np.any(mask) and not np.any(mask & (support == 0)))

    def check_source(
        self,
        index,
        content,
        suggestion,
        active_texts=None,
        active_layouts=None,
        *,
        display_group_support=None,
    ):
        from app.core.native_text_review import LAYOUT_VERSION

        result = dict(
            state="NEEDS_LAYOUT_REVIEW",
            reason="",
            export_version=REVIEW_EXPORT_VERSION,
            layout_version=LAYOUT_VERSION,
        )
        try:
            evidence = suggestion["evidence"]
            if (
                index not in self.emitted_indices
                or not evidence.get("layout_eligible")
                or evidence.get("status") != "NATIVE_TEXT_SUGGESTION"
            ):
                raise ValueError("No complete source region bound to this native TEXT")
            if (
                not content
                or content != _normalised_content(content)
                or any(ord(c) < 32 for c in content)
                or len(content.encode("utf-8")) > 250
            ):
                raise ValueError(
                    "Only a normalized, compatible single-line TEXT is supported"
                )
            quad = evidence["quad"]
            placement = source_anchored_text_placement(
                self.structure.texts[index], content, quad, transform=self.transform
            )
            result["geometry"] = placement.geometry.payload()
            result["source_quad"] = quad
            proposal = polygon(visible_corners(placement))
            proposed_glyphs = glyph_footprint(placement)
            page = polygon(
                [
                    (0, 0),
                    (self.structure.source_size_px[0], 0),
                    self.structure.source_size_px,
                    (0, self.height),
                ]
            )
            if not page.contains(proposal):
                raise ValueError("Source-anchored glyphs exceed the page")
            if self.unknown:
                raise ValueError(
                    "Unmeasured CAD objects: " + ", ".join(sorted(self.unknown))
                )
            preserved = 0
            for owner, obstacle, bounds in self.obstacles:
                if owner == index:
                    continue
                if owner is not None:
                    content_other = (active_texts or {}).get(owner)
                    other_quad = (active_layouts or {}).get(owner)
                    if other_quad:
                        other = source_anchored_text_placement(
                            self.structure.texts[owner],
                            content_other,
                            other_quad,
                            transform=self.transform,
                        )
                    elif content_other:
                        other = fixed_text_placement(
                            self.structure.texts[owner],
                            content_other,
                            transform=self.transform,
                        )
                    else:
                        other = native_text_placement(
                            self.structure.texts[owner], transform=self.transform
                        )
                    if (
                        other.metrics.fallback_reason
                        or other.metrics.metric_source != "librecad-lff-visible-bounds"
                    ):
                        raise ValueError("Neighbor TEXT has unmeasured glyphs")
                    # OCR quads may extend into adjacent rows. Test the actual
                    # current LFF strokes, not an empty rectangle between them.
                    if proposed_glyphs.intersects(self._glyph_path(owner, other)):
                        raise ValueError(
                            "Source-anchored glyphs intersect neighboring TEXT strokes"
                        )
                    continue
                nontext_probe = (
                    proposed_glyphs if display_group_support is not None else proposal
                )
                if nontext_probe.boundingRect().intersects(
                    bounds
                ) and nontext_probe.intersects(obstacle):
                    support_suggestion = (
                        display_group_support
                        if display_group_support is not None
                        else suggestion
                    )
                    if owner is None and self._is_preserved_source(
                        obstacle, support_suggestion
                    ):
                        preserved += 1
                    else:
                        raise ValueError(
                            "Source-anchored glyphs intersect another CAD object or mixed source footprint"
                        )
            result.update(
                state="PASS",
                reason="Exact LFF fit to unique visible source region; other CAD objects retained",
                preserved_source_footprints=preserved,
            )
        except (ValueError, RuntimeError, KeyError, TypeError, IndexError) as exc:
            result["reason"] = str(exc)
        return result
