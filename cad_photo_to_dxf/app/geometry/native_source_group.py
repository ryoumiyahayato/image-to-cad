"""Atomic, bounded PDF area/open-stroke replacement of a mixed raster LINE.

NativeFill v1 remains an area fact without raster ownership. This separate
contract transfers a complete saved trajectory to two visible areas and five
complete PDF open strokes. Detector histories remain historical observations.
"""

from __future__ import annotations

import ctypes as ct
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter

import numpy as np

from app.core.structure import metadata_to_jsonable
from app.geometry.line_detect import LineSegment

POLICY = "pdf-area-open-stroke-source-group-v1"
KEY = "native_source_group_replacements_v1"
BUDGETS = dict(
    pairs=8,
    page_objects=32768,
    path_segments=256,
    local_paths=64,
    page_pixels=32_000_000,
    pdf_bytes=128_000_000,
    local_pixels=250_000,
    local_renders=64,
    total_local_pixels=8_000_000,
    seconds=8.0,
)


def _rectangle(fill):
    x0, y0, x1, y1 = _bounds(fill.points)
    expected = np.array([(x0, y0), (x0, y1), (x1, y0), (x1, y1)])
    points = np.asarray(fill.points)
    return points.shape == (4, 2) and all(
        np.count_nonzero(np.all(np.isclose(points, corner, atol=1e-6, rtol=0), axis=1))
        == 1
        for corner in expected
    )


def _bounds(points):
    p = np.asarray(points)
    return (*p.min(axis=0), *p.max(axis=0))


def _inside(point, fill):
    # This policy admits axis-aligned vertical quads only.
    x0, y0, x1, y1 = _bounds(fill.points)
    x, y = point
    return x0 <= x <= x1 and y0 <= y <= y1


def _pairs(fills):
    for a in fills:
        ax0, ay0, ax1, ay1 = _bounds(a.points)
        if ay1 - ay0 <= ax1 - ax0 or ax1 - ax0 <= 2:
            continue
        if not _rectangle(a):
            continue
        for b in fills:
            bx0, by0, bx1, by1 = _bounds(b.points)
            if (
                _rectangle(b)
                and a.source.document == b.source.document
                and a.source.page_number == b.source.page_number
                and a.page_to_pixel == b.page_to_pixel
                and a.rgb == b.rgb
                and abs(ax0 - bx0) < 1e-6
                and abs(ax1 - bx1) < 1e-6
                and ay1 < by0
                and by1 - by0 > bx1 - bx0
                and by1 - ay0 < 1024
                and ax1 - ax0 < 128
            ):
                yield a, b


@dataclass(frozen=True)
class SourceGroupEvidence:
    fills: tuple
    stroke: dict
    paths: tuple
    open_strokes: tuple
    source_masks: tuple
    context_visibility: tuple
    nonpath_context: tuple
    box: tuple
    source_gray: np.ndarray
    group_gray: np.ndarray
    stroke_gray: np.ndarray
    without_stroke_gray: np.ndarray
    binding: dict


def _read_paths(page, mapping, raw, deadline=None):
    """Complete page-order facts; no path index is a production selector."""
    objects = list(page.get_objects(max_depth=1))
    if len(objects) > 32768 or any(o.type == raw.FPDF_PAGEOBJ_FORM for o in objects):
        raise ValueError("GROUP_FORM_OR_OBJECT_BUDGET")
    a, b, c, d, e, f = mapping
    facts, states, nonpaths = [], [], []
    for index, obj in enumerate(objects):
        if deadline is not None and perf_counter() > deadline:
            raise ValueError("GROUP_TIME_BUDGET")
        active = raw.FPDF_BOOL()
        if not raw.FPDFPageObj_GetIsActive(obj, ct.byref(active)):
            raise ValueError("GROUP_ACTIVE_STATE_UNAVAILABLE")
        states.append(active.value)
        if not active.value:
            continue
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            left, bottom, right, top = obj.get_bounds()
            points = [
                (a * x + c * y + e, b * x + d * y + f)
                for x, y in ((left, bottom), (left, top), (right, bottom), (right, top))
            ]
            bounds = _bounds(points)
            if not np.isfinite(bounds).all():
                raise ValueError("GROUP_NONPATH_BOUNDS_UNAVAILABLE")
            nonpaths.append(dict(index=index, type=obj.type, bounds=list(bounds)))
            continue
        n = raw.FPDFPath_CountSegments(obj)
        if n > 256:
            raise ValueError("GROUP_PATH_BUDGET")
        fill, stroke = ct.c_int(), raw.FPDF_BOOL()
        if not raw.FPDFPath_GetDrawMode(obj, ct.byref(fill), ct.byref(stroke)):
            raise ValueError("GROUP_DRAW_MODE_UNAVAILABLE")
        segments = []
        matrix = obj.get_matrix()
        for j in range(n):
            seg = raw.FPDFPath_GetPathSegment(obj, j)
            x, y = ct.c_float(), ct.c_float()
            if not raw.FPDFPathSegment_GetPoint(seg, ct.byref(x), ct.byref(y)):
                raise ValueError("GROUP_PATH_POINT_UNAVAILABLE")
            px, py = matrix.on_point(x.value, y.value)
            segments.append(
                dict(
                    type=raw.FPDFPathSegment_GetType(seg),
                    point=[a * px + c * py + e, b * px + d * py + f],
                    close=bool(raw.FPDFPathSegment_GetClose(seg)),
                )
            )
        color = [ct.c_uint() for _ in range(4)]
        if not raw.FPDFPageObj_GetStrokeColor(obj, *[ct.byref(v) for v in color]):
            raise ValueError("GROUP_STROKE_COLOR_UNAVAILABLE")
        width = ct.c_float()
        if not raw.FPDFPageObj_GetStrokeWidth(obj, ct.byref(width)):
            raise ValueError("GROUP_STROKE_WIDTH_UNAVAILABLE")
        clip = raw.FPDFPageObj_GetClipPath(obj)
        facts.append(
            dict(
                index=index,
                draw_order=index,
                fill=fill.value,
                stroke=bool(stroke.value),
                segments=segments,
                matrix=list(matrix.get()),
                rgba=[v.value for v in color],
                width_pt=width.value,
                line_cap=raw.FPDFPageObj_GetLineCap(obj),
                dash_count=raw.FPDFPageObj_GetDashCount(obj),
                transparent=bool(raw.FPDFPageObj_HasTransparency(obj)),
                clip_count=raw.FPDFClipPath_CountPaths(clip) if clip else 0,
            )
        )
    return objects, states, facts, nonpaths


def collect_source_groups(evidence, image, structure):
    """Use an independent memory document. Never toggle the loader's page."""
    import pypdfium2 as pdfium

    started = perf_counter()
    grayscale_render = image.ndim == 2
    if not grayscale_render:
        import cv2

        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    pairs = []
    for upper, lower in _pairs(evidence.native_fills):
        x0, y0, x1, gap0 = _bounds(upper.points)
        _, gap1, _, y1 = _bounds(lower.points)
        mixed = any(
            abs(line.x1 - line.x2) < 1e-7
            and x0 + 1 < line.x1 < x1 - 1
            and y0 <= min(line.y1, line.y2) < gap0
            and gap1 < max(line.y1, line.y2) <= y1
            and abs(line.width - (x1 - x0)) <= 2
            for line in structure.straight_lines
        )
        committed = any(
            tuple(r["fill_ids"]) == (upper.object_id, lower.object_id)
            for r in structure.provenance.get(KEY, ())
        )
        if mixed or committed:
            pairs.append((upper, lower))
    if not pairs:
        return ()
    if len(pairs) > BUDGETS["pairs"]:
        raise ValueError("GROUP_PAIR_BUDGET")
    if image.size > BUDGETS["page_pixels"]:
        raise ValueError("GROUP_PAGE_PIXEL_BUDGET")
    source_path = Path(evidence.binding["document"])
    if source_path.stat().st_size > BUDGETS["pdf_bytes"]:
        raise ValueError("GROUP_PDF_BYTE_BUDGET")
    document = pdfium.PdfDocument(source_path.read_bytes())
    page = document[evidence.binding["page_number"] - 1]
    raw = pdfium.raw
    try:
        objects, states, paths, nonpaths = _read_paths(
            page, evidence.page_to_pixel, raw, started + BUDGETS["seconds"]
        )
        scale = evidence.binding["requested_dpi"] / 72
        w, h = evidence.source_size_px

        rendered_pixels = 0
        local_renders = 0

        def charge(box):
            nonlocal rendered_pixels, local_renders
            pixels = (box[2] - box[0]) * (box[3] - box[1])
            if (
                pixels > BUDGETS["local_pixels"]
                or local_renders + 1 > BUDGETS["local_renders"]
                or rendered_pixels + pixels > BUDGETS["total_local_pixels"]
            ):
                raise ValueError("GROUP_LOCAL_RENDER_BUDGET")
            local_renders += 1
            rendered_pixels += pixels

        def render(selected=None, exclude=None, box=None, restoring=False):
            if not restoring:
                if perf_counter() - started > BUDGETS["seconds"]:
                    raise ValueError("GROUP_TIME_BUDGET")
                if box is not None:
                    charge(box)
            for i, (obj, state) in enumerate(zip(objects, states)):
                target = (
                    state if (selected is None or i in selected) and i != exclude else 0
                )
                if not raw.FPDFPageObj_SetIsActive(obj, target):
                    raise ValueError("GROUP_STATE_WRITE_FAILED")
            crop = (
                (0, 0, 0, 0)
                if box is None
                else tuple(
                    max(0, v - 1e-5) / scale
                    for v in (box[0], h - box[3], w - box[2], box[1])
                )
            )
            bitmap = page.render(scale=scale, crop=crop, grayscale=grayscale_render)
            try:
                if grayscale_render:
                    return np.array(bitmap.to_pil().convert("L"))
                import cv2

                return cv2.cvtColor(
                    np.array(bitmap.to_pil().convert("RGB")), cv2.COLOR_RGB2GRAY
                )
            finally:
                bitmap.close()

        baseline = render()
        if baseline.shape != image.shape or not np.array_equal(baseline, image):
            raise ValueError("GROUP_CURRENT_SOURCE_RENDER_MISMATCH")
        groups = []
        for upper, lower in pairs:
            x0, y0, x1, gap0 = _bounds(upper.points)
            _, gap1, _, y1 = _bounds(lower.points)
            center = (x0 + x1) / 2
            strokes = [
                p
                for p in paths
                if not p["fill"]
                and p["stroke"]
                and len(p["segments"]) == 2
                and [s["type"] for s in p["segments"]] == [2, 0]
                and not any(s["close"] for s in p["segments"])
                and np.allclose(
                    sorted([s["point"] for s in p["segments"]], key=lambda q: q[1]),
                    [(center, gap0), (center, gap1)],
                    atol=1e-6,
                    rtol=0,
                )
            ]
            if len(strokes) != 1:
                continue
            stroke = strokes[0]
            if (
                stroke["line_cap"] != 0
                or stroke["dash_count"] != 0
                or stroke["transparent"]
                or stroke["clip_count"] > 0
                or stroke["rgba"] != [*upper.rgb, 255]
            ):
                continue
            # Only an isotropic page transform and non-scaled object matrix are
            # supported for native pen width. Geometry always uses the full matrix.
            a, b, c, d, _, _ = evidence.page_to_pixel
            ma, mb, mc, md, _, _ = stroke["matrix"]
            if not np.allclose(
                [a * a + b * b, c * c + d * d, a * c + b * d],
                [scale * scale, scale * scale, 0],
                atol=1e-5,
            ):
                continue
            if not np.allclose(
                [ma * ma + mb * mb, mc * mc + md * md, ma * mc + mb * md],
                [1, 1, 0],
                atol=1e-6,
            ):
                continue
            stroke = dict(stroke, width_px=stroke["width_pt"] * scale)
            expected = [
                ((x0, gap0), (x1, gap0)),
                ((x0, gap1), (x1, gap1)),
                ((x0, gap0), (x0, gap1)),
                ((x1, gap0), (x1, gap1)),
            ]
            frame = []
            for start, end in expected:
                matches = [
                    p
                    for p in paths
                    if not p["fill"]
                    and p["stroke"]
                    and len(p["segments"]) == 2
                    and [s["type"] for s in p["segments"]] == [2, 0]
                    and not any(s["close"] for s in p["segments"])
                    and (
                        np.allclose(
                            [s["point"] for s in p["segments"]],
                            [start, end],
                            atol=1e-6,
                            rtol=0,
                        )
                        or np.allclose(
                            [s["point"] for s in p["segments"]],
                            [end, start],
                            atol=1e-6,
                            rtol=0,
                        )
                    )
                ]
                if len(matches) != 1:
                    break
                p = matches[0]
                if (
                    p["line_cap"] != 0
                    or p["dash_count"] != 0
                    or p["transparent"]
                    or p["clip_count"] > 0
                    or p["rgba"] != [*upper.rgb, 255]
                    or p["matrix"] != stroke["matrix"]
                ):
                    break
                frame.append(dict(p, width_px=p["width_pt"] * scale))
            if len(frame) != 4:
                continue
            open_strokes = tuple(sorted([stroke, *frame], key=lambda p: p["index"]))
            box = (
                max(0, int(np.floor(x0)) - 4),
                max(0, int(np.floor(y0)) - 4),
                min(w, int(np.ceil(x1)) + 4),
                min(h, int(np.ceil(y1)) + 4),
            )
            nonpath_context = []
            for item in nonpaths:
                bounds = item["bounds"]
                if not (
                    bounds[2] >= box[0]
                    and bounds[0] <= box[2]
                    and bounds[3] >= box[1]
                    and bounds[1] <= box[3]
                ):
                    continue
                nonpath_only = render(selected={item["index"]}, box=box)
                nonpath_without = render(exclude=item["index"], box=box)
                source_roi = baseline[box[1] : box[3], box[0] : box[2]]
                ink_pixels = int((nonpath_only < 250).sum())
                changed_pixels = int(np.count_nonzero(nonpath_without != source_roi))
                if ink_pixels or changed_pixels:
                    raise ValueError("GROUP_UNEXPLAINED_NONPATH_CONTEXT")
                nonpath_context.append(
                    dict(
                        item,
                        only_ink_pixels=ink_pixels,
                        without_changed_pixels=changed_pixels,
                        disposition="NO_LOCAL_INK_AND_NO_FULL_CONTEXT_CONTRIBUTION",
                    )
                )
            # Directly contacting paths are retained with their full geometry.
            # There is one expansion only, never a graph traversal.
            local = []
            for path in paths:
                px0, py0, px1, py1 = _bounds([s["point"] for s in path["segments"]])
                if px1 >= box[0] and px0 <= box[2] and py1 >= box[1] and py0 <= box[3]:
                    local.append(path)
            if len(local) > BUDGETS["local_paths"]:
                raise ValueError("GROUP_LOCAL_PATH_BUDGET")
            ids = {
                upper.source.object_index,
                lower.source.object_index,
                *[p["index"] for p in open_strokes],
            }
            # Match the complete current fill paths to admitted area facts.
            for fill in (upper, lower):
                p = next(
                    (p for p in paths if p["index"] == fill.source.object_index), None
                )
                points = [s["point"] for s in p["segments"]] if p else []
                if len(points) == 5 and np.allclose(points[0], points[-1], atol=1e-6):
                    points.pop()
                if (
                    not p
                    or not p["fill"]
                    or p["stroke"]
                    or not np.allclose(points, fill.points, atol=1e-6, rtol=0)
                ):
                    raise ValueError("GROUP_FILL_SOURCE_CHANGED")
            full = render(box=box)
            group = render(selected=ids, box=box)
            only = render(selected={stroke["index"]}, box=box)
            actual_strokes = render(
                selected={p["index"] for p in open_strokes}, box=box
            )
            reference_document = pdfium.PdfDocument.new()
            reference = reference_document.new_page(w / scale, h / scale)
            try:
                for path in open_strokes:
                    start, end = [v["point"] for v in path["segments"]]
                    shape = raw.FPDFPageObj_CreateNewPath(
                        start[0] / scale, (h - start[1]) / scale
                    )
                    if not shape:
                        raise ValueError("GROUP_REFERENCE_UNAVAILABLE")
                    try:
                        if not (
                            raw.FPDFPath_LineTo(
                                shape, end[0] / scale, (h - end[1]) / scale
                            )
                            and raw.FPDFPageObj_SetStrokeColor(shape, *path["rgba"])
                            and raw.FPDFPageObj_SetStrokeWidth(
                                shape, path["width_px"] / scale
                            )
                            and raw.FPDFPageObj_SetLineCap(shape, 0)
                            and raw.FPDFPath_SetDrawMode(shape, 0, 1)
                        ):
                            raise ValueError("GROUP_REFERENCE_STYLE_UNAVAILABLE")
                        raw.FPDFPage_InsertObject(reference, shape)
                        shape = None
                    finally:
                        if shape:
                            raw.FPDFPageObj_Destroy(shape)
                crop = tuple(
                    max(0, v - 1e-5) / scale
                    for v in (box[0], h - box[3], w - box[2], box[1])
                )
                charge(box)
                bitmap = reference.render(
                    scale=scale, crop=crop, grayscale=grayscale_render
                )
                try:
                    if grayscale_render:
                        expected_strokes = np.array(bitmap.to_pil().convert("L"))
                    else:
                        import cv2

                        expected_strokes = cv2.cvtColor(
                            np.array(bitmap.to_pil().convert("RGB")), cv2.COLOR_RGB2GRAY
                        )
                finally:
                    bitmap.close()
                if actual_strokes.shape != expected_strokes.shape or np.any(
                    np.abs(actual_strokes.astype(int) - expected_strokes.astype(int))
                    > 2
                ):
                    raise ValueError("GROUP_REFERENCE_GEOMETRY_OR_CLIP_CHANGED")
                mask = actual_strokes < 250
                if np.any(
                    full[mask].astype(int) > actual_strokes[mask].astype(int) + 2
                ):
                    raise ValueError("GROUP_OPEN_STROKE_OCCLUDED")
            finally:
                reference.close()
                reference_document.close()

            without = render(exclude=stroke["index"], box=box)
            if full.shape != (box[3] - box[1], box[2] - box[0]):
                raise ValueError("GROUP_PARENT_GRID_CHANGED")
            native = only < 250
            if not native.any() or np.any(
                full[native].astype(int) > only[native].astype(int) + 2
            ):
                raise ValueError("GROUP_STROKE_OCCLUDED")
            # Require the complete open-stroke interior to contribute in the real
            # full context. Counterfactual exposure is never output geometry.
            yy = np.arange(box[1], box[3])[:, None]
            interior = native & (yy > gap0 + 2) & (yy < gap1 - 2)
            if not interior.any() or np.any(without[interior] <= full[interior] + 2):
                raise ValueError("GROUP_STROKE_NOT_INDEPENDENTLY_VISIBLE")
            masks = []
            visibility = []
            for path in local:
                native_only = render(selected={path["index"]}, box=box)
                native_without = render(exclude=path["index"], box=box)
                ink = native_only < 250
                visible = ink & (native_without.astype(int) > full.astype(int) + 2)
                visibility.append(
                    dict(
                        index=path["index"],
                        draw_order=path["draw_order"],
                        native_ink_pixels=int(ink.sum()),
                        independent_visible_pixels=int(visible.sum()),
                        full_context_lighter_pixels=int(
                            (
                                ink & (full.astype(int) > native_only.astype(int) + 2)
                            ).sum()
                        ),
                        disposition="SOURCE_GROUP"
                        if path["index"] in ids
                        else "RETAIN_CONTEXT_ONLY",
                    )
                )
                if path["index"] in ids:
                    ink.setflags(write=False)
                    masks.append((path["index"], ink))
            arrays = (full, group, only, without)
            for arr in arrays:
                arr.setflags(write=False)
            groups.append(
                SourceGroupEvidence(
                    (upper, lower),
                    stroke,
                    tuple(local),
                    open_strokes,
                    tuple(masks),
                    tuple(visibility),
                    tuple(nonpath_context),
                    box,
                    *arrays,
                    dict(
                        document=evidence.binding["document"],
                        page_number=evidence.binding["page_number"],
                        requested_dpi=evidence.binding["requested_dpi"],
                        source_size_px=list(evidence.source_size_px),
                        page_to_pixel=list(evidence.page_to_pixel),
                        policy=POLICY,
                        budgets=dict(BUDGETS),
                        actual_local_renders=local_renders,
                        actual_local_pixels=rendered_pixels,
                    ),
                )
            )
        return tuple(groups)
    finally:
        if "objects" in locals():
            for obj, state in zip(objects, states):
                if not raw.FPDFPageObj_SetIsActive(obj, state):
                    raise RuntimeError("GROUP_STATE_RESTORE_FAILED")
            for obj, state in zip(objects, states):
                active = raw.FPDF_BOOL()
                if (
                    not raw.FPDFPageObj_GetIsActive(obj, ct.byref(active))
                    or active.value != state
                ):
                    raise RuntimeError("GROUP_STATE_RESTORE_FAILED")
            if "baseline" in locals() and not np.array_equal(
                render(restoring=True), baseline
            ):
                raise RuntimeError("GROUP_RENDER_RESTORE_FAILED")
        page.close()
        document.close()


@dataclass(frozen=True)
class SourceGroupPlan:
    base: object
    group: SourceGroupEvidence
    index: int
    native: tuple[LineSegment, ...]
    proof: dict


def plan_source_group(structure, group):
    upper, lower = group.fills
    if "draftsman_output_v1" in structure.provenance:
        raise ValueError("GROUP_FROZEN_COMPOSITE_BINDING")
    required = (
        "document",
        "page_number",
        "requested_dpi",
        "source_size_px",
        "page_to_pixel",
        "policy",
        "budgets",
    )
    if any(key not in group.binding for key in required):
        raise ValueError("GROUP_REQUIRED_SOURCE_BINDING_MISSING")
    if (
        group.binding["policy"] != POLICY
        or group.binding["budgets"] != BUDGETS
        or tuple(group.binding["source_size_px"]) != structure.source_size_px
        or any(
            group.binding["document"] != fill.source.document
            or group.binding["page_number"] != fill.source.page_number
            or tuple(group.binding["page_to_pixel"]) != fill.page_to_pixel
            or group.binding["requested_dpi"] != fill.source_dpi
            for fill in group.fills
        )
    ):
        raise ValueError("GROUP_SOURCE_BINDING_MISMATCH")
    if (upper, lower) not in tuple(_pairs(group.fills)):
        raise ValueError("GROUP_AXIS_RECTANGLE_REQUIRED")
    if any(f not in structure.native_fills for f in group.fills):
        raise ValueError("GROUP_REQUIRED_FILL_MISSING")
    x0, y0, x1, gap0 = _bounds(upper.points)
    _, gap1, _, y1 = _bounds(lower.points)
    # Complete mixed members only. No member ordinal, handle or detector ID is
    # involved in retrieval; support identity is checked after geometry retrieval.
    candidates = [
        (i, line)
        for i, line in enumerate(structure.straight_lines)
        if abs(line.x1 - line.x2) < 1e-7
        and x0 + 1 < line.x1 < x1 - 1
        and y0 <= min(line.y1, line.y2) < gap0
        and gap1 < max(line.y1, line.y2) <= y1
        and abs(line.width - (x1 - x0)) <= 2
    ]
    if len(candidates) != 1:
        raise ValueError("GROUP_MIXED_MEMBER_NOT_UNIQUE")
    index, old = candidates[0]
    ledgers = [
        o["ledger"]
        for o in structure.observations
        if o.get("event") == "source_stroke_reconciliation"
    ]
    if len(ledgers) != 1:
        raise ValueError("GROUP_SUPPORT_LEDGER_MISSING")
    ledger = ledgers[0]
    reps = [
        r
        for r in ledger["representations"]
        if tuple(r["source_ids"]) == old.source_ids
        and np.allclose(
            [
                *r["geometry_px"]["start"],
                *r["geometry_px"]["end"],
                r["geometry_px"]["width"],
            ],
            [old.x1, old.y1, old.x2, old.y2, old.width],
            atol=1e-7,
            rtol=0,
        )
    ]
    if len(reps) != 1 or reps[0]["structural_obligation_ids"]:
        raise ValueError("GROUP_COMPLETE_TRAJECTORY_IDENTITY_MISSING")
    rep = reps[0]
    intervals = rep["source_support_intervals"]
    if (
        len(intervals) != 1
        or abs(intervals[0]["start"]) > 1e-7
        or abs(intervals[0]["end"] - old.length) > 1e-6
    ):
        raise ValueError("GROUP_SUPPORT_INTERVAL_INCOMPLETE")
    evidence_by_id = {v["evidence_id"]: v for v in ledger["evidence"]}
    refs = intervals[0]["evidence_refs"]
    if not refs or any(
        ref not in evidence_by_id
        or evidence_by_id[ref]["kind"] != "TRAJECTORY_BINDING"
        or evidence_by_id[ref]["result"] != "SUPPORTED"
        for ref in refs
    ):
        raise ValueError("GROUP_SUPPORT_EVIDENCE_MISSING")
    # Revisit every half-pixel of the full stored support, including endpoints,
    # on the unchanged original gray and binary. The observed stroke width is
    # deliberately not treated as physical ink or a new source ownership mask.
    t = np.linspace(0, 1, int(np.ceil(old.length * 2)) + 1)
    pts = old.p1 + (old.p2 - old.p1) * t[:, None]
    pixels = np.rint(pts).astype(int)
    bx0, by0, bx1, by1 = group.box
    local = pixels - [bx0, by0]
    if (
        np.any(local < 0)
        or np.any(local[:, 0] >= bx1 - bx0)
        or np.any(local[:, 1] >= by1 - by0)
    ):
        raise ValueError("GROUP_SUPPORT_OUTSIDE_BOUND")
    xx, yy = local.T
    if structure.preview_binary is None or np.any(
        structure.preview_binary[pixels[:, 1], pixels[:, 0]] >= 128
    ):
        raise ValueError("GROUP_BINARY_SUPPORT_CHANGED")
    if np.any(group.source_gray[yy, xx] > 150) or np.any(
        group.group_gray[yy, xx] > 150
    ):
        raise ValueError("GROUP_SUPPORT_NOT_EXPLAINED_BY_SOURCE_OBJECTS")
    bands = []
    for ref in refs:
        support = evidence_by_id[ref]
        sx0, sy0, sx1, sy1 = map(int, support["roi_px"])
        if not (bx0 <= sx0 < sx1 <= bx1 and by0 <= sy0 < sy1 <= by1):
            raise ValueError("GROUP_FULL_SOURCE_BAND_OUTSIDE_BOUND")
        band = group.source_gray[sy0 - by0 : sy1 - by0, sx0 - bx0 : sx1 - bx0]
        owned = group.group_gray[sy0 - by0 : sy1 - by0, sx0 - bx0 : sx1 - bx0]
        binary = structure.preview_binary[sy0:sy1, sx0:sx1]
        binary_ink = binary < 128
        gray_ink = band <= 150
        foreground = gray_ink & binary_ink
        all_support = gray_ink | binary_ink
        if np.any(foreground & (owned > 150)):
            raise ValueError("GROUP_SOURCE_BAND_HAS_UNEXPLAINED_PIXELS")
        # Exact row runs retain the full affected support, not its bounding box
        # or a percentage. Blank and separate source runs remain distinct.
        runs = []
        for row in range(foreground.shape[0]):
            xs = np.flatnonzero(foreground[row])
            if len(xs):
                splits = np.split(xs, np.flatnonzero(np.diff(xs) > 1) + 1)
                runs.extend(
                    [[row + sy0, int(v[0]) + sx0, int(v[-1]) + sx0 + 1] for v in splits]
                )
        assignments = []
        assigned = np.zeros(foreground.shape, bool)
        for object_index, mask in group.source_masks:
            contribution = (
                all_support & mask[sy0 - by0 : sy1 - by0, sx0 - bx0 : sx1 - bx0]
            )
            assigned |= contribution
            assignments.append(
                dict(object_index=object_index, pixels=int(contribution.sum()))
            )
        if np.any(all_support & ~assigned):
            raise ValueError("GROUP_SUPPORT_PIXEL_SOURCE_IDENTITY_UNEXPLAINED")
        bands.append(
            dict(
                binary_black_gray_above_cutoff=int((binary_ink & ~gray_ink).sum()),
                gray_dark_binary_white=int((gray_ink & ~binary_ink).sum()),
                all_gray_or_binary_support_pixels=int(all_support.sum()),
                assignments=assignments,
                evidence_ref=ref,
                roi=[sx0, sy0, sx1, sy1],
                pixels=int(foreground.sum()),
                runs=runs,
                unexplained_pixels=0,
                assignees=[
                    upper.object_id,
                    lower.object_id,
                    *[p["index"] for p in group.open_strokes],
                ],
            )
        )
    # Any additional native stroke crossing the retired trajectory remains an
    # independent obligation. A nonseed crossing cannot be inferred from color.
    for path in group.paths:
        if not path["stroke"] or path["index"] == group.stroke["index"]:
            continue
        segs = path["segments"]
        for sa, sb in zip(segs, segs[1:]):
            a, b = np.array(sa["point"]), np.array(sb["point"])
            if sa["type"] not in (0, 2) or sb["type"] != 0:
                raise ValueError("GROUP_UNEXPLAINED_CURVED_CONTEXT")
            if abs(b[0] - a[0]) < 1e-9:
                if abs(a[0] - old.x1) <= group.stroke["width_px"] / 2:
                    raise ValueError("GROUP_INDEPENDENT_COLLINEAR_STROKE")
                continue
            u = (old.x1 - a[0]) / (b[0] - a[0])
            cy = a[1] + u * (b[1] - a[1])
            if 0 <= u <= 1 and min(old.y1, old.y2) <= cy <= max(old.y1, old.y2):
                # Opening frame endpoints are actual source stroke endpoints.
                if abs(cy - gap0) > 1e-6 and abs(cy - gap1) > 1e-6:
                    raise ValueError("GROUP_UNEXPLAINED_NATIVE_STROKE_CROSSING")
    endpoints = []
    for point in (old.p1, old.p2):
        fills = [f.object_id for f in group.fills if _inside(point, f)]
        if not fills:
            raise ValueError("GROUP_ENDPOINT_UNEXPLAINED")
        endpoints.append(
            dict(
                point=list(point),
                classification="RASTER_AREA_OBSERVATION_ENDPOINT",
                source_areas=fills,
            )
        )
    contacts = []
    for i, line in enumerate(structure.straight_lines):
        if i == index:
            continue
        a, b = line.p1, line.p2
        if abs(b[0] - a[0]) < 1e-9:
            continue
        u = (old.x1 - a[0]) / (b[0] - a[0])
        cy = a[1] + u * (b[1] - a[1])
        if 0 <= u <= 1 and min(old.y1, old.y2) <= cy <= max(old.y1, old.y2):
            fills = [f.object_id for f in group.fills if _inside((old.x1, cy), f)]
            if not fills:
                raise ValueError("GROUP_UNEXPLAINED_LINE_CROSSING")
            contacts.append(
                dict(
                    index=i,
                    point=[old.x1, float(cy)],
                    classification="RASTER_AREA_OBSERVATION_CROSSING",
                    source_areas=fills,
                    retained_line=asdict(line),
                    physical_node_assertion=False,
                )
            )
    # The shared text/graphic protection checks use the actual new source ink.
    from app.geometry.native_arc_replacement import _protection
    from types import SimpleNamespace

    stroke_ids = {p["index"] for p in group.open_strokes}
    stroke_ink = np.logical_or.reduce(
        [mask for index, mask in group.source_masks if index in stroke_ids]
    )
    _protection(
        structure,
        SimpleNamespace(
            box=group.box, native_gray=np.where(stroke_ink, 0, 255).astype(np.uint8)
        ),
    )
    natives = []
    for path in group.open_strokes:
        points = [s["point"] for s in path["segments"]]
        sid = f"PDF-PATH:p{upper.source.page_number}:o{path['index']}:s0"
        native = LineSegment(
            *points[0],
            *points[1],
            width=path["width_px"],
            layer=old.layer,
            source_ids=(sid,),
            history=(POLICY, "complete-visible-native-open-stroke"),
        )
        equivalents = [
            line
            for i, line in enumerate(structure.straight_lines)
            if i != index
            and (
                np.allclose(
                    [*line.p1, *line.p2], [*native.p1, *native.p2], atol=1e-6, rtol=0
                )
                or np.allclose(
                    [*line.p2, *line.p1], [*native.p1, *native.p2], atol=1e-6, rtol=0
                )
            )
        ]
        if equivalents:
            if len(equivalents) != 1 or equivalents[0] != native:
                raise ValueError("GROUP_EQUIVALENT_LINE_REQUIRES_SOURCE_IDENTITY")
        else:
            natives.append(native)
    natives = tuple(natives)
    local_lines = [
        dict(index=i, line=asdict(line))
        for i, line in enumerate(structure.straight_lines)
        if max(line.x1, line.x2) >= bx0
        and min(line.x1, line.x2) <= bx1
        and max(line.y1, line.y2) >= by0
        and min(line.y1, line.y2) <= by1
    ]
    local_contours = [
        dict(index=i, points=list(path.points))
        for i, path in enumerate(structure.contours)
        if _bounds(path.points)[2] >= bx0
        and _bounds(path.points)[0] <= bx1
        and _bounds(path.points)[3] >= by0
        and _bounds(path.points)[1] <= by1
    ]
    proof = dict(
        policy=POLICY,
        binding=group.binding,
        box=list(group.box),
        fill_ids=[f.object_id for f in group.fills],
        native_stroke=group.stroke,
        open_strokes=list(group.open_strokes),
        context_paths=list(group.paths),
        old_member_index=index,
        old_member=asdict(old),
        historic_representation=metadata_to_jsonable(rep),
        support_evidence_refs=list(refs),
        support_interval=[0, old.length],
        support_samples=len(t),
        full_source_bands=bands,
        source_gray_cutoff=150,
        support_disposition="complete trajectory assigned to visible native areas and open stroke; detector IDs historical",
        endpoints=endpoints,
        contacts=contacts,
        local_lines=local_lines,
        local_contours=local_contours,
        native_lines=[asdict(v) for v in natives],
        native_line_source=dict(
            document=upper.source.document,
            page_number=upper.source.page_number,
            object_index=group.stroke["index"],
            subpath_index=0,
        ),
        nearby_dispositions=[
            dict(
                index=item["index"],
                source_ids=list(item["line"]["source_ids"]),
                decision="RETAIN",
                reason="not selected for source transfer; complete saved support required",
                source_support_intervals=[
                    metadata_to_jsonable(r["source_support_intervals"])
                    for r in ledger["representations"]
                    if tuple(r["source_ids"]) == tuple(item["line"]["source_ids"])
                ],
            )
            for item in local_lines
            if item["index"] != index
        ],
        context_visibility=list(group.context_visibility),
        nonpath_context=list(group.nonpath_context),
        native_stroke_endpoints=[
            dict(
                source_index=p["index"],
                points=[v["point"] for v in p["segments"]],
                classification="VISIBLE_NATIVE_STROKE_ENDPOINTS_PRESERVED",
            )
            for p in group.open_strokes
        ],
        restored_and_reread=True,
    )
    return SourceGroupPlan(structure, group, index, natives, proof)


def commit_source_group(structure, plan):
    if structure is not plan.base:
        raise ValueError("GROUP_STALE_PLAN")
    verified = plan_source_group(structure, plan.group)
    if (
        verified.index != plan.index
        or verified.native != plan.native
        or verified.proof != plan.proof
    ):
        raise ValueError("GROUP_PLAN_CHANGED")
    lines = [line for i, line in enumerate(structure.straight_lines) if i != plan.index]
    lines.extend(plan.native)
    provenance = metadata_to_jsonable(structure.provenance)
    presentation = provenance.get("stroke_presentation", {})
    records = presentation.get("line_records", [])
    if records:
        if len(records) != len(structure.straight_lines):
            raise ValueError("GROUP_PRESENTATION_BINDING_CHANGED")
        # The retired thick raster presentation cannot certify native geometry.
        del records[plan.index]
        from app.geometry.source_presentation import lineweight_record

        for line in plan.native:
            records.append(
                dict(
                    lineweight_record(
                        dict(source_width_px=line.width), plan.group.fills[0].source_dpi
                    ),
                    source_support="complete visible PDF open stroke; source group replacement",
                    source_rgb=list(plan.group.fills[0].rgb),
                )
            )
    provenance.setdefault(KEY, []).append(plan.proof)
    # Legacy reconciliation stays immutable evidence. The new relation explicitly
    # supersedes this member; no modified geometry inherits its raster certificate.
    return replace(structure, straight_lines=tuple(lines), provenance=provenance)


def apply_native_source_groups(structure, image, evidence):
    if not getattr(evidence, "native_fills", ()):
        return structure
    decisions = []
    try:
        groups = collect_source_groups(evidence, image, structure)
        for group in groups:
            existing = structure.provenance.get(KEY, ())
            record = next(
                (
                    r
                    for r in existing
                    if r["native_stroke"]["index"] == group.stroke["index"]
                    and r["binding"]["document"] == group.binding["document"]
                    and r["binding"]["page_number"] == group.binding["page_number"]
                ),
                None,
            )
            if record:
                natives = [
                    LineSegment(
                        **{
                            **metadata_to_jsonable(v),
                            "source_ids": tuple(v["source_ids"]),
                            "history": tuple(v["history"]),
                            "classification_reasons": tuple(
                                v["classification_reasons"]
                            ),
                        }
                    )
                    for v in record["native_lines"]
                ]
                if (
                    any(v not in structure.straight_lines for v in natives)
                    or any(fill not in structure.native_fills for fill in group.fills)
                    or metadata_to_jsonable(record["native_stroke"]) != group.stroke
                    or metadata_to_jsonable(record["open_strokes"])
                    != list(group.open_strokes)
                    or metadata_to_jsonable(record["context_paths"])
                    != list(group.paths)
                    or any(
                        metadata_to_jsonable(record["binding"].get(key))
                        != metadata_to_jsonable(group.binding.get(key))
                        for key in (
                            "document",
                            "page_number",
                            "requested_dpi",
                            "source_size_px",
                            "page_to_pixel",
                            "policy",
                            "budgets",
                        )
                    )
                ):
                    raise ValueError("GROUP_COMMITTED_SOURCE_CHANGED")
                continue
            try:
                plan = plan_source_group(structure, group)
                structure = commit_source_group(structure, plan)
                decisions.append(
                    dict(
                        decision="REPLACED",
                        member_index=plan.index,
                        source=plan.proof["native_line_source"],
                    )
                )
            except (ValueError, KeyError) as exc:
                decisions.append(
                    dict(
                        decision="RETAINED",
                        reason=str(exc),
                        stroke_index=group.stroke["index"],
                    )
                )
    except (ValueError, KeyError, OSError) as exc:
        decisions.append(dict(decision="RETAINED", reason=str(exc)))
    if not decisions:
        return structure
    return replace(
        structure,
        observations=(*structure.observations, dict(event=POLICY, decisions=decisions)),
    )
