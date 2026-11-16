"""Serialize source-proved members of a scanned symbol with measured weights."""

from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS


def symbol_lineweight(width_px, dpi):
    requested = width_px * 2540 / dpi
    return min((w for w in VALID_DXF_LINEWEIGHTS if w > 0), key=lambda w: abs(w - requested))


def symbol_glyph_pens(width_px, dpi):
    nominal = symbol_lineweight(width_px, dpi)
    # Outline fonts may cover the source stroke with a slightly lighter pen.
    return tuple(w * dpi / 2540 for w in sorted(VALID_DXF_LINEWEIGHTS, reverse=True)
                 if 0 < w <= nominal and w * dpi / 2540 >= max(.5, width_px - 1))


def bind_symbol_member(entity, record, role, width_px):
    dpi = record["dpi"]
    entity.dxf.lineweight = symbol_lineweight(width_px, dpi)
    appids = entity.doc.appids
    for name in ("P3A_STROKE", "ENGINEERING_GRAPHIC_SOURCE"):
        if name not in appids:
            appids.add(name)
    entity.set_xdata("P3A_STROKE", [
        (1000, "OBSERVED_SYMBOL_STROKE"), (1040, float(width_px)), (1040, float(dpi)),
    ])
    entity.set_xdata("ENGINEERING_GRAPHIC_SOURCE", [
        (1000, "OBSERVED_SOURCE_INK"),
        (1000, "ELECTRICAL_CONNECTIVITY_UNRESOLVED"),
        (1000, ",".join(map(str, record["bbox"]))),
        (1000, role),
    ])
