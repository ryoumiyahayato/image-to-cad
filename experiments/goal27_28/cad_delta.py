"""Snapshot content comparison. No operation truth or target handles are inputs.

An equal record proves equal content, never historical instance identity.
Only raw input DXFs are the lossless record; deltas retain changed raw values.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import hashlib
import math
from pathlib import Path
import sys

import ezdxf
from ezdxf import colors
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.tools.difftags import diff_tags

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cad_photo_to_dxf"))
from app.export.portable_dxf import PortableDxfError, live_images, package_dxf, _resolve

MM_TOLERANCE = 0.001
SUPPORTED = {"TEXT", "MTEXT", "LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "HATCH", "IMAGE", "INSERT", "POINT", "SOLID", "TRACE"}
LOCAL_FIELDS = {"handle", "owner", "image_def_handle", "image_def_reactor_handle", "material_handle", "plotstyle_handle", "visualstyle_handle"}


def plain(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite CAD value")
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return list(value)
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def frozen(value):
    if isinstance(value, dict):
        return tuple((k, frozen(v)) for k, v in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(frozen(v) for v in value)
    return value


def values(entity, fields):
    return {k: plain(entity.dxf.get(k, default) if entity.dxf.is_supported(k) else default) for k, default in fields.items()}


def color(entity):
    rgb = entity.dxf.get("true_color")
    aci = abs(entity.dxf.get("color", 256))
    if rgb is not None:
        return {"rgb": list(colors.int2rgb(rgb))}
    if 0 < aci < 256 and aci != 7:
        return {"rgb": list(colors.aci2rgb(aci))}
    # ACI7 adapts to canvas; explicit black and ACI7 must remain different.
    return {"aci": aci}


def hatch_boundary(entity):
    loops = []
    for path in entity.paths:
        edges = []
        if hasattr(path, "vertices"):
            vs = list(path.vertices)
            for a, b in zip(vs, vs[1:] + (vs[:1] if path.is_closed else [])):
                if a[2] == 0:
                    edges.append(["LineEdge", *sorted([plain(a[:2]), plain(b[:2])])])
                else:
                    edges.append(["BulgedEdge", plain(a), plain(b)])
        else:
            for edge in path.edges:
                if type(edge).__name__ == "LineEdge":
                    edges.append(["LineEdge", *sorted([plain(edge.start), plain(edge.end)])])
                else:
                    edges.append([type(edge).__name__, plain(vars(edge))])
        loops.append(sorted(edges, key=repr))
    return sorted(loops, key=repr)


def content(entity):
    kind = entity.dxftype()
    row = {"type": kind, **values(entity, {"layer": "0", "linetype": "BYLAYER", "lineweight": -1, "ltscale": 1.0, "invisible": 0, "transparency": None, "extrusion": (0., 0., 1.)}), "paint": color(entity)}
    row["linetype"] = row["linetype"].upper()
    fields = {
        "LINE": {"start": (0., 0., 0.), "end": (0., 0., 0.), "thickness": 0.},
        "TEXT": {"text": "", "insert": (0., 0., 0.), "height": 1., "width": 1., "rotation": 0., "oblique": 0., "halign": 0, "valign": 0, "style": "Standard", "text_generation_flag": 0, "thickness": 0.},
        "MTEXT": {"insert": (0., 0., 0.), "char_height": 1., "width": 0., "rotation": 0., "attachment_point": 1, "flow_direction": 1, "style": "Standard", "line_spacing_style": 1, "line_spacing_factor": 1., "text_direction": (1., 0., 0.), "bg_fill": 0, "bg_fill_color": 0, "bg_fill_true_color": None, "box_fill_scale": 1.5, "bg_fill_color_name": None, "bg_fill_transparency": 0},
        "CIRCLE": {"center": (0., 0., 0.), "radius": 1., "thickness": 0.},
        "ARC": {"center": (0., 0., 0.), "radius": 1., "start_angle": 0., "end_angle": 360., "thickness": 0.},
        "ELLIPSE": {"center": (0., 0., 0.), "major_axis": (1., 0., 0.), "ratio": 1., "start_param": 0., "end_param": math.tau},
        "INSERT": {"name": "", "insert": (0., 0., 0.), "xscale": 1., "yscale": 1., "zscale": 1., "rotation": 0., "column_count": 1, "row_count": 1, "column_spacing": 0., "row_spacing": 0.},
        "POINT": {"location": (0., 0., 0.), "thickness": 0.},
        "IMAGE": {"insert": (0., 0., 0.), "u_pixel": (1., 0., 0.), "v_pixel": (0., 1., 0.), "image_size": (0., 0.), "flags": 3, "clipping": 0, "clipping_boundary_type": 1, "brightness": 50, "contrast": 50, "fade": 0},
        "HATCH": {"solid_fill": 1, "pattern_name": "SOLID", "hatch_style": 0, "elevation": (0., 0., 0.), "pattern_angle": 0., "pattern_scale": 1., "pattern_double": 0},
        "LWPOLYLINE": {"elevation": 0., "const_width": 0., "thickness": 0.},
    }
    row.update(values(entity, fields.get(kind, {})))
    if kind == "TEXT" and (row["halign"] or row["valign"]):
        row["align_point"] = plain(entity.dxf.get("align_point", entity.dxf.insert))
    if kind == "MTEXT":
        row["text"] = entity.text
    if kind == "LWPOLYLINE":
        row.update(closed=entity.closed, points=plain(entity.get_points("xyseb")))
    if kind == "HATCH":
        row.update(boundaries=hatch_boundary(entity), loop_count=len(entity.paths), pattern=plain(entity.pattern.as_list()) if entity.pattern else None, gradient=plain(vars(entity.gradient)) if entity.gradient else None)
    if kind == "IMAGE":
        row.update(boundary_path=plain(entity.boundary_path))
    if kind == "POLYLINE":
        row.update(flags=entity.dxf.flags, vertices=[{k: plain(v) for k, v in e.dxf.all_existing_dxf_attribs().items() if k not in LOCAL_FIELDS} for e in entity.vertices])
    if kind == "SPLINE":
        row.update(values(entity, {"degree": 3, "flags": 0, "knot_tolerance": 1e-7, "control_point_tolerance": 1e-7, "fit_tolerance": 1e-10}))
        row.update(control_points=plain(entity.control_points), fit_points=plain(entity.fit_points), knots=plain(entity.knots), weights=plain(entity.weights))
    if kind in {"SOLID", "TRACE"}:
        row.update(values(entity, {"vtx0": (0., 0., 0.), "vtx1": (0., 0., 0.), "vtx2": (0., 0., 0.), "vtx3": (0., 0., 0.)}))
    if kind == "INSERT":
        row["attribs"] = [plain({k: v for k, v in a.dxf.all_existing_dxf_attribs().items() if k not in LOCAL_FIELDS}) for a in entity.attribs]
    if kind not in SUPPORTED:
        row["unsupported_raw"] = [[t.code, plain(t.value)] for t in TagCollector.dxftags(entity) if t.code not in {5, 330}]
    return row


def source_tags(entity):
    return {name: [[t.code, plain(t.value)] for t in tags] for name, tags in entity.xdata.data.items()} if entity.xdata else {}


def source_validity(entity):
    result = {}
    for appid, reader in (("P16_LINE_SOURCE", "line"), ("P16_CONTOUR_SOURCE", "contour")):
        if not entity.has_xdata(appid):
            continue
        try:
            if reader == "line":
                from app.export.line_source_ref import read_line_source_ref
                record = read_line_source_ref(entity)
            else:
                from app.export.contour_source_ref import read_contour_source_ref
                record = read_contour_source_ref(entity)
            result[appid] = "VALID_CURRENT_RECORD" if record else "ABSENT"
        except (ValueError, TypeError, ImportError) as exc:
            result[appid] = "STALE_OR_UNSUPPORTED: " + str(exc)
    for appid in source_tags(entity):
        result.setdefault(appid, "RETAINED_UNVALIDATED_VERSION")
    return result


@dataclass
class Snapshot:
    path: Path
    doc: object
    rows: list
    metadata: dict
    assets: dict
    missing: list
    units_mm: float
    file_sha256: str = ""


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _assert_snapshot_file(snapshot):
    if not snapshot.file_sha256 or _file_sha256(snapshot.path) != snapshot.file_sha256:
        raise ValueError("SOURCE_RECORD_INPUT_CHANGED: " + snapshot.path.name)


def validate_source_record_binding(record, saved_path, *, baseline_path=None):
    """Check exact files/assets, not historical object correspondence.

    Any subsequent save invalidates this binding, even if visually equivalent.
    Generate a new record for that file; never transplant old XDATA by this check.
    """
    binding = record.get("file_binding", {})
    if binding.get("schema") != "source-file-binding-v1":
        raise ValueError("SOURCE_RECORD_FILE_BINDING_MISSING")
    saved = Path(saved_path).resolve(strict=True)
    if _file_sha256(saved) != binding.get("saved_sha256"):
        raise ValueError("SOURCE_RECORD_SAVED_FILE_MISMATCH")
    if baseline_path is not None and _file_sha256(baseline_path) != binding.get("baseline_sha256"):
        raise ValueError("SOURCE_RECORD_BASELINE_FILE_MISMATCH")
    for asset in binding.get("saved_images", ()):
        path = _resolve(asset["file"], saved.parent, {})
        if _file_sha256(path) != asset["sha256"]:
            raise ValueError("SOURCE_RECORD_IMAGE_MISMATCH: " + asset["file"])
    return {"files_match": True, "historical_identity": "NOT_PROVEN",
            "source_automatic_operations": False}


def read(path):
    path = Path(path).resolve()
    fingerprint = _file_sha256(path)
    doc = ezdxf.readfile(path)
    if _file_sha256(path) != fingerprint:
        raise ValueError("SOURCE_RECORD_INPUT_CHANGED_DURING_READ: " + path.name)
    factors = {1: 25.4, 2: 304.8, 4: 1., 5: 10., 6: 1000., 14: 100.}
    unit = int(doc.header.get("$INSUNITS", 0))
    if unit not in factors:
        raise ValueError(f"Unsupported/unspecified INSUNITS {unit}; explicit conversion required")
    # Resolve before live_images, which also traverses INSERT references.
    referenced_content(doc)
    rows = [{"handle": e.dxf.handle, "content": content(e), "source": source_tags(e), "source_validity": source_validity(e)} for e in doc.modelspace()]
    assets, missing = {}, []
    for entity in live_images(doc):
        filename = entity.image_def.dxf.filename if entity.image_def else ""
        try:
            resource = _resolve(filename, path.parent, {})
            data = resource.read_bytes()
            from PIL import Image
            import io
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            assets[entity.dxf.handle] = {"filename": filename, "bytes": data, "path": str(resource), "definition": values(entity.image_def, {"pixel_size": (1., 1.), "image_size": (0., 0.), "loaded": 1, "resolution_units": 0})}
        except (ValueError, OSError) as exc:
            missing.append({"handle": entity.dxf.handle, "file": filename, "error": str(exc)})
    metadata = {
        "coordinates": {k: plain(doc.header.get(k)) for k in ("$INSUNITS", "$MEASUREMENT", "$INSBASE", "$UCSORG", "$UCSXDIR", "$UCSYDIR", "$ELEVATION")},
        "layers": {e.dxf.name: {"off": e.is_off(), "frozen": e.is_frozen(), "locked": e.is_locked(), "paint": color(e), **values(e, {"linetype": "Continuous", "lineweight": -3, "plot": 1})} for e in doc.layers},
        "styles": {e.dxf.name: values(e, {"font": "", "bigfont": "", "height": 0., "width": 1., "oblique": 0., "generation_flags": 0}) for e in doc.styles},
        "linetypes": {e.dxf.name: [[t.code, plain(t.value)] for t in e.pattern_tags.tags] for e in doc.linetypes},
        "blocks": {b.name: {"base_point": plain(b.block.dxf.base_point), "members": [content(e) for e in b]} for b in doc.blocks if not b.name.startswith("*Model_Space") and not b.name.startswith("*Paper_Space")},
    }
    for layer in metadata["layers"].values():
        layer["linetype"] = layer["linetype"].upper()
    return Snapshot(path, doc, rows, metadata, assets, missing, factors[unit], fingerprint)


def referenced_content(doc):
    """Reachable block closure without expanding/transformation of geometry."""
    blocks, active, rows = set(), set(), []

    def visit(entities):
        for entity in entities:
            row = content(entity)
            rows.append(row)
            if entity.dxftype() == "MTEXT" and entity.has_columns:
                raise ValueError("UNSUPPORTED_MTEXT_COLUMNS")
            if row["type"] != "INSERT":
                continue
            name = row["name"].casefold()
            if name in active:
                raise ValueError("UNSUPPORTED_BLOCK_CYCLE: " + row["name"])
            if name in blocks:
                continue
            block = doc.blocks.get(row["name"])
            if block is None:
                raise ValueError("MISSING_BLOCK: " + row["name"])
            blocks.add(name)
            active.add(name)
            visit(block)
            active.remove(name)

    visit(doc.modelspace())
    return rows, blocks


def fields_changed(a, b, prefix=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out.extend(fields_changed(a.get(key), b.get(key), f"{prefix}.{key}" if prefix else key))
        return out
    if a == b:
        return []
    return [{"field": prefix, "before": a, "after": b}]


def scale(row):
    if row["type"] in {"TEXT", "MTEXT"}:
        return max(row.get("height", row.get("char_height", 0.)), row.get("height", row.get("char_height", 0.)) * row.get("width", 1.) * max(1, len(row.get("text", ""))))
    if "radius" in row:
        return row["radius"]
    if "start" in row and "end" in row:
        return math.dist(row["start"], row["end"])
    return None


def near(a, b, tolerance):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return abs(a - b) <= tolerance
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return all(near(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def functional_equal(a, b, units):
    changes = fields_changed(a, b)
    coordinate = {"insert", "align_point", "start", "end", "center", "radius", "height", "char_height", "elevation", "const_width", "thickness", "location", "control_points", "fit_points", "boundaries"}
    for delta in changes:
        key = delta["field"]
        if key in coordinate:
            if not near(delta["before"], delta["after"], MM_TOLERANCE / units):
                return False
        elif key == "points" and a["type"] == "LWPOLYLINE":
            if len(a[key]) != len(b[key]) or any(x[4] != y[4] or not near(x[:4], y[:4], MM_TOLERANCE / units) for x, y in zip(a[key], b[key])):
                return False
        elif key in {"rotation", "oblique", "start_angle", "end_angle"}:
            extent = max(scale(a) or 0, scale(b) or 0)
            if extent == 0 or abs(delta["before"] - delta["after"]) * math.pi / 180 * extent * units > MM_TOLERANCE:
                return False
        elif key == "width" and a["type"] == b["type"] == "TEXT":
            span = max(a["height"], b["height"]) * max(1, len(a["text"]), len(b["text"]))
            if abs(a[key] - b[key]) * span * units > MM_TOLERANCE:
                return False
        else:
            return False
    return True


def anchor(row):
    for key in ("insert", "start", "center", "location"):
        if key in row:
            return row[key][:2]
    if row.get("points"):
        return row["points"][0][:2]
    return None


def _linear_hatch_anchor(row):
    """Conservative lookup key, NEVER a correspondence or identity decision.

    Canonical linear HATCH boundaries can acquire sub-resolution decimal noise
    in a CAD save. Previously every such hatch was compared with every pending
    hatch. A minimum endpoint is Lipschitz under the existing per-coordinate
    tolerance: any peer accepted by proposal_score has an anchor within that
    tolerance. Curved, malformed or empty boundaries remain exhaustive.
    """
    if row.get("type") != "HATCH":
        return None
    points = []
    for loop in row.get("boundaries", ()):
        for edge in loop:
            if not isinstance(edge, (tuple, list)) or len(edge) != 3 or edge[0] != "LineEdge":
                return None
            for point in edge[1:]:
                if (not isinstance(point, (tuple, list)) or len(point) != 2
                        or any(isinstance(v, bool) or not isinstance(v, (int, float))
                               or not math.isfinite(v) for v in point)):
                    return None
                points.append(point)
    if not points:
        return None
    return (min(p[0] for p in points), min(p[1] for p in points))


def _hatch_cell(row, cell_size):
    point = _linear_hatch_anchor(row)
    if point is None:
        return None
    scaled = tuple(v / cell_size for v in point)
    # At huge coordinate magnitudes use the legacy exhaustive path rather than
    # risk a floating-point bin skip. No geometry is rounded or rewritten.
    if not all(math.isfinite(v) and abs(v) <= 2**40 for v in scaled):
        return None
    return tuple(math.floor(v) for v in scaled)


def proposal_score(a, b, units):
    if a["type"] != b["type"]:
        return None
    changed = {d["field"] for d in fields_changed(a, b)}
    if functional_equal(a, b, units):
        return (0, 0.)
    property_fields = {"paint.aci", "paint.rgb", "layer", "linetype", "lineweight", "invisible", "text", "height", "width", "style", "rotation", "oblique"}
    omitted = {k.split(".")[0] for k in property_fields}
    ga, gb = ({k: v for k, v in row.items() if k not in omitted} for row in (a, b))
    if changed <= property_fields or functional_equal(ga, gb, units):
        return (1, float(len(changed)))
    pa, pb = anchor(a), anchor(b)
    distance = math.dist(pa, pb) * units if pa is not None and pb is not None else None
    if distance is not None and distance <= MM_TOLERANCE:
        return (2, float(len(changed)))
    if a["type"] in {"TEXT", "MTEXT"} and a.get("text") == b.get("text"):
        return (3, distance or 0.)
    # Nearby changed text remains a suggestion, never a source assertion.
    if a["type"] in {"TEXT", "MTEXT"} and distance is not None and distance <= 5 and a["layer"] == b["layer"]:
        return (4, distance)
    return None


def raw_delta(a, b):
    ta, tb = TagCollector.dxftags(a), TagCollector.dxftags(b)
    # Raw originals remain alongside the report. No rounding is applied here.
    return [{"operation": op.opcode.name, "before": [[t.code, plain(t.value)] for t in ta[op.i1:op.i2]], "after": [[t.code, plain(t.value)] for t in tb[op.j1:op.j2]]} for op in diff_tags(ta, tb) if op.opcode.name != "equal"]


def compare(before, after):
    a = read(before) if not isinstance(before, Snapshot) else before
    b = read(after) if not isinstance(after, Snapshot) else after
    if a.units_mm != b.units_mm:
        raise ValueError("UNIT_CONFLICT: rescale requires explicit review")
    left, right = defaultdict(list), defaultdict(list)
    for i, row in enumerate(a.rows):
        left[frozen(row["content"])].append(i)
    for i, row in enumerate(b.rows):
        right[frozen(row["content"])].append(i)
    pairs, duplicates = [], []
    used_a, used_b = set(), set()
    for key in left.keys() & right.keys():
        ia, ib = left[key], right[key]
        count = min(len(ia), len(ib))
        for x, y in zip(ia[:count], ib[:count]):
            pairs.append((x, y, "CONTENT_EQUAL" if len(ia) == len(ib) == 1 else "EQUAL_MULTIPLICITY_ONLY"))
            used_a.add(x); used_b.add(y)
        if len(ia) != 1 or len(ib) != 1:
            duplicates.append({"before": [a.rows[i]["handle"] for i in ia], "after": [b.rows[i]["handle"] for i in ib], "count_changed": len(ia) != len(ib), "identity": "AMBIGUOUS"})
    pending_a = [i for i in range(len(a.rows)) if i not in used_a]
    pending_b = [i for i in range(len(b.rows)) if i not in used_b]
    by_type, spatial = defaultdict(list), defaultdict(list)
    cell_size = MM_TOLERANCE / a.units_mm
    hatch_grid, hatch_unindexed = defaultdict(list), []
    # Four tolerance units per bin plus the 3x3 neighbours is a conservative
    # superset. Original floating values still reach the unmodified scorer.
    hatch_cell_size = 4 * cell_size
    diagnostics = {"policy": "linear-hatch-candidate-index-v1",
                   "candidate_pairs_evaluated": 0, "hatch_index_queries": 0,
                   "hatch_exhaustive_queries": 0}
    for j in pending_b:
        row = b.rows[j]["content"]
        by_type[row["type"]].append(j)
        if row["type"] == "HATCH":
            cell = _hatch_cell(row, hatch_cell_size)
            if cell is None:
                hatch_unindexed.append(j)
            else:
                hatch_grid[cell].append(j)
        point = anchor(row)
        if point is not None:
            spatial[(row["type"], math.floor(point[0] / cell_size), math.floor(point[1] / cell_size))].append(j)
    choices_a, choices_b = {}, defaultdict(list)
    for i in pending_a:
        options = []
        row = a.rows[i]["content"]
        point = anchor(row)
        hatch_cell = _hatch_cell(row, hatch_cell_size) if row["type"] == "HATCH" else None
        if hatch_cell is not None:
            cx, cy = hatch_cell
            candidate_indexes = sorted(set(hatch_unindexed).union(
                j for x in range(cx-1, cx+2) for y in range(cy-1, cy+2)
                for j in hatch_grid[(x, y)]))
            diagnostics["hatch_index_queries"] += 1
        elif point is not None and row["type"] not in {"TEXT", "MTEXT"}:
            cx, cy = [math.floor(v / cell_size) for v in point]
            candidate_indexes = [j for x in range(cx-1, cx+2) for y in range(cy-1, cy+2) for j in spatial[(row["type"], x, y)]]
        else:
            candidate_indexes = by_type[row["type"]]
            if row["type"] == "HATCH":
                diagnostics["hatch_exhaustive_queries"] += 1
        for j in candidate_indexes:
            diagnostics["candidate_pairs_evaluated"] += 1
            score = proposal_score(a.rows[i]["content"], b.rows[j]["content"], a.units_mm)
            if score is not None:
                options.append((score, j))
        if options:
            options.sort()
            best = options[0][0]
            candidates = [j for score, j in options if score == best]
            choices_a[i] = candidates
            for j in candidates:
                choices_b[j].append(i)
    ambiguous = []
    for i, candidates in choices_a.items():
        if len(candidates) == 1 and len(choices_b[candidates[0]]) == 1:
            j = candidates[0]
            status = "FUNCTIONALLY_EQUAL" if functional_equal(a.rows[i]["content"], b.rows[j]["content"], a.units_mm) else "CORRESPONDENCE_SUGGESTION"
            pairs.append((i, j, status)); used_a.add(i); used_b.add(j)
        else:
            ambiguous.append({"before": a.rows[i]["handle"], "after_candidates": [b.rows[j]["handle"] for j in candidates], "status": "AMBIGUOUS"})
    changes, mappings, serialization = [], [], []
    source_lost = 0
    for i, j, status in sorted(pairs):
        ar, br = a.rows[i], b.rows[j]
        h0, h1 = ar["handle"], br["handle"]
        mapping = {"before": h0, "after": h1, "status": status, "identity": "NOT_PROVEN", "source_automatic_operations": False}
        mappings.append(mapping)
        changed = fields_changed(ar["content"], br["content"])
        asset0, asset1 = a.assets.get(h0), b.assets.get(h1)
        asset_changes = []
        if asset0 and asset1:
            if asset0["bytes"] != asset1["bytes"]:
                asset_changes.append({"field": "asset_content", "before": "present", "after": "different bytes"})
            if asset0["filename"] != asset1["filename"]:
                asset_changes.append({"field": "asset_path", "before": asset0["filename"], "after": asset1["filename"]})
            asset_changes.extend(fields_changed(asset0["definition"], asset1["definition"], "IMAGEDEF"))
        elif bool(asset0) != bool(asset1):
            asset_changes.append({"field": "asset_availability", "before": bool(asset0), "after": bool(asset1)})
        if asset_changes:
            mapping["status"] = "ASSET_CHANGE"
        if status == "CORRESPONDENCE_SUGGESTION" or asset_changes:
            changes.append({**mapping, "fields": changed + asset_changes, "raw_delta": raw_delta(a.doc.entitydb[h0], b.doc.entitydb[h1])})
        elif changed:
            serialization.append({"before": h0, "after": h1, "reason": "BELOW_FUNCTIONAL_RESOLUTION; origin unknown", "fields": changed})
        if ar["source"] and not br["source"]:
            source_lost += 1
    removed = [a.rows[i]["handle"] for i in range(len(a.rows)) if i not in used_a]
    added = [b.rows[i]["handle"] for i in range(len(b.rows)) if i not in used_b]
    metadata_delta = []
    ar, ab = referenced_content(a.doc)
    br, bb = referenced_content(b.doc)
    used = {"styles": {r.get("style", "").casefold() for r in ar + br}, "linetypes": {r["linetype"].casefold() for r in ar + br} | {v["linetype"].casefold() for s in (a, b) for v in s.metadata["layers"].values()}, "blocks": ab | bb}
    for section in a.metadata:
        for name in sorted(set(a.metadata[section]) | set(b.metadata[section])):
            for change in fields_changed(a.metadata[section].get(name), b.metadata[section].get(name), f"{section}.{name}"):
                if section in used and name.casefold() not in used[section]:
                    serialization.append({"reason": "UNREFERENCED_TABLE_RECORD", **change})
                else:
                    metadata_delta.append(change)
    return {
        "before": str(a.path), "after": str(b.path), "precision_mm": MM_TOLERANCE,
        "counts_before": dict(Counter(r["content"]["type"] for r in a.rows)), "counts_after": dict(Counter(r["content"]["type"] for r in b.rows)),
        "matching_diagnostics": diagnostics,
        "mappings": mappings, "changes": changes, "removed_or_unmatched": removed, "added_or_unmatched": added,
        "ambiguous": ambiguous, "duplicate_groups": duplicates, "serialization_or_subresolution": serialization,
        "document_changes": metadata_delta, "source_records_lost": source_lost,
        "missing_dependencies": b.missing, "unsupported_types": sorted({r["type"] for r in ar + br} - SUPPORTED),
        "summary": {"content_equal": sum(p["status"] in {"CONTENT_EQUAL", "EQUAL_MULTIPLICITY_ONLY"} for p in mappings), "functional_equal": sum(p["status"] == "FUNCTIONALLY_EQUAL" for p in mappings), "changed_suggestions": len(changes), "unmatched_before": len(removed), "unmatched_after": len(added), "ambiguous_groups": len(ambiguous) + sum(d["count_changed"] for d in duplicates), "confirmed_historical_identities": 0},
    }


def _source_snapshot(snapshot):
    def member(entity, tags):
        return {
            "type": entity.dxftype(),
            "attributes": plain(entity.dxfattribs()),
            "xdata": tags,
        }

    modelspace = {
        row["handle"]: {
            **member(snapshot.doc.entitydb[row["handle"]], row["source"]),
            "source_validity": row["source_validity"],
        }
        for row in snapshot.rows if row["source"]
    }
    blocks = {}
    for block in snapshot.doc.blocks:
        if block.name.startswith(("*Model_Space", "*Paper_Space")):
            continue
        members = {e.dxf.handle: member(e, source_tags(e)) for e in block if e.xdata}
        if members:
            blocks[block.name] = members
    objects = [
        {**member(e, source_tags(e)), "owner": e.dxf.get("owner")}
        for e in snapshot.doc.objects.query("IMAGEDEF PLOTSETTINGS")
    ]
    return {
        "dxf_version": snapshot.doc.dxfversion,
        "layers": snapshot.metadata["layers"],
        "modelspace": modelspace,
        "blocks": blocks,
        "objects": objects,
    }


def retain_source_trace(before, after, report):
    """Archive file-local source metadata and separately list review candidates."""
    baseline, saved = _source_snapshot(before), _source_snapshot(after)
    source_handles = set(baseline["modelspace"])
    groups = [
        {"before": g["before"], "after_candidates": g["after"], "reason": "DUPLICATE_CONTENT"}
        for g in report["duplicate_groups"]
    ] + [
        {"before": [g["before"]], "after_candidates": g["after_candidates"], "reason": "AMBIGUOUS_MATCH"}
        for g in report["ambiguous"]
    ]
    ambiguous_before = {h for g in groups for h in g["before"]}
    ambiguous_after = {h for g in groups for h in g["after_candidates"]}
    candidates = [m for m in report["mappings"]
                  if m["before"] in source_handles
                  and m["before"] not in ambiguous_before and m["after"] not in ambiguous_after
                  and m["status"] != "EQUAL_MULTIPLICITY_ONLY"]
    # Keep unresolved records at their original handles. A duplicated entity
    # must never inherit the XDATA of an arbitrary peer selected by ordering.
    unmatched = source_handles - ambiguous_before - {m["before"] for m in candidates}
    return {
        "schema": "image-to-cad-source-trace-v1",
        "historical_identity": "NOT_PROVEN",
        "source_automatic_operations": False,
        "baseline": baseline,
        "saved": saved,
        "candidates": candidates,
        "ambiguous_groups": [g for g in groups if source_handles.intersection(g["before"])],
        "unmatched_baseline_handles": sorted(unmatched),
    }


def source_record(before, after):
    _assert_snapshot_file(before)
    _assert_snapshot_file(after)
    comparison = compare(before, after)
    result = {k: comparison[k] for k in (
        "before", "after", "precision_mm", "summary", "missing_dependencies", "unsupported_types",
    )}
    result["changes"] = [{k: v for k, v in change.items() if k != "raw_delta"}
                         for change in comparison["changes"]]
    result["document_changes"] = [change for change in comparison["document_changes"]
                                  if not change["field"].startswith("blocks.")]
    result["source_trace"] = retain_source_trace(before, after, comparison)
    result["matching_diagnostics"] = comparison["matching_diagnostics"]
    result["file_binding"] = {
        "schema": "source-file-binding-v1",
        "baseline_sha256": before.file_sha256,
        "saved_sha256": after.file_sha256,
        "saved_images": [
            {"file": asset["filename"],
             "sha256": hashlib.sha256(asset["bytes"]).hexdigest()}
            for asset in after.assets.values()
        ],
        "historical_identity": "NOT_PROVEN",
        "source_automatic_operations": False,
    }
    _assert_snapshot_file(before)
    _assert_snapshot_file(after)
    return result


def _delivery_block_sources(before, after, source_blocks):
    candidates, unresolved = [], {}
    for name, records in source_blocks.items():
        original = before.doc.blocks.get(name)
        delivered = after.doc.blocks.get(name)
        missing = set(records)
        if delivered is not None and near(
            plain(original.block.dxf.base_point), plain(delivered.block.dxf.base_point),
            MM_TOLERANCE / before.units_mm,
        ):
            left = [(e.dxf.handle, content(e)) for e in original if e.dxftype() in SUPPORTED]
            right = [(e.dxf.handle, content(e)) for e in delivered if e.dxftype() in SUPPORTED]
            matches, reverse = defaultdict(list), Counter()
            for handle, row in left:
                for target, other in right:
                    if row["type"] == other["type"] and functional_equal(row, other, before.units_mm):
                        matches[handle].append((target, other))
                        reverse[target] += 1
            for handle in records:
                peers = matches[handle]
                if len(peers) == 1 and reverse[peers[0][0]] == 1:
                    target, geometry = peers[0]
                    candidates.append({
                        "before_block": name, "after_block": delivered.name,
                        "before": handle, "after": target, "content": geometry,
                        "identity": "NOT_PROVEN", "source_automatic_operations": False,
                    })
                    missing.remove(handle)
        if missing:
            unresolved[name] = sorted(missing)
    return candidates, unresolved


def package_delivery(before_path, after_path, output_path, *, restore_layer_states=False, trusted_map=None):
    """Package an external save and compare the source to the actual ZIP DXF."""
    before = read(before_path)

    def record(target):
        delivered = read(target)
        if delivered.missing:
            raise PortableDxfError("Packaged IMAGE resources could not be read")
        result = source_record(before, delivered)
        trace = result["source_trace"]
        targets = {item["after"] for item in trace["candidates"]}
        trace["candidate_targets"] = {
            row["handle"]: row["content"] for row in delivered.rows if row["handle"] in targets
        }
        trace["block_candidates"], trace["unresolved_block_handles"] = _delivery_block_sources(
            before, delivered, trace["baseline"]["blocks"]
        )
        result["before"] = before.path.name
        result["after"] = target.name
        return result

    return package_dxf(
        after_path, output_path, trusted_map=trusted_map,
        layer_reference=before.doc if restore_layer_states else None,
        source_record=record,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("before"); parser.add_argument("after"); parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--retain-source", action="store_true",
                      help="Write a compact source record without modifying either DXF")
    mode.add_argument("--portable", action="store_true",
                      help="Package the after DXF, live images, font note and source record")
    parser.add_argument("--restore-layer-states", action="store_true",
                        help="With --portable, restore off/frozen/locked from matching baseline layers")
    parser.add_argument("--trusted-map", type=Path,
                        help="With --portable, JSON maps exact IMAGEDEF filenames to trusted files")
    args = parser.parse_args()
    if (args.restore_layer_states or args.trusted_map) and not args.portable:
        parser.error("--restore-layer-states and --trusted-map require --portable")
    if args.portable:
        try:
            mapping = json.loads(args.trusted_map.read_text(encoding="utf-8")) if args.trusted_map else None
            result = package_delivery(args.before, args.after, args.output,
                                      restore_layer_states=args.restore_layer_states, trusted_map=mapping)
        except (OSError, ValueError, ezdxf.DXFError) as exc:
            parser.exit(2, f"{exc}\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.retain_source:
        result = source_record(read(args.before), read(args.after))
        with Path(args.output).open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
    else:
        result = compare(args.before, args.after)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
