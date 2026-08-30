"""Typed, immutable contracts for the Draftsman M1 candidate shadow layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Protocol, Sequence, TypeAlias

from .draftsman_contract import (
    DRAFTSMAN_CONTRACT_VERSION,
    SourcePageRef,
    SourceRegionRef,
    TransformRef,
    canonical_json,
    canonical_json_bytes,
    semantic_id,
)


DRAFTSMAN_CANDIDATE_VERSION = "draftsman-candidate-v1"
CANDIDATE_RELATIONSHIP_VERSION = "draftsman-candidate-relationship-v1"


class CandidateKind(str, Enum):
    LINE_SEGMENT = "LINE_SEGMENT"
    OCR_TEXT = "OCR_TEXT"
    LOGO = "LOGO"
    SIGNATURE = "SIGNATURE"
    STRUCTURAL_ROI = "STRUCTURAL_ROI"
    TABLE_REGION = "TABLE_REGION"
    CIRCLE = "CIRCLE"
    SYMBOL = "SYMBOL"


class CandidateRelationshipKind(str, Enum):
    OVERLAPS = "OVERLAPS"
    CONTAINS = "CONTAINS"
    DERIVED_FROM = "DERIVED_FROM"
    COLLINEAR_WITH = "COLLINEAR_WITH"
    BELONGS_TO_REGION = "BELONGS_TO_REGION"


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _canonical_payload_json(value: object, name: str) -> str:
    payload = canonical_json(value)
    if not payload:
        raise ValueError(f"{name} must not be empty")
    return payload


def _assert_canonical_json(value: str, name: str) -> None:
    parsed = json.loads(value)
    if canonical_json(parsed) != value:
        raise ValueError(f"{name} must be canonical JSON")


def _sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_required(value, "identity") for value in values}))


def _confidence(value: float) -> float:
    resolved = float(value)
    if not isfinite(resolved) or not 0.0 <= resolved <= 1.0:
        raise ValueError("confidence must be finite and between zero and one")
    return resolved


class CandidatePayload(Protocol):
    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class LineCandidatePayload:
    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    detector_history: tuple[str, ...]
    proposed_layer: str
    classification_confidence: float
    classification_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (*self.start, *self.end, self.width)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("Line candidate geometry must be finite")
        if float(self.width) <= 0.0:
            raise ValueError("Line candidate width must be positive")
        _required(self.proposed_layer, "proposed_layer")
        _confidence(self.classification_confidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "start": list(self.start),
            "end": list(self.end),
            "width": self.width,
            "detector_history": list(self.detector_history),
            "proposed_layer": self.proposed_layer,
            "classification_confidence": self.classification_confidence,
            "classification_reasons": list(self.classification_reasons),
        }


@dataclass(frozen=True)
class TextCandidatePayload:
    raw_recognized_text: str
    source_bbox: tuple[int, int, int, int]
    source_quad: tuple[tuple[float, float], ...] | None
    rotation_degrees: float
    orientation_evidence: str
    detector_text_kind: str
    detector_source: str
    character_boxes: tuple[tuple[int, int, int, int], ...]
    replacement_safe: bool
    review_note: str

    def __post_init__(self) -> None:
        _required(self.raw_recognized_text, "raw_recognized_text")
        if len(self.source_bbox) != 4 or self.source_bbox[2] <= 0 or self.source_bbox[3] <= 0:
            raise ValueError("OCR source_bbox must be x, y, positive width and height")
        if self.source_quad is not None:
            if len(self.source_quad) != 4 or not all(
                len(point) == 2
                and all(isfinite(float(value)) for value in point)
                for point in self.source_quad
            ):
                raise ValueError("OCR source_quad must contain four finite points")
        if not isfinite(float(self.rotation_degrees)):
            raise ValueError("OCR rotation must be finite")
        _required(self.orientation_evidence, "orientation_evidence")
        _required(self.detector_text_kind, "detector_text_kind")
        _required(self.detector_source, "detector_source")

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_recognized_text": self.raw_recognized_text,
            "source_bbox": list(self.source_bbox),
            "source_quad": (
                None
                if self.source_quad is None
                else [list(point) for point in self.source_quad]
            ),
            "rotation_degrees": self.rotation_degrees,
            "orientation_evidence": self.orientation_evidence,
            "detector_text_kind": self.detector_text_kind,
            "detector_source": self.detector_source,
            "character_boxes": [list(box) for box in self.character_boxes],
            "replacement_safe": self.replacement_safe,
            "review_note": self.review_note,
        }


@dataclass(frozen=True)
class LogoCandidatePayload:
    source_bbox: tuple[int, int, int, int]
    source_mask_sha256: str
    source_foreground_pixels: int
    visual_kind: str
    structural_score: float
    hole_count: int
    contour_count: int
    density: float
    closed_complexity: int
    reflection_similarity: float

    def __post_init__(self) -> None:
        _required(self.source_mask_sha256, "source_mask_sha256")
        _required(self.visual_kind, "visual_kind")
        _confidence(self.structural_score)
        if self.source_foreground_pixels < 0:
            raise ValueError("source_foreground_pixels must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_bbox": list(self.source_bbox),
            "source_mask_sha256": self.source_mask_sha256,
            "source_foreground_pixels": self.source_foreground_pixels,
            "visual_kind": self.visual_kind,
            "structural_score": self.structural_score,
            "hole_count": self.hole_count,
            "contour_count": self.contour_count,
            "density": self.density,
            "closed_complexity": self.closed_complexity,
            "reflection_similarity": self.reflection_similarity,
        }


@dataclass(frozen=True)
class SignatureCandidatePayload:
    source_bbox: tuple[int, int, int, int]
    source_mask_sha256: str
    source_foreground_pixels: int
    source_component_count: int
    density: float
    continuity: float
    directional_complexity: int
    positive_diagonal_span: float
    negative_diagonal_span: float
    bidirectional_diagonal_support: bool
    perimeter_per_pixel: float
    convex_solidity: float

    def __post_init__(self) -> None:
        _required(self.source_mask_sha256, "source_mask_sha256")
        if self.source_foreground_pixels < 0 or self.source_component_count < 0:
            raise ValueError("Signature source counts must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_bbox": list(self.source_bbox),
            "source_mask_sha256": self.source_mask_sha256,
            "source_foreground_pixels": self.source_foreground_pixels,
            "source_component_count": self.source_component_count,
            "density": self.density,
            "continuity": self.continuity,
            "directional_complexity": self.directional_complexity,
            "positive_diagonal_span": self.positive_diagonal_span,
            "negative_diagonal_span": self.negative_diagonal_span,
            "bidirectional_diagonal_support": self.bidirectional_diagonal_support,
            "perimeter_per_pixel": self.perimeter_per_pixel,
            "convex_solidity": self.convex_solidity,
        }


@dataclass(frozen=True)
class StructuralRoiCandidatePayload:
    purpose: str
    source_bbox: tuple[int, int, int, int]
    related_line_candidate_ids: tuple[str, ...]
    evidence_intersections: tuple[tuple[float, float], ...]
    expansion_distance: float
    source_types: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(self.purpose, "purpose")
        if self.related_line_candidate_ids != _sorted_unique(
            self.related_line_candidate_ids
        ):
            raise ValueError("related line candidate IDs must be sorted and unique")
        if not isfinite(float(self.expansion_distance)):
            raise ValueError("ROI expansion distance must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "purpose": self.purpose,
            "source_bbox": list(self.source_bbox),
            "related_line_candidate_ids": list(self.related_line_candidate_ids),
            "evidence_intersections": [
                list(point) for point in self.evidence_intersections
            ],
            "expansion_distance": self.expansion_distance,
            "source_types": list(self.source_types),
        }


@dataclass(frozen=True)
class CircleCandidatePayload:
    center: tuple[float, float]
    radius: float

    def __post_init__(self) -> None:
        if not all(isfinite(float(value)) for value in (*self.center, self.radius)):
            raise ValueError("Circle candidate geometry must be finite")
        if self.radius <= 0.0:
            raise ValueError("Circle radius must be positive")

    def to_dict(self) -> dict[str, object]:
        return {"center": list(self.center), "radius": self.radius}


@dataclass(frozen=True)
class SymbolCandidatePayload:
    detector_symbol_kind: str
    source_bbox: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        _required(self.detector_symbol_kind, "detector_symbol_kind")

    def to_dict(self) -> dict[str, object]:
        return {
            "detector_symbol_kind": self.detector_symbol_kind,
            "source_bbox": list(self.source_bbox),
        }


CandidatePayloadValue: TypeAlias = (
    LineCandidatePayload
    | TextCandidatePayload
    | LogoCandidatePayload
    | SignatureCandidatePayload
    | StructuralRoiCandidatePayload
    | CircleCandidatePayload
    | SymbolCandidatePayload
)


_PAYLOAD_KIND_TYPES: dict[CandidateKind, tuple[type[object], ...]] = {
    CandidateKind.LINE_SEGMENT: (LineCandidatePayload,),
    CandidateKind.OCR_TEXT: (TextCandidatePayload,),
    CandidateKind.LOGO: (LogoCandidatePayload,),
    CandidateKind.SIGNATURE: (SignatureCandidatePayload,),
    CandidateKind.STRUCTURAL_ROI: (StructuralRoiCandidatePayload,),
    CandidateKind.TABLE_REGION: (StructuralRoiCandidatePayload,),
    CandidateKind.CIRCLE: (CircleCandidatePayload,),
    CandidateKind.SYMBOL: (SymbolCandidatePayload,),
}


@dataclass(frozen=True)
class CandidateProducerIdentity:
    producer: str
    producer_version: str
    producer_config_id: str
    producer_config_json: str
    diagnostic_metadata_json: str
    schema_version: str = DRAFTSMAN_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        _required(self.producer, "producer")
        _required(self.producer_version, "producer_version")
        _assert_canonical_json(self.producer_config_json, "producer_config_json")
        _assert_canonical_json(
            self.diagnostic_metadata_json,
            "diagnostic_metadata_json",
        )
        expected = semantic_id(
            "candidate-producer-config",
            self.schema_version,
            self.identity_payload(),
        )
        if self.producer_config_id != expected:
            raise ValueError("producer_config_id does not match producer semantics")

    @classmethod
    def create(
        cls,
        *,
        producer: str,
        producer_version: str,
        producer_config: object,
        diagnostic_metadata: object | None = None,
        schema_version: str = DRAFTSMAN_CANDIDATE_VERSION,
    ) -> CandidateProducerIdentity:
        config_json = _canonical_payload_json(
            producer_config,
            "producer_config",
        )
        identity = {
            "producer": producer,
            "producer_version": producer_version,
            "producer_config": json.loads(config_json),
        }
        return cls(
            producer=producer,
            producer_version=producer_version,
            producer_config_id=semantic_id(
                "candidate-producer-config",
                schema_version,
                identity,
            ),
            producer_config_json=config_json,
            diagnostic_metadata_json=canonical_json(
                diagnostic_metadata or {}
            ),
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_config": json.loads(self.producer_config_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_config_id": self.producer_config_id,
            "producer_config": json.loads(self.producer_config_json),
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


@dataclass(frozen=True)
class CandidateEvidenceRef:
    evidence_kind: str
    evidence_id: str
    evidence_hash: str
    evidence_payload_json: str
    identity_participates: bool = True

    def __post_init__(self) -> None:
        _required(self.evidence_kind, "evidence_kind")
        _required(self.evidence_id, "evidence_id")
        _assert_canonical_json(self.evidence_payload_json, "evidence_payload_json")
        expected = sha256(self.evidence_payload_json.encode("utf-8")).hexdigest()
        if self.evidence_hash != expected:
            raise ValueError("evidence_hash does not match evidence payload")

    @classmethod
    def create(
        cls,
        *,
        evidence_kind: str,
        evidence_id: str,
        evidence_payload: object,
        identity_participates: bool = True,
    ) -> CandidateEvidenceRef:
        payload_json = canonical_json(evidence_payload)
        return cls(
            evidence_kind=evidence_kind,
            evidence_id=evidence_id,
            evidence_hash=sha256(payload_json.encode("utf-8")).hexdigest(),
            evidence_payload_json=payload_json,
            identity_participates=identity_participates,
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
            "identity_participates": self.identity_participates,
            "evidence_payload": json.loads(self.evidence_payload_json),
        }


@dataclass(frozen=True)
class DraftsmanCandidateRecord:
    stable_candidate_id: str
    candidate_payload_id: str
    candidate_kind: CandidateKind
    source_page_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    transform_id: str
    payload: CandidatePayloadValue
    confidence: float
    producer: str
    producer_version: str
    producer_config_id: str
    evidence_refs: tuple[CandidateEvidenceRef, ...]
    occurrence: int
    diagnostic_metadata_json: str
    schema_version: str = DRAFTSMAN_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        _required(self.stable_candidate_id, "stable_candidate_id")
        _required(self.candidate_payload_id, "candidate_payload_id")
        _required(self.source_page_id, "source_page_id")
        _required(self.source_document_id, "source_document_id")
        if self.source_page <= 0:
            raise ValueError("source_page must be positive")
        _required(self.transform_id, "transform_id")
        _confidence(self.confidence)
        _required(self.producer, "producer")
        _required(self.producer_version, "producer_version")
        _required(self.producer_config_id, "producer_config_id")
        if self.occurrence <= 0:
            raise ValueError("occurrence must be positive")
        expected_types = _PAYLOAD_KIND_TYPES[self.candidate_kind]
        if not isinstance(self.payload, expected_types):
            raise TypeError(
                f"{self.candidate_kind.value} does not accept "
                f"{type(self.payload).__name__}"
            )
        if self.evidence_refs != tuple(
            sorted(self.evidence_refs, key=lambda item: canonical_json_bytes(item.to_dict()))
        ):
            raise ValueError("evidence_refs must use canonical order")
        _assert_canonical_json(
            self.diagnostic_metadata_json,
            "diagnostic_metadata_json",
        )
        expected_payload_id = semantic_id(
            "candidate-payload",
            self.schema_version,
            {
                "candidate_kind": self.candidate_kind.value,
                "payload": self.payload.to_dict(),
            },
        )
        if self.candidate_payload_id != expected_payload_id:
            raise ValueError("candidate_payload_id does not match typed payload")
        expected_id = semantic_id(
            "draftsman-candidate",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_candidate_id != expected_id:
            raise ValueError("stable_candidate_id does not match candidate semantics")

    @classmethod
    def create(
        cls,
        *,
        source_page: SourcePageRef,
        source_region: SourceRegionRef,
        transform: TransformRef,
        candidate_kind: CandidateKind,
        payload: CandidatePayloadValue,
        confidence: float,
        producer: CandidateProducerIdentity,
        evidence_refs: Sequence[CandidateEvidenceRef] = (),
        occurrence: int = 1,
        diagnostic_metadata: object | None = None,
        schema_version: str = DRAFTSMAN_CANDIDATE_VERSION,
    ) -> DraftsmanCandidateRecord:
        evidence = tuple(
            sorted(evidence_refs, key=lambda item: canonical_json_bytes(item.to_dict()))
        )
        payload_id = semantic_id(
            "candidate-payload",
            schema_version,
            {
                "candidate_kind": candidate_kind.value,
                "payload": payload.to_dict(),
            },
        )
        identity = {
            "source_page_id": source_page.source_page_id,
            "source_region": source_region.identity_payload(),
            "transform_id": transform.transform_id,
            "candidate_kind": candidate_kind.value,
            "candidate_payload_id": payload_id,
            "confidence": float(confidence),
            "producer_config_id": producer.producer_config_id,
            "identity_evidence": [
                item.identity_payload()
                for item in evidence
                if item.identity_participates
            ],
            "occurrence": int(occurrence),
        }
        return cls(
            stable_candidate_id=semantic_id(
                "draftsman-candidate",
                schema_version,
                identity,
            ),
            candidate_payload_id=payload_id,
            candidate_kind=candidate_kind,
            source_page_id=source_page.source_page_id,
            source_document_id=source_page.source_document_id,
            source_page=source_page.source_page,
            source_region=source_region,
            transform_id=transform.transform_id,
            payload=payload,
            confidence=_confidence(confidence),
            producer=producer.producer,
            producer_version=producer.producer_version,
            producer_config_id=producer.producer_config_id,
            evidence_refs=evidence,
            occurrence=int(occurrence),
            diagnostic_metadata_json=canonical_json(
                diagnostic_metadata or {}
            ),
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page_id,
            "source_region": self.source_region.identity_payload(),
            "transform_id": self.transform_id,
            "candidate_kind": self.candidate_kind.value,
            "candidate_payload_id": self.candidate_payload_id,
            "confidence": self.confidence,
            "producer_config_id": self.producer_config_id,
            "identity_evidence": [
                item.identity_payload()
                for item in self.evidence_refs
                if item.identity_participates
            ],
            "occurrence": self.occurrence,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_candidate_id": self.stable_candidate_id,
            "candidate_payload_id": self.candidate_payload_id,
            "candidate_kind": self.candidate_kind.value,
            "source_page_id": self.source_page_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_region": self.source_region.to_dict(),
            "transform_id": self.transform_id,
            "payload": self.payload.to_dict(),
            "confidence": self.confidence,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "producer_config_id": self.producer_config_id,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "occurrence": self.occurrence,
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


@dataclass(frozen=True)
class CandidateRelationship:
    stable_relationship_id: str
    relationship_kind: CandidateRelationshipKind
    source_candidate_id: str
    target_candidate_id: str
    evidence_json: str
    schema_version: str = CANDIDATE_RELATIONSHIP_VERSION

    def __post_init__(self) -> None:
        _required(self.stable_relationship_id, "stable_relationship_id")
        _required(self.source_candidate_id, "source_candidate_id")
        _required(self.target_candidate_id, "target_candidate_id")
        if self.source_candidate_id == self.target_candidate_id:
            raise ValueError("Candidate relationship endpoints must differ")
        _assert_canonical_json(self.evidence_json, "evidence_json")
        expected = semantic_id(
            "candidate-relationship",
            self.schema_version,
            self.identity_payload(),
        )
        if self.stable_relationship_id != expected:
            raise ValueError("stable_relationship_id does not match semantics")

    @classmethod
    def create(
        cls,
        *,
        relationship_kind: CandidateRelationshipKind,
        source_candidate_id: str,
        target_candidate_id: str,
        evidence: object | None = None,
        schema_version: str = CANDIDATE_RELATIONSHIP_VERSION,
    ) -> CandidateRelationship:
        source = _required(source_candidate_id, "source_candidate_id")
        target = _required(target_candidate_id, "target_candidate_id")
        if relationship_kind in {
            CandidateRelationshipKind.OVERLAPS,
            CandidateRelationshipKind.COLLINEAR_WITH,
        }:
            source, target = sorted((source, target))
        evidence_json = canonical_json(evidence or {})
        identity = {
            "relationship_kind": relationship_kind.value,
            "source_candidate_id": source,
            "target_candidate_id": target,
            "evidence": json.loads(evidence_json),
        }
        return cls(
            stable_relationship_id=semantic_id(
                "candidate-relationship",
                schema_version,
                identity,
            ),
            relationship_kind=relationship_kind,
            source_candidate_id=source,
            target_candidate_id=target,
            evidence_json=evidence_json,
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "relationship_kind": self.relationship_kind.value,
            "source_candidate_id": self.source_candidate_id,
            "target_candidate_id": self.target_candidate_id,
            "evidence": json.loads(self.evidence_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_relationship_id": self.stable_relationship_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class DraftsmanCandidateManifest:
    source_page: SourcePageRef
    transform: TransformRef
    candidates: tuple[DraftsmanCandidateRecord, ...]
    producers: tuple[CandidateProducerIdentity, ...]
    relationships: tuple[CandidateRelationship, ...] = ()
    schema_version: str = DRAFTSMAN_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        candidate_ids = [item.stable_candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Candidate manifest IDs must be unique")
        producer_ids = {item.producer_config_id for item in self.producers}
        missing_producers = {
            item.producer_config_id for item in self.candidates
        }.difference(producer_ids)
        if missing_producers:
            raise ValueError(
                f"Candidate manifest lacks producer identities: {sorted(missing_producers)}"
            )
        known_candidates = set(candidate_ids)
        unknown_relationship_ids = {
            endpoint
            for relation in self.relationships
            for endpoint in (
                relation.source_candidate_id,
                relation.target_candidate_id,
            )
            if endpoint not in known_candidates
        }
        if unknown_relationship_ids:
            raise ValueError(
                "Candidate relationships reference unknown candidates: "
                f"{sorted(unknown_relationship_ids)}"
            )

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-candidate-manifest",
            self.schema_version,
            self.identity_payload(),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page.source_page_id,
            "transform_id": self.transform.transform_id,
            "candidate_ids": sorted(
                item.stable_candidate_id for item in self.candidates
            ),
            "candidate_payload_ids": sorted(
                item.candidate_payload_id for item in self.candidates
            ),
            "producer_config_ids": sorted(
                item.producer_config_id for item in self.producers
            ),
            "relationship_ids": sorted(
                item.stable_relationship_id for item in self.relationships
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_page": self.source_page.to_dict(),
            "transform": self.transform.to_dict(),
            "candidate_count": self.candidate_count,
            "candidates": [
                item.to_dict()
                for item in sorted(
                    self.candidates,
                    key=lambda candidate: candidate.stable_candidate_id,
                )
            ],
            "producers": [
                item.to_dict()
                for item in sorted(
                    self.producers,
                    key=lambda producer: producer.producer_config_id,
                )
            ],
            "relationships": [
                item.to_dict()
                for item in sorted(
                    self.relationships,
                    key=lambda relation: relation.stable_relationship_id,
                )
            ],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def candidate_manifest_sha256(manifest: DraftsmanCandidateManifest) -> str:
    return sha256(manifest.canonical_bytes()).hexdigest()


def contract_parent_version() -> str:
    return DRAFTSMAN_CONTRACT_VERSION
