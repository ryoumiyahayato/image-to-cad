"""Non-exclusive ownership relations and discrepancy adjudication for M2-S2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Mapping, Sequence

from .draftsman_candidate import (
    CandidateKind,
    DraftsmanCandidateManifest,
    DraftsmanCandidateRecord,
    LineCandidatePayload,
    TextCandidatePayload,
)
from .draftsman_contract import (
    SourcePageRef,
    SourceRegionRef,
    canonical_json,
    canonical_json_bytes,
    semantic_id,
)
from .draftsman_ownership import (
    DRAFTSMAN_OWNERSHIP_VERSION,
    DiscrepancyCategory,
    DraftsmanOwnershipManifest,
    OwnershipGroup,
    build_ownership_discrepancy_report,
)


DRAFTSMAN_OWNERSHIP_RELATION_VERSION = "draftsman-ownership-relation-v1"


class OwnershipSemanticRelation(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    COEXIST = "COEXIST"
    OCCLUDED_BACKGROUND = "OCCLUDED_BACKGROUND"
    SAME_ENTITY = "SAME_ENTITY"
    DUPLICATE_HYPOTHESIS = "DUPLICATE_HYPOTHESIS"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


class SourceEvidenceRelation(str, Enum):
    SINGLE_CANDIDATE = "SINGLE_CANDIDATE"
    SHARED_FOOTPRINT = "SHARED_FOOTPRINT"
    OVERLAPPING_FOOTPRINTS = "OVERLAPPING_FOOTPRINTS"
    DISTINCT_FOOTPRINTS = "DISTINCT_FOOTPRINTS"
    UNKNOWN = "UNKNOWN"


class DiscrepancyAdjudicationCategory(str, Enum):
    TRUE_DESTRUCTIVE_SUPPRESSION = "TRUE_DESTRUCTIVE_SUPPRESSION"
    LEGITIMATE_EXCLUSIVE = "LEGITIMATE_EXCLUSIVE"
    COEXIST = "COEXIST"
    OCCLUDED_BACKGROUND = "OCCLUDED_BACKGROUND"
    DUPLICATE_HYPOTHESIS = "DUPLICATE_HYPOTHESIS"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


_DESTRUCTIVE_ROUTES = {"REMOVED", "DROPPED", "MASKED_OUT", "UNOBSERVED"}
_EXPLICIT_SUPPRESSION_ROUTES = {"DROPPED", "MASKED_OUT"}


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _confidence(value: float) -> float:
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError("Relation confidence must be finite")
    return round(max(0.0, min(1.0, normalized)), 6)


def _sorted_ids(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_required(value, "identity") for value in values}))


def _validate_canonical(value: str, name: str) -> None:
    if canonical_json(json.loads(value)) != value:
        raise ValueError(f"{name} must be canonical JSON")


@dataclass(frozen=True)
class OwnershipRelationAdjudication:
    relation_id: str
    original_discrepancy_id: str
    ownership_group_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    candidate_ids: tuple[str, ...]
    hypothesis_ids: tuple[str, ...]
    source_evidence_relation: SourceEvidenceRelation
    candidate_interpretations: tuple[str, ...]
    related_final_candidate_ids: tuple[str, ...]
    final_cad_relation: OwnershipSemanticRelation
    adjudication_category: DiscrepancyAdjudicationCategory
    confidence: float
    reasons: tuple[str, ...]
    production_routes: tuple[tuple[str, str], ...]
    review_required: bool
    review_reason: str | None
    review_item_id: str | None
    diagnostic_metadata_json: str = "{}"
    schema_version: str = DRAFTSMAN_OWNERSHIP_RELATION_VERSION

    def __post_init__(self) -> None:
        _required(self.original_discrepancy_id, "original_discrepancy_id")
        _required(self.ownership_group_id, "ownership_group_id")
        _required(self.source_document_id, "source_document_id")
        if self.source_page <= 0:
            raise ValueError("source_page must be positive")
        if not self.candidate_ids:
            raise ValueError("Relation adjudication requires candidates")
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("Relation candidate IDs must use canonical order")
        if self.hypothesis_ids != tuple(sorted(set(self.hypothesis_ids))):
            raise ValueError("Relation hypothesis IDs must use canonical order")
        if self.candidate_interpretations != tuple(
            sorted(set(self.candidate_interpretations))
        ):
            raise ValueError("Candidate interpretations must use canonical order")
        if self.related_final_candidate_ids != _sorted_ids(
            self.related_final_candidate_ids
        ):
            raise ValueError("Related final candidate IDs must use canonical order")
        if self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("Relation reasons must use canonical order")
        if self.production_routes != tuple(sorted(set(self.production_routes))):
            raise ValueError("Production routes must use canonical order")
        if self.confidence != _confidence(self.confidence):
            raise ValueError("Relation confidence must be normalized")
        if self.review_required:
            if not self.review_reason or not self.review_item_id:
                raise ValueError("Review-required relations need stable linkage")
        elif self.review_reason is not None or self.review_item_id is not None:
            raise ValueError("Accepted relation must not carry review linkage")
        _validate_canonical(self.diagnostic_metadata_json, "diagnostic_metadata_json")
        expected = semantic_id(
            "ownership-relation-adjudication",
            self.schema_version,
            self.identity_payload(),
        )
        if self.relation_id != expected:
            raise ValueError("relation_id does not match relation semantics")

    def identity_payload(self) -> dict[str, object]:
        return {
            "original_discrepancy_id": self.original_discrepancy_id,
            "ownership_group_id": self.ownership_group_id,
            "source_region": self.source_region.identity_payload(),
            "candidate_ids": list(self.candidate_ids),
            "hypothesis_ids": list(self.hypothesis_ids),
            "source_evidence_relation": self.source_evidence_relation.value,
            "candidate_interpretations": list(self.candidate_interpretations),
            "related_final_candidate_ids": list(self.related_final_candidate_ids),
            "final_cad_relation": self.final_cad_relation.value,
            "adjudication_category": self.adjudication_category.value,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "production_routes": [list(item) for item in self.production_routes],
            "review_required": self.review_required,
            "review_reason": self.review_reason,
            "review_item_id": self.review_item_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "relation_id": self.relation_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            **self.identity_payload(),
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


@dataclass(frozen=True)
class OwnershipDiscrepancyLedger:
    source_page: SourcePageRef
    candidate_manifest_id: str
    ownership_manifest_id: str
    final_candidate_manifest_id: str | None
    original_discrepancy_ids: tuple[str, ...]
    entries: tuple[OwnershipRelationAdjudication, ...]
    count_unit: str = "ownership-group"
    schema_version: str = DRAFTSMAN_OWNERSHIP_RELATION_VERSION

    def __post_init__(self) -> None:
        if self.count_unit != "ownership-group":
            raise ValueError("M2 discrepancy ledger count unit is ownership-group")
        if self.original_discrepancy_ids != tuple(
            sorted(set(self.original_discrepancy_ids))
        ):
            raise ValueError("Original discrepancy IDs must use canonical order")
        if self.entries != tuple(
            sorted(self.entries, key=lambda item: item.relation_id)
        ):
            raise ValueError("Discrepancy ledger entries must use canonical order")
        represented = tuple(
            sorted(item.original_discrepancy_id for item in self.entries)
        )
        if represented != self.original_discrepancy_ids:
            raise ValueError("Every original discrepancy must be adjudicated once")
        group_ids = [item.ownership_group_id for item in self.entries]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("A discrepancy group cannot be adjudicated twice")

    @property
    def ledger_id(self) -> str:
        return semantic_id(
            "ownership-discrepancy-ledger",
            self.schema_version,
            self.identity_payload(),
        )

    @property
    def original_discrepancy_count(self) -> int:
        return len(self.original_discrepancy_ids)

    @property
    def category_counts(self) -> dict[str, int]:
        return {
            category.value: sum(
                item.adjudication_category is category for item in self.entries
            )
            for category in DiscrepancyAdjudicationCategory
        }

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page.source_page_id,
            "candidate_manifest_id": self.candidate_manifest_id,
            "ownership_manifest_id": self.ownership_manifest_id,
            "final_candidate_manifest_id": self.final_candidate_manifest_id,
            "count_unit": self.count_unit,
            "original_discrepancy_ids": list(self.original_discrepancy_ids),
            "relation_ids": [item.relation_id for item in self.entries],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ledger_id": self.ledger_id,
            "source_page": self.source_page.to_dict(),
            "candidate_manifest_id": self.candidate_manifest_id,
            "ownership_manifest_id": self.ownership_manifest_id,
            "final_candidate_manifest_id": self.final_candidate_manifest_id,
            "count_unit": self.count_unit,
            "original_discrepancy_count": self.original_discrepancy_count,
            "category_counts": self.category_counts,
            "entries": [item.to_dict() for item in self.entries],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def discrepancy_ledger_sha256(ledger: OwnershipDiscrepancyLedger) -> str:
    return sha256(ledger.canonical_bytes()).hexdigest()


def _regions_overlap(left: SourceRegionRef, right: SourceRegionRef) -> bool:
    return not (
        left.x_max < right.x_min
        or right.x_max < left.x_min
        or left.y_max < right.y_min
        or right.y_max < left.y_min
    )


def _same_region(left: SourceRegionRef, right: SourceRegionRef) -> bool:
    return left.identity_payload() == right.identity_payload()


def _source_relation(
    candidates: Sequence[DraftsmanCandidateRecord],
) -> SourceEvidenceRelation:
    if len(candidates) == 1:
        return SourceEvidenceRelation.SINGLE_CANDIDATE
    if any(
        left.candidate_payload_id == right.candidate_payload_id
        or _same_region(left.source_region, right.source_region)
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
    ):
        return SourceEvidenceRelation.SHARED_FOOTPRINT
    if any(
        _regions_overlap(left.source_region, right.source_region)
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
    ):
        return SourceEvidenceRelation.OVERLAPPING_FOOTPRINTS
    return SourceEvidenceRelation.DISTINCT_FOOTPRINTS


def _line_span(
    line: DraftsmanCandidateRecord,
) -> tuple[str, float, float, float] | None:
    payload = line.payload
    if not isinstance(payload, LineCandidatePayload):
        return None
    dx = abs(payload.end[0] - payload.start[0])
    dy = abs(payload.end[1] - payload.start[1])
    if dy <= max(1.0, dx * 0.12):
        return (
            "horizontal",
            min(payload.start[0], payload.end[0]),
            max(payload.start[0], payload.end[0]),
            (payload.start[1] + payload.end[1]) * 0.5,
        )
    if dx <= max(1.0, dy * 0.12):
        return (
            "vertical",
            min(payload.start[1], payload.end[1]),
            max(payload.start[1], payload.end[1]),
            (payload.start[0] + payload.end[0]) * 0.5,
        )
    return None


def _interval_overlap(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
) -> float:
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _line_lineage_match(
    candidate: DraftsmanCandidateRecord,
    final_candidate: DraftsmanCandidateRecord,
) -> bool:
    candidate_span = _line_span(candidate)
    final_span = _line_span(final_candidate)
    if candidate_span is None or final_span is None:
        return False
    if candidate_span[0] != final_span[0]:
        return False
    candidate_length = candidate_span[2] - candidate_span[1]
    final_length = final_span[2] - final_span[1]
    overlap = _interval_overlap(
        candidate_span[1],
        candidate_span[2],
        final_span[1],
        final_span[2],
    )
    candidate_payload = candidate.payload
    final_payload = final_candidate.payload
    if not isinstance(candidate_payload, LineCandidatePayload) or not isinstance(
        final_payload,
        LineCandidatePayload,
    ):
        return False
    cross_tolerance = max(
        2.0,
        candidate_payload.width * 1.5,
        final_payload.width * 1.5,
    )
    return bool(
        abs(candidate_span[3] - final_span[3]) <= cross_tolerance
        and overlap / max(1.0, min(candidate_length, final_length)) >= 0.75
    )


def _text_lineage_match(
    candidate: DraftsmanCandidateRecord,
    final_candidate: DraftsmanCandidateRecord,
) -> bool:
    candidate_payload = candidate.payload
    final_payload = final_candidate.payload
    if not isinstance(candidate_payload, TextCandidatePayload) or not isinstance(
        final_payload,
        TextCandidatePayload,
    ):
        return False
    candidate_text = "".join(candidate_payload.raw_recognized_text.split()).casefold()
    final_text = "".join(final_payload.raw_recognized_text.split()).casefold()
    if not candidate_text or candidate_text != final_text:
        return False
    left = candidate.source_region
    right = final_candidate.source_region
    overlap_width = _interval_overlap(left.x_min, left.x_max, right.x_min, right.x_max)
    overlap_height = _interval_overlap(left.y_min, left.y_max, right.y_min, right.y_max)
    overlap_area = overlap_width * overlap_height
    left_area = max(1.0, (left.x_max - left.x_min) * (left.y_max - left.y_min))
    right_area = max(1.0, (right.x_max - right.x_min) * (right.y_max - right.y_min))
    return overlap_area / min(left_area, right_area) >= 0.5


def _related_final_candidates(
    candidate: DraftsmanCandidateRecord,
    final_candidates: Sequence[DraftsmanCandidateRecord],
) -> tuple[str, ...]:
    related = []
    for final_candidate in final_candidates:
        if candidate.candidate_kind is not final_candidate.candidate_kind:
            continue
        if candidate.candidate_payload_id == final_candidate.candidate_payload_id:
            related.append(final_candidate.stable_candidate_id)
            continue
        if candidate.candidate_kind is CandidateKind.LINE_SEGMENT and _line_lineage_match(
            candidate,
            final_candidate,
        ):
            related.append(final_candidate.stable_candidate_id)
        elif candidate.candidate_kind is CandidateKind.OCR_TEXT and _text_lineage_match(
            candidate,
            final_candidate,
        ):
            related.append(final_candidate.stable_candidate_id)
    return _sorted_ids(related)


def _line_region_relation(
    line: DraftsmanCandidateRecord,
    foreground: DraftsmanCandidateRecord,
    *,
    allow_exclusive_stroke: bool,
) -> tuple[OwnershipSemanticRelation, tuple[str, ...], float]:
    span = _line_span(line)
    if span is None:
        return (
            OwnershipSemanticRelation.PROVISIONAL,
            ("NON_AXIS_LINE_REGION_RELATION_UNCERTAIN",),
            0.45,
        )
    orientation, start, end, cross_axis = span
    region = foreground.source_region
    if orientation == "horizontal":
        region_start, region_end = region.x_min, region.x_max
        cross_start, cross_end = region.y_min, region.y_max
    else:
        region_start, region_end = region.y_min, region.y_max
        cross_start, cross_end = region.x_min, region.x_max
    extent = max(1.0, region_end - region_start)
    cross_extent = max(1.0, cross_end - cross_start)
    edge_band = max(1.0, cross_extent * 0.15)
    outside_margin = max(2.0, extent * 0.2)
    at_edge = (
        abs(cross_axis - cross_start) <= edge_band
        or abs(cross_axis - cross_end) <= edge_band
    )
    crosses_interior = cross_start + edge_band < cross_axis < cross_end - edge_band
    extends_both_sides = (
        start <= region_start - outside_margin
        and end >= region_end + outside_margin
    )
    contained = (
        start >= region_start - edge_band
        and end <= region_end + edge_band
    )
    line_length = end - start
    if at_edge:
        return (
            OwnershipSemanticRelation.COEXIST,
            ("LINE_TOUCHES_FOREGROUND_REGION_EDGE",),
            0.9,
        )
    if crosses_interior and extends_both_sides:
        return (
            OwnershipSemanticRelation.OCCLUDED_BACKGROUND,
            ("CONTINUOUS_LINE_EXTENDS_ACROSS_FOREGROUND_REGION",),
            0.9,
        )
    if (
        allow_exclusive_stroke
        and crosses_interior
        and contained
        and line_length <= max(12.0, extent * 0.75)
    ):
        return (
            OwnershipSemanticRelation.EXCLUSIVE,
            ("SHORT_STROKE_CONTAINED_IN_TEXT_FOOTPRINT",),
            0.85,
        )
    return (
        OwnershipSemanticRelation.PROVISIONAL,
        ("BBOX_OVERLAP_WITHOUT_DECISIVE_STROKE_RELATION",),
        0.5,
    )


def _same_owner_relation(
    candidates: Sequence[DraftsmanCandidateRecord],
) -> tuple[OwnershipSemanticRelation, tuple[str, ...], float] | None:
    if len(candidates) < 2:
        return None
    if all(
        item.candidate_payload_id == candidates[0].candidate_payload_id
        for item in candidates[1:]
    ):
        return (
            OwnershipSemanticRelation.SAME_ENTITY,
            ("IDENTICAL_TYPED_PAYLOAD_WITH_COUNTED_OCCURRENCES",),
            1.0,
        )
    kinds = {item.candidate_kind for item in candidates}
    if len(kinds) == 1 and all(
        _same_region(item.source_region, candidates[0].source_region)
        for item in candidates[1:]
    ):
        return (
            OwnershipSemanticRelation.DUPLICATE_HYPOTHESIS,
            ("SAME_KIND_AND_SOURCE_FOOTPRINT_DIFFERENT_PAYLOAD",),
            0.95,
        )
    return None


def _cross_owner_relation(
    group: OwnershipGroup,
    candidates: Sequence[DraftsmanCandidateRecord],
) -> tuple[OwnershipSemanticRelation, tuple[str, ...], float]:
    line_candidates = [
        item
        for item in candidates
        if item.candidate_kind is CandidateKind.LINE_SEGMENT
    ]
    text_candidates = [
        item for item in candidates if item.candidate_kind is CandidateKind.OCR_TEXT
    ]
    foreground_candidates = [
        item
        for item in candidates
        if item.candidate_kind
        in {CandidateKind.LOGO, CandidateKind.SIGNATURE}
    ]
    if line_candidates and text_candidates:
        if {
            "TABLE_REGION_STRUCTURE_SUPPORT",
            "TABLE_REGION_TEXT_SUPPORT",
        }.issubset(group.reasons):
            return (
                OwnershipSemanticRelation.COEXIST,
                ("TABLE_BORDER_AND_CELL_TEXT_HAVE_DISTINCT_CAD_ROLES",),
                0.95,
            )
        relations = [
            _line_region_relation(
                line,
                text,
                allow_exclusive_stroke=True,
            )
            for line in line_candidates
            for text in text_candidates
        ]
        return _aggregate_pair_relations(relations)
    if line_candidates and foreground_candidates:
        relations = [
            _line_region_relation(
                line,
                foreground,
                allow_exclusive_stroke=False,
            )
            for line in line_candidates
            for foreground in foreground_candidates
        ]
        return _aggregate_pair_relations(relations)
    return (
        OwnershipSemanticRelation.PROVISIONAL,
        ("OVERLAPPING_INTERPRETATIONS_LACK_RELATION_EVIDENCE",),
        0.45,
    )


def _aggregate_pair_relations(
    relations: Sequence[
        tuple[OwnershipSemanticRelation, tuple[str, ...], float]
    ],
) -> tuple[OwnershipSemanticRelation, tuple[str, ...], float]:
    kinds = {item[0] for item in relations}
    reasons = tuple(sorted({reason for item in relations for reason in item[1]}))
    confidence = min(item[2] for item in relations)
    if OwnershipSemanticRelation.PROVISIONAL in kinds:
        return OwnershipSemanticRelation.PROVISIONAL, reasons, min(confidence, 0.5)
    if OwnershipSemanticRelation.OCCLUDED_BACKGROUND in kinds:
        if kinds == {OwnershipSemanticRelation.OCCLUDED_BACKGROUND}:
            return OwnershipSemanticRelation.OCCLUDED_BACKGROUND, reasons, confidence
        return (
            OwnershipSemanticRelation.PROVISIONAL,
            (*reasons, "MIXED_PAIR_RELATIONS_REQUIRE_REVIEW"),
            0.5,
        )
    if kinds == {OwnershipSemanticRelation.COEXIST}:
        return OwnershipSemanticRelation.COEXIST, reasons, confidence
    if kinds == {OwnershipSemanticRelation.EXCLUSIVE}:
        return OwnershipSemanticRelation.EXCLUSIVE, reasons, confidence
    return (
        OwnershipSemanticRelation.PROVISIONAL,
        (*reasons, "MIXED_PAIR_RELATIONS_REQUIRE_REVIEW"),
        0.5,
    )


def _relation_for_group(
    group: OwnershipGroup,
    candidates: Sequence[DraftsmanCandidateRecord],
    routes: Sequence[tuple[str, str]],
    related_final_candidate_ids: Sequence[str],
) -> tuple[OwnershipSemanticRelation, tuple[str, ...], float]:
    same_owner = _same_owner_relation(candidates)
    if same_owner is not None:
        return same_owner
    interpretations = {
        hypothesis.ownership_kind for hypothesis in group.hypotheses
    }
    if len(interpretations) > 1:
        return _cross_owner_relation(group, candidates)
    if related_final_candidate_ids:
        return (
            OwnershipSemanticRelation.SAME_ENTITY,
            (
                "FINAL_CANDIDATE_GEOMETRIC_OR_CONTENT_LINEAGE_MATCH",
                "IDENTITY_CHANGED_WITHOUT_EVIDENCE_OF_ENTITY_SUPPRESSION",
            ),
            0.95,
        )
    route_values = {value for _candidate_id, value in routes}
    if "UNOBSERVED" in route_values:
        return (
            OwnershipSemanticRelation.UNRESOLVED,
            ("PRODUCTION_LINEAGE_UNOBSERVED",),
            0.2,
        )
    if route_values.intersection(_EXPLICIT_SUPPRESSION_ROUTES) and group.confidence >= 0.8:
        return (
            OwnershipSemanticRelation.COEXIST,
            ("INDEPENDENT_HIGH_CONFIDENCE_EVIDENCE_EXPLICITLY_SUPPRESSED",),
            0.9,
        )
    return (
        OwnershipSemanticRelation.PROVISIONAL,
        (
            "EXACT_CANDIDATE_ID_NOT_IN_FINAL_ROUTING",
            "DERIVATION_OR_SUPPRESSION_NOT_DISTINGUISHABLE_WITH_CURRENT_LINEAGE",
        ),
        0.45,
    )


def _adjudication_category(
    relation: OwnershipSemanticRelation,
    *,
    group: OwnershipGroup,
    routes: Sequence[tuple[str, str]],
    reasons: Sequence[str],
) -> DiscrepancyAdjudicationCategory:
    route_values = {value for _candidate_id, value in routes}
    retained = route_values.difference(_DESTRUCTIVE_ROUTES)
    if relation in {
        OwnershipSemanticRelation.SAME_ENTITY,
        OwnershipSemanticRelation.DUPLICATE_HYPOTHESIS,
    }:
        return DiscrepancyAdjudicationCategory.DUPLICATE_HYPOTHESIS
    if relation is OwnershipSemanticRelation.EXCLUSIVE:
        return (
            DiscrepancyAdjudicationCategory.LEGITIMATE_EXCLUSIVE
            if len(retained) == 1
            else DiscrepancyAdjudicationCategory.PROVISIONAL
        )
    if relation is OwnershipSemanticRelation.OCCLUDED_BACKGROUND:
        return DiscrepancyAdjudicationCategory.OCCLUDED_BACKGROUND
    if relation is OwnershipSemanticRelation.COEXIST:
        if (
            "INDEPENDENT_HIGH_CONFIDENCE_EVIDENCE_EXPLICITLY_SUPPRESSED"
            in reasons
            and route_values.intersection(_EXPLICIT_SUPPRESSION_ROUTES)
            and group.confidence >= 0.8
        ):
            return DiscrepancyAdjudicationCategory.TRUE_DESTRUCTIVE_SUPPRESSION
        return DiscrepancyAdjudicationCategory.COEXIST
    if relation is OwnershipSemanticRelation.UNRESOLVED:
        return DiscrepancyAdjudicationCategory.UNRESOLVED
    return DiscrepancyAdjudicationCategory.PROVISIONAL


def _review_reason(
    category: DiscrepancyAdjudicationCategory,
) -> str | None:
    return {
        DiscrepancyAdjudicationCategory.TRUE_DESTRUCTIVE_SUPPRESSION: (
            "TRUE_DESTRUCTIVE_SUPPRESSION"
        ),
        DiscrepancyAdjudicationCategory.PROVISIONAL: (
            "OWNERSHIP_RELATION_PROVISIONAL"
        ),
        DiscrepancyAdjudicationCategory.UNRESOLVED: (
            "OWNERSHIP_RELATION_UNRESOLVED"
        ),
    }.get(category)


def _build_entry(
    *,
    discrepancy_id: str,
    group: OwnershipGroup,
    candidates: Sequence[DraftsmanCandidateRecord],
    routes: Sequence[tuple[str, str]],
    related_final_candidate_ids: Sequence[str],
    diagnostic_metadata: object | None,
) -> OwnershipRelationAdjudication:
    relation, relation_reasons, confidence = _relation_for_group(
        group,
        candidates,
        routes,
        related_final_candidate_ids,
    )
    category = _adjudication_category(
        relation,
        group=group,
        routes=routes,
        reasons=relation_reasons,
    )
    reasons = tuple(
        sorted(
            {
                *relation_reasons,
                "COUNT_UNIT_OWNERSHIP_GROUP",
                "SPATIAL_OVERLAP_IS_NOT_A_DEFECT_ASSERTION",
            }
        )
    )
    review_reason = _review_reason(category)
    review_required = review_reason is not None
    candidate_ids = _sorted_ids([item.stable_candidate_id for item in candidates])
    hypothesis_ids = _sorted_ids(
        [item.hypothesis_id for item in group.hypotheses]
    )
    interpretations = tuple(
        sorted({item.ownership_kind.value for item in group.hypotheses})
    )
    related_ids = _sorted_ids(related_final_candidate_ids)
    route_tuple = tuple(sorted(set(routes)))
    review_item_id = (
        semantic_id(
            "ownership-relation-review-item",
            DRAFTSMAN_OWNERSHIP_RELATION_VERSION,
            {
                "ownership_group_id": group.ownership_group_id,
                "review_reason": review_reason,
            },
        )
        if review_required
        else None
    )
    identity = {
        "original_discrepancy_id": discrepancy_id,
        "ownership_group_id": group.ownership_group_id,
        "source_region": group.source_region.identity_payload(),
        "candidate_ids": list(candidate_ids),
        "hypothesis_ids": list(hypothesis_ids),
        "source_evidence_relation": _source_relation(candidates).value,
        "candidate_interpretations": list(interpretations),
        "related_final_candidate_ids": list(related_ids),
        "final_cad_relation": relation.value,
        "adjudication_category": category.value,
        "confidence": _confidence(confidence),
        "reasons": list(reasons),
        "production_routes": [list(item) for item in route_tuple],
        "review_required": review_required,
        "review_reason": review_reason,
        "review_item_id": review_item_id,
    }
    return OwnershipRelationAdjudication(
        relation_id=semantic_id(
            "ownership-relation-adjudication",
            DRAFTSMAN_OWNERSHIP_RELATION_VERSION,
            identity,
        ),
        original_discrepancy_id=discrepancy_id,
        ownership_group_id=group.ownership_group_id,
        source_document_id=group.source_document_id,
        source_page=group.source_page,
        source_region=group.source_region,
        candidate_ids=candidate_ids,
        hypothesis_ids=hypothesis_ids,
        source_evidence_relation=_source_relation(candidates),
        candidate_interpretations=interpretations,
        related_final_candidate_ids=related_ids,
        final_cad_relation=relation,
        adjudication_category=category,
        confidence=_confidence(confidence),
        reasons=reasons,
        production_routes=route_tuple,
        review_required=review_required,
        review_reason=review_reason,
        review_item_id=review_item_id,
        diagnostic_metadata_json=canonical_json(diagnostic_metadata or {}),
    )


def build_discrepancy_adjudication_ledger(
    *,
    candidates: DraftsmanCandidateManifest,
    ownership: DraftsmanOwnershipManifest,
    production_routes: Mapping[str, str],
    final_candidates: DraftsmanCandidateManifest | None = None,
    diagnostic_metadata: object | None = None,
) -> OwnershipDiscrepancyLedger:
    """Adjudicate each original destructive group without changing candidates."""

    candidate_bytes_before = candidates.canonical_bytes()
    ownership_bytes_before = ownership.canonical_bytes()
    final_candidate_bytes_before = (
        None if final_candidates is None else final_candidates.canonical_bytes()
    )
    if candidates.manifest_id != ownership.candidate_manifest_id:
        raise ValueError("Ownership manifest does not belong to candidate manifest")
    if (
        final_candidates is not None
        and final_candidates.source_page.source_page_id
        != candidates.source_page.source_page_id
    ):
        raise ValueError("Final candidates must belong to the same source page")
    discrepancy_report = build_ownership_discrepancy_report(
        ownership,
        production_routes,
    )
    destructive_records = tuple(
        item
        for item in discrepancy_report.records
        if item.category is DiscrepancyCategory.PRODUCTION_DESTRUCTIVE_CONFLICT
    )
    group_by_id = {
        item.ownership_group_id: item for item in ownership.groups
    }
    candidate_by_id = {
        item.stable_candidate_id: item for item in candidates.candidates
    }
    final_candidate_records = (
        () if final_candidates is None else final_candidates.candidates
    )
    entries = []
    for discrepancy in destructive_records:
        group = group_by_id[discrepancy.ownership_group_id]
        group_candidates = tuple(
            candidate_by_id[candidate_id]
            for candidate_id in group.candidate_ids
        )
        related_final_ids = _sorted_ids(
            [
                final_candidate_id
                for candidate in group_candidates
                for final_candidate_id in _related_final_candidates(
                    candidate,
                    final_candidate_records,
                )
            ]
        )
        entries.append(
            _build_entry(
                discrepancy_id=discrepancy.discrepancy_id,
                group=group,
                candidates=group_candidates,
                routes=discrepancy.production_routes,
                related_final_candidate_ids=related_final_ids,
                diagnostic_metadata=diagnostic_metadata,
            )
        )
    ledger = OwnershipDiscrepancyLedger(
        source_page=ownership.source_page,
        candidate_manifest_id=candidates.manifest_id,
        ownership_manifest_id=ownership.manifest_id,
        final_candidate_manifest_id=(
            None if final_candidates is None else final_candidates.manifest_id
        ),
        original_discrepancy_ids=tuple(
            sorted(item.discrepancy_id for item in destructive_records)
        ),
        entries=tuple(sorted(entries, key=lambda item: item.relation_id)),
    )
    if candidates.canonical_bytes() != candidate_bytes_before:
        raise AssertionError("Discrepancy adjudication mutated candidates")
    if ownership.canonical_bytes() != ownership_bytes_before:
        raise AssertionError("Discrepancy adjudication mutated ownership")
    if (
        final_candidates is not None
        and final_candidates.canonical_bytes() != final_candidate_bytes_before
    ):
        raise AssertionError("Discrepancy adjudication mutated final candidates")
    return ledger


def ownership_contract_parent_version() -> str:
    return DRAFTSMAN_OWNERSHIP_VERSION
