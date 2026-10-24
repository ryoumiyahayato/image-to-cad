"""Bounded complete LWP references to explicitly supplied source snapshots.

Old contours have no inferred source history. A trusted caller may bind a saved
generation record now; that operation is labelled P16F_REPLAY, not backdated.
Standalone XDATA proves internal consistency only, never physical authenticity.
"""

from __future__ import annotations
from dataclasses import replace
from math import isclose
import json
import uuid
import cv2
import numpy as np
from app.core.structure import metadata_to_jsonable
from app.export.line_source_ref import _text, _number, _integer, _pairs

APPID = "P16_CONTOUR_SOURCE"
KEY = "contour_source_bindings_v1"
VERSION = 1
MAX_BYTES = 8192
MAX_VERTICES = 128
CHUNK_BYTES = 240
CONTEXT_KEYS = {
    "source_path",
    "physical_page",
    "source_size_px",
    "snapshot_uuid",
    "bound_at_utc",
    "authority_ref",
    "generation_ref",
    "binding_context",
}
RECORD_KEYS = {
    "member_index",
    "points",
    "closed",
    "stage",
    "root_id",
    "source_runs",
    "source_pixels",
    "uncertain_runs",
    "uncertain_pixels",
    "basis",
}


def _context(context):
    if not isinstance(context, dict) or set(context) != CONTEXT_KEYS:
        raise ValueError("Malformed contour source context")
    for key in ("source_path", "authority_ref", "generation_ref"):
        _text(context[key], 1024)
    _text(context["bound_at_utc"], 64)
    _integer(context["physical_page"], 1)
    if context["binding_context"] != "P16F_REPLAY":
        raise ValueError("Unknown contour binding context")
    uuid.UUID(context["snapshot_uuid"])
    size = context["source_size_px"]
    if not isinstance(size, list) or len(size) != 2:
        raise ValueError("Contour source size is missing")
    for value in size:
        _integer(value, 1)


def _runs_mask(runs, size):
    if not isinstance(runs, list) or not 1 <= len(runs) <= 10000:
        raise ValueError("Missing or oversized contour source runs")
    width, height = size
    mask = np.zeros((height, width), np.uint8)
    previous = None
    for run in runs:
        if not isinstance(run, list) or len(run) != 3:
            raise ValueError("Malformed contour source run")
        y, left, right = run
        for value in run:
            _integer(value)
        if y >= height or not 0 <= left < right <= width:
            raise ValueError("Contour source run is outside its source page")
        if previous is not None and (
            y < previous[0] or (y == previous[0] and left <= previous[2])
        ):
            raise ValueError("Contour source runs overlap or are not canonical")
        mask[y, left:right] = 1
        previous = run
    return mask


def _validate_bindings(structure, bindings):
    if not isinstance(bindings, dict) or set(bindings) != {
        "version",
        "context",
        "structure_id",
        "records",
    }:
        raise ValueError("Malformed contour source snapshot")
    if (
        bindings["version"] != VERSION
        or bindings["structure_id"] != structure.source_structure_id
    ):
        raise ValueError("Contour source snapshot differs from current structure")
    context = bindings["context"]
    _context(context)
    if context["source_size_px"] != list(structure.source_size_px):
        raise ValueError("Contour source page dimensions differ")
    native = structure.provenance.get("pdf_native_suggestions_v1", {})
    for field in ("source_path", "physical_page"):
        if native.get(field) is not None and native[field] != context[field]:
            raise ValueError("Contour source context differs from saved source page")
    records = bindings["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= 16:
        raise ValueError("Missing or oversized contour source members")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            raise ValueError("Malformed contour generation member")
        index = _integer(record["member_index"])
        if index in seen or index >= len(structure.contours):
            raise ValueError("Contour source member identity is not unique")
        seen.add(index)
        path = structure.contours[index]
        points = [[float(x), float(y)] for x, y in path.points]
        if (
            record["points"] != points
            or record["closed"] is not True
            or not 3 <= len(points) <= MAX_VERTICES
            or path.depth % 2
            or any(p.parent == index for p in structure.contours)
        ):
            raise ValueError(
                "Contour source record requires a complete ordered leaf boundary"
            )
        for name in ("stage", "root_id", "basis"):
            _text(record[name])
        mask = _runs_mask(record["source_runs"], structure.source_size_px)
        pixels = _integer(record["source_pixels"], 1)
        if int(mask.sum()) != pixels or np.any(
            mask & (structure.contour_binary >= 128)
        ):
            raise ValueError("Contour source runs differ from actual final source mask")
        # Verify the entire actual component, including anything beyond its box.
        ys, xs = np.where(mask)
        x0, x1 = max(0, int(xs.min()) - 1), min(mask.shape[1], int(xs.max()) + 2)
        y0, y1 = max(0, int(ys.min()) - 1), min(mask.shape[0], int(ys.max()) + 2)
        _, labels = cv2.connectedComponents(
            (structure.contour_binary[y0:y1, x0:x1] < 128).astype(np.uint8), 8
        )
        label = labels[int(ys[0]) - y0, int(xs[0]) - x0]
        if not np.array_equal(labels == label, mask[y0:y1, x0:x1] > 0):
            raise ValueError("Contour source record omits part of its actual component")
        if any(not mask[int(y), int(x)] for x, y in points):
            raise ValueError("Contour boundary is not on its recorded component")
        uncertain = (
            _runs_mask(record["uncertain_runs"], structure.source_size_px)
            if record["uncertain_runs"]
            else np.zeros_like(mask)
        )
        if np.any(uncertain & (mask == 0)) or int(uncertain.sum()) != _integer(
            record["uncertain_pixels"]
        ):
            raise ValueError("Contour uncertainty differs from its source component")
    return bindings


def bind_contour_source_records(structure, *, context, records):
    """Explicit current binding; caller owns the trusted run/sidecar authority.

    Records retain original generation points, stage, member and complete runs.
    This function does not authenticate an arbitrary caller-supplied sidecar.
    """
    bindings = dict(
        version=VERSION,
        context=metadata_to_jsonable(context),
        structure_id=structure.source_structure_id,
        records=metadata_to_jsonable(records),
    )
    _validate_bindings(structure, bindings)
    return replace(structure, provenance={**structure.provenance, KEY: bindings})


def make_contour_source_refs(structure, *, physical_page=None):
    bindings = structure.provenance.get(KEY)
    if bindings is None:
        return {}
    bindings = _validate_bindings(structure, metadata_to_jsonable(bindings))
    if (
        physical_page is not None
        and bindings["context"]["physical_page"] != physical_page
    ):
        raise ValueError("Contour source physical page differs from export page")
    refs = {}
    for slot, record in enumerate(bindings["records"]):
        refs[record["member_index"]] = dict(
            **bindings["context"],
            structure_id=bindings["structure_id"],
            record_slot=slot,
            **{
                key: record[key]
                for key in (
                    "member_index",
                    "stage",
                    "root_id",
                    "source_pixels",
                    "uncertain_pixels",
                    "basis",
                )
            },
            source_points=record["points"],
        )
    return refs


def entity_record(entity):
    if entity.dxftype() != "LWPOLYLINE":
        raise ValueError("Contour reference requires native LWPOLYLINE")
    # These attributes affect visible output but are outside this bounded
    # default-stroke contract. Refuse them instead of silently omitting them.
    if (
        entity.dxf.hasattr("true_color")
        or entity.dxf.hasattr("transparency")
        or entity.dxf.get("invisible", 0) != 0
        or entity.dxf.get("thickness", 0) != 0
        or entity.dxf.get("ltscale", 1) != 1
        or entity.dxf.flags != 1
    ):
        raise ValueError("Unsupported nondefault contour display attributes")
    return dict(
        points=[[float(v) for v in p] for p in entity.get_points("xyseb")],
        closed=bool(entity.closed),
        elevation=float(entity.dxf.elevation),
        extrusion=list(entity.dxf.extrusion),
        const_width=float(entity.dxf.const_width),
        layer=entity.dxf.layer,
        color=int(entity.dxf.color),
        lineweight=int(entity.dxf.lineweight),
        linetype=entity.dxf.linetype,
    )


def _encoded(record):
    if (
        not isinstance(record, dict)
        or set(record) != {"version", "source", "entity"}
        or record["version"] != VERSION
    ):
        raise ValueError("Malformed contour reference")
    source = record["source"]
    source_keys = CONTEXT_KEYS | {
        "structure_id",
        "record_slot",
        "member_index",
        "stage",
        "root_id",
        "source_pixels",
        "uncertain_pixels",
        "basis",
        "transform",
    }
    if not isinstance(source, dict) or set(source) != source_keys:
        raise ValueError("Malformed contour reference source fields")
    _context({k: source[k] for k in CONTEXT_KEYS})
    for key in ("structure_id", "stage", "root_id", "basis"):
        _text(source[key])
    for key in ("record_slot", "member_index", "source_pixels", "uncertain_pixels"):
        _integer(source[key])
    if source["uncertain_pixels"] > source["source_pixels"]:
        raise ValueError("Contour uncertainty exceeds source")
    if not isinstance(source["transform"], list) or len(source["transform"]) != 6:
        raise ValueError("Missing contour page transform")
    for value in source["transform"]:
        _number(value)
    entity = record["entity"]
    if set(entity) != {
        "points",
        "closed",
        "elevation",
        "extrusion",
        "const_width",
        "layer",
        "color",
        "lineweight",
        "linetype",
    }:
        raise ValueError("Malformed contour entity fields")
    if entity["closed"] is not True or not 3 <= len(entity["points"]) <= MAX_VERTICES:
        raise ValueError("Contour reference requires complete bounded closed geometry")
    for point in entity["points"]:
        if not isinstance(point, list) or len(point) != 5:
            raise ValueError("Malformed contour vertex")
        for value in point:
            _number(value)
    for value in (entity["elevation"], entity["const_width"], *entity["extrusion"]):
        _number(value)
    for key in ("layer", "linetype"):
        _text(entity[key])
    for key in ("color", "lineweight"):
        if type(entity[key]) is not int:
            raise ValueError("Malformed contour entity attribute")
    payload = json.dumps(
        record, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    if len(payload) > MAX_BYTES:
        raise ValueError("Contour reference exceeds byte budget")
    return payload


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


def attach_contour_source_ref(entity, source, transform):
    source = dict(source)
    points = source.pop("source_points")
    origin, u, v = transform(0, 0), transform(1, 0), transform(0, 1)
    source["transform"] = [
        u[0] - origin[0],
        v[0] - origin[0],
        origin[0],
        u[1] - origin[1],
        v[1] - origin[1],
        origin[1],
    ]
    expected = [list(transform(x, y)) + [0.0, 0.0, 0.0] for x, y in points]
    entity_data = entity_record(entity)
    if not _same(entity_data["points"], expected):
        raise ValueError("Emitted contour differs from its complete source boundary")
    record = dict(version=VERSION, source=source, entity=entity_data)
    payload = _encoded(record)
    if APPID not in entity.doc.appids:
        entity.doc.appids.add(APPID)
    entity.set_xdata(
        APPID,
        [(1070, VERSION)]
        + [
            (1000, payload[i : i + CHUNK_BYTES])
            for i in range(0, len(payload), CHUNK_BYTES)
        ],
    )
    return record


def read_contour_source_ref(entity):
    if not entity.has_xdata(APPID):
        return None
    tags = list(entity.get_xdata(APPID))
    if (
        len(tags) < 2
        or len(tags) > 1 + (MAX_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES
        or tags[0].code != 1070
        or tags[0].value != VERSION
    ):
        raise ValueError("Malformed contour XDATA header")
    if any(
        t.code != 1000
        or not isinstance(t.value, str)
        or not t.value.isascii()
        or not 1 <= len(t.value) <= CHUNK_BYTES
        for t in tags[1:]
    ):
        raise ValueError("Malformed contour XDATA chunks")
    try:
        record = json.loads(
            "".join(t.value for t in tags[1:]), object_pairs_hook=_pairs
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("Malformed contour XDATA JSON") from exc
    _encoded(record)
    if not _same(entity_record(entity), record["entity"]):
        raise ValueError("Contour source binds different geometry or attributes")
    return record


def validate_contour_source_refs(entities, *, expected=None):
    entities = list(entities)
    actual = [
        (i, read_contour_source_ref(e))
        for i, e in enumerate(entities)
        if e.has_xdata(APPID)
    ]
    keys = [
        (r["source"]["snapshot_uuid"], r["source"]["member_index"]) for _, r in actual
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated contour source member")
    if expected is not None:
        expected = list(expected)
        if len(actual) != len(expected) or any(
            i != j or not _same(a, b) for (i, a), (j, b) in zip(actual, expected)
        ):
            raise ValueError("Contour source collection differs from trusted snapshot")
    return dict(
        status=("SNAPSHOT_VERIFIED" if expected is not None else "SELF_CONSISTENT_ONLY")
        if actual
        else "UNAVAILABLE",
        referenced=len(actual),
        missing=len(entities) - len(actual),
    )


def expected_contour_source_records(structure, export_plan):
    """Rebuild expectations from a trusted snapshot plus its export plan.

    The plan supplies export order, page transform and CAD presentation. Source
    context, members and every ordered vertex come from the saved snapshot.
    Never obtain this plan from the DXF currently being checked.
    """
    refs = make_contour_source_refs(structure)
    expected = []
    seen = set()
    slots = set()
    for item in export_plan:
        if set(item) != {
            "member_index",
            "entity_slot",
            "transform",
            "entity_attributes",
        }:
            raise ValueError("Malformed trusted contour export plan")
        member = _integer(item["member_index"])
        slot = _integer(item["entity_slot"])
        if member not in refs or member in seen or slot in slots:
            raise ValueError("Trusted contour export plan member differs from snapshot")
        seen.add(member)
        slots.add(slot)
        source = dict(refs[member])
        points = source.pop("source_points")
        matrix = item["transform"]
        if not isinstance(matrix, list) or len(matrix) != 6:
            raise ValueError("Malformed trusted contour page transform")
        a, b, c, d, e, f = [_number(v) for v in matrix]
        source["transform"] = matrix
        entity = dict(
            item["entity_attributes"],
            points=[
                [a * x + b * y + c, d * x + e * y + f, 0.0, 0.0, 0.0] for x, y in points
            ],
        )
        record = dict(version=VERSION, source=source, entity=entity)
        _encoded(record)
        expected.append((slot, record))
    if seen != set(refs):
        raise ValueError("Trusted contour export plan omits source members")
    return tuple(sorted(expected, key=lambda item: item[0]))


class ContourConsistencyGuard:
    def __init__(self):
        self.expected = []

    def capture(self, doc, expected_records):
        positions = {
            id(e): i for i, e in enumerate(doc.modelspace().query("LWPOLYLINE"))
        }
        self.expected.extend(
            (positions[id(e)], record) for e, record in expected_records
        )
        self.expected.sort(key=lambda item: item[0])

    def validate(self, doc):
        return validate_contour_source_refs(
            doc.modelspace().query("LWPOLYLINE"), expected=self.expected
        )
