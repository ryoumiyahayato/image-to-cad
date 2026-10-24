from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import hypot

from app.ocr.auxiliary_recognition import TextCandidate
from app.core.cancellation import (
    CancellationToken,
    ProgressCallback,
    checkpoint,
    report_progress,
)
from app.geometry.line_detect import LineSegment
from app.core.trace_types import TracePath
from app.core.arc_types import ArcSegment, transformed_arc

PointTransform = Callable[[float, float], tuple[float, float]]
MAX_EDITABLE_POLYLINE_VERTICES = 64


@dataclass(frozen=True)
class TracePalette:
    """Colors used to distinguish geometry without changing its shape."""

    straight: int = 5
    curve: int = 6
    text_symbol: int = 6


TRACE_LAYER_STYLES = {
    "NATIVE_PDF_FILL": {"color": 7, "lineweight": 0},
    "LOGO_GRAPHIC": {"color": 7, "lineweight": 0},
    "ENGINEERING_SYMBOL": {"color": 7, "lineweight": 13},
    "TRACE_STRAIGHT": {"color": 5, "lineweight": 0},
    "TRACE_CURVE": {"color": 6, "lineweight": 0},
    "TRACE_TEXT_SYMBOL": {"color": 6, "lineweight": 0},
    "SOURCE_TEXT_OUTLINE": {"color": 2, "lineweight": 0},
    "TEXT_FALLBACK_OUTLINE": {"color": 2, "lineweight": 0},
    "RESIDUAL_GRAPHIC": {"color": 3, "lineweight": 0},
    "OCR_TEXT": {"color": 6, "lineweight": 0},
    "SIGNATURE_OVERLAY": {"color": 6, "lineweight": 0},
}


def _resolved_color(value: int, fallback: int) -> int:
    color = int(value)
    return color if 1 <= color <= 255 else fallback


def _path_box(path: TracePath) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in path.points]
    ys = [float(point[1]) for point in path.points]
    return min(xs), min(ys), max(xs), max(ys)


def _classify_region(
    path: TracePath,
    *,
    source_size: tuple[int, int] | None,
    hole_count: int,
) -> str:
    """Choose a review layer only; never alter or merge contour coordinates."""

    points = path.points
    if len(points) < 3:
        return "TRACE_CURVE"
    min_x, min_y, max_x, max_y = _path_box(path)
    box_width = max_x - min_x + 1.0
    box_height = max_y - min_y + 1.0
    directions: list[tuple[int, int]] = []
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        dx = float(x2) - float(x1)
        dy = float(y2) - float(y1)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            continue
        norm = hypot(dx, dy)
        directions.append((int(round(dx / norm)), int(round(dy / norm))))

    turns = sum(
        1
        for index, direction in enumerate(directions)
        if direction != directions[index - 1]
    )
    turn_density = turns / max(len(directions), 1)

    if source_size is not None:
        source_width, source_height = source_size
        relative_width = box_width / max(float(source_width), 1.0)
        relative_height = box_height / max(float(source_height), 1.0)
    else:
        relative_width = relative_height = 1.0

    small_text_region = (
        relative_height <= 0.045
        and relative_width <= 0.30
        and (turns >= 8 or hole_count > 0 or turn_density >= 0.025)
    )
    tiny_symbol_region = (
        relative_height <= 0.018 and relative_width <= 0.06 and turns >= 4
    )
    if small_text_region or tiny_symbol_region:
        return "TRACE_TEXT_SYMBOL"
    # Structural rules have already been reconstructed and removed before this
    # residual contour stage.  Never promote a remaining elongated glyph,
    # punctuation stroke or logo segment into the blue straight-line layer.
    return "TRACE_CURVE"


def _path_matches_ocr(
    path: TracePath,
    texts: Sequence[TextCandidate],
    *,
    allow_candidate_coverage: bool = False,
) -> bool:
    if not texts or len(path.points) < 3:
        return False
    min_x, min_y, max_x, max_y = _path_box(path)
    width = max_x - min_x + 1.0
    height = max_y - min_y + 1.0
    path_area = width * height
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    for text in texts:
        x, y, box_width, box_height = text.bbox
        margin_x = max(3.0, box_width * 0.10)
        margin_y = max(3.0, box_height * 0.18)
        left = float(x) - margin_x
        top = float(y) - margin_y
        right = float(x + box_width) + margin_x
        bottom = float(y + box_height) + margin_y
        center_inside = left <= center_x <= right and top <= center_y <= bottom
        size_compatible = (
            width <= (right - left) * 1.35 and height <= (bottom - top) * 1.45
        )
        if center_inside and size_compatible:
            return True

        intersection_width = max(0.0, min(max_x, right) - max(min_x, left))
        intersection_height = max(0.0, min(max_y, bottom) - max(min_y, top))
        intersection_area = intersection_width * intersection_height
        path_overlap = intersection_area / max(path_area, 1.0)
        if path_overlap >= 0.55 and size_compatible:
            return True

        # Unreliable OCR can cover only a short segment of a longer residual
        # contour (for example, a vertical stroke misread as "S").  In that
        # state the OCR box must not promote the contour to editable text, but
        # it still provides enough evidence to place the owning contour on the
        # explicit residual layer.  Measure coverage of the candidate box only
        # for that residual classification; fallback and editable-text
        # suppression retain the stricter whole-path compatibility rule.
        candidate_area = max((right - left) * (bottom - top), 1.0)
        candidate_overlap = intersection_area / candidate_area
        if allow_candidate_coverage and candidate_overlap >= 0.55:
            return True
    return False


def _expand_bounds(
    points: Sequence[tuple[float, float]],
    bounds: list[float],
) -> None:
    for x, y in points:
        bounds[0] = min(bounds[0], x)
        bounds[1] = min(bounds[1], y)
        bounds[2] = max(bounds[2], x)
        bounds[3] = max(bounds[3], y)


def _editable_polyline_chunks(
    points: Sequence[tuple[float, float]],
    *,
    max_vertices: int = MAX_EDITABLE_POLYLINE_VERTICES,
) -> list[tuple[list[tuple[float, float]], bool]]:
    """Split a very long closed contour into small directly editable polylines."""

    resolved = list(points)
    if len(resolved) < 3:
        return []
    limit = max(3, int(max_vertices))
    if len(resolved) <= limit:
        return [(resolved, True)]

    cycle = [*resolved, resolved[0]]
    chunks: list[tuple[list[tuple[float, float]], bool]] = []
    start = 0
    final_index = len(cycle) - 1
    while start < final_index:
        end = min(start + limit - 1, final_index)
        chunk = cycle[start : end + 1]
        if len(chunk) >= 2:
            chunks.append((chunk, False))
        start = end
    return chunks


def _add_editable_contour(
    layout,
    points: Sequence[tuple[float, float]],
    *,
    layer_name: str,
    color: int,
    source_curve=None,
) -> list[object]:
    entities: list[object] = []
    chunks = (
        [(list(points), True)] if source_curve else _editable_polyline_chunks(points)
    )
    for chunk, close in chunks:
        entities.append(
            layout.add_lwpolyline(
                chunk,
                close=close,
                dxfattribs={"layer": layer_name, "color": color},
            )
        )
        if source_curve:
            proof, depth = source_curve
            if "SCANNED_CURVE_SOURCE" not in layout.doc.appids:
                layout.doc.appids.add("SCANNED_CURVE_SOURCE")
            entities[-1].set_xdata(
                "SCANNED_CURVE_SOURCE",
                [
                    (1070, 1),
                    (1000, proof["policy"]),
                    (1000, proof["source_id"]),
                    (1000, "ORIGINAL_SOURCE_BOUNDARY"),
                    (1070, int(depth)),
                    *[(1071, int(v)) for v in proof["source_box"]],
                    (1071, int(proof["source_pixels"])),
                    (1071, int(proof["released_line_pixels"])),
                    (1000, "CLOSED_SOURCE_WITHOUT_EXTERNAL_CONTACTS"),
                ],
            )
    return entities


def _layer_name(
    base_name: str,
    layer_names: Mapping[str, str] | None,
) -> str:
    return str(layer_names.get(base_name, base_name)) if layer_names else base_name


def add_straight_line_entities(
    layout,
    lines: Sequence[LineSegment],
    *,
    transform: PointTransform,
    layer_name: str = "TRACE_STRAIGHT",
    color: int = 5,
    line_records=(),
    line_source_refs=None,
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Write reconstructed structural strokes as native DXF LINE entities."""

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    resolved_color = _resolved_color(color, 5)
    if line_source_refs is not None and len(line_source_refs) != len(lines):
        raise ValueError("LINE source refs must bind every source line index")
    for index, line in enumerate(lines):
        if line.length <= 1e-6:
            continue
        start = transform(float(line.x1), float(line.y1))
        end = transform(float(line.x2), float(line.y2))
        if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            continue
        record = line_records[index] if line_records else None
        attributes = {"layer": layer_name, "color": resolved_color}
        if record:
            from app.geometry.source_presentation import LINEWEIGHTS

            weight = int(record["cad_lineweight"])
            if weight not in LINEWEIGHTS.values():
                raise ValueError("Stroke lineweight is outside the bounded vocabulary")
            attributes["lineweight"] = weight
            if "source_rgb" in record:
                rgb = record["source_rgb"]
                if len(rgb) != 3 or any(
                    type(v) is not int or not 0 <= v <= 255 for v in rgb
                ):
                    raise ValueError("Native source stroke RGB is invalid")
                attributes["true_color"] = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
        entities.append(
            layout.add_line(
                start,
                end,
                dxfattribs=attributes,
            )
        )
        if record:
            if "P3A_STROKE" not in layout.doc.appids:
                layout.doc.appids.add("P3A_STROKE")
            entities[-1].set_xdata(
                "P3A_STROKE",
                [
                    (1000, str(record["category"])),
                    (1040, float(record["source_width_px"])),
                    (1040, float(record["source_dpi"])),
                ],
            )
        if line_source_refs is not None:
            from app.export.line_source_ref import attach_line_source_ref

            attach_line_source_ref(entities[-1], line_source_refs[index])
        bounds.extend((start, end))
    return len(entities), entities, bounds


def add_arc_entities(
    layout,
    arcs: Sequence[ArcSegment],
    *,
    transform: PointTransform,
    layer_names=None,
    color=6,
):
    # Validate all transforms before emitting a member. No polyline fallback:
    # suppressed source members must never outlive a silently omitted ARC.
    geometry = [transformed_arc(arc, transform) for arc in arcs]
    paper_scales = []
    for arc, (_, radius, *_rest) in zip(arcs, geometry):
        mm_per_pixel = (
            radius / arc.radius if layout.doc.units == 4 else 25.4 / arc.source_dpi
        )
        arc.round_stroke_error_px(mm_per_pixel)
        paper_scales.append(mm_per_pixel)
    entities, bounds = [], []
    for arc, (center, radius, start, end, extrema), mm_per_pixel in zip(
        arcs, geometry, paper_scales
    ):
        layer = _layer_name(arc.layer, layer_names)
        if layer not in layout.doc.layers:
            layout.doc.layers.add(layer, color=_resolved_color(color, 6))
        entity = layout.add_arc(
            center,
            radius,
            start,
            end,
            dxfattribs={
                "layer": layer,
                "color": _resolved_color(color, 6),
                "lineweight": arc.lineweight,
            },
        )
        if "P9_ARC" not in layout.doc.appids:
            layout.doc.appids.add("P9_ARC")
        tags = [
            (1000, arc.object_id),
            (1040, arc.stroke_width_px),
            (1040, arc.source_dpi),
        ]
        if arc.stroke_cap == "round":
            # DXF ARC keeps a centerline and ISO lineweight. Normal CAD object
            # lineweight ends are round; retain the checked presentation for
            # our saved-DXF preview without changing other entities' end styles.
            tags.extend([(1000, "round"), (1040, mm_per_pixel)])
            layout.doc.header["$LWDISPLAY"] = True
        entity.set_xdata("P9_ARC", tags)
        entities.append(entity)
        bounds.extend(extrema)
    return len(entities), entities, bounds


def add_exact_trace_entities(
    layout,
    trace_paths: Sequence[TracePath],
    *,
    transform: PointTransform,
    color: int = 7,
    source_size: tuple[int, int] | None = None,
    palette: TracePalette | None = None,
    ocr_texts: Sequence[TextCandidate] = (),
    text_rule_contours: Sequence = (),
    source_outline_ocr_texts: Sequence[TextCandidate] = (),
    fallback_ocr_texts: Sequence[TextCandidate] = (),
    residual_ocr_texts: Sequence[TextCandidate] = (),
    forced_layer_name: str | None = None,
    layer_names: Mapping[str, str] | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
    bound_members: Mapping[int, object] | None = None,
    excluded_indices: Sequence[int] = (),
    fill_records=None,
    closed_curve_records=(),
    contour_source_refs=None,
    contour_source_expectations=None,
) -> tuple[int, int, list[object], list[tuple[float, float]]]:
    """Write residual editable geometry without OCR glyph or hollow child outlines."""

    if not trace_paths:
        return 0, 0, [], []

    checkpoint(cancellation_token)
    selected_palette = palette or TracePalette()
    if int(color) != 7:
        selected_palette = TracePalette(int(color), int(color), int(color))

    children: dict[int, list[int]] = defaultdict(list)
    black_indices: list[int] = []
    for index, trace_path in enumerate(trace_paths):
        if trace_path.parent is not None:
            children[int(trace_path.parent)].append(index)
        if trace_path.depth % 2 == 0:
            black_indices.append(index)

    entities: list[object] = []
    bounds = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    total_black = max(len(black_indices), 1)
    retained_rules = {
        tuple(tuple(point) for point in points) for points in text_rule_contours
    }
    complete_curves = {
        int(member["index"]): (record["proof"], member["depth"])
        for record in closed_curve_records
        for member in record["members"]
    }
    exported_path_count = 0
    exported_vertex_count = 0

    for position, index in enumerate(black_indices):
        if index in excluded_indices:
            continue
        if position % 64 == 0:
            checkpoint(cancellation_token)
            report_progress(progress_callback, "cad-entities", position / total_black)
        trace_path = trace_paths[index]
        bound_member = None if bound_members is None else bound_members.get(index)
        if bound_members is not None and (
            bound_member is None
            or getattr(bound_member, "emit_mode", None) == "ALIAS_NO_EMIT"
        ):
            continue
        hole_indices = [
            child_index
            for child_index in children.get(index, [])
            if trace_paths[child_index].depth == trace_path.depth + 1
            and (
                bound_members is None
                or (
                    bound_members.get(child_index) is not None
                    and getattr(bound_members[child_index], "emit_mode", None)
                    != "ALIAS_NO_EMIT"
                )
            )
        ]
        if forced_layer_name is not None:
            base_layer_name = str(forced_layer_name)
        elif bound_member is not None:
            # The committed resolver decision takes precedence over OCR region
            # matching and heuristic region classification.
            base_layer_name = str(bound_member.layer)
        elif tuple(trace_path.points) in retained_rules:
            # Final source ownership proved this complete contour is a rule,
            # not a glyph. A nearby OCR rectangle cannot revoke that proof.
            base_layer_name = _classify_region(
                trace_path, source_size=source_size, hole_count=len(hole_indices)
            )
        elif _path_matches_ocr(
            trace_path,
            residual_ocr_texts,
            allow_candidate_coverage=True,
        ):
            base_layer_name = "RESIDUAL_GRAPHIC"
        elif _path_matches_ocr(
            trace_path,
            fallback_ocr_texts,
            allow_candidate_coverage=True,
        ):
            base_layer_name = "TEXT_FALLBACK_OUTLINE"
        elif _path_matches_ocr(trace_path, source_outline_ocr_texts):
            base_layer_name = "SOURCE_TEXT_OUTLINE"
        elif _path_matches_ocr(trace_path, ocr_texts):
            continue
        else:
            base_layer_name = _classify_region(
                trace_path,
                source_size=source_size,
                hole_count=len(hole_indices),
            )
        if base_layer_name == "TRACE_STRAIGHT":
            entity_color = _resolved_color(selected_palette.straight, 5)
        elif base_layer_name in {
            "SOURCE_TEXT_OUTLINE",
            "TEXT_FALLBACK_OUTLINE",
        }:
            entity_color = 2
        elif base_layer_name == "RESIDUAL_GRAPHIC":
            entity_color = 3
        elif base_layer_name == "TRACE_TEXT_SYMBOL":
            entity_color = _resolved_color(selected_palette.text_symbol, 6)
        else:
            entity_color = _resolved_color(selected_palette.curve, 3)
        resolved_layer_name = _layer_name(base_layer_name, layer_names)

        root_points = [transform(float(x), float(y)) for x, y in trace_path.points]
        if len(root_points) < 3:
            continue
        fill = (fill_records or {}).get(str(index))
        if fill and base_layer_name not in {
            "SOURCE_TEXT_OUTLINE",
            "TEXT_FALLBACK_OUTLINE",
            "RESIDUAL_GRAPHIC",
        }:
            hatch = layout.add_hatch(dxfattribs={"layer": resolved_layer_name})
            gray = int(fill["source_gray"])
            hatch.dxf.true_color = (gray << 16) | (gray << 8) | gray
            hatch.paths.add_polyline_path(root_points, is_closed=True)
            entities.append(hatch)
            _expand_bounds(root_points, bounds)
            exported_path_count += 1
            exported_vertex_count += len(trace_path.points)
            continue
        created = _add_editable_contour(
            layout,
            root_points,
            layer_name=resolved_layer_name,
            color=entity_color,
            source_curve=complete_curves.get(index),
        )
        if contour_source_refs and index in contour_source_refs:
            if len(created) != 1:
                raise ValueError(
                    "Source-bound contour must emit one complete native LWP"
                )
            from app.export.contour_source_ref import attach_contour_source_ref

            record = attach_contour_source_ref(
                created[0], contour_source_refs[index], transform
            )
            contour_source_expectations.append((created[0], record))
        entities.extend(created)
        _expand_bounds(root_points, bounds)
        exported_path_count += 1
        exported_vertex_count += len(trace_path.points)

        for child_index in hole_indices:
            child_points = [
                transform(float(x), float(y))
                for x, y in trace_paths[child_index].points
            ]
            if len(child_points) < 3:
                continue
            entities.extend(
                _add_editable_contour(
                    layout,
                    child_points,
                    layer_name=resolved_layer_name,
                    color=entity_color,
                    source_curve=complete_curves.get(child_index),
                )
            )
            _expand_bounds(child_points, bounds)
            exported_path_count += 1
            exported_vertex_count += len(trace_paths[child_index].points)

    report_progress(progress_callback, "cad-entities", 1.0)
    resolved_bounds = (
        [] if not entities else [(bounds[0], bounds[1]), (bounds[2], bounds[3])]
    )
    return (
        exported_path_count,
        exported_vertex_count,
        entities,
        resolved_bounds,
    )
