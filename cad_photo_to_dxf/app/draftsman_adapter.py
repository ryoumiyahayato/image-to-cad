"""Read-only adapter from the current production model to Draftsman shadow v1."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import numpy as np

from .draftsman_contract import (
    CandidateRef,
    DRAFTSMAN_CONTRACT_VERSION,
    DraftsmanPageSnapshot,
    EntityProvenance,
    EvidenceState,
    ExternalEvidenceRef,
    FinalEntityRecord,
    OutputDisposition,
    OwnershipState,
    ReviewItem,
    SourcePageRef,
    SourceRegionRef,
    TransformRef,
    canonical_json,
    canonical_json_bytes,
    semantic_id,
    stable_review_item_id,
)
LEGACY_ADAPTER_VERSION = "legacy-final-structure-adapter-v1"
RC3_CREATION_METHOD = "legacy_rc3_adapter"
RC3_RECONSTRUCTION_RULE = "text_mask_restoration"
TEXT_MASK_RESTORATION = RC3_RECONSTRUCTION_RULE
V2_RESTORATION_EVIDENCE_KIND = "editable-text-v2-restoration"


class FinalStructureView(Protocol):
    """The read-only portion of ``FinalStructure`` consumed by this adapter."""

    source_size_px: tuple[int, int]
    straight_lines: Sequence[object]
    contours: Sequence[object]
    texts: Sequence[object]
    logos: Sequence[object]
    signatures: Sequence[object]
    observations: Sequence[Mapping[str, object]]

    @property
    def structure_id(self) -> str: ...

    def assert_valid(self) -> None: ...


def _round(value: float) -> float:
    return round(float(value), 9)


def _line_key(coords: Sequence[float]) -> tuple[float, float, float, float]:
    if len(coords) != 4:
        raise ValueError("Line evidence must contain four coordinates")
    first = (_round(coords[0]), _round(coords[1]))
    second = (_round(coords[2]), _round(coords[3]))
    start, end = sorted((first, second))
    return (start[0], start[1], end[0], end[1])


def load_v2_restoration_records(path: str | Path) -> tuple[Mapping[str, object], ...]:
    """Load the existing V2 page evidence without rewriting its schema."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    restorations = payload.get("restorations")
    if not isinstance(restorations, list):
        raise ValueError("V2 page evidence does not contain restorations")
    if not all(isinstance(item, Mapping) for item in restorations):
        raise ValueError("V2 restorations must be JSON objects")
    return tuple(restorations)


def _v2_index(
    records: Sequence[Mapping[str, object]],
) -> dict[tuple[float, float, float, float], tuple[Mapping[str, object], ...]]:
    grouped: dict[
        tuple[float, float, float, float],
        list[Mapping[str, object]],
    ] = {}
    for record in records:
        source_geometry = record.get("source_geometry")
        if not isinstance(source_geometry, Mapping):
            raise ValueError("V2 restoration lacks source_geometry")
        coords = source_geometry.get("coords")
        if not isinstance(coords, list):
            raise ValueError("V2 restoration lacks source geometry coordinates")
        grouped.setdefault(_line_key(coords), []).append(record)
    return {
        key: tuple(sorted(values, key=_v2_record_sort_key))
        for key, values in grouped.items()
    }


def _v2_record_sort_key(record: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(
        {
            "restoration_id": record.get("restoration_id"),
            "canonical_entity_id": record.get("canonical_entity_id"),
            "evidence_hash": record.get("evidence_hash"),
        }
    )


def _region_from_points(
    points: Sequence[Sequence[float]],
) -> SourceRegionRef:
    if not points:
        raise ValueError("Entity source points must not be empty")
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return SourceRegionRef(min(xs), min(ys), max(xs), max(ys))


def _masked_payload(item: object) -> dict[str, object]:
    mask = np.ascontiguousarray(getattr(item, "mask"), dtype=np.uint8)
    payload_method = getattr(item, "payload", None)
    details = payload_method() if callable(payload_method) else {}
    return {
        "bbox": [int(value) for value in getattr(item, "bbox")],
        "mask_sha256": sha256(mask.tobytes()).hexdigest(),
        "foreground_pixels": int(np.count_nonzero(mask)),
        "legacy_details": details,
    }


@dataclass(frozen=True)
class _EntitySeed:
    source_region: SourceRegionRef
    source_candidate_ids: tuple[str, ...]
    entity_kind: str
    state: EvidenceState
    provenance: EntityProvenance
    confidence: float
    ownership_state: OwnershipState
    entity_payload: object
    output_disposition: OutputDisposition = OutputDisposition.FINAL_VISIBLE

    def occurrence_key(self) -> bytes:
        return canonical_json_bytes(
            {
                "source_region": self.source_region.identity_payload(),
                "source_candidate_ids": list(self.source_candidate_ids),
                "entity_kind": self.entity_kind,
                "state": self.state.value,
                "provenance_id": self.provenance.provenance_id,
                "ownership_state": self.ownership_state.value,
                "entity_payload": self.entity_payload,
            }
        )


def _candidate_ids(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _legacy_provenance(
    *,
    source_region: SourceRegionRef,
    transform: TransformRef,
    source_candidate_ids: Sequence[str],
    history: Sequence[str] = (),
    creation_method: str = LEGACY_ADAPTER_VERSION,
    reconstruction_method: str | None = None,
    reconstruction_rule: str | None = None,
    external_evidence: Sequence[ExternalEvidenceRef] = (),
    missing: Sequence[str] = (),
) -> EntityProvenance:
    candidates = _candidate_ids(source_candidate_ids)
    unavailable = list(missing)
    if not candidates:
        unavailable.append("legacy_source_candidate_ids")
    return EntityProvenance.create(
        creation_method=creation_method,
        source_candidate_ids=candidates,
        source_region=source_region,
        transform_id=transform.transform_id,
        reconstruction_method=reconstruction_method,
        reconstruction_rule=reconstruction_rule,
        history=tuple(history),
        external_evidence=external_evidence,
        legacy_evidence_unavailable=tuple(unavailable),
        diagnostic_metadata={"adapter_version": LEGACY_ADAPTER_VERSION},
    )


def _external_v2(record: Mapping[str, object]) -> ExternalEvidenceRef:
    evidence_id = str(record.get("restoration_id") or "").strip()
    if not evidence_id:
        raise ValueError("V2 restoration lacks restoration_id")
    raw_hash = str(record.get("evidence_hash") or "").strip().lower()
    evidence_hash = raw_hash if len(raw_hash) == 64 else None
    return ExternalEvidenceRef.create(
        evidence_kind=V2_RESTORATION_EVIDENCE_KIND,
        evidence_id=evidence_id,
        evidence=record,
        evidence_hash=evidence_hash,
    )


def _line_seed(
    line: object,
    *,
    transform: TransformRef,
    evidence_index: Mapping[
        tuple[float, float, float, float],
        tuple[Mapping[str, object], ...],
    ],
    evidence_offsets: Counter[tuple[float, float, float, float]],
) -> _EntitySeed:
    coords = (
        float(getattr(line, "x1")),
        float(getattr(line, "y1")),
        float(getattr(line, "x2")),
        float(getattr(line, "y2")),
    )
    region = _region_from_points(((coords[0], coords[1]), (coords[2], coords[3])))
    history = tuple(str(item) for item in getattr(line, "history", ()))
    current_candidates = tuple(str(item) for item in getattr(line, "source_ids", ()))
    reconstructed = TEXT_MASK_RESTORATION in history
    external: tuple[ExternalEvidenceRef, ...] = ()
    candidates = current_candidates
    missing: tuple[str, ...] = ()
    if reconstructed:
        key = _line_key(coords)
        matches = evidence_index.get(key, ())
        offset = evidence_offsets[key]
        evidence_offsets[key] += 1
        record = matches[offset] if offset < len(matches) else None
        if record is None:
            missing = ("editable_text_v2_restoration_record",)
        else:
            external = (_external_v2(record),)
            candidates = (
                *candidates,
                str(record.get("restoration_id") or ""),
                str(record.get("canonical_entity_id") or ""),
            )
    candidate_ids = _candidate_ids(candidates)
    provenance = _legacy_provenance(
        source_region=region,
        transform=transform,
        source_candidate_ids=candidate_ids,
        history=history,
        creation_method=(RC3_CREATION_METHOD if reconstructed else LEGACY_ADAPTER_VERSION),
        reconstruction_method=(RC3_CREATION_METHOD if reconstructed else None),
        reconstruction_rule=(RC3_RECONSTRUCTION_RULE if reconstructed else None),
        external_evidence=external,
        missing=missing,
    )
    confidence = min(
        float(getattr(line, "confidence", 1.0)),
        float(getattr(line, "classification_confidence", 1.0)),
    )
    return _EntitySeed(
        source_region=region,
        source_candidate_ids=candidate_ids,
        entity_kind="LINE",
        state=(EvidenceState.RECONSTRUCTED if reconstructed else EvidenceState.OBSERVED),
        provenance=provenance,
        confidence=max(0.0, min(1.0, confidence)),
        ownership_state=OwnershipState.PRIMARY,
        entity_payload={
            "start": [coords[0], coords[1]],
            "end": [coords[2], coords[3]],
            "width": float(getattr(line, "width", 1.0)),
            "layer": str(getattr(line, "layer", "DETAIL")),
            "classification_reasons": list(
                getattr(line, "classification_reasons", ())
            ),
        },
    )


def _contour_seed(path: object, transform: TransformRef) -> _EntitySeed:
    points = tuple(
        (float(point[0]), float(point[1]))
        for point in getattr(path, "points")
    )
    region = _region_from_points(points)
    provenance = _legacy_provenance(
        source_region=region,
        transform=transform,
        source_candidate_ids=(),
        missing=("legacy_contour_candidate_id",),
    )
    return _EntitySeed(
        source_region=region,
        source_candidate_ids=(),
        entity_kind="POLYLINE",
        state=EvidenceState.OBSERVED,
        provenance=provenance,
        confidence=1.0,
        ownership_state=OwnershipState.PRIMARY,
        entity_payload={
            "points": [[x, y] for x, y in points],
            "parent": getattr(path, "parent"),
            "depth": int(getattr(path, "depth")),
            "root": int(getattr(path, "root")),
        },
    )


def _text_seed(text: object, transform: TransformRef) -> _EntitySeed:
    bbox = tuple(int(value) for value in getattr(text, "bbox"))
    region = SourceRegionRef.from_xywh(bbox)
    provenance = _legacy_provenance(
        source_region=region,
        transform=transform,
        source_candidate_ids=(),
        missing=("legacy_text_candidate_id",),
    )
    quad = getattr(text, "quad", None)
    return _EntitySeed(
        source_region=region,
        source_candidate_ids=(),
        entity_kind="TEXT",
        state=EvidenceState.OBSERVED,
        provenance=provenance,
        confidence=max(0.0, min(1.0, float(getattr(text, "confidence", 0.0)))),
        ownership_state=OwnershipState.PRIMARY,
        entity_payload={
            "content": str(getattr(text, "text")),
            "bbox": list(bbox),
            "quad": None
            if quad is None
            else [[float(x), float(y)] for x, y in quad],
            "rotation_degrees": float(getattr(text, "rotation_deg", 0.0)),
            "kind": str(getattr(text, "kind", "text")),
            "source": str(getattr(text, "source", "unknown")),
            "approved": bool(getattr(text, "approved", True)),
            "reviewed": bool(getattr(text, "reviewed", False)),
            "replacement_safe": bool(getattr(text, "replacement_safe", True)),
        },
    )


def _masked_seed(
    item: object,
    *,
    transform: TransformRef,
    entity_kind: str,
) -> _EntitySeed:
    bbox = tuple(int(value) for value in getattr(item, "bbox"))
    region = SourceRegionRef.from_xywh(bbox)
    provenance = _legacy_provenance(
        source_region=region,
        transform=transform,
        source_candidate_ids=(),
        missing=(f"legacy_{entity_kind.lower()}_candidate_id",),
    )
    confidence = 1.0
    visual = getattr(item, "visual_evidence", None)
    if visual is not None:
        confidence = float(getattr(visual, "confidence", confidence))
    if hasattr(item, "structural_score"):
        confidence = float(getattr(item, "structural_score"))
    return _EntitySeed(
        source_region=region,
        source_candidate_ids=(),
        entity_kind=entity_kind,
        state=EvidenceState.OBSERVED,
        provenance=provenance,
        confidence=max(0.0, min(1.0, confidence)),
        ownership_state=OwnershipState.PRIMARY,
        entity_payload=_masked_payload(item),
    )


def _page_review_items(
    structure: FinalStructureView,
    source_page: SourcePageRef,
) -> tuple[ReviewItem, ...]:
    page_region = SourceRegionRef(
        0.0,
        0.0,
        float(source_page.source_size_px[0]),
        float(source_page.source_size_px[1]),
    )
    items: list[ReviewItem] = []
    reasons = (
        ("conflict_objects", "LEGACY_PAGE_OWNERSHIP_CONFLICT"),
        ("downgrades", "LEGACY_PAGE_OWNERSHIP_DOWNGRADE"),
    )
    for observation in structure.observations:
        if str(observation.get("event", "")) != "ownership_partitioned":
            continue
        for field, reason in reasons:
            raw_count = observation.get(field, 0)
            count = int(raw_count) if isinstance(raw_count, (int, float, str)) else 0
            if count <= 0:
                continue
            item_id = stable_review_item_id(
                source_page=source_page,
                source_region=page_region,
                review_reason=reason,
                candidate_identity={"field": field, "count": count},
            )
            items.append(
                ReviewItem(
                    review_item_id=item_id,
                    source_document_id=source_page.source_document_id,
                    source_page=source_page.source_page,
                    source_region=page_region,
                    review_reason=reason,
                    candidate_entity_ids=(),
                    alternative_candidate_ids=(),
                    suggested_action="OPEN_PAGE_REGION",
                )
            )
    return tuple(sorted(items, key=lambda item: item.review_item_id))


def adapt_legacy_final_structure(
    structure: FinalStructureView,
    *,
    document_id: str,
    page_number: int,
    source_sha256: str,
    transform: TransformRef,
    v2_restoration_records: Sequence[Mapping[str, object]] = (),
) -> DraftsmanPageSnapshot:
    """Project ``FinalStructure`` into a deterministic, read-only shadow model."""

    structure.assert_valid()
    structure_id_before = structure.structure_id
    source_page = SourcePageRef(
        source_document_id=document_id,
        source_page=page_number,
        source_sha256=source_sha256,
        source_size_px=structure.source_size_px,
    )
    evidence_index = _v2_index(v2_restoration_records)
    evidence_offsets: Counter[tuple[float, float, float, float]] = Counter()
    seeds: list[_EntitySeed] = []
    seeds.extend(
        _line_seed(
            line,
            transform=transform,
            evidence_index=evidence_index,
            evidence_offsets=evidence_offsets,
        )
        for line in structure.straight_lines
    )
    seeds.extend(_contour_seed(path, transform) for path in structure.contours)
    seeds.extend(_text_seed(text, transform) for text in structure.texts)
    seeds.extend(
        _masked_seed(item, transform=transform, entity_kind="SYMBOL")
        for item in structure.logos
    )
    seeds.extend(
        _masked_seed(item, transform=transform, entity_kind="SIGNATURE")
        for item in structure.signatures
    )

    occurrence_counts: Counter[bytes] = Counter()
    entities: list[FinalEntityRecord] = []
    for seed in sorted(seeds, key=lambda item: item.occurrence_key()):
        occurrence_key = seed.occurrence_key()
        occurrence_counts[occurrence_key] += 1
        entities.append(
            FinalEntityRecord.create(
                source_page=source_page,
                source_region=seed.source_region,
                source_candidate_ids=seed.source_candidate_ids,
                transform_id=transform.transform_id,
                entity_kind=seed.entity_kind,
                state=seed.state,
                provenance=seed.provenance,
                confidence=seed.confidence,
                ownership_state=seed.ownership_state,
                entity_payload=seed.entity_payload,
                output_disposition=seed.output_disposition,
                occurrence=occurrence_counts[occurrence_key],
            )
        )

    snapshot = DraftsmanPageSnapshot(
        source_page=source_page,
        transform=transform,
        final_structure_id=structure_id_before,
        entities=tuple(entities),
        review_items=_page_review_items(structure, source_page),
    )
    structure.assert_valid()
    if structure.structure_id != structure_id_before:
        raise AssertionError("Draftsman adapter mutated FinalStructure")
    return snapshot


def legacy_candidate_ref(
    *,
    source_page: SourcePageRef,
    candidate_kind: str,
    source_region: SourceRegionRef,
    evidence: object,
) -> CandidateRef:
    """Build an explicit shadow candidate ref for M1 callers without wiring it."""

    return CandidateRef.create(
        source_page=source_page,
        candidate_kind=candidate_kind,
        source_region=source_region,
        evidence={
            "adapter_version": LEGACY_ADAPTER_VERSION,
            "evidence": evidence,
        },
    )


def shadow_manifest_sha256(snapshot: DraftsmanPageSnapshot) -> str:
    return sha256(snapshot.canonical_bytes()).hexdigest()


def shadow_contract_identity() -> str:
    return semantic_id(
        "draftsman-shadow-contract",
        DRAFTSMAN_CONTRACT_VERSION,
        {"legacy_adapter_version": LEGACY_ADAPTER_VERSION},
    )


def shadow_manifest_json(snapshot: DraftsmanPageSnapshot) -> str:
    return canonical_json(snapshot.to_dict())
