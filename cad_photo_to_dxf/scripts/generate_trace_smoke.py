from __future__ import annotations

import argparse
from pathlib import Path
import sys

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.raster_trace import trace_image  # noqa: E402
from app.scale_calibrator import ScaleCalibration  # noqa: E402
from app.trace_single_export import export_exact_trace_dxf  # noqa: E402


def build_smoke_image() -> np.ndarray:
    image = np.full((500, 800, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (770, 470), (0, 0, 0), 4)
    cv2.line(image, (80, 100), (720, 100), (0, 0, 0), 3)
    cv2.line(image, (100, 150), (100, 430), (0, 0, 0), 3)
    cv2.circle(image, (300, 280), 75, (0, 0, 0), 4)
    cv2.ellipse(image, (550, 285), (110, 65), 15, 0, 300, (0, 0, 0), 4)
    cv2.putText(
        image,
        "TRACE A11 9000",
        (150, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    cv2.rectangle(image, (690, 390), (696, 396), (80, 80, 80), -1)
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()

    image = build_smoke_image()
    result = trace_image(image)
    calibration = ScaleCalibration((0.0, 0.0), (799.0, 0.0), 420.0)
    export = export_exact_trace_dxf(
        result.paths,
        args.output,
        result.binary.shape[0],
        calibration,
        drawing_multiplier=100.0,
        trace_color=7,
    )
    if args.binary is not None:
        args.binary.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.binary), result.binary):
            raise RuntimeError(f"Failed to write {args.binary}")
    if export.trace_path_count <= 0 or export.trace_vertex_count <= 0:
        raise RuntimeError("Trace smoke export did not contain traced geometry")
    print(
        f"trace_paths={export.trace_path_count} "
        f"trace_vertices={export.trace_vertex_count} "
        f"model_mm_per_pixel={export.mm_per_pixel:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
