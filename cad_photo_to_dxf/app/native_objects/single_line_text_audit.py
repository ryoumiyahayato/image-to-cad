"""Saved ordinary TEXT bindings and replay of newly recovered single lines.

Font ink bounds determine placement only. They are never recognition evidence,
and are not compared pixel-for-pixel with scan noise or a replacement font.
Legacy standalone TEXT retains its existing cap-height/advance-width contract,
measured from the saved adjacent font without a host font-manager fallback.
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import ezdxf
from ezdxf.fonts import fonts
from ezdxf.tools.text import plain_text
import numpy as np

from .contracts import plain

APPID = "I2CAD_NATIVE_V2"
FIELD = "single_line_recovery"
BINDING_SCHEMA = "native-text-geometry-binding-v1"
RECOVERY_SCHEMA = "native-single-line-label-evidence-v1"
EPS = 1e-9


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=plain,
        ).encode("utf-8")
    ).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity(entity):
    try:
        value = json.loads(
            "".join(tag.value for tag in entity.get_xdata(APPID) if tag.code == 1000)
        )
        return (
            value
            if isinstance(value, dict)
            and isinstance(value.get("id"), str)
            and isinstance(value.get("kind"), str)
            else {}
        )
    except (ezdxf.DXFError, ValueError, TypeError):
        return {}


def _source_evidence(obj):
    value = obj.get("source_evidence") if isinstance(obj, dict) else None
    return value if isinstance(value, dict) else {}


def source_row_layout_adoption(obj):
    """Validate a specialized font declaration without accepting arbitrary paths."""
    evidence = _source_evidence(obj).get(FIELD)
    adoption = evidence.get("layout_adoption", {}) if isinstance(evidence, dict) else {}
    if not isinstance(adoption, dict) or adoption.get("selected_layout") is None:
        return None
    from .source_row_font_registry import FONT_SPEC

    if (adoption.get("pass") is not True or adoption.get("font") != FONT_SPEC
            or not isinstance(adoption.get("selected_layout"), dict)):
        raise ValueError("SOURCE_ROW_LAYOUT_OR_FONT_DECLARATION_INVALID")
    return adoption


def resolve_saved_text_font(path, metadata, obj):
    """Bind the actual adjacent bytes and permission to the fixed font profile."""
    path = Path(path)
    adopted = source_row_layout_adoption(obj)
    if adopted is None:
        record = metadata["font"]
        filename, style = "DejaVuSans.ttf", "I2CAD_TEXT"
        if record.get("font") != filename:
            raise ValueError("NATIVE_TEXT_LEGACY_FONT_DECLARATION_CHANGED")
    else:
        from .source_row_font_registry import FONT_SPEC

        filename, style = FONT_SPEC["font"], FONT_SPEC["style"]
        entries = [row for row in metadata.get("fonts", []) if row.get("font") == filename]
        if len(entries) != 1 or any(entries[0].get(k) != v for k, v in FONT_SPEC.items()):
            raise ValueError("SOURCE_ROW_SAVED_FONT_REGISTRY_BINDING_MISSING_OR_CHANGED")
        record = entries[0]
        license_path = path.parent / FONT_SPEC["bundled_license"]
        if (not license_path.is_file() or license_path.is_symlink()
                or license_path.stat().st_size != FONT_SPEC["license_bytes"]
                or _sha(license_path) != FONT_SPEC["license_sha256"]):
            raise ValueError("SOURCE_ROW_SAVED_FONT_PERMISSION_CHANGED")
        companion = path.parent / FONT_SPEC["librecad_font"]
        if (not companion.is_file() or companion.is_symlink()
                or companion.stat().st_size != FONT_SPEC["librecad_bytes"]
                or _sha(companion) != FONT_SPEC["librecad_sha256"]):
            raise ValueError("SOURCE_ROW_SAVED_LFF_COMPANION_CHANGED")
    font_path = path.parent / filename
    if (not font_path.is_file() or font_path.is_symlink()
            or _sha(font_path) != record.get("sha256")):
        raise ValueError("NATIVE_TEXT_ACTUAL_ADJACENT_FONT_BYTES_CHANGED")
    if adopted is not None and font_path.stat().st_size != record["bytes"]:
        raise ValueError("SOURCE_ROW_SAVED_FONT_SIZE_CHANGED")
    return record, font_path, style


def _same(left, right):
    if isinstance(left, (str, bool)) or left is None:
        return left == right
    try:
        a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
        return a.shape == b.shape and bool(
            np.isfinite(a).all()
            and np.isfinite(b).all()
            and np.allclose(a, b, atol=EPS, rtol=0)
        )
    except (TypeError, ValueError):
        return False


def geometry_bbox(geometry):
    text = geometry["text"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or any(ch in text for ch in "\r\n\t")
    ):
        raise ValueError("NATIVE_TEXT_REQUIRES_ONE_LITERAL_NONEMPTY_LINE")
    x, y, width, height, rotation = (
        float(geometry["x"]),
        float(geometry["y"]),
        float(geometry["width_px"]),
        float(geometry["height_px"]),
        float(geometry.get("rotation_deg_image", 0.0)),
    )
    if (
        not all(math.isfinite(v) for v in (x, y, width, height, rotation))
        or min(width, height) <= 0
    ):
        raise ValueError("NATIVE_TEXT_REQUIRES_FINITE_POSITIVE_LAYOUT")
    return [x, y - height, x + width, y]


@lru_cache(maxsize=512)
def _ink_metrics(font_path, font_sha, text):
    # The byte identity in the cache key prevents reuse after a font replacement.
    font = fonts.sideload_ttf(Path(font_path), 1.0)
    bbox = font.text_path(text).bbox()
    if not bbox.has_data:
        raise ValueError("SINGLE_LINE_TEXT_HAS_NO_PORTABLE_FONT_INK")
    values = [
        float(bbox.extmin.x),
        float(bbox.extmin.y),
        float(bbox.extmax.x),
        float(bbox.extmax.y),
    ]
    if (
        not all(math.isfinite(v) for v in values)
        or values[2] <= values[0]
        or values[3] <= values[1]
    ):
        raise ValueError("SINGLE_LINE_TEXT_PORTABLE_FONT_BOUNDS_INVALID")
    return tuple(values)


def source_ink_text_layout(geometry, roi, dpi, font_path):
    """Map the whole string's portable-font ink box to its source ink box."""
    box = geometry_bbox(geometry)
    mm = 25.4 / float(dpi)
    if not math.isfinite(mm) or mm <= 0:
        raise ValueError("NATIVE_TEXT_INVALID_DPI")
    font_path = Path(font_path)
    font_sha = _sha(font_path)
    xmin, ymin, xmax, ymax = _ink_metrics(
        str(font_path.resolve()), font_sha, geometry["text"]
    )
    height = (box[3] - box[1]) * mm / (ymax - ymin)
    width = (box[2] - box[0]) * mm / ((xmax - xmin) * height)
    rotation = -float(geometry.get("rotation_deg_image", 0.0))
    angle = math.radians(rotation)
    c, s = math.cos(angle), math.sin(angle)
    ox, oy = xmin * height * width, ymin * height
    target = ((box[0] - roi[0]) * mm, (roi[3] - box[3]) * mm)
    insert = [target[0] - (c * ox - s * oy), target[1] - (s * ox + c * oy), 0.0]
    return {
        "insert": insert,
        "height": height,
        "width": width,
        "rotation": rotation,
        "font_ink_bounds_at_unit_cap_height": [xmin, ymin, xmax, ymax],
        "source_ink_bbox_xyxy_px": box,
        "font_sha256": font_sha,
        "basis": "whole_literal_string_portable_font_ink_box",
        "font_is_recognition_evidence": False,
        "scan_pixel_equality_required": False,
    }


def text_attributes(entity):
    return {
        "text": entity.dxf.text,
        "insert": list(entity.dxf.insert),
        "height": float(entity.dxf.height),
        "width": float(entity.dxf.width),
        "rotation": float(entity.dxf.rotation),
        "style": entity.dxf.style,
        "halign": int(entity.dxf.halign),
        "valign": int(entity.dxf.valign),
        "align_point": list(entity.dxf.align_point)
        if entity.dxf.align_point is not None
        else None,
        "oblique": float(entity.dxf.oblique),
        "text_generation_flag": int(entity.dxf.text_generation_flag),
        "extrusion": list(entity.dxf.extrusion),
        "thickness": float(entity.dxf.thickness),
        "layer": entity.dxf.layer,
        "color": int(entity.dxf.color),
    }


def _style_attributes(doc, name):
    style = doc.styles.get(name)
    return {
        "name": name,
        "font": style.dxf.font,
        "bigfont": style.dxf.bigfont,
        "width": float(style.dxf.width),
        "height": float(style.dxf.height),
        "oblique": float(style.dxf.oblique),
        "flags": int(style.dxf.flags),
        "generation_flags": int(style.dxf.generation_flags),
    }


def export_text_geometry_binding(entity, obj, font_record, layout=None):
    """Record the exact emitted attributes without altering a legacy entity."""
    evidence = _source_evidence(obj).get(FIELD)
    required = FIELD in _source_evidence(obj)
    if required and (
        not isinstance(evidence, dict) or evidence.get("schema") != RECOVERY_SCHEMA
    ):
        raise ValueError("SINGLE_LINE_TEXT_RECOVERY_SCHEMA_MISSING")
    return {
        "schema": BINDING_SCHEMA,
        "candidate_geometry_sha256": _digest(obj["geometry"]),
        "actual_text_attributes": text_attributes(entity),
        "style_attributes": _style_attributes(entity.doc, entity.dxf.style),
        "font": {"font": font_record["font"], "sha256": font_record["sha256"]},
        "layout_basis": "source_component_affine" if source_row_layout_adoption(obj)
        else "source_ink_box" if required else "legacy_cap_height_and_advance_width",
        "source_ink_layout": layout,
        "requires_single_line_source_replay": required,
        "recovery_evidence_sha256": _digest(evidence) if required else None,
    }


def _expected_attributes(entity, obj, roi, dpi, font_path, recovered):
    geometry = obj["geometry"]
    geometry_bbox(geometry)
    mm = 25.4 / float(dpi)
    common = {
        "text": geometry["text"],
        "style": "I2CAD_TEXT",
        "halign": 0,
        "valign": 0,
        "align_point": None,
        "oblique": 0.0,
        "text_generation_flag": 0,
        "extrusion": [0.0, 0.0, 1.0],
        "thickness": 0.0,
        "layer": obj["layer"],
        "color": 256,
    }
    if recovered:
        adopted = source_row_layout_adoption(obj)
        if adopted is not None:
            from .single_line_source_layout import fit_source_glyph_layout

            fitted = fit_source_glyph_layout(
                geometry, _source_evidence(obj)[FIELD]["source_partition"], roi, dpi, font_path,
            )
            if (not fitted["pass"]
                    or fitted["selected_layout"] != adopted["selected_layout"]):
                raise ValueError("SOURCE_ROW_SAVED_LAYOUT_SOURCE_REPLAY_MISMATCH")
            layout = fitted["selected_layout"]
            common["style"] = adopted["font"]["style"]
        else:
            layout = source_ink_text_layout(geometry, roi, dpi, font_path)
        return {
            **common,
            **{k: layout[k] for k in ("insert", "height", "width", "rotation")},
        }, layout
    common.update(
        insert=[(geometry["x"] - roi[0]) * mm, (roi[3] - geometry["y"]) * mm, 0.0],
        height=geometry["height_px"] * mm,
        rotation=-geometry.get("rotation_deg_image", 0.0),
        width=1.0,
    )
    # Recompute from the bound candidate and actual adjacent font bytes.
    # Reusing text_size(entity) can repeat the writer's host fallback and
    # incorrectly approve a width fitted to a different font.
    measured = fonts.sideload_ttf(
        Path(font_path).resolve(), common["height"]
    ).text_width(plain_text(geometry["text"]))
    if not math.isfinite(measured) or measured <= 0:
        raise ValueError("UNMEASURABLE_LEGACY_NATIVE_TEXT")
    common["width"] = geometry["width_px"] * mm / measured
    return common, None


def cold_native_text_bindings(path, doc, gray, roi, dpi, evidence_root):
    """Union actual entities, object claims and written receipts: none may hide.

    Removing an XDATA recovery flag, its sidecar evidence, written receipt, or
    the entity produces a failed check. Existing TEXT checks bind the saved
    candidate only; they do not claim new OCR/raw-source replay.
    """
    path = Path(path)
    actual, by_handle = defaultdict(list), {}
    actual_text_targets = set()
    for entity in doc.modelspace():
        ident = _identity(entity)
        by_handle[entity.dxf.handle] = entity
        if ident.get("id"):
            actual[ident["id"]].append(entity)
        if entity.dxftype() == "TEXT" and not (
            entity.dxf.layer == "REVIEW" and ident.get("kind") == "REVIEW"
        ):
            actual_text_targets.add(
                ident.get("id") or "UNIDENTIFIED:" + entity.dxf.handle
            )
        if ident.get(FIELD):
            actual_text_targets.add(
                ident.get("id") or "UNIDENTIFIED:" + entity.dxf.handle
            )
    objects, written, load_error, metadata = {}, {}, None, {}
    try:
        metadata = json.loads(
            path.with_suffix(".objects.json").read_text(encoding="utf-8")
        )
        source_rows, write_rows = metadata["objects"], metadata["written"]
        objects = {obj["id"]: obj for obj in source_rows}
        written = {row["id"]: row for row in write_rows}
        if len(objects) != len(source_rows) or len(written) != len(write_rows):
            raise ValueError("NATIVE_TEXT_DUPLICATE_SIDECAR_IDENTITIES")
        if metadata.get("dxf_sha256") != _sha(path):
            raise ValueError("NATIVE_TEXT_SIDECAR_NOT_BOUND_TO_ACTUAL_DXF")
        if metadata.get("roi_xyxy_px") != list(roi) or metadata.get("dpi") != dpi:
            raise ValueError("NATIVE_TEXT_SIDECAR_COORDINATES_CHANGED")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        load_error = type(exc).__name__ + ": " + str(exc)
    targets = (
        actual_text_targets
        | {
            oid
            for oid, obj in objects.items()
            if obj.get("kind") == "TEXT" or FIELD in _source_evidence(obj)
        }
        | {
            oid
            for oid, row in written.items()
            if row.get("kind") == "TEXT"
            or row.get("type") == "TEXT"
            or "text_geometry_binding" in row
        }
    )
    candidate_checks, source_checks = [], []
    for oid in sorted(targets):
        obj, receipt = objects.get(oid), written.get(oid)
        entries = actual.get(oid, [])
        binding = (
            receipt.get("text_geometry_binding") if isinstance(receipt, dict) else None
        )
        binding = binding if isinstance(binding, dict) else {}
        proof_present = FIELD in _source_evidence(obj)
        flagged = any(_identity(e).get(FIELD) is True for e in entries)
        required = (
            proof_present
            or flagged
            or binding.get("requires_single_line_source_replay") is True
        )
        checks = {}
        row = {
            "id": oid,
            "type": "NATIVE_TEXT_CANDIDATE_BINDING",
            "pass": False,
            "scope": "saved_candidate_content_and_layout_only; new raw replay is separate",
        }
        try:
            if load_error:
                raise ValueError(load_error)
            if obj is None or receipt is None:
                raise ValueError("NATIVE_TEXT_CANDIDATE_OR_WRITTEN_RECEIPT_MISSING")
            if len(entries) != 1:
                raise ValueError("NATIVE_TEXT_ACTUAL_ENTITY_MISSING_OR_DUPLICATED")
            entity = entries[0]
            checks["one_top_level_TEXT"] = entity.dxftype() == "TEXT"
            checks["actual_identity_matches_candidate"] = (
                _identity(entity).get("kind")
                == obj.get("kind")
                == receipt.get("kind")
                == "TEXT"
            )
            checks["written_handle_matches_actual"] = (
                receipt.get("handle") == entity.dxf.handle
                and by_handle.get(receipt.get("handle")) is entity
            )
            checks["written_type_is_TEXT"] = receipt.get("type") == "TEXT"
            checks["binding_schema_matches"] = binding.get("schema") == BINDING_SCHEMA
            checks["candidate_geometry_binding_matches"] = binding.get(
                "candidate_geometry_sha256"
            ) == _digest(obj["geometry"])
            checks["recovery_requirement_agrees_in_all_three_records"] = (
                proof_present
                == flagged
                == binding.get("requires_single_line_source_replay")
                == required
            )
            if entity.dxftype() != "TEXT":
                raise ValueError("NATIVE_TEXT_ENTITY_TYPE_CHANGED")
            font_record, font_path, expected_style = resolve_saved_text_font(path, metadata, obj)
            checks["portable_font_identity_matches"] = (
                binding.get("font")
                == {"font": font_record["font"], "sha256": font_record["sha256"]}
            )
            current_style = _style_attributes(doc, entity.dxf.style)
            checks["style_is_expected_portable_font"] = (
                entity.dxf.style == expected_style
                and current_style
                == {
                    "name": expected_style,
                    "font": font_record["font"],
                    "bigfont": "",
                    "width": 1.0,
                    "height": 0.0,
                    "oblique": 0.0,
                    "flags": 0,
                    "generation_flags": 0,
                }
            )
            checks["written_style_matches_actual"] = current_style == binding.get(
                "style_attributes"
            )
            expected, layout = _expected_attributes(
                entity, obj, roi, dpi, font_path, required
            )
            actual_attributes = text_attributes(entity)
            for key, value in expected.items():
                checks["actual_" + key + "_matches_candidate"] = _same(
                    value, actual_attributes.get(key)
                )
            checks["written_attributes_match_actual"] = all(
                _same(value, actual_attributes.get(key))
                for key, value in binding.get("actual_text_attributes", {}).items()
            ) and set(binding.get("actual_text_attributes", {})) == set(
                actual_attributes
            )
            checks["layout_contract_matches"] = binding.get("layout_basis") == (
                "source_component_affine" if source_row_layout_adoption(obj)
                else "source_ink_box" if required else "legacy_cap_height_and_advance_width"
            )
            checks["source_ink_layout_matches"] = (
                binding.get("source_ink_layout") == layout
            )
            if required:
                evidence = _source_evidence(obj).get(FIELD)
                checks["recovery_evidence_binding_matches"] = (
                    isinstance(evidence, dict)
                    and evidence.get("schema") == RECOVERY_SCHEMA
                    and binding.get("recovery_evidence_sha256") == _digest(evidence)
                )
            row["actual_text_attributes"] = actual_attributes
            row["pass"] = all(value is True for value in checks.values())
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ezdxf.DXFError,
        ) as exc:
            row["failure"] = type(exc).__name__ + ": " + str(exc)
        row["saved_candidate_checks"] = checks
        candidate_checks.append(row)
        if required:
            source = {
                "id": oid,
                "type": "SINGLE_LINE_TEXT_SOURCE_BINDING",
                "pass": False,
                "saved_candidate_checks": checks,
                "saved_candidate_pass": row["pass"],
            }
            try:
                if obj is None or not proof_present:
                    raise ValueError("SINGLE_LINE_TEXT_SOURCE_PROOF_MISSING")
                from .single_line_labels import verify_single_line_label_evidence

                replay = verify_single_line_label_evidence(
                    gray,
                    roi,
                    obj["source_evidence"][FIELD],
                    evidence_root=evidence_root,
                )
                source["source_replay"] = replay
                from .single_line_neighbor_clearance import check_text_round_white_gaps

                if len(entries) != 1 or entries[0].dxftype() != "TEXT":
                    raise ValueError("SINGLE_LINE_CLEARANCE_ACTUAL_TEXT_MISSING_OR_AMBIGUOUS")
                _, actual_font_path, expected_style = resolve_saved_text_font(path, metadata, obj)
                if entries[0].dxf.style != expected_style:
                    raise ValueError("SINGLE_LINE_CLEARANCE_ACTUAL_STYLE_CHANGED")
                # This independently reads the saved entity's actual transform.
                # Repeating the writer's expected layout can approve the same
                # newly closed source white gap twice.
                clearance = check_text_round_white_gaps(
                    gray, roi, obj["source_evidence"][FIELD]["source_partition"],
                    text_attributes(entries[0]), actual_font_path, dpi,
                ) if replay.get("pass") is True else {
                    "pass": False, "reason": "SINGLE_LINE_CLEARANCE_SOURCE_NOT_REPLAYED",
                    "actual_geometry_inspection_not_run": True,
                }
                source["actual_saved_text_round_clearance"] = clearance
                component_layout = {"pass": True, "required": False}
                if source_row_layout_adoption(obj) is not None:
                    from .single_line_source_layout import verify_source_glyph_layout

                    component_layout = verify_source_glyph_layout(
                        obj["geometry"], obj["source_evidence"][FIELD]["source_partition"],
                        roi, dpi, actual_font_path, text_attributes(entries[0]), gray=gray,
                    ) if replay.get("pass") is True else {
                        "pass": False, "reason": "SINGLE_LINE_LAYOUT_SOURCE_NOT_REPLAYED",
                    }
                source["actual_saved_source_component_layout"] = component_layout
                source["source_text_matches_candidate"] = (
                    replay.get("text") == obj["geometry"]["text"]
                )
                source["source_bbox_matches_candidate"] = _same(
                    replay.get("bbox_xyxy_px"), geometry_bbox(obj["geometry"])
                )
                source["source_rotation_is_supported"] = _same(
                    obj["geometry"].get("rotation_deg_image", 0.0), 0.0
                )
                source["pass"] = (
                    row["pass"]
                    and replay.get("pass") is True
                    and source["source_text_matches_candidate"]
                    and source["source_bbox_matches_candidate"]
                    and source["source_rotation_is_supported"]
                    and clearance["pass"]
                    and component_layout["pass"]
                )
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                ImportError,
            ) as exc:
                source["failure"] = type(exc).__name__ + ": " + str(exc)
            source_checks.append(source)
    return candidate_checks, source_checks
