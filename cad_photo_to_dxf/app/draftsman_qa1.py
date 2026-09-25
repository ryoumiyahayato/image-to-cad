"""Reference-free, read-only disposition and cross-layer lineage auditor."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
import json
from math import hypot
from pathlib import Path
from typing import Mapping

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_raster_evidence import (
    RasterEndpointEvidence,
    RasterGlyphEvidence,
    RasterLineSegmentEvidence,
    RasterTagRegionEvidence,
)
from .draftsman_vs3_u1 import DraftsmanVs3U1Result, SEMANTIC_IDENTITY_UNVERIFIED


QA1_VERSION = "draftsman-qa1-lineage-auditor-v1"


class CandidateDisposition(str, Enum):
    REPRESENTED_VERIFIED = "REPRESENTED_VERIFIED"
    REPRESENTED_UNVERIFIED = "REPRESENTED_UNVERIFIED"
    EXPLICIT_REVIEW = "EXPLICIT_REVIEW"
    EXPLICIT_REJECTION = "EXPLICIT_REJECTION"
    LIKELY_NOISE = "LIKELY_NOISE"
    UNEXPLAINED = "UNEXPLAINED"


class FindingSeverity(str, Enum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


class FindingFamily(str, Enum):
    EVIDENCE_WITHOUT_DISPOSITION = "EVIDENCE_WITHOUT_DISPOSITION"
    HYPOTHESIS_WITHOUT_EVIDENCE = "HYPOTHESIS_WITHOUT_EVIDENCE"
    LOGICAL_ENTITY_WITHOUT_SOURCE_PROVENANCE = "LOGICAL_ENTITY_WITHOUT_SOURCE_PROVENANCE"
    CAD_IR_WITHOUT_LOGICAL_ENTITY = "CAD_IR_WITHOUT_LOGICAL_ENTITY"
    CAD_IR_WITHOUT_SOURCE_PROVENANCE = "CAD_IR_WITHOUT_SOURCE_PROVENANCE"
    REVIEW_ITEM_WITHOUT_SOURCE_REGION = "REVIEW_ITEM_WITHOUT_SOURCE_REGION"
    DUPLICATE_FINAL_REPRESENTATION = "DUPLICATE_FINAL_REPRESENTATION"
    VERIFIED_AND_UNVERIFIED_DOUBLE_REPRESENTATION = (
        "VERIFIED_AND_UNVERIFIED_DOUBLE_REPRESENTATION"
    )
    REJECTED_BUT_STILL_EMITTED = "REJECTED_BUT_STILL_EMITTED"
    ENTITY_STATE_INCONSISTENCY = "ENTITY_STATE_INCONSISTENCY"


@dataclass(frozen=True)
class LogicalRecord:
    logical_entity_id: str
    candidate_id: str
    semantic_state: str
    source_evidence_ids: tuple[str, ...]
    source_region: tuple[int, int, int, int]


@dataclass(frozen=True)
class CadRecord:
    cad_entity_id: str
    logical_entity_id: str | None
    source_evidence_ids: tuple[str, ...]
    semantic_state: str


@dataclass(frozen=True)
class ReviewRecord:
    review_item_id: str
    candidate_id: str
    source_region: tuple[int, int, int, int] | None
    source_evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class RejectionRecord:
    rejection_id: str
    candidate_id: str
    source_evidence_ids: tuple[str, ...]
    reason: str
    disposition: CandidateDisposition

    def to_dict(self) -> dict[str, object]:
        return {
            "rejection_id": self.rejection_id,
            "candidate_id": self.candidate_id,
            "source_evidence_ids": list(self.source_evidence_ids),
            "reason": self.reason,
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True)
class QA1AuditInput:
    u1_result_id: str
    candidates: tuple[Mapping[str, object], ...]
    evidence_ids: tuple[str, ...]
    domain_hypotheses: tuple[Mapping[str, object], ...]
    topology_hypotheses: tuple[Mapping[str, object], ...]
    logical_entities: tuple[LogicalRecord, ...]
    cad_entities: tuple[CadRecord, ...]
    review_items: tuple[ReviewRecord, ...]
    rejection_records: tuple[RejectionRecord, ...]

    @property
    def input_id(self) -> str:
        payload = {
            "u1_result_id": self.u1_result_id,
            "candidates": [dict(item) for item in self.candidates],
            "evidence_ids": list(self.evidence_ids),
            "domain_hypotheses": [dict(item) for item in self.domain_hypotheses],
            "topology_hypotheses": [dict(item) for item in self.topology_hypotheses],
            "logical_entities": [item.__dict__ for item in self.logical_entities],
            "cad_entities": [item.__dict__ for item in self.cad_entities],
            "review_items": [item.__dict__ for item in self.review_items],
            "rejection_records": [item.to_dict() for item in self.rejection_records],
        }
        return semantic_id("draftsman-qa1-input", QA1_VERSION, payload)


@dataclass(frozen=True)
class QA1Finding:
    finding_id: str
    family: FindingFamily
    severity: FindingSeverity
    source_region: tuple[int, int, int, int] | None
    evidence_refs: tuple[str, ...]
    hypothesis_refs: tuple[str, ...]
    logical_entity_refs: tuple[str, ...]
    cad_entity_refs: tuple[str, ...]
    review_item_refs: tuple[str, ...]
    reason: str
    recommended_review_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "finding_family": self.family.value,
            "severity": self.severity.value,
            "source_region": None if self.source_region is None else list(self.source_region),
            "evidence_refs": list(self.evidence_refs),
            "hypothesis_refs": list(self.hypothesis_refs),
            "logical_entity_refs": list(self.logical_entity_refs),
            "cad_entity_refs": list(self.cad_entity_refs),
            "review_item_refs": list(self.review_item_refs),
            "reason": self.reason,
            "recommended_review_action": self.recommended_review_action,
            "signal_version": QA1_VERSION,
        }


@dataclass(frozen=True)
class QA1LedgerEntry:
    ledger_entry_id: str
    candidate_id: str
    evidence_kind: str
    source_region: tuple[int, int, int, int]
    provenance: str
    source_evidence_ids: tuple[str, ...]
    related_domain_hypothesis_ids: tuple[str, ...]
    related_topology_hypothesis_ids: tuple[str, ...]
    related_logical_entity_ids: tuple[str, ...]
    related_cad_ir_entity_ids: tuple[str, ...]
    related_review_item_ids: tuple[str, ...]
    rejection_record: Mapping[str, object] | None
    final_disposition: CandidateDisposition
    disposition_reason: str
    auditor_finding_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ledger_entry_id": self.ledger_entry_id,
            "candidate_id": self.candidate_id,
            "evidence_kind": self.evidence_kind,
            "source_region": list(self.source_region),
            "provenance": self.provenance,
            "source_evidence_ids": list(self.source_evidence_ids),
            "related_domain_hypothesis_ids": list(self.related_domain_hypothesis_ids),
            "related_topology_hypothesis_ids": list(self.related_topology_hypothesis_ids),
            "related_logical_entity_ids": list(self.related_logical_entity_ids),
            "related_cad_ir_entity_ids": list(self.related_cad_ir_entity_ids),
            "related_review_item_ids": list(self.related_review_item_ids),
            "rejection_record": (
                None if self.rejection_record is None else dict(self.rejection_record)
            ),
            "final_disposition": self.final_disposition.value,
            "disposition_reason": self.disposition_reason,
            "auditor_finding_ids": list(self.auditor_finding_ids),
        }


@dataclass(frozen=True)
class QA1AuditResult:
    input_id: str
    ledger: tuple[QA1LedgerEntry, ...]
    findings: tuple[QA1Finding, ...]
    summary: Mapping[str, object]
    schema_version: str = QA1_VERSION

    @property
    def audit_id(self) -> str:
        return semantic_id("draftsman-qa1-audit", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "input_id": self.input_id,
            "runtime_contract": {
                "reference_available": False,
                "read_only": True,
                "production_routing_changed": False,
                "limitation": (
                    "Cannot detect an object for which the frontend produced literally no evidence."
                ),
            },
            "summary": dict(self.summary),
            "ledger": [item.to_dict() for item in self.ledger],
            "findings": [item.to_dict() for item in self.findings],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _candidate_evidence(candidate: Mapping[str, object]) -> tuple[str, ...]:
    raw_lines = candidate.get("nearby_line_evidence_ids", [])
    lines = raw_lines if isinstance(raw_lines, list) else []
    return tuple(
        sorted(
            {
                str(candidate["glyph_evidence_id"]),
                str(candidate["tag_evidence_id"]),
                *(str(item) for item in lines),
            }
        )
    )


def input_from_u1(result: DraftsmanVs3U1Result) -> QA1AuditInput:
    """Normalize U1 into immutable records without consulting reference truth."""

    t1 = result.t1_result
    primitive_by_id = t1.evidence.primitive_by_id()
    candidates = tuple(
        sorted(
            (item.to_dict() for item in t1.evidence.candidates),
            key=lambda item: str(item["stable_candidate_id"]),
        )
    )
    candidate_by_id = {item.stable_candidate_id: item for item in t1.evidence.candidates}
    domains = {item.candidate_id: item for item in t1.domain_hypotheses}
    logical: list[LogicalRecord] = []
    logical_sources: dict[str, tuple[str, ...]] = {}
    connection_owner: dict[str, str] = {}
    for verified_symbol in t1.logical_symbols:
        candidate = candidate_by_id[verified_symbol.candidate_id]
        source_ids = tuple(
            sorted(set(domains[verified_symbol.candidate_id].source_evidence_ids))
        )
        glyph = primitive_by_id[candidate.glyph_evidence_id]
        source_region = (
            int(glyph.source_bbox_px[0]),
            int(glyph.source_bbox_px[1]),
            int(glyph.source_bbox_px[2]),
            int(glyph.source_bbox_px[3]),
        )
        logical.append(
            LogicalRecord(
                verified_symbol.logical_entity_id,
                verified_symbol.candidate_id,
                "VERIFIED",
                source_ids,
                source_region,
            )
        )
        logical_sources[verified_symbol.logical_entity_id] = source_ids
        for connection in verified_symbol.connections:
            connection_owner[connection.connection_id] = verified_symbol.logical_entity_id
    for unverified_symbol in result.unverified_symbols:
        logical.append(
            LogicalRecord(
                unverified_symbol.logical_entity_id,
                unverified_symbol.candidate_id,
                unverified_symbol.semantic_state,
                tuple(sorted(unverified_symbol.source_evidence_ids)),
                unverified_symbol.source_region,
            )
        )
        logical_sources[unverified_symbol.logical_entity_id] = tuple(
            sorted(unverified_symbol.source_evidence_ids)
        )

    cad: list[CadRecord] = []
    for cad_symbol in t1.cad_ir.symbols:
        logical_id = str(cad_symbol["logical_entity_id"])
        cad.append(
            CadRecord(
                str(cad_symbol["cad_entity_id"]),
                logical_id,
                logical_sources[logical_id],
                "VERIFIED",
            )
        )
    for cad_line in t1.cad_ir.lines:
        line_logical_id = connection_owner.get(str(cad_line["logical_connection_id"]))
        raw_source_ids = cad_line["source_evidence_ids"]
        if not isinstance(raw_source_ids, list):
            raise TypeError("CAD line source evidence IDs must be a list")
        source_ids = tuple(str(value) for value in raw_source_ids)
        cad.append(
            CadRecord(
                str(cad_line["cad_entity_id"]),
                line_logical_id,
                source_ids,
                "VERIFIED",
            )
        )
    groups = result.cad_ir.get("unverified_groups", [])
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            logical_id = str(group["logical_entity_id"])
            entities = group.get("entities", [])
            if not isinstance(entities, list):
                continue
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                source_id = str(entity["source_evidence_id"])
                cad.append(
                    CadRecord(
                        str(entity["cad_entity_id"]),
                        logical_id,
                        (source_id,),
                        str(entity["semantic_state"]),
                    )
                )

    reviews = tuple(
        sorted(
            (
                ReviewRecord(
                    semantic_id(
                        "draftsman-qa1-observed-review-state",
                        QA1_VERSION,
                        {
                            "logical_entity_id": item.logical_entity_id,
                            "review_state": list(item.review_state),
                        },
                    ),
                    item.candidate_id,
                    item.source_region,
                    tuple(sorted(item.source_evidence_ids)),
                    "; ".join(item.review_state),
                )
                for item in result.unverified_symbols
            ),
            key=lambda item: item.review_item_id,
        )
    )
    topology_by_candidate: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for topology_hypothesis in t1.topology_hypotheses:
        topology_by_candidate[topology_hypothesis.candidate_id].append(
            topology_hypothesis.to_dict()
        )
    rejections: list[RejectionRecord] = []
    for candidate_id, state in sorted(result.ineligible_candidates.items()):
        candidate = candidate_by_id[candidate_id]
        has_ports = any(
            bool(item.get("ports")) for item in topology_by_candidate[candidate_id]
        )
        disposition = (
            CandidateDisposition.EXPLICIT_REJECTION
            if has_ports
            else CandidateDisposition.LIKELY_NOISE
        )
        reason = (
            f"{state.value}; observed body support below U1 preservation requirement"
            if has_ports
            else f"{state.value}; no symbol-boundary line incidence"
        )
        payload = {
            "candidate_id": candidate_id,
            "reason": reason,
            "disposition": disposition.value,
        }
        rejections.append(
            RejectionRecord(
                semantic_id("draftsman-qa1-rejection", QA1_VERSION, payload),
                candidate_id,
                _candidate_evidence(candidate.to_dict()),
                reason,
                disposition,
            )
        )
    return QA1AuditInput(
        u1_result_id=result.result_id,
        candidates=candidates,
        evidence_ids=tuple(sorted(primitive_by_id)),
        domain_hypotheses=tuple(
            sorted(
                (item.to_dict() for item in t1.domain_hypotheses),
                key=lambda item: str(item["hypothesis_id"]),
            )
        ),
        topology_hypotheses=tuple(
            sorted(
                (item.to_dict() for item in t1.topology_hypotheses),
                key=lambda item: str(item["hypothesis_id"]),
            )
        ),
        logical_entities=tuple(sorted(logical, key=lambda item: item.logical_entity_id)),
        cad_entities=tuple(sorted(cad, key=lambda item: item.cad_entity_id)),
        review_items=reviews,
        rejection_records=tuple(rejections),
    )


def _finding(
    family: FindingFamily,
    severity: FindingSeverity,
    reason: str,
    *,
    source_region: tuple[int, int, int, int] | None = None,
    evidence: tuple[str, ...] = (),
    hypotheses: tuple[str, ...] = (),
    logical: tuple[str, ...] = (),
    cad: tuple[str, ...] = (),
    reviews: tuple[str, ...] = (),
) -> QA1Finding:
    payload = {
        "family": family.value,
        "severity": severity.value,
        "reason": reason,
        "source_region": source_region,
        "evidence": evidence,
        "hypotheses": hypotheses,
        "logical": logical,
        "cad": cad,
        "reviews": reviews,
    }
    return QA1Finding(
        semantic_id("draftsman-qa1-finding", QA1_VERSION, payload),
        family,
        severity,
        source_region,
        evidence,
        hypotheses,
        logical,
        cad,
        reviews,
        reason,
        "Inspect the cited lineage records; the auditor does not repair reconstruction.",
    )


def audit_qa1_lineage(data: QA1AuditInput) -> QA1AuditResult:
    """Audit a normalized snapshot.  The input is never mutated."""

    input_id = data.input_id
    evidence_ids = set(data.evidence_ids)
    logical_by_id = {item.logical_entity_id: item for item in data.logical_entities}
    logical_by_candidate: dict[str, list[LogicalRecord]] = defaultdict(list)
    for logical_record in data.logical_entities:
        logical_by_candidate[logical_record.candidate_id].append(logical_record)
    cad_by_logical: dict[str, list[CadRecord]] = defaultdict(list)
    for cad_record in data.cad_entities:
        if cad_record.logical_entity_id is not None:
            cad_by_logical[cad_record.logical_entity_id].append(cad_record)
    reviews_by_candidate: dict[str, list[ReviewRecord]] = defaultdict(list)
    for review_record in data.review_items:
        reviews_by_candidate[review_record.candidate_id].append(review_record)
    rejection_by_candidate = {item.candidate_id: item for item in data.rejection_records}
    findings: list[QA1Finding] = []

    domain_by_id = {
        str(item["hypothesis_id"]): item for item in data.domain_hypotheses
    }
    for hypothesis in (*data.domain_hypotheses, *data.topology_hypotheses):
        hypothesis_id = str(hypothesis["hypothesis_id"])
        refs = hypothesis.get("source_evidence_ids")
        if not isinstance(refs, list):
            raw_support = hypothesis.get("rule_support", [])
            support_items = raw_support if isinstance(raw_support, list) else []
            refs = [
                evidence_id
                for support in support_items
                if isinstance(support, dict)
                for evidence_id in support.get("evidence_ids", [])
            ]
        domain_parent = domain_by_id.get(str(hypothesis.get("domain_hypothesis_id", "")))
        if not refs and domain_parent is not None:
            parent_refs = domain_parent.get("source_evidence_ids", [])
            refs = parent_refs if isinstance(parent_refs, list) else []
        missing = tuple(sorted(str(item) for item in refs if str(item) not in evidence_ids))
        if not refs or missing:
            findings.append(
                _finding(
                    FindingFamily.HYPOTHESIS_WITHOUT_EVIDENCE,
                    FindingSeverity.ERROR,
                    "Hypothesis has no valid source-evidence lineage.",
                    evidence=missing,
                    hypotheses=(hypothesis_id,),
                )
            )
    for logical_record in data.logical_entities:
        valid = tuple(
            ref for ref in logical_record.source_evidence_ids if ref in evidence_ids
        )
        if not valid:
            findings.append(
                _finding(
                    FindingFamily.LOGICAL_ENTITY_WITHOUT_SOURCE_PROVENANCE,
                    FindingSeverity.ERROR,
                    "Logical entity has no valid source-evidence provenance.",
                    source_region=logical_record.source_region,
                    logical=(logical_record.logical_entity_id,),
                )
            )
    for cad_record in data.cad_entities:
        logical = logical_by_id.get(cad_record.logical_entity_id or "")
        if logical is None:
            findings.append(
                _finding(
                    FindingFamily.CAD_IR_WITHOUT_LOGICAL_ENTITY,
                    FindingSeverity.ERROR,
                    "CAD IR entity has no logical-entity lineage.",
                    cad=(cad_record.cad_entity_id,),
                )
            )
        transitive = set(cad_record.source_evidence_ids)
        if logical is not None:
            transitive.update(logical.source_evidence_ids)
        if not (transitive & evidence_ids):
            findings.append(
                _finding(
                    FindingFamily.CAD_IR_WITHOUT_SOURCE_PROVENANCE,
                    FindingSeverity.ERROR,
                    "CAD IR entity has neither direct nor transitive source provenance.",
                    logical=() if logical is None else (logical.logical_entity_id,),
                    cad=(cad_record.cad_entity_id,),
                )
            )
        if logical is not None and cad_record.semantic_state != logical.semantic_state:
            findings.append(
                _finding(
                    FindingFamily.ENTITY_STATE_INCONSISTENCY,
                    FindingSeverity.ERROR,
                    "CAD and logical semantic states disagree.",
                    logical=(logical.logical_entity_id,),
                    cad=(cad_record.cad_entity_id,),
                )
            )
    for review_record in data.review_items:
        if review_record.source_region is None:
            findings.append(
                _finding(
                    FindingFamily.REVIEW_ITEM_WITHOUT_SOURCE_REGION,
                    FindingSeverity.REVIEW,
                    "Review item lacks a source region.",
                    evidence=review_record.source_evidence_ids,
                    reviews=(review_record.review_item_id,),
                )
            )

    for candidate_id, entities in logical_by_candidate.items():
        if len(entities) > 1:
            states = {item.semantic_state for item in entities}
            family = (
                FindingFamily.VERIFIED_AND_UNVERIFIED_DOUBLE_REPRESENTATION
                if {"VERIFIED", SEMANTIC_IDENTITY_UNVERIFIED} <= states
                else FindingFamily.DUPLICATE_FINAL_REPRESENTATION
            )
            findings.append(
                _finding(
                    family,
                    FindingSeverity.ERROR,
                    "One candidate has multiple final logical representations.",
                    logical=tuple(sorted(item.logical_entity_id for item in entities)),
                )
            )
    for candidate_id, rejection in rejection_by_candidate.items():
        emitted = logical_by_candidate.get(candidate_id, [])
        if emitted:
            findings.append(
                _finding(
                    FindingFamily.REJECTED_BUT_STILL_EMITTED,
                    FindingSeverity.ERROR,
                    "A rejected candidate still has a final logical representation.",
                    evidence=rejection.source_evidence_ids,
                    logical=tuple(sorted(item.logical_entity_id for item in emitted)),
                )
            )

    domains_by_candidate: dict[str, list[str]] = defaultdict(list)
    topologies_by_candidate: dict[str, list[str]] = defaultdict(list)
    for domain_hypothesis in data.domain_hypotheses:
        domains_by_candidate[str(domain_hypothesis["candidate_id"])].append(
            str(domain_hypothesis["hypothesis_id"])
        )
    for topology_hypothesis in data.topology_hypotheses:
        topologies_by_candidate[str(topology_hypothesis["candidate_id"])].append(
            str(topology_hypothesis["hypothesis_id"])
        )
    ledger_base: list[QA1LedgerEntry] = []
    for candidate in data.candidates:
        candidate_id = str(candidate["stable_candidate_id"])
        logical_records = logical_by_candidate.get(candidate_id, [])
        cad_records = [
            cad_item
            for logical_item in logical_records
            for cad_item in cad_by_logical.get(logical_item.logical_entity_id, [])
        ]
        review_records = reviews_by_candidate.get(candidate_id, [])
        candidate_rejection = rejection_by_candidate.get(candidate_id)
        center = candidate["source_center_px"]
        raw_radius = candidate["radius_px"]
        if not isinstance(raw_radius, int):
            raise TypeError("candidate radius must be an integer")
        if not isinstance(center, list):
            raise TypeError("candidate source center must be a list")
        radius = raw_radius
        source_region = (
            int(center[0]) - radius,
            int(center[1]) - radius,
            int(center[0]) + radius,
            int(center[1]) + radius,
        )
        states = {item.semantic_state for item in logical_records}
        if "VERIFIED" in states:
            disposition = CandidateDisposition.REPRESENTED_VERIFIED
            reason = "Verified logical entity and CAD representation exist."
        elif SEMANTIC_IDENTITY_UNVERIFIED in states:
            disposition = CandidateDisposition.REPRESENTED_UNVERIFIED
            reason = "Editable CAD exists with semantic identity explicitly unverified."
        elif review_records:
            disposition = CandidateDisposition.EXPLICIT_REVIEW
            reason = "Candidate has an explicit review record and no emitted entity."
        elif candidate_rejection is not None:
            disposition = candidate_rejection.disposition
            reason = candidate_rejection.reason
        else:
            disposition = CandidateDisposition.UNEXPLAINED
            reason = "Candidate has no final representation, review, or rejection."
            findings.append(
                _finding(
                    FindingFamily.EVIDENCE_WITHOUT_DISPOSITION,
                    FindingSeverity.REVIEW,
                    reason,
                    source_region=source_region,
                    evidence=_candidate_evidence(candidate),
                    hypotheses=tuple(
                        sorted(domains_by_candidate[candidate_id] + topologies_by_candidate[candidate_id])
                    ),
                )
            )
        rejection_dict = (
            None if candidate_rejection is None else candidate_rejection.to_dict()
        )
        identity_payload = {
            "candidate_id": candidate_id,
            "input_id": input_id,
        }
        ledger_base.append(
            QA1LedgerEntry(
                semantic_id("draftsman-qa1-ledger-entry", QA1_VERSION, identity_payload),
                candidate_id,
                "RASTER_ELECTRICAL_CANDIDATE",
                source_region,
                "FROZEN_RASTER_EVIDENCE",
                _candidate_evidence(candidate),
                tuple(sorted(domains_by_candidate[candidate_id])),
                tuple(sorted(topologies_by_candidate[candidate_id])),
                tuple(sorted(item.logical_entity_id for item in logical_records)),
                tuple(sorted(item.cad_entity_id for item in cad_records)),
                tuple(sorted(item.review_item_id for item in review_records)),
                rejection_dict,
                disposition,
                reason,
                (),
            )
        )
    findings.sort(key=lambda item: item.finding_id)
    candidate_finding_ids: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        for entry in ledger_base:
            if set(finding.evidence_refs) & set(entry.source_evidence_ids):
                candidate_finding_ids[entry.candidate_id].append(finding.finding_id)
    ledger = tuple(
        QA1LedgerEntry(
            **{
                **item.__dict__,
                "auditor_finding_ids": tuple(sorted(candidate_finding_ids[item.candidate_id])),
            }
        )
        for item in sorted(ledger_base, key=lambda item: item.ledger_entry_id)
    )
    dispositions = Counter(item.final_disposition.value for item in ledger)
    severities = Counter(item.severity.value for item in findings)
    summary: dict[str, object] = {
        "evidence_candidates": len(data.candidates),
        "domain_hypotheses": len(data.domain_hypotheses),
        "topology_hypotheses": len(data.topology_hypotheses),
        "logical_entities": len(data.logical_entities),
        "cad_ir_entities": len(data.cad_entities),
        "review_items": len(data.review_items),
        "candidate_dispositions": {
            item.value: dispositions[item.value] for item in CandidateDisposition
        },
        "actionable_findings": {item.value: severities[item.value] for item in FindingSeverity},
        "candidates_without_disposition": dispositions[CandidateDisposition.UNEXPLAINED.value],
        "logical_entities_without_provenance": sum(
            item.family is FindingFamily.LOGICAL_ENTITY_WITHOUT_SOURCE_PROVENANCE
            for item in findings
        ),
        "cad_ir_without_logical_lineage": sum(
            item.family is FindingFamily.CAD_IR_WITHOUT_LOGICAL_ENTITY for item in findings
        ),
        "cad_ir_without_source_provenance": sum(
            item.family is FindingFamily.CAD_IR_WITHOUT_SOURCE_PROVENANCE for item in findings
        ),
        "duplicate_final_representations": sum(
            item.family
            in {
                FindingFamily.DUPLICATE_FINAL_REPRESENTATION,
                FindingFamily.VERIFIED_AND_UNVERIFIED_DOUBLE_REPRESENTATION,
            }
            for item in findings
        ),
    }
    return QA1AuditResult(input_id, ledger, tuple(findings), summary)


def audit_draftsman_qa1(result: DraftsmanVs3U1Result) -> QA1AuditResult:
    """Convenience wrapper for reference-free QA1 runtime auditing."""

    return audit_qa1_lineage(input_from_u1(result))


def _point_segment_distance(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return hypot(point[0] - first[0], point[1] - first[1])
    fraction = (
        (point[0] - first[0]) * dx + (point[1] - first[1]) * dy
    ) / length_squared
    fraction = max(0.0, min(1.0, fraction))
    projection = (first[0] + fraction * dx, first[1] + fraction * dy)
    return hypot(point[0] - projection[0], point[1] - projection[1])


def measurement_only_omission_signals(
    result: DraftsmanVs3U1Result,
) -> Mapping[str, object]:
    """Measure QA0 heuristics without creating actionable QA1 findings."""

    primitives = result.t1_result.evidence.primitives
    matched_glyph_ids = {
        item.glyph_evidence_id for item in result.t1_result.evidence.candidates
    }
    unmatched = [
        item
        for item in primitives
        if isinstance(item, RasterGlyphEvidence)
        and item.stable_evidence_id not in matched_glyph_ids
        and item.ring_coverage >= 0.90
    ]
    endpoints = [
        (float(item.source_point_px[0]), float(item.source_point_px[1]))
        for item in primitives
        if isinstance(item, RasterEndpointEvidence)
    ]
    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for item in primitives:
        if isinstance(item, RasterLineSegmentEvidence):
            first = (float(item.source_start_px[0]), float(item.source_start_px[1]))
            second = (float(item.source_end_px[0]), float(item.source_end_px[1]))
            lines.append((first, second))
    glyph_centers = [
        (float(item.center_px[0]), float(item.center_px[1]))
        for item in primitives
        if isinstance(item, RasterGlyphEvidence)
    ]
    final_centers = [item.center for item in result.t1_result.logical_symbols]
    final_centers.extend(item.observed_center_px for item in result.unverified_symbols)
    region_candidates: list[tuple[int, int, tuple[float, float]]] = []
    for item in primitives:
        if not isinstance(item, RasterTagRegionEvidence):
            continue
        center = (float(item.center_px[0]), float(item.center_px[1]))
        if any(hypot(center[0] - x, center[1] - y) <= 20.0 for x, y in glyph_centers):
            continue
        if any(hypot(center[0] - x, center[1] - y) <= 20.0 for x, y in final_centers):
            continue
        endpoint_count = sum(
            hypot(center[0] - x, center[1] - y) <= 22.0 for x, y in endpoints
        )
        if endpoint_count < 6:
            continue
        line_match_count = sum(
            hypot(second[0] - first[0], second[1] - first[1]) >= 40.0
            and min(
                hypot(center[0] - first[0], center[1] - first[1]),
                hypot(center[0] - second[0], center[1] - second[1]),
            )
            >= 8.0
            and _point_segment_distance(center, first, second) <= 4.0
            for first, second in lines
        )
        if line_match_count:
            region_candidates.append((endpoint_count, line_match_count, center))
    selected: list[tuple[float, float]] = []
    for _, _, center in sorted(
        region_candidates, key=lambda item: (-item[0], -item[1], item[2])
    ):
        if all(hypot(center[0] - x, center[1] - y) > 28.0 for x, y in selected):
            selected.append(center)
    signals = (
        {
            "signal_id": "QA1-MO-01-UNMATCHED-COHERENT-GLYPH",
            "mode": "MEASUREMENT_ONLY",
            "alerts": len(unmatched),
            "enters_actionable_review": False,
        },
        {
            "signal_id": "QA1-MO-02-ORPHAN-MULTITYPE-REGION-WITHOUT-GLYPH",
            "mode": "MEASUREMENT_ONLY",
            "alerts": len(selected),
            "enters_actionable_review": False,
        },
    )
    return {
        "schema_version": "draftsman-qa1-measurement-only-signals-v1",
        "signals": list(signals),
        "total_alerts": len(unmatched) + len(selected),
        "actionable_review_alerts": 0,
        "reference_available": False,
    }


def write_draftsman_qa1_artifacts(
    output_dir: str | Path,
    *,
    audit: QA1AuditResult,
    measurement: Mapping[str, object],
    replay_audit_ids: tuple[str, ...],
    reference_evaluation: Mapping[str, object],
) -> tuple[Path, ...]:
    """Write ignored QA1 reports; runtime and post-hoc payloads remain separate."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    deterministic = len(replay_audit_ids) >= 2 and len(set(replay_audit_ids)) == 1
    payloads: dict[str, object] = {
        "qa1-disposition-ledger.json": {
            "schema_version": "draftsman-qa1-disposition-ledger-v1",
            "audit_id": audit.audit_id,
            "reference_available": False,
            "candidate_count": len(audit.ledger),
            "entries": [item.to_dict() for item in audit.ledger],
        },
        "qa1-findings.json": {
            "schema_version": "draftsman-qa1-findings-v1",
            "audit_id": audit.audit_id,
            "reference_available": False,
            "findings": [item.to_dict() for item in audit.findings],
        },
        "qa1-lineage-summary.json": {
            "schema_version": "draftsman-qa1-lineage-summary-v1",
            "audit_id": audit.audit_id,
            "summary": dict(audit.summary),
            "deterministic_replay": {
                "passed": deterministic,
                "runs": len(replay_audit_ids),
                "audit_ids": list(replay_audit_ids),
            },
            "denominator_contract": {
                "evidence_candidates": "candidate observations, not object count",
                "domain_hypotheses": "domain proposal records",
                "logical_entities": "verified plus source-wide unverified entities",
                "cad_ir_entities": "emitted editable CAD entities; provisional relations excluded",
                "review_items": "existing U1 review-state records projected for audit",
            },
            "runtime_contract": audit.to_dict()["runtime_contract"],
        },
        "qa1-measurement-only-signals.json": dict(measurement),
        "qa1-reference-evaluation.json": dict(reference_evaluation),
    }
    written: list[Path] = []
    for name, payload in payloads.items():
        path = target / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    dispositions = audit.summary["candidate_dispositions"]
    severities = audit.summary["actionable_findings"]
    if not isinstance(dispositions, dict) or not isinstance(severities, dict):
        raise TypeError("QA1 summary counters must be dictionaries")
    report = target / "QA1_REPORT.md"
    report.write_text(
        "\n".join(
            (
                "# Draftsman QA1 — Reference-free disposition and lineage audit",
                "",
                "QA1 is a shadow-only, read-only auditor. Golden reference data is absent",
                "from runtime inference and appears only in the separate post-hoc evaluation.",
                "",
                "## Separate denominators",
                "",
                f"- Evidence candidates: **{audit.summary['evidence_candidates']}**",
                f"- Domain hypotheses: **{audit.summary['domain_hypotheses']}**",
                f"- Topology hypotheses: **{audit.summary['topology_hypotheses']}**",
                f"- Logical entities: **{audit.summary['logical_entities']}**",
                f"- CAD IR entities: **{audit.summary['cad_ir_entities']}**",
                f"- Review items: **{audit.summary['review_items']}**",
                "",
                "The 71 represented-unverified entries are candidate dispositions. They must",
                "not be interpreted as 71 members of the 38-instance evaluation family.",
                "",
                "## Candidate dispositions",
                "",
                *(
                    f"- {item.value}: **{dispositions[item.value]}**"
                    for item in CandidateDisposition
                ),
                "",
                "## Actionable findings",
                "",
                *(
                    f"- {item.value}: **{severities[item.value]}**"
                    for item in FindingSeverity
                ),
                "",
                f"Measurement-only omission alerts: **{measurement['total_alerts']}**;",
                "none enter the actionable Review Queue.",
                "",
                "## Explicit limitation",
                "",
                "QA1 can audit only evidence and hypotheses the frontend actually emitted.",
                "It cannot detect an object for which the frontend produced literally no evidence.",
                "",
            )
        ),
        encoding="utf-8",
    )
    written.append(report)
    return tuple(written)
