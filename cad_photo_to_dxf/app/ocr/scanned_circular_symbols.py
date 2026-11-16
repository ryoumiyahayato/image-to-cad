"""Fit editable members of a source-connected circular symbol in a raster scan."""
from __future__ import annotations

from dataclasses import replace
from math import ceil, pi, sqrt

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPainterPathStroker, QTransform

from app.core.trace_types import TracePath
from app.export.engineering_symbol_entities import symbol_glyph_pens, symbol_lineweight
from app.export.ocr_outline_export import native_text_placement
from app.geometry.source_filled_marks import _RAY_COUNT, _RAY_STEP, _fit_boundary
from app.geometry.text_residual_retirement import pixel_runs
from app.ocr.auxiliary_recognition import TextCandidate
from app.ocr.librecad_lff import librecad_font_available, librecad_text_path


_ANGLES = np.arange(_RAY_COUNT) * (2 * pi / _RAY_COUNT)
_RAYS = np.column_stack((np.cos(_ANGLES), np.sin(_ANGLES)))


def _sample(mask, points):
    x, y = np.asarray(points, dtype=np.float32).T
    return cv2.remap(mask, x[:, None], y[:, None], cv2.INTER_LINEAR).ravel()


def _circle(mask, seed, seed_radius):
    fitted = _fit_boundary(np.uint8(mask) * 255, *seed, seed_radius, _RAYS)
    if fitted is None:
        return None
    center, inner, metrics = fitted
    center = np.asarray(center)
    steps = np.arange(max(0, inner - 2), inner * 1.6 + 3, _RAY_STEP)
    samples = (center + _RAYS[:, None] * steps[None, :, None]).reshape(-1, 2)
    ink = _sample(mask.astype(np.float32), samples).reshape(len(_RAYS), -1) >= .5
    enters = np.argmax(ink, axis=1)
    exits = ~ink & (np.arange(len(steps))[None, :] > enters[:, None])
    sampled = ink.any(axis=1) & exits.any(axis=1)
    measured_outer = steps[np.argmax(exits, axis=1)] - _RAY_STEP / 2
    if sampled.sum() < .75 * len(_RAYS):
        return None
    median = np.median(measured_outer[sampled])
    # Long rays along an attached stroke don't measure ring thickness.
    clean = sampled & (abs(measured_outer - median) <= max(1.2, .08 * inner))
    if clean.sum() < .70 * len(_RAYS) or min(clean.reshape(4, -1).sum(axis=1)) < len(_RAYS) / 8:
        return None
    width = float(np.median(measured_outer[clean]) - inner)
    radius = inner + width / 2
    if not 1 <= width < inner / 2 or _sample(mask.astype(np.float32), center + radius * _RAYS).min() < .5:
        return None
    metrics["outer_p95_radial_error_px"] = float(np.percentile(abs(measured_outer[clean] - inner - width), 95))
    return center, float(radius), width, metrics


def _near_branch(component, center, radius, distance, outer):
    # Find the outward axis at the attachment. The far end may turn, widen
    # or join other strokes, so it cannot determine the fitting window.
    near = component & (distance <= outer + 2.5)
    if not near.any():
        return None
    yy, xx = np.nonzero(near)
    outward = np.array((xx.mean(), yy.mean())) - center
    length = np.linalg.norm(outward)
    if length == 0:
        return None
    axis = int(np.argmax(abs(outward)))
    direction = 1 if outward[axis] > 0 else -1
    stations = np.arange(component.shape[1 - axis])
    attachment = (xx, yy)[axis]
    first = attachment.min() if direction > 0 else attachment.max()
    span = radius * abs(outward[axis]) / length
    # One measured ring radius of exterior stroke, in the local direction.
    # Quantize the span before testing stations for translation invariance.
    offset = (stations - first) * direction
    within = (offset >= 0) & (offset <= round(span))
    prefix = component & (within[None, :] if axis == 0 else within[:, None])
    return prefix, axis, direction, bool(np.any(component & ~prefix))


def _line_fit(component, ring, center, radius, axis, outward, dpi, clipped):
    points = np.argwhere(component)[:, ::-1]
    if len(points) < 5:
        return None
    stations = np.unique(points[:, axis])
    if len(stations) < 5 or np.any(np.diff(stations) != 1):
        return None
    centers, widths = [], []
    for value in stations:
        cross = np.sort(points[points[:, axis] == value, 1 - axis])
        if np.any(np.diff(cross) != 1):
            return None
        xy = np.empty(2)
        xy[axis], xy[1 - axis] = value, (cross[0] + cross[-1]) / 2
        centers.append(xy)
        widths.append(cross[-1] - cross[0] + 1)
    centers = np.asarray(centers)
    # Cutting at the outside of the ring leaves a partial first section.
    # Measure the axis from full sections and validate the entire extension.
    full = np.asarray(widths) >= .65 * np.median(widths)
    if full.sum() < 5 or np.any(~full[np.flatnonzero(full)[0]:np.flatnonzero(full)[-1] + 1]):
        return None
    centers = centers[full]
    dx, dy, x, y = map(float, cv2.fitLine(centers.astype(np.float32), cv2.DIST_L2, 0, .01, .01).ravel())
    direction = np.array((dx, dy))
    direction /= np.linalg.norm(direction)
    if direction[axis] * outward < 0:
        direction *= -1
    mid = np.array((x, y))
    error = abs((centers - mid) @ (-direction[1], direction[0]))
    width = float(np.median(np.asarray(widths)[full]) * abs(direction[axis]))
    if np.percentile(error, 95) > .85 or error.max() > 1.35 or width < 1:
        return None
    offset = mid - center
    projection = offset @ direction
    discriminant = projection ** 2 - offset @ offset + radius ** 2
    if discriminant <= 0:
        return None
    start = mid + (-projection + sqrt(discriminant)) * direction
    last = stations[-1] if direction[axis] > 0 else stations[0]
    edge = clipped and last == (ring.shape[::-1][axis] - 1 if outward > 0 else 0)
    if edge:
        end = mid + (last - mid[axis]) / direction[axis] * direction
    else:
        pen = symbol_lineweight(width, dpi) * dpi / 2540
        terminal = np.max((points - mid) @ direction) + .5 - pen / 2
        # The round cap itself must end before the first unobserved station.
        # Projecting only the farthest ink point can leak into a diagonal gap.
        cap_center = last + np.sign(direction[axis]) * (.5 - pen / 2)
        terminal = min(terminal, (cap_center - mid[axis]) / direction[axis])
        end = mid + terminal * direction
    extent = (end - start) @ direction
    if extent < max(4, 1.5 * width):
        return None
    centers = start + np.linspace(0, extent, ceil(extent / _RAY_STEP) + 1)[:, None] * direction
    support = float(_sample(ring.astype(np.float32), centers).min())
    if support < .5:
        return None
    # Only extend to the pixel edge when the observed last station is a
    # clipped image edge. No continuation through an interior white station.
    if edge:
        end += .5 / abs(direction[axis]) * direction
    if np.any(end < -.50001) or np.any(end > np.asarray(ring.shape[::-1]) - .49999):
        return None
    return start, end, width, {
        "center_p95_error_px": float(np.percentile(error, 95)),
        "center_max_error_px": float(error.max()),
        "minimum_center_ink": support,
        "crop_edge_endpoint": bool(edge),
    }


def _recognize(mark):
    from app.ocr.ocr_recognition import _get_rapidocr_engine

    # Scaling here is only an OCR input. All measurements use native pixels.
    scale = max(1, ceil(20 / mark.shape[0]))
    crops = []
    for factor in (scale, scale + 1):
        enlarged = cv2.resize(mark, None, fx=factor, fy=factor, interpolation=cv2.INTER_NEAREST)
        padded = cv2.copyMakeBorder(enlarged, 4 * factor, 4 * factor, 4 * factor, 4 * factor,
                                    cv2.BORDER_CONSTANT, value=255)
        crops.append(cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR))
    try:
        result = _get_rapidocr_engine().recognize_txt(crops)
        a, b = (str(text).strip() for text in result.txts)
        confidence = min(float(score) for score in result.scores)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if a != b or len(a) != 1 or not a.isascii() or not a.isalnum() or not .90 <= confidence <= 1:
        return None
    return a, confidence


def _width(glyph):
    distance = cv2.distanceTransform(np.uint8(glyph), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    ridges = (distance > 0) & (distance == cv2.dilate(distance, np.ones((3, 3), np.uint8)))
    return float(max(1, 2 * np.median(distance[ridges]) - 1))


def _glyph(mark, box, center, radius, ring_width, dpi):
    recognized = _recognize(np.where(mark, 0, 255).astype(np.uint8))
    if recognized is None:
        return None
    text, confidence = recognized
    width = _width(np.pad(mark, 1))
    ring_pen = symbol_lineweight(ring_width, dpi) * dpi / 2540
    for pen in symbol_glyph_pens(width, dpi):
        fit = _fit_glyph(mark, box, center, radius - ring_pen / 2, text, confidence, pen)
        if fit is not None:
            candidate, clearance, coverage, precision = fit
            return candidate, pen, width, clearance, coverage, precision
    return None


def _fit_glyph(mark, box, center, inner_radius, text, confidence, pen):
    x, y, w, h = box
    half = pen / 2
    if min(w, h) <= pen + 1:
        return None
    quad = ((x+half, y+half), (x+w-half, y+half), (x+w-half, y+h-half), (x+half, y+h-half))
    candidate = TextCandidate(text, box, confidence, "text_candidate",
                              source="rapidocr-observed-circular-symbol", display_quad=quad)
    fit = native_text_placement(candidate, transform=lambda a, b: (a, -b))
    if fit is None or fit.metrics.fallback_reason:
        return None
    geometry = fit.geometry
    transform = QTransform()
    transform.translate(geometry.insert[0], -geometry.insert[1])
    transform.rotate(-geometry.rotation)
    scale = geometry.character_height / fit.metrics.em_height
    transform.scale(scale * geometry.width_factor, scale)
    stroker = QPainterPathStroker()
    stroker.setWidth(pen)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    path = stroker.createStroke(transform.map(librecad_text_path(text)))
    far = max((np.linalg.norm(np.array((p.x(), p.y())) - center - .5)
               for poly in path.toSubpathPolygons() for p in poly), default=np.inf)
    clearance = float(inner_radius - far)
    if clearance <= 0:
        return None
    raster = QImage(w + 4, h + 4, QImage.Format.Format_Grayscale8)
    raster.fill(255)
    painter = QPainter(raster)
    painter.translate(2 - x, 2 - y)
    painter.fillPath(path, Qt.GlobalColor.black)
    painter.end()
    pixels = np.frombuffer(raster.constBits(), dtype=np.uint8, count=raster.sizeInBytes())
    emitted = pixels.reshape(h + 4, raster.bytesPerLine())[:, :w + 4] < 128
    coverage, precision = _coverage(np.pad(mark, 2), emitted)
    if min(coverage, precision) < .90:
        return None
    return candidate, clearance, coverage, precision


def _coverage(source, model):
    """Mutual source/model coverage within the native one-pixel fringe."""
    if not source.any() or not model.any():
        return 0., 0.
    covered = np.count_nonzero(source & _source_fringe(model)) / source.sum()
    supported = np.count_nonzero(model & _source_fringe(source)) / model.sum()
    return float(covered), float(supported)


def _source_fringe(model):
    return cv2.dilate(np.uint8(model), np.ones((3, 3), np.uint8)) > 0


def _related_glyph(text, candidates):
    gx, gy, gw, gh = text.bbox
    related = set()
    for i, candidate in enumerate(candidates):
        bx, by, bw, bh = candidate.bbox
        if bx+bw <= gx or bx >= gx+gw or by+bh <= gy or by >= gy+gh:
            continue
        if (candidate.text.strip() == text.text
                and gx-2 <= bx < bx+bw <= gx+gw+2 and gy-2 <= by < by+bh <= gy+gh+2):
            related.add(i)
        else:
            return None
    return related


def _circular_holes(ink, dpi, min_side):
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return
    for contour, relation in zip(contours, hierarchy[0]):
        parent = relation[3]
        # RETR_TREE alternates source ink and holes. A drawing frame or room
        # enclosure adds two ancestors without changing a symbol hole's role.
        # Do not require the enclosing ink component to be a top-level root.
        depth, ancestor = 0, int(parent)
        while ancestor >= 0:
            depth += 1
            ancestor = int(hierarchy[0][ancestor][3])
        if parent < 0 or depth % 2 != 1 or len(contour) < 12:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if not min_side <= min(w, h) <= 14 * dpi / 25.4 or not .85 <= w / h <= 1.18:
            continue
        if cv2.contourArea(contour) < .62 * w * h:
            continue
        yield contour, contours[parent], (x, y, w, h)


def recover_circular_symbols(binary, candidates, *, protected, text_owned, dpi,
                             search_bounds=None, skip_boxes=(),
                             crop_edges=(True, True, True, True), glyph_verifier=None, search_regions=None):
    """Find circular symbols and replace each supported member locally."""
    claimed = np.zeros(binary.shape, dtype=bool)
    can_fit_glyph = librecad_font_available()
    ink = np.uint8(binary < 128)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    paths, records, texts, replaced = [], [], [], set()
    for contour, parent, box in _circular_holes(ink, dpi, 10):
        if box in skip_boxes:
            continue
        x, y, w, h = box
        seed, axes, _ = cv2.fitEllipse(contour)
        if search_regions is not None and not any(
                a <= seed[0] < a+c and b <= seed[1] < b+d
                for a, b, c, d in search_regions):
            continue
        if search_bounds is not None:
            x0, y0, x1, y1 = search_bounds
            if not (x0 <= seed[0] < x1 and y0 <= seed[1] < y1):
                continue
        # Bound the fit to a local observation even if the source component
        # joins the rest of the drawing. Ink outside it is never retired.
        pad = 2 * max(w, h)
        l, t = max(0, x - pad), max(0, y - pad)
        r, b = min(binary.shape[1], x + w + pad), min(binary.shape[0], y + h + pad)
        window = np.s_[t:b, l:r]
        local = labels[window]
        rx, ry = parent[0, 0]
        ring = local == labels[ry, rx]
        fitted = _circle(ring, np.asarray(seed) - (l, t), min(axes) / 2)
        if fitted is None:
            continue
        center, radius, width, metrics = fitted
        yy, xx = np.indices(ring.shape)
        distance = np.hypot(xx - center[0], yy - center[1])
        ids = np.unique(local[(distance < radius - width / 2 - 1) & ~ring])
        ids = ids[ids > 0]
        if len(ids) != 1:
            continue
        gx, gy, gw, gh, count = map(int, stats[ids[0]])
        glyph = local == ids[0]
        if (count < 8 or count != glyph.sum() or np.any(glyph & (distance >= radius - width / 2))
                or not (l <= gx < gx+gw <= r and t <= gy < gy+gh <= b)):
            continue
        outer = radius + width / 2
        blocked = protected[window] | claimed[window]
        geometry_blocked = blocked | text_owned[window]
        foreign_ink = (local > 0) & ~ring
        ring_pen = symbol_lineweight(width, dpi) * dpi / 2540
        ring_model = abs(distance - radius) <= ring_pen / 2
        ring_source = ring & (distance <= outer + 1)
        coverage, precision = _coverage(ring_source, ring_model)
        owned_ring = ring_source & _source_fringe(ring_model)
        ring_replaced = (
            min(coverage, precision) >= .95
            and not np.any(ring_model & foreign_ink)
            and not np.any((owned_ring | ring_model) & geometry_blocked)
        )
        if not ring_replaced:
            owned_ring[:] = False

        _, exterior, exterior_stats, _ = cv2.connectedComponentsWithStats(
            np.uint8(ring & ~ring_source), connectivity=8,
        )
        owned = owned_ring.copy()
        branches = []
        clipped_sides = {
            (0, -1): crop_edges[0] and l == 0,
            (0, 1): crop_edges[2] and r == binary.shape[1],
            (1, -1): crop_edges[1] and t == 0,
            (1, 1): crop_edges[3] and b == binary.shape[0],
        }
        for i in range(1, len(exterior_stats)):
            if exterior_stats[i, cv2.CC_STAT_AREA] < max(4, width):
                continue
            component = exterior == i
            near = _near_branch(component, center, radius, distance, outer)
            if near is None:
                continue
            prefix, axis, outward, continued = near
            branch = _line_fit(prefix, ring, center, radius, axis, outward, dpi,
                               clipped_sides[axis, outward])
            if branch is None:
                continue
            start, end, pen, detail = branch
            vx, vy = end - start
            fraction = np.clip(((xx - start[0]) * vx + (yy - start[1]) * vy) / (vx*vx + vy*vy), 0, 1)
            rendered_width = symbol_lineweight(pen, dpi) * dpi / 2540
            stroke = np.hypot(xx - start[0] - fraction*vx, yy - start[1] - fraction*vy) <= rendered_width/2
            exterior_stroke = stroke & ~ring_model
            coverage_branch, precision_branch = _coverage(prefix, exterior_stroke)
            owned_branch = prefix & _source_fringe(stroke)
            if (min(coverage_branch, precision_branch) < .95
                    or np.any(stroke & (foreign_ink | ((exterior > 0) & ~component)))
                    or np.any((stroke | owned_branch) & geometry_blocked)
                    or np.any(owned_branch & owned)):
                continue
            owned |= owned_branch
            branches.append(dict(
                start_px=tuple(start + (l, t)), end_px=tuple(end + (l, t)), width_px=pen, **detail,
                source_coverage=coverage_branch, model_coverage=precision_branch,
                retained_continuation=continued, retired_runs_y_x0_x1=pixel_runs(owned_branch, l, t),
            ))

        glyph_record = {}
        original_glyph_review = None
        if can_fit_glyph and not np.any(glyph & blocked):
            box = (gx, gy, gw, gh)
            observed = _glyph(glyph[gy-t:gy-t+gh, gx-l:gx-l+gw], box, center+(l,t), radius, width, dpi)
            if observed is not None:
                text, text_width, observed_width, clearance, glyph_coverage, glyph_precision = observed
                related = _related_glyph(text, candidates)
                if glyph_verifier is not None:
                    original_glyph_review = glyph_verifier(text)
                source_agreement = (original_glyph_review is None
                                    or original_glyph_review.get("accepted") is True)
                if (source_agreement and related is not None and not related & replaced
                        and (related or not np.any(glyph & text_owned[window]))):
                    owned |= glyph
                    texts.append(text)
                    replaced.update(related)
                    glyph_record = dict(
                        glyph_box=box, glyph_text=text.text, glyph_width_px=text_width,
                        glyph_gap_px=clearance, glyph_observed_width_px=observed_width,
                        glyph_source_coverage=glyph_coverage, glyph_model_coverage=glyph_precision,
                        glyph_retired_runs_y_x0_x1=pixel_runs(glyph, l, t),
                    )
        if not owned.any():
            continue
        center = center + (l, t)
        if ring_replaced:
            points = tuple(map(tuple, center + radius * _RAYS))
            paths.append(TracePath(points, None, 0, len(paths)))
        claimed[window] |= owned
        records.append(dict(
            kind="circle", bbox=(x, y, w, h), native_scan=True, dpi=dpi,
            center_px=tuple(center), radius_px=radius, width_px=width,
            ring_replaced=ring_replaced, branches=branches,
            source_coverage=coverage, model_coverage=precision,
            ring_retired_runs_y_x0_x1=pixel_runs(owned_ring, l, t),
            retired_runs_y_x0_x1=pixel_runs(owned, l, t),
            preserved_ring_pixels=int(np.count_nonzero(ring & ~owned)),
            electrical_connectivity="UNRESOLVED", **metrics, **glyph_record,
            **({"registered_glyph_confirmation": original_glyph_review}
               if original_glyph_review is not None else {}),
        ))
    return tuple(texts), tuple(paths), tuple(records), claimed, replaced



def confirm_input_glyph_on_registered_original(candidate, scan, source_crop=None):
    """A low-resolution fallback cannot bypass conflicting original evidence.

    The input-grid glyph remains visible on rejection. A returned reading is
    evidence only: it never substitutes a different character without fitting
    that character to its own source geometry.
    """
    x,y,w,h = candidate.bbox
    ox,oy = source_crop[:2] if source_crop is not None else (0,0)
    q=scan.ratio
    l,t,rr,b=(x+ox)*q,(y+oy)*q,(x+ox+w)*q,(y+oy+h)*q
    record=dict(proposed=candidate.text,original_bbox=(l,t,rr,b),accepted=False,
                authority="CORROBORATION_ONLY")
    if not 0 <= l < rr <= scan.pixels.shape[1] or not 0 <= t < b <= scan.pixels.shape[0]:
        return dict(record,reason="ORIGINAL_GLYPH_OUT_OF_BOUNDS")
    mark=np.where(scan.pixels[t:b,l:rr] < 128,0,255).astype(np.uint8)
    reading=_recognize(mark)
    if reading is None:
        return dict(record,reason="ORIGINAL_GLYPH_UNRESOLVED")
    value,confidence=reading
    return dict(record,original_reading=value,original_confidence=confidence,
                accepted=value==candidate.text,
                reason="REGISTERED_ORIGINAL_AGREES" if value==candidate.text
                       else "REGISTERED_ORIGINAL_DISAGREES")

def recover_registered_circular_symbols(source_gray, binary, candidates, *, protected,
                                        text_owned, dpi, scan, source_crop, search_regions=None):
    """Nominate on the input grid and fit only those windows on the original grid."""
    ratio = scan.ratio
    crop_x, crop_y = source_crop[:2] if source_crop is not None else (0, 0)
    height, width = binary.shape
    claimed = np.zeros(binary.shape, dtype=bool)
    paths, records, texts, replaced = [], [], [], set()
    for _, _, box in _circular_holes(np.uint8(binary < 128), dpi, max(5, ceil(10 / ratio))):
        x, y, w, h = box
        if search_regions is not None and not any(
                a <= x+w/2 < a+c and b <= y+h/2 < b+d
                for a, b, c, d in search_regions):
            continue
        # A hole-width margin covers the ring wall and the near branch fit.
        pad = max(w, h)
        l, t = max(0, x - pad), max(0, y - pad)
        r, b = min(width, x + w + pad), min(height, y + h + pad)
        window = np.s_[t:b, l:r]
        nx0, ny0, nx1, ny1 = ((crop_x + l) * ratio, (crop_y + t) * ratio,
                              (crop_x + r) * ratio, (crop_y + b) * ratio)
        native = scan.pixels[ny0:ny1, nx0:nx1]
        if native.shape != ((b - t) * ratio, (r - l) * ratio):
            continue

        def expand(mask):
            return mask.repeat(ratio, axis=0).repeat(ratio, axis=1)

        visible = source_gray[window] < 255
        native = np.where(expand(visible), native, 255)
        candidate_indices = []
        native_candidates = []
        for i, c in enumerate(candidates):
            cx, cy, cw, ch = c.bbox
            if cx < r and cy < b and cx + cw > l and cy + ch > t:
                candidate_indices.append(i)
                native_candidates.append(
                    replace(c, bbox=((cx-l)*ratio, (cy-t)*ratio, cw*ratio, ch*ratio))
                )
        local_texts, local_paths, local_records, _, local_replaced = recover_circular_symbols(
            native, native_candidates, dpi=scan.dpi,
            protected=expand(protected[window] | claimed[window]),
            text_owned=expand(text_owned[window]),
            search_bounds=((x-l)*ratio, (y-t)*ratio, (x+w-l)*ratio, (y+h-t)*ratio),
            crop_edges=(l == 0, t == 0, r == width, b == height),
        )
        related = {candidate_indices[i] for i in local_replaced}
        if len(local_records) != 1 or related & replaced:
            continue
        record, owned = _map_registered_symbol(local_records[0], native < 128, ratio, (l, t), dpi)
        if not owned.any():
            continue
        record.update(
            input_candidate_bbox=box, sampling_source="registered_original_scan",
            original_dpi=scan.dpi, original_pixels_per_input_axis=ratio,
            original_window_px=(nx0, ny0, nx1, ny1),
        )
        if record["ring_replaced"]:
            path, = local_paths
            paths.append(replace(path, points=tuple(_input_center(p, ratio, (l, t)) for p in path.points)))
        if "glyph_box" in record:
            text, = local_texts
            quad = tuple((px / ratio + l, py / ratio + t) for px, py in text.display_quad)
            texts.append(replace(text, bbox=record["glyph_box"], display_quad=quad))
            replaced.update(related)
        claimed[window] |= owned
        records.append(record)
    return tuple(texts), tuple(paths), tuple(records), claimed, replaced


def _input_center(point, ratio, origin):
    x, y = point
    l, t = origin
    return (x + .5) / ratio + l - .5, (y + .5) / ratio + t - .5


def _map_registered_symbol(record, native_ink, ratio, origin, dpi):
    l, t = origin
    h, w = native_ink.shape
    footprint = (h // ratio, ratio, w // ratio, ratio)
    owned = np.zeros((h // ratio, w // ratio), dtype=bool)
    original_member_pixels = 0

    def on_input(mask):
        return mask.reshape(footprint).any(axis=(1, 3))

    def bbox(box):
        x, y, w, h = box
        left, top = x // ratio, y // ratio
        return left + l, top + t, ceil((x+w)/ratio) - left, ceil((y+h)/ratio) - top

    def member_runs(runs):
        nonlocal original_member_pixels
        if not runs:
            return []
        member = np.zeros(native_ink.shape, dtype=bool)
        for y, x0, x1 in runs:
            member[y, x0:x1] = True
        # Keep mixed cells at the handoff. Any other native ink in the same
        # input pixel must remain visible when this member is replaced.
        cells = on_input(member) & ~on_input(native_ink & ~member)
        if cells.any():
            owned[:] |= cells
            original_member_pixels += int(member.sum())
        return pixel_runs(cells, l, t)

    ring_runs = member_runs(record["ring_retired_runs_y_x0_x1"])
    mapped = dict(
        record, dpi=dpi, bbox=bbox(record["bbox"]),
        center_px=_input_center(record["center_px"], ratio, origin),
        radius_px=record["radius_px"] / ratio, width_px=record["width_px"] / ratio,
        ring_retired_runs_y_x0_x1=ring_runs, ring_replaced=bool(ring_runs), branches=[],
    )
    if "glyph_box" in record:
        runs = member_runs(record["glyph_retired_runs_y_x0_x1"])
        if runs:
            mapped.update(glyph_box=bbox(record["glyph_box"]), glyph_retired_runs_y_x0_x1=runs)
            for field in ("glyph_width_px", "glyph_observed_width_px", "glyph_gap_px"):
                mapped[field] /= ratio
        else:
            mapped = {key: value for key, value in mapped.items() if not key.startswith("glyph_")}
    for branch in record["branches"]:
        runs = member_runs(branch["retired_runs_y_x0_x1"])
        if runs:
            mapped["branches"].append(dict(
                branch, start_px=_input_center(branch["start_px"], ratio, origin),
                end_px=_input_center(branch["end_px"], ratio, origin),
                width_px=branch["width_px"] / ratio, retired_runs_y_x0_x1=runs,
            ))
    mapped.update(retired_runs_y_x0_x1=pixel_runs(owned, l, t),
                  original_member_pixels=original_member_pixels)
    return mapped, owned
