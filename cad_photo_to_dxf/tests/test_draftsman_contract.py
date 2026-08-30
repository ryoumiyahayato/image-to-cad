from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from app.draftsman_contract import (
    DRAFTSMAN_CONTRACT_VERSION,
    PROVENANCE_CONTRACT_VERSION,
    DraftsmanPageSnapshot,
    EntityProvenance,
    EvidenceState,
    FinalEntityRecord,
    OutputDisposition,
    OwnershipState,
    ReviewItem,
    ReviewStatus,
    SourcePageRef,
    SourceRegionRef,
    TransformRef,
    canonical_json,
    stable_review_item_id,
)


def _page(source_sha256: str = "a" * 64) -> SourcePageRef:
    return SourcePageRef("document-A", 3, source_sha256, (200, 100))


def _transform(payload: object | None = None) -> TransformRef:
    return TransformRef.create(
        source_space="source-pixel",
        target_space="cad-page",
        transform_payload=payload
        or {
            "origin": [0.0, 100.0],
            "scale": [1.0, -1.0],
            "rotation_degrees": 0.0,
        },
    )


def _entity(
    *,
    page: SourcePageRef | None = None,
    transform: TransformRef | None = None,
    geometry: object | None = None,
    candidate_ids: tuple[str, ...] = ("candidate-b", "candidate-a"),
    state: EvidenceState = EvidenceState.OBSERVED,
    diagnostic_metadata: object | None = None,
    schema_version: str = DRAFTSMAN_CONTRACT_VERSION,
) -> FinalEntityRecord:
    selected_page = page or _page()
    selected_transform = transform or _transform()
    region = SourceRegionRef(10.0, 20.0, 80.0, 20.0)
    provenance = EntityProvenance.create(
        creation_method="direct-observation-adapter-v1",
        source_candidate_ids=candidate_ids,
        source_region=region,
        transform_id=selected_transform.transform_id,
        diagnostic_metadata=diagnostic_metadata,
    )
    review_required = state in {
        EvidenceState.PROVISIONAL,
        EvidenceState.UNRESOLVED,
    }
    review_reason = "LINE_CONTINUATION_AMBIGUOUS" if review_required else None
    review_item_id = (
        stable_review_item_id(
            source_page=selected_page,
            source_region=region,
            review_reason=review_reason or "unused",
            candidate_ids=candidate_ids,
            candidate_identity=geometry or {"start": [10, 20], "end": [80, 20]},
        )
        if review_required
        else None
    )
    return FinalEntityRecord.create(
        source_page=selected_page,
        source_region=region,
        source_candidate_ids=candidate_ids,
        transform_id=selected_transform.transform_id,
        entity_kind="LINE",
        state=state,
        provenance=provenance,
        confidence=0.92,
        ownership_state=(
            OwnershipState.COMPETING
            if review_required
            else OwnershipState.PRIMARY
        ),
        entity_payload=geometry or {"start": [10, 20], "end": [80, 20]},
        review_state=(ReviewStatus.PENDING if review_required else ReviewStatus.NOT_REQUIRED),
        review_required=review_required,
        review_reason=review_reason,
        review_item_id=review_item_id,
        output_disposition=(
            OutputDisposition.PROVISIONAL_VISIBLE
            if review_required
            else OutputDisposition.FINAL_VISIBLE
        ),
        schema_version=schema_version,
    )


def test_contract_version_and_records_are_immutable() -> None:
    assert DRAFTSMAN_CONTRACT_VERSION == "draftsman-shadow-v1"
    assert PROVENANCE_CONTRACT_VERSION == "draftsman-provenance-v1"
    entity = _entity()
    with pytest.raises(FrozenInstanceError):
        entity.confidence = 0.1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        entity.source_region.x_min = 0.0  # type: ignore[misc]


def test_stable_entity_id_is_deterministic_and_candidate_order_independent() -> None:
    first = _entity(candidate_ids=("candidate-b", "candidate-a"))
    second = _entity(candidate_ids=("candidate-a", "candidate-b"))
    assert first.stable_entity_id == second.stable_entity_id
    assert first.provenance.provenance_id == second.provenance.provenance_id
    assert first.source_candidate_ids == ("candidate-a", "candidate-b")


def test_geometry_mutation_changes_stable_entity_id() -> None:
    first = _entity(geometry={"start": [10, 20], "end": [80, 20]})
    changed = _entity(geometry={"start": [10, 20], "end": [81, 20]})
    assert first.stable_entity_id != changed.stable_entity_id


def test_source_identity_and_transform_change_stable_entity_id() -> None:
    first = _entity()
    source_changed = _entity(page=_page("b" * 64))
    transform_changed = _entity(
        transform=_transform(
            {
                "origin": [0.0, 100.0],
                "scale": [2.0, -2.0],
                "rotation_degrees": 0.0,
            }
        )
    )
    assert first.stable_entity_id != source_changed.stable_entity_id
    assert first.stable_entity_id != transform_changed.stable_entity_id


def test_timestamp_and_guid_diagnostics_do_not_change_semantic_ids() -> None:
    first = _entity(
        diagnostic_metadata={
            "timestamp": "2026-08-31T00:00:00Z",
            "runtime_guid": "11111111-1111-1111-1111-111111111111",
        }
    )
    replay = _entity(
        diagnostic_metadata={
            "timestamp": "2030-01-01T12:34:56Z",
            "runtime_guid": "99999999-9999-9999-9999-999999999999",
        }
    )
    assert first.provenance.provenance_id == replay.provenance.provenance_id
    assert first.stable_entity_id == replay.stable_entity_id


@pytest.mark.parametrize("state", list(EvidenceState))
def test_state_serialization(state: EvidenceState) -> None:
    entity = _entity(state=state)
    assert entity.to_dict()["state"] == state.value
    assert json.loads(canonical_json(entity.to_dict()))["state"] == state.value


def test_provenance_serialization_preserves_minimum_contract() -> None:
    entity = _entity()
    payload = entity.provenance.to_dict()
    assert payload["schema_version"] == PROVENANCE_CONTRACT_VERSION
    assert payload["creation_method"] == "direct-observation-adapter-v1"
    assert payload["source_candidate_ids"] == ["candidate-a", "candidate-b"]
    assert payload["source_region"]["coordinate_space"] == "source-pixel"
    assert payload["transform_id"] == entity.transform_id
    assert payload["parent_entity_ids"] == []


def test_provisional_and_unresolved_require_stable_review_linkage() -> None:
    page = _page()
    transform = _transform()
    entity = _entity(
        page=page,
        transform=transform,
        state=EvidenceState.PROVISIONAL,
    )
    assert entity.review_required
    assert entity.review_item_id is not None
    review = ReviewItem(
        review_item_id=entity.review_item_id,
        source_document_id=page.source_document_id,
        source_page=page.source_page,
        source_region=entity.source_region,
        review_reason=entity.review_reason or "",
        candidate_entity_ids=(entity.stable_entity_id,),
        alternative_candidate_ids=(),
        suggested_action="CHOOSE_ALTERNATIVE",
    )
    snapshot = DraftsmanPageSnapshot(
        source_page=page,
        transform=transform,
        final_structure_id="synthetic-structure",
        entities=(entity,),
        review_items=(review,),
    )
    assert snapshot.to_dict()["review_items"][0]["review_item_id"] == entity.review_item_id


def test_provisional_without_review_link_is_rejected() -> None:
    observed = _entity()
    with pytest.raises(ValueError, match="require review"):
        FinalEntityRecord.create(
            source_page=_page(),
            source_region=observed.source_region,
            source_candidate_ids=observed.source_candidate_ids,
            transform_id=observed.transform_id,
            entity_kind="LINE",
            state=EvidenceState.PROVISIONAL,
            provenance=observed.provenance,
            confidence=0.5,
            ownership_state=OwnershipState.COMPETING,
            entity_payload={"start": [10, 20], "end": [80, 20]},
        )


def test_schema_version_changes_identity_instead_of_reinterpreting_history() -> None:
    current = _entity()
    future = _entity(schema_version="draftsman-shadow-v2")
    assert current.schema_version == "draftsman-shadow-v1"
    assert current.stable_entity_id != future.stable_entity_id


def test_snapshot_serialization_is_entity_order_independent() -> None:
    page = _page()
    transform = _transform()
    first = _entity(page=page, transform=transform)
    second = _entity(
        page=page,
        transform=transform,
        geometry={"start": [1, 2], "end": [3, 4]},
    )
    forward = DraftsmanPageSnapshot(
        page,
        transform,
        "structure",
        (first, second),
    )
    reverse = DraftsmanPageSnapshot(
        page,
        transform,
        "structure",
        (second, first),
    )
    assert forward.manifest_id == reverse.manifest_id
    assert forward.canonical_bytes() == reverse.canonical_bytes()
