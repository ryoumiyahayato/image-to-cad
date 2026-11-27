"""Convert original PDF paths directly into editable DXF geometry.

Lines, polylines, cubic splines and filled boundaries retain their native
coordinates. Circular cubic constructions are exported as ARC or CIRCLE.
"""
from __future__ import annotations

import math
import re

import ezdxf
import numpy as np
import pymupdf as fitz

from app.geometry.pdf_arc_evidence import fit_cubic_arc

PT_MM = 25.4 / 72.0
WEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70,
           80, 90, 100, 106, 120, 140, 158, 200, 211)


def _subpaths(path):
    paths, edges = [], []
    def finish(closed=False):
        nonlocal edges
        if edges:
            paths.append({"edges": edges, "closed": closed})
            edges = []
    for item in path["items"]:
        kind = item[0]
        if kind in {"l", "c"}:
            points = [tuple(p) for p in item[1:]]
            if edges and edges[-1][1][-1] != points[0]:
                finish()
            edges.append((kind, points))
        elif kind in {"re", "qu"}:
            finish()
            if kind == "re":
                r = fitz.Rect(item[1])
                points = [tuple(r.tl), tuple(r.tr), tuple(r.br), tuple(r.bl)]
                if item[2] < 0:
                    points.reverse()
            else:
                q = fitz.Quad(item[1])
                points = [tuple(q.ul), tuple(q.ur), tuple(q.lr), tuple(q.ll)]
            edges = [("l", [a, b]) for a, b in zip(points, points[1:] + points[:1])]
            finish(True)
        else:
            raise ValueError(f"UNSUPPORTED_PDF_PATH_COMMAND:{kind}")
    finish(bool(path.get("closePath")))
    return paths


def _arc(points, width):
    try:
        geometry, _ = fit_cubic_arc(points, max(float(width), 0.25))
        return geometry
    except (ValueError, np.linalg.LinAlgError):
        return None


def _closed_circle(edges, width):
    if len(edges) < 2 or any(kind != "c" for kind, _ in edges):
        return None
    arcs = [_arc(points, width) for _, points in edges]
    if any(a is None for a in arcs):
        return None
    first = arcs[0]
    if (any(math.dist(a["center"], first["center"]) > 1e-4 or abs(a["radius"] - first["radius"]) > 1e-4 for a in arcs)
            or abs(abs(sum(a["sweep_angle_deg"] for a in arcs)) - 360) > 1e-3
            or math.dist(edges[0][1][0], edges[-1][1][-1]) > 1e-4):
        return None
    return first


def _flatten(edges, transform, tolerance_mm=0.01):
    points = [transform(edges[0][1][0])]
    for kind, control in edges:
        if kind == "l":
            points.append(transform(control[-1]))
        else:
            p = np.asarray(control, float)
            second = 6 * np.linalg.norm(np.diff(p, n=2, axis=0), axis=1).max() * PT_MM
            n = max(4, min(4096, math.ceil(math.sqrt(second / (8 * tolerance_mm)))))
            for t in np.linspace(0, 1, n + 1)[1:]:
                points.append(transform((1-t)**3*p[0] + 3*(1-t)**2*t*p[1] + 3*(1-t)*t*t*p[2] + t**3*p[3]))
    return points


def _attributes(doc, path, mode, monochrome):
    a = {"layer": "PDF_GEOMETRY", "color": 256}
    rgb = path.get("color" if mode == "stroke" else "fill")
    if not monochrome and rgb:
        a["true_color"] = ezdxf.colors.rgb2int(tuple(max(0, min(255, round(c * 255))) for c in rgb))
    if mode == "stroke":
        width = max(0.0, float(path.get("width") or 0.0)) * PT_MM
        a["lineweight"] = min(WEIGHTS, key=lambda w: abs(w / 100 - width))
        pattern = str(path.get("dashes", "[] 0"))
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", pattern.split("]")[0])
        lengths = [float(v) * PT_MM for v in numbers if float(v) > 0]
        if lengths:
            if len(lengths) % 2:
                lengths *= 2
            name = "PDF_DASH_" + "_".join(format(v, ".6g").replace(".", "p") for v in lengths)
            if name not in doc.linetypes:
                doc.linetypes.new(name, dxfattribs={"pattern": [sum(lengths), *[v if i % 2 == 0 else -v for i, v in enumerate(lengths)]]})
            a["linetype"] = name
    opacity = path.get(mode + "_opacity", 1.0)
    if opacity is not None and opacity < 1.0:
        a["transparency"] = ezdxf.colors.float2transparency(1.0 - max(0.0, float(opacity)))
    return a


def add_native_pdf_path(doc, msp, path, world, monochrome):
    parts = _subpaths(path)
    width = float(path.get("width") or 0.0)
    if "f" in path["type"] and float(path.get("fill_opacity", 1.0) or 0) > 0:
        fill = path.get("fill") or (0, 0, 0)
        if all(float(c) >= 0.999 for c in fill):
            for part in parts:
                ring = _flatten(part["edges"], world)
                if len(ring) >= 3:
                    msp.add_wipeout(ring, dxfattribs={"layer": "PDF_GEOMETRY"})
        else:
            hatch = msp.add_hatch(color=7, dxfattribs=_attributes(doc, path, "fill", monochrome))
            for part in parts:
                boundary = hatch.paths.add_edge_path(flags=0)
                for kind, points in part["edges"]:
                    if kind == "l":
                        boundary.add_line(world(points[0]), world(points[-1]))
                    else:
                        boundary.add_spline(control_points=[world(p) for p in points],
                                            knot_values=[0, 0, 0, 0, 1, 1, 1, 1], degree=3)
                first, last = part["edges"][0][1][0], part["edges"][-1][1][-1]
                if first != last:
                    boundary.add_line(world(last), world(first))
    if "s" not in path["type"] or float(path.get("stroke_opacity", 1.0) or 0) <= 0:
        return
    attrs = _attributes(doc, path, "stroke", monochrome)
    for part in parts:
        edges = part["edges"]
        circle = _closed_circle(edges, width) if part["closed"] or edges[0][1][0] == edges[-1][1][-1] else None
        if circle:
            msp.add_circle(world(circle["center"]), circle["radius"] * PT_MM, dxfattribs=attrs)
        elif all(kind == "l" for kind, _ in edges):
            points = [edges[0][1][0], *[p[-1] for _, p in edges]]
            closed = part["closed"] or points[0] == points[-1]
            if points[0] == points[-1]:
                points.pop()
            if len(points) == 2 and not closed:
                msp.add_line(world(points[0]), world(points[1]), dxfattribs=attrs)
            elif len(points) >= 2:
                msp.add_lwpolyline([world(p) for p in points], close=closed, dxfattribs=attrs)
        else:
            for kind, points in edges:
                if kind == "l":
                    msp.add_line(world(points[0]), world(points[-1]), dxfattribs=attrs)
                    continue
                arc = _arc(points, width)
                if arc:
                    c = world(arc["center"])
                    start, end = world(points[0]), world(points[-1])
                    a0 = math.degrees(math.atan2(start[1]-c[1], start[0]-c[0])) % 360
                    a1 = math.degrees(math.atan2(end[1]-c[1], end[0]-c[0])) % 360
                    if arc["sweep_angle_deg"] < 0:
                        a0, a1 = a1, a0
                    msp.add_arc(c, arc["radius"] * PT_MM, a0, a1, dxfattribs=attrs)
                else:
                    msp.add_open_spline([(*world(p), 0) for p in points], degree=3, dxfattribs=attrs)
            if part["closed"] and edges[-1][1][-1] != edges[0][1][0]:
                msp.add_line(world(edges[-1][1][-1]), world(edges[0][1][0]), dxfattribs=attrs)
