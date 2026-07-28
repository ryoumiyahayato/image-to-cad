from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.debug_bundle import capture_debug_bundle  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture the complete 26-stage image-to-CAD debug bundle for one "
            "raster image or one PDF page."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-index", type=int, default=0)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument(
        "--disable-ocr",
        action="store_true",
        help="Skip OCR; the bundle still records its stages as not executed.",
    )
    parser.add_argument("--foreground-threshold", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest_path = capture_debug_bundle(
        args.input,
        args.output,
        page_index=args.page_index,
        dpi=args.dpi,
        enable_ocr=not args.disable_ocr,
        foreground_threshold=args.foreground_threshold,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "passed": manifest["passed"],
                "manifest": str(manifest_path),
                "stage_count": manifest["stage_count"],
                "structure_id": manifest["structure_id"],
                "dxf_audit_error_count": manifest["dxf"]["audit_error_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
