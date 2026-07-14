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

from app.dxf_validator import validate_dxf


SUPPORTED_ENTITY_TYPES = {"LINE", "CIRCLE"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    parser.add_argument("--max-intersection-checks", type=int, default=2_000_000)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema_version": "dxf-validation/4",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input.resolve()),
        "success": False,
    }
    return_code = 1
    try:
        if not args.input.is_file():
            raise FileNotFoundError(args.input)

        line_validation = validate_dxf(
            args.input,
            tolerance=max(1e-9, args.endpoint_tolerance),
            gap_tolerance=max(args.endpoint_tolerance, args.gap_tolerance),
            max_intersection_checks=args.max_intersection_checks,
        )
        document = ezdxf.readfile(str(args.input))
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

        layers: Counter[str] = Counter()
        xs: list[float] = []
        ys: list[float] = []
        for entity in modelspace.query("LINE"):
            start = entity.dxf.start
            end = entity.dxf.end
            values = (
                float(start.x),
                float(start.y),
                float(end.x),
                float(end.y),
            )
            if all(math.isfinite(value) for value in values):
                xs.extend((values[0], values[2]))
                ys.extend((values[1], values[3]))
                layers[str(entity.dxf.layer)] += 1

        circles: list[tuple[float, float, float, str]] = []
        nonfinite_circles = 0
        nonpositive_radius_circles = 0
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
            xs.extend((values[0] - values[2], values[0] + values[2]))
            ys.extend((values[1] - values[2], values[1] + values[2]))

        circle_keys = Counter(
            _canonical_circle_key(center_x, center_y, radius)
            for center_x, center_y, radius, _layer in circles
        )
        exact_circle_duplicates = sum(
            count - 1 for count in circle_keys.values() if count > 1
        )
        circle_count = int(entity_type_counts.get("CIRCLE", 0))
        supported_entity_count = line_validation.line_count + circle_count
        empty_geometry = supported_entity_count == 0
        bounds = (
            {
                "min_x": min(xs),
                "min_y": min(ys),
                "max_x": max(xs),
                "max_y": max(ys),
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
            }
            if xs and ys
            else None
        )
        topology = {
            "dangling_endpoint_count": line_validation.dangling_endpoint_count,
            "unique_endpoint_count": line_validation.unique_endpoint_count,
            "connected_component_count": line_validation.connected_component_count,
            "open_component_count": line_validation.open_component_count,
            "closed_component_count": line_validation.closed_component_count,
            "near_gap_count": line_validation.near_gap_count,
            "unsplit_intersection_count": line_validation.unsplit_intersection_count,
            "intersection_pair_checks": line_validation.intersection_pair_checks,
            "intersection_check_limit_reached": (
                line_validation.intersection_check_limit_reached
            ),
        }

        success = (
            line_validation.passed
            and not empty_geometry
            and unexpected_entity_count == 0
            and nonfinite_circles == 0
            and nonpositive_radius_circles == 0
            and exact_circle_duplicates == 0
        )
        evidence.update(
            {
                "input_sha256": _sha256(args.input),
                "dxf_version": document.dxfversion,
                "audit_error_count": line_validation.audit_error_count,
                "audit_fix_count": line_validation.audit_fix_count,
                "audit_errors": list(line_validation.audit_errors),
                "audit_fixes": list(line_validation.audit_fixes),
                "entity_type_counts": dict(sorted(entity_type_counts.items())),
                "supported_entity_count": supported_entity_count,
                "unexpected_entity_types": unexpected_entity_types,
                "unexpected_entity_count": unexpected_entity_count,
                "empty_geometry": empty_geometry,
                "line_count": line_validation.line_count,
                "circle_count": circle_count,
                "layer_counts": dict(sorted(layers.items())),
                "bounds": bounds,
                "nonfinite_line_count": line_validation.invalid_coordinate_count,
                "zero_length_line_count": line_validation.zero_length_count,
                "exact_duplicate_line_count": line_validation.duplicate_line_count,
                "nonfinite_circle_count": nonfinite_circles,
                "nonpositive_radius_circle_count": nonpositive_radius_circles,
                "exact_duplicate_circle_count": exact_circle_duplicates,
                "topology": topology,
                "success": success,
            }
        )
        return_code = 0 if success else 1
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
