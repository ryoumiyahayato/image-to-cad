"""General circular-arc recognition for native PDF cubic paths."""
from __future__ import annotations

from math import ceil, comb, degrees, isfinite
import numpy as np

MAX_SAMPLES = 16385


def fit_cubic_arc(points, stroke_width_px):
    """Recognize circular cubic constructions in the input coordinate system.

    Allow at most 0.10 coordinate units or 8% of the stroke width, whichever is
    smaller. Check the complete cubic using sampled radial error plus a bound
    between samples, and reject tangent or angular reversals. The PDF importer
    passes points and stroke widths in PDF points; no rendered image is needed.
    Inputs use page coordinates (x right, y down).
    """
    p = np.asarray(points, dtype=np.float64)
    if (
        p.shape != (4, 2)
        or not np.isfinite(p).all()
        or not isfinite(stroke_width_px)
        or stroke_width_px <= 0
    ):
        raise ValueError("INVALID_CUBIC")
    tangent0, tangent1 = p[1] - p[0], p[3] - p[2]
    normals = np.array([tangent0, tangent1])
    if (
        abs(np.linalg.det(normals))
        <= np.linalg.norm(tangent0) * np.linalg.norm(tangent1) * 1e-6
    ):
        raise ValueError("UNRESOLVED_CENTER")
    center = np.linalg.solve(normals, [tangent0 @ p[0], tangent1 @ p[3]])
    radii = np.linalg.norm(p[[0, 3]] - center, axis=1)
    radius = float(radii.mean())
    tolerance = min(0.10, stroke_width_px * 0.08)
    if radius <= stroke_width_px * 4 or abs(radii[0] - radii[1]) > tolerance:
        raise ValueError("ENDPOINT_RADII_OR_SCALE")
    speed_bound = float(3 * np.linalg.norm(np.diff(p, axis=0), axis=1).max())
    count = max(257, ceil(speed_bound / (tolerance / 4)) + 1)
    if count > MAX_SAMPLES:
        raise ValueError("CURVE_SAMPLE_BUDGET")
    t = np.linspace(0, 1, count)[:, None]
    q = (
        (1 - t) ** 3 * p[0]
        + 3 * (1 - t) ** 2 * t * p[1]
        + 3 * (1 - t) * t * t * p[2]
        + t**3 * p[3]
    )
    radial_error = float(np.abs(np.linalg.norm(q - center, axis=1) - radius).max())
    gap_bound = speed_bound / (2 * (count - 1))
    if radial_error + gap_bound > tolerance:
        raise ValueError("NONCIRCULAR_CUBIC")
    angles = np.unwrap(np.arctan2(-(q[:, 1] - center[1]), q[:, 0] - center[0]))
    delta = np.diff(angles)
    sweep = float(degrees(angles[-1] - angles[0]))
    if not 1e-5 < abs(sweep) < 180 or np.any(delta * np.sign(sweep) < -1e-10):
        raise ValueError("UNRESOLVED_SWEEP")
    # The curvature numerator of a cubic is quadratic. Check its extrema, not
    # only sampled points, so a reversal between samples cannot pass.
    a, b, c = (
        -p[0] + 3 * p[1] - 3 * p[2] + p[3],
        3 * p[0] - 6 * p[1] + 3 * p[2],
        3 * (p[1] - p[0]),
    )

    def cross(u, v):
        return float(u[0] * v[1] - u[1] * v[0])

    qa, qb, qc = -6 * cross(a, b), 6 * cross(c, a), 2 * cross(c, b)
    checks = [0.0, 1.0]
    if qa and 0 < -qb / (2 * qa) < 1:
        checks.append(-qb / (2 * qa))
    curvature = [(qa * x * x + qb * x + qc) * -np.sign(sweep) for x in checks]
    if min(curvature) <= 0:
        raise ValueError("CURVATURE_REVERSAL")
    # Bernstein coefficients of cross(B-center, B') give a conservative sign
    # check on the entire segment's polar motion. Together with the radial
    # bound this covers the complete arc locus, including both mapped ends.
    angular = np.zeros(6)
    for i in range(4):
        for j in range(3):
            angular[i + j] += (
                comb(3, i)
                * comb(2, j)
                / comb(5, i + j)
                * cross(p[i] - center, 3 * (p[j + 1] - p[j]))
            )
    angular *= -np.sign(sweep)
    if min(angular) <= 0:
        raise ValueError("ANGULAR_RANGE_UNRESOLVED")
    endpoint_angles = angles[[0, -1]]
    circle_tangents = np.stack(
        (-np.sin(endpoint_angles), -np.cos(endpoint_angles)), axis=1
    ) * np.sign(sweep)
    source_tangents = np.asarray([tangent0, tangent1])
    source_tangents /= np.linalg.norm(source_tangents, axis=1)[:, None]
    tangent_alignment = np.sum(circle_tangents * source_tangents, axis=1)
    if min(tangent_alignment) < 1 - 1e-6:
        raise ValueError("ENDPOINT_TANGENT_CHANGED")
    return dict(
        center=tuple(float(x) for x in center),
        radius=radius,
        start_angle_deg=float(degrees(angles[0])) % 360,
        sweep_angle_deg=sweep,
    ), dict(
        sample_count=count,
        sampled_radial_error_px=radial_error,
        between_sample_bound_px=gap_bound,
        radial_upper_bound_px=radial_error + gap_bound,
        tolerance_px=tolerance,
        endpoint_radii_px=radii.tolist(),
        endpoint_displacement_px=float(np.abs(radii - radius).max()),
        curvature_numerator_min=float(min(curvature)),
        angular_bernstein_min=float(min(angular)),
        endpoint_tangent_alignment=tangent_alignment.tolist(),
    )
