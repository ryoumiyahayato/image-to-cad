"""Serialize source-bound path members; no saved-DXF postprocessing."""

from math import cos, radians, sin

import numpy as np

WEIGHTS = (
    0,
    5,
    9,
    13,
    15,
    18,
    20,
    25,
    30,
    35,
    40,
    50,
    53,
    60,
    70,
    80,
    90,
    100,
    106,
    120,
    140,
    158,
    200,
    211,
)


def _ring(path, transform, tolerance=0.01):
    points = [path["start"]]
    for edge in path["edges"]:
        p = np.asarray(edge["points"], float)
        if edge["kind"] == "L":
            points.append(p[-1])
        else:
            # HATCH polyline fallback, with a conservative cubic chord bound.
            second = 6 * np.linalg.norm(np.diff(p, n=2, axis=0), axis=1).max()
            n = max(1, int(np.ceil(np.sqrt(second / (8 * tolerance)))))
            if n > 4096:
                raise ValueError("HATCH_FLATTENING_BUDGET")
            t = np.linspace(0, 1, n + 1)[1:, None]
            points.extend(
                (1 - t) ** 3 * p[0]
                + 3 * (1 - t) ** 2 * t * p[1]
                + 3 * (1 - t) * t * t * p[2]
                + t**3 * p[3]
            )
    return [transform(*p) for p in points]


def add_native_path_entities(doc, space, paths, transform):
    if not paths:
        return []
    from app.geometry.native_pdf_choices import fill_component_perimeters, reference

    perimeters = fill_component_perimeters(paths)
    perimeter_ids = {fact["id"] for members in perimeters.values() for fact in members}
    layer = "NATIVE_PDF_PATH"
    if layer not in doc.layers:
        doc.layers.new(layer, dxfattribs={"color": 7})
    for appid in ("PDF_PATH_SOURCE", "PDF_PATH_ALIASES", "P3A_STROKE"):
        if appid not in doc.appids:
            doc.appids.new(appid)
    origin = np.asarray(transform(0, 0))
    unit = float(np.linalg.norm(np.asarray(transform(1, 0)) - origin))
    bounds = []
    emitted = {}
    for fact in paths:
        style = fact["style"]
        created = []
        member = 0

        def attrs(color):
            source_layer = "SOURCE_TEXT_OUTLINE" if "editable_text_owner" in fact else layer
            a = {"layer": source_layer, "color": 7}
            # ACI7 is the CAD foreground equivalent of PDF black; keep RGB facts
            # in provenance and preserve other explicit source colors.
            if tuple(color[:3]) != (0, 0, 0):
                a["true_color"] = (color[0] << 16) | (color[1] << 8) | color[2]
            dpi = fact.get("source_dpi", 25.4/unit)
            width = fact["stroke_width_px"] * 25.4 / dpi * 100
            a["lineweight"] = (
                min(WEIGHTS, key=lambda w: abs(w - width)) if style["width"] else 0
            )
            return a

        def bind(entity, role, subpath, edge, aliases=()):
            nonlocal member
            entity.set_xdata(
                "PDF_PATH_SOURCE",
                [
                    (1000, fact["id"]),
                    (1000, role),
                    (1071, int(fact["object_index"])),
                    (1071, subpath),
                    (1071, edge),
                    (1071, member),
                ],
            )
            if aliases:
                entity.set_xdata("PDF_PATH_ALIASES", [tag for ref in aliases for tag in (
                    (1000, ref["id"]), (1000, ref.get("role", role)),
                    (1071, int(ref["object_index"])), (1071, ref.get("subpath", -1)),
                    (1071, ref.get("edge", -1)))])
            if role in {"stroke", "bounded_curve"} and fact["stroke_width_px"] > 0:
                entity.set_xdata(
                    "P3A_STROKE",
                    [
                        (1000, "NATIVE_PDF_SOURCE_WIDTH"),
                        (1040, float(fact["stroke_width_px"])),
                        (1040, float(fact.get("source_dpi", 25.4/unit))),
                    ],
                )
            created.append(entity)
            emitted.setdefault(fact['id'],[]).append(entity)
            member += 1

        union = fact.get("fill_union")
        union_member = fact.get("fill_union_owner")
        if union:
            aliases = [{"id": sid, "object_index": oi, "role": "fill_union"}
                       for sid, oi in zip(union["source_ids"], union["objects"])]
            hatch = space.add_hatch(color=7, dxfattribs=attrs(style["colors"]["fill"]))
            for ring in union["rings"]:
                points = [transform(*p) for p in ring]
                hatch.paths.add_polyline_path(points, is_closed=True, flags=1)
                bounds.extend(points)
            bind(hatch, "fill_union", -1, -1, aliases)
        fill_paths = [p for p in fact["subpaths"] if not p.get("zero_area_fill")]
        if style["fill"] and not union_member and fill_paths:
            hatch = space.add_hatch(color=7, dxfattribs=attrs(style["colors"]["fill"]))
            hatch.dxf.hatch_style = 0
            for path in fill_paths:
                ring = _ring(path, transform)
                hatch.paths.add_polyline_path(ring, is_closed=True, flags=1)
                bounds.extend(ring)
            bind(hatch, "fill", -1, -1)
        if style["stroke"]:
            for si, path in enumerate(fact["subpaths"]):
                circle = path.get("circular")
                a = attrs(style["colors"]["stroke"])
                choice = path.get("cad_choice", {})
                if choice.get("type") == "LWPOLYLINE":
                    points = _ring(path, transform, choice["chord_error_upper_px"])
                    if path["closed"] and np.linalg.norm(np.asarray(points[0])-points[-1]) < 1e-8:
                        points.pop()
                    entity = space.add_lwpolyline(points, close=path["closed"], dxfattribs=a)
                    aliases = [alias for ei, edge in enumerate(path["edges"])
                               for alias in edge.get("aliases", ({"id": fact["id"],
                                   "object_index": fact["object_index"], "role": "bounded_curve",
                                   "subpath": si, "edge": ei},))]
                    bind(entity, "bounded_curve", si, -1, aliases)
                    bounds.extend(points)
                    continue
                if circle:
                    from app.export.trace_dxf_entities import affine_ellipse

                    ellipse, _ = affine_ellipse(
                        circle["center"], circle["radius"], circle["start"],
                        360. if circle["kind"] == "CIRCLE" else circle["sweep"], transform,
                    )
                    if ellipse is not None:
                        entity = space.new_entity("ELLIPSE", {**a, **ellipse.dxfattribs()})
                        bind(entity, "stroke", si, -1)
                        bounds.extend((p.x, p.y) for p in (
                            ellipse.start_point, ellipse.end_point, *ellipse.main_axis_points(),
                        ))
                        continue
                    center = transform(*circle["center"])
                    radius = circle["radius"] * unit
                    # Transform the source start vector, rather than assuming
                    # export rotation or reflection from a particular page.
                    angle = radians(circle["start"])
                    p = transform(
                        circle["center"][0] + circle["radius"] * cos(angle),
                        circle["center"][1] - circle["radius"] * sin(angle),
                    )
                    from math import atan2, degrees

                    start = degrees(atan2(p[1] - center[1], p[0] - center[0]))
                    if circle["kind"] == "CIRCLE":
                        entity = space.add_circle(center, radius, dxfattribs=a)
                    else:
                        end = start + circle["sweep"]
                        if circle["sweep"] < 0:
                            start, end = end, start
                        entity = space.add_arc(center, radius, start, end, dxfattribs=a)
                    bind(entity, "stroke", si, -1)
                    bounds.extend(
                        [
                            (center[0] - radius, center[1] - radius),
                            (center[0] + radius, center[1] + radius),
                        ]
                    )
                    continue
                for ei, edge in enumerate(path["edges"]):
                    if edge.get("shared_with") or edge.get("existing_line") is not None:
                        continue
                    p = [transform(*q) for q in edge["points"]]
                    bounds.extend(p)
                    if edge["kind"] == "L":
                        entity = space.add_line(*p, dxfattribs=a)
                    else:
                        entity = space.add_spline(degree=3, dxfattribs=a)
                        # Explicit planar geometry is a target-editor trial.
                        # Actual LibreCAD roundtrip, not first-file validity,
                        # decides whether this representation is supported.
                        entity.dxf.flags = 8
                        entity.dxf.extrusion = (0, 0, 1)
                        entity.control_points = p
                        entity.knots = [0, 0, 0, 0, 1, 1, 1, 1]
                    bind(entity, "stroke", si, ei, edge.get("aliases", ()))
        if created and not fact.get("fill_union_owner") and fact["id"] not in perimeter_ids:
            group = doc.groups.new(
                description="One observed PDF paint operation; engineering-object membership unresolved"
            )
            group.extend(created)
    from app.export.source_component import source_component
    for fact in paths:
        union=fact.get('fill_union')
        if not union or not union.get('component_block'):
            continue
        sources=union['source_ids']
        perimeter = perimeters.get(fact["id"], ())
        entities = [e for member in perimeter for e in emitted.get(member["id"], ())]
        entities.extend(e for sid in sources for e in emitted.get(sid, ()))
        refs=[{'id':sid,'object_index':oi,'role':'paint_component'}
              for sid,oi in zip(sources,union['objects'])]
        refs.extend(reference(member, role="paint_perimeter") for member in perimeter)
        insert=source_component(doc,space,entities,f"PDF_PAINT_{fact['object_index']}",refs)
        insert.set_xdata('PDF_PATH_SOURCE',[(1000,fact['id']),(1000,'paint_component'),
            (1071,fact['object_index']),(1071,-1),(1071,-1),(1071,-1)])
    return bounds
