"""Serialize accepted native areas without adding boundary strokes."""

import numpy as np


def equivalent_visible_hatch(doc, entity, points, rgb):
    layer = doc.layers.get(entity.dxf.layer)
    if (
        layer.is_off()
        or layer.is_frozen()
        or entity.dxf.get("invisible", 0)
        or entity.dxf.get("transparency", 0) not in (0, 0x020000FF)
        or entity.dxf.extrusion != (0, 0, 1)
        or entity.dxf.elevation != (0, 0, 0)
        or entity.gradient is not None
        or not entity.dxf.solid_fill
        or len(entity.paths) != 1
    ):
        return False
    color = entity.rgb
    if color is None:
        return False  # An indexed color is not an established actual RGB fact.
    if color != rgb:
        return False
    boundary = entity.paths[0]
    if (
        not hasattr(boundary, "vertices")
        or not boundary.is_closed
        or len(boundary.vertices) < 3
    ):
        return False
    if any(v[2] != 0 for v in boundary.vertices):
        return False
    vertices = _comparison_ring([(v[0], v[1]) for v in boundary.vertices])
    wanted = _comparison_ring(points)
    if vertices is None or wanted is None or vertices.shape != wanted.shape:
        return False
    return any(
        np.allclose(np.roll(order, k, axis=0), wanted, atol=1e-6, rtol=0)
        for order in (vertices, vertices[::-1])
        for k in range(len(wanted))
    )


def add_native_fill_entities(doc, space, fills, transform, names):
    bounds = []
    if fills and "P18_NATIVE_FILL" not in doc.appids:
        doc.appids.add("P18_NATIVE_FILL")
    for fill in fills:
        points = [transform(x, y) for x, y in fill.points]
        equivalent = any(
            equivalent_visible_hatch(doc, e, points, fill.rgb)
            for e in space.query("HATCH")
        )
        if equivalent:
            continue
        hatch = space.add_hatch(
            color=7, dxfattribs={"layer": names["NATIVE_PDF_FILL"], "associative": 0}
        )
        hatch.rgb = fill.rgb
        hatch.paths.add_polyline_path(points, is_closed=True, flags=1)
        # DXF 1000 strings have a 255-byte limit; retain a compact source ref.
        hatch.set_xdata(
            "P18_NATIVE_FILL", [(1000, fill.object_id), (1000, fill.visibility)]
        )
        bounds.extend(points)
    return bounds


def _comparison_ring(points):
    """Remove redundant collinear samples only for equality, never serialization."""
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
        return None
    p = p.copy()
    changed = True
    while changed and len(p) > 3:
        changed = False
        for i in range(len(p)):
            a, b, c = p[(i - 1) % len(p)], p[i], p[(i + 1) % len(p)]
            ac = c - a
            length = np.linalg.norm(ac)
            if length <= 1e-12:
                continue  # Do not erase a reversal or a separate excursion.
            cross = ac[0] * (b[1] - a[1]) - ac[1] * (b[0] - a[0])
            if abs(cross) <= 1e-9 * length and np.dot(b - a, c - b) >= 0:
                p = np.delete(p, i, axis=0)
                changed = True
                break
    return p
