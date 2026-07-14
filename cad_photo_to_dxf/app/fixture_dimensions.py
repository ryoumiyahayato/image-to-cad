from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class VerificationReference:
    reference_id: str
    ground_truth_start: tuple[float, float]
    ground_truth_end: tuple[float, float]
    expected_mm: float

    @property
    def ground_truth_length(self) -> float:
        return math.hypot(
            self.ground_truth_end[0] - self.ground_truth_start[0],
            self.ground_truth_end[1] - self.ground_truth_start[1],
        )


def _point(value: object, field: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must contain exactly two coordinates")
    coordinates: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field} coordinates must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{field} coordinates must be finite")
        coordinates.append(number)
    return coordinates[0], coordinates[1]


def parse_verification_references(
    manifest: dict[str, Any],
) -> tuple[VerificationReference, ...]:
    value = manifest.get("verification_references")
    if not isinstance(value, list) or not value:
        raise ValueError("verification_references must contain at least one reference")

    references: list[VerificationReference] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        field = f"verification_references[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field} must be an object")
        required = {
            "id",
            "ground_truth_start",
            "ground_truth_end",
            "expected_mm",
        }
        if set(item) != required:
            raise ValueError(f"{field} must contain exactly {sorted(required)}")
        reference_id = item.get("id")
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise ValueError(f"{field}.id must be a non-empty string")
        if reference_id in seen_ids:
            raise ValueError(f"duplicate verification reference id: {reference_id}")
        seen_ids.add(reference_id)

        start = _point(item.get("ground_truth_start"), f"{field}.ground_truth_start")
        end = _point(item.get("ground_truth_end"), f"{field}.ground_truth_end")
        expected = item.get("expected_mm")
        if (
            isinstance(expected, bool)
            or not isinstance(expected, (int, float))
            or not math.isfinite(float(expected))
            or float(expected) <= 0
        ):
            raise ValueError(f"{field}.expected_mm must be finite and positive")
        reference = VerificationReference(
            reference_id=reference_id,
            ground_truth_start=start,
            ground_truth_end=end,
            expected_mm=float(expected),
        )
        if reference.ground_truth_length <= 1e-9:
            raise ValueError(f"{field} ground-truth segment has zero length")
        references.append(reference)

    declared_dimensions = manifest.get("verification_dimensions")
    expected_dimensions = [reference.expected_mm for reference in references]
    if not isinstance(declared_dimensions, list):
        raise ValueError("verification_dimensions must be a list")
    try:
        declared = [float(item) for item in declared_dimensions]
    except (TypeError, ValueError) as exc:
        raise ValueError("verification_dimensions must contain numbers") from exc
    if len(declared) != len(expected_dimensions) or any(
        not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
        for left, right in zip(declared, expected_dimensions, strict=True)
    ):
        raise ValueError(
            "verification_dimensions must match verification_references expected_mm values"
        )

    calibration_dimensions = manifest.get("calibration_dimensions")
    if isinstance(calibration_dimensions, list):
        try:
            calibration = [float(item) for item in calibration_dimensions]
        except (TypeError, ValueError) as exc:
            raise ValueError("calibration_dimensions must contain numbers") from exc
        if calibration == declared:
            raise ValueError(
                "verification references must be independent from calibration dimensions"
            )

    scale_tolerance = manifest.get("tolerances", {}).get("scale_relative")
    if isinstance(scale_tolerance, bool) or not isinstance(
        scale_tolerance,
        (int, float),
    ):
        raise ValueError("tolerances.scale_relative must be numeric")
    maximum_relative_error = max(float(scale_tolerance), 1e-6)
    for reference in references:
        relative_error = abs(
            reference.ground_truth_length / reference.expected_mm - 1.0
        )
        if relative_error > maximum_relative_error:
            raise ValueError(
                f"verification reference {reference.reference_id} ground-truth length "
                f"differs from expected_mm by {relative_error:.6f}"
            )

    return tuple(references)
