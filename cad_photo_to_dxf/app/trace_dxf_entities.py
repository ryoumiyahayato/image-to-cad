from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import hypot

from .cancellation import CancellationToken, ProgressCallback, checkpoint, report_progress
from .raster_trace import TracePath


PointTransform = Callable[[float, float], tuple[float, float]]


@dataclass(frozen=True)
class TracePalette:
    """Colors used to distinguish geometry without changing its shape."""

    straight: int = 5
    curve: int = 3
    text_symbol: int = 6


TRACE_LAYER_STYLES = {
    "TRACE_STRAIGHT": {"color": 5, "lineweight": 0},
    "TRACE_CURVE": {"color": 3, "lineweight": 0},
    "TRACE_TEXT_SYMBOL": {"color": 6, "lineweight": 0},
}

# Large multi-loop HATCH entities are not rendered consistently by LibreCAD and
# several DWG importers.  They can be triangulated as page-spanning wedges even
# though the contour tree itself is valid.  Exact outlines are always written;
# solid fills are limited to small text/symbol regions where they are useful and
# interoperable.
_SAFE_FILL_MAX_VERTICES = 2048
_SAFE_FILL_MAX_TOTAL_VERTICES = 8192
_SAFE_FILL_MAX_HOLES = 32
_SAFE_FILL_MAX_BOX_AREA_RATIO = 0.02


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
    """Classify one connected black region for visual checking only.

    Classification never changes or simplifies the contour. It only chooses a
    layer/color. Small, turn-heavy regions are treated as text/symbols; long
    low-turn regions as straight linework; the remainder as curves.
    """

    points = path.points
    if len(points) < 3:
        return "TRACE_STRAIGHT"
    min_x, min_y, max_x, max_y = _path_box(path)
    box_width = max_x - min_x + 1.0
    box_height = max_y - min_y + 1.0
    short_side = max(1.0, min(box_width, box_height))
    long_side = max(box_width, box_height)
    aspect = long_side / short_side

    directions: list[tuple[int, int]] = []
    axis_steps = 0
    total_steps = 0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        dx = float(x2) - float(x1)
        dy = float(y2) - float(y1)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            continue
        total_steps += 1
        if abs(dx) < 1e-9 or abs(dy) < 1e-9:
            axis_steps += 1
        norm = hypot(dx, dy)
        directions.append((int(round(dx / norm)), int(round(dy / norm))))

    turns = 0
    for index, direction in enumerate(directions):
        if direction != directions[index - 1]:
            turns += 1
    axis_fraction = axis_steps / max(total_steps, 1)
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

    if aspect >= 4.0 and turns <= 16:
        return "TRACE_STRAIGHT"
    if axis_fraction >= 0.90 and turn_density <= 0.06:
        return "TRACE_STRAIGHT"
    return "TRACE_CURVE"


def _safe_fill_allowed(
    path: TracePath,
    hole_paths: Sequence[TracePath],
    *,
    layer_name: str,
    source_size: tuple[int, int] | None,
) -> bool:
    """Return whether a solid HATCH is safe for broad CAD interoperability."""

    if layer_name != "TRACE_TEXT_SYMBOL":
        return False
    if len(path.points) > _SAFE_FILL_MAX_VERTICES:
        return False
    if len(hole_paths) > _SAFE_FILL_MAX_HOLES:
        return False
    total_vertices = len(path.points) + sum(len(item.points) for item in hole_paths)
    if total_vertices > _SAFE_FILL_MAX_TOTAL_VERTICES:
        return False
    if source_size is not None:
        source_width, source_height = source_size
        min_x, min_y, max_x, max_y = _path_box(path)
        box_area = max(1.0, max_x - min_x + 1.0) * max(1.0, max_y - min_y + 1.0)
        source_area = max(1.0, float(source_width) * float(source_height))
        if box_area / source_area > _SAFE_FILL_MAX_BOX_AREA_RATIO:
            return False
    return True


def _expand_bounds(
    points: Sequence[tuple[float, float]],
    bounds: list[float],
) -> None:
    for x, y in points:
        bounds[0] = min(bounds[0], x)
        bounds[1] = min(bounds[1], y)
        bounds[2] = max(bounds[2], x)
        bounds[3] = max(bounds[3], y)


def add_exact_trace_entities(
    layout,
    trace_paths: Sequence[TracePath],
    *,
    transform: PointTransform,
    color: int = 7,
    source_size: tuple[int, int] | None = None,
    palette: TracePalette | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[int, int, list[object], list[tuple[float, float]]]:
    """Add exact editable contour boundaries once in model space.

    Every retained contour is written as one closed LWPOLYLINE.  Only small,
    bounded text/symbol regions receive a correctly flagged solid HATCH so that
    glyph strokes do not appear hollow.  Page-spanning and complex linework is
    deliberately never hatched because common CAD viewers can render such
    multi-loop fills as giant diagonal wedges and become unusably slow.
    """

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

    for position, index in enumerate(black_indices):
        if position % 64 == 0:
            checkpoint(cancellation_token)
            report_progress(
                progress_callback,
                "cad-entities",
                position / total_black,
            )
        trace_path = trace_paths[index]
        root_points = [transform(float(x), float(y)) for x, y in trace_path.points]
        if len(root_points) < 3:
            continue

        hole_indices = [
            child_index
            for child_index in children.get(index, [])
            if trace_paths[child_index].depth == trace_path.depth + 1
        ]
        hole_paths = [trace_paths[child_index] for child_index in hole_indices]
        layer_name = _classify_region(
            trace_path,
            source_size=source_size,
            hole_count=len(hole_indices),
        )
        if layer_name == "TRACE_STRAIGHT":
            entity_color = _resolved_color(selected_palette.straight, 5)
        elif layer_name == "TRACE_TEXT_SYMBOL":
            entity_color = _resolved_color(selected_palette.text_symbol, 6)
        else:
            entity_color = _resolved_color(selected_palette.curve, 3)

        root_outline = layout.add_lwpolyline(
            root_points,
            close=True,
            dxfattribs={"layer": layer_name, "color": entity_color},
        )
        entities.append(root_outline)
        _expand_bounds(root_points, bounds)

        transformed_holes: list[list[tuple[float, float]]] = []
        for child_index in hole_indices:
            child_points = [
                transform(float(x), float(y))
                for x, y in trace_paths[child_index].points
            ]
            if len(child_points) < 3:
                continue
            child_outline = layout.add_lwpolyline(
                child_points,
                close=True,
                dxfattribs={"layer": layer_name, "color": entity_color},
            )
            entities.append(child_outline)
            transformed_holes.append(child_points)
            _expand_bounds(child_points, bounds)

        if _safe_fill_allowed(
            trace_path,
            hole_paths,
            layer_name=layer_name,
            source_size=source_size,
        ):
            hatch = layout.add_hatch(
                color=entity_color,
                dxfattribs={"layer": layer_name, "color": entity_color},
            )
            hatch.set_solid_fill(color=entity_color)
            hatch.dxf.hatch_style = 0
            # The POLYLINE flag (2) is mandatory.  External loop = 1 | 2;
            # internal holes = 2.  The old 1/0 flags caused LibreCAD to
            # triangulate complex loops as giant page-spanning wedges.
            hatch.paths.add_polyline_path(root_points, is_closed=True, flags=3)
            for child_points in transformed_holes:
                hatch.paths.add_polyline_path(child_points, is_closed=True, flags=2)
            entities.append(hatch)

    report_progress(progress_callback, "cad-entities", 1.0)
    resolved_bounds = (
        []
        if not entities
        else [(bounds[0], bounds[1]), (bounds[2], bounds[3])]
    )
    return (
        len(trace_paths),
        sum(len(path.points) for path in trace_paths),
        entities,
        resolved_bounds,
    )
