from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Protocol

from app.geometry.line_detect import LineSegment
from app.geometry.source_stroke_reconciliation import ReconciliationResult

JUNCTION_CONSUMER_SCHEMA_VERSION = 1
TRUSTED_AUTHORITY_SCHEMA_VERSION = 1
TRUSTED_AUTHORITY_MANIFEST_DIGEST = (
    "507b8bde69c46cd8f9de47c3297d7a7607ae4c18df3a31e020208ecbc4e6a6e7"
)
_TRUSTED_AUTHORITY_RESOURCE = (
    Path(__file__).resolve().parents[1] / "geometry_rules" / "junction_v2_geometry_rules_v1.json"
)
_TRUSTED_R4_REPLAY_RESOURCE = (
    Path(__file__).resolve().parents[1] / "geometry_rules" / "junction_v2_r4_saved_replay_v1.json"
)


class JunctionAction(str, Enum):
    CANONICALIZE_ENDPOINT_TO_NODE = "CANONICALIZE_ENDPOINT_TO_NODE"
    SPLIT_AT_CANONICAL_NODE = "SPLIT_AT_CANONICAL_NODE"
    SOURCE_SUPPORTED_EXTEND_TO_NODE = "SOURCE_SUPPORTED_EXTEND_TO_NODE"
    KEEP_UNCHANGED = "KEEP_UNCHANGED"
    BLOCK_AND_REVIEW = "BLOCK_AND_REVIEW"


class EndpointSelector(str, Enum):
    START = "START"
    END = "END"
    NONE = "NONE"


class JunctionConsumptionError(RuntimeError):
    """Base failure for a fail-closed bounded Junction transaction."""


class JunctionBlockedError(JunctionConsumptionError):
    """The explicit obligation could not be safely consumed."""


class JunctionAlreadyConsumedError(JunctionConsumptionError):
    """A validated Junction result cannot be consumed a second time."""


@dataclass(frozen=True)
class JunctionV2TrustedAuthority:
    """Tracked reviewed authority independent of a caller's contract payload."""

    authority_id: str
    authority_version: str
    canonical_head: str
    contract_id: str
    trusted_contract_digest: str
    node_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    required_member_count: int
    r4_member_binding_digest: str
    r4_member_identity_digest: str
    r4_transaction_binding_digest: str
    trusted_r4_replay_id: str
    trusted_r4_replay_resource_sha256: str
    page_scope_digests: tuple[str, ...]
    node_final_set_digests: tuple[str, ...]
    resource_sha256: str

    @property
    def cache_identity(self) -> dict[str, object]:
        return {
            "authority_id": self.authority_id,
            "authority_version": self.authority_version,
            "resource_sha256": self.resource_sha256,
            "trusted_contract_digest": self.trusted_contract_digest,
            "r4_transaction_binding_digest": self.r4_transaction_binding_digest,
            "r4_member_identity_digest": self.r4_member_identity_digest,
            "trusted_r4_replay_resource_sha256": (
                self.trusted_r4_replay_resource_sha256
            ),
        }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _line_payload(line: LineSegment) -> dict[str, object]:
    return {
        "start": [float(line.x1).hex(), float(line.y1).hex()],
        "end": [float(line.x2).hex(), float(line.y2).hex()],
        "width": float(line.width).hex(),
        "confidence": float(line.confidence).hex(),
        "layer": str(line.layer),
        "source_ids": list(line.source_ids),
        "history": list(line.history),
        "classification_confidence": float(line.classification_confidence).hex(),
        "classification_reasons": list(line.classification_reasons),
    }


def _lines_digest(lines: Sequence[LineSegment]) -> str:
    return _digest([_line_payload(line) for line in lines])


@dataclass(frozen=True)
class JunctionObligation:
    obligation_id: str
    node_id: str
    participant_id: str
    input_member_id: str
    action: JunctionAction
    canonical_point: tuple[float, float]
    endpoint_selector: EndpointSelector
    source_ids: tuple[str, ...]
    frozen_role: str
    source_support_to_node: str
    source_evidence_refs: tuple[str, ...]
    protection_clear: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("obligation_id", self.obligation_id),
            ("node_id", self.node_id),
            ("participant_id", self.participant_id),
            ("input_member_id", self.input_member_id),
            ("frozen_role", self.frozen_role),
        ):
            if not str(value).strip():
                raise ValueError(f"Junction {name} must not be empty")
        if len(self.canonical_point) != 2 or not all(
            isfinite(float(value)) for value in self.canonical_point
        ):
            raise ValueError("Junction canonical point must contain two finite values")
        if not self.source_ids:
            raise ValueError("Junction obligation must retain frozen source IDs")
        endpoint_actions = {
            JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
            JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE,
        }
        if self.action in endpoint_actions and self.endpoint_selector not in {
            EndpointSelector.START,
            EndpointSelector.END,
        }:
            raise ValueError("Endpoint action requires its frozen endpoint selector")
        if (
            self.action is JunctionAction.SPLIT_AT_CANONICAL_NODE
            and self.endpoint_selector is not EndpointSelector.NONE
        ):
            raise ValueError("Split action must not select an endpoint")

    def payload(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "node_id": self.node_id,
            "participant_id": self.participant_id,
            "input_member_id": self.input_member_id,
            "action": self.action.value,
            "canonical_point": [
                float(self.canonical_point[0]).hex(),
                float(self.canonical_point[1]).hex(),
            ],
            "endpoint_selector": self.endpoint_selector.value,
            "source_ids": list(self.source_ids),
            "frozen_role": self.frozen_role,
            "source_support_to_node": self.source_support_to_node,
            "source_evidence_refs": list(self.source_evidence_refs),
            "protection_clear": bool(self.protection_clear),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> JunctionObligation:
        point = payload["canonical_point"]
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)):
            raise TypeError("Junction canonical point must be an array")
        protection_clear = payload["protection_clear"]
        if type(protection_clear) is not bool:
            raise TypeError("Junction protection decision must be boolean")
        return cls(
            obligation_id=str(payload["obligation_id"]),
            node_id=str(payload["node_id"]),
            participant_id=str(payload["participant_id"]),
            input_member_id=str(payload["input_member_id"]),
            action=JunctionAction(str(payload["action"])),
            canonical_point=(float(point[0]), float(point[1])),
            endpoint_selector=EndpointSelector(str(payload["endpoint_selector"])),
            source_ids=tuple(str(value) for value in payload["source_ids"]),
            frozen_role=str(payload["frozen_role"]),
            source_support_to_node=str(payload["source_support_to_node"]),
            source_evidence_refs=tuple(
                str(value) for value in payload["source_evidence_refs"]
            ),
            protection_clear=protection_clear,
        )


@dataclass(frozen=True)
class JunctionContract:
    contract_id: str
    obligations: tuple[JunctionObligation, ...]

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("Junction contract ID must not be empty")
        obligation_ids = [item.obligation_id for item in self.obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("Junction obligation identities must be unique")
        semantic_keys = [
            (item.node_id, item.participant_id, item.action.value)
            for item in self.obligations
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("Junction semantic obligations must not be duplicated")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": JUNCTION_CONSUMER_SCHEMA_VERSION,
            "contract_id": self.contract_id,
            "obligations": [item.payload() for item in self.obligations],
        }

    @property
    def digest(self) -> str:
        return _digest(self.payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> JunctionContract:
        if int(payload.get("schema_version", 0)) != JUNCTION_CONSUMER_SCHEMA_VERSION:
            raise ValueError("Unsupported Junction consumer contract schema")
        raw = payload["obligations"]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise TypeError("Junction obligations must be an array")
        if not all(isinstance(item, Mapping) for item in raw):
            raise TypeError("Every Junction obligation must be an object")
        return cls(
            contract_id=str(payload["contract_id"]),
            obligations=tuple(JunctionObligation.from_payload(item) for item in raw),
        )


@lru_cache(maxsize=1)
def load_junction_v2_trusted_authority() -> JunctionV2TrustedAuthority:
    """Load the sole tracked authority registry entry for bounded Junction V2."""

    payload = json.loads(_TRUSTED_AUTHORITY_RESOURCE.read_text(encoding="utf-8"))
    resource_sha256 = _digest(payload)
    if resource_sha256 != TRUSTED_AUTHORITY_MANIFEST_DIGEST:
        raise JunctionBlockedError("Tracked Junction authority resource integrity failed")
    if int(payload.get("schema_version", 0)) != TRUSTED_AUTHORITY_SCHEMA_VERSION:
        raise JunctionBlockedError("Unsupported trusted Junction authority schema")
    if payload.get("authority_kind") != "BOUNDED_REVIEWED_JUNCTION_V2":
        raise JunctionBlockedError("Unrecognized Junction authority kind")
    nodes = tuple(str(value) for value in payload["node_ids"])
    obligations = tuple(str(value) for value in payload["obligation_ids"])
    page_scopes = tuple(
        str(item["source_scope_digest"]) for item in payload["page_scopes"]
    )
    node_final_sets = tuple(
        str(item["final_set_digest"]) for item in payload["r4_node_transactions"]
    )
    if len(nodes) != int(payload["required_node_count"]) or len(set(nodes)) != len(
        nodes
    ):
        raise JunctionBlockedError("Trusted Junction node registry is incomplete")
    if len(obligations) != int(payload["required_obligation_count"]) or len(
        set(obligations)
    ) != len(obligations):
        raise JunctionBlockedError("Trusted Junction obligation registry is incomplete")
    authority = JunctionV2TrustedAuthority(
        authority_id=str(payload["authority_id"]),
        authority_version=str(payload["authority_version"]),
        canonical_head=str(payload["canonical_head"]),
        contract_id=str(payload["contract_id"]),
        trusted_contract_digest=str(payload["trusted_contract_digest"]),
        node_ids=nodes,
        obligation_ids=obligations,
        required_member_count=int(payload["required_member_count"]),
        r4_member_binding_digest=str(payload["r4_member_binding_digest"]),
        r4_member_identity_digest=str(payload["r4_member_identity_digest"]),
        r4_transaction_binding_digest=str(
            payload["r4_transaction_binding_digest"]
        ),
        trusted_r4_replay_id=str(payload["trusted_r4_replay_id"]),
        trusted_r4_replay_resource_sha256=str(
            payload["trusted_r4_replay_resource_sha256"]
        ),
        page_scope_digests=page_scopes,
        node_final_set_digests=node_final_sets,
        resource_sha256=resource_sha256,
    )
    expected_transaction_binding = _digest(
        {
            "canonical_head": authority.canonical_head,
            "r4_member_binding_digest": authority.r4_member_binding_digest,
            "source_scope_digests": list(authority.page_scope_digests),
            "node_final_set_digests": list(authority.node_final_set_digests),
        }
    )
    if expected_transaction_binding != authority.r4_transaction_binding_digest:
        raise JunctionBlockedError("Trusted Junction R4 transaction binding changed")
    return authority


def validate_junction_contract_authority(
    contract: JunctionContract,
) -> JunctionV2TrustedAuthority:
    """Reject any caller contract not byte-semantically equal to tracked authority."""

    authority = load_junction_v2_trusted_authority()
    if contract.contract_id != authority.contract_id:
        raise JunctionBlockedError("Junction contract ID is not trusted")
    if contract.digest != authority.trusted_contract_digest:
        raise JunctionBlockedError("Junction contract digest is not trusted")
    if len(contract.obligations) != len(authority.obligation_ids):
        raise JunctionBlockedError("Junction contract obligation set is incomplete")
    obligation_ids = tuple(item.obligation_id for item in contract.obligations)
    if obligation_ids != authority.obligation_ids:
        raise JunctionBlockedError("Junction contract obligation identity/order changed")
    node_ids = tuple(dict.fromkeys(item.node_id for item in contract.obligations))
    if node_ids != authority.node_ids:
        raise JunctionBlockedError("Junction contract node set changed")
    return authority


class R4LineAuthority(Protocol):
    lines: tuple[LineSegment, ...]
    final_piece_ids: tuple[str, ...]
    final_set_digest: str

    def assert_complete(
        self, actual_final_lines: Sequence[LineSegment] | None = None
    ) -> None: ...


_BOUNDED_R4_AUTHORITY_SEAL = object()
_BOUNDED_R4_PROVENANCE: dict[
    object,
    tuple[
        tuple[LineSegment, ...],
        tuple[str, ...],
        str,
        tuple[str, ...],
        str,
        str,
    ],
] = {}


@dataclass(frozen=True)
class BoundedR4JunctionAuthority:
    """Sealed view produced only by verified replay or validated R4 results."""

    lines: tuple[LineSegment, ...]
    final_piece_ids: tuple[str, ...]
    final_set_digest: str
    source_scope_digests: tuple[str, ...]
    authority_origin: str
    provenance_digest: str
    _provenance_token: object
    _seal: object

    def assert_complete(
        self, actual_final_lines: Sequence[LineSegment] | None = None
    ) -> None:
        if self._seal is not _BOUNDED_R4_AUTHORITY_SEAL:
            raise JunctionBlockedError("Bounded R4 Junction authority seal changed")
        registered = _BOUNDED_R4_PROVENANCE.get(self._provenance_token)
        if registered is None or registered != (
            self.lines,
            self.final_piece_ids,
            self.final_set_digest,
            self.source_scope_digests,
            self.authority_origin,
            self.provenance_digest,
        ):
            raise JunctionBlockedError("Bounded R4 provenance registration changed")
        if registered[0] is not self.lines or registered[1] is not self.final_piece_ids:
            raise JunctionBlockedError("Bounded R4 tuple provenance changed")
        if type(self.lines) is not tuple or type(self.final_piece_ids) is not tuple:
            raise JunctionBlockedError("Bounded R4 Junction tuples changed")
        if len(self.lines) != len(self.final_piece_ids):
            raise JunctionBlockedError("Bounded R4 member identities are incomplete")
        if self.final_set_digest != _lines_digest(self.lines):
            raise JunctionBlockedError("Bounded R4 final-set identity is stale or changed")
        authority = load_junction_v2_trusted_authority()
        if self.authority_origin == "VERIFIED_SAVED_REPLAY":
            if self.provenance_digest != authority.trusted_r4_replay_resource_sha256:
                raise JunctionBlockedError("Saved R4 replay provenance changed")
        elif self.authority_origin != "VALIDATED_R4_RESULTS":
            raise JunctionBlockedError("Bounded R4 authority origin is not trusted")
        if actual_final_lines is not None and actual_final_lines is not self.lines:
            raise JunctionBlockedError("Bounded R4 line tuple was substituted")


def _line_from_replay_payload(payload: Mapping[str, object]) -> LineSegment:
    return LineSegment(
        x1=float.fromhex(str(payload["x1"])),
        y1=float.fromhex(str(payload["y1"])),
        x2=float.fromhex(str(payload["x2"])),
        y2=float.fromhex(str(payload["y2"])),
        width=float.fromhex(str(payload["width"])),
        confidence=float.fromhex(str(payload["confidence"])),
        layer=str(payload["layer"]),
        source_ids=tuple(str(value) for value in payload["source_ids"]),
        history=tuple(str(value) for value in payload["history"]),
        classification_confidence=float.fromhex(
            str(payload["classification_confidence"])
        ),
        classification_reasons=tuple(
            str(value) for value in payload["classification_reasons"]
        ),
    )


def _r4_member_identity_payload(
    source: R4LineAuthority,
    contract: JunctionContract,
) -> list[dict[str, object]]:
    by_member = dict(zip(source.final_piece_ids, source.lines, strict=True))
    member_ids = tuple(
        dict.fromkeys(item.input_member_id for item in contract.obligations)
    )
    payload: list[dict[str, object]] = []
    for member_id in member_ids:
        line = by_member.get(member_id)
        if line is None:
            raise JunctionBlockedError(f"Trusted R4 member is absent: {member_id}")
        payload.append({"member_id": member_id, "line": _line_payload(line)})
    return payload


@lru_cache(maxsize=1)
def load_verified_junction_v2_r4_replay() -> BoundedR4JunctionAuthority:
    """Load the fixed hash-pinned R4 replay derived from reviewed saved evidence."""

    authority = load_junction_v2_trusted_authority()
    payload = json.loads(_TRUSTED_R4_REPLAY_RESOURCE.read_text(encoding="utf-8"))
    resource_sha256 = _digest(payload)
    if resource_sha256 != authority.trusted_r4_replay_resource_sha256:
        raise JunctionBlockedError("Tracked saved R4 replay integrity failed")
    if int(payload.get("schema_version", 0)) != 1:
        raise JunctionBlockedError("Unsupported saved R4 replay schema")
    if payload.get("replay_id") != authority.trusted_r4_replay_id:
        raise JunctionBlockedError("Saved R4 replay identity changed")
    if payload.get("canonical_head") != authority.canonical_head:
        raise JunctionBlockedError("Saved R4 replay canonical binding changed")
    page_scopes = tuple(
        str(item["source_scope_digest"]) for item in payload["page_scopes"]
    )
    if page_scopes != authority.page_scope_digests:
        raise JunctionBlockedError("Saved R4 replay source/page scope changed")
    node_final_sets = tuple(
        str(item["final_set_digest"]) for item in payload["r4_node_transactions"]
    )
    if node_final_sets != authority.node_final_set_digests:
        raise JunctionBlockedError("Saved R4 replay transaction set changed")
    members = payload["members"]
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
        raise JunctionBlockedError("Saved R4 replay member set is malformed")
    final_piece_ids = tuple(str(item["member_id"]) for item in members)
    if len(final_piece_ids) != authority.required_member_count or len(
        set(final_piece_ids)
    ) != len(final_piece_ids):
        raise JunctionBlockedError("Saved R4 replay member set is incomplete")
    lines = tuple(_line_from_replay_payload(item) for item in members)
    token = object()
    result = BoundedR4JunctionAuthority(
        lines=lines,
        final_piece_ids=final_piece_ids,
        final_set_digest=_lines_digest(lines),
        source_scope_digests=page_scopes,
        authority_origin="VERIFIED_SAVED_REPLAY",
        provenance_digest=resource_sha256,
        _provenance_token=token,
        _seal=_BOUNDED_R4_AUTHORITY_SEAL,
    )
    contract_identity_payload = [
        {"member_id": member_id, "line": _line_payload(line)}
        for member_id, line in zip(final_piece_ids, lines, strict=True)
    ]
    if _digest(contract_identity_payload) != authority.r4_member_identity_digest:
        raise JunctionBlockedError("Saved R4 replay member identity changed")
    _BOUNDED_R4_PROVENANCE[token] = (
        result.lines,
        result.final_piece_ids,
        result.final_set_digest,
        result.source_scope_digests,
        result.authority_origin,
        result.provenance_digest,
    )
    result.assert_complete()
    return result


def bounded_r4_authority_from_reconciliation_results(
    results: tuple[ReconciliationResult, ...],
    contract: JunctionContract,
) -> BoundedR4JunctionAuthority:
    """Create the bounded view only from exact sealed R4 transaction results."""

    authority = validate_junction_contract_authority(contract)
    if type(results) is not tuple or not results:
        raise JunctionBlockedError("Validated R4 transaction results are required")
    for result in results:
        if type(result) is not ReconciliationResult:
            raise JunctionBlockedError("R4 transaction result was substituted")
        result.assert_complete()
    result_final_sets = tuple(result.final_set_digest for result in results)
    if result_final_sets != authority.node_final_set_digests:
        raise JunctionBlockedError("Validated R4 transaction set is not reviewed")
    scopes = tuple(
        dict.fromkeys(result._validation_context.source_scope_digest for result in results)
    )
    if scopes != authority.page_scope_digests:
        raise JunctionBlockedError("Validated R4 source/page scope is not reviewed")
    expected_member_ids = tuple(
        dict.fromkeys(item.input_member_id for item in contract.obligations)
    )
    resolved: dict[str, LineSegment] = {}
    for result in results:
        for member_id, line in zip(result.final_piece_ids, result.lines, strict=True):
            if member_id in expected_member_ids:
                previous = resolved.setdefault(member_id, line)
                if _line_payload(previous) != _line_payload(line):
                    raise JunctionBlockedError("Repeated validated R4 member changed")
    if set(resolved) != set(expected_member_ids):
        raise JunctionBlockedError("Validated R4 member set is incomplete")
    lines = tuple(resolved[member_id] for member_id in expected_member_ids)
    provenance_digest = _digest(
        {
            "ledger_digests": [result.ledger_digest for result in results],
            "final_set_digests": list(result_final_sets),
            "source_scope_digests": list(scopes),
        }
    )
    token = object()
    bounded = BoundedR4JunctionAuthority(
        lines=lines,
        final_piece_ids=expected_member_ids,
        final_set_digest=_lines_digest(lines),
        source_scope_digests=scopes,
        authority_origin="VALIDATED_R4_RESULTS",
        provenance_digest=provenance_digest,
        _provenance_token=token,
        _seal=_BOUNDED_R4_AUTHORITY_SEAL,
    )
    if _digest(_r4_member_identity_payload(bounded, contract)) != (
        authority.r4_member_identity_digest
    ):
        raise JunctionBlockedError("Validated R4 member identity changed")
    _BOUNDED_R4_PROVENANCE[token] = (
        bounded.lines,
        bounded.final_piece_ids,
        bounded.final_set_digest,
        bounded.source_scope_digests,
        bounded.authority_origin,
        bounded.provenance_digest,
    )
    bounded.assert_complete()
    return bounded


def _source_scope_digests(source: R4LineAuthority) -> tuple[str, ...]:
    explicit = getattr(source, "source_scope_digests", None)
    if explicit is not None:
        if type(explicit) is not tuple:
            raise JunctionBlockedError("Junction source scopes must be an exact tuple")
        return tuple(str(value) for value in explicit)
    context = getattr(source, "_validation_context", None)
    scope = getattr(context, "source_scope_digest", None)
    if scope is None:
        raise JunctionBlockedError("Junction source/page scope identity is absent")
    return (str(scope),)


def _r4_member_binding_payload(
    source: R4LineAuthority,
    contract: JunctionContract,
) -> list[dict[str, object]]:
    by_member = dict(zip(source.final_piece_ids, source.lines, strict=True))
    member_ids = tuple(
        dict.fromkeys(item.input_member_id for item in contract.obligations)
    )
    payload: list[dict[str, object]] = []
    for member_id in member_ids:
        line = by_member.get(member_id)
        if line is None:
            raise JunctionBlockedError(f"Trusted R4 member is absent: {member_id}")
        payload.append(
            {
                "member_id": member_id,
                "source_ids": list(line.source_ids),
                "geometry": {
                    "start": [float(line.x1).hex(), float(line.y1).hex()],
                    "end": [float(line.x2).hex(), float(line.y2).hex()],
                    "width": float(line.width).hex(),
                },
            }
        )
    return payload


def _validate_r4_authority_binding(
    source: R4LineAuthority,
    contract: JunctionContract,
    authority: JunctionV2TrustedAuthority,
) -> None:
    """Bind exact current R4 members and page scopes before any mutation."""

    if not isinstance(getattr(source, "final_set_digest", None), str):
        raise JunctionBlockedError("Sealed R4 final-set identity is absent")
    if (
        type(source) is BoundedR4JunctionAuthority
        and source.final_set_digest != _lines_digest(source.lines)
    ):
        raise JunctionBlockedError("Sealed R4 final-set identity is stale or changed")
    source_scopes = _source_scope_digests(source)
    if source_scopes != authority.page_scope_digests:
        raise JunctionBlockedError("Junction source/page scope is not trusted")
    member_payload = _r4_member_binding_payload(source, contract)
    if len(member_payload) != authority.required_member_count:
        raise JunctionBlockedError("Trusted R4 member set is incomplete")
    member_binding_digest = _digest(member_payload)
    if member_binding_digest != authority.r4_member_binding_digest:
        raise JunctionBlockedError("Current R4 transaction/member binding changed")
    expected_member_ids = tuple(
        dict.fromkeys(item.input_member_id for item in contract.obligations)
    )
    if source.final_piece_ids != expected_member_ids:
        raise JunctionBlockedError("Trusted R4 complete member set changed")
    member_identity_digest = _digest(_r4_member_identity_payload(source, contract))
    if member_identity_digest != authority.r4_member_identity_digest:
        raise JunctionBlockedError("Current R4 output-significant identity changed")
    transaction_binding = _digest(
        {
            "canonical_head": authority.canonical_head,
            "r4_member_binding_digest": member_binding_digest,
            "source_scope_digests": list(source_scopes),
            "node_final_set_digests": list(authority.node_final_set_digests),
        }
    )
    if transaction_binding != authority.r4_transaction_binding_digest:
        raise JunctionBlockedError("Current R4 transaction identity is not trusted")


@dataclass(frozen=True)
class JunctionLineageRecord:
    obligation_id: str
    node_id: str
    participant_id: str
    action: str
    canonical_point: tuple[float, float]
    input_r4_member_id: str
    input_active_member_ids: tuple[str, ...]
    output_member_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    input_geometries: tuple[tuple[float, float, float, float], ...]
    output_geometries: tuple[tuple[float, float, float, float], ...]

    def payload(self) -> dict[str, object]:
        return {
            "obligation_id": self.obligation_id,
            "node_id": self.node_id,
            "participant_id": self.participant_id,
            "action": self.action,
            "canonical_point": [
                float(self.canonical_point[0]).hex(),
                float(self.canonical_point[1]).hex(),
            ],
            "input_r4_member_id": self.input_r4_member_id,
            "input_active_member_ids": list(self.input_active_member_ids),
            "output_member_ids": list(self.output_member_ids),
            "source_ids": list(self.source_ids),
            "input_geometries": [
                [float(value).hex() for value in geometry]
                for geometry in self.input_geometries
            ],
            "output_geometries": [
                [float(value).hex() for value in geometry]
                for geometry in self.output_geometries
            ],
        }


@dataclass(frozen=True)
class JunctionConsumptionResult:
    lines: tuple[LineSegment, ...]
    final_piece_ids: tuple[str, ...]
    consumed_obligation_ids: tuple[str, ...]
    lineage: tuple[JunctionLineageRecord, ...]
    node_incidence: tuple[Mapping[str, object], ...]
    trusted_authority_id: str
    trusted_authority_version: str
    trusted_authority_resource_sha256: str
    trusted_r4_transaction_binding_digest: str
    contract_digest: str
    source_r4_final_set_digest: str
    source_r4_geometry_digest: str
    output_set_digest: str
    ledger_json: str
    ledger_digest: str
    _source_authority: R4LineAuthority

    def ledger_payload(self) -> dict[str, object]:
        return json.loads(self.ledger_json)

    def assert_complete(
        self, actual_final_lines: Sequence[LineSegment] | None = None
    ) -> None:
        self._source_authority.assert_complete()
        if type(self.lines) is not tuple or any(
            type(line) is not LineSegment for line in self.lines
        ):
            raise TypeError("Junction output must be an exact frozen LineSegment tuple")
        if actual_final_lines is not None:
            if type(actual_final_lines) is not tuple:
                raise TypeError("FinalStructure Junction input must be an exact tuple")
            if actual_final_lines is not self.lines:
                raise AssertionError(
                    "FinalStructure must consume the exact validated Junction tuple"
                )
        if len(self.lines) != len(self.final_piece_ids):
            raise AssertionError("Junction output member accounting is incomplete")
        if len(self.final_piece_ids) != len(set(self.final_piece_ids)):
            raise AssertionError("Junction output member identities are not unique")
        if len(self.consumed_obligation_ids) != len(set(self.consumed_obligation_ids)):
            raise AssertionError("A Junction obligation was consumed more than once")
        if _lines_digest(self.lines) != self.output_set_digest:
            raise AssertionError("Validated Junction output geometry changed")
        if (
            _lines_digest(self._source_authority.lines)
            != self.source_r4_geometry_digest
        ):
            raise AssertionError("Junction source R4 geometry changed")
        if (
            str(
                getattr(
                    self._source_authority,
                    "final_set_digest",
                    self.source_r4_geometry_digest,
                )
            )
            != self.source_r4_final_set_digest
        ):
            raise AssertionError("Junction source R4 accounting digest changed")
        payload = self.ledger_payload()
        if _digest(payload) != self.ledger_digest:
            raise AssertionError("Junction lineage ledger changed")
        if payload.get("contract_digest") != self.contract_digest:
            raise AssertionError("Junction contract binding changed")
        if payload.get("trusted_authority_id") != self.trusted_authority_id:
            raise AssertionError("Junction trusted authority identity changed")
        if (
            payload.get("trusted_authority_resource_sha256")
            != self.trusted_authority_resource_sha256
        ):
            raise AssertionError("Junction trusted authority resource changed")
        if (
            payload.get("trusted_r4_transaction_binding_digest")
            != self.trusted_r4_transaction_binding_digest
        ):
            raise AssertionError("Junction trusted R4 transaction binding changed")
        if payload.get("state") != "VALIDATED":
            raise AssertionError("Junction transaction is not validated")
        if not all(item.get("status") == "PASS" for item in self.node_incidence):
            raise AssertionError("Junction exact-node postcondition failed")

    def commit(self) -> tuple[LineSegment, ...]:
        self.assert_complete()
        return self.lines


@dataclass(frozen=True)
class _ActiveMember:
    member_id: str
    line: LineSegment


def _history(line: LineSegment, obligation: JunctionObligation) -> tuple[str, ...]:
    marker = f"junction_v2:{obligation.obligation_id}:{obligation.action.value}"
    return tuple(dict.fromkeys((*line.history, marker)))


def _output_id(input_id: str, obligation: JunctionObligation, suffix: str) -> str:
    identity = _digest(
        {
            "input_member_id": input_id,
            "obligation": obligation.payload(),
            "suffix": suffix,
        }
    )[:24]
    return f"{input_id}:junction-v2:{identity}:{suffix}"


def _exact_interior_split(line: LineSegment, point: tuple[float, float]) -> bool:
    x, y = point
    dx = line.x2 - line.x1
    dy = line.y2 - line.y1
    cross = (x - line.x1) * dy - (y - line.y1) * dx
    if cross != 0.0:
        return False
    dot = (x - line.x1) * dx + (y - line.y1) * dy
    squared_length = dx * dx + dy * dy
    return 0.0 < dot < squared_length


def _endpoint_equals(
    line: LineSegment, point: tuple[float, float], selector: EndpointSelector
) -> bool:
    if selector is EndpointSelector.START:
        return (line.x1, line.y1) == point
    if selector is EndpointSelector.END:
        return (line.x2, line.y2) == point
    return False


def _replace_endpoint(
    active: _ActiveMember, obligation: JunctionObligation
) -> _ActiveMember:
    x, y = obligation.canonical_point
    changes: dict[str, object] = {"history": _history(active.line, obligation)}
    if obligation.endpoint_selector is EndpointSelector.START:
        changes.update(x1=x, y1=y)
    elif obligation.endpoint_selector is EndpointSelector.END:
        changes.update(x2=x, y2=y)
    else:
        raise JunctionBlockedError(
            f"{obligation.obligation_id}: missing frozen endpoint selector"
        )
    output = active.line.copy(**changes)
    if output.length <= 0.0:
        raise JunctionBlockedError(
            f"{obligation.obligation_id}: endpoint action would create a zero-length member"
        )
    return _ActiveMember(
        member_id=_output_id(active.member_id, obligation, "member-000"),
        line=output,
    )


def _split_member(
    active: _ActiveMember, obligation: JunctionObligation
) -> tuple[_ActiveMember, _ActiveMember]:
    point = obligation.canonical_point
    if not _exact_interior_split(active.line, point):
        raise JunctionBlockedError(
            f"{obligation.obligation_id}: frozen node is not an exact interior point"
        )
    x, y = point
    history = _history(active.line, obligation)
    left = active.line.copy(x2=x, y2=y, history=history)
    right = active.line.copy(x1=x, y1=y, history=history)
    if left.length <= 0.0 or right.length <= 0.0:
        raise JunctionBlockedError(
            f"{obligation.obligation_id}: split would create an empty arm"
        )
    return (
        _ActiveMember(_output_id(active.member_id, obligation, "piece-000"), left),
        _ActiveMember(_output_id(active.member_id, obligation, "piece-001"), right),
    )


def consume_junction_contract(
    source: R4LineAuthority | JunctionConsumptionResult,
    contract: JunctionContract,
) -> JunctionConsumptionResult:
    """Apply only explicit frozen obligations to an already validated R4 tuple."""

    if isinstance(source, JunctionConsumptionResult):
        raise JunctionAlreadyConsumedError(
            "A Junction consumption result cannot be consumed again"
        )
    if type(source) not in {ReconciliationResult, BoundedR4JunctionAuthority}:
        raise TypeError("Junction source must be a validated R4 line authority")
    authority = validate_junction_contract_authority(contract)
    source.assert_complete()
    if type(source.lines) is not tuple or type(source.final_piece_ids) is not tuple:
        raise TypeError("R4 Junction input must use exact immutable tuples")
    if len(source.lines) != len(source.final_piece_ids):
        raise JunctionBlockedError("R4 member identities do not cover every input line")
    if len(source.final_piece_ids) != len(set(source.final_piece_ids)):
        raise JunctionBlockedError("R4 member identities are not unique")
    _validate_r4_authority_binding(source, contract, authority)

    source_order = tuple(source.final_piece_ids)
    active: dict[str, list[_ActiveMember]] = {
        member_id: [_ActiveMember(member_id, line)]
        for member_id, line in zip(source.final_piece_ids, source.lines, strict=True)
    }
    lineage: list[JunctionLineageRecord] = []
    consumed: list[str] = []

    # Validate the complete authorization set before changing the local transaction.
    for obligation in contract.obligations:
        members = active.get(obligation.input_member_id)
        if members is None:
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: remapped R4 member is absent"
            )
        if any(member.line.source_ids != obligation.source_ids for member in members):
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: frozen source identity differs"
            )
        if obligation.action is JunctionAction.BLOCK_AND_REVIEW:
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: frozen action requires review"
            )
        if (
            obligation.action is not JunctionAction.KEEP_UNCHANGED
            and not obligation.protection_clear
        ):
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: protection veto is not clear"
            )
        if obligation.action is JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE and (
            obligation.source_support_to_node != "YES_SAVED_RASTER_CONTINUOUS"
            or not obligation.source_evidence_refs
        ):
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: frozen source-support authority is absent"
            )

    for obligation in contract.obligations:
        members = active[obligation.input_member_id]
        before_ids = tuple(item.member_id for item in members)
        if obligation.action is JunctionAction.KEEP_UNCHANGED:
            updated = members
        elif obligation.action in {
            JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
            JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE,
        }:
            if len(members) != 1:
                raise JunctionBlockedError(
                    f"{obligation.obligation_id}: endpoint action requires one active member"
                )
            updated = [_replace_endpoint(members[0], obligation)]
        elif obligation.action is JunctionAction.SPLIT_AT_CANONICAL_NODE:
            if len(members) != 1:
                raise JunctionBlockedError(
                    f"{obligation.obligation_id}: split requires one active member"
                )
            updated = list(_split_member(members[0], obligation))
        else:
            raise JunctionBlockedError(
                f"{obligation.obligation_id}: unsupported Junction action"
            )
        active[obligation.input_member_id] = updated
        consumed.append(obligation.obligation_id)
        lineage.append(
            JunctionLineageRecord(
                obligation_id=obligation.obligation_id,
                node_id=obligation.node_id,
                participant_id=obligation.participant_id,
                action=obligation.action.value,
                canonical_point=obligation.canonical_point,
                input_r4_member_id=obligation.input_member_id,
                input_active_member_ids=before_ids,
                output_member_ids=tuple(item.member_id for item in updated),
                source_ids=obligation.source_ids,
                input_geometries=tuple(
                    (item.line.x1, item.line.y1, item.line.x2, item.line.y2)
                    for item in members
                ),
                output_geometries=tuple(
                    (item.line.x1, item.line.y1, item.line.x2, item.line.y2)
                    for item in updated
                ),
            )
        )

    output_members = tuple(
        member for source_id in source_order for member in active[source_id]
    )
    output_lines = tuple(item.line for item in output_members)
    output_ids = tuple(item.member_id for item in output_members)

    node_incidence: list[dict[str, object]] = []
    node_ids = tuple(dict.fromkeys(item.node_id for item in contract.obligations))
    for node_id in node_ids:
        obligations = tuple(
            item for item in contract.obligations if item.node_id == node_id
        )
        points = {item.canonical_point for item in obligations}
        if len(points) != 1:
            raise JunctionBlockedError(
                f"{node_id}: obligations disagree on the immutable canonical point"
            )
        point = next(iter(points))
        incident_ids: list[str] = []
        expected_arms = 0
        for obligation in obligations:
            members = active[obligation.input_member_id]
            if obligation.action is JunctionAction.SPLIT_AT_CANONICAL_NODE:
                matching = [
                    item.member_id
                    for item in members
                    if (item.line.x1, item.line.y1) == point
                    or (item.line.x2, item.line.y2) == point
                ]
                expected_arms += 2
                if len(matching) != 2:
                    raise JunctionBlockedError(
                        f"{obligation.obligation_id}: split does not produce two exact arms"
                    )
                incident_ids.extend(matching)
            elif obligation.action in {
                JunctionAction.CANONICALIZE_ENDPOINT_TO_NODE,
                JunctionAction.SOURCE_SUPPORTED_EXTEND_TO_NODE,
            }:
                expected_arms += 1
                matching = [
                    item.member_id
                    for item in members
                    if _endpoint_equals(item.line, point, obligation.endpoint_selector)
                ]
                if len(matching) != 1:
                    raise JunctionBlockedError(
                        f"{obligation.obligation_id}: designated endpoint is not exact"
                    )
                incident_ids.extend(matching)
        status = "PASS" if len(incident_ids) == expected_arms else "FAIL"
        if status != "PASS":
            raise JunctionBlockedError(f"{node_id}: exact shared-node incidence failed")
        node_incidence.append(
            {
                "node_id": node_id,
                "canonical_point": [float(point[0]).hex(), float(point[1]).hex()],
                "expected_arms": expected_arms,
                "actual_arms": len(incident_ids),
                "incident_output_member_ids": incident_ids,
                "status": status,
            }
        )

    source_geometry_digest = _lines_digest(source.lines)
    source_final_set_digest = source.final_set_digest
    output_digest = _lines_digest(output_lines)
    ledger = {
        "schema_version": JUNCTION_CONSUMER_SCHEMA_VERSION,
        "state": "VALIDATED",
        "contract_id": contract.contract_id,
        "contract_digest": contract.digest,
        "trusted_authority_id": authority.authority_id,
        "trusted_authority_version": authority.authority_version,
        "trusted_authority_resource_sha256": authority.resource_sha256,
        "trusted_r4_transaction_binding_digest": (
            authority.r4_transaction_binding_digest
        ),
        "source_r4_final_set_digest": source_final_set_digest,
        "source_r4_geometry_digest": source_geometry_digest,
        "output_set_digest": output_digest,
        "consumed_obligation_ids": consumed,
        "lineage": [item.payload() for item in lineage],
        "node_incidence": node_incidence,
        "authority_order": [
            "SOURCE_FAMILY_AUTHORIZATION",
            "PARTICIPANT_IDENTIFICATION",
            "CANONICAL_NODE",
            "BRANCH_ACTION",
            "GEOMETRIC_CONSUMER",
        ],
        "global_distance_authority": False,
        "global_snap": False,
        "participant_discovery": False,
    }
    ledger_json = _canonical_json(ledger)
    result = JunctionConsumptionResult(
        lines=output_lines,
        final_piece_ids=output_ids,
        consumed_obligation_ids=tuple(consumed),
        lineage=tuple(lineage),
        node_incidence=tuple(node_incidence),
        trusted_authority_id=authority.authority_id,
        trusted_authority_version=authority.authority_version,
        trusted_authority_resource_sha256=authority.resource_sha256,
        trusted_r4_transaction_binding_digest=(
            authority.r4_transaction_binding_digest
        ),
        contract_digest=contract.digest,
        source_r4_final_set_digest=source_final_set_digest,
        source_r4_geometry_digest=source_geometry_digest,
        output_set_digest=output_digest,
        ledger_json=ledger_json,
        ledger_digest=_digest(ledger),
        _source_authority=source,
    )
    result.assert_complete()
    return result
