"""Cold proof of independently saved strokes from the original source graph.

The discovery receipt is not an approval.  Current pixels and the frozen rule
must reproduce its complete paths, and every preceding object must correspond
to a unique actual saved entity, including text groups and block members.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import ezdxf
from ezdxf.tools.text_size import text_size

from .contracts import save_json
from .single_line_text_audit import (
    _expected_attributes,
    _same,
    resolve_saved_text_font,
    text_attributes,
)
from .text_contact_audit import _neighbor_matches, _primitive_matches


FIELD = "attached_stroke_graph"
ADOPTION_SCHEMA = "source-attached-stroke-adoption-v3-component-exact"
PLAN_SCHEMA = "source-attached-stroke-graph-plan-v3-component-exact"
EVIDENCE_SCHEMA = "source-attached-stroke-native-v3-component-exact"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def _identity(entity):
    from .cad_io import APPID

    try:
        value = json.loads(entity.get_xdata(APPID)[0].value)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, IndexError, ezdxf.DXFError):
        return {}


def _unique_rows(rows, label):
    if not isinstance(rows, list):
        raise ValueError(label + "_IS_NOT_AN_OBJECT_LIST")
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"] or row["id"] in result):
            raise ValueError(label + "_INVALID_OR_DUPLICATE_ID")
        result[row["id"]] = row
    return result


def restore_attached_stroke_evidence(out, completion):
    """Persist a source-bound assembly receipt; its verdict is never reused."""
    if (not isinstance(completion, dict)
            or completion.get("schema") != ADOPTION_SCHEMA
            or completion.get("retired_ids") != []):
        raise ValueError("ATTACHED_STROKE_ASSEMBLY_RECEIPT_INVALID")
    plan = completion.get("plan")
    if (not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA
            or completion.get("prior_object_bindings") != plan.get("prior_object_bindings")):
        raise ValueError("ATTACHED_STROKE_ASSEMBLY_PLAN_BINDING_INVALID")
    _unique_rows(completion.get("objects"), "ATTACHED_STROKE_ADOPTION")
    _unique_rows(completion.get("prior_object_bindings"), "ATTACHED_STROKE_PRIOR")
    destination = Path(out) / "attached_strokes"
    for filename, value in (("adoption.json", completion), ("plan.json", plan)):
        target = destination / filename
        if target.exists() and json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError("ATTACHED_STROKE_ASSEMBLY_DESTINATION_ALREADY_DIFFERS")
        save_json(target, value)


def _text_group_matches(entity, obj, roi, dpi, font_path, style):
    if (entity.dxftype() != "INSERT"
            or entity.dxf.name != "I2CAD_" + obj["id"].replace("-", "_")
            or entity.attribs
            or not _same([entity.dxf.xscale, entity.dxf.yscale,
                          entity.dxf.zscale, entity.dxf.rotation], [1, 1, 1, 0])
            or sum(e.dxftype() == "INSERT" and e.dxf.name == entity.dxf.name
                   for e in entity.doc.modelspace()) != 1):
        return False
    members = list(entity.virtual_entities())
    expected = obj["geometry"]["text_members"]
    if len(members) != len(expected) or any(m.dxftype() != "TEXT" for m in members):
        return False
    for member, geometry in zip(members, expected):
        attributes, _ = _expected_attributes(
            member, {"geometry": geometry, "layer": "0"}, roi, dpi, font_path, False,
        )
        attributes["color"] = 0
        # Only an inactive virtual TEXT alignment point is materialized by
        # ezdxf; insertion and all active alignment modes remain checked.
        attributes.pop("align_point", None)
        actual = text_attributes(member)
        if (member.dxf.style != style
                or any(not _same(actual.get(key), value) for key, value in attributes.items())):
            return False
    return True


def _mtext_matches(entity, obj, roi, dpi, font_path, style):
    """Preserve the existing ordinary MTEXT contract when checking all priors.

    Its historical advance-width expression is deliberately reproduced here;
    attached-stroke adoption does not change the multiline layout contract.
    """
    if (entity.dxftype() != "MTEXT" or entity.columns is not None
            or not entity.dxf.hasattr("flow_direction")
            or entity.dxf.style != style):
        return False
    style_record = entity.doc.styles.get(style)
    if (style_record.dxf.font != font_path.name or style_record.dxf.bigfont
            or not _same([style_record.dxf.width, style_record.dxf.height,
                          style_record.dxf.oblique, style_record.dxf.flags,
                          style_record.dxf.generation_flags], [1, 0, 0, 0, 0])):
        return False
    geometry = obj["geometry"]
    lines, rows = geometry["lines"], geometry["source_line_geometries"]
    if not lines or len(lines) != len(rows):
        return False
    mm = 25.4 / float(dpi)
    height = float(geometry["height_px"]) * mm
    reference = ezdxf.new("R2013")
    reference.styles.new(style, dxfattribs={"font": font_path.name})
    parts = []
    for line, row in zip(lines, rows):
        temporary = reference.modelspace().add_text(
            line, dxfattribs={"height": height, "style": style},
        )
        measured = text_size(temporary).width
        if not math.isfinite(measured) or measured <= 0:
            return False
        factor = float(row["width_px"]) * mm / measured
        parts.append("{\\W" + format(factor, ".10g") + ";" + line + "}")
    expected = reference.modelspace().add_mtext("\\P".join(parts), dxfattribs={
        "layer": obj["layer"], "color": 256,
        "insert": [(geometry["x"] - roi[0]) * mm, (roi[3] - geometry["y"]) * mm],
        "char_height": height, "width": float(geometry["width_px"]) * mm * 1.03,
        "attachment_point": 1, "style": style, "rotation": 0,
        "line_spacing_style": 2, "flow_direction": 1,
        "line_spacing_factor": min(4.0, max(0.25,
            geometry.get("line_pitch_px", geometry["height_px"] * 1.5)
            / (geometry["height_px"] * (5 / 3)))),
    })
    ignored = {"handle", "owner"}
    attributes = expected.dxf.all_existing_dxf_attribs()
    if entity.text != expected.text or any(
        not _same(getattr(entity.dxf, key), value)
        for key, value in attributes.items() if key not in ignored
    ):
        return False
    # Defaults may disappear on ordinary DXF serialization.  Extra active
    # direction, extrusion, background or layout attributes must not appear.
    return all(
        _same(value, entity.DXFATTRIBS.get(key).default)
        for key, value in entity.dxf.all_existing_dxf_attribs().items()
        if key not in ignored and key not in attributes
    )


def _saved_object_matches(path, metadata, entity, obj, written, roi, dpi):
    identity = _identity(entity)
    if (identity.get("id") != obj["id"] or identity.get("kind") != obj["kind"]
            or written.get("handle") != entity.dxf.handle
            or written.get("kind") != obj["kind"]
            or written.get("type") != entity.dxftype()
            or entity.dxf.layer != obj["layer"] or int(entity.dxf.color) != 256):
        return False
    if obj["kind"] in ("LINE", "ARC", "CIRCLE", "CONNECTION_PATH"):
        return all(_primitive_matches(entity, obj["kind"], obj["geometry"], roi, dpi).values())
    _, font_path, style = resolve_saved_text_font(path, metadata, obj)
    if obj["kind"] == "TEXT_GROUP":
        return _text_group_matches(entity, obj, roi, dpi, font_path, style)
    if obj["kind"] == "MTEXT":
        return _mtext_matches(entity, obj, roi, dpi, font_path, style)
    return _neighbor_matches(entity, obj, roi, dpi, font_path)


def _published_export_binding(path, metadata_path, metadata, root):
    """The worker publishes this envelope after its first cold gate.

    Subsequent cold reads of a published result bind its actual sidecars too;
    a pre-publication audit explicitly reports that there is no envelope yet.
    """
    envelope_path = path.with_suffix(".export.json")
    if not envelope_path.exists():
        return {"present": False, "status": "NOT_YET_PUBLISHED", "pass": True}
    if envelope_path.is_symlink():
        raise ValueError("ATTACHED_STROKE_PUBLISHED_ENVELOPE_IS_A_SYMLINK")
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    if (envelope.get("source_sha256") != metadata.get("source_sha256")
            or envelope.get("DXF_sha256") != _sha(path)
            or envelope.get("files", {}).get(path.name) != _sha(path)
            or envelope.get("files", {}).get(metadata_path.name) != _sha(metadata_path)):
        raise ValueError("ATTACHED_STROKE_PUBLISHED_FILE_BINDING_CHANGED")
    for name in ("adoption.json", "plan.json"):
        relative = "evidence/attached_strokes/" + name
        if envelope.get("evidence_files", {}).get(relative) != _sha(root / "attached_strokes" / name):
            raise ValueError("ATTACHED_STROKE_PUBLISHED_EVIDENCE_BINDING_CHANGED")
    return {"present": True, "status": "PASS", "pass": True,
            "sha256": _sha(envelope_path), "actual_export_and_evidence_files_checked": True}


def _stage_declarations(path, root):
    """Recognize executed-stage evidence even if its own directory was lost.

    An installed algorithm module is not an execution declaration: the
    bounded connection-checkpoint entry does not run this completion stage.
    """
    declared, errors = [], []
    stage_directory = root / "attached_strokes"
    if stage_directory.exists() or stage_directory.is_symlink():
        # Normal cold reads already have an unambiguous stage declaration.
        # Avoid decoding the much larger completed assembly a second time;
        # the normal proof still checks the publication envelope below.
        return ["ATTACHED_STROKE_STAGE_DIRECTORY"], []
    for candidate, label in (
        (root / "completed_assembly.json", "COMPLETED_ASSEMBLY"),
        (path.with_suffix(".export.json"), "PUBLISHED_EXPORT"),
    ):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            if candidate.is_symlink():
                raise ValueError("DECLARATION_IS_A_SYMLINK")
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("DECLARATION_IS_NOT_AN_OBJECT")
            if label == "COMPLETED_ASSEMBLY":
                if "attached_stroke_completion" in data:
                    declared.append("COMPLETED_ASSEMBLY_ATTACHED_STROKE_STAGE")
            else:
                files = data.get("evidence_files", {})
                if not isinstance(files, dict) or any(not isinstance(key, str) for key in files):
                    raise ValueError("PUBLISHED_EVIDENCE_FILES_IS_NOT_A_PATH_MAP")
                if any(key.startswith("evidence/attached_strokes/") for key in files):
                    declared.append("PUBLISHED_ATTACHED_STROKE_EVIDENCE_FILES")
        except (OSError, ValueError, TypeError) as exc:
            errors.append("ATTACHED_STROKE_" + label + "_DECLARATION_INVALID:" + str(exc))
    return declared, errors


def cold_attached_stroke_bindings(path, doc, gray, roi, dpi, evidence_root):
    path, root = Path(path), Path(evidence_root)
    report = {"pass": True, "checks": [], "targets": [], "prior_object_checks": [],
              "new_OCR_calls": 0, "new_model_calls": 0}
    actual, flagged, unidentified_formal = {}, set(), []
    for entity in doc.modelspace():
        identity = _identity(entity)
        oid = identity.get("id")
        if isinstance(oid, str):
            actual.setdefault(oid, []).append(entity)
        elif entity.dxf.layer != "REVIEW":
            unidentified_formal.append(entity.dxf.handle)
        if identity.get(FIELD) or isinstance(oid, str) and oid.startswith("GRAPHSTROKE-"):
            flagged.add(oid if isinstance(oid, str) and oid else "UNIDENTIFIED:" + entity.dxf.handle)
    metadata_path = path.with_suffix(".objects.json")
    metadata, objects, written, load_errors = {}, {}, {}, []
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        objects = _unique_rows(metadata["objects"], "ATTACHED_STROKE_SAVED_OBJECTS")
        written = _unique_rows(metadata["written"], "ATTACHED_STROKE_WRITTEN")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        load_errors.append("ATTACHED_STROKE_METADATA_UNREADABLE:" + str(exc))
    receipt_path = root / "attached_strokes/adoption.json"
    receipt, adopted = None, {}
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            adopted = _unique_rows(receipt["objects"], "ATTACHED_STROKE_ADOPTED")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            load_errors.append("ATTACHED_STROKE_ADOPTION_UNREADABLE:" + str(exc))
    targets = flagged | set(adopted) | {
        oid for oid, obj in objects.items()
        if FIELD in (obj.get("source_evidence") or {}) or oid.startswith("GRAPHSTROKE-")
    }
    # Zero adoption still has source and pending evidence.  Surviving explicit
    # declarations cannot disappear into the old-output compatibility branch.
    declarations, declaration_errors = _stage_declarations(path, root)
    load_errors.extend(declaration_errors)
    report["stage_declarations"] = declarations
    if not targets and not declarations and not declaration_errors:
        return report  # Existing outputs from before this stage retain their contract.
    report["targets"] = sorted(targets)
    global_check = {"id": "ATTACHED_STROKE_SOURCE_PLAN",
                    "type": "ATTACHED_STROKE_SAVED_PLAN_AND_PRIOR_OBJECTS", "pass": False}
    failure = None
    try:
        from .attached_stroke_graph import object_binding, verify_attached_stroke_graph_plan

        if load_errors:
            raise ValueError(";".join(load_errors))
        if unidentified_formal:
            raise ValueError("ATTACHED_STROKE_UNIDENTIFIED_ACTUAL_FORMAL_ENTITIES")
        if (not isinstance(receipt, dict) or receipt.get("schema") != ADOPTION_SCHEMA
                or receipt.get("retired_ids") != []):
            raise ValueError("ATTACHED_STROKE_RECEIPT_MISSING_OR_INVALID")
        if (metadata.get("dxf_sha256") != _sha(path)
                or metadata.get("roi_xyxy_px") != list(roi) or metadata.get("dpi") != dpi
                or receipt.get("source_sha256") != metadata.get("source_sha256")
                or receipt.get("roi_xyxy_px") != list(roi)):
            raise ValueError("ATTACHED_STROKE_ACTUAL_DXF_OR_SOURCE_BINDING_CHANGED")
        plan = receipt["plan"]
        if (plan.get("schema") != PLAN_SCHEMA
                or receipt.get("prior_object_bindings") != plan.get("prior_object_bindings")):
            raise ValueError("ATTACHED_STROKE_SOURCE_PLAN_OR_PRIOR_BINDINGS_CHANGED")
        saved_plan = json.loads((root / "attached_strokes/plan.json").read_text(encoding="utf-8"))
        if saved_plan != plan:
            raise ValueError("ATTACHED_STROKE_SAVED_PLAN_DIFFERS_FROM_ADOPTION")
        if targets != set(adopted):
            raise ValueError("ATTACHED_STROKE_ACTUAL_CANDIDATE_ADOPTION_ID_SET_DIFFERS")
        path_ids = [row["stroke_id"] for row in plan["paths"]]
        if len(path_ids) != len(set(path_ids)) or set(path_ids) != set(adopted):
            raise ValueError("ATTACHED_STROKE_COMPLETE_PLAN_PATHS_NOT_ALL_EXPORTED_ONCE")
        prior = _unique_rows(receipt["prior_object_bindings"], "ATTACHED_STROKE_PRIOR")
        if set(prior) & set(adopted) or set(prior) | set(adopted) != set(objects):
            raise ValueError("ATTACHED_STROKE_FINAL_OBJECT_SET_DOES_NOT_PRESERVE_PRECEDING_STAGE")
        formal_ids = {
            oid for oid, entities in actual.items()
            if any(e.dxf.layer != "REVIEW" for e in entities)
        }
        if formal_ids != set(objects) or set(written) != set(objects):
            raise ValueError("ATTACHED_STROKE_ACTUAL_EXPORT_ENTITY_SET_CHANGED")
        for oid, binding in sorted(prior.items()):
            obj = objects[oid]
            entities = actual.get(oid, [])
            row = {"id": oid, "pass": False}
            row["sidecar_matches_prior_source_and_geometry"] = object_binding(obj) == binding
            row["actual_saved_geometry_and_all_members_match"] = (
                len(entities) == 1 and _saved_object_matches(
                    path, metadata, entities[0], obj, written.get(oid, {}), roi, dpi,
                )
            )
            row["pass"] = all(row[key] for key in (
                "sidecar_matches_prior_source_and_geometry", "actual_saved_geometry_and_all_members_match"))
            report["prior_object_checks"].append(row)
        if any(not row["pass"] for row in report["prior_object_checks"]):
            raise ValueError("ATTACHED_STROKE_ACTUAL_PRECEDING_OBJECT_CHANGED")
        replay = verify_attached_stroke_graph_plan(gray, roi, plan, source_graph=None)
        report["plan_replay"] = replay
        if not isinstance(replay, dict) or replay.get("pass") is not True:
            raise ValueError("ATTACHED_STROKE_COMPLETE_SOURCE_PLAN_REPLAY_FAILED")
        if replay.get("replayed_paths") != plan.get("paths"):
            raise ValueError("ATTACHED_STROKE_COMPLETE_PATH_SET_REPLAY_DIFFERS")
        report["published_export"] = _published_export_binding(path, metadata_path, metadata, root)
        global_check["pass"] = True
        global_check["actual_prior_object_count"] = len(prior)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ezdxf.DXFError) as exc:
        failure = str(exc)
        global_check["reason"] = failure
    report["checks"].append(global_check)
    for oid in sorted(targets):
        check = {"id": oid, "type": "ATTACHED_STROKE_ACTUAL_COMPLETE_NATIVE_PATH", "pass": False}
        try:
            if failure:
                raise ValueError(failure)
            obj = objects[oid]
            if obj != adopted[oid]:
                raise ValueError("ATTACHED_STROKE_SAVED_OBJECT_DIFFERS_FROM_ADOPTION")
            entities = actual.get(oid, [])
            if len(entities) != 1 or _identity(entities[0]).get(FIELD) is not True:
                raise ValueError("ATTACHED_STROKE_ACTUAL_ENTITY_MISSING_DUPLICATE_OR_UNMARKED")
            if obj["kind"] not in ("LINE", "CONNECTION_PATH") or obj["layer"] != "SHORT_STROKE":
                raise ValueError("ATTACHED_STROKE_NATIVE_EDITING_REPRESENTATION_INVALID")
            if not _saved_object_matches(path, metadata, entities[0], obj, written[oid], roi, dpi):
                raise ValueError("ATTACHED_STROKE_ACTUAL_NATIVE_GEOMETRY_CHANGED")
            evidence = obj["source_evidence"]
            proof = evidence[FIELD]
            index = proof.get("path_index")
            if type(index) is not int or not 0 <= index < len(plan["paths"]):
                raise ValueError("ATTACHED_STROKE_PATH_INDEX_INVALID")
            source_path = plan["paths"][index]
            from .text_contact_adoption import _native_object

            native_kind, native_geometry = _native_object(source_path["representation"])
            if (proof.get("schema") != EVIDENCE_SCHEMA
                    or proof.get("source_sha256") != metadata["source_sha256"]
                    or proof.get("plan_sha256") != _digest(plan)
                    or proof.get("path") != source_path
                    or proof.get("path_sha256") != _digest(source_path)
                    or evidence.get("source_pixels_modified") is not False):
                raise ValueError("ATTACHED_STROKE_NATIVE_SOURCE_CERTIFICATE_CHANGED")
            if (oid != source_path["stroke_id"] or obj["kind"] != native_kind
                    or obj["geometry"] != native_geometry
                    or evidence.get("source_path_points") != source_path["source_path_px"]
                    or evidence.get("original_source_crop_xyxy_px") != plan["original_source_crop_xyxy_px"]
                    or evidence.get("original_source_crop_array_sha256") != plan["original_source_crop_array_sha256"]):
                raise ValueError("ATTACHED_STROKE_NATIVE_REPRESENTATION_DIFFERS_FROM_COMPLETE_PATH")
            check.update({"pass": True, "path_index": index,
                          "actual_native_type": entities[0].dxftype(),
                          "whole_path_and_both_endpoint_segments_in_one_entity": True,
                          "current_source_graph_replayed": True})
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ezdxf.DXFError) as exc:
            check["reason"] = str(exc)
        report["checks"].append(check)
    report["pass"] = all(row["pass"] for row in report["checks"])
    return report
