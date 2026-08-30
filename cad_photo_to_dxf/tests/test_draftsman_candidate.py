from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from app.draftsman_candidate import (
    CANDIDATE_RELATIONSHIP_VERSION,
    DRAFTSMAN_CANDIDATE_VERSION,
    CandidateKind,
    CandidateProducerIdentity,
    CandidateRelationship,
    CandidateRelationshipKind,
    DraftsmanCandidateManifest,
    DraftsmanCandidateRecord,
    LineCandidatePayload,
    TextCandidatePayload,
)
from app.draftsman_contract import SourcePageRef, SourceRegionRef, TransformRef


def _page(source_sha256: str = "a" * 64) -> SourcePageRef:
    return SourcePageRef("candidate-document", 2, source_sha256, (300, 200))


def _transform() -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload={
            "origin": [0.0, 200.0],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _producer(
    *,
    config: object | None = None,
    diagnostic_metadata: object | None = None,
) -> CandidateProducerIdentity:
    return CandidateProducerIdentity.create(
        producer="unit.detector",
        producer_version="unit-detector-v1",
        producer_config=config or {"threshold": 7, "modes": ["line", "text"]},
        diagnostic_metadata=diagnostic_metadata,
    )


def _line_payload(end_x: float = 80.0) -> LineCandidatePayload:
    return LineCandidatePayload(
        start=(10.0, 20.0),
        end=(end_x, 20.0),
        width=1.25,
        detector_history=("detected:hough",),
        proposed_layer="DETAIL",
        classification_confidence=0.91,
        classification_reasons=("axis-aligned",),
    )


def _candidate(
    *,
    page: SourcePageRef | None = None,
    payload: LineCandidatePayload | None = None,
    producer: CandidateProducerIdentity | None = None,
    diagnostic_metadata: object | None = None,
    occurrence: int = 1,
) -> DraftsmanCandidateRecord:
    return DraftsmanCandidateRecord.create(
        source_page=page or _page(),
        source_region=SourceRegionRef(10.0, 20.0, 80.0, 20.0),
        transform=_transform(),
        candidate_kind=CandidateKind.LINE_SEGMENT,
        payload=payload or _line_payload(),
        confidence=0.88,
        producer=producer or _producer(),
        occurrence=occurrence,
        diagnostic_metadata=diagnostic_metadata,
    )


def test_candidate_contract_version_and_immutability() -> None:
    assert DRAFTSMAN_CANDIDATE_VERSION == "draftsman-candidate-v1"
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.confidence = 0.2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        candidate.payload.width = 2.0  # type: ignore[union-attr,misc]


def test_candidate_id_is_deterministic() -> None:
    first = _candidate()
    replay = _candidate()
    assert first.stable_candidate_id == replay.stable_candidate_id
    assert first.candidate_payload_id == replay.candidate_payload_id


def test_source_mutation_changes_candidate_id() -> None:
    first = _candidate(page=_page("a" * 64))
    changed = _candidate(page=_page("b" * 64))
    assert first.stable_candidate_id != changed.stable_candidate_id


def test_geometry_mutation_changes_payload_and_candidate_ids() -> None:
    first = _candidate(payload=_line_payload(80.0))
    changed = _candidate(payload=_line_payload(81.0))
    assert first.candidate_payload_id != changed.candidate_payload_id
    assert first.stable_candidate_id != changed.stable_candidate_id


def test_producer_config_mutation_changes_candidate_id() -> None:
    first = _candidate(producer=_producer(config={"threshold": 7}))
    changed = _candidate(producer=_producer(config={"threshold": 8}))
    assert first.stable_candidate_id != changed.stable_candidate_id


def test_volatile_metadata_does_not_change_semantic_ids() -> None:
    first = _candidate(
        producer=_producer(
            diagnostic_metadata={
                "timestamp": "2026-08-31T00:00:00Z",
                "guid": "11111111-1111-1111-1111-111111111111",
            }
        ),
        diagnostic_metadata={"object_id": 12345},
    )
    replay = _candidate(
        producer=_producer(
            diagnostic_metadata={
                "timestamp": "2030-01-01T00:00:00Z",
                "guid": "99999999-9999-9999-9999-999999999999",
            }
        ),
        diagnostic_metadata={"object_id": 98765},
    )
    assert first.producer_config_id == replay.producer_config_id
    assert first.candidate_payload_id == replay.candidate_payload_id
    assert first.stable_candidate_id == replay.stable_candidate_id


def test_candidate_kind_requires_matching_typed_payload() -> None:
    line = _candidate()
    with pytest.raises(TypeError, match="OCR_TEXT does not accept"):
        DraftsmanCandidateRecord.create(
            source_page=_page(),
            source_region=line.source_region,
            transform=_transform(),
            candidate_kind=CandidateKind.OCR_TEXT,
            payload=_line_payload(),
            confidence=0.8,
            producer=_producer(),
        )


def test_typed_text_serialization_names_source_evidence_not_final_geometry() -> None:
    payload = TextCandidatePayload(
        raw_recognized_text="A-101",
        source_bbox=(20, 30, 40, 12),
        source_quad=((20.0, 30.0), (60.0, 30.0), (60.0, 42.0), (20.0, 42.0)),
        rotation_degrees=0.0,
        orientation_evidence="source-quad-and-rotation",
        detector_text_kind="text_candidate",
        detector_source="rapidocr-tile",
        character_boxes=(),
        replacement_safe=True,
        review_note="",
    )
    serialized = payload.to_dict()
    assert serialized["raw_recognized_text"] == "A-101"
    assert serialized["source_bbox"] == [20, 30, 40, 12]
    assert "cad_insertion" not in serialized
    assert "text_height" not in serialized
    assert "final_text_geometry" not in serialized


def test_relationship_serialization_and_direction_rules() -> None:
    first = _candidate(occurrence=1)
    second = _candidate(occurrence=2)
    overlap = CandidateRelationship.create(
        relationship_kind=CandidateRelationshipKind.OVERLAPS,
        source_candidate_id=second.stable_candidate_id,
        target_candidate_id=first.stable_candidate_id,
        evidence={"method": "unit-bbox"},
    )
    assert overlap.schema_version == CANDIDATE_RELATIONSHIP_VERSION
    assert overlap.source_candidate_id < overlap.target_candidate_id
    assert overlap.to_dict()["relationship_kind"] == "OVERLAPS"


def test_manifest_serialization_is_order_independent() -> None:
    first = _candidate(payload=_line_payload(80.0))
    second = _candidate(payload=_line_payload(90.0))
    page = _page()
    transform = _transform()
    producer = _producer()
    forward = DraftsmanCandidateManifest(
        page,
        transform,
        (first, second),
        (producer,),
    )
    reverse = DraftsmanCandidateManifest(
        page,
        transform,
        (second, first),
        (producer,),
    )
    assert forward.manifest_id == reverse.manifest_id
    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert json.loads(forward.canonical_bytes())["candidate_count"] == 2
