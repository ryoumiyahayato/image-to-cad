"""Bounded optional evidence from the bitmap's still-open PDF page.

No CAD attachment, file-name rules or raster candidate promotion lives here.
"""

from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass, field, replace
from math import ceil, comb, degrees, isfinite
from pathlib import Path
from types import MappingProxyType
from collections import Counter
from time import perf_counter
from sys import getsizeof

import numpy as np

from app.core.arc_types import ArcSegment, PdfPathReference

POLICY = "pdf-simple-arc-evidence-v3-round-cap"
MAX_PAGE_OBJECTS = 32768
MAX_FORM_DEPTH = 8
MAX_PATH_SEGMENTS = 256
MAX_SUPPORT_CHECKS = 512
MAX_GEOMETRY_CHECKS = 64
MAX_ARCS = 16
MAX_LOCAL_RENDERS = 16
MAX_LOCAL_PIXELS = 1_000_000
MAX_TOTAL_LOCAL_PIXELS = 4_000_000
MAX_EVIDENCE_SECONDS = 5.0
MAX_SAMPLES = 16385


def pdf_geometry_binding(path, page_index, dpi):
    return dict(
        policy=POLICY,
        document=Path(path).resolve().as_posix(),
        page_number=int(page_index) + 1,
        requested_dpi=float(dpi),
        budgets=dict(
            page_objects=MAX_PAGE_OBJECTS,
            form_depth=MAX_FORM_DEPTH,
            path_segments=MAX_PATH_SEGMENTS,
            support_checks=MAX_SUPPORT_CHECKS,
            geometry_checks=MAX_GEOMETRY_CHECKS,
            proposals=MAX_ARCS,
            local_renders=MAX_LOCAL_RENDERS,
            local_pixels=MAX_LOCAL_PIXELS,
            total_local_pixels=MAX_TOTAL_LOCAL_PIXELS,
            seconds=MAX_EVIDENCE_SECONDS,
            curve_samples=MAX_SAMPLES,
        ),
    )


def fit_cubic_arc(points, stroke_width_px):
    """Full-segment radial check in rendered coordinates, with a sampling bound.

    Allow at most 0.10 raster px or 8% of the stroke width, whichever is smaller.
    This is below the raster localization uncertainty, independent of radius or
    document. A uniform t grid includes both endpoints. The cubic derivative
    convex hull gives a conservative between-sample radial distance bound.
    PDFium's binary32 path coordinates and floating arithmetic remain limits.
    """
    p = np.asarray(points, dtype=np.float64)
    if (
        p.shape != (4, 2)
        or not np.isfinite(p).all()
        or not isfinite(stroke_width_px)
        or stroke_width_px <= 0
    ):
        raise ValueError("INVALID_CUBIC")
    tangent0, tangent1 = p[1] - p[0], p[3] - p[2]
    normals = np.array([tangent0, tangent1])
    if (
        abs(np.linalg.det(normals))
        <= np.linalg.norm(tangent0) * np.linalg.norm(tangent1) * 1e-6
    ):
        raise ValueError("UNRESOLVED_CENTER")
    center = np.linalg.solve(normals, [tangent0 @ p[0], tangent1 @ p[3]])
    radii = np.linalg.norm(p[[0, 3]] - center, axis=1)
    radius = float(radii.mean())
    tolerance = min(0.10, stroke_width_px * 0.08)
    if radius <= stroke_width_px * 4 or abs(radii[0] - radii[1]) > tolerance:
        raise ValueError("ENDPOINT_RADII_OR_SCALE")
    speed_bound = float(3 * np.linalg.norm(np.diff(p, axis=0), axis=1).max())
    count = max(257, ceil(speed_bound / (tolerance / 4)) + 1)
    if count > MAX_SAMPLES:
        raise ValueError("CURVE_SAMPLE_BUDGET")
    t = np.linspace(0, 1, count)[:, None]
    q = (
        (1 - t) ** 3 * p[0]
        + 3 * (1 - t) ** 2 * t * p[1]
        + 3 * (1 - t) * t * t * p[2]
        + t**3 * p[3]
    )
    radial_error = float(np.abs(np.linalg.norm(q - center, axis=1) - radius).max())
    gap_bound = speed_bound / (2 * (count - 1))
    if radial_error + gap_bound > tolerance:
        raise ValueError("NONCIRCULAR_CUBIC")
    angles = np.unwrap(np.arctan2(-(q[:, 1] - center[1]), q[:, 0] - center[0]))
    delta = np.diff(angles)
    sweep = float(degrees(angles[-1] - angles[0]))
    if not 1e-5 < abs(sweep) < 180 or np.any(delta * np.sign(sweep) < -1e-10):
        raise ValueError("UNRESOLVED_SWEEP")
    # The curvature numerator of a cubic is quadratic. Check its extrema, not
    # only sampled points, so a reversal between samples cannot pass.
    a, b, c = (
        -p[0] + 3 * p[1] - 3 * p[2] + p[3],
        3 * p[0] - 6 * p[1] + 3 * p[2],
        3 * (p[1] - p[0]),
    )
    def cross(u, v):
        return float(u[0] * v[1] - u[1] * v[0])

    qa, qb, qc = -6 * cross(a, b), 6 * cross(c, a), 2 * cross(c, b)
    checks = [0.0, 1.0]
    if qa and 0 < -qb / (2 * qa) < 1:
        checks.append(-qb / (2 * qa))
    curvature = [(qa * x * x + qb * x + qc) * -np.sign(sweep) for x in checks]
    if min(curvature) <= 0:
        raise ValueError("CURVATURE_REVERSAL")
    # Bernstein coefficients of cross(B-center, B') give a conservative sign
    # check on the entire segment's polar motion. Together with the radial
    # bound this covers the complete arc locus, including both mapped ends.
    angular = np.zeros(6)
    for i in range(4):
        for j in range(3):
            angular[i + j] += (
                comb(3, i)
                * comb(2, j)
                / comb(5, i + j)
                * cross(p[i] - center, 3 * (p[j + 1] - p[j]))
            )
    angular *= -np.sign(sweep)
    if min(angular) <= 0:
        raise ValueError("ANGULAR_RANGE_UNRESOLVED")
    endpoint_angles = angles[[0, -1]]
    circle_tangents = np.stack(
        (-np.sin(endpoint_angles), -np.cos(endpoint_angles)), axis=1
    ) * np.sign(sweep)
    source_tangents = np.asarray([tangent0, tangent1])
    source_tangents /= np.linalg.norm(source_tangents, axis=1)[:, None]
    tangent_alignment = np.sum(circle_tangents * source_tangents, axis=1)
    if min(tangent_alignment) < 1 - 1e-6:
        raise ValueError("ENDPOINT_TANGENT_CHANGED")
    return dict(
        center=tuple(float(x) for x in center),
        radius=radius,
        start_angle_deg=float(degrees(angles[0])) % 360,
        sweep_angle_deg=sweep,
    ), dict(
        sample_count=count,
        sampled_radial_error_px=radial_error,
        between_sample_bound_px=gap_bound,
        radial_upper_bound_px=radial_error + gap_bound,
        tolerance_px=tolerance,
        endpoint_radii_px=radii.tolist(),
        endpoint_displacement_px=float(np.abs(radii - radius).max()),
        curvature_numerator_min=float(min(curvature)),
        angular_bernstein_min=float(min(angular)),
        endpoint_tangent_alignment=tangent_alignment.tolist(),
    )


def _bitmap_rounding_mapping(page_size, bitmap_size, scale, inverse):
    """Identify integer canvas rounding without changing the actual mapping."""
    nominal = np.asarray(page_size, dtype=float) * scale
    actual = np.asarray(bitmap_size, dtype=float)
    if (
        not np.isfinite(nominal).all()
        or np.any(nominal <= 0)
        or tuple(np.ceil(nominal).astype(int)) != tuple(bitmap_size)
    ):
        return dict(integer_canvas_verified=False)
    factors = actual / nominal
    corrected = np.diag(1 / factors) @ inverse
    values = np.linalg.svd(corrected, compute_uv=False)
    verified = bool(np.allclose(values, scale, rtol=1e-6, atol=0))
    return dict(
        integer_canvas_verified=verified,
        page_size_pt=list(page_size),
        nominal_bitmap_size_px=nominal.tolist(),
        bitmap_size_px=list(bitmap_size),
        canvas_rounding_factors=factors.tolist(),
        corrected_mapping_scales=values.tolist(),
    )


def _readonly(array):
    result = np.ascontiguousarray(array, dtype=np.uint8).copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class NativeArcCandidate:
    source: PdfPathReference
    parameters: dict
    stroke_width_px: float
    source_dpi: float
    box: tuple[int, int, int, int]
    native_gray: np.ndarray
    source_gray: np.ndarray
    pixel_points: tuple[tuple[float, float], ...]
    numeric_evidence: dict
    stroke_cap: str = "butt"
    stroke_width_bounds_px: tuple[float, float] | None = None
    other_gray: np.ndarray | None = None

    def __post_init__(self):
        expected, numeric = fit_cubic_arc(self.pixel_points, self.stroke_width_px)
        for name in ("center", "radius", "start_angle_deg", "sweep_angle_deg"):
            if not np.allclose(
                self.parameters[name], expected[name], rtol=0, atol=1e-7
            ):
                raise ValueError("DERIVED_ARC_PARAMETERS_CHANGED")
        x0, y0, x1, y1 = self.box
        if (
            x0 < 0
            or y0 < 0
            or x1 <= x0
            or y1 <= y0
            or self.native_gray.shape != (y1 - y0, x1 - x0)
            or self.source_gray.shape != self.native_gray.shape
        ):
            raise ValueError("INVALID_LOCAL_RENDER_EVIDENCE")
        object.__setattr__(self, "parameters", MappingProxyType(dict(expected)))
        object.__setattr__(self, "native_gray", _readonly(self.native_gray))
        object.__setattr__(self, "source_gray", _readonly(self.source_gray))
        if self.stroke_cap not in ("butt", "round"):
            raise ValueError("CAP_UNSUPPORTED")
        if self.stroke_cap == "round":
            if (
                self.other_gray is None
                or self.other_gray.shape != self.native_gray.shape
            ):
                raise ValueError("ROUND_CAP_CONTEXT_MISSING")
            object.__setattr__(self, "other_gray", _readonly(self.other_gray))
            bounds = self.stroke_width_bounds_px
            if (
                bounds is None
                or len(bounds) != 2
                or not all(isfinite(x) for x in bounds)
                or not 0 < bounds[0] <= self.stroke_width_px <= bounds[1]
            ):
                raise ValueError("ROUND_CAP_WIDTH_UNRESOLVED")
            object.__setattr__(
                self, "stroke_width_bounds_px", tuple(float(x) for x in bounds)
            )
            object.__setattr__(
                self, "numeric_evidence", dict(self.numeric_evidence, **numeric)
            )
            cap_proof = self.check_round_caps()
            # Derived evidence is recomputed on construction, including crop
            # translations. A caller cannot bypass the cap proof with a flag.
            object.__setattr__(
                self,
                "numeric_evidence",
                dict(self.numeric_evidence, **numeric, round_caps=cap_proof),
            )

    @property
    def object_id(self):
        return f"PDF-ARC:p{self.source.page_number}:o{self.source.object_index}:s{self.source.subpath_index}"

    def accepted_member(self, replaced_members, reason):
        width_mm = self.stroke_width_px * 25.4 / self.source_dpi
        weights = (
            (
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
            if self.stroke_cap == "round"
            else (13, 25, 50, 100)
        )
        return ArcSegment(
            self.object_id,
            **self.parameters,
            source=self.source,
            stroke_width_px=self.stroke_width_px,
            source_dpi=self.source_dpi,
            lineweight=min(weights, key=lambda w: abs(w / 100 - width_mm)),
            replaced_members=tuple(replaced_members),
            acceptance_reason=reason,
            stroke_cap=self.stroke_cap,
            stroke_width_bounds_px=self.stroke_width_bounds_px,
            geometry_error_px=self.numeric_evidence["radial_upper_bound_px"]
            if self.stroke_cap == "round"
            else 0.0,
        )

    def cap_neighborhood(self):
        x0, y0, x1, y1 = self.box
        yy, xx = np.ogrid[y0:y1, x0:x1]
        ends = np.asarray(self.pixel_points)[[0, 3]]
        # Includes mapped cap extent and raster edge localization. It is a
        # rejection neighborhood, never permission to snap or connect objects.
        arc = self.accepted_member((), "round cap neighborhood validation")
        output_radius = arc.lineweight / 100 * self.source_dpi / 25.4 / 2
        reach = (
            max(self.stroke_width_bounds_px[1] / 2, output_radius)
            + arc.geometry_error_px
            + 2**0.5
        )
        caps = np.zeros((y1 - y0, x1 - x0), bool)
        for x, y in ends:
            caps |= (xx - x) ** 2 + (yy - y) ** 2 <= reach**2
        return caps

    def check_round_caps(self):
        caps = self.cap_neighborhood()
        if np.any(caps & (self.other_gray < 255)):
            raise ValueError("ROUND_CAP_SHARED_SOURCE_INK")
        arc = self.accepted_member((), "round stroke presentation validation")
        error = arc.round_stroke_error_px()
        return dict(
            context="original page with only this path disabled",
            other_cap_ink_pixels=0,
            cap_neighborhood_pixels=int(caps.sum()),
            boundary_error_upper_px=error,
            boundary_tolerance_px=0.5,
            mapped_width_bounds_px=list(self.stroke_width_bounds_px),
        )


@dataclass(frozen=True)
class PdfGeometryEvidence:
    binding: dict
    source_size_px: tuple[int, int]
    page_to_pixel: tuple[float, ...]
    candidates: tuple[NativeArcCandidate, ...] = ()
    rejections: tuple[dict, ...] = ()
    analysis: dict = field(default_factory=dict)

    def for_crop(self, box):
        """Known translation only; partial curves retain raster representation."""
        left, top, right, bottom = box
        candidates = []
        for c in self.candidates:
            x0, y0, x1, y1 = c.box
            if not (left <= x0 < x1 <= right and top <= y0 < y1 <= bottom):
                continue
            parameters = dict(
                c.parameters,
                center=(
                    c.parameters["center"][0] - left,
                    c.parameters["center"][1] - top,
                ),
            )
            candidates.append(
                replace(
                    c,
                    parameters=parameters,
                    box=(x0 - left, y0 - top, x1 - left, y1 - top),
                    pixel_points=tuple((x - left, y - top) for x, y in c.pixel_points),
                )
            )
        matrix = (
            *self.page_to_pixel[:4],
            self.page_to_pixel[4] - left,
            self.page_to_pixel[5] - top,
        )
        return replace(
            self,
            source_size_px=(right - left, bottom - top),
            page_to_pixel=matrix,
            candidates=tuple(candidates),
        )


def _screen_curve(index, obj, inverse, origin, raw, mapping=None):
    """Cheap support checks only. These never grant final member eligibility."""
    reasons = []
    fill, stroke = ct.c_int(), ct.c_long()
    if not raw.FPDFPath_GetDrawMode(obj, ct.byref(fill), ct.byref(stroke)):
        raise ValueError("PATH_STYLE_UNREADABLE")
    if fill.value or not stroke.value:
        reasons.append("FILL_OR_NO_STROKE_UNSUPPORTED")
    clip = raw.FPDFPageObj_GetClipPath(obj)
    clip_count = raw.FPDFClipPath_CountPaths(clip) if clip else 0
    if clip_count > 0:
        reasons.append("CLIPPING_UNSUPPORTED")
    dash_count, cap = raw.FPDFPageObj_GetDashCount(obj), raw.FPDFPageObj_GetLineCap(obj)
    if dash_count != 0:
        reasons.append("DASH_UNSUPPORTED")
    if cap not in (0, 1):
        reasons.append("CAP_UNSUPPORTED")
    color = [ct.c_uint() for _ in range(4)]
    readable = raw.FPDFPageObj_GetStrokeColor(obj, *[ct.byref(v) for v in color])
    rgba = [v.value for v in color]
    if not readable or rgba[3] != 255 or max(rgba[:3]) >= 128:
        reasons.append("STROKE_COLOR_UNSUPPORTED")
    width = ct.c_float()
    if not raw.FPDFPageObj_GetStrokeWidth(obj, ct.byref(width)) or width.value <= 0:
        reasons.append("STROKE_WIDTH_UNSUPPORTED")
    matrix = obj.get_matrix()
    parent = obj.container
    while parent is not None:
        parent_clip = raw.FPDFPageObj_GetClipPath(parent)
        if parent_clip and raw.FPDFClipPath_CountPaths(parent_clip) > 0:
            reasons.append("INHERITED_CLIPPING_UNSUPPORTED")
        matrix = matrix.multiply(parent.get_matrix())
        parent = parent.container
    a, b, c, d, e, f = matrix.get()
    native_basis = np.array([[a, c], [b, d]])
    native_scales = np.linalg.svd(native_basis, compute_uv=False)
    pixel_scales = np.linalg.svd(inverse @ native_basis, compute_uv=False)
    native_similarity = (
        min(native_scales) > 0
        and abs(native_scales[0] - native_scales[1]) <= max(native_scales) * 1e-6
    )
    pixel_similarity = (
        min(pixel_scales) > 0
        and abs(pixel_scales[0] - pixel_scales[1]) <= max(pixel_scales) * 1e-6
    )
    if not native_similarity or (
        not pixel_similarity and not (mapping or {}).get("integer_canvas_verified")
    ):
        reasons.append("ANISOTROPIC_PATH_TRANSFORM")
    detail = dict(
        object_index=index,
        cap=cap,
        dash_count=dash_count,
        clip_path_count=clip_count,
        support_reasons=list(dict.fromkeys(reasons)),
        native_transform_scales=native_scales.tolist(),
        page_to_pixel_scales=np.linalg.svd(inverse, compute_uv=False).tolist(),
        rendered_transform_scales=pixel_scales.tolist(),
        native_similarity=bool(native_similarity),
        integer_canvas_verified=bool((mapping or {}).get("integer_canvas_verified")),
        mapping_basis="similarity"
        if pixel_similarity
        else "verified integer canvas; final-coordinate fit required",
    )
    if reasons:
        return None, detail
    points = []
    for j in range(4):
        x, y = ct.c_float(), ct.c_float()
        segment = raw.FPDFPath_GetPathSegment(obj, j)
        if not raw.FPDFPathSegment_GetPoint(segment, ct.byref(x), ct.byref(y)):
            raise ValueError("PATH_POINT_UNREADABLE")
        points.append(
            tuple(inverse @ (np.array(matrix.on_point(x.value, y.value)) - origin))
        )
    return dict(
        object_index=index,
        points=tuple(points),
        stroke_px=float(width.value * pixel_scales.mean()),
        rgba=rgba,
        detail=detail,
        cap=cap,
        stroke_width_bounds_px=tuple(
            float(width.value * x) for x in sorted(pixel_scales)
        ),
    ), detail


def _geometry_work(records):
    # Assign work before processing; queue ordering cannot change the selected set.
    ordered = sorted(records, key=lambda r: r["object_index"])
    return ordered[:MAX_GEOMETRY_CHECKS], ordered[MAX_GEOMETRY_CHECKS:]


def extract_pdf_arc_evidence(
    path, page_index, page, bitmap, source_gray, scale, requested_dpi
):
    """Bound complete visibility context separately from candidate work.

    Never isolate against an incomplete object list. An unexamined path remains
    in the original source render and in the full visibility-state snapshot.
    Deadlines are cooperative between PDFium calls; restoration always finishes.
    """
    import pypdfium2 as pdfium

    raw = pdfium.raw
    started = perf_counter()
    h, w = source_gray.shape
    binding = pdf_geometry_binding(path, page_index, requested_dpi)
    pos = bitmap.get_posconv(page)
    origin = np.array(pos.to_page(0, 0))
    dx = (np.array(pos.to_page(w, 0)) - origin) / w
    dy = (np.array(pos.to_page(0, h)) - origin) / h
    inverse = np.linalg.inv(np.column_stack((dx, dy)))
    mapping = _bitmap_rounding_mapping(page.get_size(), (w, h), scale, inverse)
    offset = -inverse @ origin
    page_matrix = (
        float(inverse[0, 0]),
        float(inverse[1, 0]),
        float(inverse[0, 1]),
        float(inverse[1, 1]),
        float(offset[0]),
        float(offset[1]),
    )
    empty = PdfGeometryEvidence(binding, (w, h), page_matrix)
    counts = dict(
        objects_visited=0,
        object_types={},
        path_count_queries=0,
        screening_objects_visited=0,
        structural_curves=0,
        support_checks=0,
        geometry_checks=0,
        candidate_validation_fits=0,
        proposals=0,
        local_renders=0,
        visibility_checks=0,
        round_cap_checks=0,
        local_pixels=0,
        candidate_array_bytes=0,
        visibility_state_reads=0,
        visibility_state_writes=0,
        wrapper_shallow_bytes=0,
        rejection_categories={},
    )
    seconds = dict(traversal=0.0, screening=0.0, geometry=0.0, visibility=0.0)
    rejections, candidates, objects = [], [], []
    traversal_complete, interrupted = False, False

    def reject(reason, stage, category, index=None, **detail):
        row = dict(
            reason=reason,
            stage=stage,
            category=category,
            decision="NOT_EVALUATED" if category == "resource" else "REJECTED",
            **detail,
        )
        if index is not None:
            row["object_index"] = index
        rejections.append(row)

    def expired(stage):
        nonlocal interrupted
        if perf_counter() - started <= MAX_EVIDENCE_SECONDS:
            return False
        if not interrupted:
            reject("EVIDENCE_TIME_BUDGET", stage, "resource")
        interrupted = True
        return True

    def finish():
        counts["rejection_categories"] = dict(
            Counter(r["category"] for r in rejections)
        )
        limited = bool(counts["rejection_categories"].get("resource"))
        unavailable = bool(counts["rejection_categories"].get("unavailable"))
        analysis = dict(
            traversal_complete=traversal_complete,
            review_complete=traversal_complete and not limited and not unavailable,
            status="LIMITED" if limited or unavailable else "COMPLETE",
            cache_reusable=not interrupted and not unavailable,
            counts=counts,
            seconds={k: round(v, 6) for k, v in seconds.items()},
            elapsed_seconds=round(perf_counter() - started, 6),
            mapping=mapping,
        )
        return replace(
            empty,
            candidates=tuple(sorted(candidates, key=lambda c: c.source.object_index)),
            rejections=tuple(rejections),
            analysis=analysis,
        )

    def set_active(obj, value):
        counts["visibility_state_writes"] += 1
        return raw.FPDFPageObj_SetIsActive(obj, value)

    phase = perf_counter()
    for obj in page.get_objects(max_depth=MAX_FORM_DEPTH):
        counts["objects_visited"] += 1
        kind = obj.type
        name = {
            raw.FPDF_PAGEOBJ_TEXT: "TEXT",
            raw.FPDF_PAGEOBJ_PATH: "PATH",
            raw.FPDF_PAGEOBJ_IMAGE: "IMAGE",
            raw.FPDF_PAGEOBJ_FORM: "FORM",
            raw.FPDF_PAGEOBJ_SHADING: "SHADING",
        }.get(kind, "OTHER")
        counts["object_types"][name] = counts["object_types"].get(name, 0) + 1
        if counts["objects_visited"] > MAX_PAGE_OBJECTS:
            reject("PAGE_TRAVERSAL_OBJECT_BUDGET", "traversal", "resource")
            break
        objects.append(obj)
        counts["wrapper_shallow_bytes"] += getsizeof(obj)
        if kind == raw.FPDF_PAGEOBJ_FORM:
            children = raw.FPDFFormObj_CountObjects(obj)
            if children < 0:
                reject(
                    "FORM_CONTEXT_UNREADABLE",
                    "traversal",
                    "unavailable",
                    len(objects) - 1,
                )
                break
            if obj.level >= MAX_FORM_DEPTH - 1 and children:
                reject("FORM_DEPTH_BUDGET", "traversal", "resource", len(objects) - 1)
                break
        if expired("traversal"):
            break
    else:
        traversal_complete = True
    seconds["traversal"] = perf_counter() - phase
    counts["wrapper_shallow_bytes"] += getsizeof(objects)
    if not traversal_complete:
        # Missing leaves cannot be safely disabled for isolated rendering.
        return finish()

    records = []
    phase = perf_counter()
    for index, obj in enumerate(objects):
        if expired("screening"):
            break
        counts["screening_objects_visited"] += 1
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        counts["path_count_queries"] += 1
        n = raw.FPDFPath_CountSegments(obj)
        if n > MAX_PATH_SEGMENTS:
            reject(
                "PATH_SEGMENT_BUDGET", "screening", "resource", index, segment_count=n
            )
            continue
        if n != 4:
            continue
        segments = [raw.FPDFPath_GetPathSegment(obj, j) for j in range(4)]
        if [raw.FPDFPathSegment_GetType(s) for s in segments] != [2, 1, 1, 1] or any(
            raw.FPDFPathSegment_GetClose(s) for s in segments
        ):
            continue
        counts["structural_curves"] += 1
        if counts["support_checks"] >= MAX_SUPPORT_CHECKS:
            reject("SUPPORT_CHECK_BUDGET", "screening", "resource", index)
            continue
        counts["support_checks"] += 1
        try:
            record, detail = _screen_curve(index, obj, inverse, origin, raw, mapping)
            if record is None:
                reject(detail["support_reasons"][0], "support", "unsupported", **detail)
            else:
                records.append(record)
        except (ValueError, np.linalg.LinAlgError, pdfium.PdfiumError) as exc:
            reject(str(exc), "support", "unavailable", index)
    seconds["screening"] = perf_counter() - phase
    if interrupted:
        return finish()

    work, remaining = _geometry_work(records)
    for record in remaining:
        reject("GEOMETRY_CHECK_BUDGET", "geometry", "resource", record["object_index"])
    proposals = []
    phase = perf_counter()
    for i, record in enumerate(work):
        index = record["object_index"]
        if expired("geometry"):
            for pending in work[i:]:
                reject(
                    "GEOMETRY_NOT_EVALUATED_AFTER_TIMEOUT",
                    "geometry",
                    "resource",
                    pending["object_index"],
                )
            break
        if len(proposals) >= MAX_ARCS:
            for pending in work[i:]:
                reject(
                    "ARC_PROPOSAL_BUDGET",
                    "geometry",
                    "resource",
                    pending["object_index"],
                )
            break
        counts["geometry_checks"] += 1
        try:
            parameters, numeric = fit_cubic_arc(record["points"], record["stroke_px"])
            numeric["source_rgba"] = record["rgba"]
            numeric["transform"] = record["detail"]
            proposals.append(
                (
                    index,
                    parameters,
                    numeric,
                    record["stroke_px"],
                    record["points"],
                    record,
                )
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            reason = str(exc)
            reject(
                reason,
                "geometry",
                "resource" if reason == "CURVE_SAMPLE_BUDGET" else "geometry",
                index,
            )
    counts["proposals"] = len(proposals)
    seconds["geometry"] = perf_counter() - phase
    if interrupted:
        for index, *_ in proposals:
            reject("VISIBILITY_NOT_EVALUATED", "visibility", "resource", index)
        return finish()
    if not proposals:
        return finish()

    phase = perf_counter()
    states, changed = [], []
    reviewed = set()
    try:
        # Read all states before mutating any; original drawing order is intact.
        for obj in objects:
            if expired("visibility-context"):
                raise TimeoutError
            active = ct.c_long()
            counts["visibility_state_reads"] += 1
            if not raw.FPDFPageObj_GetIsActive(obj, ct.byref(active)):
                raise ValueError("VISIBILITY_STATE_UNREADABLE")
            states.append(active.value)
        state_by_object = {id(obj): state for obj, state in zip(objects, states)}
        for obj, state in zip(objects, states):
            if expired("visibility-context"):
                raise TimeoutError
            changed.append((obj, state))
            target = state if obj.type == raw.FPDF_PAGEOBJ_FORM else 0
            if not set_active(obj, target):
                raise ValueError("VISIBILITY_ISOLATION_UNAVAILABLE")
        for index, parameters, numeric, stroke_px, points, record in proposals:
            if expired("visibility"):
                break
            render_count = 2 if record["cap"] == 1 else 1
            if counts["local_renders"] + render_count > MAX_LOCAL_RENDERS:
                reject("LOCAL_RENDER_BUDGET", "visibility", "resource", index)
                reviewed.add(index)
                continue
            obj = objects[index]
            ancestors, parent = [obj], obj.container
            while parent is not None:
                ancestors.append(parent)
                parent = parent.container
            if any(not state_by_object[id(a)] for a in ancestors):
                reject("INACTIVE_PATH", "visibility", "unsupported", index)
                reviewed.add(index)
                continue
            margin = ceil(max(6, stroke_px * 3))
            ps = np.asarray(points)
            x0, y0 = np.floor(ps.min(axis=0)).astype(int) - margin
            x1, y1 = np.ceil(ps.max(axis=0)).astype(int) + margin + 1
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                reject("CURVE_AT_PAGE_EDGE", "visibility", "unsupported", index)
                reviewed.add(index)
                continue
            pixels = int((x1 - x0) * (y1 - y0))
            if (
                pixels > MAX_LOCAL_PIXELS
                or counts["local_pixels"] + render_count * pixels
                > MAX_TOTAL_LOCAL_PIXELS
            ):
                reject(
                    "LOCAL_PIXEL_BUDGET",
                    "visibility",
                    "resource",
                    index,
                    local_pixels=pixels,
                )
                reviewed.add(index)
                continue
            crop_px = (x0, h - y1, w - x1, y0)
            crop = tuple(max(0, x - 1e-5) / scale for x in crop_px)
            if not set_active(obj, 1):
                raise ValueError("VISIBILITY_ISOLATION_UNAVAILABLE")
            counts["local_renders"] += 1
            counts["local_pixels"] += pixels
            isolated = None
            try:
                isolated = page.render(scale=scale, grayscale=True, crop=crop)
                native = np.array(isolated.to_pil().convert("L"))
            finally:
                if isolated is not None:
                    isolated.close()
                if not set_active(obj, 0):
                    raise ValueError("VISIBILITY_ISOLATION_UNAVAILABLE")
            if expired("visibility"):
                break
            source = source_gray[y0:y1, x0:x1]
            if native.shape != source.shape:
                reject(
                    "LOCAL_RENDER_MAPPING_UNRESOLVED",
                    "visibility",
                    "unavailable",
                    index,
                )
                reviewed.add(index)
                continue
            counts["visibility_checks"] += 1
            visible = native < 255
            if not np.any(visible) or np.any(
                visible & (source.astype(int) > native.astype(int) + 2)
            ):
                reject(
                    "VISIBLE_STROKE_OCCLUDED_OR_CHANGED",
                    "visibility",
                    "visibility",
                    index,
                    numeric=numeric,
                    parameters=parameters,
                )
                reviewed.add(index)
                continue
            other = None
            if record["cap"] == 1:
                # Render the whole original context with this path alone off.
                # Other black strokes hidden under the black cap remain visible
                # here, unlike an original-vs-isolated darkness comparison.
                for item, state in zip(objects, states):
                    if expired("round-cap-context"):
                        raise TimeoutError
                    if not set_active(item, 0 if item is obj else state):
                        raise ValueError("VISIBILITY_ISOLATION_UNAVAILABLE")
                counts["local_renders"] += 1
                counts["local_pixels"] += pixels
                context_bitmap = None
                try:
                    context_bitmap = page.render(scale=scale, grayscale=True, crop=crop)
                    other = np.array(context_bitmap.to_pil().convert("L"))
                finally:
                    if context_bitmap is not None:
                        context_bitmap.close()
                for item, state in zip(objects, states):
                    if expired("round-cap-context"):
                        raise TimeoutError
                    if not set_active(
                        item, state if item.type == raw.FPDF_PAGEOBJ_FORM else 0
                    ):
                        raise ValueError("VISIBILITY_ISOLATION_UNAVAILABLE")
                if other.shape != native.shape:
                    reject(
                        "LOCAL_RENDER_MAPPING_UNRESOLVED",
                        "round-cap",
                        "unavailable",
                        index,
                    )
                    reviewed.add(index)
                    continue
                counts["round_cap_checks"] += 1
            counts["candidate_validation_fits"] += 1
            try:
                candidate = NativeArcCandidate(
                    PdfPathReference(binding["document"], page_index + 1, index),
                    parameters,
                    stroke_px,
                    scale * 72,
                    (int(x0), int(y0), int(x1), int(y1)),
                    native,
                    source,
                    points,
                    numeric,
                    stroke_cap="round" if record["cap"] == 1 else "butt",
                    stroke_width_bounds_px=record["stroke_width_bounds_px"]
                    if record["cap"] == 1
                    else None,
                    other_gray=other,
                )
            except ValueError as exc:
                reject(
                    str(exc),
                    "round-cap",
                    "visibility",
                    index,
                    numeric=numeric,
                    parameters=parameters,
                    stroke_width_bounds_px=record["stroke_width_bounds_px"],
                )
                reviewed.add(index)
                continue
            candidates.append(candidate)
            reviewed.add(index)
            counts["candidate_array_bytes"] += (
                candidate.native_gray.nbytes
                + candidate.source_gray.nbytes
                + (0 if other is None else other.nbytes)
            )
    except TimeoutError:
        pass
    except (ValueError, pdfium.PdfiumError) as exc:
        # A broken isolation/visibility context cannot authorize any replacement.
        candidates.clear()
        reject(str(exc), "visibility-context", "unavailable")
    finally:
        restored = all([bool(set_active(obj, state)) for obj, state in changed])
        if not restored:
            candidates.clear()
            reject(
                "VISIBILITY_STATE_RESTORE_FAILED", "visibility-context", "unavailable"
            )
        seconds["visibility"] = perf_counter() - phase
    for index, *_ in proposals:
        if index not in reviewed:
            reject(
                "VISIBILITY_NOT_EVALUATED",
                "visibility",
                "resource" if interrupted else "unavailable",
                index,
            )
    expired("closeout")
    return finish()
