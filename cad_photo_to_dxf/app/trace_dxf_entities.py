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


def _resolved_color(value: int, fallback: int) -> int:
    color = int(value)
    return color if 1 <= color <= 255 else fallback


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
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    box_width = max(xs) - min(xs) + 1.0
    box_height = max(ys) - min(ys) + 1.0
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
    """Add one editable solid HATCH per connected black region.

    Earlier builds wrote every contour twice (outline plus hatch) and then wrote
    the same geometry again in paper space. This function writes the minimum
    exact representation: one hatch exterior plus its immediate white holes.
    The contour coordinates themselves are unchanged.
    """

    if not trace_paths:
        return 0, 0, [], []

    checkpoint(cancellation_token)
    selected_palette = palette or TracePalette()
    # A non-default legacy single-color request remains supported.
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
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
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

        hatch = layout.add_hatch(
            color=entity_color,
            dxfattribs={"layer": layer_name, "color": entity_color},
        )
        hatch.set_solid_fill(color=entity_color)
        hatch.paths.add_polyline_path(root_points, is_closed=True, flags=1)

        for child_index in hole_indices:
            child_points = [
                transform(float(x), float(y))
                for x, y in trace_paths[child_index].points
            ]
            if len(child_points) >= 3:
                hatch.paths.add_polyline_path(child_points, is_closed=True, flags=0)

        entities.append(hatch)
        for x, y in root_points:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    report_progress(progress_callback, "cad-entities", 1.0)
    bounds = [] if not entities else [(min_x, min_y), (max_x, max_y)]
    return (
        len(trace_paths),
        sum(len(path.points) for path in trace_paths),
        entities,
        bounds,
    )
