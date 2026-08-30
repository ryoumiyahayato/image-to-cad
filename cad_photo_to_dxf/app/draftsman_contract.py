"""Immutable, versioned contracts for the Draftsman shadow model.

These records are deliberately independent of the production processing and
DXF models.  M0-S1 callers may project a current ``FinalStructure`` into this
model, but production code must not consume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Mapping, Sequence


DRAFTSMAN_CONTRACT_VERSION = "draftsman-shadow-v1"
PROVENANCE_CONTRACT_VERSION = "draftsman-provenance-v1"
REVIEW_CONTRACT_VERSION = "draftsman-review-link-v1"


class EvidenceState(str, Enum):
    OBSERVED = "OBSERVED"
    RECONSTRUCTED = "RECONSTRUCTED"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


class OwnershipState(str, Enum):
    PRIMARY = "PRIMARY"
    COMPETING = "COMPETING"
    UNRESOLVED = "UNRESOLVED"
    LEGACY_UNAVAILABLE = "LEGACY_UNAVAILABLE"


class ReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    DEFERRED = "DEFERRED"


class OutputDisposition(str, Enum):
    FINAL_VISIBLE = "FINAL_VISIBLE"
    PROVISIONAL_VISIBLE = "PROVISIONAL_VISIBLE"
    REVIEW_MARKER_ONLY = "REVIEW_MARKER_ONLY"
    OMITTED = "OMITTED"


def _require_text(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_sha256(value: str, name: str) -> str:
    normalized = _require_text(value, name).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


def _normalize_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Canonical JSON does not support non-finite numbers")
        return 0.0 if value == 0.0 else value
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical JSON mapping keys must be strings")
            result[key] = _normalize_json(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize_json(item) for item in value]
        return sorted(normalized, key=canonical_json_bytes)
    raise TypeError(f"Unsupported canonical JSON value: {type(value)!r}")


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic JSON bytes without runtime serialization fields."""

    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def semantic_id(namespace: str, version: str, payload: object) -> str:
    identity = {
        "namespace": _require_text(namespace, "namespace"),
        "version": _require_text(version, "version"),
        "payload": payload,
    }
    digest = sha256(canonical_json_bytes(identity)).hexdigest()
    return f"{namespace}:{digest}"


def _sorted_ids(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_require_text(value, "identity") for value in values}))


@dataclass(frozen=True)
class SourceRegionRef:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    coordinate_space: str = "source-pixel"
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        values = (self.x_min, self.y_min, self.x_max, self.y_max)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("Source region coordinates must be finite")
        if float(self.x_max) < float(self.x_min):
            raise ValueError("Source region x_max must not precede x_min")
        if float(self.y_max) < float(self.y_min):
            raise ValueError("Source region y_max must not precede y_min")
        _require_text(self.coordinate_space, "coordinate_space")
        _require_text(self.schema_version, "schema_version")

    @classmethod
    def from_xywh(
        cls,
        bbox: Sequence[float],
        *,
        coordinate_space: str = "source-pixel",
    ) -> SourceRegionRef:
        if len(bbox) != 4:
            raise ValueError("Source bbox must contain x, y, width and height")
        x, y, width, height = (float(value) for value in bbox)
        if width < 0.0 or height < 0.0:
            raise ValueError("Source bbox width and height must not be negative")
        return cls(x, y, x + width, y + height, coordinate_space)

    def identity_payload(self) -> dict[str, object]:
        return {
            "coordinate_space": self.coordinate_space,
            "bounds": [self.x_min, self.y_min, self.x_max, self.y_max],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class SourcePageRef:
    source_document_id: str
    source_page: int
    source_sha256: str
    source_size_px: tuple[int, int]
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.source_document_id, "source_document_id")
        if int(self.source_page) <= 0:
            raise ValueError("source_page must be positive")
        _require_sha256(self.source_sha256, "source_sha256")
        if len(self.source_size_px) != 2 or any(
            int(value) <= 0 for value in self.source_size_px
        ):
            raise ValueError("source_size_px must contain two positive integers")
        _require_text(self.schema_version, "schema_version")

    @property
    def source_page_id(self) -> str:
        return semantic_id(
            "source-page",
            self.schema_version,
            self.identity_payload(),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "source_page": int(self.source_page),
            "source_sha256": self.source_sha256.lower(),
            "source_size_px": list(self.source_size_px),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_page_id": self.source_page_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class TransformRef:
    transform_id: str
    source_space: str
    target_space: str
    transform_payload_json: str
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.transform_id, "transform_id")
        _require_text(self.source_space, "source_space")
        _require_text(self.target_space, "target_space")
        parsed = json.loads(self.transform_payload_json)
        if canonical_json(parsed) != self.transform_payload_json:
            raise ValueError("transform_payload_json must be canonical JSON")
        expected = semantic_id(
            "transform",
            self.schema_version,
            self.identity_payload(),
        )
        if self.transform_id != expected:
            raise ValueError("transform_id does not match transform semantics")

    @classmethod
    def create(
        cls,
        *,
        source_space: str,
        target_space: str,
        transform_payload: object,
        schema_version: str = DRAFTSMAN_CONTRACT_VERSION,
    ) -> TransformRef:
        payload_json = canonical_json(transform_payload)
        identity = {
            "source_space": source_space,
            "target_space": target_space,
            "transform_payload": json.loads(payload_json),
        }
        return cls(
            transform_id=semantic_id("transform", schema_version, identity),
            source_space=source_space,
            target_space=target_space,
            transform_payload_json=payload_json,
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_space": self.source_space,
            "target_space": self.target_space,
            "transform_payload": json.loads(self.transform_payload_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "transform_id": self.transform_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class CandidateRef:
    candidate_id: str
    candidate_kind: str
    source_region: SourceRegionRef
    evidence_json: str
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.candidate_kind, "candidate_kind")
        parsed = json.loads(self.evidence_json)
        if canonical_json(parsed) != self.evidence_json:
            raise ValueError("evidence_json must be canonical JSON")

    @classmethod
    def create(
        cls,
        *,
        source_page: SourcePageRef,
        candidate_kind: str,
        source_region: SourceRegionRef,
        evidence: object,
    ) -> CandidateRef:
        evidence_json = canonical_json(evidence)
        identity = {
            "source_page_id": source_page.source_page_id,
            "candidate_kind": candidate_kind,
            "source_region": source_region.identity_payload(),
            "evidence": json.loads(evidence_json),
        }
        return cls(
            candidate_id=semantic_id(
                "source-candidate",
                DRAFTSMAN_CONTRACT_VERSION,
                identity,
            ),
            candidate_kind=candidate_kind,
            source_region=source_region,
            evidence_json=evidence_json,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "source_region": self.source_region.to_dict(),
            "evidence": json.loads(self.evidence_json),
        }


@dataclass(frozen=True)
class ExternalEvidenceRef:
    evidence_kind: str
    evidence_id: str
    evidence_hash: str
    evidence_json: str

    def __post_init__(self) -> None:
        _require_text(self.evidence_kind, "evidence_kind")
        _require_text(self.evidence_id, "evidence_id")
        _require_sha256(self.evidence_hash, "evidence_hash")
        parsed = json.loads(self.evidence_json)
        if canonical_json(parsed) != self.evidence_json:
            raise ValueError("evidence_json must be canonical JSON")

    @classmethod
    def create(
        cls,
        *,
        evidence_kind: str,
        evidence_id: str,
        evidence: object,
        evidence_hash: str | None = None,
    ) -> ExternalEvidenceRef:
        evidence_json = canonical_json(evidence)
        resolved_hash = evidence_hash or sha256(
            evidence_json.encode("utf-8")
        ).hexdigest()
        return cls(
            evidence_kind=evidence_kind,
            evidence_id=evidence_id,
            evidence_hash=resolved_hash,
            evidence_json=evidence_json,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "evidence_kind": self.evidence_kind,
            "evidence_id": self.evidence_id,
            "evidence_hash": self.evidence_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence": json.loads(self.evidence_json),
        }


@dataclass(frozen=True)
class EntityProvenance:
    provenance_id: str
    creation_method: str
    source_candidate_ids: tuple[str, ...]
    source_region: SourceRegionRef
    transform_id: str
    reconstruction_method: str | None
    reconstruction_rule: str | None
    parent_entity_ids: tuple[str, ...]
    history: tuple[str, ...]
    external_evidence: tuple[ExternalEvidenceRef, ...]
    legacy_evidence_unavailable: tuple[str, ...]
    diagnostic_metadata_json: str
    schema_version: str = PROVENANCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.provenance_id, "provenance_id")
        _require_text(self.creation_method, "creation_method")
        _require_text(self.transform_id, "transform_id")
        if self.source_candidate_ids != _sorted_ids(self.source_candidate_ids):
            raise ValueError("source_candidate_ids must be sorted and unique")
        if self.parent_entity_ids != _sorted_ids(self.parent_entity_ids):
            raise ValueError("parent_entity_ids must be sorted and unique")
        if self.reconstruction_method is None and self.reconstruction_rule is not None:
            raise ValueError("reconstruction_rule requires reconstruction_method")
        if self.reconstruction_method is not None and self.reconstruction_rule is None:
            raise ValueError("reconstruction_method requires reconstruction_rule")
        parsed = json.loads(self.diagnostic_metadata_json)
        if canonical_json(parsed) != self.diagnostic_metadata_json:
            raise ValueError("diagnostic_metadata_json must be canonical JSON")
        expected = semantic_id(
            "provenance",
            self.schema_version,
            self.identity_payload(),
        )
        if self.provenance_id != expected:
            raise ValueError("provenance_id does not match provenance semantics")

    @classmethod
    def create(
        cls,
        *,
        creation_method: str,
        source_candidate_ids: Sequence[str],
        source_region: SourceRegionRef,
        transform_id: str,
        reconstruction_method: str | None = None,
        reconstruction_rule: str | None = None,
        parent_entity_ids: Sequence[str] = (),
        history: Sequence[str] = (),
        external_evidence: Sequence[ExternalEvidenceRef] = (),
        legacy_evidence_unavailable: Sequence[str] = (),
        diagnostic_metadata: object | None = None,
        schema_version: str = PROVENANCE_CONTRACT_VERSION,
    ) -> EntityProvenance:
        candidate_ids = _sorted_ids(source_candidate_ids)
        parents = _sorted_ids(parent_entity_ids)
        external = tuple(
            sorted(
                external_evidence,
                key=lambda item: canonical_json_bytes(item.identity_payload()),
            )
        )
        unavailable = tuple(sorted(set(legacy_evidence_unavailable)))
        identity = {
            "creation_method": creation_method,
            "source_candidate_ids": list(candidate_ids),
            "source_region": source_region.identity_payload(),
            "transform_id": transform_id,
            "reconstruction_method": reconstruction_method,
            "reconstruction_rule": reconstruction_rule,
            "parent_entity_ids": list(parents),
            "history": list(history),
            "external_evidence": [item.identity_payload() for item in external],
            "legacy_evidence_unavailable": list(unavailable),
        }
        return cls(
            provenance_id=semantic_id("provenance", schema_version, identity),
            creation_method=creation_method,
            source_candidate_ids=candidate_ids,
            source_region=source_region,
            transform_id=transform_id,
            reconstruction_method=reconstruction_method,
            reconstruction_rule=reconstruction_rule,
            parent_entity_ids=parents,
            history=tuple(history),
            external_evidence=external,
            legacy_evidence_unavailable=unavailable,
            diagnostic_metadata_json=canonical_json(diagnostic_metadata or {}),
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "creation_method": self.creation_method,
            "source_candidate_ids": list(self.source_candidate_ids),
            "source_region": self.source_region.identity_payload(),
            "transform_id": self.transform_id,
            "reconstruction_method": self.reconstruction_method,
            "reconstruction_rule": self.reconstruction_rule,
            "parent_entity_ids": list(self.parent_entity_ids),
            "history": list(self.history),
            "external_evidence": [
                item.identity_payload() for item in self.external_evidence
            ],
            "legacy_evidence_unavailable": list(
                self.legacy_evidence_unavailable
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provenance_id": self.provenance_id,
            **self.identity_payload(),
            "source_region": self.source_region.to_dict(),
            "external_evidence": [
                item.to_dict() for item in self.external_evidence
            ],
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


def stable_review_item_id(
    *,
    source_page: SourcePageRef,
    source_region: SourceRegionRef,
    review_reason: str,
    candidate_ids: Sequence[str] = (),
    candidate_identity: object | None = None,
) -> str:
    return semantic_id(
        "review-item",
        REVIEW_CONTRACT_VERSION,
        {
            "source_page_id": source_page.source_page_id,
            "source_region": source_region.identity_payload(),
            "review_reason": _require_text(review_reason, "review_reason"),
            "candidate_ids": list(_sorted_ids(candidate_ids)),
            "candidate_identity": candidate_identity,
        },
    )


@dataclass(frozen=True)
class FinalEntityRecord:
    stable_entity_id: str
    source_page_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    source_candidate_ids: tuple[str, ...]
    transform_id: str
    entity_kind: str
    state: EvidenceState
    provenance: EntityProvenance
    confidence: float
    ownership_state: OwnershipState
    review_state: ReviewStatus
    review_required: bool
    review_reason: str | None
    review_item_id: str | None
    output_disposition: OutputDisposition
    entity_payload_json: str
    occurrence: int = 1
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.stable_entity_id, "stable_entity_id")
        _require_text(self.source_page_id, "source_page_id")
        _require_text(self.source_document_id, "source_document_id")
        if int(self.source_page) <= 0:
            raise ValueError("source_page must be positive")
        if self.source_candidate_ids != _sorted_ids(self.source_candidate_ids):
            raise ValueError("source_candidate_ids must be sorted and unique")
        _require_text(self.transform_id, "transform_id")
        _require_text(self.entity_kind, "entity_kind")
        if not isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be finite and between zero and one")
        if int(self.occurrence) <= 0:
            raise ValueError("occurrence must be positive")
        parsed = json.loads(self.entity_payload_json)
        if canonical_json(parsed) != self.entity_payload_json:
            raise ValueError("entity_payload_json must be canonical JSON")
        if self.source_candidate_ids != self.provenance.source_candidate_ids:
            raise ValueError("Entity and provenance source candidates must match")
        if self.source_region != self.provenance.source_region:
            raise ValueError("Entity and provenance source regions must match")
        if self.transform_id != self.provenance.transform_id:
            raise ValueError("Entity and provenance transform IDs must match")
        uncertain = self.state in {
            EvidenceState.PROVISIONAL,
            EvidenceState.UNRESOLVED,
        }
        if uncertain and not self.review_required:
            raise ValueError("PROVISIONAL and UNRESOLVED entities require review")
        if self.review_required:
            _require_text(self.review_reason or "", "review_reason")
            _require_text(self.review_item_id or "", "review_item_id")
            if self.review_state is ReviewStatus.NOT_REQUIRED:
                raise ValueError("Required review cannot have NOT_REQUIRED status")
        elif self.review_reason is not None or self.review_item_id is not None:
            raise ValueError("Non-review entity cannot carry review linkage")
        expected = semantic_id(
            "draftsman-entity",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_entity_id != expected:
            raise ValueError("stable_entity_id does not match entity semantics")

    @classmethod
    def create(
        cls,
        *,
        source_page: SourcePageRef,
        source_region: SourceRegionRef,
        source_candidate_ids: Sequence[str],
        transform_id: str,
        entity_kind: str,
        state: EvidenceState,
        provenance: EntityProvenance,
        confidence: float,
        ownership_state: OwnershipState,
        entity_payload: object,
        review_state: ReviewStatus = ReviewStatus.NOT_REQUIRED,
        review_required: bool = False,
        review_reason: str | None = None,
        review_item_id: str | None = None,
        output_disposition: OutputDisposition = OutputDisposition.FINAL_VISIBLE,
        occurrence: int = 1,
        schema_version: str = DRAFTSMAN_CONTRACT_VERSION,
    ) -> FinalEntityRecord:
        candidate_ids = _sorted_ids(source_candidate_ids)
        payload_json = canonical_json(entity_payload)
        identity = {
            "source_page_id": source_page.source_page_id,
            "source_region": source_region.identity_payload(),
            "source_candidate_ids": list(candidate_ids),
            "transform_id": transform_id,
            "entity_kind": entity_kind,
            "state": state.value,
            "provenance_id": provenance.provenance_id,
            "ownership_state": ownership_state.value,
            "entity_payload": json.loads(payload_json),
            "occurrence": int(occurrence),
        }
        return cls(
            stable_entity_id=semantic_id(
                "draftsman-entity",
                schema_version,
                identity,
            ),
            source_page_id=source_page.source_page_id,
            source_document_id=source_page.source_document_id,
            source_page=source_page.source_page,
            source_region=source_region,
            source_candidate_ids=candidate_ids,
            transform_id=transform_id,
            entity_kind=entity_kind,
            state=state,
            provenance=provenance,
            confidence=float(confidence),
            ownership_state=ownership_state,
            review_state=review_state,
            review_required=bool(review_required),
            review_reason=review_reason,
            review_item_id=review_item_id,
            output_disposition=output_disposition,
            entity_payload_json=payload_json,
            occurrence=int(occurrence),
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page_id,
            "source_region": self.source_region.identity_payload(),
            "source_candidate_ids": list(self.source_candidate_ids),
            "transform_id": self.transform_id,
            "entity_kind": self.entity_kind,
            "state": self.state.value,
            "provenance_id": self.provenance.provenance_id,
            "ownership_state": self.ownership_state.value,
            "entity_payload": json.loads(self.entity_payload_json),
            "occurrence": int(self.occurrence),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_entity_id": self.stable_entity_id,
            "source_page_id": self.source_page_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_region": self.source_region.to_dict(),
            "source_candidate_ids": list(self.source_candidate_ids),
            "transform_id": self.transform_id,
            "entity_kind": self.entity_kind,
            "state": self.state.value,
            "provenance": self.provenance.to_dict(),
            "confidence": self.confidence,
            "ownership_state": self.ownership_state.value,
            "review_state": self.review_state.value,
            "review_required": self.review_required,
            "review_reason": self.review_reason,
            "review_item_id": self.review_item_id,
            "output_disposition": self.output_disposition.value,
            "entity_payload": json.loads(self.entity_payload_json),
            "occurrence": self.occurrence,
        }


@dataclass(frozen=True)
class ReviewItem:
    review_item_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    review_reason: str
    candidate_entity_ids: tuple[str, ...]
    alternative_candidate_ids: tuple[str, ...]
    suggested_action: str
    review_state: ReviewStatus = ReviewStatus.PENDING
    schema_version: str = REVIEW_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.review_item_id, "review_item_id")
        _require_text(self.source_document_id, "source_document_id")
        if self.source_page <= 0:
            raise ValueError("source_page must be positive")
        _require_text(self.review_reason, "review_reason")
        _require_text(self.suggested_action, "suggested_action")
        if self.candidate_entity_ids != _sorted_ids(self.candidate_entity_ids):
            raise ValueError("candidate_entity_ids must be sorted and unique")
        if self.alternative_candidate_ids != _sorted_ids(
            self.alternative_candidate_ids
        ):
            raise ValueError("alternative_candidate_ids must be sorted and unique")
        if self.review_state is ReviewStatus.NOT_REQUIRED:
            raise ValueError("Review items cannot have NOT_REQUIRED status")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "review_item_id": self.review_item_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_region": self.source_region.to_dict(),
            "review_reason": self.review_reason,
            "candidate_entity_ids": list(self.candidate_entity_ids),
            "alternative_candidate_ids": list(self.alternative_candidate_ids),
            "suggested_action": self.suggested_action,
            "review_state": self.review_state.value,
        }


@dataclass(frozen=True)
class DraftsmanPageSnapshot:
    source_page: SourcePageRef
    transform: TransformRef
    final_structure_id: str
    entities: tuple[FinalEntityRecord, ...]
    review_items: tuple[ReviewItem, ...] = ()
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.final_structure_id, "final_structure_id")
        if len({item.stable_entity_id for item in self.entities}) != len(
            self.entities
        ):
            raise ValueError("Draftsman entity IDs must be unique")
        known_reviews = {item.review_item_id for item in self.review_items}
        linked_reviews = {
            item.review_item_id
            for item in self.entities
            if item.review_item_id is not None
        }
        missing = linked_reviews.difference(known_reviews)
        if missing:
            raise ValueError(
                "Every entity review link must reference a snapshot review item: "
                f"{sorted(missing)}"
            )

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-shadow-manifest",
            self.schema_version,
            self.identity_payload(),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page": self.source_page.to_dict(),
            "transform": self.transform.to_dict(),
            "final_structure_id": self.final_structure_id,
            "entity_ids": sorted(item.stable_entity_id for item in self.entities),
            "review_item_ids": sorted(
                item.review_item_id for item in self.review_items
            ),
        }

    def to_dict(self) -> dict[str, object]:
        entities = sorted(self.entities, key=lambda item: item.stable_entity_id)
        reviews = sorted(self.review_items, key=lambda item: item.review_item_id)
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_page": self.source_page.to_dict(),
            "transform": self.transform.to_dict(),
            "final_structure_id": self.final_structure_id,
            "entities": [item.to_dict() for item in entities],
            "review_items": [item.to_dict() for item in reviews],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())
