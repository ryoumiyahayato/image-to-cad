"""Real DXF writer, cold-reader and official ezdxf -> MuPDF consumer."""

from .performance import profiled
from pathlib import Path
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
import shutil
import numpy as np
import ezdxf
import fitz
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from ezdxf.math import Matrix44
from ezdxf.lldxf.tagwriter import TagWriter
from ezdxf.tools.text_size import text_size
from ezdxf.fonts import fonts
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
from ezdxf.addons.drawing.recorder import Recorder
from ezdxf.addons.drawing.pymupdf import PyMuPdfRenderBackend
from ezdxf.addons.drawing.unified_text_renderer import UnifiedTextRenderer
from scipy.ndimage import map_coordinates, distance_transform_edt
from .contracts import save_json
from .connection_retrace_audit import certify_saved_retraces

APPID = "I2CAD_NATIVE_V2"
LAYERS = (
    "GEOMETRY",
    "SHORT_STROKE",
    "ROOM_LABELS",
    "ANNOTATION",
    "WALL_SEGMENTS",
    "DOOR",
    "CONNECTIONS",
    "CIRCULAR_MARKERS",
)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def identity(e):
    return json.loads(e.get_xdata(APPID)[0].value)


def mark(e, o):
    data = {"id": o["id"], "kind": o["kind"]}
    if o.get("source_evidence", {}).get("circle_endpoint_contacts"):
        data["circle_endpoint_contacts"] = True
    if o.get("source_evidence", {}).get("circle_white_gap_protection"):
        data["circle_white_gap_protection"] = True
    e.set_xdata(
        APPID,
        [(1000, json.dumps(data, ensure_ascii=True))],
    )


def _circle_parameters(geometry):
    """A full circle has a finite centre and positive source-pixel radius."""
    centre = np.asarray(geometry["center"], dtype=float)
    radius = float(geometry["radius_px"])
    if centre.shape != (2,) or not np.isfinite(centre).all():
        raise ValueError("NATIVE_CIRCLE_CENTER_MUST_BE_FINITE_XY")
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("NATIVE_CIRCLE_RADIUS_MUST_BE_POSITIVE")
    return centre, radius


def _font(out):
    root = Path(__file__).resolve().parents[2] / "resources/fonts"
    # app/native_objects/cad_io.py -> cad_photo_to_dxf/resources
    options = [
        (root / "DejaVuSans.ttf", root / "DejaVuSans.LICENSE.txt"),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/doc/fonts-dejavu-core/copyright"),
        ),
    ]
    source, lic = next(
        (
            (font, license_file)
            for font, license_file in options
            if font.is_file() and license_file.is_file()
        ),
        (None, None),
    )
    if source is None:
        raise FileNotFoundError("NATIVE_EXPORT_FONT_OR_LICENSE_MISSING")
    target = out / "DejaVuSans.ttf"
    shutil.copy2(source, target)
    shutil.copy2(lic, out / "FONT_LICENSE_DejaVu.txt")
    return {
        "font": target.name,
        "sha256": sha(target),
        "bundled_license": "FONT_LICENSE_DejaVu.txt",
        "source": str(source),
    }


@lru_cache(maxsize=128)
def _circular_character_ink_metrics(font_path, font_sha256, character):
    """Measure literal ink in the actual portable font, not advance width.

    A source glyph box includes descenders and excludes side bearings. DXF
    TEXT height instead means cap height, and its insertion is a baseline.
    The font hash is part of the cache key so changed bytes cannot reuse old
    metrics. Paths are measured only; output remains one native TEXT.
    """
    with TTFont(font_path) as font:
        cmap = font.getBestCmap() or {}
        glyphs = font.getGlyphSet()

        def bounds(letter):
            if ord(letter) not in cmap:
                raise ValueError("CIRCULAR_CHARACTER_NOT_IN_PORTABLE_FONT")
            pen = BoundsPen(glyphs)
            glyphs[cmap[ord(letter)]].draw(pen)
            if pen.bounds is None:
                raise ValueError("CIRCULAR_CHARACTER_HAS_NO_FONT_INK")
            return tuple(float(value) for value in pen.bounds)

        # These are font metrics, not recognized content. ezdxf's TrueType
        # renderer defines the baseline from x and the cap height from A.
        baseline = bounds("x")[1]
        cap_height = bounds("A")[3] - baseline
        xmin, ymin, xmax, ymax = bounds(character)
    values = (xmin, ymin - baseline, xmax, ymax - baseline, cap_height)
    if not all(math.isfinite(value) for value in values) or not (
        xmax > xmin and ymax > ymin and cap_height > 0
    ):
        raise ValueError("UNMEASURABLE_CIRCULAR_CHARACTER_FONT_INK")
    return values


def _circular_text_placement(g, mm, font_path):
    """Fit the complete font ink box to the proven source glyph box."""
    height, width = float(g["height_px"]) * mm, float(g["width_px"]) * mm
    if not all(math.isfinite(value) and value > 0 for value in (height, width)):
        raise ValueError("CIRCULAR_CHARACTER_REQUIRES_POSITIVE_SOURCE_INK_BOX")
    metrics = _circular_character_ink_metrics(str(font_path), sha(font_path), g["text"])
    xmin, ymin, xmax, ymax, cap = metrics
    sx, sy = width / (xmax - xmin), height / (ymax - ymin)
    angle = -math.radians(float(g.get("rotation_deg_image", 0.0)))
    c, s = math.cos(angle), math.sin(angle)
    # Subtract the transformed ink bearing from the source box's lower-left
    # anchor. This preserves the original white gap beneath a descender.
    offset = (c * xmin * sx - s * ymin * sy, s * xmin * sx + c * ymin * sy)
    return {
        "height": cap * sy,
        "width": sx / sy,
        "baseline_offset_mm": offset,
        "font_ink_bounds_units": list(metrics[:4]),
        "font_cap_height_units": cap,
        "font_sha256": sha(font_path),
        "basis": "complete_source_ink_box_to_portable_font_ink_bounds",
    }


def circular_text_ink_corners(entity):
    """Read actual saved TEXT ink corners using its portable font bytes."""
    style = entity.doc.styles.get(entity.dxf.style)
    filename = str(style.dxf.font)
    if filename != "DejaVuSans.ttf":
        raise ValueError("CIRCULAR_CHARACTER_PORTABLE_FONT_REFERENCE_CHANGED")
    font_path = Path(entity.doc.filename).parent / filename
    xmin, ymin, xmax, ymax, cap = _circular_character_ink_metrics(
        str(font_path), sha(font_path), entity.dxf.text
    )
    sy = float(entity.dxf.height) / cap
    sx = sy * float(entity.dxf.get("width", 1.0))
    angle = math.radians(float(entity.dxf.get("rotation", 0.0)))
    c, s = math.cos(angle), math.sin(angle)
    origin = np.array([entity.dxf.insert.x, entity.dxf.insert.y])
    return [
        origin + np.array([c * x * sx - s * y * sy, s * x * sx + c * y * sy])
        for x, y in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))
    ]


class _ExplicitMTextDirectionWriter(TagWriter):
    """Use ezdxf's standard tag export, retaining an explicit MTEXT code 72.

    In ezdxf 1.4.5 an explicitly assigned direction of 1 is otherwise omitted
    because it equals the optional attribute's default. LibreCAD 2.2.1.6 has
    already interpreted the missing tag differently. Only the direction slot
    immediately after MTEXT's mandatory attachment-point tag is forced; other
    entities and optional defaults retain the normal exporter behavior.
    """

    def write_tag2(self, code, value):
        if code == 0:
            self._in_mtext = value == "MTEXT"
            self.force_optional = False
        super().write_tag2(code, value)
        if getattr(self, "_in_mtext", False):
            if code == 71:
                self.force_optional = True
            elif code in (72, 1, 3):
                self.force_optional = False

    def write_tag(self, tag):
        # DXFNamespace uses write_tag for attributes, while entity headers use
        # write_tag2; both routes must maintain the same narrow direction slot.
        if tag.code == 0:
            self._in_mtext = tag.value == "MTEXT"
            self.force_optional = False
        super().write_tag(tag)
        if getattr(self, "_in_mtext", False):
            if tag.code == 71:
                self.force_optional = True
            elif tag.code in (72, 1, 3):
                self.force_optional = False


def save_native_dxf(doc, path):
    """Serialize a newly generated drawing; never rewrites a CAD GUI save.

    The MTEXT branch uses ezdxf's native TagWriter and section exporter with
    the same preparation as Drawing.write. That section API is internal:
    restrict this adapter to the verified library/version and R2013 contract.
    No recognition, string, geometry, font size or source threshold is changed.
    """
    mtexts = [e for e in doc.entitydb.values() if e.is_alive and e.dxftype() == "MTEXT"]
    if not mtexts:
        doc.saveas(path)
        return {"method": "ezdxf.Drawing.saveas", "explicit_mtext_directions": []}
    if ezdxf.__version__ != "1.4.5" or doc.dxfversion != "AC1027":
        raise RuntimeError(
            "EXPLICIT_MTEXT_SERIALIZER_REQUIRES_VERIFIED_EZDXF_1_4_5_R2013"
        )
    if any(not e.dxf.hasattr("flow_direction") for e in mtexts):
        raise ValueError("NATIVE_MTEXT_DIRECTION_MUST_BE_EXPLICIT_BEFORE_SERIALIZATION")
    expected = {e.dxf.handle: int(e.dxf.flow_direction) for e in mtexts}
    doc.filename = str(path)
    doc.commit_pending_changes()
    doc.classes.add_required_classes(doc.dxfversion)
    doc.update_all()
    with Path(path).open(
        "wt", encoding=doc.output_encoding, errors="dxfreplace"
    ) as stream:
        writer = _ExplicitMTextDirectionWriter(
            stream, dxfversion=doc.dxfversion, write_handles=True
        )
        doc.export_sections(writer)
    cold = ezdxf.readfile(path)
    actual = {
        e.dxf.handle: int(e.dxf.flow_direction)
        for e in cold.entitydb.values()
        if e.is_alive and e.dxftype() == "MTEXT" and e.dxf.hasattr("flow_direction")
    }
    if actual != expected:
        raise ValueError("SAVED_MTEXT_EXPLICIT_DIRECTION_TAG_MISSING_OR_CHANGED")
    return {
        "method": "ezdxf.TagWriter_explicit_MTEXT_direction",
        "ezdxf_version": ezdxf.__version__,
        "section_API": "internal_pinned_and_regression_checked",
        "explicit_mtext_directions": [
            {"handle": k, "group_code": 72, "value": v} for k, v in actual.items()
        ],
        "ordinary_GUI_save_not_rewritten": True,
    }


@profiled("cad_io.export_objects")
def export_objects(
    objects, path, roi, dpi, source_sha, *, diagnostic_source_mtext_layout=False
):
    """Write formal geometry; failed consumer layout remains an explicit probe.

    The source-paragraph indent experiment has not passed LibreCAD layout.
    Production callers therefore retain main's existing MTEXT expression.
    Only a checkpoint diagnostic may opt in to reproducing that experiment.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mm = 25.4 / dpi
    x0, y0, x1, y1 = roi

    def xy(p):
        return ((float(p[0]) - x0) * mm, (y1 - float(p[1])) * mm)

    font = _font(path.parent)
    doc = ezdxf.new("R2013")
    doc.units = 4
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.appids.new(APPID)
    for name in LAYERS:
        doc.layers.new(name, dxfattribs={"color": 7, "lineweight": 13, "plot": 1})
    review = doc.layers.new("REVIEW", dxfattribs={"color": 30, "plot": 0})
    # LibreCAD 2.2.1.6 displayed the off (negative-color) navigation layer on
    # import. Freeze as well as off/lock; these are navigation entities only.
    # Formal objects and their layers retain their original visibility.
    review.lock()
    review.off()
    review.freeze()
    doc.styles.new("I2CAD_TEXT", dxfattribs={"font": "DejaVuSans.ttf"})
    msp = doc.modelspace()
    written = []

    def text(layout_, g, attrs, anchor=(0, 0)):
        point = xy((g["x"], g["y"]))
        insert = (point[0] - anchor[0], point[1] - anchor[1])
        e = layout_.add_text(
            g["text"],
            dxfattribs={
                **attrs,
                "insert": insert,
                "height": g["height_px"] * mm,
                "style": "I2CAD_TEXT",
                "rotation": -g.get("rotation_deg_image", 0),
            },
        )
        measure = text_size(e)
        if measure.width <= 0:
            raise ValueError("UNMEASURABLE_NATIVE_TEXT")
        e.dxf.width = g["width_px"] * mm / measure.width
        return e

    for o in objects:
        kind = o["kind"]
        g = o["geometry"]
        attrs = {"layer": o["layer"], "color": 256}
        member_info = []
        mtext_line_layout = None
        circular_text_layout = None
        if kind == "LINE":
            e = msp.add_line(xy(g["start"]), xy(g["end"]), dxfattribs=attrs)
        elif kind == "CIRCLE":
            centre, radius = _circle_parameters(g)
            e = msp.add_circle(xy(centre), radius * mm, dxfattribs=attrs)
        elif kind == "ARC":
            centre, radius = _circle_parameters(g)
            sweep = float(
                g.get("sweep_deg_image", g["end_deg_image"] - g["start_deg_image"])
            )
            if not math.isfinite(sweep) or not 0 < abs(sweep) < 360:
                raise ValueError("NATIVE_ARC_REQUIRES_OBSERVED_OPEN_SWEEP")
            start, end = -float(g["start_deg_image"]), -float(g["end_deg_image"])
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError("NATIVE_ARC_ANGLES_MUST_BE_FINITE")
            if sweep > 0:
                start, end = end, start
            e = msp.add_arc(
                xy(centre),
                radius * mm,
                start_angle=start % 360,
                end_angle=end % 360,
                dxfattribs=attrs,
            )
        elif kind == "CIRCULAR_MARKER":
            centre, radius = _circle_parameters(g["circle_geometry"])
            if o.get("source_evidence", {}).get("components_complete") is not True:
                raise ValueError("CIRCULAR_MARKER_REQUIRES_COMPLETE_COMPONENT_EVIDENCE")
            tg = g["text_geometry"]
            if (
                not isinstance(tg.get("text"), str)
                or len(tg["text"]) != 1
                or not tg["text"].isprintable()
                or tg["text"].isspace()
            ):
                raise ValueError("CIRCULAR_MARKER_REQUIRES_ONE_LITERAL_CHARACTER")
            # Each marker owns only its border and literal character. Exterior
            # connections stay in modelspace and cannot move with this block.
            name = "I2CAD_" + o["id"].replace("-", "_")
            block = doc.blocks.new(name)
            anchor = xy(centre)
            block.add_circle((0, 0), radius * mm, dxfattribs={"layer": "0", "color": 0})
            circular_text_layout = _circular_text_placement(
                tg, mm, path.parent / font["font"]
            )
            point = xy((tg["x"], tg["y"]))
            offset = circular_text_layout["baseline_offset_mm"]
            block.add_text(
                tg["text"],
                dxfattribs={
                    "layer": "0",
                    "color": 0,
                    "style": "I2CAD_TEXT",
                    "insert": tuple(point[i] - anchor[i] - offset[i] for i in (0, 1)),
                    "height": circular_text_layout["height"],
                    "width": circular_text_layout["width"],
                    "rotation": -float(tg.get("rotation_deg_image", 0.0)),
                },
            )
            e = msp.add_blockref(name, anchor, dxfattribs=attrs)
            member_info = [m.dxftype() for m in block]
        elif kind == "CONNECTION_PATH":
            points = g["points"]
            bulges = g.get("bulges", [0.0] * len(points))
            if len(points) < 2 or len(bulges) != len(points) or g.get("closed", False):
                raise ValueError("CONNECTION_PATH_REQUIRES_VALID_OPEN_VERTEX_CHAIN")
            if not all(math.isfinite(float(v)) for p in points for v in p) or not all(
                math.isfinite(float(b)) for b in bulges
            ):
                raise ValueError("CONNECTION_PATH_HAS_NONFINITE_PARAMETERS")
            # The source coordinate system is y-down, so reflection into CAD
            # reverses arc orientation. No width is invented by the writer.
            e = msp.add_lwpolyline(
                [(*xy(p), -float(b)) for p, b in zip(points, bulges)],
                format="xyb",
                close=False,
                dxfattribs=attrs,
            )
        elif kind == "TEXT":
            e = text(msp, g, attrs)
        elif kind == "MTEXT":
            h = float(g["height_px"]) * mm
            lines = g["lines"]
            source_rows = g.get("source_line_geometries")
            if (
                not isinstance(source_rows, list)
                or len(source_rows) != len(lines)
                or not lines
            ):
                raise ValueError("MTEXT_REQUIRES_ORDERED_SOURCE_LINE_GEOMETRIES")
            content_parts = []
            mtext_line_layout = []
            for index, (line, row) in enumerate(zip(lines, source_rows)):
                source_width = float(row["width_px"])
                box = list(row["bbox_xyxy_px"])
                if not math.isfinite(source_width) or source_width <= 0:
                    raise ValueError("MTEXT_SOURCE_LINE_WIDTH_MUST_BE_POSITIVE")
                temp = msp.add_text(
                    line, dxfattribs={"height": h, "style": "I2CAD_TEXT"}
                )
                try:
                    measured = text_size(temp).width
                finally:
                    msp.delete_entity(temp)
                if not math.isfinite(measured) or measured <= 0:
                    raise ValueError("UNMEASURABLE_NATIVE_MTEXT_LINE")
                factor = source_width * mm / measured
                left_offset = float(box[0]) - float(g["x"])
                if not math.isfinite(left_offset):
                    raise ValueError("MTEXT_SOURCE_LINE_OFFSET_MUST_BE_FINITE")
                # Paragraph indents are multiples of the initial char height,
                # not drawing units. Reset every paragraph, including a zero
                # offset, so a preceding indented row cannot shift its neighbor.
                paragraph = (
                    "\\pxi0,l" + format(left_offset * mm / h, ".10g") + ",r0,ql;"
                    if diagnostic_source_mtext_layout
                    else ""
                )
                # Each paragraph gets an independent absolute width factor.
                # Keep one true MTEXT and the original text/height/line pitch.
                content_parts.append(
                    paragraph + "{\\W" + format(factor, ".10g") + ";" + line + "}"
                )
                mtext_line_layout.append(
                    {
                        "line_index": index,
                        "text": line,
                        "source_bbox_xyxy_px": box,
                        "source_width_px": source_width,
                        "source_left_offset_px": left_offset,
                        "source_left_offset_applied": diagnostic_source_mtext_layout,
                        "layout_profile": (
                            "FAILED_LIBRECAD_LAYOUT_DIAGNOSTIC"
                            if diagnostic_source_mtext_layout
                            else "EXISTING_MAIN_MTEXT_EXPRESSION"
                        ),
                        "paragraph_indent_char_heights": left_offset * mm / h,
                        "unscaled_font_width_mm": measured,
                        "inline_width_factor": factor,
                        "font_width_target_mm": source_width * mm,
                        "glyph_ink_bbox_measured": False,
                        "width_basis": "source_row_bbox_to_font_text_width_not_glyph_ink_fit",
                    }
                )
            width = float(g["width_px"]) * mm
            content = "\\P".join(content_parts)
            e = msp.add_mtext(
                content,
                dxfattribs={
                    **attrs,
                    "insert": xy((g["x"], g["y"])),
                    "char_height": h,
                    "width": width * 1.03,
                    "attachment_point": 1,
                    "style": "I2CAD_TEXT",
                    "rotation": (
                        -g.get("rotation_deg_image", 0)
                        if diagnostic_source_mtext_layout
                        else 0
                    ),
                    "line_spacing_style": 2,
                    "flow_direction": 1,
                    "line_spacing_factor": float(
                        np.clip(
                            g.get("line_pitch_px", g["height_px"] * 1.5)
                            / (g["height_px"] * (5 / 3)),
                            0.25,
                            4,
                        )
                    ),
                },
            )
        elif kind in ("ROOM_LABEL", "WALL_SEGMENT", "DOOR"):
            name = "I2CAD_" + o["id"].replace("-", "_")
            block = doc.blocks.new(name)
            # Every annotation gets a unique block definition. Editing one
            # instance's true TEXT cannot mutate other room labels.
            if kind == "ROOM_LABEL":
                points = g["frame_points"]
                anchor = xy(points[0])
                pts = [(xy(p)[0] - anchor[0], xy(p)[1] - anchor[1]) for p in points]
                block.add_lwpolyline(
                    pts, close=True, dxfattribs={"layer": "0", "color": 0}
                )
                text(block, g["text_geometry"], {"layer": "0", "color": 0}, anchor)
                # These are actual retained source-frame endpoint remnants,
                # counted as extra LINE members, not hidden inside a claim of
                # a two-entity annotation. They share the annotation edit scope.
                for part in g.get("frame_source_remainders", []):
                    a, b = xy(part["geometry"]["start"]), xy(part["geometry"]["end"])
                    block.add_line(
                        (a[0] - anchor[0], a[1] - anchor[1]),
                        (b[0] - anchor[0], b[1] - anchor[1]),
                        dxfattribs={"layer": "0", "color": 0},
                    )
            elif kind == "WALL_SEGMENT":
                anchor = xy(g["members"][0]["geometry"]["start"])
                for member in g["members"]:
                    a, b = (
                        xy(member["geometry"]["start"]),
                        xy(member["geometry"]["end"]),
                    )
                    block.add_line(
                        (a[0] - anchor[0], a[1] - anchor[1]),
                        (b[0] - anchor[0], b[1] - anchor[1]),
                        dxfattribs={"layer": "0", "color": 0},
                    )
            elif g.get("native_members") is not None:
                members_ = g["native_members"]
                if not members_:
                    raise ValueError("EMPTY_NATIVE_DOOR_MEMBERS")
                anchor = xy(g["hinge"])
                for member in members_:
                    mg = member["geometry"]
                    mt = member["kind"]
                    if mt == "LINE":
                        a, b = xy(mg["start"]), xy(mg["end"])
                        block.add_line(
                            (a[0] - anchor[0], a[1] - anchor[1]),
                            (b[0] - anchor[0], b[1] - anchor[1]),
                            dxfattribs={"layer": "0", "color": 0},
                        )
                    elif mt == "ARC":
                        c = xy(mg["center"])
                        st, en = (
                            -float(mg["start_deg_image"]),
                            -float(mg["end_deg_image"]),
                        )
                        if (
                            float(
                                mg.get(
                                    "sweep_deg_image",
                                    mg["end_deg_image"] - mg["start_deg_image"],
                                )
                            )
                            > 0
                        ):
                            st, en = en, st
                        block.add_arc(
                            (c[0] - anchor[0], c[1] - anchor[1]),
                            float(mg["radius_px"]) * mm,
                            start_angle=st % 360,
                            end_angle=en % 360,
                            dxfattribs={"layer": "0", "color": 0},
                        )
                    else:
                        raise ValueError("UNSUPPORTED_NATIVE_DOOR_MEMBER:" + str(mt))
            else:
                leaves = g.get("leaves", [g])
                anchor = xy(g.get("hinge", leaves[0]["hinge"]))
                for leaf in leaves:
                    c = xy(leaf["hinge"])
                    r = leaf["radius_px"] * mm
                    theta = math.radians(leaf["leaf_angle_deg_image"])
                    tip = (c[0] + r * math.cos(theta), c[1] - r * math.sin(theta))
                    local = (c[0] - anchor[0], c[1] - anchor[1])
                    block.add_line(
                        local,
                        (tip[0] - anchor[0], tip[1] - anchor[1]),
                        dxfattribs={"layer": "0", "color": 0},
                    )
                    st, en = -leaf["start_deg_image"], -leaf["end_deg_image"]
                    if (
                        leaf.get(
                            "sweep_deg_image",
                            leaf["end_deg_image"] - leaf["start_deg_image"],
                        )
                        > 0
                    ):
                        st, en = en, st
                    block.add_arc(
                        local,
                        r,
                        start_angle=st % 360,
                        end_angle=en % 360,
                        dxfattribs={"layer": "0", "color": 0},
                    )
            e = msp.add_blockref(name, anchor, dxfattribs=attrs)
            member_info = [m.dxftype() for m in block]
        else:
            raise ValueError("UNSUPPORTED_NATIVE_KIND:" + kind)
        mark(e, o)
        written.append(
            {
                "id": o["id"],
                "kind": kind,
                "type": e.dxftype(),
                "handle": e.dxf.handle,
                "block_members": member_info,
            }
        )
        if mtext_line_layout is not None:
            written[-1]["mtext_line_layout"] = mtext_line_layout
        if circular_text_layout is not None:
            written[-1]["circular_text_layout"] = circular_text_layout
    regions = []
    for row in range(4):
        for col in range(6):
            bx0 = x0 + (x1 - x0) * col / 6
            bx1 = x0 + (x1 - x0) * (col + 1) / 6
            by0 = y0 + (y1 - y0) * row / 4
            by1 = y0 + (y1 - y0) * (row + 1) / 4
            rid = f"R{row * 6 + col + 1:02d}"
            bbox = [bx0, by0, bx1, by1]
            e = msp.add_lwpolyline(
                [xy(p) for p in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1))],
                close=True,
                dxfattribs={"layer": "REVIEW"},
            )
            mark(e, {"id": rid + "-BOX", "kind": "REVIEW"})
            e = msp.add_text(
                rid,
                dxfattribs={
                    "layer": "REVIEW",
                    "insert": xy((bx0 + 5, by0 + 25)),
                    "height": 2.5,
                    "style": "I2CAD_TEXT",
                },
            )
            mark(e, {"id": rid + "-LABEL", "kind": "REVIEW"})
            regions.append(
                {
                    "id": rid,
                    "bbox_xyxy_px": bbox,
                    "scope": "Every source item not confirmed remains repair work",
                }
            )
    serialization = save_native_dxf(doc, path)
    meta = {
        "dxf_path": str(path),
        "source_sha256": source_sha,
        "dxf_sha256": sha(path),
        "roi_xyxy_px": list(roi),
        "dpi": dpi,
        "unit": "paper_mm",
        "objects": objects,
        "written": written,
        "font": font,
        "repair_regions": regions,
        "native_schema": "complete_objects_v2",
        "serialization": serialization,
    }
    save_json(path.with_suffix(".objects.json"), meta)
    return meta


def entity_data(e):
    attrs = {
        k: v
        for k, v in e.dxf.all_existing_dxf_attribs().items()
        if k not in ("handle", "owner")
    }
    for k, v in list(attrs.items()):
        if hasattr(v, "x"):
            attrs[k] = list(v)
    if e.dxftype() == "LWPOLYLINE":
        attrs["vertices"] = [list(p) for p in e.get_points("xyseb")]
    if e.dxftype() == "MTEXT":
        attrs["content"] = e.text
        attrs["plain_text"] = e.plain_text()
    return {"type": e.dxftype(), "attributes": attrs}


def snapshot(doc):
    result = {}
    for e in doc.modelspace():
        oid = identity(e)["id"]
        row = entity_data(e)
        if e.dxftype() == "INSERT":
            row["members"] = [entity_data(m) for m in doc.blocks.get(e.dxf.name)]
        row["layer_state"] = {
            "on": doc.layers.get(e.dxf.layer).is_on(),
            "locked": doc.layers.get(e.dxf.layer).is_locked(),
            "plot": doc.layers.get(e.dxf.layer).dxf.plot,
        }
        result[oid] = row
    return result


def _same_circle_parameters(left, right):
    """Only serialization round-off is allowed in a candidate correspondence."""
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if (
        left.shape != right.shape
        or not np.isfinite(left).all()
        or not np.isfinite(right).all()
    ):
        return False
    scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), 1.0)
    return bool(np.all(np.abs(left - right) <= 64 * np.spacing(scale)))


def circular_candidate_contract(entity, obj, pixel_from_cad, mm):
    """Check the actual saved marker members, including literal TEXT layout.

    Both the cold source audit and the broader review call this same contract.
    It never obtains a candidate from its entity's appearance or guessed text.
    """
    kind, g = obj["kind"], obj["geometry"]
    complete = kind == "CIRCULAR_MARKER"
    checks = {
        "native_circular_representation": entity.dxftype()
        == ("INSERT" if complete else "CIRCLE"),
        "component_status_explicit": obj.get("source_evidence", {}).get(
            "components_complete"
        )
        is complete,
    }
    if not checks["native_circular_representation"]:
        return checks
    expanded = list(entity.virtual_entities()) if complete else [entity]
    checks["exact_circle_and_character_member_set"] = Counter(
        e.dxftype() for e in expanded
    ) == (Counter({"CIRCLE": 1, "TEXT": 1}) if complete else Counter({"CIRCLE": 1}))
    circles = [e for e in expanded if e.dxftype() == "CIRCLE"]
    cg = g["circle_geometry"] if complete else g
    centre, radius = _circle_parameters(cg)
    checks["circle_parameters_match_candidate"] = len(circles) == 1 and (
        _same_circle_parameters(pixel_from_cad(circles[0].dxf.center), centre)
        and _same_circle_parameters(float(circles[0].dxf.radius) / mm, radius)
    )
    checks["circle_is_planar_source_xy"] = len(circles) == 1 and (
        float(circles[0].dxf.center.z) == 0.0
        and float(circles[0].dxf.get("thickness", 0.0)) == 0.0
        and _same_circle_parameters(
            circles[0].dxf.get("extrusion", (0, 0, 1)), (0, 0, 1)
        )
    )
    if complete:
        checks["independent_marker_definition"] = (
            sum(
                1
                for e in entity.doc.modelspace().query("INSERT")
                if e.dxf.name == entity.dxf.name
            )
            == 1
        )
        checks["no_attribute_or_nested_members"] = not entity.attribs and all(
            e.dxftype() in ("CIRCLE", "TEXT")
            for e in entity.doc.blocks.get(entity.dxf.name)
        )
        checks["marker_unit_transform"] = all(
            _same_circle_parameters(float(entity.dxf.get(key, 1.0)), 1.0)
            for key in ("xscale", "yscale", "zscale")
        ) and _same_circle_parameters(float(entity.dxf.get("rotation", 0.0)) % 360, 0.0)
        strings = [e for e in expanded if e.dxftype() == "TEXT"]
        tg = g["text_geometry"]
        checks["one_literal_source_character"] = (
            isinstance(tg.get("text"), str)
            and len(tg["text"]) == 1
            and tg["text"].isprintable()
            and not tg["text"].isspace()
            and len(strings) == 1
            and strings[0].dxf.text == tg["text"]
        )
        if len(strings) == 1:
            t = strings[0]
            style = t.doc.styles.get(t.dxf.style)
            angle = math.radians(float(tg.get("rotation_deg_image", 0.0)))
            c, s = math.cos(angle), math.sin(angle)
            origin = np.array([tg["x"], tg["y"]], dtype=float)
            u = np.array([c, s]) * float(tg["width_px"])
            v = np.array([s, -c]) * float(tg["height_px"])
            source_corners = (origin, origin + u, origin + u + v, origin + v)
            actual_corners = [pixel_from_cad(p) for p in circular_text_ink_corners(t)]
            rotation_difference = math.radians(
                float(t.dxf.get("rotation", 0.0))
                + float(tg.get("rotation_deg_image", 0.0))
            )
            checks["character_source_layout_matches"] = (
                _same_circle_parameters(actual_corners, source_corners)
                and _same_circle_parameters(
                    (math.cos(rotation_difference), math.sin(rotation_difference)),
                    (1.0, 0.0),
                )
                and int(t.dxf.get("halign", 0)) == 0
                and int(t.dxf.get("valign", 0)) == 0
                and int(t.dxf.get("text_generation_flag", 0)) == 0
                and float(t.dxf.get("oblique", 0.0)) == 0.0
                and float(t.dxf.get("thickness", 0.0)) == 0.0
                and _same_circle_parameters(t.dxf.get("extrusion", (0, 0, 1)), (0, 0, 1))
                and float(style.dxf.get("width", 1.0)) == 1.0
                and float(style.dxf.get("oblique", 0.0)) == 0.0
            )
    return checks


def _cold_circular_bindings(path, doc, gray, roi, dpi, evidence_root):
    """Require replayable ring and character evidence for new circular kinds."""
    targets = [
        e
        for e in doc.modelspace()
        if e.dxf.layer != "REVIEW"
        and identity(e).get("kind") in ("CIRCLE", "CIRCULAR_MARKER")
    ]
    if not targets:
        return []
    candidate_path = Path(path).with_suffix(".objects.json")
    by_id, load_error = {}, None
    try:
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
        if data.get("dxf_sha256") != sha(path):
            raise ValueError("CIRCULAR_CANDIDATE_NOT_BOUND_TO_ACTUAL_SAVED_DXF")
        if list(data.get("roi_xyxy_px", [])) != list(roi) or data.get("dpi") != dpi:
            raise ValueError("CIRCULAR_CANDIDATE_COORDINATES_OR_DPI_CHANGED")
        rows = data["objects"]
        by_id = {o["id"]: o for o in rows}
        if len(by_id) != len(rows):
            raise ValueError("DUPLICATE_CIRCULAR_CANDIDATE_IDENTITY")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        load_error = type(exc).__name__ + ": " + str(exc)
    mm = 25.4 / dpi

    def px(point):
        return np.array([point[0] / mm + roi[0], roi[3] - point[1] / mm])

    result = []
    for entity in targets:
        oid, kind = identity(entity)["id"], identity(entity)["kind"]
        row = {"id": oid, "type": "CIRCULAR_SOURCE_BINDING", "pass": False}
        try:
            if load_error is not None:
                raise ValueError(load_error)
            obj = by_id[oid]
            if obj["kind"] != kind:
                raise ValueError("CIRCULAR_SAVED_IDENTITY_KIND_CHANGED")
            checks = circular_candidate_contract(entity, obj, px, mm)
            from .circular_markers import verify_circle_source_evidence

            ring = verify_circle_source_evidence(
                gray, roi, obj, evidence_root=evidence_root
            )
            row.update(saved_candidate_checks=checks, ring_source=ring)
            character_ok = True
            if kind == "CIRCULAR_MARKER":
                from .circle_character_recognition import (
                    verify_circle_character_evidence,
                )

                character = verify_circle_character_evidence(
                    gray, roi, obj, evidence_root=evidence_root
                )
                row["character_source"] = character
                character_ok = character.get("pass") is True
            row["pass"] = (
                all(value is True for value in checks.values())
                and ring.get("pass") is True
                and character_ok
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ImportError,
            ezdxf.DXFError,
        ) as exc:
            row["failure"] = type(exc).__name__ + ": " + str(exc)
        result.append(row)
    return result


@profiled("cad_io.cold_audit")
def cold_audit(path, gray, roi, dpi, out):
    before = sha(path)
    doc = ezdxf.readfile(path)
    audit = doc.audit()
    mm = 25.4 / dpi
    x0, y0, x1, y1 = roi
    # An ROI selects output geometry; it is not a white mask on neighbouring
    # original pixels. Use actual source context for interpolation at its
    # boundary, identical distance thresholds and sampling as before.
    ox, oy = max(0, x0 - 8), max(0, y0 - 8)
    rx, by = min(gray.shape[1], x1 + 8), min(gray.shape[0], y1 + 8)
    dist = distance_transform_edt(gray[oy:by, ox:rx] >= 128)
    checks = []
    entities = []
    texts = []
    counts = Counter()
    members = Counter()
    duplicates = []
    all_repeated = []
    certified_retraces = []
    seen = {}
    circular_curves = []
    room_blocks = []
    evidence_root = Path(out).parent
    circular_checks = _cold_circular_bindings(path, doc, gray, roi, dpi, evidence_root)
    checks.extend(circular_checks)
    from .circle_endpoint_contacts import cold_circle_endpoint_contacts

    circle_contact_checks = cold_circle_endpoint_contacts(path, doc, gray, roi, dpi)
    checks.extend(circle_contact_checks)
    from .circle_white_gap_protection import cold_circle_white_gaps

    circle_white_gap_checks = cold_circle_white_gaps(path, doc, gray, roi, dpi)
    checks.extend(circle_white_gap_checks)
    retrace_proof = certify_saved_retraces(
        doc,
        before,
        Path(path).with_suffix(".objects.json"),
        evidence_root / "connections/discovery/source_graph.json",
        evidence_root / "connections/discovery/connections.json",
        gray,
        roi,
        dpi,
    )
    allowed_retraces = {
        (row["handle"], *sorted(row["segment_indices"])): row
        for row in retrace_proof["allowances"]
    }

    def px(point):
        return np.array([point[0] / mm + x0, y1 - point[1] / mm])

    for e in doc.modelspace():
        if e.dxf.layer == "REVIEW":
            continue
        oid = identity(e)["id"]
        counts[e.dxftype()] += 1
        if e.dxftype() == "INSERT" and identity(e)["kind"] == "ROOM_LABEL":
            room_blocks.append(e.dxf.name)
        expanded = list(e.virtual_entities()) if e.dxftype() == "INSERT" else [e]
        # LWPOLYLINE bulges are true circular arcs. Audit the cold-read DXF
        # segments, rather than silently treating every bulge as a chord.
        expanded = [
            part
            for m in expanded
            for part in (
                list(m.virtual_entities())
                if m.dxftype() == "LWPOLYLINE"
                and any(abs(float(b)) > 0 for *_, b in m.get_points("xyb"))
                else [m]
            )
        ]
        for idx, m in enumerate(expanded):
            typ = m.dxftype()
            members[typ] += 1
            if typ in ("TEXT", "MTEXT"):
                texts.append(
                    {
                        "id": oid,
                        "type": typ,
                        "text": m.dxf.text if typ == "TEXT" else m.plain_text(),
                    }
                )
                continue
            segments = []
            if typ == "LINE":
                segments = [(px(m.dxf.start), px(m.dxf.end))]
            elif typ == "LWPOLYLINE":
                pts = [px(v) for v in m.get_points("xy")]
                segments = list(zip(pts, pts[1:] + (pts[:1] if m.closed else [])))
            elif typ in ("ARC", "CIRCLE"):
                c = px(m.dxf.center)
                r = m.dxf.radius / mm
                start = float(m.dxf.start_angle) if typ == "ARC" else 0.0
                sweep = (
                    (float(m.dxf.end_angle) - start) % 360 if typ == "ARC" else 360.0
                )
                angle = np.deg2rad(
                    np.linspace(
                        start,
                        start + sweep,
                        max(
                            3,
                            int(math.ceil(r * math.radians(sweep) / 0.05)) + 1,
                        ),
                    )
                )
                points = c + r * np.column_stack((np.cos(angle), -np.sin(angle)))
                ds = map_coordinates(
                    dist,
                    [points[:, 1] - oy, points[:, 0] - ox],
                    order=1,
                    mode="constant",
                    cval=999,
                )
                checks.append(
                    {
                        "id": oid,
                        "member": idx,
                        "type": typ,
                        "max_distance_px": float(ds.max()),
                        "samples": len(ds),
                        "tolerance_px": 2.5,
                        "sampled_sweep_deg": sweep,
                        "pass": bool(ds.max() <= 2.5),
                    }
                )
                curve = {
                    "id": oid,
                    "handle": e.dxf.handle,
                    "member": idx,
                    "type": typ,
                    "center": c.tolist(),
                    "radius_px": r,
                    "start_deg_cad": start,
                    "sweep_deg": sweep,
                }
                for previous in circular_curves:
                    # A CIRCLE cannot be added over a previously retained ARC
                    # of that same circle, even when their DXF types differ.
                    if (
                        "CIRCLE" in (typ, previous["type"])
                        and sweep > 0
                        and previous["sweep_deg"] > 0
                        and _same_circle_parameters(previous["center"], c)
                        and _same_circle_parameters(previous["radius_px"], r)
                    ):
                        duplicate = {
                            "objects": [previous["id"], oid],
                            "actual_handles": [previous["handle"], e.dxf.handle],
                            "expanded_member_indices": [previous["member"], idx],
                            "duplicate_kind": "COINCIDENT_CIRCLE_OR_CIRCLE_ARC",
                            "circular_members": [previous, curve],
                        }
                        duplicates.append(duplicate)
                        all_repeated.append(duplicate)
                circular_curves.append(curve)
                continue
            else:
                raise ValueError("UNEXPECTED_DXF_PRIMITIVE:" + typ)
            for segment_index, (a, b) in enumerate(segments):
                length = float(np.linalg.norm(b - a))
                p = np.linspace(a, b, max(2, int(math.ceil(length / 0.25)) + 1))
                ds = map_coordinates(
                    dist,
                    [p[:, 1] - oy, p[:, 0] - ox],
                    order=1,
                    mode="constant",
                    cval=999,
                )
                d = np.diff(np.r_[False, ds > 2, False].astype(int))
                s = np.flatnonzero(d == 1)
                t = np.flatnonzero(d == -1)
                gap = float(max(t - s, default=0) * length / max(1, len(p) - 1))
                fraction = float(np.mean(ds <= 2))
                passed = fraction >= 0.98 and gap <= 5
                checks.append(
                    {
                        "id": oid,
                        "member": idx,
                        "type": typ,
                        "max_distance_px": float(ds.max()),
                        "source_fraction": fraction,
                        "maximum_gap_px": gap,
                        "samples": len(ds),
                        "pass": passed,
                    }
                )
                key = json.dumps(
                    sorted([np.round(a, 7).tolist(), np.round(b, 7).tolist()])
                )
                if key in seen:
                    previous = seen[key]
                    repeated = {
                        "objects": [previous["id"], oid],
                        "same_geometry": key,
                        "actual_handles": [previous["handle"], e.dxf.handle],
                        "expanded_member_indices": [previous["member"], idx],
                        "segment_indices": [previous["segment"], segment_index],
                    }
                    all_repeated.append(repeated)
                    allowed = allowed_retraces.get(
                        (e.dxf.handle, *sorted((previous["segment"], segment_index)))
                    )
                    if (
                        allowed is not None
                        and previous["handle"] == e.dxf.handle
                        and previous["member"] == idx == 0
                        and previous["top_level_open_polyline"]
                        and e.dxftype() == "LWPOLYLINE"
                        and m is e
                    ):
                        certified_retraces.append(
                            {**repeated, "source_certificate": allowed}
                        )
                    else:
                        duplicates.append(repeated)
                else:
                    seen[key] = {
                        "id": oid,
                        "handle": e.dxf.handle,
                        "member": idx,
                        "segment": segment_index,
                        "top_level_open_polyline": e.dxftype() == "LWPOLYLINE"
                        and m is e
                        and not e.closed,
                    }
                entities.append({"id": oid, "start": a.tolist(), "end": b.tolist()})
    report = {
        "dxf_sha256": before,
        "dxf_unchanged": before == sha(path),
        "ezdxf_errors": [str(x) for x in audit.errors],
        "ezdxf_in_memory_fixes": [str(x) for x in audit.fixes],
        "formal_modelspace_types": dict(counts),
        "expanded_formal_types": dict(members),
        "texts": texts,
        "source_checks": checks,
        "source_geometry_gate_pass": all(x["pass"] for x in checks),
        "local_retrace_certificate_gate_pass": all(
            row["pass"] for row in retrace_proof["object_checks"]
        ),
        "source_gate_pass": all(x["pass"] for x in checks)
        and all(row["pass"] for row in retrace_proof["object_checks"]),
        "exact_duplicate_segments": duplicates,
        "all_repeated_segments": all_repeated,
        "certified_same_owner_retraces": certified_retraces,
        "same_owner_retrace_cold_proof": retrace_proof,
        "duplicate_geometry_policy": {
            "all_observed_repetitions_retained_in_report": True,
            "cross_entity_or_unproved_repetition_still_blocks": True,
            "exemption_requires_same_actual_modelspace_handle_and_exact_protected_segment_indices": True,
            "source_or_DXF_geometry_modified": False,
        },
        "room_block_definitions_are_unique": len(room_blocks) == len(set(room_blocks)),
        "snapshot": snapshot(doc),
        "CAD_GUI": "NOT_RUN_BY_THIS_AUDIT",
        "engineer_UAT": "NOT_MEASURED",
        "source_distance_field_bbox_xyxy_px": [ox, oy, rx, by],
        "ROI_is_not_a_white_source_mask": True,
        "source_distance_thresholds_changed": False,
    }
    if circular_checks:
        report["circular_marker_source_checks"] = circular_checks
        report["circular_member_source_sampling"] = {
            "closed_circle_sweep_deg": 360.0,
            "maximum_sample_spacing_px": 0.05,
            "source_distance_tolerance_px": 2.5,
            "circle_and_character_evidence_replayed": True,
            "missing_or_unreadable_evidence_passes": False,
        }
    if circle_contact_checks:
        report["circle_endpoint_contact_checks"] = circle_contact_checks
    if circle_white_gap_checks:
        report["circle_white_gap_protection_checks"] = circle_white_gap_checks
    save_json(out, report)
    return report


class _PortableTextRenderer(UnifiedTextRenderer):
    """Use the saved font for native text without changing system font caches.

    ezdxf resolves a style's filename through its system FontManager; it does
    not search beside the DXF. A missing installed DejaVu can silently become
    a fallback such as Arial, although export measured the bundled font.
    The public sideload API bypasses that fallback, and an instance per render
    also avoids the drawing pipeline's shared, filename-only text cache.
    """

    def __init__(self, font_path):
        super().__init__()
        self.portable_name = font_path.name.casefold()
        self.portable_font = fonts.sideload_ttf(font_path.resolve(), 1.0)

    def get_font(self, font_face):
        if font_face.filename.casefold() == self.portable_name:
            return self.portable_font
        return super().get_font(font_face)


def _saved_text_renderer(doc, path, context):
    native_styles = {
        style.dxf.name.casefold()
        for style in doc.styles
        if style.dxf.font.casefold() == "dejavusans.ttf"
    }
    if not any(
        entity.dxftype() in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF")
        and entity.dxf.get("style", "Standard").casefold() in native_styles
        for entity in doc.entitydb.values()
    ):
        return None, None
    font_path = Path(path).parent / "DejaVuSans.ttf"
    # Missing or unreadable saved resources must fail, even if a same-named
    # system font happens to exist. The DXF and its audit remain untouched.
    renderer = _PortableTextRenderer(font_path)
    for name in native_styles:
        context.fonts[name] = fonts.FontFace(filename=font_path.name)
    return renderer, {
        "font": font_path.name,
        "sha256": sha(font_path),
        "resolution": "DXF_adjacent_file_via_ezdxf_sideload_ttf",
        "system_font_fallback": False,
    }


@profiled("cad_io.render_saved")
def render_saved(path, png_path, roi, dpi=200, include_review=False):
    if int(dpi) != dpi:
        raise ValueError("NATIVE_REVIEW_RENDER_REQUIRES_INTEGER_DPI")
    raster_dpi = int(dpi)
    doc = ezdxf.readfile(path)
    mm = 25.4 / dpi
    w = (roi[2] - roi[0]) * mm
    h = (roi[3] - roi[1]) * mm
    if include_review:
        doc.layers.get("REVIEW").on()
        doc.layers.get("REVIEW").thaw()
    cfg = config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.COLOR,
        lineweight_policy=config.LineweightPolicy.ABSOLUTE,
        min_lineweight=0.0,
    )
    recorder = Recorder()
    context = RenderContext(doc)
    text_renderer, font_receipt = _saved_text_renderer(doc, path, context)
    frontend = Frontend(context, recorder, config=cfg)
    if text_renderer is not None:
        frontend.pipeline.text_engine = text_renderer
    frontend.draw_layout(
        doc.modelspace(),
        finalize=True,
        filter_func=lambda e: include_review or e.dxf.layer != "REVIEW",
    )
    player = recorder.player()
    scale = 72 / 25.4
    wp, hp = w * scale, h * scale
    player.transform(
        Matrix44.chain(
            Matrix44.scale(scale, -scale, 1),
            Matrix44.translate(mm * scale * 0.5, hp + mm * scale * 0.5, 0),
        )
    )
    backend = PyMuPdfRenderBackend(layout.Page(w, h), layout.Settings(fit_page=False))
    backend.doc.close()
    backend.doc = fitz.open()
    backend.page_width_in_pt = wp
    backend.page_height_in_pt = hp
    backend.page = backend.doc.new_page(width=wp, height=hp)
    backend.content_shape = backend.page.new_shape()
    try:
        player.replay(backend)
        pix = backend.get_pixmap(dpi=raster_dpi, alpha=False)
        pix.save(str(png_path))
        Path(png_path).with_suffix(".pdf").write_bytes(backend.get_pdf_bytes())
        return {
            "renderer": "official_ezdxf_to_MuPDF",
            "DXF_sha256": sha(path),
            "png_path": str(png_path),
            "size_px": [pix.width, pix.height],
            "CAD_GUI_screenshot": False,
            "portable_text_font": font_receipt,
        }
    finally:
        backend.doc.close()
