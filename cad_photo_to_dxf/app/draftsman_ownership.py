"""Deterministic shadow ownership contracts and arbitration for Draftsman M2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import hypot, isfinite
from typing import Mapping, Sequence

from .draftsman_candidate import (
    DRAFTSMAN_CANDIDATE_VERSION,
    CandidateKind,
    DraftsmanCandidateManifest,
    DraftsmanCandidateRecord,
    LineCandidatePayload,
    TextCandidatePayload,
)
from .draftsman_contract import (
    SourcePageRef,
    SourceRegionRef,
    TransformRef,
    canonical_json,
    canonical_json_bytes,
    semantic_id,
)


DRAFTSMAN_OWNERSHIP_VERSION = "draftsman-ownership-v1"
DRAFTSMAN_DISCREPANCY_VERSION = "draftsman-ownership-discrepancy-v1"


class OwnershipDecisionState(str, Enum):
    RESOLVED = "RESOLVED"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


class OwnershipKind(str, Enum):
    STRUCTURE = "STRUCTURE"
    TEXT = "TEXT"
    LOGO = "LOGO"
    SIGNATURE = "SIGNATURE"
    SYMBOL = "SYMBOL"
    LAYOUT_CONTEXT = "LAYOUT_CONTEXT"
    GRAPHIC = "GRAPHIC"


class DiscrepancyCategory(str, Enum):
    SAME = "SAME"
    SHADOW_MORE_CONSERVATIVE = "SHADOW_MORE_CONSERVATIVE"
    SHADOW_MORE_SPECIFIC = "SHADOW_MORE_SPECIFIC"
    PRODUCTION_DESTRUCTIVE_CONFLICT = "PRODUCTION_DESTRUCTIVE_CONFLICT"
    SHADOW_PROVISIONAL = "SHADOW_PROVISIONAL"
    SHADOW_UNRESOLVED = "SHADOW_UNRESOLVED"


_CONTEXT_KINDS = {
    CandidateKind.STRUCTURAL_ROI,
    CandidateKind.TABLE_REGION,
}


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _canonical_payload(value: object) -> str:
    return canonical_json(value)


def _validate_canonical(value: str, name: str) -> None:
    if canonical_json(json.loads(value)) != value:
        raise ValueError(f"{name} must be canonical JSON")


def _score(value: float) -> float:
    resolved = float(value)
    if not isfinite(resolved):
        raise ValueError("Ownership score must be finite")
    return round(max(0.0, min(1.0, resolved)), 6)


def _sorted_ids(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_required(value, "candidate_id") for value in values}))


@dataclass(frozen=True)
class OwnershipEvidence:
    evidence_id: str
    reason_code: str
    candidate_ids: tuple[str, ...]
    weight: float
    details_json: str
    schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION

    def __post_init__(self) -> None:
        _required(self.reason_code, "reason_code")
        if not self.candidate_ids:
            raise ValueError("Ownership evidence requires candidate IDs")
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("Ownership evidence candidate IDs must be canonical")
        if not isfinite(float(self.weight)) or not -1.0 <= self.weight <= 1.0:
            raise ValueError("Ownership evidence weight must be finite and normalized")
        _validate_canonical(self.details_json, "details_json")
        expected = semantic_id(
            "ownership-evidence",
            self.schema_version,
            self.identity_payload(),
        )
        if self.evidence_id != expected:
            raise ValueError("evidence_id does not match ownership evidence")

    @classmethod
    def create(
        cls,
        *,
        reason_code: str,
        candidate_ids: Sequence[str],
        weight: float,
        details: object | None = None,
        schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION,
    ) -> OwnershipEvidence:
        ids = _sorted_ids(candidate_ids)
        details_json = _canonical_payload(details or {})
        identity = {
            "reason_code": _required(reason_code, "reason_code"),
            "candidate_ids": list(ids),
            "weight": round(float(weight), 6),
            "details": json.loads(details_json),
        }
        return cls(
            evidence_id=semantic_id("ownership-evidence", schema_version, identity),
            reason_code=reason_code,
            candidate_ids=ids,
            weight=round(float(weight), 6),
            details_json=details_json,
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "candidate_ids": list(self.candidate_ids),
            "weight": self.weight,
            "details": json.loads(self.details_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class OwnershipHypothesis:
    hypothesis_id: str
    ownership_kind: OwnershipKind
    supporting_candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    score: float
    schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION

    def __post_init__(self) -> None:
        if not self.supporting_candidate_ids:
            raise ValueError("Ownership hypothesis requires candidate support")
        if self.supporting_candidate_ids != _sorted_ids(self.supporting_candidate_ids):
            raise ValueError("Hypothesis candidate IDs must be canonical")
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("Hypothesis evidence IDs must be canonical")
        if self.score != _score(self.score):
            raise ValueError("Hypothesis score must be normalized")
        expected = semantic_id(
            "ownership-hypothesis",
            self.schema_version,
            self.identity_payload(),
        )
        if self.hypothesis_id != expected:
            raise ValueError("hypothesis_id does not match hypothesis")

    @classmethod
    def create(
        cls,
        *,
        ownership_kind: OwnershipKind,
        supporting_candidate_ids: Sequence[str],
        evidence_ids: Sequence[str],
        score: float,
        schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION,
    ) -> OwnershipHypothesis:
        candidate_ids = _sorted_ids(supporting_candidate_ids)
        canonical_evidence = tuple(sorted(set(evidence_ids)))
        normalized_score = _score(score)
        identity = {
            "ownership_kind": ownership_kind.value,
            "supporting_candidate_ids": list(candidate_ids),
            "evidence_ids": list(canonical_evidence),
            "score": normalized_score,
        }
        return cls(
            hypothesis_id=semantic_id(
                "ownership-hypothesis",
                schema_version,
                identity,
            ),
            ownership_kind=ownership_kind,
            supporting_candidate_ids=candidate_ids,
            evidence_ids=canonical_evidence,
            score=normalized_score,
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "ownership_kind": self.ownership_kind.value,
            "supporting_candidate_ids": list(self.supporting_candidate_ids),
            "evidence_ids": list(self.evidence_ids),
            "score": self.score,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class OwnershipConflict:
    conflict_id: str
    conflict_code: str
    candidate_ids: tuple[str, ...]
    details_json: str
    schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION

    def __post_init__(self) -> None:
        _required(self.conflict_code, "conflict_code")
        if not self.candidate_ids:
            raise ValueError("Ownership conflict requires candidate IDs")
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("Conflict candidate IDs must be canonical")
        _validate_canonical(self.details_json, "details_json")
        expected = semantic_id(
            "ownership-conflict",
            self.schema_version,
            self.identity_payload(),
        )
        if self.conflict_id != expected:
            raise ValueError("conflict_id does not match conflict")

    @classmethod
    def create(
        cls,
        *,
        conflict_code: str,
        candidate_ids: Sequence[str],
        details: object | None = None,
        schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION,
    ) -> OwnershipConflict:
        ids = _sorted_ids(candidate_ids)
        details_json = _canonical_payload(details or {})
        identity = {
            "conflict_code": _required(conflict_code, "conflict_code"),
            "candidate_ids": list(ids),
            "details": json.loads(details_json),
        }
        return cls(
            conflict_id=semantic_id("ownership-conflict", schema_version, identity),
            conflict_code=conflict_code,
            candidate_ids=ids,
            details_json=details_json,
            schema_version=schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "conflict_code": self.conflict_code,
            "candidate_ids": list(self.candidate_ids),
            "details": json.loads(self.details_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "conflict_id": self.conflict_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class OwnershipGroup:
    ownership_group_id: str
    source_page_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    candidate_ids: tuple[str, ...]
    hypotheses: tuple[OwnershipHypothesis, ...]
    selected_hypothesis_id: str | None
    decision_state: OwnershipDecisionState
    confidence: float
    evidence: tuple[OwnershipEvidence, ...]
    reasons: tuple[str, ...]
    conflicts: tuple[OwnershipConflict, ...]
    alternative_hypothesis_ids: tuple[str, ...]
    review_required: bool
    review_reason: str | None
    review_item_id: str | None
    diagnostic_metadata_json: str = "{}"
    schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION

    def __post_init__(self) -> None:
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("Ownership group candidate IDs must be canonical")
        if not self.candidate_ids:
            raise ValueError("Ownership group must not be empty")
        if self.hypotheses != tuple(
            sorted(self.hypotheses, key=lambda item: item.hypothesis_id)
        ):
            raise ValueError("Ownership hypotheses must use canonical order")
        hypothesis_ids = {item.hypothesis_id for item in self.hypotheses}
        if self.selected_hypothesis_id not in hypothesis_ids | {None}:
            raise ValueError("Selected hypothesis is not in ownership group")
        if not set(self.alternative_hypothesis_ids).issubset(hypothesis_ids):
            raise ValueError("Alternative hypothesis is not in ownership group")
        if self.alternative_hypothesis_ids != tuple(
            sorted(set(self.alternative_hypothesis_ids))
        ):
            raise ValueError("Alternative hypotheses must use canonical order")
        if self.evidence != tuple(
            sorted(self.evidence, key=lambda item: item.evidence_id)
        ):
            raise ValueError("Ownership evidence must use canonical order")
        if self.conflicts != tuple(
            sorted(self.conflicts, key=lambda item: item.conflict_id)
        ):
            raise ValueError("Ownership conflicts must use canonical order")
        if self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("Ownership reasons must use canonical order")
        if self.confidence != _score(self.confidence):
            raise ValueError("Ownership confidence must be normalized")
        if self.decision_state is OwnershipDecisionState.RESOLVED:
            if self.selected_hypothesis_id is None or self.review_required:
                raise ValueError("Resolved ownership requires one selected hypothesis")
        else:
            if not self.review_required or not self.review_reason or not self.review_item_id:
                raise ValueError("Uncertain ownership requires stable review linkage")
        if self.review_required is False and any(
            value is not None
            for value in (self.review_reason, self.review_item_id)
        ):
            raise ValueError("Resolved ownership must not carry review linkage")
        _validate_canonical(self.diagnostic_metadata_json, "diagnostic_metadata_json")
        expected = semantic_id(
            "ownership-group",
            self.schema_version,
            self.group_identity_payload(),
        )
        if self.ownership_group_id != expected:
            raise ValueError("ownership_group_id does not match group membership")

    def group_identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page_id,
            "source_region": self.source_region.identity_payload(),
            "candidate_ids": list(self.candidate_ids),
        }

    def decision_identity_payload(self) -> dict[str, object]:
        return {
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "selected_hypothesis_id": self.selected_hypothesis_id,
            "decision_state": self.decision_state.value,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "reasons": list(self.reasons),
            "conflicts": [item.to_dict() for item in self.conflicts],
            "alternative_hypothesis_ids": list(self.alternative_hypothesis_ids),
            "review_required": self.review_required,
            "review_reason": self.review_reason,
            "review_item_id": self.review_item_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ownership_group_id": self.ownership_group_id,
            "source_page_id": self.source_page_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_region": self.source_region.to_dict(),
            "candidate_ids": list(self.candidate_ids),
            **self.decision_identity_payload(),
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


@dataclass(frozen=True)
class DraftsmanOwnershipManifest:
    source_page: SourcePageRef
    transform: TransformRef
    candidate_manifest_id: str
    considered_candidate_ids: tuple[str, ...]
    groups: tuple[OwnershipGroup, ...]
    schema_version: str = DRAFTSMAN_OWNERSHIP_VERSION

    def __post_init__(self) -> None:
        if self.considered_candidate_ids != _sorted_ids(self.considered_candidate_ids):
            raise ValueError("Considered candidate IDs must be canonical")
        memberships = [candidate_id for group in self.groups for candidate_id in group.candidate_ids]
        if len(memberships) != len(set(memberships)):
            raise ValueError("A candidate cannot belong to multiple ownership groups")
        if tuple(sorted(memberships)) != self.considered_candidate_ids:
            raise ValueError("Ownership arbitration must preserve every candidate")
        if self.groups != tuple(
            sorted(self.groups, key=lambda item: item.ownership_group_id)
        ):
            raise ValueError("Ownership groups must use canonical order")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-ownership-manifest",
            self.schema_version,
            self.identity_payload(),
        )

    @property
    def resolved_count(self) -> int:
        return sum(
            item.decision_state is OwnershipDecisionState.RESOLVED
            for item in self.groups
        )

    @property
    def provisional_count(self) -> int:
        return sum(
            item.decision_state is OwnershipDecisionState.PROVISIONAL
            for item in self.groups
        )

    @property
    def unresolved_count(self) -> int:
        return sum(
            item.decision_state is OwnershipDecisionState.UNRESOLVED
            for item in self.groups
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page.source_page_id,
            "transform_id": self.transform.transform_id,
            "candidate_manifest_id": self.candidate_manifest_id,
            "considered_candidate_ids": list(self.considered_candidate_ids),
            "group_decisions": [
                {
                    "ownership_group_id": item.ownership_group_id,
                    **item.decision_identity_payload(),
                }
                for item in self.groups
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_page": self.source_page.to_dict(),
            "transform": self.transform.to_dict(),
            "candidate_manifest_id": self.candidate_manifest_id,
            "candidate_count": len(self.considered_candidate_ids),
            "group_count": len(self.groups),
            "resolved_count": self.resolved_count,
            "provisional_count": self.provisional_count,
            "unresolved_count": self.unresolved_count,
            "groups": [item.to_dict() for item in self.groups],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def ownership_manifest_sha256(manifest: DraftsmanOwnershipManifest) -> str:
    return sha256(manifest.canonical_bytes()).hexdigest()


class _UnionFind:
    def __init__(self, candidate_ids: Sequence[str]) -> None:
        self._parent = {candidate_id: candidate_id for candidate_id in candidate_ids}

    def find(self, candidate_id: str) -> str:
        parent = self._parent[candidate_id]
        while parent != self._parent[parent]:
            parent = self._parent[parent]
        current = candidate_id
        while self._parent[current] != parent:
            next_id = self._parent[current]
            self._parent[current] = parent
            current = next_id
        return parent

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        self._parent[second] = first


def _owner_for(candidate: DraftsmanCandidateRecord) -> OwnershipKind:
    return {
        CandidateKind.LINE_SEGMENT: OwnershipKind.STRUCTURE,
        CandidateKind.OCR_TEXT: OwnershipKind.TEXT,
        CandidateKind.LOGO: OwnershipKind.LOGO,
        CandidateKind.SIGNATURE: OwnershipKind.SIGNATURE,
        CandidateKind.CIRCLE: OwnershipKind.SYMBOL,
        CandidateKind.SYMBOL: OwnershipKind.SYMBOL,
        CandidateKind.STRUCTURAL_ROI: OwnershipKind.LAYOUT_CONTEXT,
        CandidateKind.TABLE_REGION: OwnershipKind.LAYOUT_CONTEXT,
    }[candidate.candidate_kind]


def _regions_overlap(left: SourceRegionRef, right: SourceRegionRef) -> bool:
    return not (
        left.x_max < right.x_min
        or right.x_max < left.x_min
        or left.y_max < right.y_min
        or right.y_max < left.y_min
    )


def _same_region(left: SourceRegionRef, right: SourceRegionRef) -> bool:
    return left.identity_payload() == right.identity_payload()


def _union_region(candidates: Sequence[DraftsmanCandidateRecord]) -> SourceRegionRef:
    return SourceRegionRef(
        min(item.source_region.x_min for item in candidates),
        min(item.source_region.y_min for item in candidates),
        max(item.source_region.x_max for item in candidates),
        max(item.source_region.y_max for item in candidates),
        candidates[0].source_region.coordinate_space,
    )


def _group_candidates(
    candidates: Sequence[DraftsmanCandidateRecord],
) -> tuple[tuple[DraftsmanCandidateRecord, ...], ...]:
    ordered = tuple(sorted(candidates, key=lambda item: item.stable_candidate_id))
    claims = tuple(item for item in ordered if item.candidate_kind not in _CONTEXT_KINDS)
    union_find = _UnionFind([item.stable_candidate_id for item in claims])
    by_owner: dict[OwnershipKind, list[DraftsmanCandidateRecord]] = {}
    for candidate in claims:
        by_owner.setdefault(_owner_for(candidate), []).append(candidate)
    owner_kinds = sorted(by_owner, key=lambda item: item.value)
    for left_index, left_owner in enumerate(owner_kinds):
        left_candidates = by_owner[left_owner]
        for right_owner in owner_kinds[left_index + 1 :]:
            for left in left_candidates:
                for right in by_owner[right_owner]:
                    if _regions_overlap(left.source_region, right.source_region):
                        union_find.union(
                            left.stable_candidate_id,
                            right.stable_candidate_id,
                        )
    for owner_candidates in by_owner.values():
        same_payload: dict[str, list[DraftsmanCandidateRecord]] = {}
        same_bbox: dict[str, list[DraftsmanCandidateRecord]] = {}
        for candidate in owner_candidates:
            same_payload.setdefault(candidate.candidate_payload_id, []).append(candidate)
            same_bbox.setdefault(
                canonical_json(candidate.source_region.identity_payload()),
                [],
            ).append(candidate)
        for competing in (*same_payload.values(), *same_bbox.values()):
            for candidate in competing[1:]:
                union_find.union(
                    competing[0].stable_candidate_id,
                    candidate.stable_candidate_id,
                )
    grouped: dict[str, list[DraftsmanCandidateRecord]] = {}
    for candidate in claims:
        grouped.setdefault(union_find.find(candidate.stable_candidate_id), []).append(candidate)
    groups = [
        tuple(sorted(group, key=lambda item: item.stable_candidate_id))
        for group in grouped.values()
    ]
    groups.extend((candidate,) for candidate in ordered if candidate.candidate_kind in _CONTEXT_KINDS)
    return tuple(sorted(groups, key=lambda group: group[0].stable_candidate_id))


def _line_length(candidate: DraftsmanCandidateRecord) -> float:
    payload = candidate.payload
    if not isinstance(payload, LineCandidatePayload):
        return 0.0
    return hypot(payload.end[0] - payload.start[0], payload.end[1] - payload.start[1])


def _candidate_score(candidate: DraftsmanCandidateRecord) -> float:
    payload = candidate.payload
    if isinstance(payload, LineCandidatePayload):
        return _score(
            0.6 * candidate.confidence
            + 0.4 * payload.classification_confidence
        )
    return _score(candidate.confidence)


def _context_candidates(
    group: Sequence[DraftsmanCandidateRecord],
    contexts: Sequence[DraftsmanCandidateRecord],
) -> tuple[DraftsmanCandidateRecord, ...]:
    region = _union_region(group)
    return tuple(
        context
        for context in contexts
        if _regions_overlap(region, context.source_region)
    )


def _evidence_for_group(
    group: Sequence[DraftsmanCandidateRecord],
    contexts: Sequence[DraftsmanCandidateRecord],
) -> tuple[tuple[OwnershipEvidence, ...], dict[OwnershipKind, float], bool]:
    evidence: list[OwnershipEvidence] = []
    scores: dict[OwnershipKind, float] = {}
    grouped_by_owner: dict[OwnershipKind, list[DraftsmanCandidateRecord]] = {}
    for candidate in group:
        grouped_by_owner.setdefault(_owner_for(candidate), []).append(candidate)
    for owner, owner_candidates in grouped_by_owner.items():
        base = max(_candidate_score(item) for item in owner_candidates)
        scores[owner] = base
        evidence.append(
            OwnershipEvidence.create(
                reason_code="DETECTOR_KIND_AND_CONFIDENCE",
                candidate_ids=[item.stable_candidate_id for item in owner_candidates],
                weight=base,
                details={
                    "ownership_kind": owner.value,
                    "candidate_kinds": sorted(
                        {item.candidate_kind.value for item in owner_candidates}
                    ),
                    "maximum_confidence": base,
                },
            )
        )

    line_candidates = [
        item
        for item in group
        if item.candidate_kind is CandidateKind.LINE_SEGMENT
    ]
    ambiguous_short_stroke = False
    if line_candidates:
        longest_ratio = max(
            _line_length(item)
            / max(1.0, float(getattr(item.payload, "width", 1.0)))
            for item in line_candidates
        )
        line_ids = [item.stable_candidate_id for item in line_candidates]
        if longest_ratio >= 12.0:
            scores[OwnershipKind.STRUCTURE] = _score(
                scores[OwnershipKind.STRUCTURE] + 0.12
            )
            evidence.append(
                OwnershipEvidence.create(
                    reason_code="LONG_LINEAR_CONTINUITY_SUPPORT",
                    candidate_ids=line_ids,
                    weight=0.12,
                    details={"maximum_length_width_ratio": round(longest_ratio, 6)},
                )
            )
        elif longest_ratio <= 4.0 and scores[OwnershipKind.STRUCTURE] < 0.8:
            ambiguous_short_stroke = True
            graphic_score = _score(
                max(0.35, scores[OwnershipKind.STRUCTURE] + 0.02)
            )
            scores[OwnershipKind.GRAPHIC] = graphic_score
            evidence.append(
                OwnershipEvidence.create(
                    reason_code="AMBIGUOUS_SHORT_STROKE",
                    candidate_ids=line_ids,
                    weight=0.0,
                    details={"maximum_length_width_ratio": round(longest_ratio, 6)},
                )
            )

    text_candidates = [
        item
        for item in group
        if item.candidate_kind is CandidateKind.OCR_TEXT
    ]
    if text_candidates:
        text_ids = [item.stable_candidate_id for item in text_candidates]
        if any(
            isinstance(item.payload, TextCandidatePayload)
            and item.payload.source_quad is not None
            for item in text_candidates
        ):
            scores[OwnershipKind.TEXT] = _score(scores[OwnershipKind.TEXT] + 0.06)
            evidence.append(
                OwnershipEvidence.create(
                    reason_code="OCR_QUAD_ORIENTATION_SUPPORT",
                    candidate_ids=text_ids,
                    weight=0.06,
                    details={"bbox_is_source_evidence_only": True},
                )
            )
        if any(
            isinstance(item.payload, TextCandidatePayload)
            and item.payload.replacement_safe
            for item in text_candidates
        ):
            scores[OwnershipKind.TEXT] = _score(scores[OwnershipKind.TEXT] + 0.04)
            evidence.append(
                OwnershipEvidence.create(
                    reason_code="EXISTING_TEXT_REPLACEMENT_SAFETY",
                    candidate_ids=text_ids,
                    weight=0.04,
                )
            )

    context_ids = [item.stable_candidate_id for item in contexts]
    structure_ids = [
        item.stable_candidate_id
        for item in group
        if _owner_for(item) is OwnershipKind.STRUCTURE
    ]
    text_ids = [
        item.stable_candidate_id
        for item in group
        if _owner_for(item) is OwnershipKind.TEXT
    ]
    structural_contexts = [
        item
        for item in contexts
        if item.candidate_kind is CandidateKind.STRUCTURAL_ROI
    ]
    table_contexts = [
        item
        for item in contexts
        if item.candidate_kind is CandidateKind.TABLE_REGION
    ]
    if structure_ids and structural_contexts:
        scores[OwnershipKind.STRUCTURE] = _score(
            scores[OwnershipKind.STRUCTURE] + 0.12
        )
        evidence.append(
            OwnershipEvidence.create(
                reason_code="STRUCTURAL_ROI_SUPPORT",
                candidate_ids=(*structure_ids, *context_ids),
                weight=0.12,
            )
        )
    if table_contexts and structure_ids:
        scores[OwnershipKind.STRUCTURE] = _score(
            scores[OwnershipKind.STRUCTURE] + 0.08
        )
        evidence.append(
            OwnershipEvidence.create(
                reason_code="TABLE_REGION_STRUCTURE_SUPPORT",
                candidate_ids=(*structure_ids, *context_ids),
                weight=0.08,
            )
        )
    if table_contexts and text_ids:
        scores[OwnershipKind.TEXT] = _score(scores[OwnershipKind.TEXT] + 0.06)
        evidence.append(
            OwnershipEvidence.create(
                reason_code="TABLE_REGION_TEXT_SUPPORT",
                candidate_ids=(*text_ids, *context_ids),
                weight=0.06,
                details={"placement_not_decided": True},
            )
        )
    restored_lines = [
        item
        for item in line_candidates
        if isinstance(item.payload, LineCandidatePayload)
        and "text_mask_restoration" in item.payload.detector_history
    ]
    if restored_lines:
        scores[OwnershipKind.STRUCTURE] = _score(
            scores[OwnershipKind.STRUCTURE] + 0.05
        )
        evidence.append(
            OwnershipEvidence.create(
                reason_code="EXISTING_RC3_PROVENANCE_SUPPORT",
                candidate_ids=[item.stable_candidate_id for item in restored_lines],
                weight=0.05,
                details={"state_remains": "RECONSTRUCTED"},
            )
        )
    return (
        tuple(sorted(evidence, key=lambda item: item.evidence_id)),
        scores,
        ambiguous_short_stroke,
    )


def _build_group(
    group: Sequence[DraftsmanCandidateRecord],
    *,
    contexts: Sequence[DraftsmanCandidateRecord],
    diagnostic_metadata: object | None,
) -> OwnershipGroup:
    evidence, scores, ambiguous_short_stroke = _evidence_for_group(group, contexts)
    evidence_by_owner: dict[OwnershipKind, list[str]] = {}
    group_candidate_ids = {item.stable_candidate_id for item in group}
    for item in evidence:
        if item.reason_code == "DETECTOR_KIND_AND_CONFIDENCE":
            details = json.loads(item.details_json)
            supported_owners = {
                OwnershipKind(str(details["ownership_kind"]))
            }
        elif item.reason_code in {
            "LONG_LINEAR_CONTINUITY_SUPPORT",
            "STRUCTURAL_ROI_SUPPORT",
            "TABLE_REGION_STRUCTURE_SUPPORT",
            "EXISTING_RC3_PROVENANCE_SUPPORT",
        }:
            supported_owners = {OwnershipKind.STRUCTURE}
        elif item.reason_code in {
            "OCR_QUAD_ORIENTATION_SUPPORT",
            "EXISTING_TEXT_REPLACEMENT_SAFETY",
            "TABLE_REGION_TEXT_SUPPORT",
        }:
            supported_owners = {OwnershipKind.TEXT}
        elif item.reason_code == "AMBIGUOUS_SHORT_STROKE":
            supported_owners = {
                OwnershipKind.STRUCTURE,
                OwnershipKind.GRAPHIC,
            }
        else:
            supported_owners = set()
        for owner in supported_owners.intersection(scores):
            evidence_by_owner.setdefault(owner, []).append(item.evidence_id)
    hypotheses = tuple(
        sorted(
            (
                OwnershipHypothesis.create(
                    ownership_kind=owner,
                    supporting_candidate_ids=(
                        [
                            item.stable_candidate_id
                            for item in group
                            if _owner_for(item) is owner
                        ]
                        if owner is not OwnershipKind.GRAPHIC
                        else [
                            item.stable_candidate_id
                            for item in group
                            if item.candidate_kind is CandidateKind.LINE_SEGMENT
                        ]
                    ),
                    evidence_ids=evidence_by_owner.get(owner, ()),
                    score=value,
                )
                for owner, value in scores.items()
            ),
            key=lambda item: item.hypothesis_id,
        )
    )
    ranked = sorted(
        hypotheses,
        key=lambda item: (-item.score, item.ownership_kind.value),
    )
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = top.score if second is None else _score(top.score - second.score)
    tied = second is not None and top.score == second.score
    if top.score < 0.35:
        decision_state = OwnershipDecisionState.UNRESOLVED
        selected = None
        review_reason = "OWNERSHIP_UNRESOLVED"
    elif second is None and top.score >= 0.6:
        decision_state = OwnershipDecisionState.RESOLVED
        selected = top.hypothesis_id
        review_reason = None
    elif (
        second is not None
        and top.score >= 0.8
        and margin >= 0.25
        and not tied
    ):
        decision_state = OwnershipDecisionState.RESOLVED
        selected = top.hypothesis_id
        review_reason = None
    else:
        decision_state = OwnershipDecisionState.PROVISIONAL
        selected = (
            top.hypothesis_id
            if not tied and (second is None or margin >= 0.05)
            else None
        )
        review_reason = (
            "AMBIGUOUS_SHORT_STROKE"
            if ambiguous_short_stroke
            else "OWNERSHIP_COMPETITION"
        )

    conflicts: list[OwnershipConflict] = []
    owner_kinds = {_owner_for(item) for item in group}
    if len(owner_kinds) > 1:
        conflicts.append(
            OwnershipConflict.create(
                conflict_code="COMPETING_OWNER_CLAIMS",
                candidate_ids=sorted(group_candidate_ids),
                details={"ownership_kinds": sorted(item.value for item in owner_kinds)},
            )
        )
    if len(group) > 1 and len(owner_kinds) == 1:
        conflicts.append(
            OwnershipConflict.create(
                conflict_code="DUPLICATE_OR_COMPETING_CANDIDATES",
                candidate_ids=sorted(group_candidate_ids),
                details={"candidate_count": len(group)},
            )
        )
    if ambiguous_short_stroke:
        conflicts.append(
            OwnershipConflict.create(
                conflict_code="AMBIGUOUS_SHORT_STROKE",
                candidate_ids=[
                    item.stable_candidate_id
                    for item in group
                    if item.candidate_kind is CandidateKind.LINE_SEGMENT
                ],
            )
        )
    conflicts_tuple = tuple(sorted(conflicts, key=lambda item: item.conflict_id))
    reasons = tuple(
        sorted(
            {
                *(item.reason_code for item in evidence),
                *(item.conflict_code for item in conflicts_tuple),
            }
        )
    )
    candidate_ids = _sorted_ids([item.stable_candidate_id for item in group])
    region = _union_region(group)
    page = group[0]
    group_identity = {
        "source_page_id": page.source_page_id,
        "source_region": region.identity_payload(),
        "candidate_ids": list(candidate_ids),
    }
    group_id = semantic_id(
        "ownership-group",
        DRAFTSMAN_OWNERSHIP_VERSION,
        group_identity,
    )
    review_required = decision_state is not OwnershipDecisionState.RESOLVED
    review_item_id = (
        semantic_id(
            "ownership-review-item",
            DRAFTSMAN_OWNERSHIP_VERSION,
            {
                "ownership_group_id": group_id,
                "review_reason": review_reason,
            },
        )
        if review_required
        else None
    )
    selected_id = selected
    alternative_ids = tuple(
        sorted(
            item.hypothesis_id
            for item in hypotheses
            if item.hypothesis_id != selected_id
        )
    )
    return OwnershipGroup(
        ownership_group_id=group_id,
        source_page_id=page.source_page_id,
        source_document_id=page.source_document_id,
        source_page=page.source_page,
        source_region=region,
        candidate_ids=candidate_ids,
        hypotheses=hypotheses,
        selected_hypothesis_id=selected_id,
        decision_state=decision_state,
        confidence=top.score,
        evidence=evidence,
        reasons=reasons,
        conflicts=conflicts_tuple,
        alternative_hypothesis_ids=alternative_ids,
        review_required=review_required,
        review_reason=review_reason,
        review_item_id=review_item_id,
        diagnostic_metadata_json=canonical_json(diagnostic_metadata or {}),
    )


def arbitrate_candidate_ownership(
    manifest: DraftsmanCandidateManifest,
    *,
    diagnostic_metadata: object | None = None,
) -> DraftsmanOwnershipManifest:
    """Explain ownership hypotheses without mutating or routing candidates."""

    candidate_bytes_before = manifest.canonical_bytes()
    contexts = tuple(
        item
        for item in manifest.candidates
        if item.candidate_kind in _CONTEXT_KINDS
    )
    groups = []
    for candidate_group in _group_candidates(manifest.candidates):
        relevant_contexts = (
            ()
            if candidate_group[0].candidate_kind in _CONTEXT_KINDS
            else _context_candidates(candidate_group, contexts)
        )
        groups.append(
            _build_group(
                candidate_group,
                contexts=relevant_contexts,
                diagnostic_metadata=diagnostic_metadata,
            )
        )
    result = DraftsmanOwnershipManifest(
        source_page=manifest.source_page,
        transform=manifest.transform,
        candidate_manifest_id=manifest.manifest_id,
        considered_candidate_ids=_sorted_ids(
            [item.stable_candidate_id for item in manifest.candidates]
        ),
        groups=tuple(sorted(groups, key=lambda item: item.ownership_group_id)),
    )
    if manifest.canonical_bytes() != candidate_bytes_before:
        raise AssertionError("Ownership arbitration mutated the candidate manifest")
    return result


@dataclass(frozen=True)
class OwnershipDiscrepancy:
    discrepancy_id: str
    ownership_group_id: str
    category: DiscrepancyCategory
    production_routes: tuple[tuple[str, str], ...]
    shadow_decision_state: OwnershipDecisionState
    shadow_owner: OwnershipKind | None
    reasons: tuple[str, ...]
    schema_version: str = DRAFTSMAN_DISCREPANCY_VERSION

    def __post_init__(self) -> None:
        if self.production_routes != tuple(sorted(set(self.production_routes))):
            raise ValueError("Production routes must use canonical order")
        if self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("Discrepancy reasons must use canonical order")
        expected = semantic_id(
            "ownership-discrepancy",
            self.schema_version,
            self.identity_payload(),
        )
        if self.discrepancy_id != expected:
            raise ValueError("discrepancy_id does not match discrepancy")

    def identity_payload(self) -> dict[str, object]:
        return {
            "ownership_group_id": self.ownership_group_id,
            "category": self.category.value,
            "production_routes": [list(item) for item in self.production_routes],
            "shadow_decision_state": self.shadow_decision_state.value,
            "shadow_owner": None if self.shadow_owner is None else self.shadow_owner.value,
            "reasons": list(self.reasons),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "discrepancy_id": self.discrepancy_id,
            **self.identity_payload(),
        }


@dataclass(frozen=True)
class OwnershipDiscrepancyReport:
    ownership_manifest_id: str
    records: tuple[OwnershipDiscrepancy, ...]
    schema_version: str = DRAFTSMAN_DISCREPANCY_VERSION

    @property
    def discrepancy_count(self) -> int:
        return sum(item.category is not DiscrepancyCategory.SAME for item in self.records)

    @property
    def category_counts(self) -> dict[str, int]:
        return {
            category.value: sum(item.category is category for item in self.records)
            for category in DiscrepancyCategory
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ownership_manifest_id": self.ownership_manifest_id,
            "group_count": len(self.records),
            "discrepancy_count": self.discrepancy_count,
            "category_counts": self.category_counts,
            "records": [item.to_dict() for item in self.records],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _selected_owner(group: OwnershipGroup) -> OwnershipKind | None:
    return next(
        (
            item.ownership_kind
            for item in group.hypotheses
            if item.hypothesis_id == group.selected_hypothesis_id
        ),
        None,
    )


def build_ownership_discrepancy_report(
    ownership: DraftsmanOwnershipManifest,
    production_routes: Mapping[str, str],
) -> OwnershipDiscrepancyReport:
    """Compare current routing observations without treating them as truth."""

    records: list[OwnershipDiscrepancy] = []
    destructive = {"REMOVED", "DROPPED", "MASKED_OUT", "UNOBSERVED"}
    generic = {"GRAPHIC", "RESIDUAL", "OUTLINE", "FALLBACK"}
    for group in ownership.groups:
        routes = tuple(
            sorted(
                (
                    candidate_id,
                    str(production_routes.get(candidate_id, "UNOBSERVED")).upper(),
                )
                for candidate_id in group.candidate_ids
            )
        )
        route_values = {value for _candidate_id, value in routes}
        shadow_owner = _selected_owner(group)
        if group.decision_state is OwnershipDecisionState.UNRESOLVED:
            category = DiscrepancyCategory.SHADOW_UNRESOLVED
        elif group.decision_state is OwnershipDecisionState.PROVISIONAL:
            category = DiscrepancyCategory.SHADOW_PROVISIONAL
        elif route_values.intersection(destructive):
            category = DiscrepancyCategory.PRODUCTION_DESTRUCTIVE_CONFLICT
        elif shadow_owner is not None and route_values == {shadow_owner.value}:
            category = DiscrepancyCategory.SAME
        elif route_values.intersection(generic) and shadow_owner is not OwnershipKind.GRAPHIC:
            category = DiscrepancyCategory.SHADOW_MORE_SPECIFIC
        elif shadow_owner is OwnershipKind.GRAPHIC:
            category = DiscrepancyCategory.SHADOW_MORE_CONSERVATIVE
        else:
            category = DiscrepancyCategory.SHADOW_MORE_SPECIFIC
        reasons = tuple(
            sorted(
                {
                    f"PRODUCTION:{value}" for value in route_values
                }
                | {f"SHADOW:{item}" for item in group.reasons}
            )
        )
        identity = {
            "ownership_group_id": group.ownership_group_id,
            "category": category.value,
            "production_routes": [list(item) for item in routes],
            "shadow_decision_state": group.decision_state.value,
            "shadow_owner": None if shadow_owner is None else shadow_owner.value,
            "reasons": list(reasons),
        }
        records.append(
            OwnershipDiscrepancy(
                discrepancy_id=semantic_id(
                    "ownership-discrepancy",
                    DRAFTSMAN_DISCREPANCY_VERSION,
                    identity,
                ),
                ownership_group_id=group.ownership_group_id,
                category=category,
                production_routes=routes,
                shadow_decision_state=group.decision_state,
                shadow_owner=shadow_owner,
                reasons=reasons,
            )
        )
    return OwnershipDiscrepancyReport(
        ownership_manifest_id=ownership.manifest_id,
        records=tuple(sorted(records, key=lambda item: item.discrepancy_id)),
    )


def candidate_contract_parent_version() -> str:
    return DRAFTSMAN_CANDIDATE_VERSION
