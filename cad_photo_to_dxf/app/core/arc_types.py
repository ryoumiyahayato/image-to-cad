"""Accepted circular arcs in source pixels, separate from PDF proposals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import atan2, cos, degrees, hypot, isfinite, radians, sin
import numpy as np


def arc_extrema(center, radius, start, sweep, *, y_down=True):
    angles = [start, start + sweep]
    for angle in (0.0, 90.0, 180.0, 270.0):
        distance = ((angle - start) if sweep > 0 else (start - angle)) % 360.0
        if distance <= abs(sweep) + 1e-10:
            angles.append(angle)
    return tuple((center[0] + radius * cos(radians(a)),
                  center[1] + (-1 if y_down else 1) * radius * sin(radians(a)))
                 for a in angles)


@dataclass(frozen=True)
class PdfPathReference:
    document: str
    page_number: int
    object_index: int
    subpath_index: int = 0

    def __post_init__(self):
        if not self.document.strip():
            raise ValueError('PDF source document is required')
        for name, minimum in (('page_number', 1), ('object_index', 0), ('subpath_index', 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f'Invalid PDF {name}')


@dataclass(frozen=True)
class ArcSegment:
    """Final member: center/radius in px, angles about +X with +Y upward.

    Source coordinates have Y downward. Signed sweep follows source traversal;
    0 and full circles are rejected. DXF serializes the same locus CCW.
    """
    object_id: str
    center: tuple[float, float]
    radius: float
    start_angle_deg: float
    sweep_angle_deg: float
    layer: str = 'TRACE_CURVE'
    stroke_width_px: float = 1.0
    source_dpi: float = 300.0
    lineweight: int = 13
    source: PdfPathReference | None = None
    replaced_members: tuple[str, ...] = ()
    acceptance_reason: str = 'explicit accepted structure member'
    stroke_cap: str = 'butt'
    stroke_width_bounds_px: tuple[float, float] | None = None
    geometry_error_px: float = 0.0

    def __post_init__(self):
        if not self.object_id.strip() or not self.layer.strip() or not self.acceptance_reason.strip():
            raise ValueError('ARC identity, layer and acceptance reason are required')
        if len(self.center) != 2:
            raise ValueError('ARC center must have two coordinates')
        for value in (*self.center, self.radius, self.start_angle_deg,
                      self.sweep_angle_deg, self.stroke_width_px, self.source_dpi):
            if isinstance(value, (bool, np.bool_)) or not isfinite(float(value)):
                raise ValueError('ARC parameters must be finite numbers')
        if min(self.radius, self.stroke_width_px, self.source_dpi) <= 0:
            raise ValueError('ARC radius, stroke width and DPI must be positive')
        if not 0 < abs(self.sweep_angle_deg) < 360:
            raise ValueError('ARC sweep must be nonzero and smaller than a full circle')
        if isinstance(self.lineweight, bool) or self.lineweight not in (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211):
            raise ValueError('Invalid ARC DXF lineweight')
        if self.source is not None and not isinstance(self.source, PdfPathReference):
            raise TypeError('ARC source must be a PDF path reference')
        if self.stroke_cap not in ('butt', 'round'):
            raise ValueError('Unsupported ARC stroke cap')
        if isinstance(self.geometry_error_px, (bool, np.bool_)) or not isfinite(self.geometry_error_px) or self.geometry_error_px < 0:
            raise ValueError('Invalid ARC geometry error')
        if self.stroke_cap == 'round':
            bounds = self.stroke_width_bounds_px
            if bounds is None or len(bounds) != 2 or not all(not isinstance(x, (bool, np.bool_)) and isfinite(x) for x in bounds) or not 0 < bounds[0] <= self.stroke_width_px <= bounds[1]:
                raise ValueError('Round ARC requires mapped stroke width bounds')
            if self.lineweight <= 0:
                raise ValueError('Round ARC requires a positive DXF lineweight')
            if self.geometry_error_px > min(.10, self.stroke_width_px*.08):
                raise ValueError('Round ARC exceeds the curve error tolerance')
            object.__setattr__(self, 'stroke_width_bounds_px', tuple(float(x) for x in bounds))
            self.round_stroke_error_px()
        elif self.stroke_width_bounds_px is not None or self.geometry_error_px != 0:
            raise ValueError('Stroke approximation evidence requires a round ARC')
        object.__setattr__(self, 'center', tuple(float(x) for x in self.center))
        object.__setattr__(self, 'start_angle_deg', float(self.start_angle_deg) % 360)
        for name in ('radius', 'sweep_angle_deg', 'stroke_width_px', 'source_dpi'):
            object.__setattr__(self, name, float(getattr(self, name)))
        object.__setattr__(self, 'replaced_members', tuple(self.replaced_members))
        if any(not isinstance(x, str) or not x.strip() for x in self.replaced_members):
            raise ValueError('ARC replaced member references must be nonempty strings')
        if len(set(self.replaced_members)) != len(self.replaced_members):
            raise ValueError('Duplicate ARC replaced member references')
        if (self.start_angle_deg+self.sweep_angle_deg) % 360 == self.start_angle_deg:
            raise ValueError('ARC sweep cannot collapse in floating point')
        if not all(isfinite(v) for point in self.extrema for v in point):
            raise ValueError('ARC extent must be finite')

    def point_at(self, fraction):
        a = radians(self.start_angle_deg + self.sweep_angle_deg * fraction)
        return (self.center[0] + self.radius * cos(a), self.center[1] - self.radius * sin(a))

    @property
    def extrema(self):
        return arc_extrema(self.center, self.radius, self.start_angle_deg, self.sweep_angle_deg)

    @property
    def bounds(self):
        points = self.extrema
        return (min(x for x, y in points), min(y for x, y in points),
                max(x for x, y in points), max(y for x, y in points))

    def payload(self):
        payload = asdict(self)
        if self.stroke_cap == 'butt':
            # Preserve schema-4 identities of already saved P9/P9-B members.
            for name in ('stroke_cap', 'stroke_width_bounds_px', 'geometry_error_px'):
                payload.pop(name)
        return {'coordinate_system': 'source-pixels-y-down-angles-y-up', **payload}

    def round_stroke_error_px(self, mm_per_pixel=None):
        """Bound round-stroke boundary displacement, separate from circle error.

        A round stroke is the centerline swept by a disk. Singular values bound
        the mapped disk; adding its radius error to the full centerline error
        bounds the visible stroke, including both caps. Half a source pixel is
        the maximum display displacement; the tighter curve tolerance is intact.
        """
        if self.stroke_cap != 'round':
            return 0.
        scale = 25.4/self.source_dpi if mm_per_pixel is None else mm_per_pixel
        if not isfinite(scale) or scale <= 0:
            raise ValueError('Invalid round ARC paper scale')
        rendered_width = self.lineweight/100/scale
        error = self.geometry_error_px + max(abs(rendered_width-w) for w in self.stroke_width_bounds_px)/2
        if error > .5:
            raise ValueError('ROUND_CAP_DISPLAY_ERROR')
        return error

    @classmethod
    def from_payload(cls, payload):
        value = dict(payload)
        if value.pop('coordinate_system', None) != 'source-pixels-y-down-angles-y-up':
            raise ValueError('Unsupported ARC coordinate system')
        if value.get('source') is not None:
            value['source'] = PdfPathReference(**value['source'])
        return cls(**value)


def transformed_arc(arc: ArcSegment, transform):
    """Reject non-similarity transforms before any DXF entity is written."""
    cx, cy = arc.center
    center = transform(cx, cy)
    x = transform(cx + 1, cy)
    y = transform(cx, cy - 1)
    u, v = (x[0]-center[0], x[1]-center[1]), (y[0]-center[0], y[1]-center[1])
    sx, sy = hypot(*u), hypot(*v)
    if not all(isfinite(z) for z in (*center, *u, *v)) or min(sx, sy) <= 0:
        raise ValueError('Invalid ARC output transform')
    if abs(sx-sy) > max(sx, sy)*1e-6 or abs(u[0]*v[0]+u[1]*v[1]) > sx*sy*1e-6:
        raise ValueError('ARC requires a uniform orthogonal output transform')
    p = transform(*arc.point_at(0))
    start = degrees(atan2(p[1]-center[1], p[0]-center[0])) % 360
    sweep = arc.sweep_angle_deg * (1 if u[0]*v[1]-u[1]*v[0] > 0 else -1)
    radius = arc.radius * sx
    extrema = arc_extrema(center, radius, start, sweep, y_down=False)
    if not isfinite(radius) or radius <= 0 or p == center or not all(isfinite(z) for point in extrema for z in point):
        raise ValueError('ARC output geometry is not representable')
    if sweep < 0:
        start += sweep
        sweep = -sweep
    return center, radius, start % 360, (start+sweep) % 360, extrema
