"""Canonical counted-multiset identity for the V2 structure contract.

This module deliberately owns the V2 boundary while reusing the historical
entity payload normalization rules.  DXF handles, owners, insertion order,
and other runtime serialization details never participate in identity.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

import ezdxf

try:  # Package import from tests/application code.
    from .editable_text_regression_contract import (
        SOURCE_OUTLINE_LAYER,
        TEXT_LAYER,
        TEXT_SYMBOL_LAYER,
        _entity_payload,
        _normalise,
        _protected_layer,
    )
except ImportError:  # Direct ``python scripts/v2_canonical_structure.py`` use.
    from editable_text_regression_contract import (
        SOURCE_OUTLINE_LAYER,
        TEXT_LAYER,
        TEXT_SYMBOL_LAYER,
        _entity_payload,
        _normalise,
        _protected_layer,
    )


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def canonical_payload(value: Any) -> dict[str, Any]:
    """Return the V2 canonical payload for an ezdxf entity or payload mapping."""

    if hasattr(value, "dxftype"):
        payload = dict(_entity_payload(value))
    elif isinstance(value, Mapping):
        payload = dict(_normalise(value))
    else:
        raise TypeError(f"Unsupported canonical entity value: {type(value)!r}")

    entity_type = str(payload.get("type", ""))
    if entity_type == "LINE":
        start = tuple(payload.get("start", ()))
        end = tuple(payload.get("end", ()))
        if len(start) != len(end) or not start or not end:
            raise ValueError("LINE canonical payload requires two endpoints")
        if tuple(float(item) for item in start) > tuple(float(item) for item in end):
            payload["start"], payload["end"] = list(end), list(start)

    return dict(_normalise(payload))


def payload_key(payload: Mapping[str, Any]) -> str:
    return canonical_json_bytes(canonical_payload(payload)).decode("utf-8")


def payload_hash(payload: Mapping[str, Any]) -> str:
    return content_hash(canonical_payload(payload))


def is_structure_entity(entity: Any) -> bool:
    """Select the same non-text structure partition used by the V1 audit."""

    entity_type = str(entity.dxftype())
    layer = str(entity.dxf.get("layer", "0"))
    return bool(
        entity_type != "TEXT"
        and layer not in {TEXT_LAYER, SOURCE_OUTLINE_LAYER, TEXT_SYMBOL_LAYER}
        and not _protected_layer(layer)
    )


def canonical_structure_payloads(document: Any) -> list[dict[str, Any]]:
    payloads = [
        canonical_payload(entity)
        for entity in document.modelspace()
        if is_structure_entity(entity)
    ]
    return sorted(payloads, key=canonical_json_bytes)


def read_structure_payloads(path: Any) -> tuple[Any, list[dict[str, Any]]]:
    document = ezdxf.readfile(path)
    return document, canonical_structure_payloads(document)


def _identity_token(page_id: str, payload: Mapping[str, Any]) -> str:
    return content_hash({"page_id": page_id, "payload": canonical_payload(payload)})


def counted_entities(
    payloads: Iterable[Mapping[str, Any]],
    *,
    page_id: str,
    role: str,
) -> list[dict[str, Any]]:
    """Expand a canonical multiset with deterministic occurrence identities."""

    grouped: dict[str, dict[str, Any]] = {}
    for raw in payloads:
        payload = canonical_payload(raw)
        key = payload_key(payload)
        grouped.setdefault(key, {"payload": payload, "count": 0})["count"] += 1

    result: list[dict[str, Any]] = []
    for key in sorted(grouped):
        item = grouped[key]
        payload = item["payload"]
        count = int(item["count"])
        token = _identity_token(page_id, payload)[:16]
        entity_type = str(payload.get("type", ""))
        layer = str(payload.get("layer", "0"))
        for occurrence in range(1, count + 1):
            result.append(
                {
                    "canonical_entity_id": (
                        f"{role}:{token}:{occurrence:04d}"
                    ),
                    "canonical_payload": payload,
                    "canonical_payload_hash": content_hash(payload),
                    "canonical_key": key,
                    "entity_type": entity_type,
                    "layer": layer,
                    "occurrence": occurrence,
                    "multiplicity": count,
                }
            )
    return result


def multiset_counts(payloads: Iterable[Mapping[str, Any]]) -> Counter[str]:
    return Counter(payload_key(payload) for payload in payloads)


def multiset_digest(records: Iterable[Mapping[str, Any]]) -> str:
    grouped: dict[str, dict[str, Any]] = {}
    for item in records:
        payload = canonical_payload(item["canonical_payload"])
        key = payload_key(payload)
        entry = grouped.setdefault(
            key,
            {
                "canonical_payload": payload,
                "canonical_payload_hash": content_hash(payload),
                "count": 0,
            },
        )
        entry["count"] += 1
    return content_hash(sorted(grouped.values(), key=canonical_json_bytes))


def delta_entities(
    base_payloads: Iterable[Mapping[str, Any]],
    candidate_payloads: Iterable[Mapping[str, Any]],
    *,
    page_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return base records, additive candidate records, and preservation proof."""

    base_records = counted_entities(base_payloads, page_id=page_id, role="base")
    candidate_records = counted_entities(
        candidate_payloads,
        page_id=page_id,
        role="candidate",
    )
    base_counts = multiset_counts(item["canonical_payload"] for item in base_records)
    candidate_counts = multiset_counts(
        item["canonical_payload"] for item in candidate_records
    )

    missing_keys = sorted(
        key for key, count in base_counts.items() if candidate_counts[key] < count
    )
    added_keys = sorted(
        key for key, count in candidate_counts.items() if count > base_counts[key]
    )
    delta_records: list[dict[str, Any]] = []
    for key in added_keys:
        delta_records.extend(
            item
            for item in candidate_records
            if item["canonical_key"] == key
            and int(item["occurrence"]) > int(base_counts[key])
        )

    shared_count = sum(
        min(base_counts[key], candidate_counts[key])
        for key in set(base_counts) | set(candidate_counts)
    )
    proof = {
        "base_entity_count": sum(base_counts.values()),
        "candidate_entity_count": sum(candidate_counts.values()),
        "shared_preserved_count": shared_count,
        "base_missing_count": sum(
            base_counts[key] - candidate_counts[key] for key in missing_keys
        ),
        "added_delta_count": len(delta_records),
        "missing_payload_hashes": [content_hash(json.loads(key)) for key in missing_keys],
        "base_multiset_hash": multiset_digest(base_records),
        "candidate_multiset_hash": multiset_digest(candidate_records),
        "delta_multiset_hash": multiset_digest(delta_records),
        "proof_passed": not missing_keys,
    }
    return base_records, delta_records, proof


def validate_structure_relation(
    base_payloads: Iterable[Mapping[str, Any]],
    candidate_payloads: Iterable[Mapping[str, Any]],
    *,
    page_id: str,
    approved_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Independently compute and authorize a candidate-minus-base delta."""

    base_records, delta_records, proof = delta_entities(
        base_payloads,
        candidate_payloads,
        page_id=page_id,
    )
    expected = {
        str(item["canonical_entity_id"]): item for item in delta_records
    }
    approved = list(approved_records)
    approved_ids = [str(item.get("canonical_entity_id", "")) for item in approved]
    approved_id_set = set(approved_ids)
    computed_id_set = set(expected)
    errors: list[str] = []
    if not proof["proof_passed"]:
        errors.append("base structure is not preserved as an exact counted multiset")
    if len(approved_ids) != len(approved_id_set):
        errors.append("restoration manifest contains duplicate canonical entity IDs")
    if computed_id_set != approved_id_set:
        errors.append(
            "restoration manifest does not equal candidate-minus-base delta: "
            f"missing={sorted(computed_id_set - approved_id_set)}, "
            f"unapproved={sorted(approved_id_set - computed_id_set)}"
        )
    return {
        "base_records": base_records,
        "delta_records": delta_records,
        "proof": proof,
        "expected_delta": expected,
        "approved_ids": approved_ids,
        "computed_ids": sorted(computed_id_set),
        "missing_approved_count": len(computed_id_set - approved_id_set),
        "unapproved_count": len(approved_id_set - computed_id_set),
        "duplicate_manifest_id_count": len(approved_ids) - len(approved_id_set),
        "errors": errors,
        "passed": not errors,
    }


def stable_record_digest(records: Iterable[Mapping[str, Any]]) -> str:
    """Hash only deterministic per-entity authorization material."""

    stable = []
    for record in records:
        stable.append(
            {
                "canonical_entity_id": record["canonical_entity_id"],
                "canonical_payload_hash": record["canonical_payload_hash"],
                "canonical_entity": canonical_payload(record["canonical_entity"]),
                "source_geometry": _normalise(record["source_geometry"]),
                "world_geometry": _normalise(record["world_geometry"]),
                "evidence_hash": record["evidence_hash"],
            }
        )
    return content_hash(sorted(stable, key=canonical_json_bytes))
