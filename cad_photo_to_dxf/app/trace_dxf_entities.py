from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import atan2, degrees, hypot
from unicodedata import east_asian_width

from .auxiliary_recognition import TextCandidate
from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .line_detect import LineSegment
from .raster_trace import TracePath


PointTransform = Callable[[float, float], tuple[float, float]]
MAX_EDITABLE_POLYLINE_VERTICES = 64


@dataclass(frozen=True)
class TracePalette:
    """Colors used to distinguish geometry without changing its shape."""

    straight: int = 5
    curve: int = 6
    text_symbol: int = 6


TRACE_LAYER_STYLES = {
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
        1 for index, direction in enumerate(directions) if direction != directions[index - 1]
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
        relative_height <= 0.018
        and relative_width <= 0.06
        and turns >= 4
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
        size_compatible = width <= (right - left) * 1.35 and height <= (bottom - top) * 1.45
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
) -> list[object]:
    entities: list[object] = []
    for chunk, close in _editable_polyline_chunks(points):
        entities.append(
            layout.add_lwpolyline(
                chunk,
                close=close,
                dxfattribs={"layer": layer_name, "color": color},
            )
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
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Write reconstructed structural strokes as native DXF LINE entities."""

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    resolved_color = _resolved_color(color, 5)
    for line in lines:
        if line.length <= 1e-6:
            continue
        start = transform(float(line.x1), float(line.y1))
        end = transform(float(line.x2), float(line.y2))
        if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            continue
        entities.append(
            layout.add_line(
                start,
                end,
                dxfattribs={"layer": layer_name, "color": resolved_color},
            )
        )
        bounds.extend((start, end))
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
    source_outline_ocr_texts: Sequence[TextCandidate] = (),
    fallback_ocr_texts: Sequence[TextCandidate] = (),
    residual_ocr_texts: Sequence[TextCandidate] = (),
    layer_names: Mapping[str, str] | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
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
    exported_path_count = 0
    exported_vertex_count = 0

    for position, index in enumerate(black_indices):
        if position % 64 == 0:
            checkpoint(cancellation_token)
            report_progress(progress_callback, "cad-entities", position / total_black)
        trace_path = trace_paths[index]
        hole_indices = [
            child_index
            for child_index in children.get(index, [])
            if trace_paths[child_index].depth == trace_path.depth + 1
        ]
        if _path_matches_ocr(
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
        entities.extend(
            _add_editable_contour(
                layout,
                root_points,
                layer_name=resolved_layer_name,
                color=entity_color,
            )
        )
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


def _candidate_quad(text: TextCandidate) -> tuple[tuple[float, float], ...]:
    if text.quad and len(text.quad) == 4:
        return text.quad
    x, y, width, height = text.bbox
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )


def _text_width_units(content: str) -> float:
    units = 0.0
    for character in content:
        if character.isspace():
            units += 0.35
        elif east_asian_width(character) in {"W", "F", "A"}:
            units += 1.0
        else:
            units += 0.58
    return max(units, 1.0)


def add_ocr_text_entities(
    layout,
    texts: Sequence[TextCandidate],
    *,
    transform: PointTransform,
    layer_name: str = "OCR_TEXT",
    style_name: str = "OCR_CJK",
    minimum_confidence: float = 0.58,
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Add one complete, directly editable DXF TEXT per OCR line."""

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    for candidate in texts:
        content = " ".join(
            candidate.text.replace("\r", " ").replace("\n", " ").split()
        )
        if not content or candidate.confidence < minimum_confidence:
            continue
        quad = _candidate_quad(candidate)
        transformed = [transform(float(x), float(y)) for x, y in quad]
        top_left, top_right, bottom_right, bottom_left = transformed
        target_height = (
            hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
            + hypot(top_right[0] - bottom_right[0], top_right[1] - bottom_right[1])
        ) * 0.5
        target_width = (
            hypot(top_right[0] - top_left[0], top_right[1] - top_left[1])
            + hypot(bottom_right[0] - bottom_left[0], bottom_right[1] - bottom_left[1])
        ) * 0.5
        char_height = max(0.01, target_height * 0.82)
        natural_width = char_height * _text_width_units(content)
        width_factor = min(4.0, max(0.20, target_width / max(natural_width, 0.01)))
        rotation = degrees(
            atan2(bottom_right[1] - bottom_left[1], bottom_right[0] - bottom_left[0])
        )
        entity = layout.add_text(
            content,
            height=char_height,
            dxfattribs={
                "layer": layer_name,
                "color": 6,
                "style": style_name,
                "rotation": float(rotation),
                "width": float(width_factor),
            },
        )
        entity.set_placement(bottom_left)
        entities.append(entity)
        bounds.extend(transformed)
    return len(entities), entities, bounds
