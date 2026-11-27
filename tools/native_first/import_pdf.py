"""Command-line access to the same native PDF converter as the desktop app."""
from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "cad_photo_to_dxf"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

_conversion = import_module("app.core.pdf_conversion")
inspect_page = _conversion.inspect_pdf_page
export_page = _conversion.convert_pdf_page


def main():
    parser = argparse.ArgumentParser(description="Native PDF vectors, editable Unicode text and images to DXF")
    parser.add_argument("input", type=Path)
    parser.add_argument("--page", type=int, default=1, help="1-based page number")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--color", action="store_true", help="Retain PDF source colors instead of black-and-white layers")
    args = parser.parse_args()
    if args.inspect:
        result = inspect_page(args.input, args.page)
    else:
        if not args.output:
            parser.error("--output is required unless --inspect is used")
        result = export_page(args.input, args.output, args.page, monochrome=not args.color, overwrite=args.overwrite)
        if result["route"] == "scan":
            parser.error("This page is a scan. Use cad_photo_to_dxf/main.py for automatic scan conversion.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
