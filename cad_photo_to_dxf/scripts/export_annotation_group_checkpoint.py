"""Export one complete adjudicated annotation and unchanged saved neighbors.

This bounded checkpoint consumer runs no OCR or regional conversion. It keeps
the saved CAD coordinates and copies every selected neighbor whole. A complete
source-bound group is mandatory; incomplete rows cannot become a partial note.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import ezdxf
from ezdxf import bbox
from ezdxf.addons import Importer
import numpy as np
from PIL import Image


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.native_objects import cad_io
from app.native_objects.pipeline import _text_objects
from app.native_objects.text_regions import source_array_sha256


APPID = cad_io.APPID


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalized(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: normalized(val) for key, val in sorted(value.items())}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return [normalized(item) for item in value]


def identity(entity):
    if not entity.has_xdata(APPID):
        return None
    return json.loads(entity.get_xdata(APPID)[0].value).get("id")


def attributes(entity):
    values = entity.dxfattribs()
    for key in ("handle", "owner"):
        values.pop(key, None)
    if not values.get("paperspace", 0):
        values.pop("paperspace", None)
    return normalized(values)


def signature(entity, stack=()):
    result = {
        "type": entity.dxftype(),
        "attributes": attributes(entity),
        "xdata": {
            appid: normalized([(tag.code, tag.value) for tag in entity.get_xdata(appid)])
            for appid in sorted(entity.xdata.data if entity.xdata else ())
        },
    }
    if entity.dxftype() == "LWPOLYLINE":
        result["vertices_xyseb"] = normalized(list(entity.get_points()))
    if entity.dxftype() in {"TEXT", "MTEXT"}:
        result["style"] = attributes(entity.doc.styles.get(entity.dxf.style))
    if entity.dxftype() == "MTEXT":
        result["content"] = entity.text
        result["plain_text"] = entity.plain_text()
    if entity.dxftype() == "INSERT":
        name = entity.dxf.name
        if name in stack:
            raise ValueError("CYCLIC_BLOCK_REFERENCE")
        result["block_definition"] = attributes(entity.block().block)
        result["members"] = [signature(item, stack + (name,)) for item in entity.block()]
        result["attached_attributes"] = [signature(item, stack) for item in entity.attribs]
    return result


def layers_used(entities):
    result = set()
    for entity in entities:
        result.add(entity.dxf.layer)
        if entity.dxftype() == "INSERT":
            result.update(layers_used(entity.block()))
            result.update(layers_used(entity.attribs))
    return result


def snapshot(doc, target_id, entities=None):
    entities = list(doc.modelspace() if entities is None else entities)
    ids = [identity(entity) for entity in entities]
    if any(value is None for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("LOCAL_ENTITY_IDENTITIES_MUST_BE_PRESENT_AND_UNIQUE")
    target = [entity for entity in entities if identity(entity) == target_id]
    if len(target) > 1 or (target and target[0].dxftype() != "MTEXT"):
        raise ValueError("TARGET_MUST_BE_ONE_NATIVE_MTEXT")
    return {
        "dxfversion": doc.dxfversion,
        "units": doc.units,
        "entities": {identity(entity): signature(entity) for entity in entities},
        "types": dict(Counter(entity.dxftype() for entity in entities)),
        "layers": {name: attributes(doc.layers.get(name)) for name in sorted(layers_used(entities))},
        "target_count": len(target),
    }


def preserve_defaults(source, destination, names):
    values = source.dxfattribs()
    for name in names:
        if name in values:
            destination.dxf.set(name, values[name])
        else:
            destination.dxf.discard(name)


def restore_xdata(source, destination):
    for appid in source.xdata.data if source.xdata else ():
        if appid not in destination.doc.appids:
            destination.doc.appids.new(appid)
        destination.set_xdata(appid, source.get_xdata(appid))
    if source.dxftype() == "INSERT":
        preserve_defaults(source.block().block, destination.block().block, ("layer", "description"))
        old, new = list(source.block()), list(destination.block())
        if len(old) != len(new) or len(source.attribs) != len(destination.attribs):
            raise ValueError("IMPORT_CHANGED_BLOCK_OR_ATTRIBUTE_COUNT")
        for first, second in zip(old, new):
            restore_xdata(first, second)
        for first, second in zip(source.attribs, destination.attribs):
            restore_xdata(first, second)


def import_whole(source_doc, entities, destination):
    start = len(destination.modelspace())
    importer = Importer(source_doc, destination)
    importer.import_entities(entities)
    importer.finalize()
    copied = list(destination.modelspace())[start:]
    if len(copied) != len(entities):
        raise ValueError("IMPORT_CHANGED_SELECTED_ENTITY_COUNT")
    for source, target in zip(entities, copied):
        restore_xdata(source, target)
    for name in layers_used(entities):
        preserve_defaults(source_doc.layers.get(name), destination.layers.get(name),
                          ("flags", "lineweight", "linetype", "color", "plot"))
    if [signature(entity) for entity in entities] != [signature(entity) for entity in copied]:
        raise ValueError("IMPORT_CHANGED_ENTITY_BLOCK_FONT_OR_XDATA")
    return copied


def intersects(extents, box):
    return extents.has_data and not (
        extents.extmax.x < box[0] or extents.extmin.x > box[2]
        or extents.extmax.y < box[1] or extents.extmin.y > box[3]
    )


def cold_read(path, target_id):
    doc = ezdxf.readfile(path)
    result = snapshot(doc, target_id)
    audit = doc.audit()
    result.update(file_sha256=digest(path), audit_errors=len(audit.errors), audit_repairs=len(audit.fixes))
    return result


def independent_cold_read(path, target_id):
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--cold-read", str(path), "--group-id", target_id],
        check=True, capture_output=True, text=True, timeout=45,
    )
    result = json.loads(process.stdout)
    if result["audit_errors"] or result["audit_repairs"]:
        raise ValueError("SAVED_DXF_REQUIRES_AUDIT_REPAIR")
    return result


def unchanged_neighbors(actual, expected, target_id):
    old = {key: value for key, value in expected["entities"].items() if key != target_id}
    new = {key: value for key, value in actual["entities"].items() if key != target_id}
    if old != new:
        raise ValueError("NEIGHBOR_CONTENT_GEOMETRY_FONT_OR_XDATA_CHANGED")
    if any(actual[key] != expected[key] for key in ("units", "dxfversion")):
        raise ValueError("UNITS_OR_DXF_VERSION_CHANGED")
    for name, value in expected["layers"].items():
        if actual["layers"].get(name) != value:
            raise ValueError("NEIGHBOR_LAYER_CHANGED")


def completed_group(updated, baseline, group_id):
    groups = [group for group in updated["groups"] if group["id"] == group_id]
    if len(groups) != 1 or groups[0].get("complete") is not True:
        raise ValueError("WHOLE_ANNOTATION_GROUP_MUST_BE_COMPLETE")
    group = groups[0]
    region_ids = group["region_ids"]
    if len(region_ids) < 2 or len(region_ids) != len(set(region_ids)):
        raise ValueError("MTEXT_REQUIRES_DISTINCT_ORDERED_SOURCE_ROWS")
    by_id = {row["id"]: row for row in updated["regions"]}
    rows = [by_id[rid] for rid in region_ids]
    if any(row.get("complete") is not True for row in rows):
        raise ValueError("INCOMPLETE_ROW_PREVENTS_WHOLE_GROUP_EXPORT")
    lines = [row["text"] for row in rows]
    if (group["text"].splitlines() != lines
            or [row["region_id"] for row in group["lines"]] != region_ids
            or [row["text"] for row in group["lines"]] != lines):
        raise ValueError("GROUP_LINE_ORDER_OR_CONTENT_DIFFERS_FROM_SOURCE_ROWS")
    original = {row["id"]: row for row in baseline["regions"]}
    if any(rid not in original for rid in region_ids):
        raise ValueError("GROUP_SOURCE_ROWS_NOT_IN_FROZEN_CHECKPOINT")
    if any(row["bbox_xyxy_px"] != original[row["id"]]["bbox_xyxy_px"] for row in rows):
        raise ValueError("LOCAL_ADJUDICATION_MUST_KEEP_BOUND_SOURCE_ROW_GEOMETRY")
    if any(row.get("words") != original[row["id"]].get("words") for row in rows):
        raise ValueError("RAW_WORD_OBSERVATIONS_MUST_REMAIN_UNCHANGED")
    return group, rows


def check_adjudication(updated, group, source_file_sha256):
    from app.native_objects.source_glyph_resolution import receipt_digest

    receipt = updated.get("source_glyph_resolution_receipt", {})
    group_binding = group.get("source_glyph_adjudication", {})
    status = "ACCEPTED_SOURCE_GLYPH_ADJUDICATION"
    if (receipt.get("schema") != "source_glyph_resolution_v1"
            or receipt.get("accepted") is not True or receipt.get("status") != status
            or group_binding.get("accepted") is not True or group_binding.get("status") != status
            or receipt.get("group_id") != group["id"]
            or receipt.get("source_array_sha256") != updated["source_array_sha256"]
            or receipt.get("source_file_sha256") != source_file_sha256
            or receipt.get("recognition_calls") != 0
            or receipt.get("raw_observations_changed") is not False):
        raise ValueError("COMPLETE_GROUP_REQUIRES_BOUND_SOURCE_GLYPH_ADJUDICATION")
    actual_digest = receipt_digest(receipt)
    if receipt.get("receipt_sha256") != actual_digest or group_binding.get("receipt_sha256") != actual_digest:
        raise ValueError("SOURCE_GLYPH_ADJUDICATION_RECEIPT_HASH_MISMATCH")
    rows = {row["id"]: row for row in updated["regions"]}
    region_ids = group["region_ids"]
    if (receipt.get("ordered_region_ids") != region_ids
            or receipt.get("resolved_group_text") != group["text"]
            or receipt.get("resolved_region_texts") != {rid: rows[rid]["text"] for rid in region_ids}
            or receipt.get("source_region_bboxes") != {rid: rows[rid]["bbox_xyxy_px"] for rid in region_ids}):
        raise ValueError("EXPORTED_CONTENT_OR_LAYOUT_DIFFERS_FROM_ADJUDICATION_RECEIPT")
    return receipt


def export_checkpoint(checkpoint, updated_path, group_id, source_image, context, out, move_mm=(6.0, 4.0)):
    checkpoint, updated_path = Path(checkpoint).resolve(), Path(updated_path).resolve()
    source_image, out = Path(source_image).resolve(), Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Use a new output directory; preserve existing artifacts")
    dxf_path = checkpoint / "result.dxf"
    objects_path = checkpoint / "result.objects.json"
    completed_path = checkpoint / "evidence/source_text_completion/completed_text.json"
    inputs = [dxf_path, objects_path, completed_path, updated_path, source_image]
    hashes = {str(path): digest(path) for path in inputs}
    manifest, baseline, updated = map(read_json, (objects_path, completed_path, updated_path))
    if hashes[str(dxf_path)] != manifest["dxf_sha256"]:
        raise ValueError("CHECKPOINT_DXF_HASH_MISMATCH")
    if hashes[str(source_image)] != manifest["source_sha256"]:
        raise ValueError("FROZEN_SOURCE_FILE_HASH_MISMATCH")
    image = np.asarray(Image.open(source_image).convert("L"))
    if source_array_sha256(image) != updated["source_array_sha256"]:
        raise ValueError("UPDATED_TEXT_SOURCE_ARRAY_HASH_MISMATCH")
    if updated["source_array_sha256"] != baseline["source_array_sha256"] or updated["roi_xyxy_px"] != manifest["roi_xyxy_px"]:
        raise ValueError("UPDATED_TEXT_SOURCE_OR_ROI_DIFFERS_FROM_CHECKPOINT")
    if updated.get("source_pixels_modified") is not False:
        raise ValueError("ADJUDICATION_MUST_KEEP_ORIGINAL_SOURCE_PIXELS")
    group, rows = completed_group(updated, baseline, group_id)
    adjudication = check_adjudication(updated, group, hashes[str(source_image)])
    bounds = group["bbox_xyxy_px"]
    if not (context[0] <= bounds[0] < bounds[2] <= context[2]
            and context[1] <= bounds[1] < bounds[3] <= context[3]):
        raise ValueError("CONTEXT_MUST_INCLUDE_WHOLE_ANNOTATION_GROUP")
    region_ids = set(group["region_ids"])
    for obj in manifest["objects"]:
        if obj["id"] == group_id or region_ids.intersection(obj.get("source_evidence", {}).get("region_ids", [])):
            raise ValueError("TARGET_SOURCE_ALREADY_HAS_A_FORMAL_OBJECT")
    limited = {**updated, "groups": [copy.deepcopy(group)], "regions": copy.deepcopy(rows)}
    targets, issues = _text_objects(limited, set(), set(), image)
    if len(targets) != 1 or issues or targets[0]["kind"] != "MTEXT":
        raise ValueError("SOURCE_GROUP_DID_NOT_ASSEMBLE_ONE_COMPLETE_MTEXT")
    if targets[0]["geometry"]["lines"] != [row["text"] for row in rows]:
        raise ValueError("ASSEMBLY_CHANGED_ORDERED_SOURCE_CONTENT")
    source_doc = ezdxf.readfile(dxf_path)
    if source_doc.units != 4 or manifest["unit"] != "paper_mm":
        raise ValueError("CHECKPOINT_MUST_USE_PAPER_MILLIMETRES")
    roi, dpi = manifest["roi_xyxy_px"], manifest["dpi"]
    scale = 25.4 / dpi
    box = [(context[0] - roi[0]) * scale, (roi[3] - context[3]) * scale,
           (context[2] - roi[0]) * scale, (roi[3] - context[1]) * scale]
    selected = [entity for entity in source_doc.modelspace()
                if entity.dxf.layer != "REVIEW" and intersects(bbox.extents([entity]), box)]
    expected = snapshot(source_doc, group_id, selected)
    if expected["target_count"]:
        raise ValueError("SAVED_CHECKPOINT_ALREADY_CONTAINS_TARGET")
    local = ezdxf.new(source_doc.dxfversion)
    local.units = source_doc.units
    local.header["$MEASUREMENT"] = source_doc.header.get("$MEASUREMENT", 1)
    import_whole(source_doc, selected, local)
    if snapshot(local, group_id) != expected:
        raise ValueError("LOCAL_BEFORE_COPY_CHANGED_CHECKPOINT")
    out.mkdir(parents=True, exist_ok=True)
    before_path = out / "before.dxf"
    cad_io.save_native_dxf(local, before_path)
    before = independent_cold_read(before_path, group_id)
    unchanged_neighbors(before, expected, group_id)

    evidence = out / "evidence"
    target_path = evidence / "assembled_target.dxf"
    target_meta = cad_io.export_objects(targets, target_path, roi, dpi, manifest["source_sha256"])
    if target_meta["font"]["sha256"] != manifest["font"]["sha256"]:
        raise ValueError("CURRENT_WRITER_FONT_DIFFERS_FROM_CHECKPOINT_FONT")
    for name in (manifest["font"]["font"], manifest["font"]["bundled_license"]):
        shutil.copy2(checkpoint / name, out / name)
    if digest(out / manifest["font"]["font"]) != manifest["font"]["sha256"]:
        raise ValueError("COPIED_SOURCE_FONT_HASH_MISMATCH")
    target_doc = ezdxf.readfile(target_path)
    generated = [entity for entity in target_doc.modelspace() if identity(entity) == group_id]
    if len(generated) != 1 or generated[0].dxftype() != "MTEXT":
        raise ValueError("WRITER_DID_NOT_SAVE_ONE_MTEXT")
    import_whole(target_doc, generated, local)
    restored_path = out / "restored.dxf"
    cad_io.save_native_dxf(local, restored_path)
    restored = independent_cold_read(restored_path, group_id)
    unchanged_neighbors(restored, expected, group_id)
    restored_target = restored["entities"][group_id]
    if restored["target_count"] != 1 or restored_target["plain_text"].splitlines() != [row["text"] for row in rows]:
        raise ValueError("SAVED_MTEXT_CONTENT_OR_ENTITY_COUNT_CHANGED")
    if len(restored["entities"]) != len(expected["entities"]) + 1:
        raise ValueError("RESTORATION_CREATED_UNEXPECTED_ENTITIES")

    translation = [float(move_mm[0]), float(move_mm[1]), 0.0]
    moved_doc = ezdxf.readfile(restored_path)
    moved_target = next(entity for entity in moved_doc.modelspace() if identity(entity) == group_id)
    moved_target.translate(*translation)
    moved_path = out / "moved.dxf"
    cad_io.save_native_dxf(moved_doc, moved_path)
    moved = independent_cold_read(moved_path, group_id)
    unchanged_neighbors(moved, expected, group_id)
    moved_signature = copy.deepcopy(moved["entities"][group_id])
    old_position = restored_target["attributes"]["insert"]
    if any(abs(moved_signature["attributes"]["insert"][i] - old_position[i] - translation[i]) > 1e-8 for i in range(3)):
        raise ValueError("WHOLE_NOTE_DID_NOT_MOVE_BY_REQUESTED_VECTOR")
    moved_signature["attributes"]["insert"] = old_position
    if moved_signature != restored_target:
        raise ValueError("MOVE_CHANGED_TEXT_LAYOUT_OR_NON_POSITION_ATTRIBUTES")

    deleted_doc = ezdxf.readfile(restored_path)
    deleted_target = next(entity for entity in deleted_doc.modelspace() if identity(entity) == group_id)
    deleted_doc.modelspace().delete_entity(deleted_target)
    deleted_path = out / "deleted.dxf"
    cad_io.save_native_dxf(deleted_doc, deleted_path)
    deleted = independent_cold_read(deleted_path, group_id)
    unchanged_neighbors(deleted, expected, group_id)
    if deleted["target_count"] or deleted["entities"] != before["entities"]:
        raise ValueError("DELETE_LEFT_TARGET_OR_CHANGED_NEIGHBORS")
    if hashes != {path: digest(path) for path in hashes}:
        raise ValueError("INPUT_CHECKPOINT_OR_SOURCE_WAS_CHANGED")
    outputs = {}
    for name, path, result in (("before", before_path, before), ("restored", restored_path, restored),
                               ("moved", moved_path, moved), ("deleted", deleted_path, deleted)):
        outputs[name] = {"path": str(path), "sha256": result["file_sha256"], "types": result["types"],
                         "target_count": result["target_count"], "audit_errors": result["audit_errors"],
                         "audit_repairs": result["audit_repairs"]}
    receipt = {
        "schema": "local-annotation-group-checkpoint-v1",
        "status": "PASS_LOCAL_COMPLETE_MTEXT_MOVE_DELETE_AND_PROCESS_COLD_READ",
        "group_id": group_id, "source_region_ids": group["region_ids"],
        "source_glyph_resolution_receipt_sha256": adjudication["receipt_sha256"],
        "input_hashes": hashes, "code_sha256": digest(__file__),
        "assembly_writer_code_sha256": digest(cad_io.__file__),
        "context_source_xyxy_px": list(context), "context_paper_mm": box,
        "roi_xyxy_px": roi, "dpi": dpi, "unit": "paper_mm",
        "neighbor_ids": list(expected["entities"]), "neighbor_count": len(expected["entities"]),
        "translation_mm": translation, "outputs": outputs,
        "ordered_source_rows": [{"id": row["id"], "text": row["text"], "bbox_xyxy_px": row["bbox_xyxy_px"]} for row in rows],
        "assembled_geometry": targets[0]["geometry"],
        "saved_mtext_signature": restored_target,
        "checks": {
            "all_rows_complete_and_source_bound": True,
            "one_true_mtext_has_all_lines_in_source_order": True,
            "no_preexisting_formal_object_claims_target_source": True,
            "all_neighbors_copied_whole_without_clipping": True,
            "neighbors_geometry_blocks_fonts_layers_xdata_unchanged": True,
            "delete_returns_exact_before_entity_content": True,
            "all_four_files_cold_read_in_new_processes": True,
            "all_four_files_audit_zero_errors_and_repairs": True,
            "original_source_and_checkpoint_unchanged": True,
        },
        "OCR_calls": 0, "model_calls": 0, "regional_conversion_run": False,
        "GUI_validation": "NOT_RUN_BY_THIS_SCRIPT",
        "engineer_UAT": "NOT_RUN", "product_status": "LOCAL_NO_GO",
        "edited_files_do_not_inherit_original_audit": True,
    }
    (out / "local_edit_check.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--updated-text", type=Path)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--source-image", type=Path)
    parser.add_argument("--context", type=int, nargs=4)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--move-mm", type=float, nargs=2, default=[6.0, 4.0])
    parser.add_argument("--cold-read", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cold_read:
        print(json.dumps(cold_read(args.cold_read, args.group_id)))
        return
    if any(value is None for value in (args.checkpoint_dir, args.updated_text, args.source_image, args.context, args.out_dir)):
        parser.error("--checkpoint-dir, --updated-text, --source-image, --context and --out-dir are required")
    receipt = export_checkpoint(args.checkpoint_dir, args.updated_text, args.group_id,
                                args.source_image, args.context, args.out_dir, args.move_mm)
    print(json.dumps({key: receipt[key] for key in ("status", "group_id", "neighbor_count", "outputs")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
