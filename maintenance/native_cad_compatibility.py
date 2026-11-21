"""Read-only DXF compatibility observations, including unmodified ASCII tags.

This is not a CAD/engineer acceptance gate. It never repairs or rewrites DXFs.
Run with the locked native-engine environment; JSON output may contain private
text/geometry and belongs beside the private input, not in the public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import ezdxf


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_records(path: Path, encoding: str) -> list[dict[str, Any]]:
    """Read ASCII code/value pairs without normalising invalid scale factors."""
    data = path.read_bytes()
    if data.startswith(b"AutoCAD Binary DXF"):
        raise ValueError("RAW_ASCII_AUDIT_UNAVAILABLE_FOR_BINARY_DXF")
    lines = data.decode(encoding, errors="surrogateescape").splitlines()
    if len(lines) % 2:
        raise ValueError("ODD_NUMBER_OF_DXF_LINES")
    tags = [(int(lines[i].strip()), lines[i + 1]) for i in range(0, len(lines), 2)]
    records: list[dict[str, Any]] = []
    record: dict[str, Any] | None = None
    section = ""
    block = None
    for code, value in tags:
        if code == 0:
            if record is not None:
                records.append(record)
            record = {"type": value.strip(), "section": section,
                      "block": block, "tags": []}
            if value.strip() == "ENDBLK":
                block = None
        elif record is not None:
            record["tags"].append((code, value))
            if record["type"] == "SECTION" and code == 2:
                section = value.strip()
            if record["type"] == "BLOCK" and code == 2:
                block = value.strip()
    if record is not None:
        records.append(record)
    return records


def tag(record: dict[str, Any], code: int, default: Any = None) -> Any:
    return next((value for group, value in record["tags"] if group == code), default)


def finite_float(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("NONFINITE_DXF_FIELD")
    return number


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return [jsonable(v) for v in value]


def snapshot(path: Path) -> dict[str, Any]:
    before_hash = sha256(path)
    doc = ezdxf.readfile(path)
    records = raw_records(path, doc.output_encoding)
    raw_inserts = [r for r in records if r["type"] == "INSERT"]
    inserts = []
    for record in raw_inserts:
        handle = tag(record, 5)
        scales = [finite_float(tag(record, code, 1.0)) for code in (41, 42, 43)]
        block_name = tag(record, 2, "")
        members = [r for r in records if r["section"] == "BLOCKS"
                   and r["block"] == block_name
                   and r["type"] not in {"BLOCK", "ENDBLK"}]
        # Coordinates/elevations, not extrusion normal Z (group 230).
        member_z = [finite_float(v) for r in members for c, v in r["tags"]
                    if 30 <= c <= 38]
        entity = doc.entitydb.get(handle)
        interpreted = None
        if entity is not None and entity.dxftype() == "INSERT":
            try:
                interpreted = {"xscale": entity.dxf.xscale,
                               "yscale": entity.dxf.yscale,
                               "zscale": entity.dxf.zscale,
                               "matrix_determinant": entity.matrix44().determinant()}
            except (ArithmeticError, ValueError, TypeError) as error:
                interpreted = {"error": type(error).__name__ + ": " + str(error)}
        inserts.append({"handle": handle, "block_name": block_name,
                        "section": record["section"], "parent_block": record["block"],
                        "raw_scale_tags": {str(c): tag(record, c) for c in (41, 42, 43)},
                        "raw_scale_with_dxf_defaults": scales,
                        "raw_scale_determinant": math.prod(scales),
                        "singular_scale": any(x == 0 for x in scales),
                        "block_member_count": len(members),
                        "direct_member_types": dict(Counter(r["type"] for r in members)),
                        "direct_member_z_all_zero": all(z == 0 for z in member_z),
                        "nested_insert_requires_recursive_check": any(r["type"] == "INSERT" for r in members),
                        "ezdxf_interpretation": interpreted})

    layers = [{"name": layer.dxf.name, "off": layer.is_off(),
               "frozen": layer.is_frozen(), "locked": layer.is_locked(),
               "plot": layer.dxf.plot,
               "modelspace_entities": sum(e.dxf.layer == layer.dxf.name for e in doc.modelspace())}
              for layer in doc.layers]
    texts = []
    for block in doc.blocks:
        for entity in block:
            if entity.dxftype() in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
                attrs = entity.dxfattribs()
                texts.append({"layout": block.name, "type": entity.dxftype(),
                              "handle": entity.dxf.handle,
                              "content": entity.text if entity.dxftype() == "MTEXT" else entity.dxf.text,
                              "attributes": jsonable(attrs)})

    plotsettings = []
    for record in records:
        if record["type"] != "PLOTSETTINGS":
            continue
        handle = tag(record, 5)
        incoming = [{"type": r["type"], "handle": tag(r, 5), "code": code}
                    for r in records for code, value in r["tags"]
                    if 330 <= code <= 369 and value == handle]
        plotsettings.append({"handle": handle, "raw_owner": tag(record, 330),
                             "incoming_handle_references": incoming,
                             "unowned_unreferenced": tag(record, 330) in (None, "0") and not incoming})

    xdata = Counter(appid for entity in doc.modelspace()
                    for appid in (entity.xdata.data if entity.xdata is not None else []))
    result = {"file": str(path.resolve()), "sha256": before_hash,
              "ezdxf_version": ezdxf.__version__, "dxf_version": doc.dxfversion,
              "insunits": doc.header.get("$INSUNITS"), "measurement": doc.header.get("$MEASUREMENT"),
              "scale_meaning": "UNCONFIRMED_BY_FILE_ALONE; DPI only establishes paper units",
              "modelspace_counts": dict(Counter(e.dxftype() for e in doc.modelspace())),
              "modelspace_xdata_counts_by_appid": dict(xdata),
              "modelspace_entities_with_xdata": sum(e.xdata is not None for e in doc.modelspace()),
              "styles": [{"name": s.dxf.name, "font": s.dxf.font, "bigfont": s.dxf.bigfont}
                         for s in doc.styles],
              "layers": layers, "inserts": inserts, "texts": texts,
              "plotsettings": plotsettings,
              "not_established": ["actual_font_resolution", "glyph_clipping_or_overlap",
                                  "GUI_edit_save_reopen", "printed_review_visibility",
                                  "independent_consumer", "engineer_repair_time"]}
    if sha256(path) != before_hash:
        raise RuntimeError("INPUT_CHANGED_DURING_READ_ONLY_AUDIT")
    return result


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Report observations. Differences are not blanket acceptance failures."""
    old_xdata = before["modelspace_entities_with_xdata"]
    new_xdata = after["modelspace_entities_with_xdata"]
    return {"same_file_bytes": before["sha256"] == after["sha256"],
            "prior_audit_reusable": before["sha256"] == after["sha256"],
            "changed_file_requires_new_audit_binding": before["sha256"] != after["sha256"],
            "units_equal": before["insunits"] == after["insunits"],
            "version_before_after": [before["dxf_version"], after["dxf_version"]],
            "xdata_before_after": [old_xdata, new_xdata],
            "xdata_loss_is_traceability_issue_not_editability_verdict": new_xdata < old_xdata,
            "singular_insert_counts_before_after": [sum(e["singular_scale"] for e in x["inserts"])
                                                    for x in (before, after)],
            "manual_effect_checks_required": ["text_readability_layout_editability",
                                              "door_room_transform_in_independent_consumer",
                                              "review_hidden_print_and_selection",
                                              "normal_open_save_print"],
            "status": "OBSERVATIONS_ONLY_NOT_CAD_ACCEPTANCE"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {args.before.resolve(), args.after.resolve()}:
        parser.error("output must not overwrite an input DXF")
    before, after = snapshot(args.before), snapshot(args.after)
    result = {"schema": "native-cad-compatibility/1", "before": before, "after": after,
              "comparison": compare(before, after)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["comparison"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
