"""Cold acceptance entry for actual saved DXF and unchanged original pixels.

Font pins are a JSON map of saved font filenames to SHA-256 or to explicit
{path, sha256} bindings. Target IDs locate entities; source truth is rebuilt.
The resulting file can contain private drawing coordinates and stays private.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))

from app.native_objects.finite_component_source_audit import (
    audit_saved_source_component,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dxf", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--roi", type=int, nargs=4, required=True)
    parser.add_argument("--dpi", type=float, required=True)
    parser.add_argument("--target-id", action="append", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-dxf-sha256", required=True)
    parser.add_argument("--font-pins", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new receipt; preserve previous results")
    bindings = json.loads(args.font_pins.read_text(encoding="utf-8")) if args.font_pins else None
    report = audit_saved_source_component(args.dxf, args.source, args.roi, args.dpi, args.target_id,
        font_bindings=bindings, expected_dxf_sha256=args.expected_dxf_sha256,
        expected_source_sha256=args.expected_source_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"schema": report["schema"], "status": report["status"],
        "source_sha256": report["source_sha256"], "dxf_sha256": report["dxf_sha256"],
        "failure_reasons": report["failure_reasons"]}, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
