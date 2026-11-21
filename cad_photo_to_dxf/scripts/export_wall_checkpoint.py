"""Export and cold-check one existing source-supported wall and its neighbors.

This is a checkpoint/export tool, not a recognizer or a reconstruction stage.
It does not create wall members, change source ownership, run OCR, or certify
that other nearby strokes belong to the target. That responsibility review
must accompany this tool's limited whole-object editing evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

import ezdxf
from ezdxf import bbox
from ezdxf.addons import Importer

from export_text_checkpoint import digest, identity, intersects, normalized, read_json


def attributes(value):
    data = value.dxfattribs()
    for name in ("handle", "owner"):
        data.pop(name, None)
    if not data.get("paperspace", 0):
        data.pop("paperspace", None)
    return normalized(data)


def xdata(entity):
    return {
        appid: normalized([(tag.code, tag.value) for tag in entity.get_xdata(appid)])
        for appid in sorted(entity.xdata.data if entity.xdata else ())
    }


def entity_signature(entity, stack=()):
    result = {"type": entity.dxftype(), "attributes": attributes(entity),
              "xdata": xdata(entity)}
    if entity.dxftype() == "LWPOLYLINE":
        result["vertices_xyseb"] = normalized(list(entity.get_points()))
    if entity.dxftype() in {"TEXT", "MTEXT"}:
        result["style"] = attributes(entity.doc.styles.get(entity.dxf.style))
    if entity.dxftype() == "INSERT":
        name = entity.dxf.name
        if name in stack:
            raise ValueError("CYCLIC_BLOCK_REFERENCE")
        block = entity.block()
        result["block_definition"] = attributes(block.block)
        result["members"] = [entity_signature(item, stack + (name,)) for item in block]
        result["attributes"] = attributes(entity)
        result["attached_attributes"] = [entity_signature(item, stack) for item in entity.attribs]
    return result


def used_layers(entities):
    result = set()
    for entity in entities:
        result.add(entity.dxf.layer)
        if entity.dxftype() == "INSERT":
            result.update(used_layers(entity.block()))
            result.update(used_layers(entity.attribs))
    return result


def block_reference_count(entities, block_name, stack=()):
    count = 0
    for entity in entities:
        if entity.dxftype() != "INSERT":
            continue
        name = entity.dxf.name
        if name in stack:
            raise ValueError("CYCLIC_BLOCK_REFERENCE")
        count += name == block_name
        count += block_reference_count(entity.block(), block_name, stack + (name,))
    return count


def world_members(entity):
    """Expand the actual INSERT transform, rather than trusting a block name."""
    result = []
    for member in entity.virtual_entities():
        if member.dxftype() != "LINE":
            raise ValueError("THIS_WALL_CHECK_REQUIRES_SOURCE_LINE_MEMBERS")
        result.append({"type": "LINE", "start": list(member.dxf.start),
                       "end": list(member.dxf.end)})
    return result


def snapshot(doc, target_id, target_block_name, entities=None):
    entities = list(doc.modelspace() if entities is None else entities)
    ids = [identity(entity) for entity in entities]
    if any(value is None for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("VISIBLE_ENTITY_IDENTITIES_MUST_BE_PRESENT_AND_UNIQUE")
    targets = [entity for entity in entities if identity(entity) == target_id]
    if len(targets) > 1 or (targets and targets[0].dxftype() != "INSERT"):
        raise ValueError("TARGET_MUST_BE_ONE_INSERT")
    return {
        "dxfversion": doc.dxfversion,
        "units": doc.units,
        "entities": {identity(entity): entity_signature(entity) for entity in entities},
        "types": dict(Counter(entity.dxftype() for entity in entities)),
        "layers": {name: attributes(doc.layers.get(name)) for name in sorted(used_layers(entities))},
        "target_count": len(targets),
        "target_world_members": world_members(targets[0]) if targets else [],
        "visible_target_block_references": block_reference_count(entities, target_block_name),
    }


def cold_read(path, target_id, target_block_name):
    doc = ezdxf.readfile(path)
    result = snapshot(doc, target_id, target_block_name)
    audit = doc.audit()
    result["audit_errors"] = len(audit.errors)
    result["audit_repairs"] = len(audit.fixes)
    result["file_sha256"] = digest(path)
    return result


def independent_cold_read(path, target_id, block_name):
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--cold-read", str(path),
         "--object-id", target_id, "--target-block", block_name],
        check=True, capture_output=True, text=True, timeout=45,
    )
    result = json.loads(process.stdout)
    if result["audit_errors"] or result["audit_repairs"]:
        raise ValueError("SAVED_DXF_REQUIRES_AUDIT_REPAIR")
    return result


def preserve_explicit_defaults(source, destination, names):
    """Keep source field presence when Importer substitutes DXF defaults.

    Resource handles and identities remain owned by Importer. Only these
    value fields are restored; the subsequent full signatures stay strict.
    """
    values = source.dxfattribs()
    for name in names:
        if name in values:
            destination.dxf.set(name, values[name])
        else:
            destination.dxf.discard(name)


def copy_xdata(source, destination):
    for appid in source.xdata.data if source.xdata else ():
        if appid not in destination.doc.appids:
            destination.doc.appids.new(appid)
        destination.set_xdata(appid, source.get_xdata(appid))
    if source.dxftype() == "INSERT":
        preserve_explicit_defaults(source.block().block, destination.block().block,
                                   ("layer", "description"))
        old_members, new_members = list(source.block()), list(destination.block())
        if len(old_members) != len(new_members):
            raise ValueError("IMPORT_CHANGED_BLOCK_MEMBER_COUNT")
        for old, new in zip(old_members, new_members):
            copy_xdata(old, new)
        if len(source.attribs) != len(destination.attribs):
            raise ValueError("IMPORT_CHANGED_ATTACHED_ATTRIBUTE_COUNT")
        for old, new in zip(source.attribs, destination.attribs):
            copy_xdata(old, new)


def source_members_in_mm(target, roi, scale):
    result = []
    for member in target["geometry"]["members"]:
        if member["kind"] != "LINE":
            raise ValueError("THIS_EXPORT_REQUIRES_LINE_BASED_WALL_GEOMETRY")
        points = {}
        for end in ("start", "end"):
            x, y = member["geometry"][end]
            points[end] = [(x - roi[0]) * scale, (roi[3] - y) * scale, 0.0]
        result.append({"type": "LINE", **points})
    return result


def check_member_coordinates(actual, expected, translation=(0.0, 0.0, 0.0)):
    if len(actual) != len(expected) or not expected:
        raise ValueError("TARGET_MEMBER_COUNT_DIFFERS_FROM_SOURCE")
    for got, wanted in zip(actual, expected):
        if got["type"] != wanted["type"]:
            raise ValueError("TARGET_MEMBER_TYPE_CHANGED")
        for end in ("start", "end"):
            for i in range(3):
                if abs(got[end][i] - wanted[end][i] - translation[i]) > 1e-8:
                    raise ValueError("TARGET_WORLD_MEMBER_COORDINATES_CHANGED")


def unchanged_neighbors(actual, original, target_id):
    expected = {key: value for key, value in original["entities"].items() if key != target_id}
    received = {key: value for key, value in actual["entities"].items() if key != target_id}
    if expected != received:
        raise ValueError("NON_TARGET_ENTITY_BLOCK_TEXT_STYLE_OR_XDATA_CHANGED")
    if actual["units"] != original["units"] or actual["dxfversion"] != original["dxfversion"]:
        raise ValueError("UNITS_OR_DXF_VERSION_CHANGED")
    for name, value in actual["layers"].items():
        if value != original["layers"][name]:
            raise ValueError("NEIGHBOR_LAYER_DEFINITION_CHANGED")


def export_checkpoint(checkpoint, object_id, context, guard_ids, move_mm, out):
    checkpoint, out = Path(checkpoint).resolve(), Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Use a new output directory; preserve earlier artifacts")
    dxf_path, objects_path = checkpoint / "result.dxf", checkpoint / "result.objects.json"
    input_hashes = {str(path): digest(path) for path in (dxf_path, objects_path)}
    manifest = read_json(objects_path)
    if input_hashes[str(dxf_path)] != manifest["dxf_sha256"]:
        raise ValueError("CHECKPOINT_DXF_HASH_MISMATCH")
    matches = [item for item in manifest["objects"] if item["id"] == object_id]
    if len(matches) != 1 or matches[0]["kind"] != "WALL_SEGMENT":
        raise ValueError("TARGET_MUST_BE_ONE_EXISTING_WALL_CHECKPOINT_OBJECT")
    target = matches[0]
    evidence = target["source_evidence"]
    feasibility = evidence["whole_wall_feasibility"]
    member_checks = feasibility["member_checks"]
    if (len(member_checks) != len(target["geometry"]["members"])
            or not member_checks or any(row.get("pass") is not True for row in member_checks)
            or any(row.get("pass") is not True for row in feasibility.get("derived_remainder_checks", []))
            or feasibility.get("source_thresholds_changed") is not False
            or evidence.get("rejection_reasons")):
        raise ValueError("WALL_CHECKPOINT_HAS_NO_COMPLETE_UNCHANGED_SOURCE_GATE_PASS")
    if context[0] >= context[2] or context[1] >= context[3]:
        raise ValueError("CONTEXT_MUST_BE_A_NONEMPTY_SOURCE_PIXEL_BOX")
    edge_points = [member["geometry"][end] for member in target["geometry"]["members"]
                   for end in ("start", "end")]
    if any(not (context[0] <= x <= context[2] and context[1] <= y <= context[3])
           for x, y in edge_points):
        raise ValueError("CONTEXT_MUST_INCLUDE_ALL_OWNED_WALL_MEMBERS")
    junction_ids = {
        value for row in evidence.get("junction_boundary_responsibilities", [])
        for value in row.get("represented_by_wall_ids", [])
    }
    required_ids = set(guard_ids) | junction_ids | {object_id}
    doc = ezdxf.readfile(dxf_path)
    if doc.units != 4 or manifest["unit"] != "paper_mm":
        raise ValueError("SOURCE_MUST_BE_IN_PAPER_MILLIMETRES")
    roi, scale = manifest["roi_xyxy_px"], 25.4 / manifest["dpi"]
    box = [(context[0] - roi[0]) * scale, (roi[3] - context[3]) * scale,
           (context[2] - roi[0]) * scale, (roi[3] - context[1]) * scale]
    selected = [entity for entity in doc.modelspace() if entity.dxf.layer != "REVIEW"
                and (identity(entity) in required_ids or intersects(bbox.extents([entity]), box))]
    selected_ids = [identity(entity) for entity in selected]
    if not required_ids.issubset(selected_ids):
        raise ValueError("REQUIRED_GUARD_OR_JUNCTION_NEIGHBOR_MISSING")
    source_target = next(entity for entity in selected if identity(entity) == object_id)
    if source_target.dxftype() != "INSERT":
        raise ValueError("TARGET_MUST_ALREADY_BE_A_SAVED_INSERT")
    target_block = source_target.dxf.name
    expected = snapshot(doc, object_id, target_block, selected)
    if expected["visible_target_block_references"] != 1:
        raise ValueError("TARGET_ALREADY_HAS_MULTIPLE_VISIBLE_BLOCK_REFERENCES")
    expected_members = source_members_in_mm(target, roi, scale)
    check_member_coordinates(expected["target_world_members"], expected_members)

    local = ezdxf.new(doc.dxfversion)
    local.units = doc.units
    local.header["$MEASUREMENT"] = doc.header.get("$MEASUREMENT", 1)
    importer = Importer(doc, local)
    importer.import_entities(selected)
    importer.finalize()
    copied = list(local.modelspace())
    if len(copied) != len(selected):
        raise ValueError("IMPORT_CHANGED_SELECTED_ENTITY_COUNT")
    for source, destination in zip(selected, copied):
        copy_xdata(source, destination)
    for name in used_layers(selected):
        preserve_explicit_defaults(doc.layers.get(name), local.layers.get(name),
                                   ("flags", "lineweight", "linetype", "color"))
    if snapshot(local, object_id, target_block) != expected:
        raise ValueError("IMPORT_CHANGED_WALL_OR_NEIGHBOR_CONTENT")

    out.mkdir(parents=True, exist_ok=True)
    restored_path = out / "wall_local_restored.dxf"
    local.saveas(restored_path)
    restored = independent_cold_read(restored_path, object_id, target_block)
    unchanged_neighbors(restored, expected, object_id)
    if restored["entities"] != expected["entities"]:
        raise ValueError("RESTORED_SAVED_FILE_DIFFERS_FROM_CHECKPOINT")
    check_member_coordinates(restored["target_world_members"], expected_members)

    move_doc = ezdxf.readfile(restored_path)
    move_target = next(entity for entity in move_doc.modelspace() if identity(entity) == object_id)
    translation = [float(move_mm[0]), float(move_mm[1]), 0.0]
    move_target.translate(*translation)
    moved_path = out / "wall_local_moved.dxf"
    move_doc.saveas(moved_path)
    moved = independent_cold_read(moved_path, object_id, target_block)
    unchanged_neighbors(moved, expected, object_id)
    if moved["target_count"] != 1 or moved["visible_target_block_references"] != 1:
        raise ValueError("MOVE_CHANGED_TARGET_REFERENCE_COUNT")
    check_member_coordinates(moved["target_world_members"], expected_members, translation)
    moved_signature = moved["entities"][object_id]
    original_signature = expected["entities"][object_id]
    moved_attrs = dict(moved_signature["attributes"])
    original_attrs = dict(original_signature["attributes"])
    moved_attrs.pop("insert")
    original_attrs.pop("insert")
    if moved_attrs != original_attrs or any(
            moved_signature[key] != original_signature[key]
            for key in original_signature if key != "attributes"):
        raise ValueError("MOVE_CHANGED_TARGET_DEFINITION_OR_NON_POSITION_ATTRIBUTES")

    delete_doc = ezdxf.readfile(restored_path)
    delete_target = next(entity for entity in delete_doc.modelspace() if identity(entity) == object_id)
    delete_doc.modelspace().delete_entity(delete_target)
    deleted_path = out / "wall_local_deleted.dxf"
    delete_doc.saveas(deleted_path)
    deleted = independent_cold_read(deleted_path, object_id, target_block)
    unchanged_neighbors(deleted, expected, object_id)
    if deleted["target_count"] or deleted["visible_target_block_references"]:
        raise ValueError("DELETE_LEFT_A_VISIBLE_TARGET_REFERENCE")
    if len(deleted["entities"]) != len(expected["entities"]) - 1:
        raise ValueError("DELETE_CHANGED_NON_TARGET_ENTITY_COUNT")
    if input_hashes != {path: digest(path) for path in input_hashes}:
        raise ValueError("ORIGINAL_CHECKPOINT_CHANGED")

    outputs = {name: {"path": str(path), "sha256": result["file_sha256"],
                      "types": result["types"], "target_count": result["target_count"],
                      "visible_target_block_references": result["visible_target_block_references"],
                      "actual_world_members_mm": result["target_world_members"],
                      "audit_errors": result["audit_errors"], "audit_repairs": result["audit_repairs"]}
               for name, path, result in (("restored", restored_path, restored),
                                         ("moved", moved_path, moved), ("deleted", deleted_path, deleted))}
    receipt = {
        "schema": "single-wall-checkpoint-edit-cold-read-v1",
        "status": "PASS_LOCAL_WALL_COPY_MOVE_DELETE_COLD_READ",
        "target_id": object_id, "target_block": target_block,
        "input_hashes": input_hashes, "code_sha256": digest(__file__),
        "context_source_xyxy_px": context, "context_paper_mm": box,
        "roi_xyxy_px": roi, "dpi": manifest["dpi"], "unit": "paper_mm",
        "selected_ids": selected_ids, "guard_ids": list(guard_ids),
        "junction_neighbor_ids": sorted(junction_ids), "neighbor_count": len(selected) - 1,
        "actual_source_member_checks": member_checks,
        "translation_mm": translation, "outputs": outputs,
        "checks": {
            "actual_world_members_match_source_manifest": True,
            "existing_whole_wall_feasibility_checks_all_pass": True,
            "all_selected_entities_copied_whole_without_clipping": True,
            "all_neighbors_blocks_text_styles_layers_and_xdata_unchanged": True,
            "each_owned_member_moved_by_exact_requested_translation": True,
            "delete_removed_whole_insert_and_all_visible_target_references": True,
            "all_three_outputs_cold_read_by_separate_python_processes": True,
            "all_three_outputs_audit_zero_errors_and_repairs": True,
            "original_checkpoint_unchanged": True,
        },
        "new_OCR_calls": 0, "new_model_calls": 0, "source_conversion_run": False,
        "new_geometry_or_ownership_decisions": False,
        "GUI_edit_validation": "NOT_RUN_SCRIPTED_EDIT_AND_PROCESS_COLD_READ_ONLY",
        "duplicate_source_residue_review": "SEPARATE_SOURCE_RESPONSIBILITY_REVIEW_REQUIRED",
        "inherited_source_boundary": "Neighbor wall ownership ambiguity remains; this export does not settle it.",
        "edited_files_do_not_inherit_original_file_audit": True,
    }
    (out / "local_edit_check.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "target_id": object_id,
                      "neighbor_count": receipt["neighbor_count"], "outputs": outputs}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--context", type=int, nargs=4)
    parser.add_argument("--guard-id", action="append", default=[])
    parser.add_argument("--move-mm", type=float, nargs=2, default=[12.0, 8.0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cold-read", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--target-block", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cold_read:
        if not args.target_block:
            parser.error("--target-block is required for a cold reader")
        print(json.dumps(cold_read(args.cold_read, args.object_id, args.target_block)))
        return
    if args.checkpoint is None or args.context is None or args.out is None:
        parser.error("--checkpoint, --context and --out are required")
    export_checkpoint(args.checkpoint, args.object_id, args.context, args.guard_id, args.move_mm, args.out)


if __name__ == "__main__":
    main()
