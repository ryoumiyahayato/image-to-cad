"""Create two bounded, unadopted native MTEXT layout diagnostics.

Read an existing source-bound MTEXT and a genuinely CAD-authored template.
The template supplies only LibreCAD's native font selector (the STYLE name).
Source content, height, line spacing and rotation are never fitted to an
expected answer. Actual consumer rendering and ordinary editing remain gates
outside this script; neither candidate is an adopted replacement.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import statistics
import sys

import ezdxf


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.native_objects import cad_io
from export_annotation_group_checkpoint import (
    digest,
    identity,
    independent_cold_read,
    normalized,
    read_json,
    restore_xdata,
    signature,
    snapshot,
    unchanged_neighbors,
)


STATUS = "DIAGNOSTIC_NOT_ADOPTED"


def _finite(value, path="geometry"):
    """Reject non-finite source coordinates before creating any output."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(f"NON_FINITE_SOURCE_GEOMETRY:{path}")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _finite(child, f"{path}.{key}")
        return
    for index, child in enumerate(value):
        _finite(child, f"{path}[{index}]")


def _positive(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"POSITIVE_FINITE_SOURCE_VALUE_REQUIRED:{name}") from error
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"POSITIVE_FINITE_SOURCE_VALUE_REQUIRED:{name}")
    return result


def _all_styles(doc):
    return {style.dxf.name.casefold(): signature(style) for style in doc.styles}


def _target(doc, group_id):
    targets = [entity for entity in doc.modelspace()
               if identity(entity) == group_id]
    if (len(targets) != 1 or targets[0].dxftype() != "MTEXT"
            or len(doc.modelspace().query("MTEXT")) != 1):
        raise ValueError("SOURCE_REQUIRES_ONE_TARGET_NATIVE_MTEXT")
    return targets[0]


def _source_contract(doc, receipt):
    if (receipt.get("schema") != "local-annotation-group-checkpoint-v1"
            or receipt.get("status")
            != "PASS_LOCAL_COMPLETE_MTEXT_MOVE_DELETE_AND_PROCESS_COLD_READ"
            or receipt.get("unit") != "paper_mm"
            or receipt.get("checks", {}).get("all_rows_complete_and_source_bound") is not True):
        raise ValueError("REQUIRES_COMPLETE_SOURCE_BOUND_LAYOUT_RECEIPT")
    group_id = receipt.get("group_id")
    if not isinstance(group_id, str) or not group_id:
        raise ValueError("SOURCE_GROUP_ID_MISSING")
    target = _target(doc, group_id)
    before = snapshot(doc, group_id)
    if (doc.dxfversion != "AC1027" or int(doc.units) != 4
            or target.dxf.attachment_point != 1
            or target.dxf.flow_direction != 1
            or target.dxf.line_spacing_style != 2):
        raise ValueError("REQUIRES_R2013_PAPER_MM_LEFT_TO_RIGHT_TOP_LEFT_EXACT_SPACING")
    if signature(target) != receipt.get("saved_mtext_signature"):
        raise ValueError("SOURCE_MTEXT_DIFFERS_FROM_SAVED_LAYOUT_SIGNATURE")
    geometry = receipt.get("assembled_geometry", {})
    rows = receipt.get("ordered_source_rows", [])
    _finite(geometry)
    _finite(rows, "ordered_source_rows")
    _finite(target.dxfattribs(), "saved_mtext")
    dpi = _positive(receipt.get("dpi"), "dpi")
    mm_per_px = 25.4 / dpi
    height = _positive(geometry.get("height_px"), "height_px")
    pitch = _positive(geometry.get("line_pitch_px"), "line_pitch_px")
    _positive(geometry.get("width_px"), "width_px")
    origin_x = float(geometry.get("x", float("nan")))
    origin_y = float(geometry.get("y", float("nan")))
    _finite([origin_x, origin_y], "source_origin")
    lines = geometry.get("lines")
    source_rows = geometry.get("source_line_geometries")
    if (not isinstance(lines, list) or len(lines) < 2
            or not all(isinstance(line, str) and line for line in lines)
            or not isinstance(source_rows, list)
            or len(rows) != len(lines) or len(source_rows) != len(lines)):
        raise ValueError("REQUIRES_ALL_ORDERED_SOURCE_ROWS")
    plain = target.plain_text()
    if (plain != "\n".join(lines)
            or geometry.get("text") != plain
            or [row.get("text") for row in rows] != lines):
        raise ValueError("SOURCE_CONTENT_OR_LINE_ORDER_MISMATCH")
    # This bounded plain profile must not introduce a new escape convention.
    if any(char in plain for char in "\\{}\r"):
        raise ValueError("PLAIN_CONTENT_HAS_RESERVED_MTEXT_SYNTAX")
    offsets = []
    for row, source_row in zip(rows, source_rows):
        box = source_row.get("bbox_xyxy_px")
        if (not isinstance(box, list) or len(box) != 4
                or box != row.get("bbox_xyxy_px")
                or float(box[2]) <= float(box[0])
                or float(box[3]) <= float(box[1])):
            raise ValueError("SOURCE_ROW_BOXES_MUST_MATCH_AND_BE_NONEMPTY")
        width = _positive(source_row.get("width_px"), "row_width_px")
        if not math.isclose(width, float(box[2]) - float(box[0]), abs_tol=1e-8):
            raise ValueError("SOURCE_ROW_WIDTH_DIFFERS_FROM_BOX")
        offsets.append(float(box[0]) - origin_x)
    if (not math.isclose(target.dxf.char_height, height * mm_per_px, abs_tol=1e-8)
            or not math.isclose(target.dxf.line_spacing_factor,
                                pitch / (height * (5 / 3)), abs_tol=1e-8)):
        raise ValueError("SAVED_HEIGHT_OR_SPACING_DIFFERS_FROM_SOURCE")
    direction = target.get_text_direction().normalize()
    _finite(direction, "actual_baseline_direction")
    common_offset_px = float(statistics.median(offsets))
    shift = direction * (common_offset_px * mm_per_px)
    approximation = {
        "method": "common_left_is_median_of_bound_source_row_offsets",
        "source_left_offsets_px": offsets,
        "common_left_offset_px": common_offset_px,
        "per_row_common_left_error_px": [common_offset_px - value for value in offsets],
        "actual_baseline_direction": list(direction),
        "common_left_shift_mm": list(shift),
        "individual_indents_preserved": False,
    }
    return target, before, geometry, plain, shift, approximation, mm_per_px


def _font_selector(template):
    notes = list(template.modelspace().query("MTEXT"))
    if len(notes) != 1:
        raise ValueError("NATIVE_TEMPLATE_REQUIRES_ONE_MTEXT")
    note = notes[0]
    _finite(note.dxfattribs(), "native_template")
    selector = note.dxf.style
    if not isinstance(selector, str) or not selector:
        raise ValueError("NATIVE_TEMPLATE_FONT_SELECTOR_MISSING")
    return note, selector, template.styles.get(selector)


def _use_native_selector(doc, native_style, selector):
    """LibreCAD 2.2.1.6 selects LFF/CXF by code 7, not STYLE font fields.

    Existing case-insensitive style records must not be rewritten to make
    this consumer-specific diagnostic look like a cross-CAD font contract.
    """
    if selector in doc.styles:
        style = doc.styles.get(selector)
        added = False
    else:
        attrs = native_style.dxfattribs()
        for key in ("name", "handle", "owner"):
            attrs.pop(key, None)
        style = doc.styles.new(selector, dxfattribs=attrs)
        restore_xdata(native_style, style)
        added = True
    return {
        "native_font_selector": selector,
        "consumer_specific_style_name_semantics": True,
        "consumer": "LibreCAD 2.2.1.6",
        "style_record_added": added,
        "native_template_style_record": signature(native_style),
        "candidate_style_record": signature(style),
        "existing_style_record_rewritten": False,
        "style_font_field_is_not_a_cross_cad_font_equivalence_proof": True,
    }


def _check_target_change(old, new, plain, insert, selector, width):
    if (new["content"] != r"\P".join(plain.split("\n"))
            or new["plain_text"] != plain
            or new["attributes"].get("style") != selector
            or new["attributes"].get("insert") != normalized(insert)
            or not math.isclose(new["attributes"]["width"], width, abs_tol=1e-8)):
        raise ValueError("CANDIDATE_CONTENT_OR_DECLARED_CHANGE_MISMATCH")
    left, right = copy.deepcopy(old), copy.deepcopy(new)
    for value in (left, right):
        for key in ("content", "plain_text", "style"):
            value.pop(key, None)
        for key in ("insert", "style", "width"):
            value["attributes"].pop(key, None)
    if left != right:
        raise ValueError("CANDIDATE_CHANGED_OTHER_SOURCE_MTEXT_ATTRIBUTES_OR_XDATA")


def create_probes(source_restored, source_layout_receipt, native_template, out_dir):
    source_restored = Path(source_restored).resolve()
    source_layout_receipt = Path(source_layout_receipt).resolve()
    native_template = Path(native_template).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise FileExistsError("Use a new output directory; preserve previous candidates")
    inputs = (source_restored, source_layout_receipt, native_template)
    input_hashes = {str(path): digest(path) for path in inputs}
    receipt = read_json(source_layout_receipt)
    if input_hashes[str(source_restored)] != receipt.get("outputs", {}).get("restored", {}).get("sha256"):
        raise ValueError("SOURCE_RESTORED_HASH_DIFFERS_FROM_LAYOUT_RECEIPT")
    source = ezdxf.readfile(source_restored)
    (target, before, geometry, plain, shift,
     approximation, mm_per_px) = _source_contract(source, receipt)
    group_id = receipt["group_id"]
    original_styles = _all_styles(source)
    template = ezdxf.readfile(native_template)
    native_note, selector, native_style = _font_selector(template)
    if native_note.plain_text() != plain:
        raise ValueError("NATIVE_TEMPLATE_CONTENT_DIFFERS_FROM_BOUND_SOURCE")
    original_signature = signature(target)
    position = target.dxf.insert + shift
    candidates = (
        ("C_native_plain", float(target.dxf.width)),
        ("D_reference_width", float(geometry["width_px"]) * mm_per_px),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name, width in candidates:
        doc = ezdxf.readfile(source_restored)
        font = _use_native_selector(doc, native_style, selector)
        note = _target(doc, group_id)
        note.text = r"\P".join(plain.split("\n"))
        note.dxf.style = selector
        note.dxf.insert = position
        note.dxf.width = width
        path = out_dir / (name + ".dxf")
        cad_io.save_native_dxf(doc, path)
        cold = independent_cold_read(path, group_id)
        unchanged_neighbors(cold, before, group_id)
        actual_doc = ezdxf.readfile(path)
        actual_styles = _all_styles(actual_doc)
        if any(actual_styles.get(key) != value for key, value in original_styles.items()):
            raise ValueError("EXISTING_STYLE_RECORD_CHANGED")
        _check_target_change(original_signature, cold["entities"][group_id],
                             plain, position, selector, width)
        outputs[name] = {
            "path": str(path), "sha256": digest(path), "status": STATUS,
            "reference_width_mm": width, "native_font": font,
            "cold_read": cold,
        }
    first = copy.deepcopy(outputs["C_native_plain"]["cold_read"])
    second = copy.deepcopy(outputs["D_reference_width"]["cold_read"])
    for value in (first, second):
        value.pop("file_sha256")
        value["entities"][group_id]["attributes"].pop("width")
    if first != second:
        raise ValueError("C_AND_D_MUST_DIFFER_ONLY_IN_REFERENCE_WIDTH")
    if input_hashes != {str(path): digest(path) for path in inputs}:
        raise ValueError("SOURCE_PUBLICATION_OR_NATIVE_TEMPLATE_BYTES_CHANGED")
    manifest = {
        "schema": "librecad-mtext-layout-probes-v1", "status": STATUS,
        "group_id": group_id, "derived_plain_content": plain,
        "input_hashes": input_hashes,
        "source_layout_receipt_sha256": input_hashes[str(source_layout_receipt)],
        "source_glyph_resolution_receipt_sha256": receipt.get("source_glyph_resolution_receipt_sha256"),
        "code_sha256": digest(__file__),
        "serializer_code_sha256": digest(cad_io.__file__),
        "source_geometry": geometry, "common_left_approximation": approximation,
        "source_mm_per_px": mm_per_px,
        "removed_inline_controls": ["paragraph_indents", "per_line_width_factors", "format_groups"],
        "per_line_widths_preserved": False, "individual_indents_preserved": False,
        "source_pixels_modified": False, "input_bytes_unchanged": True,
        "neighbors_unchanged": True, "existing_styles_unchanged": True,
        "candidate_count": 2, "C_and_D_differ_only_in_reference_width": True,
        "outputs": outputs, "recognition_calls": 0,
        "regional_conversion_run": False, "original_source_audit_inherited": False,
        "actual_CAD_layout": "NOT_MEASURED_BY_THIS_SCRIPT",
        "actual_CAD_edit_save_reopen": "NOT_RUN_BY_THIS_SCRIPT",
        "adoption_requires": ["actual consumer layout measurement", "ordinary CAD edit/save/full-exit/reopen"],
        "product_status": "LOCAL_NO_GO",
    }
    (out_dir / "probe_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-restored", type=Path, required=True)
    parser.add_argument("--source-layout-receipt", type=Path, required=True)
    parser.add_argument("--native-template", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main():
    args = build_parser().parse_args()
    manifest = create_probes(args.source_restored, args.source_layout_receipt,
                             args.native_template, args.out_dir)
    print(json.dumps({key: manifest[key] for key in ("status", "group_id", "candidate_count", "outputs")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
