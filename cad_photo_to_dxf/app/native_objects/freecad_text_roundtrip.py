"""Explicit, source-bound FreeCAD text edits written back as real DXF text.

This is an opt-in compatibility tool, not FreeCAD's ordinary exporter and not
OCR. Only bound modelspace TEXT/MTEXT may change. Nontext CAD edits, new text,
unsupported font/layout edits and stale source bindings stop the transaction.
No source height scaling or text outlining is performed.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import uuid


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain(value):
    if hasattr(value, "x") and hasattr(value, "y"):
        return list(value)
    if isinstance(value, (tuple, list)):
        return [plain(x) for x in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def dump(path, value):
    path = Path(path)
    if path.exists():
        raise FileExistsError("PRESERVE_EXISTING_EVIDENCE:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def source_manifest(source):
    import ezdxf

    source = Path(source).resolve()
    doc = ezdxf.readfile(source)
    audit = doc.audit()
    if audit.errors or audit.fixes:
        raise ValueError("SOURCE_DXF_REQUIRES_REPAIR_NOT_ACCEPTED")
    if doc.units != 4:
        raise ValueError("EXPLICIT_MM_DXF_REQUIRED")
    rows = []
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind not in ("TEXT", "MTEXT"):
            continue
        if kind == "TEXT":
            anchor = (
                e.dxf.align_point if (e.dxf.halign or e.dxf.valign) else e.dxf.insert
            )
            row = {
                "handle": e.dxf.handle,
                "type": kind,
                "text": e.plain_text(),
                "raw_text": e.dxf.text,
                "height_mm": e.dxf.height,
                "rotation_deg": e.dxf.rotation,
                "width_factor": e.dxf.width,
                "halign": e.dxf.halign,
                "valign": e.dxf.valign,
                "anchor_mm": list(anchor)[:2],
            }
        else:
            row = {
                "handle": e.dxf.handle,
                "type": kind,
                "text": e.plain_text(),
                "raw_text": e.text,
                "height_mm": e.dxf.char_height,
                "rotation_deg": e.get_rotation(),
                "width_mm": e.dxf.width,
                "attachment_point": e.dxf.attachment_point,
                "anchor_mm": list(e.dxf.insert)[:2],
            }
        row.update(
            layer=e.dxf.layer,
            style=e.dxf.style,
            font_file=doc.styles.get(e.dxf.style).dxf.font,
        )
        rows.append(plain(row))
    nested = [
        {"block": b.name, "handle": e.dxf.handle, "type": e.dxftype()}
        for b in doc.blocks
        if not b.name.startswith("*")
        for e in b
        if e.dxftype() in ("TEXT", "MTEXT", "ATTDEF")
    ]
    return {
        "schema": "i2cad-freecad-text-source-v1",
        "source_dxf": str(source),
        "source_dxf_sha256": sha(source),
        "unit": "mm",
        "expected_texts": rows,
        "unsupported_nested_text_entities": nested,
        "scope": "EXPLICIT_MODELSPACE_TEXT_EDIT_ONLY_NOT_FULL_FREECAD_COMPATIBILITY",
        "recognition_result": False,
    }


def _text_state(obj, App):
    x = obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
    z = obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    if max(abs(z.x), abs(z.y), abs(z.z - 1)) > 1e-9:
        raise ValueError("NONPLANAR_TEXT_EDIT_UNSUPPORTED:" + obj.Name)
    return {
        "name": obj.Name,
        "text": list(obj.Text),
        "position_mm": list(obj.Placement.Base),
        "rotation_deg": math.degrees(math.atan2(x.y, x.x)),
        "height_mm": float(obj.ViewObject.FontSize),
        "font_name": str(obj.ViewObject.FontName),
        "justification": str(obj.ViewObject.Justification),
        "line_spacing": float(obj.ViewObject.LineSpacing),
        "scale_multiplier": float(obj.ViewObject.ScaleMultiplier),
        "display_mode": str(obj.ViewObject.DisplayMode),
        "text_color": list(obj.ViewObject.TextColor),
        "parents": sorted(o.Name for o in obj.InList),
    }


def _nontext_state(doc, text_names, marker_name):
    result = {}
    for obj in doc.Objects:
        if obj.Name in text_names or obj.Name == marker_name:
            continue
        row = {"type": obj.TypeId, "label": obj.Label}
        if hasattr(obj, "Placement"):
            row["placement"] = list(obj.Placement.toMatrix().A)
        if hasattr(obj, "Shape"):
            row["brep_sha256"] = hashlib.sha256(
                obj.Shape.exportBrepToString().encode()
            ).hexdigest()
        if hasattr(obj, "Group"):
            row["group_nontext_members"] = sorted(
                o.Name for o in obj.Group if o.Name not in text_names
            )
        view = getattr(obj, "ViewObject", None)
        row["view"] = {
            k: plain(getattr(view, k))
            for k in ("Visibility", "LineColor", "ShapeColor", "LineWidth", "PointSize")
            if hasattr(view, k)
        }
        result[obj.Name] = row
    return result


def bind_document(doc, manifest, source, *, App):
    """Call after explicit source-parameter restoration, before user edits."""
    if tuple(App.Version()[:3]) != ("1", "0", "0"):
        raise ValueError("FREECAD_VERSION_NOT_VALIDATED")
    if sha(source) != manifest["source_dxf_sha256"]:
        raise ValueError("SOURCE_BINDING_MISMATCH")
    if any(hasattr(o, "I2CADSessionID") for o in doc.Objects):
        raise ValueError("DOCUMENT_ALREADY_BOUND")
    bindings = []
    used = set()
    for row in manifest["expected_texts"]:
        found = []
        for obj in doc.Objects:
            if not hasattr(obj, "Text") or not hasattr(obj, "Placement"):
                continue
            content = "\n".join(obj.Text)
            p = obj.Placement.Base
            if (
                content in (row["text"], row.get("raw_text"))
                and math.hypot(p.x - row["anchor_mm"][0], p.y - row["anchor_mm"][1])
                <= 1e-9
            ):
                found.append(obj)
        if len(found) != 1 or found[0].Name in used:
            raise ValueError("AMBIGUOUS_SOURCE_TEXT_BINDING:" + row["handle"])
        obj = found[0]
        used.add(obj.Name)
        bindings.append(
            {
                "handle": row["handle"],
                "name": obj.Name,
                "baseline": _text_state(obj, App),
                "source": row,
            }
        )
    if not bindings:
        raise ValueError("NO_MODELSPACE_TEXT_TO_BIND")
    unbound = [o.Name for o in doc.Objects if hasattr(o, "Text") and o.Name not in used]
    if unbound:
        raise ValueError("UNBOUND_TEXTS_MUST_BE_RESOLVED:" + ",".join(unbound))
    marker = doc.addObject("App::FeaturePython", "I2CADTextEditSession")
    marker.Label = "I2CAD source-bound text edit session (not drawing geometry)"
    marker.addProperty("App::PropertyString", "I2CADSessionID", "I2CAD")
    marker.addProperty("App::PropertyString", "I2CADSourceSHA256", "I2CAD")
    marker.I2CADSessionID = str(uuid.uuid4())
    marker.I2CADSourceSHA256 = manifest["source_dxf_sha256"]
    marker.setEditorMode("I2CADSessionID", 1)
    marker.setEditorMode("I2CADSourceSHA256", 1)
    marker.ViewObject.Visibility = False
    doc.recompute()
    return {
        "schema": "i2cad-freecad-text-binding-v1",
        "session_id": marker.I2CADSessionID,
        "marker_name": marker.Name,
        "source_dxf_sha256": manifest["source_dxf_sha256"],
        "source_dxf": str(Path(source).resolve()),
        "manifest": manifest,
        "bindings": bindings,
        "nontext_baseline": _nontext_state(doc, used, marker.Name),
        "ordinary_FreeCAD_export_repaired": False,
    }


def capture_edits(doc, binding, *, App):
    marker = doc.getObject(binding["marker_name"])
    if (
        marker is None
        or marker.I2CADSessionID != binding["session_id"]
        or marker.I2CADSourceSHA256 != binding["source_dxf_sha256"]
    ):
        raise ValueError("FREECAD_DOCUMENT_SESSION_MISMATCH")
    names = {row["name"] for row in binding["bindings"]}
    if [o.Name for o in doc.Objects if hasattr(o, "Text") and o.Name not in names]:
        raise ValueError("NEW_UNBOUND_TEXT_UNSUPPORTED")
    current = _nontext_state(doc, names, marker.Name)
    if current != binding["nontext_baseline"]:
        raise ValueError("NONTEXT_EDIT_REJECTED_DO_NOT_SILENTLY_RESTORE_ORIGINAL")
    rows = []
    for row in binding["bindings"]:
        obj = doc.getObject(row["name"])
        rows.append(
            {
                "handle": row["handle"],
                "name": row["name"],
                "deleted": obj is None,
                "current": None if obj is None else _text_state(obj, App),
            }
        )
    return {
        "schema": "i2cad-freecad-text-edits-v1",
        "session_id": binding["session_id"],
        "source_dxf_sha256": binding["source_dxf_sha256"],
        "nontext_unchanged": True,
        "nontext_current": current,
        "rows": rows,
        "captured_from_live_FreeCAD_document": True,
    }


def _entity_snapshot(doc):
    from ezdxf.lldxf.tagwriter import TagCollector

    result = {}
    for block in doc.blocks:
        for e in block:
            collector = TagCollector(dxfversion=doc.dxfversion)
            e.export_dxf(collector)
            result[e.dxf.handle] = [[t.code, plain(t.value)] for t in collector.tags]
    return result


def export_bound_edits(source, binding, edits, destination):
    """Fresh source DXF + observed text delta; reject every unbound change."""
    import ezdxf

    source, destination = Path(source).resolve(), Path(destination).resolve()
    if (
        source == destination
        or destination.exists()
        or destination.with_suffix(".text_edit_audit.json").exists()
    ):
        raise FileExistsError("OUTPUT_MUST_BE_NEW_AND_DISTINCT_FROM_SOURCE")
    if (
        sha(source) != binding["source_dxf_sha256"]
        or edits["source_dxf_sha256"] != binding["source_dxf_sha256"]
        or edits["session_id"] != binding["session_id"]
    ):
        raise ValueError("STALE_OR_WRONG_SOURCE_BINDING")
    if (
        edits.get("nontext_unchanged") is not True
        or edits["nontext_current"] != binding["nontext_baseline"]
    ):
        raise ValueError("NONTEXT_EDIT_REJECTED")
    doc = ezdxf.readfile(source)
    initial_audit = doc.audit()
    if initial_audit.errors or initial_audit.fixes:
        raise ValueError("SOURCE_DXF_REQUIRES_REPAIR")
    before = _entity_snapshot(doc)
    bound = {r["handle"]: r for r in binding["bindings"]}
    if len(edits["rows"]) != len(bound) or {r["handle"] for r in edits["rows"]} != set(
        bound
    ):
        raise ValueError("TEXT_EDIT_ACCOUNTING_MISMATCH")
    changes = []
    for change in edits["rows"]:
        original = bound[change["handle"]]
        if change["name"] != original["name"]:
            raise ValueError("TEXT_OBJECT_IDENTITY_CHANGED")
        entity = doc.entitydb[change["handle"]]
        if entity.dxftype() != original["source"]["type"]:
            raise ValueError("TEXT_ENTITY_TYPE_CHANGED")
        if change["deleted"]:
            doc.modelspace().delete_entity(entity)
            changes.append({"handle": change["handle"], "operation": "delete"})
            continue
        current, baseline = change["current"], original["baseline"]
        if current == baseline:
            continue
        for field in (
            "font_name",
            "line_spacing",
            "scale_multiplier",
            "display_mode",
            "text_color",
            "parents",
        ):
            if current[field] != baseline[field]:
                raise ValueError("UNSUPPORTED_TEXT_EDIT:" + field)
        if current["justification"] != baseline["justification"]:
            raise ValueError("ALIGNMENT_CHANGE_REQUIRES_SEPARATE_LAYOUT_VALIDATION")
        values = current["position_mm"] + [
            current["rotation_deg"],
            current["height_mm"],
        ]
        if not all(math.isfinite(v) for v in values) or current["height_mm"] <= 0:
            raise ValueError("INVALID_TEXT_EDIT_GEOMETRY")
        content = "\n".join(current["text"])
        old_content = "\n".join(baseline["text"])
        if content != old_content:
            if entity.dxftype() == "TEXT":
                if "\n" in content:
                    raise ValueError("MULTILINE_CONTENT_CANNOT_REPLACE_TEXT")
                entity.dxf.text = content
            else:
                raw = original["source"]["raw_text"]
                if raw.replace("\\P", "\n") != original["source"]["text"]:
                    raise ValueError(
                        "RICH_MTEXT_CONTENT_EDIT_REQUIRES_FORMAT_AWARE_EDITOR"
                    )
                entity.text = "\\P".join(
                    s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                    for s in current["text"]
                )
        delta = [a - b for a, b in zip(current["position_mm"], baseline["position_mm"])]
        if any(delta):
            entity.translate(*delta)
        if current["height_mm"] != baseline["height_mm"]:
            if entity.dxftype() == "TEXT":
                entity.dxf.height = current["height_mm"]
            else:
                entity.dxf.char_height = current["height_mm"]
        rotation = current["rotation_deg"] - baseline["rotation_deg"]
        if rotation:
            if entity.dxftype() == "TEXT":
                entity.dxf.rotation += rotation
            else:
                entity.set_rotation(entity.get_rotation() + rotation)
        changes.append(
            {
                "handle": change["handle"],
                "operation": "edit",
                "new_plain_text": content,
                "translation_mm": delta,
                "new_height_mm": current["height_mm"],
                "rotation_delta_deg": rotation,
            }
        )
    expected = _entity_snapshot(doc)
    changed = {r["handle"] for r in changes}
    if {k: v for k, v in expected.items() if k not in changed} != {
        k: v for k, v in before.items() if k not in changed
    }:
        raise ValueError("UNEXPECTED_NONTARGET_MUTATION_BEFORE_SAVE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        "." + destination.name + "." + uuid.uuid4().hex + ".tmp.dxf"
    )
    doc.saveas(temporary)
    cold = ezdxf.readfile(temporary)
    audit = cold.audit()
    if audit.errors or audit.fixes or _entity_snapshot(cold) != expected:
        raise ValueError("COLD_DXF_MISMATCH_TEMPORARY_RETAINED:" + str(temporary))
    os.link(temporary, destination)
    temporary.unlink()
    report = {
        "status": "BOUND_TEXT_DXF_SAVE_AND_COLD_READ_PASS",
        "source_unchanged": sha(source) == binding["source_dxf_sha256"],
        "output": str(destination),
        "output_sha256": sha(destination),
        "changes": changes,
        "non_target_entity_count": len(before) - len(changed),
        "non_target_entities_exact": True,
        "output_texts": [
            {"handle": e.dxf.handle, "type": e.dxftype(), "text": e.plain_text()}
            for e in cold.modelspace()
            if e.dxftype() in ("TEXT", "MTEXT")
        ],
        "ordinary_FreeCAD_export_repaired": False,
        "font_width_and_layout_display_verified": False,
        "actual_GUI_acceptance": "NOT_PROVEN_BY_BACKEND",
        "target_LibreCAD_acceptance": "NOT_RUN",
    }
    dump(destination.with_suffix(".text_edit_audit.json"), report)
    return report


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("source")
    m.add_argument("output")
    e = sub.add_parser("export")
    e.add_argument("source")
    e.add_argument("binding")
    e.add_argument("edits")
    e.add_argument("output")
    args = p.parse_args()
    if args.command == "manifest":
        result = source_manifest(args.source)
        dump(args.output, result)
        print(
            json.dumps(
                {
                    "status": "MANIFEST_ONLY_NOT_CAD_ACCEPTANCE",
                    "text_count": len(result["expected_texts"]),
                    "nested_text_count": len(
                        result["unsupported_nested_text_entities"]
                    ),
                }
            )
        )
    else:
        result = export_bound_edits(
            args.source,
            json.loads(Path(args.binding).read_text()),
            json.loads(Path(args.edits).read_text()),
            args.output,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "changes": len(result["changes"]),
                    "text_count": len(result["output_texts"]),
                }
            )
        )


if __name__ == "__main__":
    main()
