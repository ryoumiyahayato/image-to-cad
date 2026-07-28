from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trace one source pixel through a completed debug bundle."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def _pixel_value(path: Path, x: int, y: int) -> int | list[int] | None:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        return None
    if not (0 <= y < image.shape[0] and 0 <= x < image.shape[1]):
        return None
    value = image[y, x]
    if getattr(value, "ndim", 0) == 0:
        return int(value)
    return [int(item) for item in value.tolist()]


def main() -> int:
    args = _parser().parse_args()
    bundle = args.bundle.resolve()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    width, height = (int(value) for value in manifest["input"]["source_size_px"])
    if not (0 <= args.x < width and 0 <= args.y < height):
        raise ValueError(
            f"Pixel ({args.x}, {args.y}) lies outside {width}x{height}"
        )

    observations = []
    for stage in manifest["stages"]:
        artifact_values = []
        for artifact in stage["artifacts"]:
            metadata = json.loads(
                (bundle / artifact["metadata_path"]).read_text(encoding="utf-8")
            )
            observed_x = args.x
            observed_y = args.y
            region = metadata.get("observation", {}).get("region")
            if isinstance(region, list) and len(region) == 4:
                left, top, right, bottom = (int(value) for value in region)
                if not (
                    left <= args.x < right
                    and top <= args.y < bottom
                ):
                    continue
                observed_x -= left
                observed_y -= top
            value = _pixel_value(
                bundle / artifact["path"],
                observed_x,
                observed_y,
            )
            if value is not None:
                artifact_values.append(
                    {
                        "path": artifact["path"],
                        "role": artifact["role"],
                        "value": value,
                    }
                )
        observations.append(
            {
                "stage_id": stage["stage_id"],
                "stage_name": stage["stage_name"],
                "status": stage["status"],
                "artifact_values": artifact_values,
            }
        )

    lineage_path = bundle / manifest["pixel_lineage"]["path"]
    owner_code = _pixel_value(lineage_path, args.x, args.y)
    codebook = manifest["pixel_lineage"]["codebook"]
    owner = codebook.get(str(owner_code), "unknown")
    result = {
        "bundle": str(bundle),
        "input_sha256": manifest["input"]["sha256"],
        "structure_id": manifest["structure_id"],
        "pixel": [args.x, args.y],
        "final_owner_code": owner_code,
        "final_owner": owner,
        "stages": observations,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
