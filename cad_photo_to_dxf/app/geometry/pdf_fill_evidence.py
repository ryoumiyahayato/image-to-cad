"""Bounded fill-only simple linear polygon extraction on the original PDF parent canvas."""

from __future__ import annotations
import ctypes as ct
from dataclasses import replace
from pathlib import Path
from time import perf_counter
import numpy as np
from app.core.arc_types import PdfPathReference
from app.core.native_fill import (
    NativeFill,
    polygon_signed_distance,
    validate_simple_polygon,
)

MAX_FILLS = 16
MAX_LOCAL_PIXELS = 1_000_000
MAX_TOTAL_PIXELS = 8_000_000


def extract_pdf_fills(path, page_index, page, bitmap, scale, dpi):
    import pypdfium2 as pdfium

    raw = pdfium.raw
    started = perf_counter()
    width, height = bitmap.width, bitmap.height
    pos = bitmap.get_posconv(page)
    origin = np.array(pos.to_page(0, 0))
    basis = np.column_stack(
        (
            (np.array(pos.to_page(width, 0)) - origin) / width,
            (np.array(pos.to_page(0, height)) - origin) / height,
        )
    )
    inverse = np.linalg.inv(basis)
    offset = -inverse @ origin
    mapping = (inverse[0, 0], inverse[1, 0], inverse[0, 1], inverse[1, 1], *offset)
    objects = []
    for obj in page.get_objects(max_depth=1):
        if len(objects) >= 32768 or obj.type == raw.FPDF_PAGEOBJ_FORM:
            return (), {"reason": "FILL_FORM_OR_OBJECT_BUDGET", "accepted": 0}
        objects.append(obj)
    rejected, accepted, facts = [], [], []
    if len(objects) > 32768 or any(o.type == raw.FPDF_PAGEOBJ_FORM for o in objects):
        return (), {"reason": "FILL_FORM_OR_OBJECT_BUDGET", "accepted": 0}
    states = []
    for obj in objects:
        value = raw.FPDF_BOOL()
        if not raw.FPDFPageObj_GetIsActive(obj, ct.byref(value)):
            return (), {"reason": "FILL_ACTIVE_STATE_UNREADABLE", "accepted": 0}
        states.append(value.value)

    def render(crop=None):
        image = page.render(scale=scale, crop=crop or (0, 0, 0, 0))
        try:
            return np.array(image.to_pil().convert("RGB"))
        finally:
            image.close()

    def reference_polygon(points, rgba, crop):
        """Independent unclipped geometry on the identical integer parent grid."""
        document = pdfium.PdfDocument.new()
        reference = document.new_page(width / scale, height / scale)
        shape = None
        try:
            vertices = [
                (float(x / scale), float((height - y) / scale)) for x, y in points
            ]
            shape = raw.FPDFPageObj_CreateNewPath(*vertices[0])
            if not shape:
                raise ValueError("FILL_REFERENCE_PATH_UNAVAILABLE")
            for vertex in vertices[1:]:
                if not raw.FPDFPath_LineTo(shape, *vertex):
                    raise ValueError("FILL_REFERENCE_PATH_UNAVAILABLE")
            if not (
                raw.FPDFPath_Close(shape)
                and raw.FPDFPageObj_SetFillColor(shape, *rgba)
                and raw.FPDFPath_SetDrawMode(shape, raw.FPDF_FILLMODE_WINDING, 0)
            ):
                raise ValueError("FILL_REFERENCE_STYLE_UNAVAILABLE")
            raw.FPDFPage_InsertObject(reference, shape)
            shape = None  # The temporary page now owns this object.
            image = reference.render(scale=scale, crop=crop)
            try:
                return np.array(image.to_pil().convert("RGB"))
            finally:
                image.close()
        finally:
            if shape:
                raw.FPDFPageObj_Destroy(shape)
            reference.close()
            document.close()

    def switch(index=None, without=False):
        for j, (obj, state) in enumerate(zip(objects, states)):
            target = (
                (state if j != index else 0)
                if without
                else (state if j == index else 0)
            )
            if not raw.FPDFPageObj_SetIsActive(obj, target):
                raise ValueError("FILL_STATE_WRITE_FAILED")

    baseline = render()
    restored = True
    checked, total_pixels = 0, 0
    legacy_checked, polygon_checked = 0, 0
    accepted_indexes = set()
    try:
        plans = [(True, index, obj) for index, obj in enumerate(objects)]
        plans += [
            (False, index, obj)
            for index, obj in sorted(
                enumerate(objects), key=lambda item: -_object_box_area(item[1])
            )
        ]
        for legacy, index, obj in plans:
            if index in accepted_indexes:
                continue
            if perf_counter() - started > 8:
                rejected.append({"reason": "FILL_TIME_BUDGET"})
                break
            if obj.type != raw.FPDF_PAGEOBJ_PATH or not states[index]:
                continue
            fill, stroke = ct.c_int(), raw.FPDF_BOOL()
            if (
                not raw.FPDFPath_GetDrawMode(obj, ct.byref(fill), ct.byref(stroke))
                or not fill.value
                or stroke.value
            ):
                continue
            n = raw.FPDFPath_CountSegments(obj)
            if (legacy and n not in (4, 5)) or (not legacy and not 4 <= n <= 129):
                continue
            segments = [raw.FPDFPath_GetPathSegment(obj, j) for j in range(n)]
            if [raw.FPDFPathSegment_GetType(s) for s in segments] != [2] + [0] * (
                n - 1
            ) or any(raw.FPDFPathSegment_GetClose(s) for s in segments[:-1]):
                continue
            if legacy:
                if not raw.FPDFPathSegment_GetClose(segments[-1]):
                    continue
                if legacy_checked >= MAX_FILLS:
                    continue
                legacy_checked += 1
                checked += 1
            try:
                color = [ct.c_uint() for _ in range(4)]
                if not raw.FPDFPageObj_GetFillColor(obj, *[ct.byref(v) for v in color]):
                    raise ValueError("FILL_COLOR_UNREADABLE")
                rgba = tuple(v.value for v in color)
                if (
                    rgba[3] != 255
                    or rgba[:3] == (255, 255, 255)
                    or raw.FPDFPageObj_HasTransparency(obj)
                ):
                    raise ValueError("FILL_TRANSPARENCY_OR_COMPOSITING")
                clip = raw.FPDFPageObj_GetClipPath(obj)
                clip_count = raw.FPDFClipPath_CountPaths(clip) if clip else 0
                if clip_count > 0:
                    raise ValueError("FILL_CLIP_UNSUPPORTED")
                points = []
                matrix = obj.get_matrix()
                for seg in segments:
                    x, y = ct.c_float(), ct.c_float()
                    if not raw.FPDFPathSegment_GetPoint(seg, ct.byref(x), ct.byref(y)):
                        raise ValueError("FILL_POINT_UNREADABLE")
                    q = matrix.on_point(x.value, y.value)
                    points.append(tuple(inverse @ (np.asarray(q) - origin)))
                explicit_end = (
                    np.allclose(points[-1], points[0], atol=1e-6, rtol=0)
                    if legacy
                    else np.array_equal(points[-1], points[0])
                )
                if not explicit_end and not raw.FPDFPathSegment_GetClose(segments[-1]):
                    raise ValueError("FILL_OPEN_PATH_UNSUPPORTED")
                if explicit_end:
                    points.pop()
                validate_simple_polygon(points)
                candidate = NativeFill(
                    PdfPathReference(
                        Path(path).resolve().as_posix(), page_index + 1, index
                    ),
                    tuple(points),
                    rgba[:3],
                    mapping,
                    scale * 72,
                    version=1 if legacy else 2,
                    visibility="full-only-without-opaque-quad-v1"
                    if legacy
                    else "full-only-without-opaque-simple-polygon-v2",
                )
                if not legacy:
                    if polygon_checked >= MAX_FILLS:
                        rejected.append({"reason": "FILL_POLYGON_CANDIDATE_BUDGET"})
                        break
                    polygon_checked += 1
                    checked += 1
                p = np.asarray(points)
                x0, y0 = np.floor(p.min(axis=0)).astype(int) - 2
                x1, y1 = np.ceil(p.max(axis=0)).astype(int) + 2
                if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
                    raise ValueError("FILL_PAGE_EDGE_UNSUPPORTED")
                pixels = int((x1 - x0) * (y1 - y0))
                if (
                    pixels > MAX_LOCAL_PIXELS
                    or total_pixels + 4 * pixels > MAX_TOTAL_PIXELS
                ):
                    raise ValueError("FILL_LOCAL_RENDER_BUDGET")
                total_pixels += 4 * pixels
                crop = tuple(
                    max(0, v - 1e-5) / scale for v in (x0, height - y1, width - x1, y0)
                )
                for item, state in zip(objects, states):
                    if not raw.FPDFPageObj_SetIsActive(item, state):
                        raise ValueError("FILL_STATE_WRITE_FAILED")
                full = render(crop)
                switch(index)
                only = render(crop)
                switch(index, without=True)
                without = render(crop)
                reference = reference_polygon(points, rgba, crop)
                if (
                    full.shape != (y1 - y0, x1 - x0, 3)
                    or only.shape != full.shape
                    or without.shape != full.shape
                ):
                    raise ValueError("FILL_PARENT_GRID_UNRESOLVED")
                if reference.shape != only.shape or np.any(
                    np.abs(reference.astype(int) - only.astype(int)) > 2
                ):
                    raise ValueError("FILL_REFERENCE_GEOMETRY_OR_CLIP_CHANGED")
                if legacy:
                    yy, xx = np.mgrid[y0:y1, x0:x1]
                    q = np.stack((xx + 0.5, yy + 0.5), axis=-1)
                    signed = []
                    for a, b in zip(p, np.roll(p, -1, axis=0)):
                        edge = b - a
                        signed.append(
                            (
                                edge[0] * (q[..., 1] - a[1])
                                - edge[1] * (q[..., 0] - a[0])
                            )
                            / np.linalg.norm(edge)
                        )
                    signed = np.asarray(signed)
                    edge0 = np.roll(p, -1, axis=0) - p
                    edge1 = np.roll(edge0, -1, axis=0)
                    if np.all(
                        edge0[:, 0] * edge1[:, 1] - edge0[:, 1] * edge1[:, 0] > 0
                    ):
                        inside = np.min(signed, axis=0)
                    else:
                        inside = np.min(-signed, axis=0)
                else:
                    inside = polygon_signed_distance(p, x0, y0, x1, y1)
                core = inside > 1
                ink = np.any(only < 255, axis=2)
                expected = np.asarray(rgba[:3])
                if not core.any() or np.any(
                    np.abs(only[core].astype(int) - expected) > 2
                ):
                    raise ValueError("FILL_GEOMETRY_OR_CLIP_UNRESOLVED")
                if np.any(ink & (inside < -1)):
                    raise ValueError("FILL_NATIVE_OUTSIDE_POLYGON")
                # Every native colored sample must remain visible. Antialiasing
                # may become darker through same-color contact, never lighter.
                if np.any(full[ink].astype(int) > only[ink].astype(int) + 2):
                    raise ValueError("FILL_OCCLUDED_OR_COLOR_CHANGED")
                if legacy and np.any(np.abs(full[core].astype(int) - expected) > 2):
                    raise ValueError("FILL_CORE_CHANGED_BY_OTHER_OBJECT")
                # Darker later marks remain separate source objects; the full/only
                # no-lightening test above still rejects white holes and occlusion.
                accepted.append(candidate)
                accepted_indexes.add(index)
                facts.append(
                    {
                        "object_index": index,
                        "points": points,
                        "rgb": rgba[:3],
                        "core_pixels": int(core.sum()),
                        "edge_ring_pixels": int((np.abs(inside) <= 1).sum()),
                        "same_color_overlap_pixels": int(
                            (
                                core
                                & np.all(
                                    np.abs(without.astype(int) - expected) <= 2, axis=2
                                )
                            ).sum()
                        ),
                        "clip_api_count": clip_count,
                        "clip_geometry_verified": True,
                    }
                )
            except (ValueError, TypeError) as exc:
                rejected.append({"object_index": index, "reason": str(exc)})
    except Exception as exc:
        accepted = []
        rejected.append({"reason": str(exc)})
    finally:
        for item, state in zip(objects, states):
            try:
                restored = bool(raw.FPDFPageObj_SetIsActive(item, state)) and restored
            except Exception:
                restored = False
        for item, state in zip(objects, states):
            actual = raw.FPDF_BOOL()
            restored = (
                bool(raw.FPDFPageObj_GetIsActive(item, ct.byref(actual)))
                and actual.value == state
                and restored
            )
        restored = restored and np.array_equal(render(), baseline)
    if not restored:
        raise RuntimeError("FILL_PAGE_STATE_RESTORE_FAILED")
    return tuple(accepted), {
        "version": 2,
        "checked": checked,
        "legacy_checked": legacy_checked,
        "polygon_checked": polygon_checked,
        "accepted": len(accepted),
        "facts": facts,
        "rejected": rejected,
        "restored_and_reread": True,
        "seconds": perf_counter() - started,
    }


def apply_pdf_fill_evidence(structure, evidence):
    if evidence.source_size_px != structure.source_size_px:
        return structure
    fills = getattr(evidence, "native_fills", ())
    if not fills:
        return structure
    if any(f.page_to_pixel != tuple(evidence.page_to_pixel) for f in fills):
        raise ValueError("FILL_TRANSFORM_BINDING_MISMATCH")
    existing = {f.object_id: f for f in structure.native_fills}
    for fill in fills:
        if (
            fill.source.document != evidence.binding["document"]
            or fill.source.page_number != evidence.binding["page_number"]
        ):
            raise ValueError("FILL_SOURCE_BINDING_MISMATCH")
        if fill.object_id in existing and existing[fill.object_id] != fill:
            raise ValueError("FILL_SOURCE_CHANGED")
        existing[fill.object_id] = fill
    return replace(
        structure,
        native_fills=tuple(existing.values()),
        provenance={
            **structure.provenance,
            "native_fill_evidence_v1": evidence.fill_analysis,
        },
    )


def _object_box_area(obj):
    try:
        left, bottom, right, top = obj.get_bounds()
        return max(0, right - left) * max(0, top - bottom)
    except Exception:
        return 0
