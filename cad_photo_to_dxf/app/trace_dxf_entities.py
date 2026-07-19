from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from .raster_trace import TracePath


PointTransform = Callable[[float, float], tuple[float, float]]


def add_exact_trace_entities(
    layout,
    trace_paths: Sequence[TracePath],
    *,
    transform: PointTransform,
    color: int = 7,
) -> tuple[int, int, list[object], list[tuple[float, float]]]:
    """Add exact outlines and solid black-region hatches.

    OpenCV's tree alternates black and white regions by depth. Every even-depth
    path is therefore one black region. It becomes its own HATCH exterior, and
    only its immediate odd-depth children become holes. Black grandchildren are
    exported as independent hatches instead of being folded into one enormous
    page-wide hatch. This is both topologically correct and easier for CAD tools
    to select, audit and render.
    """

    if not trace_paths:
        return 0, 0, [], []
    resolved_color = int(color)
    if not 1 <= resolved_color <= 255:
        resolved_color = 7

    transformed: list[list[tuple[float, float]]] = []
    entities: list[object] = []
    coordinates: list[tuple[float, float]] = []
    children: dict[int, list[int]] = defaultdict(list)

    for index, trace_path in enumerate(trace_paths):
        if trace_path.parent is not None:
            children[int(trace_path.parent)].append(index)
        points = [transform(float(x), float(y)) for x, y in trace_path.points]
        transformed.append(points)
        if len(points) < 3:
            continue
        outline = layout.add_lwpolyline(
            points,
            close=True,
            dxfattribs={"layer": "TRACE_OUTLINE", "color": resolved_color},
        )
        entities.append(outline)
        coordinates.extend(points)

    for index, trace_path in enumerate(trace_paths):
        if trace_path.depth % 2 != 0 or len(transformed[index]) < 3:
            continue
        hatch = layout.add_hatch(
            color=resolved_color,
            dxfattribs={"layer": "TRACE_FILL", "color": resolved_color},
        )
        hatch.set_solid_fill(color=resolved_color)
        hatch.paths.add_polyline_path(
            transformed[index],
            is_closed=True,
            flags=1,
        )
        for child_index in children.get(index, []):
            child = trace_paths[child_index]
            if child.depth != trace_path.depth + 1:
                continue
            child_points = transformed[child_index]
            if len(child_points) >= 3:
                hatch.paths.add_polyline_path(
                    child_points,
                    is_closed=True,
                    flags=0,
                )
        entities.append(hatch)

    return (
        len(trace_paths),
        sum(len(path.points) for path in trace_paths),
        entities,
        coordinates,
    )
