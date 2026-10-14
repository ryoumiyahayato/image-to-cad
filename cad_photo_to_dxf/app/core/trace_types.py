from dataclasses import dataclass

@dataclass(frozen=True)
class TracePath:
    """One closed boundary in source-image pixel coordinates.

    The paths represent the printed regions themselves rather than an inferred
    wall/axis/structure model. ``parent`` and ``depth`` preserve the contour
    nesting needed for counters in text and holes in symbols.
    """

    points: tuple[tuple[float, float], ...]
    parent: int | None
    depth: int
    root: int

