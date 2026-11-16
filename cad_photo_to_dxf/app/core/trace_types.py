from dataclasses import dataclass

@dataclass(frozen=True)
class TracePath:
    """A closed boundary or a one- or two-endpoint raster run in source pixels.

    The paths represent the printed regions themselves rather than an inferred
    wall/axis/structure model. ``parent`` and ``depth`` preserve the contour
    nesting needed for counters in text and holes in symbols. Raster runs
    store actual foreground pixel indices and have no inferred area boundary.
    """

    points: tuple[tuple[float, float], ...]
    parent: int | None
    depth: int
    root: int

