"""Run a fresh raw-pixel audit using a saved-geometry export JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from app.native_objects import raw_source_responsibility_audit as raw_audit
from PIL import Image


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--geometry-json", type=Path, required=True)
    parser.add_argument("--roi", type=int, nargs=4, required=True)
    parser.add_argument("--source-origin", type=int, nargs=2, default=[0, 0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("Independent evidence output already exists: " + str(args.out))
    payload = json.loads(args.geometry_json.read_text(encoding="utf-8"))
    started = time.perf_counter()
    with Image.open(args.source) as image:
        gray = np.asarray(image.convert("L"))
    result = raw_audit.audit_raw_source_responsibility(
        gray, payload["geometries"], roi_xyxy=args.roi, source_origin_xy=args.source_origin,
        attachment_declarations=payload.get("attachment_declarations", []),
        target_object_ids=payload.get("target_object_ids"),
        source_identity={"source_file_sha256": _sha(args.source)},
    )
    result["execution"] = {
        "source_file": str(args.source), "source_file_sha256": _sha(args.source),
        "geometry_file": str(args.geometry_json), "geometry_file_sha256": _sha(args.geometry_json),
        "module_sha256": _sha(raw_audit.__file__), "runner_sha256": _sha(__file__),
        "wall_seconds": time.perf_counter() - started,
        "new_ocr_calls": 0, "new_model_calls": 0,
        "source_pixels_recomputed_for_this_invocation": True,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"out": str(args.out), "summary": result["summary"],
                      "wall_seconds": result["execution"]["wall_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
