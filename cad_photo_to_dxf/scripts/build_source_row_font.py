"""Deterministically derive one complete CAD font from the fixed licensed source.

Every outlined glyph follows the same metric rule. This resource build accepts
no drawing, string, code, OCR observation or source position. Application imports
and conversions do not invoke it; explicit setup verifies the resulting bytes.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from statistics import median
import tempfile

from ezdxf.fonts import fonts
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from app.native_objects.source_row_font_registry import SOURCE_ROW_FONT


DERIVATION_PROFILE = "uniform-whole-font-CAD-metrics-v1"
FONT_FILE = "osifont-cad-metrics.ttf"
LFF_FILE = "I2CAD_SOURCE_ROW.lff"
LICENSE_FILE = "osifont-cad-metrics.LICENSE.txt"
CURVE_FLATTENING = 1 / 4096


def _verify_original(data, specification, role):
    if len(data) != specification["bytes"] or sha256(data).hexdigest() != specification["sha256"]:
        raise ValueError("SOURCE_ROW_DERIVATION_ORIGINAL_" + role + "_MISMATCH")


def _compile_font(source):
    font = TTFont(BytesIO(source), recalcTimestamp=False)
    glyph_set = font.getGlyphSet()
    measurements, recordings = {}, {}
    for name in font.getGlyphOrder():
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        record = DecomposingRecordingPen(glyph_set)
        glyph_set[name].draw(record)
        measurements[name] = (pen.bounds, font["hmtx"][name])
        recordings[name] = record
    gap = float(median(advance - (bounds[2] - bounds[0])
                       for bounds, (advance, _) in measurements.values()
                       if bounds is not None and advance > 0))
    if gap <= 0:
        raise ValueError("SOURCE_ROW_DERIVATION_NONPOSITIVE_GLOBAL_GAP")
    # Read/decompose the entire original font before changing any glyph; a
    # composite must not accidentally refer to an already shifted sibling.
    rebuilt = {}
    for name, record in recordings.items():
        bounds = measurements[name][0]
        pen = TTGlyphPen(None)
        record.replay(pen if bounds is None else TransformPen(pen, (1, 0, 0, 1, -round(bounds[0]), 0)))
        rebuilt[name] = pen.glyph()
    for name, glyph in rebuilt.items():
        font["glyf"][name] = glyph
        if measurements[name][0] is not None:
            glyph.recalcBounds(font["glyf"])
            # TT glyph readers use this control-box bearing. Retaining the old
            # bearing after shifting curves would translate the ink twice.
            font["hmtx"][name] = (measurements[name][1][0], glyph.xMin)
    rebuilt_set = font.getGlyphSet()
    outlined = 0
    for name in font.getGlyphOrder():
        pen = BoundsPen(rebuilt_set)
        rebuilt_set[name].draw(pen)
        if pen.bounds is not None:
            outlined += 1
            font["hmtx"][name] = (max(0, round(pen.bounds[2] + gap)), font["hmtx"][name][1])
    removed = []
    for tag in ("kern", "GPOS", "GSUB"):
        if tag in font:
            del font[tag]
            removed.append(tag)
    names = {
        1: "I2CAD Source Row CAD Metrics",
        3: "I2CADSourceRowCADMetrics;1.0;" + DERIVATION_PROFILE,
        4: "I2CAD Source Row CAD Metrics",
        5: "Version 1.0; " + DERIVATION_PROFILE,
        6: "I2CADSourceRowCADMetrics",
    }
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding(), errors="strict")
    # Source timestamps and copyright/name-ID 0 are preserved. No clock,
    # platform path or selected project characters enter the output font.
    output = BytesIO()
    font.save(output, reorderTables=True)
    report = {"source_glyphs": len(measurements), "outlined_glyphs": outlined,
              "global_whole_font_median_gap_units": gap, "layout_tables_removed": removed,
              "source_head_created": int(font["head"].created), "source_head_modified": int(font["head"].modified)}
    font.close()
    return output.getvalue(), report


def _compile_lff(font_data, gap):
    with tempfile.TemporaryDirectory(prefix="i2cad-font-build-") as directory:
        path = Path(directory) / FONT_FILE
        path.write_bytes(font_data)
        native = TTFont(BytesIO(font_data), recalcTimestamp=False)
        cmap, glyph_set = native.getBestCmap(), native.getGlyphSet()
        renderer = fonts.sideload_ttf(path.resolve(), 1.0)
        # Match the DXF renderer's measured cap height, which may differ from
        # the font's OS/2 declaration. LibreCAD's nominal grid is nine units.
        cap = float(renderer.glyph_cache.font_measurements.cap_height)
        lines = ["# Format: LibreCAD Font 1", "# Creator: Image-to-CAD " + DERIVATION_PROFILE,
                 "# Name: I2CAD Source Row CAD Metrics", "# Encoding: UTF-8",
                 "# LetterSpacing: " + format(gap * 9 / cap, ".12f"),
                 "# WordSpacing: " + format(native["hmtx"][cmap[32]][0] * 9 / cap, ".12f"),
                 "# LineSpacingFactor: 1",
                 "# License: GNU LGPL v3 with original font exception; see " + LICENSE_FILE,
                 "# Derived from osifont commit " + SOURCE_ROW_FONT["upstream_commit"], ""]
        errors = {}
        for codepoint, name in sorted(cmap.items()):
            bounds = BoundsPen(glyph_set)
            glyph_set[name].draw(bounds)
            if bounds.bounds is None:
                continue
            glyphs = renderer.text_glyph_paths(chr(codepoint), 1.0)
            if len(glyphs) != 1:
                raise ValueError("SOURCE_ROW_UNREPRESENTABLE_LFF_GLYPH:" + str(codepoint))
            lines.append("[%04X]" % codepoint)
            vertices = []
            for subpath in glyphs[0].sub_paths():
                points = list(subpath.flattening(CURVE_FLATTENING))
                if points and points[-1] != points[0]:
                    points.append(points[0])
                vertices.extend(points)
                lines.append(";".join(f"{point.x * 9:.12f},{point.y * 9:.12f}" for point in points))
            errors[codepoint] = max(point.x for point in vertices) * cap + gap - native["hmtx"][name][0]
            lines.append("")
        report = {"renderer_cap_height_units": cap,
                  "OS2_declared_cap_height_units": float(native["OS/2"].sCapHeight),
                  "cmap_outline_glyphs": len(errors), "curve_flattening_at_unit_cap_height": CURVE_FLATTENING,
                  "maximum_advance_quantization_error_units": max(abs(value) for value in errors.values()),
                  "nonzero_advance_errors_over_1e_6": sum(abs(value) > 1e-6 for value in errors.values()),
                  "ASCII_maximum_advance_error_units": max(abs(value) for codepoint, value in errors.items() if 33 <= codepoint <= 126),
                  "every_possible_unicode_string_is_equivalent": False}
        native.close()
    return ("\n".join(lines) + "\n").encode("utf-8"), report


def _license(original, gap):
    notice = f"""

MODIFIED FONT RESOURCE - I2CAD SOURCE ROW CAD METRICS, VERSION 1.0
Derivation profile: {DERIVATION_PROFILE}
This is a modified font, not the unmodified upstream osifont distribution.
Original source: {SOURCE_ROW_FONT['source_url']}
Original SHA256: {SOURCE_ROW_FONT['font']['sha256']}

The same rule is applied to the whole original glyph set: decompose original
outlines, translate each outlined glyph by its rounded original left ink bound,
retain the outline shape, quantize to the TrueType coordinate grid, and set
advance from final exact ink maxX plus the whole-font median gap of {gap:g} font
units. Bearing metadata follows the rebuilt glyph control box. Empty glyphs
retain their original metrics. Shaping tables are removed for unshaped CAD text.
Family, unique ID and version names identify this modified derivative. Original
copyright and font-exception notices in name-ID 0 are preserved unchanged.

The companion LibreCAD LFF is generated from these same final glyph outlines,
scaled to its nominal nine-unit grid using the renderer's measured cap height.
Curve flattening is fixed at 1/4096 of unit cap height. The complete font is
converted without any drawing, label, expected answer or source coordinate.
Some non-ASCII glyph advances have finite coordinate-grid quantization errors;
the application checks the actual used string, not universal font equivalence.

Corresponding conversion source is provided in this project's
scripts/build_source_row_font.py and app/native_objects/source_row_font_registry.py.
Project source: https://github.com/ryoumiyahayato/image-to-cad
The original copyright, LGPL version 3 and font exception reproduced above
continue to apply to these modified font resources. No extra restriction is
added to embedding the font under the original exception.
"""
    return original + notice.encode("utf-8")


def build_source_row_font(source_font: bytes, source_license: bytes):
    """Return deterministic font/LFF/license bytes and a non-adoption receipt."""
    _verify_original(source_font, SOURCE_ROW_FONT["font"], "FONT")
    _verify_original(source_license, SOURCE_ROW_FONT["license"], "LICENSE")
    ttf, font_report = _compile_font(source_font)
    lff, lff_report = _compile_lff(ttf, font_report["global_whole_font_median_gap_units"])
    license_bytes = _license(source_license, font_report["global_whole_font_median_gap_units"])
    outputs = {FONT_FILE: ttf, LFF_FILE: lff, LICENSE_FILE: license_bytes}
    report = {"schema": "source-row-whole-font-derivation-v1", "derivation": DERIVATION_PROFILE,
              "source_profile": SOURCE_ROW_FONT["profile"],
              "source_font_sha256": SOURCE_ROW_FONT["font"]["sha256"],
              "resources": {name: {"file": name, "bytes": len(data), "sha256": sha256(data).hexdigest()} for name, data in outputs.items()},
              "dependencies": {name: version(name) for name in ("fonttools", "ezdxf")},
              "whole_font_metrics": font_report, "LFF_metrics": lff_report,
              "drawing_or_recognition_inputs": False, "application_conversion_executed": False}
    return outputs, report
