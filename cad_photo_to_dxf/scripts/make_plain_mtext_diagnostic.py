"""Make an explicitly layout-failing plain MTEXT copy for ordinary CAD tests.

This cannot replace the source-preserving deliverable. It tests native editing
in consumers that display paragraph/width controls literally. It accepts no
replacement string and does not change source evidence or neighboring objects.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import ezdxf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.native_objects.cad_io import identity, save_native_dxf
from export_annotation_group_checkpoint import snapshot, unchanged_neighbors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve previous diagnostic and GUI saves")
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    doc = ezdxf.readfile(args.source)
    before = snapshot(doc, args.target_id)
    matches = [e for e in doc.modelspace()
               if e.has_xdata("I2CAD_NATIVE_V2")
               and identity(e).get("id") == args.target_id]
    if len(matches) != 1 or matches[0].dxftype() != "MTEXT":
        raise ValueError("REQUIRES_ONE_EXISTING_NATIVE_MTEXT")
    entity = matches[0]
    original_attributes = entity.dxfattribs()
    plain = entity.plain_text()
    entity.text = r"\P".join(plain.splitlines())
    if entity.dxfattribs() != original_attributes:
        raise ValueError("DIAGNOSTIC_MUST_KEEP_MTEXT_GEOMETRY_AND_STYLE")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_native_dxf(doc, args.output)
    cold = ezdxf.readfile(args.output)
    unchanged_neighbors(snapshot(cold, args.target_id), before, args.target_id)
    saved = cold.modelspace().query("MTEXT")
    target = next(e for e in saved if identity(e).get("id") == args.target_id)
    if target.plain_text() != plain:
        raise ValueError("DIAGNOSTIC_MUST_NOT_CHANGE_PLAIN_CONTENT")
    if source_hash != hashlib.sha256(args.source.read_bytes()).hexdigest():
        raise ValueError("SOURCE_DELIVERABLE_CHANGED")
    receipt = {
        "profile": "LIBRECAD_PLAIN_DIAGNOSTIC",
        "source": str(args.source.resolve()), "source_sha256": source_hash,
        "output": str(args.output.resolve()),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "target_id": args.target_id, "derived_plain_text": plain,
        "single_native_MTEXT": True, "neighbor_entities_unchanged": True,
        "source_layout_preserved": False,
        "per_line_width_and_indent": "UNSUPPORTED",
        "original_source_audit_inherited": False,
        "LibreCAD_layout": "FAILED", "overall_task": "NOT_PASSED",
        "product_status": "LOCAL_NO_GO", "recognition_calls": 0,
    }
    args.output.with_suffix(".diagnostic.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
