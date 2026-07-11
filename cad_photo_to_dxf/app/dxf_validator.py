from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import math
from typing import Any

import ezdxf


@dataclass(frozen=True)
class DxfValidationResult:
    path: Path
    audit_error_count: int
    audit_fix_count: int
    line_count: int
    invalid_coordinate_count: int
    zero_length_count: int
    duplicate_line_count: int
    dangling_endpoint_count: int
    unique_endpoint_count: int
    tolerance: float
    passed: bool
    audit_errors: tuple[str, ...] = ()
    audit_fixes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


def _quantize(value: float, tolerance: float) -> int:
    return int(round(value / tolerance))


def _point_key(point: tuple[float, float], tolerance: float) -> tuple[int, int]:
    return _quantize(point[0], tolerance), _quantize(point[1], tolerance)


def _line_key(
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float,
) -> tuple[tuple[int, int], tuple[int, int]]:
    first = _point_key(start, tolerance)
    second = _point_key(end, tolerance)
    return (first, second) if first <= second else (second, first)


def validate_dxf(
    path: str | Path,
    *,
    tolerance: float = 1e-6,
) -> DxfValidationResult:
    """Validate structural DXF integrity without claiming CAD semantic correctness."""
    if tolerance <= 0 or not math.isfinite(tolerance):
        raise ValueError("Validation tolerance must be a finite positive number")

    input_path = Path(path)
    document = ezdxf.readfile(input_path)
    auditor = document.audit()
    audit_errors = tuple(str(item) for item in auditor.errors)
    audit_fixes = tuple(str(item) for item in auditor.fixes)

    line_count = 0
    invalid_coordinate_count = 0
    zero_length_count = 0
    duplicate_line_count = 0
    line_keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    endpoint_degrees: dict[tuple[int, int], int] = {}

    for entity in document.modelspace().query("LINE"):
        line_count += 1
        start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
        end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
        coordinates = (*start, *end)
        if not all(math.isfinite(value) for value in coordinates):
            invalid_coordinate_count += 1
            continue

        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= tolerance:
            zero_length_count += 1
            continue

        key = _line_key(start, end, tolerance)
        if key in line_keys:
            duplicate_line_count += 1
        else:
            line_keys.add(key)

        for endpoint in key:
            endpoint_degrees[endpoint] = endpoint_degrees.get(endpoint, 0) + 1

    dangling_endpoint_count = sum(
        1 for degree in endpoint_degrees.values() if degree == 1
    )
    passed = (
        len(audit_errors) == 0
        and invalid_coordinate_count == 0
        and zero_length_count == 0
        and duplicate_line_count == 0
    )
    return DxfValidationResult(
        path=input_path,
        audit_error_count=len(audit_errors),
        audit_fix_count=len(audit_fixes),
        line_count=line_count,
        invalid_coordinate_count=invalid_coordinate_count,
        zero_length_count=zero_length_count,
        duplicate_line_count=duplicate_line_count,
        dangling_endpoint_count=dangling_endpoint_count,
        unique_endpoint_count=len(endpoint_degrees),
        tolerance=tolerance,
        passed=passed,
        audit_errors=audit_errors,
        audit_fixes=audit_fixes,
    )
