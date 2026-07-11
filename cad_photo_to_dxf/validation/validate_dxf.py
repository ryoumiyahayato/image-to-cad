from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import traceback

import ezdxf

from app.line_detect import LineSegment
from app.topology import validate_topology


SUPPORTED_ENTITY_TYPES = {"LINE", "CIRCLE"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_line_key(line: LineSegment, decimals: int = 9) -> tuple[float, ...]:
    start, end = sorted(
        (
            (round(line.x1, decimals), round(line.y1, decimals)),
            (round(line.x2, decimals), round(line.y2, decimals)),
        )
    )
    return (*start, *end)


def _canonical_circle_key(
    center_x: float,
    center_y: float,
    radius: float,
    decimals: int = 9,
) -> tuple[float, float, float]:
    return (
        round(center_x, decimals),
        round(center_y, decimals),
        round(radius, decimals),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a DXF and emit machine-readable geometry evidence."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--endpoint-tolerance", type=float, default=1e-6)
    parser.add_argument("--gap-tolerance", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema_version": "dxf-validation/3",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.resolve()),
        "success": False,
    }
    return_code = 1
    try:
        if not args.input.is_file():
            raise FileNotFoundError(args.input)
        document = ezdxf.readfile(str(args.input))
        auditor = document.audit()
        modelspace = document.modelspace()
        entity_type_counts = Counter(entity.dxftype() for entity in modelspace)
        unexpected_entity_types = sorted(
            entity_type
            for entity_type in entity_type_counts
            if entity_type not in SUPPORTED_ENTITY_TYPES
        )
        unexpected_entity_count = sum(
            entity_type_counts[entity_type] for entity_type in unexpected_entity_types
        )

        lines: list[LineSegment] = []
        circles: list[tuple[float, float, float, str]] = []
        layers: Counter[str] = Counter()
        nonfinite_lines = 0
        zero_length_lines = 0
        nonfinite_circles = 0
        nonpositive_radius_circles = 0

        for index, entity in enumerate(modelspace.query("LINE"), start=1):
            start = entity.dxf.start
            end = entity.dxf.end
            coordinates = (
                float(start.x),
                float(start.y),
                float(end.x),
                float(end.y),
            )
            if not all(math.isfinite(value) for value in coordinates):
                nonfinite_lines += 1
                continue
            segment = LineSegment(
                *coordinates,
                layer=str(entity.dxf.layer),
                source_ids=(f"DXF-LINE-{index:06d}",),
                history=("validation-import",),
            )
            if segment.length <= 1e-9:
                zero_length_lines += 1
            lines.append(segment)
            layers[segment.layer] += 1

        for entity in modelspace.query("CIRCLE"):
            center = entity.dxf.center
            values = (
                float(center.x),
                float(center.y),
                float(entity.dxf.radius),
            )
            if not all(math.isfinite(value) for value in values):
                nonfinite_circles += 1
                continue
            if values[2] <= 1e-9:
                nonpositive_radius_circles += 1
            layer = str(entity.dxf.layer)
            circles.append((*values, layer))
            layers[layer] += 1

        supported_entity_count = len(lines) + len(circles)
        empty_geometry = supported_entity_count == 0
        line_keys = Counter(_canonical_line_key(line) for line in lines)
        exact_line_duplicates = sum(
            count - 1 for count in line_keys.values() if count > 1
        )
        circle_keys = Counter(
            _canonical_circle_key(center_x, center_y, radius)
            for center_x, center_y, radius, _layer in circles
        )
        exact_circle_duplicates = sum(
            count - 1 for count in circle_keys.values() if count > 1
        )
        topology = validate_topology(
            lines,
            endpoint_tolerance=max(1e-9, args.endpoint_tolerance),
            gap_tolerance=max(args.endpoint_tolerance, args.gap_tolerance),
            intersection_tolerance=max(1e-9, args.endpoint_tolerance),
        )

        xs = [coordinate for line in lines for coordinate in (line.x1, line.x2)]
        ys = [coordinate for line in lines for coordinate in (line.y1, line.y2)]
        for center_x, center_y, radius, _layer in circles:
            xs.extend((center_x - radius, center_x + radius))
            ys.extend((center_y - radius, center_y + radius))
        bounds: dict[str, float] | None
        if xs and ys:
            bounds = {
                "min_x": min(xs),
                "min_y": min(ys),
                "max_x": max(xs),
                "max_y": max(ys),
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
            }
        else:
            bounds = None

        evidence.update(
            {
                "input_sha256": _sha256(args.input),
                "dxf_version": document.dxfversion,
                "audit_error_count": len(auditor.errors),
                "audit_fix_count": len(auditor.fixes),
                "audit_errors": [str(item) for item in auditor.errors],
                "audit_fixes": [str(item) for item in auditor.fixes],
                "entity_type_counts": dict(sorted(entity_type_counts.items())),
                "supported_entity_count": supported_entity_count,
                "unexpected_entity_types": unexpected_entity_types,
                "unexpected_entity_count": unexpected_entity_count,
                "empty_geometry": empty_geometry,
                "line_count": len(lines),
                "circle_count": len(circles),
                "layer_counts": dict(sorted(layers.items())),
                "bounds": bounds,
                "nonfinite_line_count": nonfinite_lines,
                "zero_length_line_count": zero_length_lines,
                "exact_duplicate_line_count": exact_line_duplicates,
                "nonfinite_circle_count": nonfinite_circles,
                "nonpositive_radius_circle_count": nonpositive_radius_circles,
                "exact_duplicate_circle_count": exact_circle_duplicates,
                "topology": topology.__dict__,
            }
        )
        evidence["success"] = (
            len(auditor.errors) == 0
            and not empty_geometry
            and unexpected_entity_count == 0
            and nonfinite_lines == 0
            and zero_length_lines == 0
            and exact_line_duplicates == 0
            and nonfinite_circles == 0
            and nonpositive_radius_circles == 0
            and exact_circle_duplicates == 0
        )
        return_code = 0 if evidence["success"] else 1
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = str(exc)
        evidence["traceback"] = traceback.format_exc()
    finally:
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return return_code


if __name__ == "__main__":
    sys.exit(main())
