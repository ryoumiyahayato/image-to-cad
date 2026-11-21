"""Real DXF writer, cold-reader and official ezdxf -> MuPDF consumer."""

from .performance import profiled
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import shutil
import numpy as np
import ezdxf
import fitz
from ezdxf.math import Matrix44
from ezdxf.lldxf.tagwriter import TagWriter
from ezdxf.tools.text_size import text_size
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
from ezdxf.addons.drawing.recorder import Recorder
from ezdxf.addons.drawing.pymupdf import PyMuPdfRenderBackend
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
)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def identity(e):
    return json.loads(e.get_xdata(APPID)[0].value)


def mark(e, o):
    e.set_xdata(
        APPID,
        [(1000, json.dumps({"id": o["id"], "kind": o["kind"]}, ensure_ascii=True))],
    )


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
def export_objects(objects, path, roi, dpi, source_sha):
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
        if kind == "LINE":
            e = msp.add_line(xy(g["start"]), xy(g["end"]), dxfattribs=attrs)
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
                paragraph = "\\pxi0,l" + format(left_offset * mm / h, ".10g") + ",r0,ql;"
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
                        "source_left_offset_applied": True,
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
                    "rotation": -g.get("rotation_deg_image", 0),
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
    room_blocks = []
    evidence_root = Path(out).parent
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
            elif typ == "ARC":
                c = px(m.dxf.center)
                r = m.dxf.radius / mm
                angle = np.deg2rad(
                    np.linspace(
                        m.dxf.start_angle,
                        m.dxf.start_angle + (m.dxf.end_angle - m.dxf.start_angle) % 360,
                        max(
                            3,
                            int(
                                math.ceil(
                                    r
                                    * math.radians(
                                        (m.dxf.end_angle - m.dxf.start_angle) % 360
                                    )
                                    / 0.05
                                )
                            )
                            + 1,
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
                        "pass": bool(ds.max() <= 2.5),
                    }
                )
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
    save_json(out, report)
    return report


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
    Frontend(RenderContext(doc), recorder, config=cfg).draw_layout(
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
        }
    finally:
        backend.doc.close()
