"""Representation choices over verified current PDF paint, not CAD handles."""

from collections import defaultdict

import cv2
import numpy as np


def reference(fact, subpath=-1, edge=-1, role="stroke"):
    return {"id": fact["id"], "object_index": fact["object_index"],
            "subpath": subpath, "edge": edge, "role": role}


def edge_key(edge):
    return tuple(sorted(tuple(p) for p in edge["points"]))


def _style_key(style):
    # Structural comparison; no content fingerprints or historical identity.
    return (style["fill"], style["stroke"], style["width"],
            tuple(style["colors"]["fill"]), tuple(style["colors"]["stroke"]),
            style["cap"], style["join"], tuple(style["matrix"]))


def fill_components(facts):
    """Exact shared edges propose unions; topology and rendering must prove them."""
    triangles = []
    for fact in facts:
        if not fact["style"]["fill"] or fact["style"]["width"] != 0:
            continue
        for si, path in enumerate(fact["subpaths"]):
            if path.get("zero_area_fill") or len(path["edges"]) != 3 or any(
                    e["kind"] != "L" for e in path["edges"]):
                continue
            p = np.asarray([e["points"][0] for e in path["edges"]], float)
            area = np.cross(p[1]-p[0], p[2]-p[0]).item()/2
            if area < 0:
                p = p[::-1]
            triangles.append((fact, si, p, abs(area)))
    parent = list(range(len(triangles)))
    if not triangles:
        return []
    vertices = np.unique(np.concatenate([p for _, _, p, _ in triangles]), axis=0)
    boundaries = []
    for _, _, triangle, _ in triangles:
        segments = []
        for start, end in zip(triangle, np.roll(triangle, -1, axis=0)):
            direction = end-start
            length = np.linalg.norm(direction)
            delta = vertices-start
            fraction = delta @ direction / length**2
            cross = np.abs(delta[:, 0]*direction[1]-delta[:, 1]*direction[0])
            inside = (fraction > 1e-10) & (fraction < 1-1e-10) & (cross <= 1e-7*length)
            points = [start, *vertices[inside][np.argsort(fraction[inside])], end]
            segments.extend((tuple(a), tuple(b)) for a, b in zip(points, points[1:]))
        boundaries.append(segments)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = defaultdict(list)
    for i, (f, _, p, _) in enumerate(triangles):
        for a, b in boundaries[i]:
            key = (_style_key(f["style"]), tuple(sorted((tuple(a), tuple(b)))))
            for j in edges[key]:
                parent[root(i)] = root(j)
            edges[key].append(i)
    groups = defaultdict(list)
    for i in range(len(triangles)):
        groups[root(i)].append(i)
    candidates = []
    for indices in groups.values():
        if len(indices) < 2:
            continue
        items = [triangles[i] for i in indices]
        source = {f["id"]: f for f, _, _, _ in items}
        # A paint object must participate completely; no partial object deletion.
        included = {(f["id"], si) for f, si, _, _ in items}
        if any((f["id"], si) not in included and not p.get("zero_area_fill")
               for f in source.values() for si, p in enumerate(f["subpaths"])):
            continue
        orders = sorted(f["draw_order"] for f in source.values())
        intervening = [f for f in facts if orders[0] <= f['draw_order'] <= orders[-1] and f['id'] not in source]
        if any(_style_key(f['style']) != _style_key(items[0][0]['style']) or
               not all(p.get('zero_area_fill') for p in f['subpaths']) for f in intervening):
            continue
        if len(orders)+len(intervening) != orders[-1]-orders[0]+1:
            continue
        # Pairwise disjoint interiors, evaluated near the local origin.
        origin = items[0][2][0]
        valid = True
        for i, (_, _, p, _) in enumerate(items):
            for _, _, q, _ in items[:i]:
                overlap, _ = cv2.intersectConvexConvex(
                    (p-origin).astype(np.float32), (q-origin).astype(np.float32))
                if overlap > 1e-5:
                    valid = False
        directed = defaultdict(list)
        for i in indices:
            for a, b in boundaries[i]:
                directed[tuple(sorted((a, b)))].append((a, b))
        boundary = []
        for occurrences in directed.values():
            if len(occurrences) == 1:
                boundary.extend(occurrences)
            elif len(occurrences) != 2 or occurrences[0] != occurrences[1][::-1]:
                valid = False
        following = dict(boundary)
        if len(following) != len(boundary) or len({b for _, b in boundary}) != len(boundary):
            valid = False
        rings = []
        while valid and following:
            start = next(iter(following))
            ring, point = [], start
            while point in following:
                ring.append(point)
                point = following.pop(point)
            if point != start or len(ring) < 3:
                valid = False
            else:
                rings.append([list(p) for p in ring])
        if not valid:
            continue
        from app.core.native_fill import validate_simple_polygon
        try:
            for ring in rings:
                validate_simple_polygon(ring)
        except ValueError:
            continue
        area = sum(abs(cv2.contourArea((np.asarray(r)-origin).astype(np.float32))) for r in rings)
        if abs(area-sum(a for _, _, _, a in items)) > 0.002:
            continue
        # Holes/nesting are left unresolved in this bounded implementation.
        if len(rings) != 1:
            continue
        boundary=(np.asarray(rings[0])-origin).astype(np.float32)
        if any(cv2.pointPolygonTest(boundary,tuple(np.asarray(p)-origin),True)<-1e-6
               for f in intervening for path in f['subpaths'] for edge in path['edges'] for p in edge['points']):
            continue
        source.update({f["id"]: f for f in intervening})
        candidates.append({"owner": min(source.values(), key=lambda f:f["draw_order"]),
                           "sources": sorted(source.values(), key=lambda f:f["draw_order"]), "rings": rings,
                           "triangles": len(items), "area_px2": area})
    return candidates


def _on_fill_boundary(points, ring):
    """Require coverage of the whole segment by collinear boundary edges."""
    start, end = np.asarray(points, dtype=float)
    direction = end - start
    length = np.linalg.norm(direction)
    tolerance = 1e-7  # Same source-pixel tolerance used to node triangle edges.
    if length <= tolerance:
        return False
    axis = direction / length
    offsets = ring - start
    on_axis = np.abs(offsets[:, 0] * axis[1] - offsets[:, 1] * axis[0]) <= tolerance
    distances = offsets @ axis
    intervals = sorted(
        (min(a, b), max(a, b))
        for a, b, on_edge in zip(distances, np.roll(distances, -1), on_axis & np.roll(on_axis, -1))
        if on_edge and max(a, b) >= 0 and min(a, b) <= length
    )
    covered = 0.0
    for left, right in intervals:
        if left > covered + tolerance:
            break
        covered = max(covered, right)
    return covered >= length - tolerance


def fill_component_perimeters(facts):
    """Attach whole adjoining hairline paint objects on a proved fill boundary."""
    by_order = {f["draw_order"]: f for f in facts}
    black = (0, 0, 0, 255)
    other_ink_bounds = []
    for fact in facts:
        if any(tuple(c) != black for c in fact["style"]["colors"].values()):
            points = np.asarray([p for s in fact["subpaths"] for e in s["edges"] for p in e["points"]])
            if points.size:
                pad = 1 + fact["stroke_width_px"] / 2
                other_ink_bounds.append((points.min(0) - pad, points.max(0) + pad))
    claims = defaultdict(list)
    for owner in facts:
        union = owner.get("fill_union")
        if not union or not union.get("component_block") or len(union["rings"]) != 1:
            continue
        style = owner["style"]
        if not style["stroke"] or style["width"] != 0 or any(tuple(c) != black for c in style["colors"].values()):
            continue
        ring = np.asarray(union["rings"][0], dtype=float)
        low, high = ring.min(0) - 1, ring.max(0) + 1
        if any(np.all(low <= end) and np.all(start <= high) for start, end in other_ink_bounds):
            continue
        members = set(union["source_ids"])
        for order in (min(union["objects"]) - 1, max(union["objects"]) + 1):
            fact = by_order.get(order)
            if (not fact or fact.get("fill_union_owner") or fact.get("fill_union")
                    or _style_key(fact["style"]) != _style_key(style)):
                continue
            paths = fact["subpaths"]
            if not paths or not all(p.get("zero_area_fill") and not p.get("cad_choice") for p in paths):
                continue
            edges = [edge for path in paths for edge in path["edges"]]
            allowed_sources = members | {fact["id"]}
            if not edges or any(
                edge["kind"] != "L"
                or edge.get("existing_line") is not None
                or (edge.get("shared_with") and edge["shared_with"]["id"] not in allowed_sources)
                or any(ref["id"] not in allowed_sources for ref in edge.get("aliases", ()))
                or not _on_fill_boundary(edge["points"], ring)
                for edge in edges
            ):
                continue
            claims[fact["id"]].append((owner["id"], fact))
    attached = defaultdict(list)
    for owners in claims.values():
        if len(owners) == 1:
            owner_id, fact = owners[0]
            attached[owner_id].append(fact)
    return attached


def choose_shared_strokes(facts):
    """Same opaque paint/style and no intervening object: share one expression."""
    groups = defaultdict(list)
    for f in facts:
        for si, p in enumerate(f["subpaths"]):
            if p.get("circular"):
                continue
            for ei, e in enumerate(p["edges"]):
                if e["kind"] == "L":
                    groups[edge_key(e)].append((f, si, ei, e))
    decisions = []
    for members in groups.values():
        if len(members) < 2:
            continue
        styles = {_style_key(f["style"]) for f, _, _, _ in members}
        orders = sorted({f["draw_order"] for f, _, _, _ in members})
        whole_path = [m for m in members if m[0]["subpaths"][m[1]].get("cad_choice")]
        equivalent = (len(styles) == 1 and len(whole_path) <= 1
                      and orders == list(range(orders[0], orders[-1]+1)))
        reason = "IDENTICAL_OPAQUE_STYLE_AND_SAME_OR_CONSECUTIVE_PAINT" if equivalent else "STYLE_OR_INTERVENING_PAINT_UNRESOLVED"
        if len(whole_path) > 1:
            reason = "OVERLAP_BETWEEN_INDIVISIBLE_CURVE_SUBPATHS"
        if equivalent and whole_path:
            # A line already emitted inside an indivisible polyline owns this
            # expression. Do not retain a competing standalone old LINE.
            owner = whole_path[0]
            members = [owner, *(m for m in members if m is not owner)]
        refs = [reference(f, si, ei) for f, si, ei, _ in members]
        if equivalent:
            members[0][3]["aliases"] = refs
            for _, _, _, e in members[1:]:
                e["shared_with"] = refs[0]
        decisions.append({"members": refs, "equivalent": equivalent, "reason": reason,
                          "styles": [f["style"] for f, _, _, _ in members],
                          "draw_orders": orders,
                          "display_role": "OPAQUE_SAME_INK; AA_MULTIPAINT_REMAINS_RENDER_CHECKED" if equivalent else "PRESERVE_ALL"})
    return decisions


def choose_existing_lines(structure, facts, *, source_dpi=None):
    """Keep an already accurate reconstructed LINE, with current source binding.

    Candidates need matching endpoints, width, color and drawing role. A mere
    bbox intersection cannot retain or retire a member. Partial/longer lines
    are not split here. Native coordinates win when the old fit is less exact.
    """
    edges = [(f, si, ei, e) for f in facts if not f["style"]["fill"]
             for si, p in enumerate(f["subpaths"])
             if not p.get("circular") and not p.get("cad_choice")
             for ei, e in enumerate(p["edges"]) if e["kind"] == "L"]
    kept, records, decisions = [], [], []
    presentation = structure.provenance.get("stroke_presentation", {})
    previous = presentation.get("line_records", ())
    for i, line in enumerate(structure.straight_lines):
        p = np.array([[line.x1, line.y1], [line.x2, line.y2]])
        nearest, error = None, float("inf")
        for f, si, ei, e in edges:
            q = np.asarray(e["points"])
            distance = min(np.linalg.norm(p-q, axis=1).max(),
                           np.linalg.norm(p-q[::-1], axis=1).max())
            if distance < error:
                nearest, error = (f, si, ei, e), float(distance)
        record = dict(previous[i] or {}) if previous else {}
        width = record.get("source_width_px", line.width)
        accepted = nearest is not None and error <= 0.05 and abs(width-nearest[0]["stroke_width_px"]) <= 0.05
        if accepted:
            f, si, ei, edge = nearest
            accepted = (edge.get("existing_line") is None and not edge.get("shared_with")
                        and tuple(record.get("source_rgb", (0, 0, 0))) == (0, 0, 0)
                        and f["style"]["colors"]["stroke"] == [0, 0, 0, 255])
        if accepted:
            dpi = source_dpi or record.get("source_dpi")
            if dpi is None or not np.isfinite(dpi) or dpi <= 0:
                accepted = False
        if accepted:
            from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
            aliases = edge.get("aliases", [reference(f, si, ei)])
            # Source-backed style is complete even when the raster fit had no
            # presentation record. Do not invent a category from an empty dict.
            width = float(f["stroke_width_px"])
            record.pop("source_rgb", None)
            record.update(category="NATIVE_PDF_SOURCE_WIDTH", source_width_px=width,
                source_dpi=float(dpi), source_width_mm=width*25.4/dpi,
                cad_lineweight=min(VALID_DXF_LINEWEIGHTS, key=lambda w:abs(w-width*25.4/dpi*100)),
                pdf_path_aliases=aliases)
            edge["existing_line"] = i
            kept.append(line)
            records.append(record)
        decisions.append({"collection": "straight_lines", "index": i,
                          "source_ids": list(line.source_ids),
                          "nearest_pdf_object": nearest[0]["object_index"] if nearest else None,
                          "endpoint_error_px": error if nearest else None,
                          "decision": "KEEP_EXISTING_LINE" if accepted else "USE_VERIFIED_NATIVE_OR_RESIDUAL",
                          "reason": "ENDPOINT_AND_STYLE_EQUIVALENCE" if accepted else "EXISTING_FIT_NOT_EQUIVALENT_TO_VERIFIED_SOURCE_EDGE"})
    # Other old representations require explicit current PDF identity. S2 has
    # no accepted ArcSegment or NativeFill members, so none are invented here.
    return tuple(kept), records, decisions
