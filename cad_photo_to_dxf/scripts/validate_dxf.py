from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dxf_validator import validate_dxf  # noqa: E402


_FREECAD_JSON_PREFIX = "DXF_VALIDATION_JSON="


def validate_with_freecad(
    path: Path,
    freecad_command: str,
) -> dict[str, Any]:
    """Import a DXF with FreeCADCmd and return machine-readable evidence."""
    script = f'''from __future__ import annotations
import json
import sys

import FreeCAD
import importDXF

input_path = sys.argv[-1]
document = FreeCAD.newDocument("DXFValidation")
importDXF.insert(input_path, document.Name)
document.recompute()
object_count = len(document.Objects)
payload = {{
    "passed": object_count > 0,
    "object_count": object_count,
    "freecad_version": list(FreeCAD.Version()),
}}
print("{_FREECAD_JSON_PREFIX}" + json.dumps(payload, ensure_ascii=False))
if object_count <= 0:
    raise SystemExit(2)
'''
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "freecad_validate.py"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [freecad_command, str(script_path), str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    parsed: dict[str, Any] | None = None
    for line in reversed(completed.stdout.splitlines()):
        stripped = line.strip()
        if not stripped.startswith(_FREECAD_JSON_PREFIX):
            continue
        try:
            value = json.loads(stripped[len(_FREECAD_JSON_PREFIX) :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed = value
            break

    payload: dict[str, Any] = {
        "command": freecad_command,
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if parsed is None:
        payload["parse_warning"] = "FreeCAD output did not contain validation JSON"
        payload["passed"] = False
        return payload

    payload.update(parsed)
    object_count = int(parsed.get("object_count", 0) or 0)
    payload["passed"] = (
        completed.returncode == 0
        and bool(parsed.get("passed"))
        and object_count > 0
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate DXF structure, duplicates, topology diagnostics, "
            "and optional FreeCAD import."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument(
        "--gap-tolerance",
        type=float,
        default=0.5,
        help="Distance used to report nearby unjoined endpoints",
    )
    parser.add_argument(
        "--max-intersection-checks",
        type=int,
        default=2_000_000,
        help="Maximum line-pair checks for unsplit intersection diagnostics",
    )
    parser.add_argument(
        "--freecad-command",
        help="Optional FreeCADCmd executable path for independent import validation",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = validate_dxf(
        args.input,
        tolerance=args.tolerance,
        gap_tolerance=args.gap_tolerance,
        max_intersection_checks=args.max_intersection_checks,
    )
    report: dict[str, Any] = {
        "dxf": result.to_dict(),
        "freecad": None,
    }
    if args.freecad_command:
        try:
            report["freecad"] = validate_with_freecad(
                args.input,
                args.freecad_command,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            report["freecad"] = {
                "passed": False,
                "error": str(exc),
            }

    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    freecad_passed = (
        report["freecad"] is None or bool(report["freecad"].get("passed"))
    )
    return 0 if result.passed and freecad_passed else 1


if __name__ == "__main__":
    sys.exit(main())
