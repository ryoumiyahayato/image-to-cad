"""Versioned native PDF area facts. These do not own raster source pixels."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
import numpy as np
from app.core.arc_types import PdfPathReference


@dataclass(frozen=True)
class NativeFill:
    source: PdfPathReference
    points: tuple[tuple[float, float], ...]
    rgb: tuple[int, int, int]
    page_to_pixel: tuple[float, ...]
    source_dpi: float
    visibility: str = "full-only-without-opaque-quad-v1"
    relation: str = "native area; existing raster representations retained, not cleaned"
    version: int = 1

    def __post_init__(self):
        if not isinstance(self.source, PdfPathReference):
            raise TypeError("Native fill requires a PDF path reference")
        if any(isinstance(v, (bool, np.bool_)) for point in self.points for v in point):
            raise ValueError("Native fill vertices must be numeric coordinates")
        p = np.asarray(self.points, dtype=float)
        if self.version == 2:
            validate_simple_polygon(p)
        elif p.shape != (4, 2) or not np.isfinite(p).all():
            raise ValueError("Native fill requires four finite vertices")
        edges = np.roll(p, -1, axis=0) - p
        turns = (
            edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1]
            - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
        )
        if self.version == 1 and not (np.all(turns > 1e-8) or np.all(turns < -1e-8)):
            raise ValueError("Native fill must be a nondegenerate convex quad")
        if (
            len(self.rgb) != 3
            or any(
                isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 255
                for x in self.rgb
            )
            or self.rgb == (255, 255, 255)
        ):
            raise ValueError("Native fill requires nonwhite RGB")
        if len(self.page_to_pixel) != 6 or not all(
            not isinstance(x, bool) and isfinite(x) for x in self.page_to_pixel
        ):
            raise ValueError("Native fill requires a finite page transform")
        a, b, c, d, _, _ = self.page_to_pixel
        if (
            abs(a * d - b * c) <= 1e-12
            or isinstance(self.source_dpi, bool)
            or not isfinite(self.source_dpi)
            or self.source_dpi <= 0
        ):
            raise ValueError("Native fill transform/DPI is invalid")
        if (
            type(self.version) is not int
            or (self.version, self.visibility)
            not in (
                (1, "full-only-without-opaque-quad-v1"),
                (2, "full-only-without-opaque-simple-polygon-v2"),
            )
            or self.relation
            != "native area; existing raster representations retained, not cleaned"
        ):
            raise ValueError("Unsupported native fill qualification")
        object.__setattr__(self, "points", tuple(tuple(float(v) for v in q) for q in p))
        object.__setattr__(self, "rgb", tuple(self.rgb))
        object.__setattr__(
            self, "page_to_pixel", tuple(float(v) for v in self.page_to_pixel)
        )

    @property
    def object_id(self):
        s = self.source
        return f"PDF-FILL:p{s.page_number}:o{s.object_index}:s{s.subpath_index}"

    def payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        data = dict(value)
        data["source"] = PdfPathReference(**data["source"])
        data["rgb"] = tuple(data["rgb"])
        return cls(**data)


def validate_simple_polygon(points):
    """One explicit, finite, nonintersecting linear ring. No inferred holes."""
    p = np.asarray(points, dtype=float)
    if (
        p.ndim != 2
        or p.shape[1] != 2
        or not 3 <= len(p) <= 128
        or not np.isfinite(p).all()
    ):
        raise ValueError("Native polygon requires 3..128 finite vertices")
    edges = np.roll(p, -1, axis=0) - p
    if np.any(np.linalg.norm(edges, axis=1) <= 1e-8):
        raise ValueError("Native polygon has a zero edge")
    area = 0.5 * abs(
        np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))
    )
    if area <= 1e-6:
        raise ValueError("Native polygon has no area")

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        for j in range(i + 2, len(p)):
            if i == 0 and j == len(p) - 1:
                continue
            c, d = p[j], p[(j + 1) % len(p)]
            if np.any(
                np.maximum(np.minimum(a, b), np.minimum(c, d))
                > np.minimum(np.maximum(a, b), np.maximum(c, d)) + 1e-9
            ):
                continue
            u, v = cross(b - a, c - a), cross(b - a, d - a)
            w, z = cross(d - c, a - c), cross(d - c, b - c)
            if u * v <= 1e-12 and w * z <= 1e-12:
                raise ValueError("Native polygon has intersecting edges")
    return p


def polygon_signed_distance(points, x0, y0, x1, y1):
    """Pixel-center containment and distance for concave linear rings."""
    yy, xx = np.mgrid[y0:y1, x0:x1]
    x = xx + 0.5
    y = yy + 0.5
    inside = np.zeros(x.shape, dtype=bool)
    distance = np.full(x.shape, np.inf)
    p = np.asarray(points, dtype=float)
    for a, b in zip(p, np.roll(p, -1, axis=0)):
        edge = b - a
        if b[1] != a[1]:
            inside ^= ((a[1] > y) != (b[1] > y)) & (
                x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            )
        t = np.clip(
            ((x - a[0]) * edge[0] + (y - a[1]) * edge[1]) / np.dot(edge, edge), 0, 1
        )
        distance = np.minimum(
            distance, np.hypot(x - a[0] - t * edge[0], y - a[1] - t * edge[1])
        )
    return np.where(inside, distance, -distance)
