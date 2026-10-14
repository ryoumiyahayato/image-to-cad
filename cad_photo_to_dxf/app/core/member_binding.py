from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from types import MappingProxyType

import numpy as np

from app.core.structure import FinalStructure, metadata_to_jsonable


DRAFTSMAN_OUTPUT_NAMESPACE = "draftsman_output_v1"
WHOLE_OBJECT_SCHEMA_VERSION = "whole-object-ownership-v2"
FINAL_MEMBER_BINDING_SCHEMA_VERSION = "object-final-member-binding-v1"
SHARED_RESOLVER_ID = "SHARED_FS3_MEMBER_RESOLVER_V1"
SHARED_RESOLVER_VERSION = "1"
SUPPORTED_CONSUMER_POLICY = "fs3-shared-consumer-v1"
SUPPORTED_EMIT_MODES = {"EMIT_SELF", "EMIT_WITH_ROOT", "ALIAS_NO_EMIT"}
CANONICAL_COLLECTION_ORDER = (
    "contours",
    "straight_lines",
    "texts",
    "logos",
    "signatures",
    "source_text_outline_mask",
    "uncertain_text_outline_mask",
)
SUPPORTED_COLLECTIONS = frozenset(CANONICAL_COLLECTION_ORDER)
REPRESENTATION_POLICY_ID = "draftsman-representation-policy-v1"
REPRESENTATION_POLICY_DIGEST = "ca4c2ffa86c14a1e09810d32b574f2e9275f968aeb3a2515272e6b658b6834a4"
CONSUMER_POLICY_TOKEN = {
    "id": "shared-fs3-member-resolver",
    "version": SHARED_RESOLVER_VERSION,
    "digest": "7" * 64,
}


class DraftsmanBindingError(ValueError):
    """A committed B/F2 output is incomplete, stale, or unsupported."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _exact_float(value: float) -> str:
    number = float(value)
    if not isfinite(number):
        raise DraftsmanBindingError("Member geometry must be finite")
    if number == 0.0:
        number = 0.0
    return number.hex()


def _mask_payload(mask: np.ndarray) -> dict[str, object]:
    normalized = np.ascontiguousarray(mask, dtype=np.uint8)
    return {
        "shape": [int(value) for value in normalized.shape],
        "dtype": str(normalized.dtype),
        "sha256": sha256(normalized.tobytes()).hexdigest(),
    }


def _collection_size(structure: FinalStructure, collection: str) -> int:
    if collection in {"source_text_outline_mask", "uncertain_text_outline_mask"}:
        mask = getattr(structure, collection)
        if mask is None:
            return 0
        from app.geometry.raster_trace import trace_binary

        return len(trace_binary(np.where(mask > 0, 0, 255).astype(np.uint8)))
    return len(getattr(structure, collection))


def terminal_member_payload(
    structure: FinalStructure,
    collection: str,
    index: int,
) -> dict[str, object]:
    """Return the exact, collection-ordered FS3 member payload."""

    if collection not in SUPPORTED_COLLECTIONS:
        raise DraftsmanBindingError(f"Unsupported member collection: {collection}")
    if collection in {"source_text_outline_mask", "uncertain_text_outline_mask"}:
        mask = getattr(structure, collection)
        if mask is None:
            raise DraftsmanBindingError(f"Semantic mask collection is absent: {collection}")
        from app.geometry.raster_trace import trace_binary

        values = trace_binary(np.where(mask > 0, 0, 255).astype(np.uint8))
    else:
        values = getattr(structure, collection)
    if index < 0 or index >= len(values):
        raise DraftsmanBindingError(
            f"Member locator is outside {collection}: {index}"
        )
    item = values[index]
    if collection in {"contours", "source_text_outline_mask", "uncertain_text_outline_mask"}:
        return {
            "collection": collection,
            "index": index,
            "points": [[_exact_float(x), _exact_float(y)] for x, y in item.points],
            "parent": item.parent,
            "depth": int(item.depth),
            "root": int(item.root),
        }
    if collection == "straight_lines":
        return {
            "collection": collection,
            "index": index,
            "start": [_exact_float(item.x1), _exact_float(item.y1)],
            "end": [_exact_float(item.x2), _exact_float(item.y2)],
            "width": _exact_float(item.width),
            "layer": str(item.layer),
            "confidence": _exact_float(item.confidence),
            "source_ids": list(item.source_ids),
            "history": list(item.history),
            "classification_confidence": _exact_float(item.classification_confidence),
            "classification_reasons": list(item.classification_reasons),
        }
    if collection == "texts":
        return {
            "collection": collection,
            "index": index,
            "text": str(item.text),
            "bbox": [int(value) for value in item.bbox],
            "quad": (
                None
                if item.quad is None
                else [[_exact_float(x), _exact_float(y)] for x, y in item.quad]
            ),
            "confidence": _exact_float(item.confidence),
            "kind": str(item.kind),
            "source": str(item.source),
            "approved": bool(item.approved),
            "reviewed": bool(item.reviewed),
            "font_family": str(item.font_family),
            "font_file": str(item.font_file),
            "font_match_score": _exact_float(item.font_match_score),
            "rotation": _exact_float(item.rotation_deg),
            "replacement_safe": bool(item.replacement_safe),
        }
    return {
        "collection": collection,
        "index": index,
        "bbox": [int(value) for value in item.bbox],
        "mask": _mask_payload(item.mask),
        **(
            {
                "structural_score": _exact_float(item.structural_score),
                "hole_count": int(item.hole_count),
                "contour_count": int(item.contour_count),
                "visual_kind": str(item.visual_kind),
                "density": _exact_float(item.density),
                "closed_complexity": int(item.closed_complexity),
                "reflection_similarity": _exact_float(item.reflection_similarity),
            }
            if collection == "logos"
            else {
                "visual_evidence": (
                    None
                    if item.visual_evidence is None
                    else item.visual_evidence.payload()
                )
            }
        ),
    }


def terminal_payload_digest(structure: FinalStructure) -> str:
    inventory: list[dict[str, object]] = []
    for collection in CANONICAL_COLLECTION_ORDER:
        for index in range(_collection_size(structure, collection)):
            inventory.append(terminal_member_payload(structure, collection, index))
    masks = {
        name: (
            None if getattr(structure, name) is None else _mask_payload(getattr(structure, name))
        )
        for name in (
            "editable_text_source_mask",
            "source_text_outline_mask",
            "uncertain_text_outline_mask",
        )
    }
    return _digest(
        {
            "source_size_px": list(structure.source_size_px),
            "contour_binary": _mask_payload(structure.contour_binary),
            "preview_binary": (
                None
                if structure.preview_binary is None
                else _mask_payload(structure.preview_binary)
            ),
            "threshold": int(structure.threshold),
            "members": inventory,
            "semantic_masks": masks,
        }
    )


















@dataclass(frozen=True)
class ResolvedMember:
    member_id: str
    collection: str
    index: int
    semantic_role: str
    effective_form: str
    emit_mode: str
    layer: str
    preview_category: str
    default_visible: bool
    protected_from_ocr: bool
    object_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedDraftsmanOutput:
    output_id: str
    behavior_digest: str
    terminal_member_digest: str
    members: tuple[ResolvedMember, ...]
    members_by_locator: Mapping[tuple[str, int], ResolvedMember]
    review_required: bool

    def emitted_indices(self, collection: str) -> tuple[int, ...]:
        return tuple(
            item.index
            for item in self.members
            if item.collection == collection and item.emit_mode != "ALIAS_NO_EMIT"
        )




def _validate_object_obligation_members(
    object_id: str,
    object_binding: Mapping[str, object],
    records_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    """Enforce the frozen per-object Final-Member boundary."""

    object_member_ids = {
        str(member_id) for member_id in object_binding.get("final_member_ids", ())
    }
    if not object_member_ids <= records_by_id.keys():
        raise DraftsmanBindingError("Object binding names a missing final member")
    if any(
        object_id not in records_by_id[member_id].get("object_ids", ())
        for member_id in object_member_ids
    ):
        raise DraftsmanBindingError("Object binding may use only its own committed members")

    closures = object_binding.get("obligation_closures", ())
    if not isinstance(closures, (list, tuple)):
        raise DraftsmanBindingError("Object obligation closures are malformed")
    for closure in closures:
        if not isinstance(closure, Mapping):
            raise DraftsmanBindingError("Object obligation closure is malformed")
        closure_member_ids = {
            str(member_id) for member_id in closure.get("final_member_ids", ())
        }
        retained_member_ids = {
            str(member_id)
            for member_id in closure.get("retained_accepted_member_ids", ())
        }
        replacement_coverage = closure.get("replacement_coverage", ())
        if not isinstance(replacement_coverage, (list, tuple)) or any(
            not isinstance(coverage, Mapping) for coverage in replacement_coverage
        ):
            raise DraftsmanBindingError("Obligation replacement coverage is malformed")
        replacement_member_ids = {
            str(coverage.get("member_id", "")) for coverage in replacement_coverage
        }
        if not (
            closure_member_ids <= object_member_ids
            and retained_member_ids <= object_member_ids
            and replacement_member_ids <= object_member_ids
        ):
            raise DraftsmanBindingError(
                "Object obligation may use only its own committed final members"
            )




def _validate_contour_forest(
    structure: FinalStructure,
    members_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    contour_members = {
        int(item["locator"]["index"]): item
        for item in members_by_id.values()
        if item["locator"]["collection"] == "contours"
    }
    for index, path in enumerate(structure.contours):
        item = contour_members[index]
        expected_role = "ROOT" if path.depth == 0 else ("HOLE" if path.depth % 2 else "ISLAND")
        if item["contour_role"] != expected_role:
            raise DraftsmanBindingError("Contour role does not match the FS3 forest")
        root = contour_members[int(path.root)]
        parent = None if path.parent is None else contour_members[int(path.parent)]
        if item["root_member_id"] != root["member_id"]:
            raise DraftsmanBindingError("Contour root member does not match TracePath.root")
        if item["parent_member_id"] != (None if parent is None else parent["member_id"]):
            raise DraftsmanBindingError("Contour parent member does not match TracePath.parent")
        if int(item["depth"]) != int(path.depth):
            raise DraftsmanBindingError("Contour depth does not match TracePath.depth")
        if expected_role == "HOLE" and item["emit_mode"] != "EMIT_WITH_ROOT":
            raise DraftsmanBindingError("Hole contours must use EMIT_WITH_ROOT")


def resolve_draftsman_output(
    structure: FinalStructure,
    *,
    required: bool = False,
) -> ResolvedDraftsmanOutput | None:
    """Validate and resolve the immutable FS3 binding without making decisions."""

    raw = structure.provenance.get(DRAFTSMAN_OUTPUT_NAMESPACE)
    if raw is None:
        if required:
            raise DraftsmanBindingError("Composite output is missing its B/F2 binding")
        return None
    namespace = metadata_to_jsonable(raw)
    if not isinstance(namespace, dict) or namespace.get("schema_version") != "draftsman-output-v1":
        raise DraftsmanBindingError("Unsupported draftsman output namespace")
    binding = namespace.get("binding")
    if not isinstance(binding, dict) or binding.get("schema_version") != FINAL_MEMBER_BINDING_SCHEMA_VERSION:
        raise DraftsmanBindingError("Unsupported object/final-member binding")
    snapshots = namespace.get("ownership_snapshots")
    if not isinstance(snapshots, dict):
        raise DraftsmanBindingError("Frozen ownership snapshots are missing")
    ownership_snapshot = binding.get("ownership_snapshot")
    if not isinstance(ownership_snapshot, dict) or ownership_snapshot.get("digest") != _digest(snapshots):
        raise DraftsmanBindingError("Frozen ownership snapshot identity is stale")
    for object_binding in binding.get("objects", ()):
        if not isinstance(object_binding, dict):
            raise DraftsmanBindingError("Object binding is malformed")
        object_id = str(object_binding.get("object_id", ""))
        snapshot = snapshots.get(object_id)
        token = object_binding.get("b_snapshot")
        if not isinstance(snapshot, dict) or not isinstance(token, dict) or token.get("digest") != _digest(snapshot):
            raise DraftsmanBindingError("Object binding does not match its exact B snapshot")
    consumer = binding.get("consumer_binding")
    if consumer != SHARED_RESOLVER_ID:
        raise DraftsmanBindingError("Unknown shared consumer policy/version")
    compiled_policy = binding.get("compiled_policy")
    if not isinstance(compiled_policy, dict) or (
        compiled_policy.get("representation_policy_id") != REPRESENTATION_POLICY_ID
        or compiled_policy.get("representation_policy_digest") != REPRESENTATION_POLICY_DIGEST
        or compiled_policy.get("consumer_policy") != CONSUMER_POLICY_TOKEN
    ):
        raise DraftsmanBindingError("Unknown behavioral consumer policy/version")
    exact_terminal = terminal_payload_digest(structure)
    if binding.get("terminal_member_digest") != exact_terminal:
        raise DraftsmanBindingError("Terminal member precision or inventory is stale")
    records = binding.get("members")
    if not isinstance(records, list):
        raise DraftsmanBindingError("Final member registry is missing")
    expected = {
        (collection, index)
        for collection in SUPPORTED_COLLECTIONS
        for index in range(_collection_size(structure, collection))
    }
    locators: set[tuple[str, int]] = set()
    by_id: dict[str, Mapping[str, object]] = {}
    resolved: list[ResolvedMember] = []
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("locator"), dict):
            raise DraftsmanBindingError("Member registry record is malformed")
        locator = item["locator"]
        collection = str(locator.get("collection"))
        index = int(locator.get("index", -1))
        key = (collection, index)
        if key in locators or key not in expected:
            raise DraftsmanBindingError("Member locator is duplicate or invalid")
        if locator.get("payload_digest") != _digest(terminal_member_payload(structure, collection, index)):
            raise DraftsmanBindingError("Member locator payload digest is stale")
        member_id = str(item.get("member_id", ""))
        if not member_id or member_id in by_id:
            raise DraftsmanBindingError("Member IDs must be complete and unique")
        policy = item.get("policy")
        if not isinstance(policy, dict):
            raise DraftsmanBindingError("Member policy is missing")
        locators.add(key)
        by_id[member_id] = item
        resolved.append(
            ResolvedMember(
                member_id=member_id,
                collection=collection,
                index=index,
                semantic_role=str(item.get("semantic_role")),
                effective_form=str(item.get("effective_form")),
                emit_mode=str(item.get("emit_mode")),
                layer=str(policy.get("layer")),
                preview_category=str(policy.get("preview_category")),
                default_visible=bool(policy.get("default_visible")),
                protected_from_ocr=(policy.get("ocr_suppression") == "EXPLICIT_OBLIGATION_REPLACEMENT_ONLY"),
                object_ids=tuple(str(value) for value in item.get("object_ids", ())),
            )
        )
    if locators != expected:
        raise DraftsmanBindingError("Final member registry is incomplete")
    objects = binding.get("objects")
    if not isinstance(objects, list):
        raise DraftsmanBindingError("Object/final-member bindings are missing")
    for object_binding in objects:
        if not isinstance(object_binding, dict):
            raise DraftsmanBindingError("Object binding is malformed")
        _validate_object_obligation_members(
            str(object_binding.get("object_id", "")),
            object_binding,
            by_id,
        )
    for item in records:
        alias = item.get("alias_of")
        if item.get("emit_mode") == "ALIAS_NO_EMIT":
            target = by_id.get(str(alias))
            if target is None or target.get("emit_mode") == "ALIAS_NO_EMIT":
                raise DraftsmanBindingError("Alias must resolve directly to one primary member")
        elif alias is not None:
            raise DraftsmanBindingError("A primary member cannot have alias_of")
    _validate_contour_forest(structure, by_id)
    behavior_payload = {
        "terminal_member_digest": exact_terminal,
        "members": records,
        "objects": binding.get("objects"),
        "suppressed_candidates": binding.get("suppressed_candidates"),
        "source_identity": binding.get("source"),
        "behavioral_policy": binding.get("compiled_policy"),
    }
    behavior_digest = _digest(behavior_payload)
    if namespace.get("behavior_digest") != behavior_digest:
        raise DraftsmanBindingError("Behavior digest is stale")
    output_id = _digest(
        {
            "terminal_product_state": exact_terminal,
            "final_member_binding": _digest(binding),
            "behavior_digest": behavior_digest,
        }
    )
    if namespace.get("output_id") != output_id:
        raise DraftsmanBindingError("Output identity is stale")
    return ResolvedDraftsmanOutput(
        output_id=output_id,
        behavior_digest=behavior_digest,
        terminal_member_digest=exact_terminal,
        members=tuple(resolved),
        members_by_locator=MappingProxyType({(item.collection, item.index): item for item in resolved}),
        review_required=bool(namespace.get("review_required")),
    )


def draftsman_cache_identity(structure: FinalStructure) -> Mapping[str, object] | None:
    resolved = resolve_draftsman_output(structure)
    if resolved is None:
        return None
    return MappingProxyType(
        {
            "resolver_id": SHARED_RESOLVER_ID,
            "resolver_version": SHARED_RESOLVER_VERSION,
            "behavior_digest": resolved.behavior_digest,
            "output_id": resolved.output_id,
            "terminal_member_digest": resolved.terminal_member_digest,
        }
    )


def cache_binding_admissible(
    structure: FinalStructure,
    expected_identity: Mapping[str, object] | None,
) -> bool:
    """Post-load gate; any stale policy, binding, or binary64 loss rejects reuse."""

    try:
        actual = draftsman_cache_identity(structure)
    except (DraftsmanBindingError, TypeError, ValueError):
        return False
    if expected_identity is None:
        return actual is None
    if actual is None:
        return False
    return dict(actual) == dict(expected_identity)


