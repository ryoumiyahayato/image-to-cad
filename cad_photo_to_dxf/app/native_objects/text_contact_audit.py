"""Cold proof of actual independent text-contact geometry and its neighbors.

The target set is the union of saved identities, candidates and the adoption
receipt.  A LINE or ARC is not skipped because it is not a polyline.  Repeated
segments are permitted only on the same saved handle, at the exact indices of
an unchanged, replayed original source-core cover.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np

from .text_contact_adoption import (
    EVIDENCE_SCHEMA,
    FIELD,
    SCHEMA,
    _as_path,
    _native_object,
    _path_source_checks,
    digest,
    object_binding,
    shared_existing_line_contact,
    whole_old_line_responsibility,
)


EPS = 1e-7


def _source_evidence(obj):
    evidence = obj.get("source_evidence") if isinstance(obj, dict) else None
    return evidence if isinstance(evidence, dict) else {}


def _identity(entity):
    try:
        return json.loads(entity.get_xdata("I2CAD_NATIVE_V2")[0].value)
    except (AttributeError, TypeError, ValueError, IndexError):
        return {}
    except Exception as exc:
        # ezdxf raises a DXFValueError when a consumer removed the appid.
        if exc.__class__.__module__.startswith("ezdxf"):
            return {}
        raise


def _same(a, b):
    if a is None or isinstance(a, (str, bool)):
        return a == b
    try:
        left, right = np.asarray(a, float), np.asarray(b, float)
        return bool(
            left.shape == right.shape
            and np.isfinite(left).all()
            and np.isfinite(right).all()
            and np.allclose(left, right, atol=EPS, rtol=0)
        )
    except (TypeError, ValueError):
        return False


def _angle_same(a, b):
    return abs((float(a) - float(b) + 180) % 360 - 180) <= EPS


def _px(point, roi, dpi):
    mm = 25.4 / float(dpi)
    return [float(point[0]) / mm + roi[0], roi[3] - float(point[1]) / mm]


def _primitive_matches(entity, kind, geometry, roi, dpi):
    mm = 25.4 / float(dpi)
    checks = {
        "native_type": entity.dxftype()
        == {"CONNECTION_PATH": "LWPOLYLINE"}.get(kind, kind)
    }
    if not checks["native_type"]:
        return checks
    checks["default_plane"] = _same(entity.dxf.get("extrusion", (0, 0, 1)), [0, 0, 1])
    checks["zero_thickness"] = abs(float(entity.dxf.get("thickness", 0))) <= EPS
    if kind == "LINE":
        checks.update(
            start=_same(_px(entity.dxf.start, roi, dpi), geometry["start"]),
            end=_same(_px(entity.dxf.end, roi, dpi), geometry["end"]),
            zero_z=_same([entity.dxf.start.z, entity.dxf.end.z], [0, 0]),
        )
    elif kind in ("CIRCLE", "ARC"):
        checks.update(
            center=_same(_px(entity.dxf.center, roi, dpi), geometry["center"]),
            radius=_same(float(entity.dxf.radius) / mm, geometry["radius_px"]),
            zero_z=abs(float(entity.dxf.center.z)) <= EPS,
        )
        if kind == "ARC":
            sweep = float(
                geometry.get(
                    "sweep_deg_image",
                    geometry["end_deg_image"] - geometry["start_deg_image"],
                )
            )
            start, end = (
                -float(geometry["start_deg_image"]),
                -float(geometry["end_deg_image"]),
            )
            if sweep > 0:
                start, end = end, start
            checks.update(
                start_angle=_angle_same(entity.dxf.start_angle, start),
                end_angle=_angle_same(entity.dxf.end_angle, end),
            )
    elif kind == "CONNECTION_PATH":
        points = list(entity.get_points("xyseb"))
        checks.update(
            vertices=_same(
                [_px(point, roi, dpi) for point in points], geometry["points"]
            ),
            bulges=_same([-float(point[4]) for point in points], geometry["bulges"]),
            closed=bool(entity.closed) == bool(geometry.get("closed", False)),
            zero_widths=all(
                abs(float(value)) <= EPS for point in points for value in point[2:4]
            ),
            zero_constant_width=abs(float(entity.dxf.get("const_width", 0))) <= EPS,
            zero_elevation=abs(float(entity.dxf.get("elevation", 0))) <= EPS,
        )
    else:
        checks["supported_primitive_contract"] = False
    return checks


def _text_matches(entity, obj, roi, dpi, font_path, *, block_member=False):
    from .single_line_text_audit import _expected_attributes, text_attributes

    if entity.dxftype() != "TEXT":
        return False
    style = entity.doc.styles.get(entity.dxf.style)
    if (style.dxf.font != Path(font_path).name or style.dxf.width != 1.0
            or style.dxf.height != 0.0 or style.dxf.oblique != 0.0):
        return False
    expected, _ = _expected_attributes(
        entity,
        obj,
        roi,
        dpi,
        font_path,
        "single_line_recovery" in _source_evidence(obj),
    )
    actual = text_attributes(entity)
    # ezdxf's virtual TEXT transform materializes an unused alignment point at
    # INSERT for left/baseline text.  Content, insertion, size and alignment
    # modes remain independently checked.
    ignored = {"color", "layer", "align_point"} if block_member else set()
    return all(
        _same(value, actual.get(key))
        for key, value in expected.items()
        if key not in ignored
    )


def _neighbor_matches(entity, obj, roi, dpi, font_path):
    """Compare actual top-level geometry and all members of protected groups."""
    kind, geometry = obj["kind"], obj["geometry"]
    if entity.dxf.layer != obj["layer"] or int(entity.dxf.color) != 256:
        return False
    if kind in ("LINE", "ARC", "CIRCLE", "CONNECTION_PATH"):
        return all(_primitive_matches(entity, kind, geometry, roi, dpi).values())
    if kind == "TEXT":
        return _text_matches(entity, obj, roi, dpi, font_path)
    if kind not in ("CIRCULAR_MARKER", "ROOM_LABEL", "WALL_SEGMENT", "DOOR"):
        return False  # An unsupported neighbor contract is explicit, never a pass.
    if (
        entity.dxftype() != "INSERT"
        or entity.dxf.name != "I2CAD_" + obj["id"].replace("-", "_")
        or not _same(
            [
                entity.dxf.xscale,
                entity.dxf.yscale,
                entity.dxf.zscale,
                entity.dxf.rotation,
            ],
            [1, 1, 1, 0],
        )
    ):
        return False
    members = list(entity.virtual_entities())
    if kind == "CIRCULAR_MARKER":
        from .cad_io import _circular_text_placement

        if len(members) != 2 or not all(
            _primitive_matches(
                members[0], "CIRCLE", geometry["circle_geometry"], roi, dpi
            ).values()
        ):
            return False
        text = members[1]
        if text.dxftype() != "TEXT":
            return False
        g = geometry["text_geometry"]
        mm = 25.4 / float(dpi)
        layout = _circular_text_placement(g, mm, font_path)
        insert = [
            (g["x"] - roi[0]) * mm - layout["baseline_offset_mm"][0],
            (roi[3] - g["y"]) * mm - layout["baseline_offset_mm"][1],
            0.0,
        ]
        return (
            text.dxf.text == g["text"]
            and _same(list(text.dxf.insert), insert)
            and _same(text.dxf.height, layout["height"])
            and _same(text.dxf.width, layout["width"])
            and _angle_same(text.dxf.rotation, -float(g.get("rotation_deg_image", 0)))
        )
    if kind == "ROOM_LABEL":
        frame = {
            "points": geometry["frame_points"],
            "bulges": [0.0] * len(geometry["frame_points"]),
            "closed": True,
        }
        remainders = geometry.get("frame_source_remainders", [])
        if len(members) != 2 + len(remainders):
            return False
        if not all(
            _primitive_matches(members[0], "CONNECTION_PATH", frame, roi, dpi).values()
        ):
            return False
        pseudo = {"kind": "TEXT", "layer": "0", "geometry": geometry["text_geometry"]}
        if not _text_matches(
            members[1], pseudo, roi, dpi, font_path, block_member=True
        ):
            return False
        return all(
            all(
                _primitive_matches(
                    actual, expected["kind"], expected["geometry"], roi, dpi
                ).values()
            )
            for actual, expected in zip(members[2:], remainders)
        )
    if kind == "WALL_SEGMENT":
        expected_members = geometry["members"]
    else:
        from .door_completion import native_members

        expected_members = native_members(obj)
    return len(members) == len(expected_members) and all(
        all(
            _primitive_matches(
                actual, expected["kind"], expected["geometry"], roi, dpi
            ).values()
        )
        for actual, expected in zip(members, expected_members)
    )


def _edge(a, b):
    return tuple(sorted((tuple(map(float, a)), tuple(map(float, b)))))


def _cover_allowances(entity, path, plan_key):
    if entity.dxftype() != "LWPOLYLINE" or entity.closed:
        return []
    geometry = path["representation"]
    points, bulges = geometry["points"], geometry["bulges"]
    occurrences = defaultdict(list)
    for index, (a, b) in enumerate(zip(points, points[1:])):
        if float(bulges[index]) == 0:
            occurrences[_edge(a, b)].append(index)
    source_counts = Counter(
        _edge(a, b) for a, b in zip(path["source_path_px"], path["source_path_px"][1:])
    )
    covers = path.get("bounded_original_cycle_covers", [])
    allowances = []
    for edge, indices in occurrences.items():
        if len(indices) < 2 or source_counts[edge] < len(indices):
            continue
        owners = [
            index
            for index, cover in enumerate(covers)
            if edge in {_edge(a, b) for a, b in cover.get("source_core_edges", [])}
        ]
        if len(owners) != 1:
            continue
        for pair in itertools.combinations(indices, 2):
            allowances.append(
                {
                    "handle": entity.dxf.handle,
                    "segment_indices": list(pair),
                    "source_edge": [list(point) for point in edge],
                    "plan_sha256": plan_key,
                    "source_cover_index": owners[0],
                    "actual_geometry_and_original_plan_replayed": True,
                    "scope": "same actual modelspace handle and these two native segment indices only",
                }
            )
    return allowances


def _actual_geometry(doc, roi, dpi):
    """Read actual primitives, including members; never use claimed candidates."""
    lines, curves = [], []
    mm = 25.4 / float(dpi)
    for parent in doc.modelspace():
        if parent.dxf.layer == "REVIEW":
            continue
        members = (
            list(parent.virtual_entities())
            if parent.dxftype() == "INSERT"
            else [parent]
        )
        for member_index, entity in enumerate(members):
            common = {
                "handle": parent.dxf.handle,
                "id": _identity(parent).get("id"),
                "member": member_index,
            }
            if entity.dxftype() == "LWPOLYLINE":
                primitives = list(entity.virtual_entities())
            else:
                primitives = [entity]
            for index, primitive in enumerate(primitives):
                row = {**common, "segment": index}
                if primitive.dxftype() == "LINE":
                    a, b = (
                        np.asarray(_px(primitive.dxf.start, roi, dpi)),
                        np.asarray(_px(primitive.dxf.end, roi, dpi)),
                    )
                    if np.linalg.norm(b - a) > EPS:
                        lines.append({**row, "a": a, "b": b})
                elif primitive.dxftype() in ("ARC", "CIRCLE"):
                    circle = primitive.dxftype() == "CIRCLE"
                    curves.append(
                        {
                            **row,
                            "center": _px(primitive.dxf.center, roi, dpi),
                            "radius": float(primitive.dxf.radius) / mm,
                            "start": 0.0
                            if circle
                            else -float(primitive.dxf.end_angle) % 360,
                            "sweep": 360.0
                            if circle
                            else (
                                float(primitive.dxf.end_angle)
                                - float(primitive.dxf.start_angle)
                            )
                            % 360,
                        }
                    )
    return lines, curves


def _actual_duplicates(doc, roi, dpi, target_handles, allowances):
    lines, curves = _actual_geometry(doc, roi, dpi)
    allowed = {(row["handle"], *sorted(row["segment_indices"])) for row in allowances}
    conflicts, active = [], []
    for line in sorted(lines, key=lambda row: float(min(row["a"][0], row["b"][0]))):
        a, b = line["a"], line["b"]
        low, high = np.minimum(a, b), np.maximum(a, b)
        active = [
            old for old in active if max(old["a"][0], old["b"][0]) >= low[0] - EPS
        ]
        axis, length = b - a, float(np.linalg.norm(b - a))
        axis /= length
        for old in active:
            if not ({line["handle"], old["handle"]} & target_handles):
                continue
            c, d = old["a"], old["b"]
            if max(c[1], d[1]) < low[1] - EPS or min(c[1], d[1]) > high[1] + EPS:
                continue
            offsets = np.asarray([c - a, d - a])
            if np.max(np.abs(offsets[:, 0] * axis[1] - offsets[:, 1] * axis[0])) > EPS:
                continue
            start, end = sorted(float(p @ axis) for p in offsets)
            overlap = min(length, end) - max(0.0, start)
            if overlap <= EPS:
                continue
            same_handle_allowance = (
                line["handle"],
                *sorted((line["segment"], old["segment"])),
            )
            if (
                line["handle"] == old["handle"]
                and line["member"] == old["member"] == 0
                and same_handle_allowance in allowed
            ):
                continue
            conflicts.append(
                {
                    "handles": [old["handle"], line["handle"]],
                    "object_ids": [old["id"], line["id"]],
                    "segment_indices": [old["segment"], line["segment"]],
                    "positive_coincident_length_px": overlap,
                    "reason": "UNPROVED_POSITIVE_NATIVE_LINE_OVERLAP",
                }
            )
        active.append(line)

    def intervals(curve):
        start, end = curve["start"], curve["start"] + curve["sweep"]
        return (
            [(0.0, 360.0)]
            if curve["sweep"] == 360
            else [(start, min(360.0, end))] + ([(0.0, end - 360)] if end > 360 else [])
        )

    for index, left in enumerate(curves):
        for right in curves[index + 1 :]:
            if not ({left["handle"], right["handle"]} & target_handles):
                continue
            if not (
                _same(left["center"], right["center"])
                and _same(left["radius"], right["radius"])
            ):
                continue
            degrees = sum(
                max(0.0, min(b, d) - max(a, c))
                for a, b in intervals(left)
                for c, d in intervals(right)
            )
            if math.radians(degrees) * left["radius"] > EPS:
                conflicts.append(
                    {
                        "handles": [left["handle"], right["handle"]],
                        "object_ids": [left["id"], right["id"]],
                        "reason": "UNPROVED_POSITIVE_NATIVE_CURVE_OVERLAP",
                        "coincident_sweep_deg": degrees,
                    }
                )
    return conflicts


def cold_text_contact_bindings(path, doc, gray, roi, dpi, evidence_root):
    """Return source checks and narrowly scoped saved-segment allowances."""
    path, evidence_root = Path(path), Path(evidence_root)
    actual = defaultdict(list)
    flagged = set()
    for entity in doc.modelspace():
        ident = _identity(entity)
        if ident.get("id"):
            actual[ident["id"]].append(entity)
        if ident.get(FIELD):
            flagged.add(ident.get("id") or "UNIDENTIFIED:" + entity.dxf.handle)
    metadata, manifest, load_errors = {}, {}, []
    manifest_path = evidence_root / "text_contact" / "adoption.json"
    try:
        metadata = json.loads(
            path.with_suffix(".objects.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        load_errors.append("CONTACT_METADATA_UNREADABLE: " + str(exc))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if manifest_path.exists() or flagged:
            load_errors.append("CONTACT_ADOPTION_MANIFEST_UNREADABLE: " + str(exc))
    objects = {obj["id"]: obj for obj in metadata.get("objects", [])}
    receipts = {obj["id"]: obj for obj in metadata.get("written", [])}
    adopted = {obj["id"]: obj for obj in manifest.get("objects", [])}
    decision_ids = {
        row["id"] for row in manifest.get("decisions", []) if row.get("adopted")
    }
    targets = (
        flagged
        | set(adopted)
        | decision_ids
        | {oid for oid, obj in objects.items() if FIELD in _source_evidence(obj)}
    )
    result = {
        "schema": "saved-text-contact-source-audit-v1",
        "checks": [],
        "allowances": [],
        "target_ids": sorted(targets),
        "duplicate_conflicts": [],
        "source_or_DXF_geometry_modified": False,
        "pass": True,
    }
    if not targets and not manifest:
        return result
    global_checks = {
        "metadata_loaded": not load_errors,
        "manifest_schema": manifest.get("schema") == SCHEMA,
        "sidecar_bound_to_actual_saved_DXF": metadata.get("dxf_sha256")
        == hashlib.sha256(path.read_bytes()).hexdigest(),
        "same_roi_and_dpi": metadata.get("roi_xyxy_px")
        == list(roi)
        == manifest.get("roi_xyxy_px")
        and metadata.get("dpi") == dpi,
        "same_original_source_identity": metadata.get("source_sha256")
        == manifest.get("source_sha256"),
        "unique_metadata_object_ids": len(objects) == len(metadata.get("objects", [])),
        "unique_written_ids": len(receipts) == len(metadata.get("written", [])),
        "unique_adopted_ids": len(adopted) == len(manifest.get("objects", [])),
        "adopted_decisions_match_actual_contracts": decision_ids == set(adopted),
        "no_partial_old_retirement": manifest.get(
            "partial_old_entity_retirement_permitted"
        )
        is False,
    }
    result["checks"].append(
        {
            "id": "TEXT_CONTACT_MANIFEST",
            "type": "TEXT_CONTACT_MANIFEST_BINDING",
            "pass": all(global_checks.values()),
            "checks": global_checks,
            "failures": load_errors,
        }
    )
    plan_checks, context = {}, None
    from .text_contact_geometry import (
        build_text_contact_source_graph,
        verify_text_contact_geometry_plan,
    )

    target_handles = set()
    for oid in sorted(targets):
        row = {
            "id": oid,
            "type": "SAVED_TEXT_CONTACT_PATH_SOURCE",
            "pass": False,
            "checks": {},
        }
        checks = row["checks"]
        try:
            if not all(global_checks.values()):
                raise ValueError("CONTACT_GLOBAL_BINDING_FAILED")
            obj, claimed, receipt = (
                objects.get(oid),
                adopted.get(oid),
                receipts.get(oid),
            )
            if (
                obj is None
                or claimed is None
                or receipt is None
                or len(actual.get(oid, [])) != 1
            ):
                raise ValueError(
                    "CONTACT_ACTUAL_CANDIDATE_OR_RECEIPT_MISSING_OR_DUPLICATED"
                )
            entity = actual[oid][0]
            target_handles.add(entity.dxf.handle)
            proof = _source_evidence(obj).get(FIELD, {})
            proof = proof if isinstance(proof, dict) else {}
            checks["three_way_object_binding"] = object_binding(obj) == object_binding(
                claimed
            ) and _source_evidence(obj).get(FIELD) == _source_evidence(claimed).get(
                FIELD
            )
            checks["actual_identity_and_flag"] = (
                _identity(entity).get("kind") == obj["kind"]
                and _identity(entity).get(FIELD) is True
            )
            checks["saved_native_receipt"] = (
                receipt.get("handle") == entity.dxf.handle
                and receipt.get("kind") == obj["kind"]
                and receipt.get("type") == entity.dxftype()
            )
            checks["actual_layer"] = entity.dxf.layer == obj["layer"]
            checks.update(
                {
                    "actual_" + key: value
                    for key, value in _primitive_matches(
                        entity, obj["kind"], obj["geometry"], roi, dpi
                    ).items()
                }
            )
            checks["source_evidence_schema"] = proof.get("schema") == EVIDENCE_SCHEMA
            checks["source_identity"] = (
                proof.get("source_sha256") == manifest["source_sha256"]
            )
            key = proof["plan_sha256"]
            plan = manifest["geometry_plans"][key]
            checks["plan_digest"] = digest(plan) == key
            selected = plan["paths"][proof["path_index"]]
            checks["selected_original_path_digest"] = (
                proof.get("path_sha256") == digest(selected)
                and proof.get("path") == selected
            )
            expected_kind, expected_geometry = _native_object(
                selected["representation"]
            )
            checks["whole_native_representation_from_source_plan"] = (
                expected_kind == obj["kind"] and expected_geometry == obj["geometry"]
            )
            if key not in plan_checks:
                if context is None:
                    context = build_text_contact_source_graph(np.asarray(gray), roi)
                plan_checks[key] = verify_text_contact_geometry_plan(
                    gray, roi, plan, source_graph=context
                )
            row["original_source_plan_replay"] = {
                name: value
                for name, value in plan_checks[key].items()
                if name != "replayed_paths"
            }
            checks["original_source_plan_replayed"] = plan_checks[key]["pass"]
            row["actual_source_geometry"] = _path_source_checks(
                np.asarray(gray), plan, selected
            )
            checks["original_source_geometry_supported"] = row[
                "actual_source_geometry"
            ]["pass"]
            shared_checks = []
            prior_bindings = {
                old["id"]: old for old in manifest.get("prior_object_bindings", [])
            }
            for declaration in (
                _source_evidence(claimed)
                .get("text_contact_responsibility", {})
                .get("shared_existing_line_contacts", [])
            ):
                old = prior_bindings[declaration["prior_object_id"]]
                fresh = shared_existing_line_contact(
                    gray, _as_path(obj), old, declaration["overlap"]
                )
                shared_checks.append(
                    {
                        "prior_object_id": old["id"],
                        "pass": fresh["pass"] and fresh == declaration,
                    }
                )
            row["shared_neighbor_source_checks"] = shared_checks
            checks["shared_neighbor_source_cores_replayed"] = all(
                item["pass"] for item in shared_checks
            )
            row["pass"] = all(checks.values())
            if row["pass"]:
                result["allowances"].extend(_cover_allowances(entity, selected, key))
        except (KeyError, ValueError, TypeError, IndexError, OSError) as exc:
            row["failure"] = type(exc).__name__ + ": " + str(exc)
        result["checks"].append(row)
    retired = set(manifest.get("retired_ids", []))
    planned_retirements = {
        oid
        for row in manifest.get("decisions", [])
        if row.get("adopted")
        for oid in row.get("retired_ids", [])
    }
    prior = {row["id"]: row for row in manifest.get("prior_object_bindings", [])}
    retirement_checks = {
        "decision_set_matches": retired == planned_retirements,
        "all_retirements_were_existing_whole_objects": retired <= set(prior),
        "all_retired_entities_absent": not (retired & (set(actual) | set(objects))),
    }
    for decision in manifest.get("decisions", []):
        if not decision.get("adopted"):
            continue
        for oid in decision.get("retired_ids", []):
            try:
                proof = whole_old_line_responsibility(
                    gray, _as_path(adopted[decision["id"]]), prior[oid]
                )
                retirement_checks["whole_source_responsibility:" + oid] = proof["pass"]
            except (KeyError, ValueError, TypeError):
                retirement_checks["whole_source_responsibility:" + oid] = False
    result["checks"].append(
        {
            "id": "TEXT_CONTACT_RETIREMENT",
            "type": "SAVED_TEXT_CONTACT_WHOLE_RETIREMENT",
            "pass": all(retirement_checks.values()),
            "checks": retirement_checks,
        }
    )
    neighbors = []
    for oid, binding in sorted(prior.items()):
        if oid in retired:
            continue
        checks = {
            "one_actual_entity": len(actual.get(oid, [])) == 1,
            "candidate_present": oid in objects,
        }
        try:
            obj = objects[oid]
            checks["actual_identity_kind_unchanged"] = (
                checks["one_actual_entity"]
                and _identity(actual[oid][0]).get("kind") == obj["kind"]
            )
            receipt = receipts.get(oid, {})
            checks["actual_written_receipt_matches"] = checks["one_actual_entity"] and (
                receipt.get("handle") == actual[oid][0].dxf.handle
                and receipt.get("kind") == obj["kind"]
                and receipt.get("type") == actual[oid][0].dxftype()
            )
            checks["unchanged_candidate_geometry"] = object_binding(obj) == binding
            neighbor_font = path.parent / "DejaVuSans.ttf"
            if obj["kind"] == "TEXT":
                from .single_line_text_audit import resolve_saved_text_font

                _, neighbor_font, _ = resolve_saved_text_font(path, metadata, obj)
            checks["actual_saved_geometry_matches_protected_candidate"] = checks[
                "one_actual_entity"
            ] and _neighbor_matches(
                actual[oid][0], obj, roi, dpi, neighbor_font
            )
        except (KeyError, ValueError, TypeError, IndexError, OSError):
            checks["actual_saved_geometry_matches_protected_candidate"] = False
        neighbors.append({"id": oid, "pass": all(checks.values()), "checks": checks})
    result["checks"].append(
        {
            "id": "TEXT_CONTACT_NEIGHBORS",
            "type": "SAVED_TEXT_CONTACT_NEIGHBOR_PROTECTION",
            "pass": all(row["pass"] for row in neighbors),
            "protected_count": len(neighbors),
            "objects": neighbors,
        }
    )
    result["duplicate_conflicts"] = _actual_duplicates(
        doc, roi, dpi, target_handles, result["allowances"]
    )
    result["checks"].append(
        {
            "id": "TEXT_CONTACT_DUPLICATES",
            "type": "SAVED_TEXT_CONTACT_NATIVE_DUPLICATES",
            "pass": not result["duplicate_conflicts"],
            "conflicts": result["duplicate_conflicts"],
        }
    )
    result["pass"] = all(row["pass"] for row in result["checks"])
    return result
