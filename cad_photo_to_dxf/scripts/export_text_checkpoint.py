"""Export one already repaired text domain and its unchanged CAD neighbors.

This consumes a completed checkpoint. It does not run OCR, propose a string,
reconvert the drawing, clip neighbors, or reuse an old adoption whitelist.
The text must already exist in both the completed source record and saved DXF.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import ezdxf
from ezdxf import bbox
from ezdxf.addons import Importer


APPID = "I2CAD_NATIVE_V2"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def identity(entity):
    if not entity.has_xdata(APPID):
        return None
    data = json.loads(entity.get_xdata(APPID)[0].value)
    return data.get("id")


def normalized(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: normalized(val) for key, val in sorted(value.items())}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return [normalized(item) for item in value]


def signature(entity, *, virtual=False):
    """Compare actual content/geometry, including all referenced block members."""
    attrs = entity.dxfattribs()
    for key in ("handle", "owner"):
        attrs.pop(key, None)
    if not attrs.get("paperspace", 0):
        attrs.pop("paperspace", None)
    result = {"type": entity.dxftype(), "attributes": normalized(attrs)}
    if entity.dxftype() == "LWPOLYLINE":
        result["vertices_xyseb"] = normalized(list(entity.get_points()))
    if entity.dxftype() == "INSERT":
        result["members"] = [signature(item, virtual=True) for item in entity.block()]
    if not virtual:
        result["source_id"] = identity(entity)
    return result


def intersects(extents, box):
    return extents.has_data and not (
        extents.extmax.x < box[0]
        or extents.extmin.x > box[2]
        or extents.extmax.y < box[1]
        or extents.extmin.y > box[3]
    )


def export_checkpoint(checkpoint, object_id, context, out):
    checkpoint = Path(checkpoint).resolve()
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Use a new output directory; preserve earlier artifacts")
    out.mkdir(parents=True, exist_ok=True)
    dxf_path = checkpoint / "result.dxf"
    objects_path = checkpoint / "result.objects.json"
    completed_path = checkpoint / "evidence/source_text_completion/completed_text.json"
    failed_path = checkpoint / "evidence/text/text_regions.json"
    inputs = [dxf_path, objects_path, completed_path, failed_path]
    before_hashes = {str(path): digest(path) for path in inputs}
    objects = read_json(objects_path)
    if digest(dxf_path) != objects["dxf_sha256"]:
        raise ValueError("CHECKPOINT_DXF_HASH_MISMATCH")
    matches = [item for item in objects["objects"] if item["id"] == object_id]
    if len(matches) != 1 or matches[0]["kind"] != "TEXT":
        raise ValueError("TARGET_MUST_BE_ONE_EXISTING_SOURCE_TEXT")
    target = matches[0]
    region_ids = target["source_evidence"]["region_ids"]
    if len(region_ids) != 1:
        raise ValueError("THIS_EXPORT_REQUIRES_ONE_TEXT_SOURCE_REGION")
    region_id = region_ids[0]
    completed = next(r for r in read_json(completed_path)["regions"] if r["id"] == region_id)
    original = next(r for r in read_json(failed_path)["regions"] if r["id"] == region_id)
    separation = completed["source_completion_evidence"]["glyph_neighbor_separation"]
    if not completed["complete"] or not separation["side_decisions"]:
        raise ValueError("MISSING_COMPLETED_SOURCE_DOMAIN_REPAIR")
    if completed["text"] != target["geometry"]["text"]:
        raise ValueError("SAVED_OBJECT_AND_SOURCE_TEXT_DIFFER")
    if any(row["source_or_neighbor_pixels_erased"] for row in separation["side_decisions"]):
        raise ValueError("SOURCE_PIXELS_MUST_REMAIN_UNMODIFIED")
    core = separation["glyph_core_box"]
    if not (context[0] <= core[0] < core[2] <= context[2]
            and context[1] <= core[1] < core[3] <= context[3]):
        raise ValueError("LOCAL_CONTEXT_MUST_INCLUDE_THE_COMPLETE_GLYPH_DOMAIN")

    doc = ezdxf.readfile(dxf_path)
    if int(doc.header["$INSUNITS"]) != 4:
        raise ValueError("PAPER_MILLIMETRE_INPUT_REQUIRED")
    scale = 25.4 / objects["dpi"]
    roi = objects["roi_xyxy_px"]
    box = [(context[0] - roi[0]) * scale, (roi[3] - context[3]) * scale,
           (context[2] - roi[0]) * scale, (roi[3] - context[1]) * scale]
    selected = [entity for entity in doc.modelspace()
                if entity.dxf.layer != "REVIEW"
                and (identity(entity) == object_id
                     or intersects(bbox.extents([entity]), box))]
    targets = [entity for entity in selected if identity(entity) == object_id]
    if len(targets) != 1 or targets[0].dxftype() != "TEXT":
        raise ValueError("ACTUAL_SAVED_TEXT_MUST_BE_UNIQUE")
    if targets[0].dxf.text != completed["text"]:
        raise ValueError("ACTUAL_DXF_CONTENT_DIFFERS_FROM_SOURCE_CHECKPOINT")
    if any(entity.dxftype() not in {"TEXT", "LINE", "ARC", "LWPOLYLINE", "INSERT"}
           for entity in selected):
        raise ValueError("UNREVIEWED_ENTITY_TYPE_IN_LOCAL_CONTEXT")

    local = ezdxf.new(doc.dxfversion)
    local.units = doc.units
    local.header["$MEASUREMENT"] = doc.header.get("$MEASUREMENT", 1)
    importer = Importer(doc, local)
    importer.import_entities(selected)
    importer.finalize()
    if APPID not in local.appids:
        local.appids.new(APPID)
    imported = list(local.modelspace())
    if len(imported) != len(selected):
        raise ValueError("IMPORT_CHANGED_LOCAL_ENTITY_COUNT")
    for source, copied in zip(selected, imported):
        if source.has_xdata(APPID):
            copied.set_xdata(APPID, source.get_xdata(APPID))
    expected = [signature(entity) for entity in selected]
    if expected != [signature(entity) for entity in imported]:
        raise ValueError("IMPORT_CHANGED_TEXT_OR_NEIGHBOR_GEOMETRY")
    output = out / "pantry_local_fixed.dxf"
    local.saveas(output)
    reread = ezdxf.readfile(output)
    actual = [signature(entity) for entity in reread.modelspace()]
    if expected != actual:
        raise ValueError("SAVED_LOCAL_FILE_CHANGED_TEXT_OR_NEIGHBORS")
    audit = reread.audit()
    if audit.errors or audit.fixes:
        raise ValueError("SAVED_LOCAL_DXF_REQUIRES_REPAIR")
    if before_hashes != {str(path): digest(path) for path in inputs}:
        raise ValueError("INPUT_CHECKPOINT_CHANGED_DURING_EXPORT")
    for name in ("DejaVuSans.ttf", "FONT_LICENSE_DejaVu.txt"):
        shutil.copy2(checkpoint / name, out / name)
    receipt = {
        "schema": "single-repaired-text-checkpoint-export-v1",
        "status": "PASS_LOCAL_SAVE_READBACK_WITH_EXPLICIT_SCOPE",
        "source_object_id": object_id,
        "source_region_id": region_id,
        "original_mixed_scope_text_preserved": original["text"],
        "original_mixed_scope_complete": original["complete"],
        "saved_TEXT_content_read_from_DXF": targets[0].dxf.text,
        "source_domain_repair": separation,
        "context_bbox_source_px": context,
        "context_bbox_paper_mm": box,
        "unit": "paper_mm_not_architectural_scale",
        "selected_entity_count": len(selected),
        "selected_entity_types": dict(Counter(entity.dxftype() for entity in selected)),
        "neighbor_entity_count": len(selected) - 1,
        "all_selected_entities_copied_whole_without_clipping": True,
        "neighbor_attributes_and_block_members_unchanged": True,
        "text_content_height_position_width_and_style_unchanged": True,
        "save_readback_entities_exact_at_1e_minus_9_mm": True,
        "ezdxf_audit_errors": 0,
        "ezdxf_audit_repairs": 0,
        "new_OCR_or_model_calls": 0,
        "new_source_conversion": False,
        "new_automatic_adoption_decision": False,
        "original_checkpoint_unchanged": True,
        "input_hashes": before_hashes,
        "selected_source_entities": [
            {"handle": entity.dxf.handle, "source_id": identity(entity),
             "type": entity.dxftype(), "layer": entity.dxf.layer}
            for entity in selected
        ],
        "local_DXF_sha256": digest(output),
        "export_code_sha256": digest(__file__),
        "local_GUI_edit_test": "NOT_RUN_THIS_EXPORT",
    }
    (out / "local_save_readback.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: receipt[key] for key in (
        "status", "saved_TEXT_content_read_from_DXF", "selected_entity_types",
        "neighbor_entity_count", "local_DXF_sha256", "new_OCR_or_model_calls"
    )}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--context", type=int, nargs=4, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    export_checkpoint(args.checkpoint, args.object_id, args.context, args.out)


if __name__ == "__main__":
    main()
