"""Opt-in consumer-side TEXT parameter repair for the measured FreeCAD 1.0.0.

This does not alter DXF source heights, outline text, or certify FreeCAD DXF
round trips. Width factors and vertical/multiline alignment stay explicit
unsupported conditions. A caller must supply cold-read source entity data.
"""

import hashlib
import math
from pathlib import Path


def repair_imported_texts(doc, manifest, source_dxf, *, App):
    if tuple(App.Version()[:3]) != ("1", "0", "0"):
        raise RuntimeError("FREECAD_TEXT_BRIDGE_VERSION_NOT_VALIDATED")
    if (
        hashlib.sha256(Path(source_dxf).read_bytes()).hexdigest()
        != manifest["source_dxf_sha256"]
    ):
        raise RuntimeError("FREECAD_TEXT_BRIDGE_SOURCE_CHANGED")
    if manifest.get("unit") != "mm":
        raise ValueError("FREECAD_TEXT_BRIDGE_REQUIRES_EXPLICIT_MM")
    plans = []
    used = set()
    for row in manifest["expected_texts"]:
        raw = row.get("raw_text", row["text"].replace("\n", "\\P"))
        accepted = (row["text"], raw)
        matches = []
        for obj in doc.Objects:
            if not hasattr(obj, "Text") or not hasattr(obj, "Placement"):
                continue
            value = "\n".join(obj.Text)
            p = obj.Placement.Base
            xy = row["anchor_mm"]
            # A strict identity match; not a relaxed source geometry gate.
            if value in accepted and math.hypot(p.x - xy[0], p.y - xy[1]) <= 1e-9:
                matches.append(obj)
        if len(matches) != 1 or matches[0].Name in used:
            raise RuntimeError(
                "FREECAD_TEXT_BRIDGE_AMBIGUOUS_IDENTITY:" + row["handle"]
            )
        obj = matches[0]
        used.add(obj.Name)
        if not all(
            hasattr(obj.ViewObject, k)
            for k in ("FontSize", "FontName", "Justification")
        ):
            raise RuntimeError("FREECAD_TEXT_BRIDGE_UNSUPPORTED_VIEW_PROVIDER")
        unsupported = []
        if row["type"] == "MTEXT":
            unsupported.extend(
                [
                    "MTEXT_ATTACHMENT_AND_PARAGRAPH_LAYOUT",
                    "MTEXT_WIDTH_AND_LINE_SPACING",
                ]
            )
        else:
            if row.get("width_factor", 1.0) != 1.0:
                unsupported.append("TEXT_WIDTH_FACTOR")
            if row.get("valign", 0) != 0:
                unsupported.append("TEXT_VERTICAL_ALIGNMENT")
            if row.get("halign", 0) not in (0, 1, 2):
                unsupported.append("TEXT_FIT_OR_ALIGNED_MODE")
        plans.append((obj, row, unsupported))
    result = []
    doc.openTransaction("I2CAD explicit source text parameter repair")
    try:
        for obj, row, unsupported in plans:
            before = {
                "text": list(obj.Text),
                "height_mm": float(obj.ViewObject.FontSize),
                "font": obj.ViewObject.FontName,
                "rotation_rad": float(obj.Placement.Rotation.Angle),
                "justification": obj.ViewObject.Justification,
            }
            # Assign authoritative entity values, not a global 72/25.4 scale.
            obj.ViewObject.FontSize = float(row["height_mm"])
            if row.get("font_file") == "DejaVuSans.ttf":
                obj.ViewObject.FontName = "DejaVu Sans"
            obj.Placement.Rotation = App.Rotation(
                App.Vector(0, 0, 1), float(row.get("rotation_deg", 0))
            )
            if row["type"] == "TEXT" and row.get("halign", 0) in (0, 1, 2):
                obj.ViewObject.Justification = {0: "Left", 1: "Center", 2: "Right"}[
                    row.get("halign", 0)
                ]
            if row["type"] == "MTEXT":
                obj.Text = row["text"].split("\n")
            result.append(
                {
                    "handle": row["handle"],
                    "FreeCAD_object": obj.Name,
                    "before": before,
                    "assigned_source_height_mm": row["height_mm"],
                    "unsupported": unsupported,
                    "full_layout_compatibility": not unsupported,
                    "font_glyph_metrics_compatibility": "NOT_CERTIFIED",
                }
            )
        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    return {
        "method": "OPT_IN_SOURCE_ENTITY_PARAMETER_RESTORE",
        "source_dxf_unchanged": True,
        "rows": result,
        "overall_compatibility_pass": False,
        "reason": "Width/vertical alignment/multiline layout and ordinary DXF export are not solved by this bridge.",
    }
