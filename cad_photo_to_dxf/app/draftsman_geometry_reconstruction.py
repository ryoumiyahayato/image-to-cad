"""Deterministic, shadow-only line continuity reconstruction for Draftsman M3.

This module deliberately consumes immutable M1 candidates and M2 ownership
decisions.  It never mutates detector output and it has no path back into the
production exporter.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from math import acos, atan2, cos, degrees, floor, hypot, isfinite, sin
from statistics import mean, median
from typing import Sequence

import numpy as np

from .draftsman_candidate import (
    CandidateKind,
    DraftsmanCandidateManifest,
    DraftsmanCandidateRecord,
    LineCandidatePayload,
    StructuralRoiCandidatePayload,
)
from .draftsman_contract import (
    SourcePageRef,
    SourceRegionRef,
    canonical_json,
    canonical_json_bytes,
    semantic_id,
)
from .draftsman_ownership import (
    DraftsmanOwnershipManifest,
    OwnershipDecisionState,
    OwnershipKind,
)
from .draftsman_ownership_adjudication import (
    OwnershipDiscrepancyLedger,
    OwnershipSemanticRelation,
)


DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION = (
    "draftsman-geometry-reconstruction-v1"
)
DRAFTSMAN_LINE_RECONSTRUCTION_CONFIG_VERSION = (
    "draftsman-line-reconstruction-config-v1"
)
DRAFTSMAN_RECONSTRUCTION_REVIEW_VERSION = "draftsman-reconstruction-review-v1"


class ReconstructionKind(str, Enum):
    COLLINEAR_GAP_BRIDGE = "COLLINEAR_GAP_BRIDGE"
    CONTINUATION = "CONTINUATION"
    LINE_FAMILY_COMPLETION = "LINE_FAMILY_COMPLETION"
    TABLE_OR_RECTILINEAR_EDGE_COMPLETION = (
        "TABLE_OR_RECTILINEAR_EDGE_COMPLETION"
    )


class ReconstructionState(str, Enum):
    RECONSTRUCTED = "RECONSTRUCTED"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


def _required(value: str, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _score(value: float) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError("confidence must be finite")
    return round(max(0.0, min(1.0, result)), 6)


def _round(value: float) -> float:
    return round(float(value), 6)


def _sorted_ids(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({_required(value, "identity") for value in values}))


def _canonical(value: object) -> str:
    return canonical_json(value)


def _validate_json(value: str, name: str) -> None:
    if canonical_json(json.loads(value)) != value:
        raise ValueError(f"{name} must be canonical JSON")


@dataclass(frozen=True)
class LineReconstructionConfig:
    """Central, versioned M3-S1 safety thresholds in reference-pixel units."""

    reference_long_edge_px: float = 2400.0
    angular_tolerance_degrees: float = 2.5
    cross_track_tolerance_px: float = 3.0
    minimum_gap_px: float = 0.75
    maximum_gap_px: float = 32.0
    maximum_gap_to_shorter_segment: float = 0.45
    maximum_width_ratio: float = 2.5
    minimum_support_length_px: float = 7.0
    glyph_like_max_length_px: float = 14.0
    crossing_minimum_angle_degrees: float = 20.0
    family_maximum_offset_px: float = 120.0
    auto_reconstruct_confidence: float = 0.78
    provisional_confidence: float = 0.58
    competing_score_margin: float = 0.015
    competing_gap_margin_px: float = 0.25
    source_foreground_threshold: int = 180
    source_sample_radius_px: float = 1.25
    schema_version: str = DRAFTSMAN_LINE_RECONSTRUCTION_CONFIG_VERSION

    def __post_init__(self) -> None:
        positive = (
            self.reference_long_edge_px,
            self.angular_tolerance_degrees,
            self.cross_track_tolerance_px,
            self.minimum_gap_px,
            self.maximum_gap_px,
            self.maximum_gap_to_shorter_segment,
            self.maximum_width_ratio,
            self.minimum_support_length_px,
            self.glyph_like_max_length_px,
            self.crossing_minimum_angle_degrees,
            self.family_maximum_offset_px,
            self.source_sample_radius_px,
            self.competing_gap_margin_px,
        )
        if not all(isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("Line reconstruction thresholds must be positive")
        if self.minimum_gap_px >= self.maximum_gap_px:
            raise ValueError("minimum gap must be smaller than maximum gap")
        if not 0 <= self.source_foreground_threshold <= 255:
            raise ValueError("source foreground threshold must be 8-bit")
        if not 0.0 <= self.provisional_confidence < self.auto_reconstruct_confidence <= 1.0:
            raise ValueError("reconstruction confidence gates are invalid")

    @property
    def config_id(self) -> str:
        return semantic_id(
            "draftsman-line-reconstruction-config",
            self.schema_version,
            self.identity_payload(),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if key != "schema_version"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "config_id": self.config_id,
            **self.identity_payload(),
        }

    def scale_for(self, source_page: SourcePageRef) -> float:
        return max(source_page.source_size_px) / self.reference_long_edge_px


@dataclass(frozen=True)
class LineGeometry:
    start: tuple[float, float]
    end: tuple[float, float]
    width: float

    def __post_init__(self) -> None:
        if not all(isfinite(float(item)) for item in (*self.start, *self.end, self.width)):
            raise ValueError("Line geometry must be finite")
        if self.width <= 0.0 or self.length <= 0.0:
            raise ValueError("Line geometry must have positive width and length")

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @classmethod
    def create(
        cls,
        start: Sequence[float],
        end: Sequence[float],
        width: float,
    ) -> LineGeometry:
        first = (_round(start[0]), _round(start[1]))
        second = (_round(end[0]), _round(end[1]))
        if second < first:
            first, second = second, first
        return cls(first, second, _round(width))

    def identity_payload(self) -> dict[str, object]:
        return {
            "start": list(self.start),
            "end": list(self.end),
            "width": self.width,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload()


@dataclass(frozen=True)
class SourceRasterEvidence:
    """Immutable source-image sampler; pixels never enter proposal identity."""

    source_page_id: str
    raster_sha256: str
    foreground_mask: np.ndarray = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.foreground_mask.ndim != 2 or self.foreground_mask.dtype != np.bool_:
            raise ValueError("foreground_mask must be a two-dimensional bool array")
        if self.foreground_mask.flags.writeable:
            raise ValueError("foreground_mask must be immutable")

    @classmethod
    def create(
        cls,
        *,
        source_page: SourcePageRef,
        image: np.ndarray,
        threshold: int = 180,
    ) -> SourceRasterEvidence:
        raster = np.asarray(image)
        if raster.ndim == 3:
            raster = np.mean(raster[..., :3].astype(np.float64), axis=2)
        if raster.ndim != 2:
            raise ValueError("source evidence image must be grayscale or color")
        if tuple(reversed(raster.shape)) != source_page.source_size_px:
            raise ValueError("source evidence dimensions do not match source page")
        contiguous = np.ascontiguousarray(raster)
        mask = np.ascontiguousarray(contiguous < int(threshold), dtype=np.bool_)
        mask.setflags(write=False)
        return cls(
            source_page_id=source_page.source_page_id,
            raster_sha256=sha256(contiguous.tobytes()).hexdigest(),
            foreground_mask=mask,
        )

    def line_foreground_ratio(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        radius: float,
    ) -> float:
        length = max(1.0, hypot(end[0] - start[0], end[1] - start[1]))
        count = max(2, int(length * 2.0) + 1)
        xs = np.linspace(start[0], end[0], count)
        ys = np.linspace(start[1], end[1], count)
        height, width = self.foreground_mask.shape
        offsets = range(-max(0, int(round(radius))), max(0, int(round(radius))) + 1)
        values: list[bool] = []
        for offset_y in offsets:
            for offset_x in offsets:
                ix = np.clip(np.rint(xs + offset_x).astype(int), 0, width - 1)
                iy = np.clip(np.rint(ys + offset_y).astype(int), 0, height - 1)
                values.extend(bool(item) for item in self.foreground_mask[iy, ix])
        return round(sum(values) / max(1, len(values)), 6)


@dataclass(frozen=True)
class AcceptedLineReconstruction:
    stable_entity_id: str
    geometry: LineGeometry
    provenance_id: str
    source_candidate_ids: tuple[str, ...] = ()
    reconstruction_rule: str = "text_mask_restoration"

    def __post_init__(self) -> None:
        _required(self.stable_entity_id, "stable_entity_id")
        _required(self.provenance_id, "provenance_id")
        _required(self.reconstruction_rule, "reconstruction_rule")
        if self.source_candidate_ids != _sorted_ids(self.source_candidate_ids):
            raise ValueError("accepted source candidate IDs must be canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "stable_entity_id": self.stable_entity_id,
            "geometry": self.geometry.to_dict(),
            "provenance_id": self.provenance_id,
            "source_candidate_ids": list(self.source_candidate_ids),
            "reconstruction_rule": self.reconstruction_rule,
            "status": "EXISTING_ACCEPTED_RECONSTRUCTION",
        }


@dataclass(frozen=True)
class ReconstructionEvidence:
    evidence_id: str
    reason_code: str
    candidate_ids: tuple[str, ...]
    weight: float
    details_json: str
    schema_version: str = DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION

    @classmethod
    def create(
        cls,
        *,
        reason_code: str,
        candidate_ids: Sequence[str],
        weight: float,
        details: object | None = None,
    ) -> ReconstructionEvidence:
        ids = _sorted_ids(candidate_ids)
        details_json = _canonical(details or {})
        identity = {
            "reason_code": _required(reason_code, "reason_code"),
            "candidate_ids": list(ids),
            "weight": _round(weight),
            "details": json.loads(details_json),
        }
        return cls(
            semantic_id("reconstruction-evidence", DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION, identity),
            reason_code,
            ids,
            _round(weight),
            details_json,
        )

    def __post_init__(self) -> None:
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("reconstruction evidence IDs must be canonical")
        if not isfinite(self.weight) or not -1.0 <= self.weight <= 1.0:
            raise ValueError("reconstruction evidence weight must be normalized")
        _validate_json(self.details_json, "details_json")
        if self.evidence_id != semantic_id(
            "reconstruction-evidence", self.schema_version, self.identity_payload()
        ):
            raise ValueError("evidence_id does not match evidence semantics")

    def identity_payload(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "candidate_ids": list(self.candidate_ids),
            "weight": self.weight,
            "details": json.loads(self.details_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "evidence_id": self.evidence_id, **self.identity_payload()}


@dataclass(frozen=True)
class ReconstructionConflict:
    conflict_id: str
    conflict_code: str
    candidate_ids: tuple[str, ...]
    details_json: str
    schema_version: str = DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION

    @classmethod
    def create(
        cls,
        *,
        conflict_code: str,
        candidate_ids: Sequence[str],
        details: object | None = None,
    ) -> ReconstructionConflict:
        ids = _sorted_ids(candidate_ids)
        details_json = _canonical(details or {})
        identity = {
            "conflict_code": _required(conflict_code, "conflict_code"),
            "candidate_ids": list(ids),
            "details": json.loads(details_json),
        }
        return cls(
            semantic_id("reconstruction-conflict", DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION, identity),
            conflict_code,
            ids,
            details_json,
        )

    def __post_init__(self) -> None:
        if self.candidate_ids != _sorted_ids(self.candidate_ids):
            raise ValueError("reconstruction conflict IDs must be canonical")
        _validate_json(self.details_json, "details_json")
        if self.conflict_id != semantic_id(
            "reconstruction-conflict", self.schema_version, self.identity_payload()
        ):
            raise ValueError("conflict_id does not match conflict semantics")

    def identity_payload(self) -> dict[str, object]:
        return {
            "conflict_code": self.conflict_code,
            "candidate_ids": list(self.candidate_ids),
            "details": json.loads(self.details_json),
        }

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "conflict_id": self.conflict_id, **self.identity_payload()}


@dataclass(frozen=True)
class ReconstructionProvenance:
    provenance_id: str
    creation_method: str
    reconstruction_rule: str
    source_candidate_ids: tuple[str, ...]
    ownership_group_ids: tuple[str, ...]
    source_region: SourceRegionRef
    transform_id: str
    parent_entity_ids: tuple[str, ...]
    schema_version: str = DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION

    @classmethod
    def create(
        cls,
        *,
        reconstruction_rule: str,
        source_candidate_ids: Sequence[str],
        ownership_group_ids: Sequence[str],
        source_region: SourceRegionRef,
        transform_id: str,
        parent_entity_ids: Sequence[str] = (),
    ) -> ReconstructionProvenance:
        values = {
            "creation_method": "draftsman-m3-s1-shadow-engine",
            "reconstruction_rule": _required(reconstruction_rule, "reconstruction_rule"),
            "source_candidate_ids": list(_sorted_ids(source_candidate_ids)),
            "ownership_group_ids": list(_sorted_ids(ownership_group_ids)),
            "source_region": source_region.identity_payload(),
            "transform_id": _required(transform_id, "transform_id"),
            "parent_entity_ids": list(_sorted_ids(parent_entity_ids)),
        }
        return cls(
            semantic_id("reconstruction-provenance", DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION, values),
            str(values["creation_method"]),
            reconstruction_rule,
            tuple(values["source_candidate_ids"]),
            tuple(values["ownership_group_ids"]),
            source_region,
            transform_id,
            tuple(values["parent_entity_ids"]),
        )

    def __post_init__(self) -> None:
        if self.provenance_id != semantic_id(
            "reconstruction-provenance", self.schema_version, self.identity_payload()
        ):
            raise ValueError("provenance_id does not match provenance semantics")

    def identity_payload(self) -> dict[str, object]:
        return {
            "creation_method": self.creation_method,
            "reconstruction_rule": self.reconstruction_rule,
            "source_candidate_ids": list(self.source_candidate_ids),
            "ownership_group_ids": list(self.ownership_group_ids),
            "source_region": self.source_region.identity_payload(),
            "transform_id": self.transform_id,
            "parent_entity_ids": list(self.parent_entity_ids),
        }

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "provenance_id": self.provenance_id, **self.identity_payload()}


@dataclass(frozen=True)
class ReconstructionProposal:
    stable_proposal_id: str
    reconstruction_kind: ReconstructionKind
    source_document_id: str
    source_page: int
    source_candidate_ids: tuple[str, ...]
    ownership_group_ids: tuple[str, ...]
    proposed_geometry: LineGeometry
    supporting_geometry: tuple[LineGeometry, ...]
    source_region: SourceRegionRef
    rule: str
    evidence: tuple[ReconstructionEvidence, ...]
    confidence: float
    state: ReconstructionState
    conflicts: tuple[ReconstructionConflict, ...]
    provenance: ReconstructionProvenance
    review_required: bool
    review_reason: str | None
    review_item_id: str | None
    diagnostic_metadata_json: str = "{}"
    schema_version: str = DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION

    def __post_init__(self) -> None:
        if self.source_candidate_ids != _sorted_ids(self.source_candidate_ids):
            raise ValueError("proposal candidate IDs must be canonical")
        if self.ownership_group_ids != _sorted_ids(self.ownership_group_ids):
            raise ValueError("proposal ownership IDs must be canonical")
        if self.evidence != tuple(sorted(self.evidence, key=lambda item: item.evidence_id)):
            raise ValueError("proposal evidence must use canonical order")
        if self.conflicts != tuple(sorted(self.conflicts, key=lambda item: item.conflict_id)):
            raise ValueError("proposal conflicts must use canonical order")
        if self.supporting_geometry != tuple(sorted(self.supporting_geometry, key=lambda item: canonical_json_bytes(item.to_dict()))):
            raise ValueError("supporting geometry must use canonical order")
        if self.confidence != _score(self.confidence):
            raise ValueError("proposal confidence must be normalized")
        if self.state is ReconstructionState.RECONSTRUCTED:
            if self.review_required:
                raise ValueError("accepted reconstruction must not require review")
        elif not self.review_required or not self.review_reason or not self.review_item_id:
            raise ValueError("uncertain reconstruction requires stable review linkage")
        _validate_json(self.diagnostic_metadata_json, "diagnostic_metadata_json")
        if self.stable_proposal_id != semantic_id(
            "draftsman-reconstruction-proposal", self.schema_version, self.identity_payload()
        ):
            raise ValueError("stable_proposal_id does not match proposal semantics")

    def identity_payload(self) -> dict[str, object]:
        return {
            "reconstruction_kind": self.reconstruction_kind.value,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_candidate_ids": list(self.source_candidate_ids),
            "ownership_group_ids": list(self.ownership_group_ids),
            "proposed_geometry": self.proposed_geometry.to_dict(),
            "supporting_geometry": [item.to_dict() for item in self.supporting_geometry],
            "source_region": self.source_region.identity_payload(),
            "rule": self.rule,
            "evidence_ids": [item.evidence_id for item in self.evidence],
            "confidence": self.confidence,
            "state": self.state.value,
            "conflict_ids": [item.conflict_id for item in self.conflicts],
            "provenance_id": self.provenance.provenance_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_proposal_id": self.stable_proposal_id,
            **self.identity_payload(),
            "evidence": [item.to_dict() for item in self.evidence],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "provenance": self.provenance.to_dict(),
            "review_required": self.review_required,
            "review_reason": self.review_reason,
            "review_item_id": self.review_item_id,
            "diagnostic_metadata": json.loads(self.diagnostic_metadata_json),
        }


@dataclass(frozen=True)
class ReconstructionReviewItem:
    review_item_id: str
    proposal_id: str
    source_document_id: str
    source_page: int
    source_region: SourceRegionRef
    proposed_geometry: LineGeometry
    source_candidate_ids: tuple[str, ...]
    reason: str
    confidence: float
    suggested_actions: tuple[str, ...]
    risk_score: float
    schema_version: str = DRAFTSMAN_RECONSTRUCTION_REVIEW_VERSION

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        source_page: SourcePageRef,
        source_region: SourceRegionRef,
        proposed_geometry: LineGeometry,
        source_candidate_ids: Sequence[str],
        reason: str,
        confidence: float,
        risk_score: float,
    ) -> ReconstructionReviewItem:
        ids = _sorted_ids(source_candidate_ids)
        identity = {
            "proposal_id": proposal_id,
            "source_page_id": source_page.source_page_id,
            "source_region": source_region.identity_payload(),
            "proposed_geometry": proposed_geometry.to_dict(),
            "source_candidate_ids": list(ids),
            "reason": reason,
        }
        return cls(
            semantic_id("reconstruction-review-item", DRAFTSMAN_RECONSTRUCTION_REVIEW_VERSION, identity),
            proposal_id,
            source_page.source_document_id,
            source_page.source_page,
            source_region,
            proposed_geometry,
            ids,
            reason,
            _score(confidence),
            ("ACCEPT", "REJECT", "EDIT", "LEAVE_UNRESOLVED"),
            _score(risk_score),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "review_item_id": self.review_item_id,
            "proposal_id": self.proposal_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_region": self.source_region.to_dict(),
            "proposed_geometry": self.proposed_geometry.to_dict(),
            "source_candidate_ids": list(self.source_candidate_ids),
            "reason": self.reason,
            "confidence": self.confidence,
            "suggested_actions": list(self.suggested_actions),
            "alternative": "NO_RECONSTRUCTION",
            "risk_score": self.risk_score,
        }


@dataclass(frozen=True)
class ReconstructionMetrics:
    source_geometry_candidates: int
    reconstruction_proposals: int
    reconstructed: int
    provisional: int
    unresolved: int
    duplicate_evidence_collapsed: int
    crossing_conflict_rejected: int
    text_structure_overlap_cases: int
    occluded_background_proposals: int
    mean_gap_length: float
    median_gap_length: float
    max_gap_length: float
    rc3_preserved: int
    rc3_hypothesis_coverage: int

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class DraftsmanGeometryReconstructionManifest:
    source_page: SourcePageRef
    transform_id: str
    candidate_manifest_id: str
    ownership_manifest_id: str
    ownership_relation_ledger_id: str | None
    config: LineReconstructionConfig
    source_raster_evidence_sha256: str | None
    accepted_reconstructions: tuple[AcceptedLineReconstruction, ...]
    proposals: tuple[ReconstructionProposal, ...]
    review_items: tuple[ReconstructionReviewItem, ...]
    metrics: ReconstructionMetrics
    schema_version: str = DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION

    def __post_init__(self) -> None:
        if self.proposals != tuple(sorted(self.proposals, key=lambda item: item.stable_proposal_id)):
            raise ValueError("reconstruction proposals must use canonical order")
        if self.review_items != tuple(sorted(self.review_items, key=lambda item: (-item.risk_score, item.review_item_id))):
            raise ValueError("review items must use risk order")
        if len({item.stable_proposal_id for item in self.proposals}) != len(self.proposals):
            raise ValueError("reconstruction proposal IDs must be unique")

    @property
    def manifest_id(self) -> str:
        return semantic_id("draftsman-geometry-reconstruction-manifest", self.schema_version, self.identity_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_page_id": self.source_page.source_page_id,
            "transform_id": self.transform_id,
            "candidate_manifest_id": self.candidate_manifest_id,
            "ownership_manifest_id": self.ownership_manifest_id,
            "ownership_relation_ledger_id": self.ownership_relation_ledger_id,
            "config_id": self.config.config_id,
            "source_raster_evidence_sha256": self.source_raster_evidence_sha256,
            "accepted_reconstruction_ids": sorted(item.stable_entity_id for item in self.accepted_reconstructions),
            "proposal_ids": [item.stable_proposal_id for item in self.proposals],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_page": self.source_page.to_dict(),
            "transform_id": self.transform_id,
            "candidate_manifest_id": self.candidate_manifest_id,
            "ownership_manifest_id": self.ownership_manifest_id,
            "ownership_relation_ledger_id": self.ownership_relation_ledger_id,
            "config": self.config.to_dict(),
            "source_raster_evidence_sha256": self.source_raster_evidence_sha256,
            "accepted_reconstructions": [item.to_dict() for item in self.accepted_reconstructions],
            "metrics": self.metrics.to_dict(),
            "proposals": [item.to_dict() for item in self.proposals],
            "review_items": [item.to_dict() for item in self.review_items],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class _LineEvidence:
    geometry: LineGeometry
    candidate_ids: tuple[str, ...]
    representative_id: str
    confidence: float


@dataclass(frozen=True)
class _PairSeed:
    left: _LineEvidence
    right: _LineEvidence
    proposed: LineGeometry
    gap_start: tuple[float, float]
    gap_end: tuple[float, float]
    gap_length: float
    angle_difference: float
    cross_track_distance: float
    width_ratio: float
    geometry_confidence: float


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        first, second = self.find(left), self.find(right)
        if first == second:
            return
        low, high = sorted((first, second))
        self.parent[high] = low


def _line_from_candidate(candidate: DraftsmanCandidateRecord) -> LineGeometry:
    payload = candidate.payload
    if not isinstance(payload, LineCandidatePayload):
        raise TypeError("candidate is not a line")
    return LineGeometry.create(payload.start, payload.end, payload.width)


def _unit(geometry: LineGeometry) -> tuple[float, float]:
    return (
        (geometry.end[0] - geometry.start[0]) / geometry.length,
        (geometry.end[1] - geometry.start[1]) / geometry.length,
    )


def _angle_difference(left: LineGeometry, right: LineGeometry) -> float:
    lu, ru = _unit(left), _unit(right)
    dot = max(-1.0, min(1.0, abs(lu[0] * ru[0] + lu[1] * ru[1])))
    return degrees(acos(dot))


def _point_line_distance(point: tuple[float, float], line: LineGeometry) -> float:
    unit = _unit(line)
    return abs((point[0] - line.start[0]) * -unit[1] + (point[1] - line.start[1]) * unit[0])


def _line_equivalent(left: LineGeometry, right: LineGeometry) -> bool:
    if _angle_difference(left, right) > 1.0:
        return False
    tolerance = max(1.5, left.width, right.width)
    if _point_line_distance(right.start, left) > tolerance or _point_line_distance(right.end, left) > tolerance:
        return False
    axis = _unit(left)
    left_values = sorted((0.0, left.length))
    right_values = sorted(
        (
            (right.start[0] - left.start[0]) * axis[0] + (right.start[1] - left.start[1]) * axis[1],
            (right.end[0] - left.start[0]) * axis[0] + (right.end[1] - left.start[1]) * axis[1],
        )
    )
    overlap = max(0.0, min(left_values[1], right_values[1]) - max(left_values[0], right_values[0]))
    return overlap / max(1.0, min(left.length, right.length)) >= 0.9


def _regions_intersect(left: SourceRegionRef, right: SourceRegionRef) -> bool:
    return not (
        left.x_max < right.x_min
        or right.x_max < left.x_min
        or left.y_max < right.y_min
        or right.y_max < left.y_min
    )


def _region_for_line(geometry: LineGeometry, pad: float = 0.0) -> SourceRegionRef:
    return SourceRegionRef(
        min(geometry.start[0], geometry.end[0]) - pad,
        min(geometry.start[1], geometry.end[1]) - pad,
        max(geometry.start[0], geometry.end[0]) + pad,
        max(geometry.start[1], geometry.end[1]) + pad,
    )


def _pair_seed(
    left: _LineEvidence,
    right: _LineEvidence,
    *,
    scale: float,
    config: LineReconstructionConfig,
) -> _PairSeed | None:
    angle = _angle_difference(left.geometry, right.geometry)
    if angle > config.angular_tolerance_degrees:
        return None
    first_unit = _unit(left.geometry)
    second_unit = _unit(right.geometry)
    if first_unit[0] * second_unit[0] + first_unit[1] * second_unit[1] < 0.0:
        second_unit = (-second_unit[0], -second_unit[1])
    axis_angle = atan2(first_unit[1] + second_unit[1], first_unit[0] + second_unit[0])
    axis = (cos(axis_angle), sin(axis_angle))
    normal = (-axis[1], axis[0])
    points = (
        left.geometry.start,
        left.geometry.end,
        right.geometry.start,
        right.geometry.end,
    )
    cross_values = [point[0] * normal[0] + point[1] * normal[1] for point in points]
    cross_distance = abs(
        (sum(cross_values[:2]) / 2.0) - (sum(cross_values[2:]) / 2.0)
    )
    cross_limit = max(
        config.cross_track_tolerance_px * scale,
        left.geometry.width * 1.5,
        right.geometry.width * 1.5,
    )
    if cross_distance > cross_limit:
        return None
    projections = [point[0] * axis[0] + point[1] * axis[1] for point in points]
    first_interval = sorted(projections[:2])
    second_interval = sorted(projections[2:])
    if first_interval[0] > second_interval[0]:
        first_interval, second_interval = second_interval, first_interval
        left, right = right, left
    gap = second_interval[0] - first_interval[1]
    if gap <= config.minimum_gap_px * scale:
        return None
    maximum_gap = min(
        config.maximum_gap_px * scale,
        min(left.geometry.length, right.geometry.length)
        * config.maximum_gap_to_shorter_segment,
    )
    if gap > maximum_gap:
        return None
    width_ratio = max(left.geometry.width, right.geometry.width) / min(
        left.geometry.width, right.geometry.width
    )
    if width_ratio > config.maximum_width_ratio:
        return None
    cross = sum(cross_values) / len(cross_values)

    def at(projected: float) -> tuple[float, float]:
        return (
            _round(projected * axis[0] + cross * normal[0]),
            _round(projected * axis[1] + cross * normal[1]),
        )

    proposed = LineGeometry.create(
        at(min(projections)),
        at(max(projections)),
        (left.geometry.width + right.geometry.width) / 2.0,
    )
    gap_start, gap_end = at(first_interval[1]), at(second_interval[0])
    confidence = (
        0.26 * (1.0 - angle / config.angular_tolerance_degrees)
        + 0.22 * (1.0 - cross_distance / cross_limit)
        + 0.16 * (1.0 - gap / max(maximum_gap, 1.0))
        + 0.12 * (1.0 - (width_ratio - 1.0) / (config.maximum_width_ratio - 1.0))
        + 0.24 * min(left.confidence, right.confidence)
    )
    return _PairSeed(
        left,
        right,
        proposed,
        gap_start,
        gap_end,
        _round(gap),
        _round(angle),
        _round(cross_distance),
        _round(width_ratio),
        _score(confidence),
    )


def _pair_endpoint_index(line: _LineEvidence, seed: _PairSeed) -> int:
    distances = (
        min(
            hypot(line.geometry.start[0] - seed.gap_start[0], line.geometry.start[1] - seed.gap_start[1]),
            hypot(line.geometry.start[0] - seed.gap_end[0], line.geometry.start[1] - seed.gap_end[1]),
        ),
        min(
            hypot(line.geometry.end[0] - seed.gap_start[0], line.geometry.end[1] - seed.gap_start[1]),
            hypot(line.geometry.end[0] - seed.gap_end[0], line.geometry.end[1] - seed.gap_end[1]),
        ),
    )
    return 0 if distances[0] <= distances[1] else 1


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    one = orientation(first_start, first_end, second_start)
    two = orientation(first_start, first_end, second_end)
    three = orientation(second_start, second_end, first_start)
    four = orientation(second_start, second_end, first_end)
    return one * two <= 0.0 and three * four <= 0.0


def _accepted_match(proposed: LineGeometry, accepted: LineGeometry) -> bool:
    if _angle_difference(proposed, accepted) > 1.0:
        return False
    if _point_line_distance(accepted.start, proposed) > max(2.0, proposed.width, accepted.width):
        return False
    axis = _unit(proposed)
    values = sorted(
        (
            (accepted.start[0] - proposed.start[0]) * axis[0] + (accepted.start[1] - proposed.start[1]) * axis[1],
            (accepted.end[0] - proposed.start[0]) * axis[0] + (accepted.end[1] - proposed.start[1]) * axis[1],
        )
    )
    overlap = max(0.0, min(proposed.length, values[1]) - max(0.0, values[0]))
    return overlap / max(1.0, min(proposed.length, accepted.length)) >= 0.8


def _build_line_evidence(
    candidates: Sequence[DraftsmanCandidateRecord],
    ownership: DraftsmanOwnershipManifest,
    relation_ledger: OwnershipDiscrepancyLedger | None,
) -> tuple[tuple[_LineEvidence, ...], int]:
    lines = {
        item.stable_candidate_id: item
        for item in candidates
        if item.candidate_kind is CandidateKind.LINE_SEGMENT
        and isinstance(item.payload, LineCandidatePayload)
        and "text_mask_restoration" not in item.payload.detector_history
    }
    union = _UnionFind(tuple(lines))
    exact_geometry: dict[LineGeometry, str] = {}
    for candidate_id, candidate in sorted(lines.items()):
        geometry = _line_from_candidate(candidate)
        previous = exact_geometry.get(geometry)
        if previous is None:
            exact_geometry[geometry] = candidate_id
        else:
            union.union(previous, candidate_id)
    if relation_ledger is not None:
        for relation in relation_ledger.entries:
            if relation.final_cad_relation not in {
                OwnershipSemanticRelation.SAME_ENTITY,
                OwnershipSemanticRelation.DUPLICATE_HYPOTHESIS,
            }:
                continue
            ids = [item for item in relation.candidate_ids if item in lines]
            for candidate_id in ids[1:]:
                union.union(ids[0], candidate_id)
    for group in ownership.groups:
        ids = [item for item in group.candidate_ids if item in lines]
        for index, left_id in enumerate(ids):
            left = _line_from_candidate(lines[left_id])
            for right_id in ids[index + 1 :]:
                if _line_equivalent(left, _line_from_candidate(lines[right_id])):
                    union.union(left_id, right_id)
    grouped: dict[str, list[DraftsmanCandidateRecord]] = defaultdict(list)
    for candidate_id, candidate in lines.items():
        grouped[union.find(candidate_id)].append(candidate)
    evidence: list[_LineEvidence] = []
    for members in grouped.values():
        ordered = sorted(
            members,
            key=lambda item: (
                -_line_from_candidate(item).length,
                -item.confidence,
                item.stable_candidate_id,
            ),
        )
        representative = ordered[0]
        evidence.append(
            _LineEvidence(
                _line_from_candidate(representative),
                _sorted_ids([item.stable_candidate_id for item in ordered]),
                representative.stable_candidate_id,
                _score(max(item.confidence for item in ordered)),
            )
        )
    return (
        tuple(sorted(evidence, key=lambda item: item.representative_id)),
        len(lines) - len(evidence),
    )


def _find_pair_seeds(
    evidence: Sequence[_LineEvidence],
    source_page: SourcePageRef,
    config: LineReconstructionConfig,
) -> tuple[_PairSeed, ...]:
    scale = config.scale_for(source_page)
    cell_size = max(1.0, config.maximum_gap_px * scale)
    endpoint_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, item in enumerate(evidence):
        for point in (item.geometry.start, item.geometry.end):
            endpoint_grid[(floor(point[0] / cell_size), floor(point[1] / cell_size))].append(index)
    pairs: dict[tuple[int, int], _PairSeed] = {}
    for index, item in enumerate(evidence):
        nearby: set[int] = set()
        for point in (item.geometry.start, item.geometry.end):
            cell = (floor(point[0] / cell_size), floor(point[1] / cell_size))
            for offset_x in (-1, 0, 1):
                for offset_y in (-1, 0, 1):
                    nearby.update(endpoint_grid.get((cell[0] + offset_x, cell[1] + offset_y), ()))
        for other_index in sorted(value for value in nearby if value > index):
            seed = _pair_seed(item, evidence[other_index], scale=scale, config=config)
            if seed is not None:
                pairs[(index, other_index)] = seed
    ordered = tuple(
        sorted(
            pairs.values(),
            key=lambda item: (
                item.left.representative_id,
                item.right.representative_id,
            ),
        )
    )
    # A draftsman continues the closest compatible stroke at each endpoint.  The
    # mutual-nearest gate prevents a dense family of nearby Hough fragments from
    # producing the Cartesian product of every plausible pair.  Near-equal
    # choices remain present so the caller can mark true competition provisional.
    endpoint_choices: dict[tuple[str, int], list[tuple[int, float, float]]] = defaultdict(list)

    pair_keys: list[tuple[tuple[str, int], tuple[str, int]]] = []
    for pair_index, seed in enumerate(ordered):
        keys = (
            (seed.left.representative_id, _pair_endpoint_index(seed.left, seed)),
            (seed.right.representative_id, _pair_endpoint_index(seed.right, seed)),
        )
        pair_keys.append(keys)
        for key in keys:
            endpoint_choices[key].append(
                (pair_index, seed.gap_length, seed.geometry_confidence)
            )
    allowed: dict[tuple[str, int], set[int]] = {}
    gap_margin = config.competing_gap_margin_px * scale
    for key, choices in endpoint_choices.items():
        best_gap = min(item[1] for item in choices)
        near = [item for item in choices if item[1] <= best_gap + gap_margin]
        best_score = max(item[2] for item in near)
        allowed[key] = {
            item[0]
            for item in near
            if item[2] >= best_score - config.competing_score_margin
        }
    return tuple(
        seed
        for pair_index, seed in enumerate(ordered)
        if all(pair_index in allowed[key] for key in pair_keys[pair_index])
    )


def _proposal_seed_id(
    *,
    source_page: SourcePageRef,
    candidate_ids: Sequence[str],
    geometry: LineGeometry,
    config_id: str,
) -> str:
    return semantic_id(
        "draftsman-reconstruction-proposal-seed",
        DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION,
        {
            "source_page_id": source_page.source_page_id,
            "candidate_ids": list(_sorted_ids(candidate_ids)),
            "geometry": geometry.to_dict(),
            "config_id": config_id,
        },
    )


def _make_proposal(
    *,
    source_page: SourcePageRef,
    transform_id: str,
    config: LineReconstructionConfig,
    seed: _PairSeed,
    candidate_ids: tuple[str, ...],
    ownership_group_ids: tuple[str, ...],
    kind: ReconstructionKind,
    confidence: float,
    state: ReconstructionState,
    evidence: Sequence[ReconstructionEvidence],
    conflicts: Sequence[ReconstructionConflict],
    review_reason: str | None,
    diagnostic_metadata: object,
) -> tuple[ReconstructionProposal, ReconstructionReviewItem | None]:
    region = _region_for_line(seed.proposed, max(seed.proposed.width, 1.0))
    provenance = ReconstructionProvenance.create(
        reconstruction_rule=kind.value,
        source_candidate_ids=candidate_ids,
        ownership_group_ids=ownership_group_ids,
        source_region=region,
        transform_id=transform_id,
    )
    sorted_evidence = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    sorted_conflicts = tuple(sorted(conflicts, key=lambda item: item.conflict_id))
    supporting = tuple(
        sorted(
            (seed.left.geometry, seed.right.geometry),
            key=lambda item: canonical_json_bytes(item.to_dict()),
        )
    )
    base_identity = {
        "reconstruction_kind": kind.value,
        "source_document_id": source_page.source_document_id,
        "source_page": source_page.source_page,
        "source_candidate_ids": list(candidate_ids),
        "ownership_group_ids": list(ownership_group_ids),
        "proposed_geometry": seed.proposed.to_dict(),
        "supporting_geometry": [item.to_dict() for item in supporting],
        "source_region": region.identity_payload(),
        "rule": kind.value,
        "evidence_ids": [item.evidence_id for item in sorted_evidence],
        "confidence": _score(confidence),
        "state": state.value,
        "conflict_ids": [item.conflict_id for item in sorted_conflicts],
        "provenance_id": provenance.provenance_id,
    }
    proposal_id = semantic_id(
        "draftsman-reconstruction-proposal",
        DRAFTSMAN_GEOMETRY_RECONSTRUCTION_VERSION,
        base_identity,
    )
    review: ReconstructionReviewItem | None = None
    if state is not ReconstructionState.RECONSTRUCTED:
        reason = review_reason or "LOW_CONFIDENCE_RECONSTRUCTION"
        review = ReconstructionReviewItem.create(
            proposal_id=proposal_id,
            source_page=source_page,
            source_region=region,
            proposed_geometry=seed.proposed,
            source_candidate_ids=candidate_ids,
            reason=reason,
            confidence=confidence,
            risk_score=min(1.0, seed.gap_length / max(1.0, config.maximum_gap_px * config.scale_for(source_page)) + (0.25 if conflicts else 0.0)),
        )
    proposal = ReconstructionProposal(
        stable_proposal_id=proposal_id,
        reconstruction_kind=kind,
        source_document_id=source_page.source_document_id,
        source_page=source_page.source_page,
        source_candidate_ids=candidate_ids,
        ownership_group_ids=ownership_group_ids,
        proposed_geometry=seed.proposed,
        supporting_geometry=supporting,
        source_region=region,
        rule=kind.value,
        evidence=sorted_evidence,
        confidence=_score(confidence),
        state=state,
        conflicts=sorted_conflicts,
        provenance=provenance,
        review_required=review is not None,
        review_reason=None if review is None else review.reason,
        review_item_id=None if review is None else review.review_item_id,
        diagnostic_metadata_json=_canonical(diagnostic_metadata),
    )
    return proposal, review


def build_line_reconstruction_manifest(
    candidate_manifest: DraftsmanCandidateManifest,
    ownership_manifest: DraftsmanOwnershipManifest,
    *,
    relation_ledger: OwnershipDiscrepancyLedger | None = None,
    source_raster_evidence: SourceRasterEvidence | None = None,
    accepted_reconstructions: Sequence[AcceptedLineReconstruction] = (),
    config: LineReconstructionConfig | None = None,
) -> DraftsmanGeometryReconstructionManifest:
    """Build an ordering-independent M3 shadow proposal manifest."""

    resolved_config = config or LineReconstructionConfig()
    if ownership_manifest.candidate_manifest_id != candidate_manifest.manifest_id:
        raise ValueError("ownership manifest does not belong to candidate manifest")
    if ownership_manifest.source_page.source_page_id != candidate_manifest.source_page.source_page_id:
        raise ValueError("ownership and candidates must describe the same page")
    if relation_ledger is not None and relation_ledger.ownership_manifest_id != ownership_manifest.manifest_id:
        raise ValueError("relation ledger does not belong to ownership manifest")
    if source_raster_evidence is not None and source_raster_evidence.source_page_id != candidate_manifest.source_page.source_page_id:
        raise ValueError("source raster evidence does not belong to source page")

    candidates = tuple(candidate_manifest.candidates)
    group_by_candidate = {
        candidate_id: group
        for group in ownership_manifest.groups
        for candidate_id in group.candidate_ids
    }
    relation_by_group = (
        {}
        if relation_ledger is None
        else {item.ownership_group_id: item for item in relation_ledger.entries}
    )
    line_evidence, duplicate_count = _build_line_evidence(
        candidates,
        ownership_manifest,
        relation_ledger,
    )
    pair_seeds = _find_pair_seeds(line_evidence, candidate_manifest.source_page, resolved_config)
    scale = resolved_config.scale_for(candidate_manifest.source_page)

    text_like = tuple(
        item
        for item in candidates
        if item.candidate_kind in {CandidateKind.OCR_TEXT, CandidateKind.LOGO, CandidateKind.SIGNATURE}
    )
    rois = tuple(
        item
        for item in candidates
        if item.candidate_kind in {CandidateKind.STRUCTURAL_ROI, CandidateKind.TABLE_REGION}
        and isinstance(item.payload, StructuralRoiCandidatePayload)
    )
    all_unique_lines = tuple(item.geometry for item in line_evidence)
    endpoint_choices: dict[tuple[str, int], list[tuple[str, float]]] = defaultdict(list)
    for seed in pair_seeds:
        endpoint_choices[
            (seed.left.representative_id, _pair_endpoint_index(seed.left, seed))
        ].append((seed.right.representative_id, seed.geometry_confidence))
        endpoint_choices[
            (seed.right.representative_id, _pair_endpoint_index(seed.right, seed))
        ].append((seed.left.representative_id, seed.geometry_confidence))

    accepted = tuple(sorted(accepted_reconstructions, key=lambda item: item.stable_entity_id))
    covered_accepted: set[str] = set()
    proposals: list[ReconstructionProposal] = []
    reviews: list[ReconstructionReviewItem] = []
    crossing_rejected = 0
    overlap_cases = 0
    occluded_count = 0
    seen_seed_ids: set[str] = set()
    gaps: list[float] = []

    for seed in pair_seeds:
        candidate_ids = _sorted_ids((*seed.left.candidate_ids, *seed.right.candidate_ids))
        seed_id = _proposal_seed_id(
            source_page=candidate_manifest.source_page,
            candidate_ids=candidate_ids,
            geometry=seed.proposed,
            config_id=resolved_config.config_id,
        )
        if seed_id in seen_seed_ids:
            continue
        seen_seed_ids.add(seed_id)
        matched = [item for item in accepted if _accepted_match(seed.proposed, item.geometry)]
        if matched:
            covered_accepted.update(item.stable_entity_id for item in matched)
            continue

        groups = tuple(
            sorted(
                {
                    group_by_candidate[item].ownership_group_id
                    for item in candidate_ids
                    if item in group_by_candidate
                }
            )
        )
        evidence: list[ReconstructionEvidence] = [
            ReconstructionEvidence.create(
                reason_code="COLLINEAR_SUPPORT",
                candidate_ids=candidate_ids,
                weight=0.26,
                details={
                    "angular_difference_degrees": seed.angle_difference,
                    "cross_track_distance": seed.cross_track_distance,
                },
            ),
            ReconstructionEvidence.create(
                reason_code="COMPATIBLE_LINE_WIDTH",
                candidate_ids=candidate_ids,
                weight=0.12,
                details={"width_ratio": seed.width_ratio},
            ),
            ReconstructionEvidence.create(
                reason_code="REASONABLE_GAP",
                candidate_ids=candidate_ids,
                weight=0.16,
                details={"gap_length": seed.gap_length},
            ),
        ]
        conflicts: list[ReconstructionConflict] = []
        gap_geometry = LineGeometry.create(seed.gap_start, seed.gap_end, seed.proposed.width)
        gap_region = _region_for_line(gap_geometry, max(2.0 * scale, seed.proposed.width))
        overlaps = [item for item in text_like if _regions_intersect(gap_region, item.source_region)]
        if overlaps:
            overlap_cases += 1
            evidence.append(
                ReconstructionEvidence.create(
                    reason_code="FOREGROUND_OCCLUSION",
                    candidate_ids=(*candidate_ids, *(item.stable_candidate_id for item in overlaps)),
                    weight=0.05,
                    details={"candidate_kinds": sorted(item.candidate_kind.value for item in overlaps)},
                )
            )

        explicit_occlusion = any(
            relation_by_group[group_id].final_cad_relation
            is OwnershipSemanticRelation.OCCLUDED_BACKGROUND
            for group_id in groups
            if group_id in relation_by_group
        )
        table_support: list[DraftsmanCandidateRecord] = []
        for item in rois:
            payload = item.payload
            if not isinstance(payload, StructuralRoiCandidatePayload):
                continue
            if len(
                set(payload.related_line_candidate_ids).intersection(candidate_ids)
            ) >= 2 or (
                item.candidate_kind is CandidateKind.TABLE_REGION
                and _regions_intersect(item.source_region, gap_region)
            ):
                table_support.append(item)
        if table_support:
            evidence.append(
                ReconstructionEvidence.create(
                    reason_code="TABLE_OR_RECTILINEAR_SUPPORT",
                    candidate_ids=(*candidate_ids, *(item.stable_candidate_id for item in table_support)),
                    weight=0.08,
                    details={"region_count": len(table_support)},
                )
            )

        family_support = False
        for geometry in all_unique_lines:
            if geometry in {seed.left.geometry, seed.right.geometry}:
                continue
            if _angle_difference(seed.proposed, geometry) > resolved_config.angular_tolerance_degrees:
                continue
            if _point_line_distance(geometry.start, seed.proposed) > resolved_config.family_maximum_offset_px * scale:
                continue
            axis = _unit(seed.proposed)
            projected = sorted(
                (
                    (geometry.start[0] - seed.proposed.start[0]) * axis[0] + (geometry.start[1] - seed.proposed.start[1]) * axis[1],
                    (geometry.end[0] - seed.proposed.start[0]) * axis[0] + (geometry.end[1] - seed.proposed.start[1]) * axis[1],
                )
            )
            gap_projection = sorted(
                (
                    (seed.gap_start[0] - seed.proposed.start[0]) * axis[0] + (seed.gap_start[1] - seed.proposed.start[1]) * axis[1],
                    (seed.gap_end[0] - seed.proposed.start[0]) * axis[0] + (seed.gap_end[1] - seed.proposed.start[1]) * axis[1],
                )
            )
            if projected[0] <= gap_projection[0] and projected[1] >= gap_projection[1]:
                family_support = True
                break
        if family_support:
            evidence.append(
                ReconstructionEvidence.create(
                    reason_code="PARALLEL_LINE_FAMILY_SUPPORT",
                    candidate_ids=candidate_ids,
                    weight=0.06,
                    details={"support_present": True},
                )
            )

        crossing_ids: list[str] = []
        for crossing_line in line_evidence:
            if set(crossing_line.candidate_ids).intersection(candidate_ids):
                continue
            angle = _angle_difference(gap_geometry, crossing_line.geometry)
            if angle < resolved_config.crossing_minimum_angle_degrees or angle > 180.0 - resolved_config.crossing_minimum_angle_degrees:
                continue
            if _segments_intersect(
                seed.gap_start,
                seed.gap_end,
                crossing_line.geometry.start,
                crossing_line.geometry.end,
            ):
                crossing_ids.extend(crossing_line.candidate_ids)
        if crossing_ids:
            crossing_rejected += 1
            conflicts.append(
                ReconstructionConflict.create(
                    conflict_code="COMPETING_INTERSECTION",
                    candidate_ids=(*candidate_ids, *crossing_ids),
                    details={"crossing_candidate_count": len(set(crossing_ids))},
                )
            )

        competing = False
        for side in (seed.left, seed.right):
            choices = sorted(
                endpoint_choices[
                    (side.representative_id, _pair_endpoint_index(side, seed))
                ],
                key=lambda item: (-item[1], item[0]),
            )
            if len(choices) >= 2 and choices[1][1] >= choices[0][1] - resolved_config.competing_score_margin:
                competing = True
        if competing:
            conflicts.append(
                ReconstructionConflict.create(
                    conflict_code="COMPETING_CONTINUATION",
                    candidate_ids=candidate_ids,
                    details={"score_margin": resolved_config.competing_score_margin},
                )
            )

        ambiguous_ownership = any(
            group_by_candidate[item].decision_state is not OwnershipDecisionState.RESOLVED
            for item in candidate_ids
            if item in group_by_candidate
        )
        structure_supported = all(
            any(
                hypothesis.ownership_kind is OwnershipKind.STRUCTURE
                for hypothesis in group_by_candidate[item].hypotheses
            )
            for item in candidate_ids
            if item in group_by_candidate
        )
        confidence = seed.geometry_confidence
        confidence += 0.08 if table_support else 0.0
        confidence += 0.06 if family_support else 0.0
        if source_raster_evidence is not None:
            ratio = source_raster_evidence.line_foreground_ratio(
                seed.gap_start,
                seed.gap_end,
                resolved_config.source_sample_radius_px * scale,
            )
            evidence.append(
                ReconstructionEvidence.create(
                    reason_code="SOURCE_RASTER_GAP_EVIDENCE",
                    candidate_ids=candidate_ids,
                    weight=0.04 if ratio >= 0.15 else 0.0,
                    details={"foreground_ratio": ratio, "raster_sha256": source_raster_evidence.raster_sha256},
                )
            )
            confidence += 0.04 if ratio >= 0.15 else 0.0
        confidence = _score(confidence)

        short_glyph_like = min(seed.left.geometry.length, seed.right.geometry.length) <= resolved_config.glyph_like_max_length_px * scale and bool(overlaps)
        has_logo = any(item.candidate_kind in {CandidateKind.LOGO, CandidateKind.SIGNATURE} for item in overlaps)
        strong_occluded_geometry = (
            seed.angle_difference <= resolved_config.angular_tolerance_degrees * 0.35
            and seed.cross_track_distance <= resolved_config.cross_track_tolerance_px * scale * 0.5
            and confidence >= resolved_config.auto_reconstruct_confidence
        )
        occluded_allowed = bool(overlaps) and (explicit_occlusion or strong_occluded_geometry) and not short_glyph_like and not has_logo
        if occluded_allowed:
            occluded_count += 1
        if crossing_ids or competing or short_glyph_like or has_logo:
            state = ReconstructionState.PROVISIONAL
            reason = (
                "GEOMETRIC_CONFLICT"
                if crossing_ids
                else "LINE_CONTINUATION_AMBIGUOUS"
                if competing
                else "STRUCTURE_TEXT_OWNERSHIP_CONFLICT"
            )
        elif ambiguous_ownership and not occluded_allowed:
            state = ReconstructionState.PROVISIONAL
            reason = "STRUCTURE_TEXT_OWNERSHIP_CONFLICT"
        elif confidence >= resolved_config.auto_reconstruct_confidence and structure_supported:
            state = ReconstructionState.RECONSTRUCTED
            reason = None
        elif confidence >= resolved_config.provisional_confidence:
            state = ReconstructionState.PROVISIONAL
            reason = "LOW_CONFIDENCE_RECONSTRUCTION"
        else:
            state = ReconstructionState.UNRESOLVED
            reason = "UNRESOLVED_LINE_CONTINUATION"

        if table_support:
            kind = ReconstructionKind.TABLE_OR_RECTILINEAR_EDGE_COMPLETION
        elif family_support:
            kind = ReconstructionKind.LINE_FAMILY_COMPLETION
        elif max(seed.left.geometry.length, seed.right.geometry.length) >= 3.0 * min(seed.left.geometry.length, seed.right.geometry.length):
            kind = ReconstructionKind.CONTINUATION
        else:
            kind = ReconstructionKind.COLLINEAR_GAP_BRIDGE
        proposal, review = _make_proposal(
            source_page=candidate_manifest.source_page,
            transform_id=candidate_manifest.transform.transform_id,
            config=resolved_config,
            seed=seed,
            candidate_ids=candidate_ids,
            ownership_group_ids=groups,
            kind=kind,
            confidence=confidence,
            state=state,
            evidence=evidence,
            conflicts=conflicts,
            review_reason=reason,
            diagnostic_metadata={
                "shadow_only": True,
                "gap_start": list(seed.gap_start),
                "gap_end": list(seed.gap_end),
                "gap_length": seed.gap_length,
                "explicit_occluded_background": explicit_occlusion,
                "occluded_background": occluded_allowed,
                "table_support": bool(table_support),
                "line_family_support": family_support,
            },
        )
        proposals.append(proposal)
        if review is not None:
            reviews.append(review)
        gaps.append(seed.gap_length)

    proposals_tuple = tuple(sorted(proposals, key=lambda item: item.stable_proposal_id))
    reviews_tuple = tuple(sorted(reviews, key=lambda item: (-item.risk_score, item.review_item_id)))
    metrics = ReconstructionMetrics(
        source_geometry_candidates=sum(item.candidate_kind is CandidateKind.LINE_SEGMENT for item in candidates),
        reconstruction_proposals=len(proposals_tuple),
        reconstructed=sum(item.state is ReconstructionState.RECONSTRUCTED for item in proposals_tuple),
        provisional=sum(item.state is ReconstructionState.PROVISIONAL for item in proposals_tuple),
        unresolved=sum(item.state is ReconstructionState.UNRESOLVED for item in proposals_tuple),
        duplicate_evidence_collapsed=duplicate_count,
        crossing_conflict_rejected=crossing_rejected,
        text_structure_overlap_cases=overlap_cases,
        occluded_background_proposals=occluded_count,
        mean_gap_length=_round(mean(gaps)) if gaps else 0.0,
        median_gap_length=_round(median(gaps)) if gaps else 0.0,
        max_gap_length=_round(max(gaps)) if gaps else 0.0,
        rc3_preserved=len(accepted),
        rc3_hypothesis_coverage=len(covered_accepted),
    )
    return DraftsmanGeometryReconstructionManifest(
        source_page=candidate_manifest.source_page,
        transform_id=candidate_manifest.transform.transform_id,
        candidate_manifest_id=candidate_manifest.manifest_id,
        ownership_manifest_id=ownership_manifest.manifest_id,
        ownership_relation_ledger_id=None if relation_ledger is None else relation_ledger.ledger_id,
        config=resolved_config,
        source_raster_evidence_sha256=None if source_raster_evidence is None else source_raster_evidence.raster_sha256,
        accepted_reconstructions=accepted,
        proposals=proposals_tuple,
        review_items=reviews_tuple,
        metrics=metrics,
    )


def reconstruction_manifest_sha256(
    manifest: DraftsmanGeometryReconstructionManifest,
) -> str:
    return sha256(manifest.canonical_bytes()).hexdigest()
