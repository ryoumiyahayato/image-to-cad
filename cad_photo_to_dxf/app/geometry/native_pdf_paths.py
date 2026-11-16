"""Opt-in source-member geometry transaction, after unchanged text processing.

No oracle lists or object-role classifier. Unqualified source paint stays in an
actual counterfactual PDF render. The transaction never edits a saved DXF.
"""

from __future__ import annotations

import ctypes as ct
from collections import Counter
from dataclasses import replace
from math import atan2, degrees
from time import monotonic
from uuid import uuid4

import numpy as np
import pypdfium2 as pdfium

from app.geometry.raster_trace import trace_binary

KEY = "native_pdf_path_geometry_v1"
POLICY = "source-path-member-representation-v5"
MAX_OBJECTS = 4096
MAX_SEGMENTS = 512
MAX_LOCAL_PIXELS = 4_000_000
MAX_TOTAL_LOCAL_PIXELS = 160_000_000
MAX_SECONDS = 60
MAX_CANVAS_PIXELS = 16_000_000
CIRCLE_ERROR_PX = 0.03
OCCLUSION_GRAY_ALLOWANCE = 2  # Same numerical allowance as existing native TEXT proof.


def circular_chain(edges):
    """Only standard quarter-cubic constructions, with a full-locus bound.

    Ordinary/elliptic Beziers keep their exact cubic SPLINE representation.
    This is a bounded geometric equivalence, not historical circle identity.
    """
    if not 1 <= len(edges) <= 4 or any(e["kind"] != "C" for e in edges):
        return None
    center, radius, sweep, upper = None, None, 0.0, 0.0
    for edge in edges:
        p = np.asarray(edge["points"], float)
        t0, t1 = p[1] - p[0], p[3] - p[2]
        a = np.array([t0, t1])
        if abs(np.linalg.det(a)) < 1e-12:
            return None
        c = np.linalg.solve(a, [t0 @ p[0], t1 @ p[3]])
        r = float(np.linalg.norm(p[0] - c))
        if r <= 0 or not np.isfinite(r):
            return None
        k = 4 * (np.sqrt(2) - 1) / 3
        # A source construction test, not just a least-squares circle fit.
        if (
            abs(np.dot(p[0] - c, p[3] - c)) > 1e-4 * r * r
            or max(abs(np.linalg.norm(t0) - k * r), abs(np.linalg.norm(t1) - k * r))
            > 0.002
        ):
            return None
        if center is not None and (
            np.linalg.norm(c - center) > 0.002 or abs(r - radius) > 0.002
        ):
            return None
        speed = 3 * np.linalg.norm(np.diff(p, axis=0), axis=1).max()
        count = max(513, int(np.ceil(speed / 0.01)) + 1)
        if count > 16385:
            return None
        t = np.linspace(0, 1, count)[:, None]
        q = (
            (1 - t) ** 3 * p[0]
            + 3 * (1 - t) ** 2 * t * p[1]
            + 3 * (1 - t) * t * t * p[2]
            + t**3 * p[3]
        )
        bound = float(
            np.abs(np.linalg.norm(q - c, axis=1) - r).max() + speed / (2 * (count - 1))
        )
        if bound > CIRCLE_ERROR_PX:
            return None
        angle = np.unwrap(np.arctan2(-(q[:, 1] - c[1]), q[:, 0] - c[0]))
        delta = float(degrees(angle[-1] - angle[0]))
        if abs(abs(delta) - 90) > 0.01 or np.any(np.diff(angle) * delta < -1e-10):
            return None
        if sweep and delta * sweep < 0:
            return None
        center, radius, sweep, upper = c, r, sweep + delta, max(upper, bound)
    start = degrees(
        atan2(
            -(edges[0]["points"][0][1] - center[1]),
            edges[0]["points"][0][0] - center[0],
        )
    )
    closed = (
        np.linalg.norm(np.array(edges[-1]["points"][-1]) - edges[0]["points"][0]) < 1e-5
    )
    return {
        "kind": "CIRCLE" if closed and abs(abs(sweep) - 360) < 0.01 else "ARC",
        "center": center.tolist(),
        "radius": radius,
        "start": start,
        "sweep": sweep,
        "radial_upper_bound_px": upper,
    }


def subpaths(segments, transform):
    paths = []
    current = None
    point = None
    i = 0
    while i < len(segments):
        typ, p, close = segments[i]
        if typ == 2:
            current = {"start": transform(p), "edges": [], "closed": False}
            paths.append(current)
            point = current["start"]
        elif typ == 0 and current is not None:
            end = transform(p)
            current["edges"].append({"kind": "L", "points": [point, end]})
            point = end
        elif typ == 1 and current is not None:
            if i + 2 >= len(segments) or any(s[0] != 1 for s in segments[i : i + 3]):
                raise ValueError("INVALID_CUBIC_SEQUENCE")
            points = [point] + [transform(s[1]) for s in segments[i : i + 3]]
            current["edges"].append({"kind": "C", "points": points})
            point = points[-1]
            close = segments[i + 2][2]
            i += 2
        else:
            raise ValueError("UNSUPPORTED_SEGMENT")
        if close:
            current["closed"] = True
            if np.linalg.norm(np.asarray(point) - current["start"]) > 1e-7:
                current["edges"].append(
                    {"kind": "L", "points": [point, current["start"]]}
                )
            point = current["start"]
        i += 1
    if not paths or any(not p["edges"] for p in paths):
        raise ValueError("EMPTY_PATH")
    return paths


def _local_render(page, box, size):
    x, y, u, v = box
    bitmap = pdfium.PdfBitmap.new_native(
        u - x, v - y, format=pdfium.raw.FPDFBitmap_Gray
    )
    try:
        bitmap.fill_rect((255, 255, 255, 255), 0, 0, u - x, v - y)
        pdfium.raw.FPDF_RenderPageBitmap(
            bitmap, page, -x, -y, *size, 0, pdfium.raw.FPDF_ANNOT
        )
        return bitmap.to_numpy().copy()
    finally:
        bitmap.close()


def render_without_active_objects(page, box, size, objects):
    """Render a crop without selected active PDF objects and restore visibility."""
    raw = pdfium.raw
    changed = []
    try:
        for obj in objects:
            if not raw.FPDFPageObj_SetIsActive(obj, 0):
                raise ValueError("Unable to isolate PDF paint")
            changed.append(obj)
        return _local_render(page, box, size)
    finally:
        restored = [raw.FPDFPageObj_SetIsActive(obj, 1) for obj in changed]
        if not all(restored):
            raise ValueError("Unable to restore PDF paint")


def _style(obj):
    r = pdfium.raw
    fill, stroke = ct.c_int(), r.FPDF_BOOL()
    width = ct.c_float()
    if not r.FPDFPath_GetDrawMode(
        obj, ct.byref(fill), ct.byref(stroke)
    ) or not r.FPDFPageObj_GetStrokeWidth(obj, ct.byref(width)):
        raise ValueError("STYLE_UNREADABLE")
    colors = {}
    for name, fn in (
        ("stroke", r.FPDFPageObj_GetStrokeColor),
        ("fill", r.FPDFPageObj_GetFillColor),
    ):
        color = [ct.c_uint() for _ in range(4)]
        if not fn(obj, *[ct.byref(c) for c in color]):
            raise ValueError("COLOR_UNREADABLE")
        colors[name] = [c.value for c in color]
    clip = r.FPDFPageObj_GetClipPath(obj)
    clip_count = r.FPDFClipPath_CountPaths(clip) if clip else -1
    result = {
        "fill": fill.value,
        "stroke": bool(stroke.value),
        "width": width.value,
        "colors": colors,
        "cap": r.FPDFPageObj_GetLineCap(obj),
        "join": r.FPDFPageObj_GetLineJoin(obj),
        "clip_count": clip_count,
        "dash_count": r.FPDFPageObj_GetDashCount(obj),
        "matrix": list(obj.get_matrix().get()),
    }
    if (
        clip_count > 0
        or result["dash_count"]
        or r.FPDFPageObj_HasTransparency(obj)
        or any(c[3] != 255 or c[:3] == [255, 255, 255] for c in colors.values())
    ):
        raise ValueError("CLIP_DASH_TRANSPARENCY_OR_WHITE_PAINT")
    if stroke.value and width.value > 0 and (result["cap"] != 1 or result["join"] != 1):
        raise ValueError("NONROUND_STROKE_CAP_OR_JOIN")
    return result


def _segments(obj):
    r = pdfium.raw
    n = r.FPDFPath_CountSegments(obj)
    if not 2 <= n <= MAX_SEGMENTS:
        raise ValueError("SEGMENT_BUDGET")
    result = []
    for i in range(n):
        s = r.FPDFPath_GetPathSegment(obj, i)
        x, y = ct.c_float(), ct.c_float()
        if not r.FPDFPathSegment_GetPoint(s, ct.byref(x), ct.byref(y)):
            raise ValueError("POINT_UNREADABLE")
        result.append(
            (
                r.FPDFPathSegment_GetType(s),
                [x.value, y.value],
                bool(r.FPDFPathSegment_GetClose(s)),
            )
        )
    return result


def _clone(segments, style):
    r = pdfium.raw
    shape = r.FPDFPageObj_CreateNewPath(*segments[0][1])
    i = 1
    while i < len(segments):
        typ, p, close = segments[i]
        if typ == 2:
            r.FPDFPath_MoveTo(shape, *p)
        elif typ == 0:
            r.FPDFPath_LineTo(shape, *p)
        elif typ == 1:
            r.FPDFPath_BezierTo(shape, *[v for s in segments[i : i + 3] for v in s[1]])
            close = segments[i + 2][2]
            i += 2
        else:
            raise ValueError("CLONE_SEGMENT_UNSUPPORTED")
        if close:
            r.FPDFPath_Close(shape)
        i += 1
    r.FPDFPath_SetDrawMode(shape, style["fill"], style["stroke"])
    r.FPDFPageObj_SetStrokeWidth(shape, style["width"])
    r.FPDFPageObj_SetStrokeColor(shape, *style["colors"]["stroke"])
    r.FPDFPageObj_SetFillColor(shape, *style["colors"]["fill"])
    r.FPDFPageObj_SetLineCap(shape, style["cap"])
    r.FPDFPageObj_SetLineJoin(shape, style["join"])
    r.FPDFPageObj_Transform(shape, *style["matrix"])
    return shape


def _fill_eligibility(paths, fill_mode):
    if not fill_mode:
        return
    from app.core.native_fill import validate_simple_polygon

    for path in paths:
        if any(e["kind"] != "L" for e in path["edges"]):
            raise ValueError("CURVED_FILL_TOPOLOGY_UNVERIFIED")
        p = np.asarray([e["points"][0] for e in path["edges"]], float)
        # A collinear fill has no area, but its observed stroke still exists.
        # A self-intersecting zero signed-area polygon is not this case.
        if len(p) >= 2 and np.linalg.matrix_rank(p-p[0], tol=1e-8) < 2:
            path["zero_area_fill"] = True
            continue
        validate_simple_polygon(p)
    # Multiple nonzero rings only when explicit source triangles have disjoint
    # interiors. No adjacent-object union, inferred holes, or implicit grouping.
    if fill_mode == 2 and len(paths) > 1:
        import cv2

        rings = []
        for path in paths:
            if path.get("zero_area_fill"):
                continue
            if any(e["kind"] != "L" for e in path["edges"]):
                raise ValueError("NONZERO_COMPOUND_CURVE_UNRESOLVED")
            p = np.asarray([e["points"][0] for e in path["edges"]], float)
            if len(p) != 3 or abs(cv2.contourArea((p-p[0]).astype(np.float32))) < 1e-8:
                raise ValueError("NONZERO_COMPOUND_NOT_DISJOINT_TRIANGLES")
            for previous in rings:
                if cv2.intersectConvexConvex((p-p[0]).astype(np.float32), (previous-p[0]).astype(np.float32))[0] > 1e-5:
                    raise ValueError("NONZERO_COMPOUND_INTERIOR_OVERLAP")
            rings.append(p)


def apply_native_pdf_paths(structure, image, evidence, dpi):
    plan = {
        "policy": POLICY,
        "status": "FALLBACK",
        "accepted": [],
        "rejected": [],
        "relations": [],
        "snapshot_id": str(uuid4()),
        "physical_network": "UNRESOLVED",
        "source_deletion_authority": "EXACT_PDF_OBJECT_TRANSACTION_ONLY",
    }

    def fallback(reason):
        if plan["accepted"]:
            plan["aborted_candidates"] = plan["accepted"]
            plan["accepted"] = []
        plan["status"] = "FALLBACK"
        plan["reason"] = reason
        return replace(structure, provenance={**structure.provenance, KEY: plan})

    native = structure.provenance.get("pdf_native_text", {})
    records = native.get("records", ())
    adopted = [
        int(x["object_index"]) for x in records if x.get("decision") == "ADOPTED"
    ]
    if not adopted:
        return fallback("NO_VERIFIED_NATIVE_TEXT_SOURCE")
    if structure.logos or structure.signatures:
        return fallback("PROTECTED_BACKGROUND_PAGE_RETAINS_BASELINE")
    if evidence is None or evidence.source_size_px != structure.source_size_px:
        return fallback("SOURCE_BINDING_UNAVAILABLE")
    binding = dict(evidence.binding)
    plan["source"] = binding
    if image.ndim != 2:
        return fallback("GRAYSCALE_CANVAS_REQUIRED")
    if image.size > MAX_CANVAS_PIXELS:
        return fallback("CANVAS_PIXEL_BUDGET")
    r = pdfium.raw
    document = pdfium.PdfDocument(binding["document"])
    page = document[binding["page_number"] - 1]
    reference_doc = pdfium.PdfDocument.new()
    reference = None
    states = []
    objects = []
    try:
        if page.get_rotation() != 0:
            return fallback("ROTATION_UNSUPPORTED")
        annotation_count = r.FPDFPage_GetAnnotCount(page)
        if annotation_count:
            bitmap = page.render(scale=dpi / 72, grayscale=True, draw_annots=False)
            try:
                no_annotations = bitmap.to_numpy().copy()
            finally:
                bitmap.close()
            if not np.array_equal(no_annotations, image):
                return fallback("VISIBLE_ANNOTATION_PAINT_UNSUPPORTED")
        plan["nonpainting_annotations"] = annotation_count
        objects = list(page.get_objects(max_depth=1))
        if len(objects) > MAX_OBJECTS or any(
            o.type not in (r.FPDF_PAGEOBJ_PATH, r.FPDF_PAGEOBJ_TEXT) for o in objects
        ):
            return fallback("FORM_IMAGE_SHADING_OR_OBJECT_BUDGET")
        size = structure.source_size_px
        whole = (0, 0, *size)
        if not np.array_equal(_local_render(page, whole, size), image):
            return fallback("SOURCE_CANVAS_MISMATCH")
        for obj in objects:
            state = r.FPDF_BOOL()
            if not r.FPDFPageObj_GetIsActive(obj, ct.byref(state)):
                return fallback("ACTIVE_STATE_UNREADABLE")
            states.append(state.value)
        for i in adopted:
            if not 0 <= i < len(objects) or objects[i].type != r.FPDF_PAGEOBJ_TEXT:
                return fallback("TEXT_SOURCE_IDENTITY_MISMATCH")
            r.FPDFPageObj_SetIsActive(objects[i], 0)
        background = _local_render(page, whole, size)
        # A raster OCR retirement mask is not authority over an independently
        # observed PDF PATH. Keep its actual paint, including shared strokes.
        for obj in objects:
            if obj.type == r.FPDF_PAGEOBJ_TEXT:
                r.FPDFPageObj_SetIsActive(obj, 0)
        path_paint = _local_render(page, whole, size) < 255
        bitmap = page.render(scale=dpi / 72, grayscale=True)
        pos = bitmap.get_posconv(page)
        origin = np.array(pos.to_page(0, 0))
        basis = np.column_stack(
            (
                (np.array(pos.to_page(size[0], 0)) - origin) / size[0],
                (np.array(pos.to_page(0, size[1])) - origin) / size[1],
            )
        )
        inverse = np.linalg.inv(basis)
        bitmap.close()
        media = page.get_mediabox(fallback_ok=False)
        crop = page.get_cropbox(fallback_ok=False) or page.get_bbox()
        if media is None:
            return fallback("PAGE_BOX_UNAVAILABLE")
        reference = reference_doc.new_page(media[2] - media[0], media[3] - media[1])
        reference.set_mediabox(*media)
        reference.set_cropbox(*crop)
        if reference.get_size() != page.get_size():
            return fallback("REFERENCE_PARENT_MISMATCH")
        protected = np.zeros(image.shape, bool)
        for mask in (
            structure.editable_text_source_mask,
            structure.source_text_outline_mask,
            structure.uncertain_text_outline_mask,
        ):
            if mask is not None:
                protected |= mask > 0
        for obj in objects:
            r.FPDFPageObj_SetIsActive(obj, 0)
        local_pixels = 0
        path_bounds = {}
        path_started = monotonic()
        for index, obj in enumerate(objects):
            if obj.type != r.FPDF_PAGEOBJ_PATH or not states[index]:
                continue
            try:
                style = _style(obj)
                segments = _segments(obj)
                matrix = obj.get_matrix()
                linear = np.array(
                    [
                        [style["matrix"][0], style["matrix"][2]],
                        [style["matrix"][1], style["matrix"][3]],
                    ]
                )
                scales = np.linalg.svd(inverse @ linear, compute_uv=False)
                if scales.min() <= 0 or scales.max() / scales.min() > 1.001:
                    raise ValueError("NONUNIFORM_STROKE_TRANSFORM")

                def transform(p):
                    return (inverse @ (np.array(matrix.on_point(*p)) - origin)).tolist()

                paths = subpaths(segments, transform)
                _fill_eligibility(paths, style["fill"])
                points = np.array(
                    [p for s in paths for e in s["edges"] for p in e["points"]]
                )
                pad = max(3, style["width"] * scales.max() + 2)
                lo = np.floor(points.min(axis=0) - pad).astype(int)
                hi = np.ceil(points.max(axis=0) + pad).astype(int)
                if np.any(lo < 0) or np.any(hi > size):
                    raise ValueError("PAGE_EDGE_UNRESOLVED")
                box = (*lo, *hi)
                x, y, u, v = box
                if (u - x) * (v - y) > MAX_LOCAL_PIXELS:
                    raise ValueError("LOCAL_RENDER_BUDGET")
                local_pixels += 2 * (u - x) * (v - y)
                if (
                    local_pixels > MAX_TOTAL_LOCAL_PIXELS
                    or monotonic() - path_started > MAX_SECONDS
                ):
                    raise ValueError("TOTAL_RENDER_BUDGET")
                r.FPDFPageObj_SetIsActive(obj, states[index])
                isolated = _local_render(page, box, size)
                r.FPDFPageObj_SetIsActive(obj, 0)
                shape = _clone(segments, style)
                r.FPDFPage_InsertObject(reference, shape)
                try:
                    rebuilt = _local_render(reference, box, size)
                finally:
                    r.FPDFPage_RemoveObject(reference, shape)
                    r.FPDFPageObj_Destroy(shape)
                if not np.array_equal(isolated, rebuilt):
                    raise ValueError("UNCLIPPED_SOURCE_REBUILD_DIFFERS")
                paint = isolated < 255
                if not np.any(paint):
                    raise ValueError("NO_VISIBLE_PAINT")
                retirement_intersection = int(
                    np.count_nonzero(paint & protected[y:v, x:u])
                )
                bright_delta = int(
                    (
                        background[y:v, x:u][paint].astype(int)
                        - isolated[paint].astype(int)
                    ).max()
                )
                if bright_delta > OCCLUSION_GRAY_ALLOWANCE:
                    raise ValueError("PAINT_OCCLUSION_OR_ORDER_UNRESOLVED")
                for s in paths:
                    s["circular"] = (
                        circular_chain(s["edges"]) if not style["fill"] else None
                    )
                    if not s["circular"] and any(e["kind"] == "C" for e in s["edges"]):
                        s["cad_choice"] = {"type": "LWPOLYLINE", "chord_error_upper_px": 0.02,
                            "reason": "TARGET_LIBRECAD_SPLINE_ROUNDTRIP_ZERO_NORMAL; ORIGINAL_CUBIC_CONTROLS_RETAINED"}
                fact = {
                    "id": f"{plan['snapshot_id']}/pdf-path/{index}",
                    "object_index": index,
                    "draw_order": index,
                    "style": style,
                    "subpaths": paths,
                    "stroke_width_px": style["width"] * float(scales.mean()),
                    "source_dpi": float(dpi),
                    "source_segments": segments,
                    "proof": "ACTUAL_OBJECT_EQUALS_UNCLIPPED_REBUILD; NO_BRIGHT_OCCLUSION; PDF_PATH_IDENTITY_PRESERVED_OVER_RASTER_MASK",
                    "role": "OBSERVED_PATH_ROLE_UNRESOLVED",
                    "grouping": "SAME_PDF_PAINT_OPERATION_ONLY",
                    "prior_text_mask_intersection_pixels": retirement_intersection,
                    "text_mask_authority_over_pdf_path": False,
                    "max_bright_delta_gray": bright_delta,
                    "gray_quantization_allowance": OCCLUSION_GRAY_ALLOWANCE,
                }
                plan["accepted"].append(fact)
                path_bounds[index] = box
                for si, s in enumerate(paths):
                    for ei in range(1, len(s["edges"])):
                        plan["relations"].append(
                            {
                                "kind": "path_continuation",
                                "source": f"{index}/{si}/{ei - 1}",
                                "target": f"{index}/{si}/{ei}",
                                "state": "VERIFIED_DRAWING_SEQUENCE",
                                "physical_network": "UNRESOLVED",
                            }
                        )
            except ValueError as exc:
                plan["rejected"].append({"object_index": index, "reason": str(exc)})
            finally:
                r.FPDFPageObj_SetIsActive(obj, 0)
        if not plan["accepted"]:
            return fallback("NO_QUALIFIED_SOURCE_PATHS")
        from app.geometry.native_pdf_choices import fill_components, choose_shared_strokes
        plan["fill_choices"] = []
        for candidate in fill_components(plan["accepted"]):
            sources = candidate["sources"]
            owner = candidate["owner"]
            # Compare actual PDF component paint with the proposed topology.
            # No source is removed on adjacency alone.
            points = np.asarray([p for ring in candidate["rings"] for p in ring])
            lo = np.floor(points.min(0)-3).astype(int)
            hi = np.ceil(points.max(0)+3).astype(int)
            box = (*lo, *hi)
            for f in sources:
                r.FPDFPageObj_SetIsActive(objects[f["object_index"]], 1)
            actual = _local_render(page, box, size)
            for f in sources:
                r.FPDFPageObj_SetIsActive(objects[f["object_index"]], 0)
            matrix = owner["style"]["matrix"]
            raw_basis = np.array([[matrix[0], matrix[2]], [matrix[1], matrix[3]]])
            raw_origin = np.array(matrix[4:])
            union_segments = []
            for ring in candidate["rings"]:
                for i, p in enumerate(ring):
                    raw_point = np.linalg.solve(raw_basis, origin+basis@p-raw_origin)
                    union_segments.append((2 if i == 0 else 0, raw_point.tolist(), i == len(ring)-1))
            union_style = dict(owner["style"], stroke=False)
            shape = _clone(union_segments, union_style)
            r.FPDFPage_InsertObject(reference, shape)
            stroke_shapes = []
            try:
                # Preserve all observed stroke roles. Internal hairlines may
                # affect display even when the filled areas form one region.
                for f in sources:
                    stroke_shape = _clone(f["source_segments"], dict(f["style"], fill=0))
                    r.FPDFPage_InsertObject(reference, stroke_shape)
                    stroke_shapes.append(stroke_shape)
                combined = _local_render(reference, box, size)
            finally:
                for stroke_shape in stroke_shapes:
                    r.FPDFPage_RemoveObject(reference, stroke_shape)
                    r.FPDFPageObj_Destroy(stroke_shape)
                r.FPDFPage_RemoveObject(reference, shape)
                r.FPDFPageObj_Destroy(shape)
            delta = np.abs(combined.astype(int)-actual.astype(int))
            decision = {"source_ids": [f["id"] for f in sources],
                        "objects": [f["object_index"] for f in sources],
                        "triangles": candidate["triangles"], "area_px2": candidate["area_px2"],
                        "max_gray_delta": int(delta.max()), "changed_pixels": int(np.count_nonzero(delta)),
                        "binary_ink_changed_pixels": int(np.count_nonzero((actual < 128) != (combined < 128))),
                        "decision": "KEEP_FRAGMENTS"}
            # The vector filled area is exactly the same and source strokes
            # remain. Permit only small antialias compositing differences with
            # identical visible ink support; retain measured differences.
            if decision['binary_ink_changed_pixels'] == 0 and delta.max() <= 16:
                decision["decision"] = "TOPOLOGICAL_HATCH_KEEP_SOURCE_STROKES"
                owner["fill_union"] = {"rings": candidate["rings"],
                    "source_ids": decision["source_ids"], "objects": decision["objects"],
                    "component_block": True,
                    "proof": "DISJOINT_SOURCE_TRIANGLES; NODED_SHARED_EDGES; SIMPLE_BOUNDARY; AREA_EQUAL; ACTUAL_RENDER_BINARY_EQUAL; AA_DELTA_AT_MOST_16; ORIGINAL_STROKES_RETAINED"}
                for f in sources:
                    f["fill_union_owner"] = owner["id"]
            plan["fill_choices"].append(decision)
        plan["duplicate_stroke_choices"] = choose_shared_strokes(plan["accepted"])
        from app.geometry.native_pdf_choices import choose_existing_lines
        retained_lines, line_records, legacy_decisions = choose_existing_lines(structure, plan["accepted"], source_dpi=dpi)
        plan["existing_geometry_choices"] = legacy_decisions
        # Preserve the older qualified geometry route on pages whose accepted
        # arcs/fills cannot be compared by this bounded selector. Do not wipe it.
        if structure.arcs or structure.native_fills:
            return fallback("EXISTING_ARC_OR_NATIVE_FILL_REQUIRES_MEMBER_COMPARISON")
        from app.ocr.pdf_path_text_ownership import bind_isolated_path_text

        active = {i: obj for i, obj in enumerate(objects) if states[i]}
        for obj in active.values():
            if not r.FPDFPageObj_SetIsActive(obj, 1):
                return fallback("ACTIVE_SOURCE_RESTORE_FAILED")
        plan["path_text_ownership"] = bind_isolated_path_text(
            page, size, active, plan["accepted"], path_bounds, structure.texts
        )
        removed = {f["object_index"] for f in plan["accepted"]} | set(adopted)
        for i, obj in enumerate(objects):
            r.FPDFPageObj_SetIsActive(obj, 0 if i in removed else states[i])
        residual = _local_render(page, whole, size)
        residual = residual.copy()
        residual[protected & ~path_paint] = 255
        binary = np.where(residual < structure.threshold, 0, 255).astype(np.uint8)
        contours = tuple(trace_binary(binary))
        plan.update(
            status="APPLIED",
            adopted_native_text_objects=adopted,
            source_path_types=dict(
                Counter(
                    e["kind"]
                    for f in plan["accepted"]
                    for p in f["subpaths"]
                    for e in p["edges"]
                )
            ),
            residual_policy="ACTUAL_PDF_RENDER_WITH_ONLY_ADOPTED_PATHS_AND_PROVED_TEXT_INACTIVE; EXISTING_TEXT_MASKS",
            residual_contours=len(contours),
            text_changes=0,
            style_limits="CAD lineweights are discrete; PDF round caps/joins recorded; hairline remains hairline",
        )
        from app.geometry.source_presentation import source_fill_records

        fills = source_fill_records(residual, contours, structure.texts)
        for fill in fills.values():
            if fill["source_gray"] == 0:
                fill["cad_foreground_source_black"] = True

        provenance = {
            **structure.provenance,
            KEY: plan,
            "stroke_presentation": {
                "line_records": line_records,
                "fill_records": fills,
            },
            "engineering_enclosures": [],
            "text_rule_contours": [],
        }
        return replace(
            structure,
            contours=contours,
            contour_binary=binary,
            straight_lines=retained_lines,
            arcs=(),
            native_fills=(),
            provenance=provenance,
        )
    except (ValueError, RuntimeError) as exc:
        return fallback("TRANSACTION_ABORTED: " + str(exc))
    finally:
        for obj, state in zip(objects, states):
            r.FPDFPageObj_SetIsActive(obj, state)
        restored = (
            _local_render(
                page, (0, 0, *structure.source_size_px), structure.source_size_px
            )
            if len(states) == len(objects)
            else None
        )
        if reference is not None:
            reference.close()
        reference_doc.close()
        page.close()
        document.close()
        if restored is not None and not np.array_equal(restored, image):
            raise ValueError("SOURCE_STATE_RESTORE_FAILED")
