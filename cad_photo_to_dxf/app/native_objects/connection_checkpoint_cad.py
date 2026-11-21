"""Merge bounded new native paths while preserving actual old DXF entities.

Old geometry is never rebuilt from its ledger.  Its saved entities, block
definitions, XDATA, layers and styles are the preservation reference.  The
ledger only supplies identities and source evidence for the resulting sidecar.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import uuid

import ezdxf

from . import cad_io
from .contracts import save_json
from .execution import file_sha


def _fail(reason):
    raise ValueError("CHECKPOINT_DXF_" + reason)


def _value(value):
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)) or hasattr(value, "x"):
        return [_value(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _entity(entity):
    result = _value(cad_io.entity_data(entity))
    result["handle"] = entity.dxf.handle
    result["xdata"] = {
        appid: [[tag.code, _value(tag.value)] for tag in tags]
        for appid, tags in (entity.xdata.data.items() if entity.xdata else [])
    }
    if entity.dxftype() == "INSERT":
        result["attribs"] = [_entity(item) for item in entity.attribs]
    return result


def _formal(doc):
    result = {}
    for entity in doc.modelspace():
        try:
            identity = cad_io.identity(entity)
        except (ezdxf.DXFError, ValueError, TypeError) as exc:
            raise ValueError("CHECKPOINT_DXF_FORMAL_IDENTITY_MISSING") from exc
        if not isinstance(identity, dict) or set(identity) != {"id", "kind"}:
            _fail("FORMAL_IDENTITY_INVALID")
        if identity["kind"] == "REVIEW" and entity.dxf.layer == "REVIEW":
            continue
        oid = identity["id"]
        if not isinstance(oid, str) or not oid or oid in result:
            _fail("FORMAL_ID_DUPLICATE_OR_INVALID")
        result[oid] = entity
    return result


def _snapshot(doc, entities):
    blocks = {}

    def include_block(name, stack):
        if name in stack:
            _fail("CYCLIC_RETAINED_BLOCK")
        if name in blocks:
            return
        block = doc.blocks.get(name)
        if block is None:
            _fail("RETAINED_BLOCK_MISSING")
        blocks[name] = {
            "definition": _entity(block.block),
            "record": _entity(block.block_record),
            "members": [_entity(member) for member in block],
        }
        for member in block:
            if member.dxftype() == "INSERT":
                include_block(member.dxf.name, (*stack, name))

    for entity in entities.values():
        if entity.dxftype() == "INSERT":
            include_block(entity.dxf.name, ())
    return {
        "entities": {oid: _entity(entity) for oid, entity in entities.items()},
        "blocks": blocks,
        "layers": {layer.dxf.name: _entity(layer) for layer in doc.layers},
        "styles": {style.dxf.name: _entity(style) for style in doc.styles},
    }


def _compare_preserved(before, after):
    for category in ("entities", "blocks", "layers", "styles"):
        for key, expected in before[category].items():
            if after[category].get(key) != expected:
                _fail("PRESERVATION_CHANGED:" + category + ":" + key)


def _rows(rows, label):
    if not isinstance(rows, list):
        _fail(label + "_MISSING")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in result:
            _fail(label + "_ID_DUPLICATE_OR_INVALID")
        result[row["id"]] = row
    return result


def _copy_resource(source, destination):
    if destination.exists():
        if not destination.is_file() or file_sha(source) != file_sha(destination):
            _fail("EXISTING_RESOURCE_DIFFERS:" + destination.name)
        return
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if file_sha(source) != file_sha(destination):
        _fail("RESOURCE_COPY_CHANGED:" + source.name)


def _resources(baseline_path, old_font, generated_font, generated_directory, output_directory):
    """Use declared resources; never follow an obsolete metadata source path."""
    resources = []
    for metadata, primary in ((old_font, baseline_path.parent), (generated_font, generated_directory)):
        if not isinstance(metadata, dict) or "font" not in metadata:
            continue
        font = metadata["font"]
        license_file = metadata.get("bundled_license")
        if not all(isinstance(name, str) and name and Path(name).name == name for name in (font, license_file)):
            _fail("FONT_RESOURCE_NAME_INVALID")
        for name in (font, license_file):
            # Captured baselines carry the DXF and ledger, while the installed
            # native writer supplies its verified font/license alongside the
            # temporary new-path DXF.  The old font hash must still match.
            candidates = [primary / name, generated_directory / name]
            source = next((path for path in candidates if path.is_file()), None)
            if source is None:
                _fail("FONT_OR_LICENSE_MISSING:" + name)
            digest = file_sha(source)
            if name == font and digest != metadata.get("sha256"):
                _fail("BASELINE_FONT_HASH_MISMATCH")
            target = output_directory / name
            _copy_resource(source, target)
            row = {"path": str(target), "sha256": digest}
            if row not in resources:
                resources.append(row)
    return resources


def _serialize_preserving_old_defaults(doc, path):
    mtexts = [entity for entity in doc.entitydb.values() if entity.is_alive and entity.dxftype() == "MTEXT"]
    missing = [entity.dxf.handle for entity in mtexts if not entity.dxf.hasattr("flow_direction")]
    if not missing:
        return cad_io.save_native_dxf(doc, path)
    # Do not invent direction=1 on an old note merely to pass the stricter
    # new-object serializer. Ordinary serialization is accepted only if the
    # subsequent cold snapshot proves all retained attributes unchanged.
    doc.saveas(path)
    return {
        "method": "ezdxf.Drawing.saveas_preserve_existing_missing_MTEXT_direction",
        "old_mtext_without_direction": missing,
        "layout_attributes_modified": False,
        "requires_exact_cold_preservation": True,
    }


def write_checkpoint_dxf(
    baseline_dxf,
    baseline_meta,
    retained_ids,
    new_objects,
    output_path,
    roi,
    dpi,
    source_sha,
    *,
    evidence_directory=None,
):
    """Save whole retained entities plus paths made by the official exporter.

    ``roi`` must be the parent's original source-to-paper mapping, not a local
    crop coordinate system. Complete retained neighbors may exceed a window.
    No old adoption decision is applied to a new object here.
    """
    baseline_path = Path(baseline_dxf).resolve()
    output = Path(output_path).resolve()
    sidecar = output.with_suffix(".objects.json")
    certificate_path = output.with_suffix(".preservation.json")
    if output == baseline_path or any(path.exists() for path in (output, sidecar, certificate_path)):
        _fail("OUTPUT_MUST_BE_NEW")
    if (
        not isinstance(baseline_meta, dict)
        or baseline_meta.get("source_sha256") != source_sha
        or baseline_meta.get("roi_xyxy_px") != list(roi)
        or baseline_meta.get("dpi") != dpi
        or baseline_meta.get("unit") != "paper_mm"
        or baseline_meta.get("dxf_sha256") != file_sha(baseline_path)
    ):
        _fail("BASELINE_SOURCE_OR_MAPPING_CHANGED")
    old_rows = _rows(baseline_meta.get("objects"), "BASELINE_OBJECTS")
    old_written = _rows(baseline_meta.get("written"), "BASELINE_WRITTEN")
    if old_rows.keys() != old_written.keys():
        _fail("BASELINE_WRITTEN_IDS_MISMATCH")
    if not isinstance(retained_ids, (list, tuple, set)):
        _fail("RETAINED_IDS_INVALID")
    retained = list(retained_ids)
    if any(not isinstance(oid, str) for oid in retained) or len(set(retained)) != len(retained):
        _fail("RETAINED_IDS_DUPLICATE_OR_INVALID")
    if not set(retained).issubset(old_rows):
        _fail("RETAINED_ID_MISSING")
    fresh_rows = _rows(new_objects, "NEW_OBJECTS")
    if set(fresh_rows) & set(old_rows):
        _fail("NEW_ID_REUSES_BASELINE_ID")
    if any(row.get("kind") != "CONNECTION_PATH" for row in fresh_rows.values()):
        _fail("ONLY_NEW_CONNECTION_PATH_ALLOWED")

    doc = ezdxf.readfile(baseline_path)
    if doc.units != 4:
        _fail("BASELINE_NOT_PAPER_MM")
    old_entities = _formal(doc)
    if old_entities.keys() != old_rows.keys() or any(
        cad_io.identity(entity)["kind"] != old_rows[oid].get("kind")
        or entity.dxftype() != old_written[oid].get("type")
        or entity.dxf.handle != old_written[oid].get("handle")
        for oid, entity in old_entities.items()
    ):
        _fail("BASELINE_ENTITIES_DISAGREE_WITH_LEDGER")
    retained_entities = {oid: old_entities[oid] for oid in old_rows if oid in retained}
    before = _snapshot(doc, retained_entities)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(evidence_directory).resolve() if evidence_directory else output.parent
    stage = evidence / ("checkpoint-writer-" + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    save_json(stage / "retained_before.json", before)
    new_path = stage / "new_paths.dxf"
    new_meta = cad_io.export_objects(new_objects, new_path, roi, dpi, source_sha)
    generated = ezdxf.readfile(new_path)
    generated_entities = _formal(generated)
    if generated_entities.keys() != fresh_rows.keys() or any(entity.dxftype() != "LWPOLYLINE" for entity in generated_entities.values()):
        _fail("NATIVE_WRITER_DID_NOT_PRODUCE_ONE_POLYLINE_PER_PATH")

    for entity in list(doc.modelspace()):
        if cad_io.identity(entity)["id"] not in retained_entities:
            doc.modelspace().delete_entity(entity)
    if cad_io.APPID not in doc.appids:
        doc.appids.new(cad_io.APPID)
    for entity in generated_entities.values():
        name = entity.dxf.layer
        if name not in doc.layers:
            source_layer = generated.layers.get(name)
            attributes = {
                key: value for key, value in source_layer.dxf.all_existing_dxf_attribs().items()
                if key in ("flags", "color", "linetype", "lineweight", "plot", "true_color", "transparency")
            }
            doc.layers.new(name, dxfattribs=attributes)
        doc.modelspace().add_entity(entity.copy())
    resources = _resources(
        baseline_path, baseline_meta.get("font"), new_meta.get("font"), stage, output.parent,
    )
    candidate = stage / "merged_candidate.dxf"
    try:
        serialization = _serialize_preserving_old_defaults(doc, candidate)
        cold = ezdxf.readfile(candidate)
        actual = _formal(cold)
        if set(actual) != set(retained_entities) | set(fresh_rows) or len(cold.modelspace()) != len(actual):
            _fail("SAVED_FORMAL_MEMBERSHIP_OR_REVIEW_CHANGED")
        after = _snapshot(cold, {oid: actual[oid] for oid in retained_entities})
        save_json(stage / "retained_after.json", after)
        _compare_preserved(before, after)
        for oid, entity in generated_entities.items():
            expected, saved = _entity(entity), _entity(actual[oid])
            expected.pop("handle")
            saved.pop("handle")
            if expected != saved:
                _fail("NEW_NATIVE_PATH_CHANGED_AFTER_TRANSFER:" + oid)
        audit = cold.audit()
        if audit.has_errors or audit.has_fixes:
            _fail("SAVED_DXF_REQUIRES_REPAIR")
        if file_sha(baseline_path) != baseline_meta["dxf_sha256"]:
            _fail("BASELINE_FILE_CHANGED_DURING_EXPORT")
    except Exception as exc:
        save_json(stage / "failure.json", {
            "status": "FAILED_NO_OUTPUT_PUBLICATION", "error": str(exc),
            "candidate": str(candidate), "baseline_dxf": str(baseline_path),
            "baseline_layout_not_modified_to_force_a_pass": True,
        })
        raise

    _copy_resource(candidate, output)
    certificate = {
        "schema": "native-checkpoint-entity-preservation-v1",
        "status": "PASS", "baseline_dxf_sha256": baseline_meta["dxf_sha256"],
        "output_dxf_sha256": file_sha(output),
        "retained_ids": list(retained_entities), "new_ids": list(fresh_rows),
        "removed_old_ids": [oid for oid in old_rows if oid not in retained_entities],
        "retained_entity_attributes_handles_and_all_XDATA_unchanged": True,
        "retained_block_definitions_and_members_unchanged": True,
        "existing_layers_and_styles_unchanged": True,
        "parent_source_to_paper_mapping_unchanged": True,
        "old_entities_reconstructed_from_ledger": False,
        "whole_neighbors_clipped_to_windows": False,
        "new_paths_exporter": "app.native_objects.cad_io.export_objects",
        "new_paths_dxf_sha256": file_sha(new_path),
        "new_entities_are_LWPOLYLINE": True,
        "REVIEW_entities_in_output": 0,
        "cold_DXF_audit_errors": 0, "cold_DXF_audit_fixes": 0,
        "snapshot_before": {"path": str(stage / "retained_before.json"), "sha256": file_sha(stage / "retained_before.json")},
        "snapshot_after": {"path": str(stage / "retained_after.json"), "sha256": file_sha(stage / "retained_after.json")},
        "resources": resources,
        "source_review_of_new_paths": "REQUIRED_SEPARATELY_NOT_INHERITED_FROM_BASELINE",
    }
    save_json(certificate_path, certificate)
    ordered_objects = [deepcopy(old_rows[oid]) for oid in retained_entities] + deepcopy(new_objects)
    written = []
    generated_written = _rows(new_meta["written"], "GENERATED_WRITTEN")
    for row in ordered_objects:
        oid = row["id"]
        entity = actual[oid]
        entry = deepcopy(old_written[oid] if oid in retained_entities else generated_written[oid])
        entry.update({
            "id": oid, "kind": row["kind"], "type": entity.dxftype(), "handle": entity.dxf.handle,
            "block_members": [member.dxftype() for member in cold.blocks.get(entity.dxf.name)] if entity.dxftype() == "INSERT" else [],
        })
        written.append(entry)
    font_metadata = deepcopy(baseline_meta.get("font") or new_meta.get("font"))
    if isinstance(font_metadata, dict) and "font" in font_metadata:
        font_metadata["source"] = str(output.parent / font_metadata["font"])
    meta = {
        "dxf_path": str(output), "source_sha256": source_sha, "dxf_sha256": file_sha(output),
        "roi_xyxy_px": list(roi), "dpi": dpi, "unit": "paper_mm",
        "objects": ordered_objects, "written": written,
        "font": font_metadata,
        "repair_regions": [], "native_schema": "complete_objects_v2", "serialization": serialization,
        "preservation_certificate": {"path": str(certificate_path), "sha256": file_sha(certificate_path), "status": "PASS"},
    }
    save_json(sidecar, meta)
    return meta
