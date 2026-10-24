"""Bounded run-local LINE references. No design identity or source authentication."""

from __future__ import annotations
import json
from math import isfinite, isclose, hypot

APPID = "P16_LINE_SOURCE"
VERSION = 1
MAX_BYTES = 8192
MAX_IDS = 128
CHUNK_BYTES = 240
_SOURCE_KEYS = {
    "structure_id",
    "member_index",
    "page_slot",
    "physical_page",
    "source_ids",
    "source_layer",
    "source_width",
}
_ENTITY_KEYS = {"start", "end", "layer", "color", "lineweight", "linetype"}


def _text(value, limit=255):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(
            "LINE source reference requires nonempty text without controls"
        )
    if len(value.encode("utf-8")) > limit:
        raise ValueError("LINE source reference text exceeds its bound")
    return value


def _number(value):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError("LINE source reference requires finite numbers")
    return float(value)


def _integer(value, lower=0):
    if type(value) is not int or value < lower:
        raise ValueError("LINE source reference requires a bounded nonnegative index")
    if value > 2147483647:
        raise ValueError("LINE source reference index exceeds its bound")
    return value


def _check_source(source):
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        raise ValueError("Malformed LINE source fields")
    _text(source["structure_id"], 128)
    _integer(source["member_index"])
    _integer(source["page_slot"])
    if source["physical_page"] is not None:
        _integer(source["physical_page"], 1)
    ids = source["source_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS:
        raise ValueError("LINE source IDs missing or overflowing")
    for item in ids:
        _text(item)
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated LINE source ID")
    _text(source["source_layer"])
    if _number(source["source_width"]) < 0:
        raise ValueError("Negative LINE source width")


def _check_entity(record):
    if not isinstance(record, dict) or set(record) != _ENTITY_KEYS:
        raise ValueError("Malformed LINE emitted fields")
    for name in ("start", "end"):
        if not isinstance(record[name], list) or len(record[name]) != 3:
            raise ValueError("Malformed LINE endpoint")
        for value in record[name]:
            _number(value)
    for name in ("layer", "linetype"):
        _text(record[name])
    for name in ("color", "lineweight"):
        if type(record[name]) is not int:
            raise ValueError("Malformed LINE attribute")


def _encoded(record):
    if not isinstance(record, dict) or set(record) != {"version", "source", "entity"}:
        raise ValueError("Malformed LINE reference record")
    if type(record["version"]) is not int or record["version"] != VERSION:
        raise ValueError("Unsupported LINE reference version")
    _check_source(record["source"])
    _check_entity(record["entity"])
    payload = json.dumps(
        record, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    if len(payload) > MAX_BYTES:
        raise ValueError("LINE source reference exceeds byte budget")
    return payload


def make_line_source_refs(structure, *, page_slot=0, physical_page=None):
    """Preserve original tuple index; empty old source facts stay absent."""
    _integer(page_slot)
    if physical_page is not None:
        _integer(physical_page, 1)
    structure_id = (
        structure.source_structure_id
    )  # source context excludes display-only fits
    refs = []
    for index, line in enumerate(structure.straight_lines):
        if not line.source_ids:
            refs.append(None)
            continue
        ref = dict(
            structure_id=structure_id,
            member_index=index,
            page_slot=page_slot,
            physical_page=physical_page,
            source_ids=list(line.source_ids),
            source_layer=line.layer,
            source_width=float(line.width),
        )
        _check_source(ref)
        refs.append(ref)
    return tuple(refs)


def entity_record(entity):
    if entity.dxftype() != "LINE":
        raise ValueError("LINE source reference attached to another entity type")
    return dict(
        start=list(entity.dxf.start),
        end=list(entity.dxf.end),
        layer=entity.dxf.layer,
        color=entity.dxf.color,
        lineweight=entity.dxf.lineweight,
        linetype=entity.dxf.linetype,
    )


def attach_line_source_ref(entity, source):
    if source is None:
        return
    record = dict(version=VERSION, source=source, entity=entity_record(entity))
    payload = _encoded(record)  # validate before writing metadata
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


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated LINE reference JSON key")
        result[key] = value
    return result


def _same_entity(actual, expected):
    for key in ("layer", "color", "lineweight", "linetype"):
        if actual[key] != expected[key]:
            return False
    return all(
        isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
        for key in ("start", "end")
        for a, b in zip(actual[key], expected[key])
    )


def read_line_source_ref(entity):
    if not entity.has_xdata(APPID):
        return None
    tags = list(entity.get_xdata(APPID))
    if (
        not tags
        or tags[0].code != 1070
        or tags[0].value != VERSION
        or len(tags) < 2
        or len(tags) > 1 + (MAX_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES
    ):
        raise ValueError("Malformed LINE source XDATA header")
    chunks = []
    for tag in tags[1:]:
        if tag.code != 1000 or not isinstance(tag.value, str):
            raise ValueError("Malformed LINE source XDATA chunk")
        if (
            not 1 <= len(tag.value.encode("ascii", errors="replace")) <= CHUNK_BYTES
            or not tag.value.isascii()
        ):
            raise ValueError("Malformed LINE source XDATA chunk length")
        chunks.append(tag.value)
    payload = "".join(chunks)
    if len(payload) > MAX_BYTES:
        raise ValueError("LINE source reference exceeds byte budget")
    try:
        record = json.loads(payload, object_pairs_hook=_pairs)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed LINE source JSON") from exc
    _encoded(record)
    actual = entity_record(entity)
    _check_entity(actual)
    if not _same_entity(actual, record["entity"]):
        raise ValueError("LINE source reference binds different geometry or attributes")
    return record


def expected_line_source_records(
    structure,
    transform,
    *,
    layer_name="TRACE_STRAIGHT",
    color=5,
    emitted_indices=None,
    page_slot=0,
    physical_page=None,
):
    """Trusted caller supplies exact exporter context; never infer it from DXF."""
    refs = make_line_source_refs(
        structure, page_slot=page_slot, physical_page=physical_page
    )
    allowed = None if emitted_indices is None else set(emitted_indices)
    presentation = structure.provenance.get("stroke_presentation", {})
    weights = presentation.get("line_records", ())
    if weights and len(weights) != len(refs):
        raise ValueError("Stroke presentation must bind every source line index")
    records = []
    for index, (line, source) in enumerate(zip(structure.straight_lines, refs)):
        if allowed is not None and index not in allowed:
            continue
        if line.length <= 1e-6:
            continue
        start = list(transform(float(line.x1), float(line.y1)))
        end = list(transform(float(line.x2), float(line.y2)))
        if hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            continue
        record = dict(
            version=VERSION,
            source=source,
            entity=dict(
                start=start + [0.0],
                end=end + [0.0],
                layer=layer_name,
                color=color if 1 <= color <= 255 else 5,
                lineweight=int(weights[index]["cad_lineweight"])
                if weights and weights[index]
                else -1,
                linetype="BYLAYER",
            ),
        )
        if source is not None:
            _encoded(record)
        else:
            _check_entity(record["entity"])
        records.append(record)
    return tuple(records)


def _key(record):
    source = record["source"]
    return source["page_slot"], source["structure_id"], source["member_index"]


def validate_line_source_refs(entities, *, expected=None):
    """Validate only the selected emitted straight-LINE collection.

    Standalone data can be rewritten consistently by an editor; it authenticates
    neither the physical source nor a design object. Snapshot verification assumes
    a trusted caller supplied the source structure, subset, and export transform.
    """
    entities = list(entities)
    records = [read_line_source_ref(entity) for entity in entities]
    known = [record for record in records if record is not None]
    keys = [_key(record) for record in known]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated LINE source member reference")
    missing = len(records) - len(known)
    if expected is not None:
        expected = tuple(expected)
        expected_known = [record for record in expected if record["source"] is not None]
        expected_unknown = [
            record["entity"] for record in expected if record["source"] is None
        ]
        for record in expected_known:
            _encoded(record)
        for record in expected_unknown:
            _check_entity(record)
        expected_map = {_key(record): record for record in expected_known}
        if len(expected_map) != len(expected_known):
            raise ValueError("Repeated expected LINE source member")
        if (
            len(records) != len(expected)
            or missing != len(expected_unknown)
            or set(keys) != set(expected_map)
        ):
            raise ValueError(
                "LINE source member collection differs from trusted snapshot"
            )
        unmatched = list(expected_unknown)
        for entity, record in zip(entities, records):
            if record is None:
                actual = entity_record(entity)
                match = next(
                    (
                        i
                        for i, item in enumerate(unmatched)
                        if _same_entity(actual, item)
                    ),
                    None,
                )
                if match is None:
                    raise ValueError(
                        "Unreferenced LINE geometry differs from trusted snapshot"
                    )
                unmatched.pop(match)
        for record in known:
            wanted = expected_map[_key(record)]
            if record["source"] != wanted["source"] or not _same_entity(
                record["entity"], wanted["entity"]
            ):
                raise ValueError("LINE source record differs from trusted snapshot")
        return dict(
            status="SNAPSHOT_VERIFIED" if known and not missing else "UNAVAILABLE",
            referenced=len(known),
            missing=missing,
        )
    return dict(
        status=("PARTIAL" if missing else "SELF_CONSISTENTONLY")
        if known
        else "UNAVAILABLE",
        referenced=len(known),
        missing=missing,
    )
