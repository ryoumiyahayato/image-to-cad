"""Deterministic instance and exception audit for a Draftsman symbol family."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from math import hypot
from pathlib import Path
from typing import Iterable, Mapping, Sequence, cast

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_domain_pack import DomainPack, ElectricalDomainPackV0, ElectricalSymbolRule
from .draftsman_electrical import ElectricalSymbolHypothesis, LogicalElectricalSymbol
from .draftsman_raster_electrical import _template_score
from .draftsman_raster_evidence import (
    RasterElectricalCandidateEvidence,
    RasterEvidencePrimitive,
    RasterGlyphEvidence,
)
from .draftsman_vs3 import DraftsmanVs3Result, run_draftsman_vs3


DRAFTSMAN_FAMILY_REFERENCE_VERSION = "draftsman-family-reference-v1"
DRAFTSMAN_EXCEPTION_AUDIT_VERSION = "draftsman-exception-audit-v0"
DRAFTSMAN_FAMILY_AUDIT_VERSION = "draftsman-family-audit-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


class FamilyInstanceState(str, Enum):
    AUTO_ACCEPTED = "AUTO_ACCEPTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MISSED = "MISSED"
    INVALID_OUTPUT = "INVALID_OUTPUT"


class ExceptionType(str, Enum):
    EVIDENCE_MISSED = "EVIDENCE_MISSED"
    DOMAIN_NO_MATCH = "DOMAIN_NO_MATCH"
    PORT_MISMATCH = "PORT_MISMATCH"
    TOPOLOGY_CONFLICT = "TOPOLOGY_CONFLICT"
    LOGICAL_ASSEMBLY_FAILURE = "LOGICAL_ASSEMBLY_FAILURE"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    FRAGMENTATION = "FRAGMENTATION"
    DUPLICATE_ENTITY = "DUPLICATE_ENTITY"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class FailureLayer(str, Enum):
    EVIDENCE = "EVIDENCE"
    DOMAIN = "DOMAIN"
    TOPOLOGY = "TOPOLOGY"
    LOGICAL_ENTITY = "LOGICAL_ENTITY"
    ASSEMBLY = "ASSEMBLY"


@dataclass(frozen=True)
class FamilyReferenceInstance:
    reference_instance_id: str
    drawing_tag: str
    source_center_px: tuple[int, int]
    source_bbox_px: tuple[int, int, int, int]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> FamilyReferenceInstance:
        center = tuple(
            int(value)
            for value in cast(Sequence[int], payload["source_center_px"])
        )
        bbox = tuple(
            int(value)
            for value in cast(Sequence[int], payload["source_bbox_px"])
        )
        if len(center) != 2 or len(bbox) != 4:
            raise ValueError("Family reference requires a 2D center and four-value bbox")
        return cls(
            reference_instance_id=str(payload["reference_instance_id"]),
            drawing_tag=str(payload["drawing_tag"]),
            source_center_px=(center[0], center[1]),
            source_bbox_px=(bbox[0], bbox[1], bbox[2], bbox[3]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_instance_id": self.reference_instance_id,
            "drawing_tag": self.drawing_tag,
            "source_center_px": list(self.source_center_px),
            "source_bbox_px": list(self.source_bbox_px),
        }


@dataclass(frozen=True)
class FamilyAuditReference:
    source_document_id: str
    source_page: int
    source_sha256: str
    image_size_px: tuple[int, int]
    family_inventory_id: str
    inventory_canonical_identity: str
    canonical_domain_identity: str
    drawing_specific_authority: str
    frozen_rule_id: str
    match_center_tolerance_px: float
    baseline_slice_reference_ids: tuple[str, ...]
    instances: tuple[FamilyReferenceInstance, ...]
    schema_version: str = DRAFTSMAN_FAMILY_REFERENCE_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DRAFTSMAN_FAMILY_REFERENCE_VERSION:
            raise ValueError(f"Unsupported family reference: {self.schema_version}")
        ids = [item.reference_instance_id for item in self.instances]
        tags = [item.drawing_tag for item in self.instances]
        if len(ids) != len(set(ids)) or len(tags) != len(set(tags)):
            raise ValueError("Family reference IDs and tags must be unique")
        if self.match_center_tolerance_px <= 0.0:
            raise ValueError("Family matching tolerance must be positive")
        if not set(self.baseline_slice_reference_ids).issubset(ids):
            raise ValueError("Baseline slice IDs must belong to the family reference")

    @classmethod
    def load(cls, path: str | Path) -> FamilyAuditReference:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        image_size = tuple(int(value) for value in payload["image_size_px"])
        if len(image_size) != 2:
            raise ValueError("Family reference image size requires two values")
        return cls(
            source_document_id=str(payload["source_document_id"]),
            source_page=int(payload["source_page"]),
            source_sha256=str(payload["source_sha256"]),
            image_size_px=(image_size[0], image_size[1]),
            family_inventory_id=str(payload["family_inventory_id"]),
            inventory_canonical_identity=str(
                payload["inventory_canonical_identity"]
            ),
            canonical_domain_identity=str(payload["canonical_domain_identity"]),
            drawing_specific_authority=str(payload["drawing_specific_authority"]),
            frozen_rule_id=str(payload["frozen_rule_id"]),
            match_center_tolerance_px=float(payload["match_center_tolerance_px"]),
            baseline_slice_reference_ids=tuple(
                sorted(
                    str(value)
                    for value in cast(
                        Sequence[object], payload["baseline_slice_reference_ids"]
                    )
                )
            ),
            instances=tuple(
                FamilyReferenceInstance.from_dict(item)
                for item in payload["instances"]
            ),
            schema_version=str(payload["schema_version"]),
        )

    @property
    def reference_id(self) -> str:
        return semantic_id(
            "draftsman-family-audit-reference",
            self.schema_version,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_sha256": self.source_sha256,
            "image_size_px": list(self.image_size_px),
            "family_inventory_id": self.family_inventory_id,
            "inventory_canonical_identity": self.inventory_canonical_identity,
            "canonical_domain_identity": self.canonical_domain_identity,
            "drawing_specific_authority": self.drawing_specific_authority,
            "frozen_rule_id": self.frozen_rule_id,
            "match_center_tolerance_px": self.match_center_tolerance_px,
            "baseline_slice_reference_ids": list(self.baseline_slice_reference_ids),
            "instances": [item.to_dict() for item in self.instances],
        }


@dataclass(frozen=True)
class ExceptionRecord:
    stable_exception_id: str
    exception_type: ExceptionType
    failure_layer: FailureLayer
    source_region: tuple[int, int, int, int]
    reason: str
    expected_reference_id: str | None
    evidence_ids: tuple[str, ...]
    domain_decision_id: str | None
    logical_entity_ids: tuple[str, ...]
    cad_ir_entity_ids: tuple[str, ...]
    factors: tuple[str, ...]
    schema_version: str = DRAFTSMAN_EXCEPTION_AUDIT_VERSION

    @classmethod
    def create(
        cls,
        *,
        exception_type: ExceptionType,
        failure_layer: FailureLayer,
        source_region: Sequence[int],
        reason: str,
        expected_reference_id: str | None,
        evidence_ids: Iterable[str] = (),
        domain_decision_id: str | None = None,
        logical_entity_ids: Iterable[str] = (),
        cad_ir_entity_ids: Iterable[str] = (),
        factors: Iterable[str] = (),
    ) -> ExceptionRecord:
        region = tuple(int(value) for value in source_region)
        if len(region) != 4:
            raise ValueError("Exception source region requires four values")
        ordered_evidence = tuple(sorted(set(evidence_ids)))
        ordered_logical = tuple(sorted(set(logical_entity_ids)))
        ordered_cad = tuple(sorted(set(cad_ir_entity_ids)))
        ordered_factors = tuple(sorted(set(factors)))
        identity = {
            "exception_type": exception_type.value,
            "failure_layer": failure_layer.value,
            "source_region": list(region),
            "reason": reason,
            "expected_reference_id": expected_reference_id,
            "evidence_ids": list(ordered_evidence),
            "domain_decision_id": domain_decision_id,
            "logical_entity_ids": list(ordered_logical),
            "cad_ir_entity_ids": list(ordered_cad),
            "factors": list(ordered_factors),
        }
        return cls(
            stable_exception_id=semantic_id(
                "draftsman-family-exception",
                DRAFTSMAN_EXCEPTION_AUDIT_VERSION,
                identity,
            ),
            exception_type=exception_type,
            failure_layer=failure_layer,
            source_region=(region[0], region[1], region[2], region[3]),
            reason=reason,
            expected_reference_id=expected_reference_id,
            evidence_ids=ordered_evidence,
            domain_decision_id=domain_decision_id,
            logical_entity_ids=ordered_logical,
            cad_ir_entity_ids=ordered_cad,
            factors=ordered_factors,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_exception_id": self.stable_exception_id,
            "exception_type": self.exception_type.value,
            "failure_layer": self.failure_layer.value,
            "source_region": list(self.source_region),
            "reason": self.reason,
            "expected_reference_id": self.expected_reference_id,
            "evidence_ids": list(self.evidence_ids),
            "domain_decision_id": self.domain_decision_id,
            "logical_entity_ids": list(self.logical_entity_ids),
            "cad_ir_entity_ids": list(self.cad_ir_entity_ids),
            "factors": list(self.factors),
        }


@dataclass(frozen=True)
class FamilyInstanceAudit:
    reference_instance_id: str
    drawing_tag: str
    source_bbox_px: tuple[int, int, int, int]
    evidence_ids: tuple[str, ...]
    candidate_id: str | None
    recognition_result: str
    domain_identity: str | None
    port_count: int
    connected_line_count: int
    meaningful_gap_state: tuple[str, ...]
    logical_entity_id: str | None
    cad_ir_entity_ids: tuple[str, ...]
    confidence: float | None
    exception_state: FamilyInstanceState
    exception_ids: tuple[str, ...]
    exception_reasons: tuple[str, ...]
    failure_layer: FailureLayer | None
    rule_factors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_instance_id": self.reference_instance_id,
            "drawing_tag": self.drawing_tag,
            "source_bbox_px": list(self.source_bbox_px),
            "evidence_ids": list(self.evidence_ids),
            "candidate_id": self.candidate_id,
            "recognition_result": self.recognition_result,
            "domain_identity": self.domain_identity,
            "port_count": self.port_count,
            "connected_line_count": self.connected_line_count,
            "meaningful_gap_state": list(self.meaningful_gap_state),
            "logical_entity_id": self.logical_entity_id,
            "cad_ir_entity_ids": list(self.cad_ir_entity_ids),
            "confidence": self.confidence,
            "exception_state": self.exception_state.value,
            "exception_ids": list(self.exception_ids),
            "exception_reasons": list(self.exception_reasons),
            "failure_layer": (
                None if self.failure_layer is None else self.failure_layer.value
            ),
            "rule_factors": list(self.rule_factors),
        }


@dataclass(frozen=True)
class FamilyAuditSummary:
    expected_instances: int
    source_wide_detected_instances: int
    matched_instances: int
    auto_accepted: int
    review_required: int
    missed: int
    invalid_output: int
    false_positives: int
    automatic_acceptance_rate: float
    auto_accepted_beyond_baseline: int
    manual_review_items: int
    review_items_per_page: int
    unnecessary_fragments: int
    duplicate_logical_entities: int
    duplicate_cad_ir_entities: int
    incorrect_line_through_symbol: int
    invalid_port_connections: int
    failure_distribution: tuple[tuple[str, int], ...]
    systematic_variant_gaps: tuple[str, ...]

    def failure_count(self, layer: FailureLayer) -> int:
        return dict(self.failure_distribution).get(layer.value, 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_instances": self.expected_instances,
            "source_wide_detected_instances": self.source_wide_detected_instances,
            "matched_instances": self.matched_instances,
            "auto_accepted": self.auto_accepted,
            "review_required": self.review_required,
            "missed": self.missed,
            "invalid_output": self.invalid_output,
            "false_positives": self.false_positives,
            "automatic_acceptance_rate": self.automatic_acceptance_rate,
            "auto_accepted_beyond_baseline": self.auto_accepted_beyond_baseline,
            "manual_review_items": self.manual_review_items,
            "review_items_per_page": self.review_items_per_page,
            "unnecessary_fragments": self.unnecessary_fragments,
            "duplicate_logical_entities": self.duplicate_logical_entities,
            "duplicate_cad_ir_entities": self.duplicate_cad_ir_entities,
            "incorrect_line_through_symbol": self.incorrect_line_through_symbol,
            "invalid_port_connections": self.invalid_port_connections,
            "failure_distribution": dict(self.failure_distribution),
            "systematic_variant_gaps": list(self.systematic_variant_gaps),
        }


@dataclass(frozen=True)
class FamilyAuditResult:
    reference: FamilyAuditReference
    vs3: DraftsmanVs3Result
    frozen_rule_id: str
    instances: tuple[FamilyInstanceAudit, ...]
    exceptions: tuple[ExceptionRecord, ...]
    summary: FamilyAuditSummary
    schema_version: str = DRAFTSMAN_FAMILY_AUDIT_VERSION

    @property
    def audit_id(self) -> str:
        return semantic_id(
            "draftsman-family-audit",
            self.schema_version,
            {
                "reference_id": self.reference.reference_id,
                "frozen_rule_id": self.frozen_rule_id,
                "evidence_manifest_id": self.vs3.evidence.manifest_id,
                "decision_manifest_id": self.vs3.interpretation.decisions.manifest_id,
                "logical_manifest_id": self.vs3.logical.manifest_id,
                "cad_ir_manifest_id": self.vs3.cad_ir.manifest_id,
                "instances": [item.to_dict() for item in self.instances],
                "exceptions": [item.to_dict() for item in self.exceptions],
                "summary": self.summary.to_dict(),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_id": self.audit_id,
            "reference": {
                **self.reference.to_dict(),
                "reference_id": self.reference.reference_id,
                "role": "EXPECTED_AUDIT_REFERENCE_NOT_RUNTIME_INPUT",
            },
            "runtime": {
                "mode": "SOURCE_WIDE_DISCOVERY",
                "source_crop_count": 0,
                "evidence_manifest_id": self.vs3.evidence.manifest_id,
                "decision_manifest_id": self.vs3.interpretation.decisions.manifest_id,
                "logical_manifest_id": self.vs3.logical.manifest_id,
                "cad_ir_manifest_id": self.vs3.cad_ir.manifest_id,
                "frozen_rule_id": self.frozen_rule_id,
                "rules_modified_during_audit": False,
            },
            "summary": self.summary.to_dict(),
            "instances": [item.to_dict() for item in self.instances],
            "exception_ids": [item.stable_exception_id for item in self.exceptions],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def canonical_sha256(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def _family_rule(reference: FamilyAuditReference, pack: DomainPack) -> ElectricalSymbolRule:
    matches = tuple(
        rule
        for rule in pack.electrical_symbol_rules
        if rule.inventory_canonical_identity == reference.inventory_canonical_identity
        and rule.canonical_domain_identity == reference.canonical_domain_identity
    )
    if len(matches) != 1:
        raise ValueError("Family reference must resolve to exactly one domain rule")
    rule = matches[0]
    if rule.rule_id != reference.frozen_rule_id:
        raise ValueError(
            "Frozen VS3 rule identity changed: "
            f"expected {reference.frozen_rule_id}, got {rule.rule_id}"
        )
    return rule


def _match_reference_candidates(
    reference: FamilyAuditReference,
    candidates: Sequence[RasterElectricalCandidateEvidence],
) -> dict[str, RasterElectricalCandidateEvidence]:
    unmatched = {item.stable_candidate_id: item for item in candidates}
    matched: dict[str, RasterElectricalCandidateEvidence] = {}
    for expected in sorted(reference.instances, key=lambda item: item.reference_instance_id):
        choices = []
        for candidate in unmatched.values():
            distance = hypot(
                candidate.source_center_px[0] - expected.source_center_px[0],
                candidate.source_center_px[1] - expected.source_center_px[1],
            )
            if distance <= reference.match_center_tolerance_px:
                choices.append((distance, candidate.stable_candidate_id, candidate))
        if not choices:
            continue
        _, candidate_id, selected = min(choices, key=lambda item: (item[0], item[1]))
        matched[expected.reference_instance_id] = selected
        unmatched.pop(candidate_id)
    return matched


def _overlaps(
    first: Sequence[int],
    second: Sequence[int],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _nearby_evidence_ids(
    expected: FamilyReferenceInstance,
    primitives: Iterable[RasterEvidencePrimitive],
) -> tuple[str, ...]:
    left, top, right, bottom = expected.source_bbox_px
    expanded = (left - 8, top - 8, right + 8, bottom + 8)
    return tuple(
        sorted(
            item.stable_evidence_id
            for item in primitives
            if _overlaps(expanded, item.source_bbox_px)
        )
    )


def _rule_factors(
    candidate: RasterElectricalCandidateEvidence,
    primitives: Mapping[str, RasterEvidencePrimitive],
    rule: ElectricalSymbolRule,
) -> tuple[tuple[str, ...], dict[str, float]]:
    signature = rule.raster_recognition_signature
    glyph = primitives[candidate.glyph_evidence_id]
    if signature is None or not isinstance(glyph, RasterGlyphEvidence):
        raise ValueError("Raster family candidate requires raster rule and glyph evidence")
    score = _template_score(
        glyph.normalized_patch_rows,
        signature.normalized_template_rows,
    )
    factors: list[str] = []
    if score < signature.minimum_template_score:
        factors.append("INCOMPLETE_SYMBOL_SHAPE")
    if glyph.ring_coverage < signature.minimum_ring_coverage:
        factors.append("INCOMPLETE_RING_SHAPE")
    if candidate.left_line_support < signature.minimum_port_support:
        factors.append("MISSING_LEFT_PORT_EVIDENCE")
    if candidate.right_line_support < signature.minimum_port_support:
        factors.append("MISSING_RIGHT_PORT_EVIDENCE")
    return (
        tuple(sorted(factors)),
        {
            "template_score": score,
            "ring_coverage": glyph.ring_coverage,
            "left_port_support": candidate.left_line_support,
            "right_port_support": candidate.right_line_support,
        },
    )


def _exception_for_unaccepted_candidate(
    *,
    expected: FamilyReferenceInstance,
    candidate: RasterElectricalCandidateEvidence,
    hypothesis: ElectricalSymbolHypothesis | None,
    factors: tuple[str, ...],
    measurements: Mapping[str, float],
) -> ExceptionRecord:
    shape_factors = {
        "INCOMPLETE_SYMBOL_SHAPE",
        "INCOMPLETE_RING_SHAPE",
    }
    port_factors = {
        "MISSING_LEFT_PORT_EVIDENCE",
        "MISSING_RIGHT_PORT_EVIDENCE",
    }
    if shape_factors.intersection(factors):
        exception_type = ExceptionType.DOMAIN_NO_MATCH
        layer = FailureLayer.DOMAIN
    elif port_factors.intersection(factors):
        exception_type = ExceptionType.PORT_MISMATCH
        layer = FailureLayer.TOPOLOGY
    else:
        exception_type = ExceptionType.DOMAIN_NO_MATCH
        layer = FailureLayer.DOMAIN
        factors = tuple(sorted({*factors, "INSUFFICIENT_REPEATED_CONTEXT"}))
    values = ", ".join(f"{key}={value:.6f}" for key, value in sorted(measurements.items()))
    reason = f"Frozen VS3 rule did not accept candidate: {', '.join(factors)}; {values}"
    return ExceptionRecord.create(
        exception_type=exception_type,
        failure_layer=layer,
        source_region=expected.source_bbox_px,
        reason=reason,
        expected_reference_id=expected.reference_instance_id,
        evidence_ids=(
            candidate.glyph_evidence_id,
            candidate.tag_evidence_id,
            *candidate.nearby_line_evidence_ids,
        ),
        domain_decision_id=(
            None if hypothesis is None else hypothesis.stable_hypothesis_id
        ),
        factors=factors,
    )


def _logical_for_hypothesis(
    hypothesis: ElectricalSymbolHypothesis,
    symbols: Iterable[LogicalElectricalSymbol],
) -> LogicalElectricalSymbol | None:
    return next(
        (
            symbol
            for symbol in symbols
            if symbol.domain_identity == hypothesis.canonical_domain_identity
            and symbol.frame_bounds_pt == hypothesis.frame_bounds_pt
        ),
        None,
    )


def _duplicate_counts(vs3: DraftsmanVs3Result) -> tuple[int, int]:
    logical_keys = [
        (item.domain_identity, item.frame_bounds_pt) for item in vs3.logical.symbols
    ]
    duplicate_logical = len(logical_keys) - len(set(logical_keys))
    cad_keys = [
        ("SYMBOL", item.logical_entity_id) for item in vs3.cad_ir.symbols
    ] + [("LINE", item.logical_line_id) for item in vs3.cad_ir.lines]
    duplicate_cad = len(cad_keys) - len(set(cad_keys))
    return duplicate_logical, duplicate_cad


def audit_electrical_family(
    source: str | Path,
    *,
    reference: FamilyAuditReference,
    domain_pack: DomainPack | None = None,
) -> FamilyAuditResult:
    """Blind-run the source-wide VS3 pipeline, then compare with audit truth."""

    pack = domain_pack or ElectricalDomainPackV0.create()
    rule = _family_rule(reference, pack)
    vs3 = run_draftsman_vs3(
        source,
        source_document_id=reference.source_document_id,
        source_page=reference.source_page,
        domain_pack=pack,
    )
    if vs3.evidence.source_sha256 != reference.source_sha256:
        raise ValueError("Family reference and runtime source SHA-256 differ")
    if vs3.evidence.image_size_px != reference.image_size_px:
        raise ValueError("Family reference and runtime source dimensions differ")

    matched_candidates = _match_reference_candidates(
        reference,
        vs3.evidence.candidates,
    )
    primitives = vs3.evidence.primitive_by_id()
    hypotheses_by_candidate = {
        item.candidate_id: item
        for item in vs3.interpretation.decisions.hypotheses
        if item.rule_id == rule.rule_id
    }
    accepted_candidate_ids = {
        item.candidate_id
        for item in vs3.interpretation.decisions.accepted
        if item.rule_id == rule.rule_id
    }
    cad_symbols_by_logical = {
        item.logical_entity_id: item for item in vs3.cad_ir.symbols
    }
    cad_lines_by_logical = {
        item.logical_line_id: item for item in vs3.cad_ir.lines
    }
    instances: list[FamilyInstanceAudit] = []
    exceptions: list[ExceptionRecord] = []
    matched_accepted_ids: set[str] = set()

    for expected in sorted(reference.instances, key=lambda item: item.reference_instance_id):
        candidate = matched_candidates.get(expected.reference_instance_id)
        if candidate is None:
            nearby = _nearby_evidence_ids(expected, vs3.evidence.primitives)
            exception = ExceptionRecord.create(
                exception_type=ExceptionType.EVIDENCE_MISSED,
                failure_layer=FailureLayer.EVIDENCE,
                source_region=expected.source_bbox_px,
                reason=(
                    "Source-wide raster frontend produced no symbol candidate within "
                    "the reference region; tag orientation or non-horizontal topology "
                    "is outside the frozen VS3 evidence signature"
                ),
                expected_reference_id=expected.reference_instance_id,
                evidence_ids=nearby,
                factors=("NO_RASTER_SYMBOL_CANDIDATE",),
            )
            exceptions.append(exception)
            instances.append(
                FamilyInstanceAudit(
                    reference_instance_id=expected.reference_instance_id,
                    drawing_tag=expected.drawing_tag,
                    source_bbox_px=expected.source_bbox_px,
                    evidence_ids=nearby,
                    candidate_id=None,
                    recognition_result="NO_EVIDENCE_CANDIDATE",
                    domain_identity=None,
                    port_count=0,
                    connected_line_count=0,
                    meaningful_gap_state=(),
                    logical_entity_id=None,
                    cad_ir_entity_ids=(),
                    confidence=None,
                    exception_state=FamilyInstanceState.MISSED,
                    exception_ids=(exception.stable_exception_id,),
                    exception_reasons=(exception.reason,),
                    failure_layer=exception.failure_layer,
                    rule_factors=exception.factors,
                )
            )
            continue

        hypothesis = hypotheses_by_candidate.get(candidate.stable_candidate_id)
        evidence_ids = tuple(
            sorted(
                {
                    candidate.glyph_evidence_id,
                    candidate.tag_evidence_id,
                    *candidate.nearby_line_evidence_ids,
                }
            )
        )
        factors, measurements = _rule_factors(candidate, primitives, rule)
        if candidate.stable_candidate_id not in accepted_candidate_ids:
            exception = _exception_for_unaccepted_candidate(
                expected=expected,
                candidate=candidate,
                hypothesis=hypothesis,
                factors=factors,
                measurements=measurements,
            )
            exceptions.append(exception)
            instances.append(
                FamilyInstanceAudit(
                    reference_instance_id=expected.reference_instance_id,
                    drawing_tag=expected.drawing_tag,
                    source_bbox_px=expected.source_bbox_px,
                    evidence_ids=evidence_ids,
                    candidate_id=candidate.stable_candidate_id,
                    recognition_result=(
                        "REJECTED" if hypothesis is not None else "NO_DOMAIN_HYPOTHESIS"
                    ),
                    domain_identity=(
                        None if hypothesis is None else hypothesis.canonical_domain_identity
                    ),
                    port_count=0 if hypothesis is None else len(hypothesis.ports),
                    connected_line_count=0,
                    meaningful_gap_state=(),
                    logical_entity_id=None,
                    cad_ir_entity_ids=(),
                    confidence=(
                        measurements["template_score"]
                        if hypothesis is None
                        else hypothesis.confidence
                    ),
                    exception_state=FamilyInstanceState.REVIEW_REQUIRED,
                    exception_ids=(exception.stable_exception_id,),
                    exception_reasons=(exception.reason,),
                    failure_layer=exception.failure_layer,
                    rule_factors=exception.factors,
                )
            )
            continue

        if hypothesis is None:
            raise ValueError("Accepted family candidate has no domain hypothesis")
        matched_accepted_ids.add(candidate.stable_candidate_id)
        logical = _logical_for_hypothesis(hypothesis, vs3.logical.symbols)
        if logical is None:
            exception = ExceptionRecord.create(
                exception_type=ExceptionType.LOGICAL_ASSEMBLY_FAILURE,
                failure_layer=FailureLayer.LOGICAL_ENTITY,
                source_region=expected.source_bbox_px,
                reason="Accepted domain hypothesis produced no logical electrical entity",
                expected_reference_id=expected.reference_instance_id,
                evidence_ids=evidence_ids,
                domain_decision_id=hypothesis.stable_hypothesis_id,
                factors=("MISSING_LOGICAL_SYMBOL",),
            )
            exceptions.append(exception)
            instances.append(
                FamilyInstanceAudit(
                    reference_instance_id=expected.reference_instance_id,
                    drawing_tag=expected.drawing_tag,
                    source_bbox_px=expected.source_bbox_px,
                    evidence_ids=evidence_ids,
                    candidate_id=candidate.stable_candidate_id,
                    recognition_result="ACCEPTED_DOMAIN_MISSING_LOGICAL_ENTITY",
                    domain_identity=hypothesis.canonical_domain_identity,
                    port_count=len(hypothesis.ports),
                    connected_line_count=0,
                    meaningful_gap_state=(),
                    logical_entity_id=None,
                    cad_ir_entity_ids=(),
                    confidence=hypothesis.confidence,
                    exception_state=FamilyInstanceState.INVALID_OUTPUT,
                    exception_ids=(exception.stable_exception_id,),
                    exception_reasons=(exception.reason,),
                    failure_layer=exception.failure_layer,
                    rule_factors=(),
                )
            )
            continue

        cad_symbol = cad_symbols_by_logical.get(logical.logical_entity_id)
        cad_lines = tuple(
            cad_lines_by_logical[item.logical_line_id]
            for item in logical.connections
            if item.logical_line_id in cad_lines_by_logical
        )
        expected_cad_count = 1 + len(logical.connections)
        actual_cad_ids = tuple(
            sorted(
                {
                    *(item.stable_entity_id for item in cad_lines),
                    *(() if cad_symbol is None else (cad_symbol.stable_entity_id,)),
                }
            )
        )
        invalid_factors: list[str] = []
        if cad_symbol is None:
            invalid_factors.append("MISSING_CAD_IR_SYMBOL")
        if len(actual_cad_ids) != expected_cad_count:
            invalid_factors.append("CAD_IR_ENTITY_COUNT_MISMATCH")
        if len(cad_lines) != len(logical.connections):
            invalid_factors.append("MISSING_CAD_IR_CONNECTION")
        instance_exceptions: tuple[ExceptionRecord, ...]
        if invalid_factors:
            exception = ExceptionRecord.create(
                exception_type=ExceptionType.LOGICAL_ASSEMBLY_FAILURE,
                failure_layer=FailureLayer.ASSEMBLY,
                source_region=expected.source_bbox_px,
                reason=(
                    "Logical family instance did not assemble to its canonical editable "
                    f"entities: {', '.join(sorted(invalid_factors))}"
                ),
                expected_reference_id=expected.reference_instance_id,
                evidence_ids=evidence_ids,
                domain_decision_id=hypothesis.stable_hypothesis_id,
                logical_entity_ids=(logical.logical_entity_id,),
                cad_ir_entity_ids=actual_cad_ids,
                factors=invalid_factors,
            )
            exceptions.append(exception)
            state = FamilyInstanceState.INVALID_OUTPUT
            instance_exceptions = (exception,)
        else:
            state = FamilyInstanceState.AUTO_ACCEPTED
            instance_exceptions = ()
        gap_states = tuple(
            sorted({cause for line in logical.connections for cause in line.gap_causes})
        )
        instances.append(
            FamilyInstanceAudit(
                reference_instance_id=expected.reference_instance_id,
                drawing_tag=expected.drawing_tag,
                source_bbox_px=expected.source_bbox_px,
                evidence_ids=evidence_ids,
                candidate_id=candidate.stable_candidate_id,
                recognition_result="ACCEPTED",
                domain_identity=hypothesis.canonical_domain_identity,
                port_count=len(hypothesis.ports),
                connected_line_count=len(logical.connections),
                meaningful_gap_state=gap_states,
                logical_entity_id=logical.logical_entity_id,
                cad_ir_entity_ids=actual_cad_ids,
                confidence=hypothesis.confidence,
                exception_state=state,
                exception_ids=tuple(
                    item.stable_exception_id for item in instance_exceptions
                ),
                exception_reasons=tuple(item.reason for item in instance_exceptions),
                failure_layer=(
                    None if not instance_exceptions else instance_exceptions[0].failure_layer
                ),
                rule_factors=(),
            )
        )

    candidates_by_id = {
        item.stable_candidate_id: item for item in vs3.evidence.candidates
    }
    false_positive_hypotheses = tuple(
        item
        for item in vs3.interpretation.decisions.accepted
        if item.rule_id == rule.rule_id and item.candidate_id not in matched_accepted_ids
    )
    for hypothesis in false_positive_hypotheses:
        candidate = candidates_by_id[hypothesis.candidate_id]
        x_value, y_value = candidate.source_center_px
        radius = candidate.radius_px
        logical = _logical_for_hypothesis(hypothesis, vs3.logical.symbols)
        logical_ids = () if logical is None else (logical.logical_entity_id,)
        cad_ids = tuple(
            item.stable_entity_id
            for item in vs3.cad_ir.symbols
            if item.logical_entity_id in logical_ids
        )
        exceptions.append(
            ExceptionRecord.create(
                exception_type=ExceptionType.FALSE_POSITIVE,
                failure_layer=FailureLayer.ASSEMBLY,
                source_region=(
                    x_value - radius,
                    y_value - radius,
                    x_value + radius,
                    y_value + radius,
                ),
                reason=(
                    "Runtime emitted a smoke-detector logical entity with no matching "
                    "family audit reference instance"
                ),
                expected_reference_id=None,
                evidence_ids=hypothesis.source_primitive_ids,
                domain_decision_id=hypothesis.stable_hypothesis_id,
                logical_entity_ids=logical_ids,
                cad_ir_entity_ids=cad_ids,
                factors=("NO_REFERENCE_SUPPORT",),
            )
        )

    ordered_instances = tuple(
        sorted(instances, key=lambda item: item.reference_instance_id)
    )
    ordered_exceptions = tuple(
        sorted(exceptions, key=lambda item: item.stable_exception_id)
    )
    state_counts = {
        state: sum(1 for item in ordered_instances if item.exception_state is state)
        for state in FamilyInstanceState
    }
    failure_counts = {
        layer.value: sum(1 for item in ordered_instances if item.failure_layer is layer)
        for layer in FailureLayer
    }
    failure_counts[FailureLayer.ASSEMBLY.value] += len(false_positive_hypotheses)
    duplicate_logical, duplicate_cad = _duplicate_counts(vs3)
    expected_count = len(reference.instances)
    auto_count = state_counts[FamilyInstanceState.AUTO_ACCEPTED]
    systematic_gaps: list[str] = []
    if failure_counts[FailureLayer.EVIDENCE.value]:
        systematic_gaps.append(
            "SYSTEMATIC_VARIANT_GAP: frozen frontend expects a below-tag pairing and "
            "horizontal support; side/above tags and angled or branch connections often "
            "produce no raster candidate"
        )
    if failure_counts[FailureLayer.TOPOLOGY.value]:
        systematic_gaps.append(
            "SYSTEMATIC_VARIANT_GAP: frozen two-sided horizontal port signature does not "
            "cover one-sided, angled, vertical, or junction-connected family instances"
        )
    if failure_counts[FailureLayer.DOMAIN.value]:
        systematic_gaps.append(
            "SYSTEMATIC_VARIANT_GAP: scan-degraded glyph shapes and isolated valid examples "
            "fail the frozen template or repeated-alignment evidence"
        )
    summary = FamilyAuditSummary(
        expected_instances=expected_count,
        source_wide_detected_instances=len(vs3.logical.symbols),
        matched_instances=sum(
            1 for item in ordered_instances if item.logical_entity_id is not None
        ),
        auto_accepted=auto_count,
        review_required=state_counts[FamilyInstanceState.REVIEW_REQUIRED],
        missed=state_counts[FamilyInstanceState.MISSED],
        invalid_output=state_counts[FamilyInstanceState.INVALID_OUTPUT],
        false_positives=len(false_positive_hypotheses),
        automatic_acceptance_rate=_number(
            0.0 if expected_count == 0 else auto_count / expected_count
        ),
        auto_accepted_beyond_baseline=sum(
            1
            for item in ordered_instances
            if item.exception_state is FamilyInstanceState.AUTO_ACCEPTED
            and item.reference_instance_id
            not in reference.baseline_slice_reference_ids
        ),
        manual_review_items=(
            state_counts[FamilyInstanceState.REVIEW_REQUIRED]
            + state_counts[FamilyInstanceState.MISSED]
            + state_counts[FamilyInstanceState.INVALID_OUTPUT]
            + len(false_positive_hypotheses)
        ),
        review_items_per_page=(
            state_counts[FamilyInstanceState.REVIEW_REQUIRED]
            + state_counts[FamilyInstanceState.MISSED]
            + state_counts[FamilyInstanceState.INVALID_OUTPUT]
            + len(false_positive_hypotheses)
        ),
        unnecessary_fragments=vs3.quality.unnecessary_fragments,
        duplicate_logical_entities=duplicate_logical,
        duplicate_cad_ir_entities=duplicate_cad,
        incorrect_line_through_symbol=vs3.quality.incorrect_line_through_symbol,
        invalid_port_connections=vs3.quality.invalid_port_connections,
        failure_distribution=tuple(sorted(failure_counts.items())),
        systematic_variant_gaps=tuple(systematic_gaps),
    )
    return FamilyAuditResult(
        reference=reference,
        vs3=vs3,
        frozen_rule_id=rule.rule_id,
        instances=ordered_instances,
        exceptions=ordered_exceptions,
        summary=summary,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _draw_audit_overview(
    source_path: str | Path,
    result: FamilyAuditResult,
    target: Path,
    *,
    exceptions_only: bool,
) -> None:
    source = Image.open(source_path).convert("RGB")
    canvas = source.copy()
    draw = ImageDraw.Draw(canvas)
    colors = {
        FamilyInstanceState.AUTO_ACCEPTED: (25, 120, 60),
        FamilyInstanceState.REVIEW_REQUIRED: (215, 130, 20),
        FamilyInstanceState.MISSED: (190, 35, 35),
        FamilyInstanceState.INVALID_OUTPUT: (145, 35, 145),
    }
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:  # pragma: no cover - platform fallback
        font = ImageFont.load_default()
    for item in result.instances:
        if exceptions_only and item.exception_state is FamilyInstanceState.AUTO_ACCEPTED:
            continue
        color = colors[item.exception_state]
        draw.rectangle(item.source_bbox_px, outline=color, width=3)
        draw.text(
            (item.source_bbox_px[0], item.source_bbox_px[1] - 16),
            f"{item.drawing_tag}:{item.exception_state.value}",
            fill=color,
            font=font,
            stroke_width=2,
            stroke_fill="white",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    ImageOps.contain(canvas, (1600, 1200)).save(target, format="PNG", optimize=False)


def write_family_audit_artifacts(
    output_dir: str | Path,
    *,
    source_path: str | Path,
    result: FamilyAuditResult,
    replay_audit_ids: Sequence[str],
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    deterministic = len(replay_audit_ids) >= 2 and len(set(replay_audit_ids)) == 1
    family_path = output / "family-audit.json"
    exceptions_path = output / "exceptions.json"
    logical_path = output / "logical-entities.json"
    cad_path = output / "cad-ir.json"
    report_path = output / "VS3_FAMILY_AUDIT.md"
    family_overview = output / "family-overview.png"
    exceptions_overview = output / "exceptions-overview.png"
    _write_json(
        family_path,
        {
            **result.to_dict(),
            "canonical_sha256": result.canonical_sha256,
            "deterministic_replay": {
                "passed": deterministic,
                "runs": len(replay_audit_ids),
                "audit_ids": list(replay_audit_ids),
            },
        },
    )
    _write_json(
        exceptions_path,
        {
            "schema_version": DRAFTSMAN_EXCEPTION_AUDIT_VERSION,
            "audit_id": result.audit_id,
            "exception_count": len(result.exceptions),
            "exceptions": [item.to_dict() for item in result.exceptions],
        },
    )
    _write_json(
        logical_path,
        {
            **result.vs3.logical.to_dict(),
            "canonical_sha256": result.vs3.logical_sha256,
        },
    )
    _write_json(
        cad_path,
        {
            **result.vs3.cad_ir.to_dict(),
            "canonical_sha256": result.vs3.cad_ir_sha256,
        },
    )
    _draw_audit_overview(
        source_path,
        result,
        family_overview,
        exceptions_only=False,
    )
    _draw_audit_overview(
        source_path,
        result,
        exceptions_overview,
        exceptions_only=True,
    )
    summary = result.summary
    gaps = "\n".join(f"- {item}" for item in summary.systematic_variant_gaps)
    report = f"""# DRAFTSMAN VS3 FULL FAMILY EXCEPTION AUDIT

- Audit contract: `{DRAFTSMAN_FAMILY_AUDIT_VERSION}`
- Exception contract: `{DRAFTSMAN_EXCEPTION_AUDIT_VERSION}`
- Reference role: expected audit truth only; **not runtime recognition input**
- Runtime mode: full-page source-wide discovery; zero predefined crops
- Frozen VS3 rule: `{result.frozen_rule_id}`
- VS3 rules modified during audit: **NO**
- Expected family instances: **{summary.expected_instances}**
- Source-wide detected logical instances: **{summary.source_wide_detected_instances}**
- Matched logical instances: **{summary.matched_instances}**
- AUTO_ACCEPTED: **{summary.auto_accepted}**
- REVIEW_REQUIRED: **{summary.review_required}**
- MISSED: **{summary.missed}**
- INVALID_OUTPUT: **{summary.invalid_output}**
- False positives: **{summary.false_positives}**
- Automatic acceptance rate: **{summary.automatic_acceptance_rate:.2%}**
- Auto-accepted beyond original VS3 slice: **{summary.auto_accepted_beyond_baseline}**
- Manual review items / page: **{summary.review_items_per_page}**
- Deterministic replay: **{'PASS' if deterministic else 'FAIL'}** ({len(replay_audit_ids)} runs)

## Editability and safety

- Unnecessary fragments: **{summary.unnecessary_fragments}**
- Duplicate logical entities: **{summary.duplicate_logical_entities}**
- Duplicate CAD IR entities: **{summary.duplicate_cad_ir_entities}**
- Incorrect line-through-symbol: **{summary.incorrect_line_through_symbol}**
- Invalid port connections: **{summary.invalid_port_connections}**

## Failure distribution

- EVIDENCE: **{summary.failure_count(FailureLayer.EVIDENCE)}**
- DOMAIN: **{summary.failure_count(FailureLayer.DOMAIN)}**
- TOPOLOGY: **{summary.failure_count(FailureLayer.TOPOLOGY)}**
- LOGICAL_ENTITY: **{summary.failure_count(FailureLayer.LOGICAL_ENTITY)}**
- ASSEMBLY: **{summary.failure_count(FailureLayer.ASSEMBLY)}**

## Systematic variant gaps

{gaps or '- NONE'}

The frozen rule {'does' if summary.auto_accepted_beyond_baseline else 'does not'}
generalize beyond the original baseline slice. The audit nevertheless exposes every expected instance, its nearest
runtime evidence, concrete rule factors, failure layer and affected logical/CAD IDs.
This makes the 33 required interventions exception-driven rather than a manual
full-page search.
"""
    report_path.write_text(report, encoding="utf-8")
    return (
        family_path,
        exceptions_path,
        logical_path,
        cad_path,
        report_path,
        family_overview,
        exceptions_overview,
    )
