"""Recheck one saved annotation group against original pixels, without OCR.

The group ID selects existing evidence; it supplies no transcription answer.
The output contains only that group's derived contract and a bound receipt.
Use export_annotation_group_checkpoint.py for the actual local DXF afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.native_objects.source_glyph_resolution import resolve_group_from_source


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def resolve_checkpoint(checkpoint, source, group_id, output):
    checkpoint, source, output = map(lambda p: Path(p).resolve(),
                                      (checkpoint, source, output))
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Preserve earlier evidence; use a new output directory")
    text_path = checkpoint / "evidence/source_text_completion/completed_text.json"
    index_path = checkpoint / "evidence/source_text_completion/text_confirmation_index.json"
    objects_path = checkpoint / "result.objects.json"
    dxf_path = checkpoint / "result.dxf"
    manifest_path = checkpoint / "publication_manifest.json"
    inputs = [source, text_path, index_path, objects_path, dxf_path, manifest_path]
    hashes = {str(path): file_sha(path) for path in inputs}
    manifest = json.loads(manifest_path.read_text())
    for path in (text_path, index_path, objects_path, dxf_path):
        record = manifest.get("files", {}).get(path.relative_to(checkpoint).as_posix(), {})
        if record.get("sha256") != hashes[str(path)] or record.get("bytes") != path.stat().st_size:
            raise ValueError("PUBLISHED_CHECKPOINT_FILE_BINDING_MISMATCH:" + path.name)
    if manifest.get("identity", {}).get("source_sha256") != hashes[str(source)]:
        raise ValueError("PUBLISHED_CHECKPOINT_SOURCE_BINDING_MISMATCH")
    objects = json.loads(objects_path.read_text())
    if hashes[str(dxf_path)] != objects["dxf_sha256"]:
        raise ValueError("CHECKPOINT_DXF_IDENTITY_MISMATCH")
    if hashes[str(source)] != objects["source_sha256"]:
        raise ValueError("CHECKPOINT_SOURCE_FILE_IDENTITY_MISMATCH")
    text_data = json.loads(text_path.read_text())
    confirmation = json.loads(index_path.read_text())
    with Image.open(source) as im:
        image = np.asarray(im.convert("L"))
    updated, receipt = resolve_group_from_source(
        image, text_data, confirmation, group_id,
        source_file_sha256=hashes[str(source)],
    )
    group = next(g for g in updated["groups"] if g["id"] == group_id)
    members = set(group["region_ids"])
    local_contract = {
        key: updated[key] for key in (
            "schema", "schema_version", "coordinate_system", "source_size_px",
            "roi_xyxy_px", "source_array_sha256", "source_pixels_modified",
        ) if key in updated
    }
    local_contract.update(
        regions=[row for row in updated["regions"] if row["id"] in members],
        groups=[group], source_glyph_resolution_receipt=receipt,
    )
    if hashes != {str(path): file_sha(path) for path in inputs}:
        raise ValueError("FROZEN_INPUT_CHANGED_DURING_LOCAL_RECHECK")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "updated_text.json", local_contract)
    write_json(output / "source_adjudication.json", receipt)
    write_json(output / "run_binding.json", {
        "schema": "single_annotation_source_recheck_v1",
        "group_id": group_id, "input_hashes": hashes,
        "source_group_bbox_px": group["bbox_xyxy_px"],
        "code_sha256": {
            str(Path(__file__).name): file_sha(__file__),
            "source_glyph_resolution.py": file_sha(
                Path(__file__).resolve().parents[1] /
                "app/native_objects/source_glyph_resolution.py"),
            "text_glyph_adjudication.py": file_sha(
                Path(__file__).resolve().parents[1] /
                "app/native_objects/text_glyph_adjudication.py"),
        },
        "status": receipt["status"], "accepted": receipt["accepted"],
        "published_checkpoint_hashes_verified": True,
        "recognition_calls": 0, "full_region_conversion_run": False,
        "unchanged_input_hashes_rechecked": True,
        "product_status": "LOCAL_NO_GO",
    })
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = resolve_checkpoint(args.checkpoint_dir, args.source_image,
                                args.group_id, args.out_dir)
    print(json.dumps({key: result.get(key) for key in (
        "status", "accepted", "changed", "reasons", "resolved_group_text",
        "receipt_sha256",
    )}, ensure_ascii=False))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
