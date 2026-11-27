"""Independent, read-only saved-DXF identity, protection and edit checks.

This module does not import a candidate producer, source graph or its PASS
flags. It compares the actual DXF content and emits actual finite geometry for
a separate raw-pixel reviewer. File-level editing is not a CAD GUI acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from fractions import Fraction
from io import StringIO
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector

SCHEMA = "independent-saved-native-geometry-audit-v1"
APPID = "I2CAD_NATIVE_V2"
HEADER_FIELDS = ("$INSUNITS", "$MEASUREMENT", "$LUNITS", "$AUNITS", "$INSBASE")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _exact(value):
    """Preserve binary64 identity; never round drawing coordinates."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NONFINITE_SAVED_DXF_VALUE")
        return {"binary64": value.hex()}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _exact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)) or hasattr(value, "__iter__"):
        return [_exact(v) for v in value]
    raise TypeError(type(value).__name__)


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entity_identity(entity):
    if not entity.has_xdata(APPID):
        return None
    chunks = [tag.value for tag in entity.get_xdata(APPID) if tag.code == 1000]
    try:
        identity = json.loads("".join(chunks))
    except (ValueError, TypeError):
        raise ValueError("INVALID_SAVED_NATIVE_IDENTITY") from None
    if not isinstance(identity, dict) or not isinstance(identity.get("id"), str):
        raise ValueError("INVALID_SAVED_NATIVE_IDENTITY")
    return identity


def entity_record(entity):
    # Handles and owner handles locate records in a DXF database. Stable object
    # identity remains in exact XDATA; geometry, attributes and other tags stay.
    tags = TagCollector.dxftags(entity, dxfversion=entity.doc.dxfversion)
    return {"type": entity.dxftype(),
            "tags": [[t.code, _exact(t.value)] for t in tags if t.code not in (5, 105, 330)]}


def _index(doc):
    formal, review, errors = {}, [], []
    for entity in doc.modelspace():
        if entity.dxf.layer == "REVIEW":
            review.append(entity)
            continue
        try:
            identity = entity_identity(entity)
        except ValueError as exc:
            errors.append({"handle": entity.dxf.handle, "reason": str(exc)})
            continue
        if identity is None:
            errors.append({"handle": entity.dxf.handle, "reason": "UNIDENTIFIED_FORMAL_ENTITY"})
        elif identity["id"] in formal:
            errors.append({"object_id": identity["id"], "reason": "DUPLICATE_FORMAL_ID"})
        else:
            formal[identity["id"]] = entity
    return formal, review, errors


def _snapshot_doc(doc):
    formal, review, errors = _index(doc)
    blocks = {block.name: {
        "record": entity_record(block.block_record),
        "begin": entity_record(block.block),
        "end": entity_record(block.endblk),
        "members": [entity_record(e) for e in block],
    } for block in doc.blocks if not block.name.startswith("*Model_Space")
              and not block.name.startswith("*Paper_Space")}
    return {
        "schema": SCHEMA, "dxf_version": doc.dxfversion,
        "formal": {oid: entity_record(e) for oid, e in sorted(formal.items())},
        "review": sorted((entity_record(e) for e in review), key=_key),
        "blocks": blocks,
        "styles": {e.dxf.name: entity_record(e) for e in doc.styles},
        "layers": {e.dxf.name: entity_record(e) for e in doc.layers},
        "linetypes": {e.dxf.name: entity_record(e) for e in doc.linetypes},
        "units_and_coordinate_header": {k: _exact(doc.header.get(k)) for k in HEADER_FIELDS},
        "identity_errors": errors,
        "counts": {"formal": len(formal), "review": len(review), "named_blocks": len(blocks)},
        "excluded_database_metadata": ["entity handle (5/105)", "owner handle (330)",
                                       "non-listed header timestamps/GUID/handseed"],
    }


def snapshot_dxf(path):
    result = _snapshot_doc(ezdxf.readfile(path))
    result["file_sha256"] = sha256(path)
    return result


def compare_saved_dxf(baseline_path, candidate_path):
    before, after = snapshot_dxf(baseline_path), snapshot_dxf(candidate_path)
    old_ids, actual_ids = set(before["formal"]), set(after["formal"])
    missing = sorted(old_ids - actual_ids)
    changed = sorted(oid for oid in old_ids & actual_ids
                     if before["formal"][oid] != after["formal"][oid])
    context = {name: before[name] == after[name] for name in (
        "review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")}
    passed = not missing and not changed and all(context.values())
    passed = passed and not before["identity_errors"] and not after["identity_errors"]
    return {"schema": SCHEMA, "status": "PASS" if passed else "FAIL",
            "baseline_sha256": before["file_sha256"], "candidate_sha256": after["file_sha256"],
            "baseline_counts": before["counts"], "candidate_counts": after["counts"],
            "new_object_ids": sorted(actual_ids - old_ids), "missing_old_ids": missing,
            "changed_old_ids": changed, "unchanged_old_object_count": len(old_ids) - len(missing) - len(changed),
            "context_exact": context, "baseline_identity_errors": before["identity_errors"],
            "candidate_identity_errors": after["identity_errors"],
            "comparison": "exact persisted tags, binary64 values and stable XDATA identities",
            "excluded_database_metadata": before["excluded_database_metadata"],
            "source_ownership_verdict": "NOT_ESTABLISHED_BY_SAVED_GEOMETRY_CHECK"}


def _mm_point(point, roi, dpi):
    scale = 25.4 / float(dpi)
    return [(float(point[0]) - roi[0]) * scale, (roi[3] - float(point[1])) * scale]


def check_target_binding(entity, source_object, roi, dpi):
    """Check actual target drawing against explicit finite geometry, exactly.

    A source object supplies a declaration to verify, never an ownership verdict.
    All non-target content is independently compared to the actual baseline.
    """
    kind, geometry = source_object.get("kind"), source_object.get("geometry", {})
    identity = entity_identity(entity) or {}
    checks = {"identity": identity.get("id") == source_object.get("id"),
              "identity_kind": identity.get("kind") == kind,
              "layer": entity.dxf.layer == source_object.get("layer"),
              "extrusion": tuple(entity.dxf.get("extrusion", (0., 0., 1.))) == (0., 0., 1.),
              "thickness_zero": entity.dxf.get("thickness", 0.) == 0.}
    if kind == "LINE" and entity.dxftype() == "LINE":
        expected = [_mm_point(geometry[k], roi, dpi) + [0.] for k in ("start", "end")]
        actual = [list(entity.dxf.start), list(entity.dxf.end)]
        checks["complete_finite_geometry"] = _exact(actual) == _exact(expected)
        checks["nondegenerate_native_geometry"] = actual[0] != actual[1]
    elif kind == "CONNECTION_PATH" and entity.dxftype() == "LWPOLYLINE":
        points = geometry.get("points", [])
        bulges = geometry.get("bulges", [0.] * len(points))
        # DXF omits zero bulges; its decoded default is positive zero.
        expected = [[*_mm_point(p, roi, dpi), 0., 0., -float(b) if b else 0.]
                    for p, b in zip(points, bulges)]
        actual = [list(row) for row in entity.get_points("xyseb")]
        checks.update(complete_finite_geometry=_exact(actual) == _exact(expected),
                      vertex_count=len(points) == len(bulges) == len(actual),
                      nondegenerate_native_geometry=len(actual) >= 2 and
                          all(a[:2] != b[:2] for a, b in zip(actual, actual[1:])),
                      open_polyline=entity.closed is False and geometry.get("closed", False) is False,
                      elevation_zero=entity.dxf.elevation == 0.,
                      constant_width_zero=entity.dxf.get("const_width", 0.) == 0.)
    else:
        checks["supported_native_type"] = False
    return {"object_id": source_object.get("id"), "handle": entity.dxf.handle,
            "actual_native_type": entity.dxftype(), "checks": checks, "pass": all(checks.values()),
            "ownership_claim_consumed": False}


def audit_saved_target_bindings(dxf_path, metadata_path, target_ids, *, expected_roi=None,
                                expected_dpi=None, expected_source_sha256=None):
    doc = ezdxf.readfile(dxf_path)
    actual, _, identity_errors = _index(doc)
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    rows = metadata.get("objects", [])
    ids = [o.get("id") for o in rows]
    duplicates = sorted(k for k, count in Counter(ids).items() if count != 1)
    declarations = {o["id"]: o for o in rows}
    written_ids = [o.get("id") for o in metadata.get("written", [])]
    file_checks = {
        "actual_dxf_sha256": metadata.get("dxf_sha256") == sha256(dxf_path),
        "declared_ids_unique": not duplicates,
        "actual_and_declared_ids_exact": set(actual) == set(ids),
        "written_id_set_exact": len(written_ids) == len(set(written_ids)) and set(written_ids) == set(ids),
        "actual_identity_valid": not identity_errors,
        "paper_mm_units": doc.units == 4 and metadata.get("unit") == "paper_mm",
        "external_source_frame_supplied": expected_roi is not None and expected_dpi is not None
                                           and expected_source_sha256 is not None,
        "roi_matches_external_source_frame": metadata.get("roi_xyxy_px") == expected_roi,
        "dpi_matches_external_source_frame": metadata.get("dpi") == expected_dpi,
        "source_hash_matches_external_source": metadata.get("source_sha256") == expected_source_sha256,
    }
    checks = []
    for oid in target_ids:
        if oid not in actual or oid not in declarations:
            checks.append({"object_id": oid, "pass": False, "reason": "TARGET_MISSING"})
        else:
            checks.append(check_target_binding(actual[oid], declarations[oid], metadata["roi_xyxy_px"], metadata["dpi"]))
    return {"schema": SCHEMA, "status": "PASS" if all(file_checks.values()) and all(r["pass"] for r in checks) else "FAIL",
            "dxf_sha256": sha256(dxf_path), "metadata_sha256": sha256(metadata_path),
            "file_checks": file_checks, "target_checks": checks, "identity_errors": identity_errors,
            "source_responsibility": "NOT_ESTABLISHED_BY_MATCHING_A_DECLARATION"}


def _source_point(point, roi, dpi):
    scale = 25.4 / float(dpi)
    return [float(point[0]) / scale + roi[0], roi[3] - float(point[1]) / scale]


def _member_geometry(entity, identity, parent, index, roi, dpi):
    kind = entity.dxftype()
    row = {"object_id": identity, "parent_object_id": parent, "member_index": index,
           "kind": kind, "handle": entity.dxf.get("handle"), "closed": False,
           "actual_saved_geometry": True, "width_unit": "saved_dxf_mm",
           "bbox_scope": "UNVERIFIED_CONTEXT_BOUND", "coverage_valid": False}
    if kind == "LINE":
        row.update(points=[_source_point(entity.dxf.start, roi, dpi), _source_point(entity.dxf.end, roi, dpi)], bulges=[0., 0.])
        if entity.dxf.start.z != 0. or entity.dxf.end.z != 0.:
            row["unsupported_reason"] = "NONPLANAR_NATIVE_LINE"
        elif entity.dxf.get("thickness", 0.) != 0.:
            row["unsupported_reason"] = "LINE_THICKNESS_REQUIRES_AREA_AUDIT"
    elif kind == "LWPOLYLINE":
        vertices = list(entity.get_points("xyseb"))
        row.update(points=[_source_point(v, roi, dpi) for v in vertices],
                   bulges=[-float(v[4]) for v in vertices], closed=bool(entity.closed),
                   widths=[[float(v[2]), float(v[3])] for v in vertices],
                   constant_width=float(entity.dxf.get("const_width", 0.)))
        if entity.dxf.elevation != 0. or tuple(entity.dxf.get("extrusion", (0., 0., 1.))) != (0., 0., 1.):
            row["unsupported_reason"] = "NONPLANAR_NATIVE_POLYLINE"
        elif any(row["bulges"]):
            row["unsupported_reason"] = "CURVED_SEGMENTS_REQUIRE_EXACT_CURVE_AUDIT"
        elif row["constant_width"] or any(any(w) for w in row["widths"]):
            row["unsupported_reason"] = "FINITE_WIDTH_POLYLINE_REQUIRES_AREA_AUDIT"
    else:
        row.update(points=[], bulges=[], unsupported_reason="NON_LINEAR_NATIVE_MEMBER")
    if row.get("points") and not any(row.get("bulges", [])):
        x, y = zip(*row["points"])
        row["bbox_xyxy"] = [min(x), min(y), max(x), max(y)]
        row["bbox_scope"] = "FINITE_CENTERLINE_ONLY"
        row["coverage_valid"] = not row.get("unsupported_reason")
    elif kind in ("CIRCLE", "ARC") and tuple(entity.dxf.get("extrusion", (0., 0., 1.))) == (0., 0., 1.) and entity.dxf.center.z == 0. and entity.dxf.get("thickness", 0.) == 0.:
        # Full-circle enclosure also conservatively contains an ARC. Evaluate
        # bounds as exact rationals of stored floats and round only outwards.
        cx, cy, radius = map(Fraction, (entity.dxf.center.x, entity.dxf.center.y, entity.dxf.radius))
        scale = Fraction(25.4 / float(dpi))
        exact = [(cx - radius) / scale + Fraction(roi[0]),
                 Fraction(roi[3]) - (cy + radius) / scale,
                 (cx + radius) / scale + Fraction(roi[0]),
                 Fraction(roi[3]) - (cy - radius) / scale]
        bounds = []
        for i, value in enumerate(exact):
            rounded = float(value)
            if (i < 2 and Fraction(rounded) > value) or (i >= 2 and Fraction(rounded) < value):
                rounded = math.nextafter(rounded, -math.inf if i < 2 else math.inf)
            bounds.append(rounded)
        row.update(bbox_xyxy=bounds, bbox_scope="CONSERVATIVE_FULL_CIRCLE_AREA_BOUND", coverage_valid=True)
    else:
        try:
            bounds = bbox.extents([entity], fast=False)
            if bounds.has_data:
                a, b = _source_point(bounds.extmin, roi, dpi), _source_point(bounds.extmax, roi, dpi)
                row["bbox_xyxy"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
            else:
                row["bbox_unavailable"] = True
        except (ValueError, TypeError, ezdxf.DXFError):
            row["bbox_unavailable"] = True
    return row


def saved_source_geometries(path, roi, dpi):
    """Read actual standalone and block-member geometry; never flatten curves."""
    doc = ezdxf.readfile(path)
    formal, _, errors = _index(doc)
    result = []

    def visit(entity, parent, member_path=(), block_stack=()):
        identity = parent if not member_path else parent + "/member:" + ".".join(map(str, member_path))
        if entity.dxftype() == "INSERT":
            def unresolved(reason, detail=None):
                result.append({"object_id": identity + "/unresolved", "parent_object_id": parent,
                               "kind": "INSERT", "points": [], "bulges": [], "closed": False,
                               "bbox_unavailable": True, "unsupported_reason": reason,
                               "detail": detail, "actual_saved_geometry": True,
                               "bbox_scope": "UNAVAILABLE", "coverage_valid": False})
            if entity.mcount > 1:
                unresolved("MULTIPLE_INSERT_REQUIRES_COMPLETE_INSTANCE_AUDIT")
                return
            if entity.dxf.name in block_stack:
                unresolved("RECURSIVE_BLOCK_REFERENCE")
                return
            if entity.has_extension_dict:
                # virtual_entities() ignores XCLIP. An unknown extension is
                # therefore explicitly unresolved, never silently discarded.
                unresolved("BLOCK_EXTENSION_REQUIRES_CLIPPING_AUDIT")
            skipped = []
            try:
                virtual = list(entity.virtual_entities(
                    skipped_entity_callback=lambda member, reason: skipped.append(
                        {"native_type": member.dxftype(), "reason": reason})))
                for index, member in enumerate(virtual):
                    visit(member, parent, (*member_path, index), (*block_stack, entity.dxf.name))
                for index, attribute in enumerate(entity.attribs, start=len(virtual)):
                    result.append(_member_geometry(attribute,
                        parent + "/member:" + ".".join(map(str, (*member_path, index))),
                        parent, [*member_path, index], roi, dpi))
                if skipped:
                    unresolved("UNTRANSFORMED_BLOCK_MEMBERS", skipped)
            except (ValueError, TypeError, ZeroDivisionError, ezdxf.DXFError) as exc:
                unresolved("BLOCK_TRANSFORM_UNRESOLVED", type(exc).__name__)
        else:
            result.append(_member_geometry(entity, identity, parent, list(member_path), roi, dpi))

    for oid, entity in sorted(formal.items()):
        visit(entity, oid)
    return {"schema": SCHEMA, "dxf_sha256": sha256(path), "roi_xyxy": list(roi), "dpi": dpi,
            "geometry_origin": "ACTUAL_SAVED_DXF_COLD_READ", "geometries": result,
            "identity_errors": errors, "curves_replaced_by_chords": False,
            "source_coordinate_transform": "x=x_mm/(25.4/dpi)+roi_x0; y=roi_y1-y_mm/(25.4/dpi)"}


def make_edit_copy(original, destination, target_id, operation, delta_mm=(11., -7., 0.)):
    destination = Path(destination)
    if destination.exists() or destination.resolve() == Path(original).resolve():
        raise ValueError("EDIT_DESTINATION_MUST_BE_NEW")
    doc = ezdxf.readfile(original)
    entities, _, errors = _index(doc)
    if errors or target_id not in entities:
        raise ValueError("INVALID_EDIT_TARGET_IDENTITY")
    target = entities[target_id]
    if operation == "delete":
        doc.modelspace().delete_entity(target)
    elif operation == "move":
        target.translate(*delta_mm)
    else:
        raise ValueError("UNKNOWN_EDIT_OPERATION")
    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(destination)
    return {"original_sha256": sha256(original), "edited_sha256": sha256(destination),
            "target_id": target_id, "operation": operation, "delta_mm": list(delta_mm),
            "operation_mode": "PROGRAMMATIC_EZDXF_SAVE_NOT_CAD_GUI"}


def audit_edit_copy(original, edited, target_id, operation, delta_mm=(11., -7., 0.)):
    """Reopen both files. Translate the whole expected entity, not a preview."""
    original_doc, edited_doc = ezdxf.readfile(original), ezdxf.readfile(edited)
    before = _snapshot_doc(original_doc)
    after = _snapshot_doc(edited_doc)
    actual, _, errors = _index(original_doc)
    target = actual.get(target_id)
    if target is None or errors:
        return {"schema": SCHEMA, "status": "FAIL", "reason": "INVALID_EDIT_SOURCE"}
    expected_ids = set(before["formal"])
    if operation == "delete":
        expected_ids.remove(target_id)
        target_ok = target_id not in after["formal"]
    elif operation == "move":
        target.translate(*delta_mm)
        # A transform may materialize optional DXF defaults in memory; the
        # serializer legally omits them. Compare two persisted representations,
        # without rounding coordinates or dropping any geometry attributes.
        stream = StringIO()
        original_doc.write(stream)
        stream.seek(0)
        expected_saved, _, expected_errors = _index(ezdxf.read(stream))
        target_ok = (not expected_errors and
                     after["formal"].get(target_id) == entity_record(expected_saved[target_id]))
    else:
        return {"schema": SCHEMA, "status": "FAIL", "reason": "UNKNOWN_EDIT_OPERATION"}
    others = set(before["formal"]) - {target_id}
    changed = sorted(oid for oid in others if before["formal"][oid] != after["formal"].get(oid))
    context = {name: before[name] == after[name] for name in (
        "review", "blocks", "styles", "layers", "linetypes", "units_and_coordinate_header")}
    checks = {"complete_target_operation": target_ok, "exact_non_target_content": not changed,
              "exact_actual_id_set": set(after["formal"]) == expected_ids,
              "actual_identities_valid": not after["identity_errors"], **context}
    return {"schema": SCHEMA, "status": "PASS" if all(checks.values()) else "FAIL",
            "original_sha256": sha256(original), "edited_sha256": sha256(edited),
            "target_id": target_id, "operation": operation, "delta_mm": list(delta_mm),
            "checks": checks, "changed_non_target_ids": changed,
            "non_target_object_count": len(others), "actual_counts_after_edit": after["counts"],
            "verification_mode": "ACTUAL_FILES_REOPENED_BY_CALLING_PROCESS",
            "source_responsibility_verdict": "NOT_ESTABLISHED_BY_EDIT_ISOLATION"}
