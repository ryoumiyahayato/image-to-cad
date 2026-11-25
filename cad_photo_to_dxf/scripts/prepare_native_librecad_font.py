"""Build/verify the offline LibreCAD companion of an existing pinned DejaVu TTF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(APP_ROOT))

from app.cad_font_resources import ensure_librecad_resource, inspect_librecad_resource  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ttf", type=Path, default=APP_ROOT / "resources/fonts/DejaVuSans.ttf")
    parser.add_argument("--source-license", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=APP_ROOT / "resources/fonts/librecad-native")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    record = (inspect_librecad_resource(args.source_ttf, args.cache_dir) if args.verify_only else
              ensure_librecad_resource(args.source_ttf, args.cache_dir, source_license=args.source_license))
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0 if record["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
