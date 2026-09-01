"""Electrical-domain interpretation and logical entities for Draftsman VS2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Iterable, Sequence

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_domain_pack import (
    DomainPack,
    ElectricalConnectionStyle,
    ElectricalPortRule,
    ElectricalPortSide,
    ElectricalSymbolRule,
)
from .draftsman_pdf_vector import (
    PdfBoxedSymbolEvidence,
    PdfBoxedSymbolEvidenceManifest,
    PdfVectorPrimitiveEvidence,
)


DRAFTSMAN_ELECTRICAL_DECISION_VERSION = "draftsman-electrical-decision-v1"
DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION = "draftsman-logical-electrical-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    if not isfinite(normalized):
        raise ValueError("Electrical geometry must be finite")
    return 0.0 if normalized == 0.0 else normalized


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError("Electrical points require two coordinates")
    return _number(value[0]), _number(value[1])


class ElectricalDecisionState(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ElectricalPortDecision:
    port_key: str
    side: ElectricalPortSide
    location: tuple[float, float]
    connection_style: ElectricalConnectionStyle
    direction: str
    connection_start: tuple[float, float]
    connection_end: tuple[float, float]
    source_primitive_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", _point(self.location))
        object.__setattr__(self, "connection_start", _point(self.connection_start))
        object.__setattr__(self, "connection_end", _point(self.connection_end))
        object.__setattr__(
            self,
            "source_primitive_ids",
            tuple(sorted(set(self.source_primitive_ids))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "port_key": self.port_key,
            "side": self.side.value,
            "location": list(self.location),
            "connection_style": self.connection_style.value,
            "direction": self.direction,
            "connection_start": list(self.connection_start),
            "connection_end": list(self.connection_end),
            "source_primitive_ids": list(self.source_primitive_ids),
        }


@dataclass(frozen=True)
class ElectricalSymbolHypothesis:
    stable_hypothesis_id: str
    candidate_id: str
    rule_id: str
    canonical_domain_identity: str
    inventory_canonical_identity: str
    state: ElectricalDecisionState
    confidence: float
    reasons: tuple[str, ...]
    source_primitive_ids: tuple[str, ...]
    ports: tuple[ElectricalPortDecision, ...]
    frame_bounds_pt: tuple[float, float, float, float]
    body_crossing_permitted: bool
    annotation_expected: bool
    cad_block_ref: str
    display_label: str
    coordinate_space: str
    frontend_kind: str
    schema_version: str = DRAFTSMAN_ELECTRICAL_DECISION_VERSION

    @classmethod
    def create(
        cls,
        *,
        candidate: PdfBoxedSymbolEvidence,
        rule: ElectricalSymbolRule,
        state: ElectricalDecisionState,
        confidence: float,
        reasons: Iterable[str],
        source_primitive_ids: Iterable[str],
        ports: Iterable[ElectricalPortDecision],
    ) -> ElectricalSymbolHypothesis:
        ordered_reasons = tuple(sorted(set(reasons)))
        ordered_source = tuple(sorted(set(source_primitive_ids)))
        ordered_ports = tuple(sorted(ports, key=lambda item: item.port_key))
        identity = {
            "candidate_id": candidate.stable_candidate_id,
            "rule_id": rule.rule_id,
            "canonical_domain_identity": rule.canonical_domain_identity,
            "state": state.value,
            "confidence": _number(confidence),
            "reasons": list(ordered_reasons),
            "source_primitive_ids": list(ordered_source),
            "ports": [port.to_dict() for port in ordered_ports],
            "frame_bounds_pt": list(candidate.frame_bounds_pt),
            "body_crossing_permitted": rule.body_crossing_permitted,
            "annotation_expected": rule.annotation_expected,
            "cad_block_ref": rule.cad_block_ref,
            "display_label": rule.display_label,
            "coordinate_space": "normalized-page-point",
            "frontend_kind": "VECTOR_PDF",
        }
        return cls(
            stable_hypothesis_id=semantic_id(
                "draftsman-electrical-symbol-hypothesis",
                DRAFTSMAN_ELECTRICAL_DECISION_VERSION,
                identity,
            ),
            candidate_id=candidate.stable_candidate_id,
            rule_id=rule.rule_id,
            canonical_domain_identity=rule.canonical_domain_identity,
            inventory_canonical_identity=rule.inventory_canonical_identity,
            state=state,
            confidence=_number(confidence),
            reasons=ordered_reasons,
            source_primitive_ids=ordered_source,
            ports=ordered_ports,
            frame_bounds_pt=candidate.frame_bounds_pt,
            body_crossing_permitted=rule.body_crossing_permitted,
            annotation_expected=rule.annotation_expected,
            cad_block_ref=rule.cad_block_ref,
            display_label=rule.display_label,
            coordinate_space="normalized-page-point",
            frontend_kind="VECTOR_PDF",
        )

    @classmethod
    def from_normalized_evidence(
        cls,
        *,
        candidate_id: str,
        rule: ElectricalSymbolRule,
        state: ElectricalDecisionState,
        confidence: float,
        reasons: Iterable[str],
        source_primitive_ids: Iterable[str],
        ports: Iterable[ElectricalPortDecision],
        frame_bounds: Sequence[float],
        coordinate_space: str,
        frontend_kind: str,
    ) -> ElectricalSymbolHypothesis:
        ordered_reasons = tuple(sorted(set(reasons)))
        ordered_source = tuple(sorted(set(source_primitive_ids)))
        ordered_ports = tuple(sorted(ports, key=lambda item: item.port_key))
        bounds = tuple(_number(value) for value in frame_bounds)
        if len(bounds) != 4:
            raise ValueError("Electrical hypothesis bounds require four values")
        identity = {
            "candidate_id": candidate_id,
            "rule_id": rule.rule_id,
            "canonical_domain_identity": rule.canonical_domain_identity,
            "state": state.value,
            "confidence": _number(confidence),
            "reasons": list(ordered_reasons),
            "source_primitive_ids": list(ordered_source),
            "ports": [port.to_dict() for port in ordered_ports],
            "frame_bounds_pt": list(bounds),
            "body_crossing_permitted": rule.body_crossing_permitted,
            "annotation_expected": rule.annotation_expected,
            "cad_block_ref": rule.cad_block_ref,
            "display_label": rule.display_label,
            "coordinate_space": coordinate_space,
            "frontend_kind": frontend_kind,
        }
        return cls(
            stable_hypothesis_id=semantic_id(
                "draftsman-electrical-symbol-hypothesis",
                DRAFTSMAN_ELECTRICAL_DECISION_VERSION,
                identity,
            ),
            candidate_id=candidate_id,
            rule_id=rule.rule_id,
            canonical_domain_identity=rule.canonical_domain_identity,
            inventory_canonical_identity=rule.inventory_canonical_identity,
            state=state,
            confidence=_number(confidence),
            reasons=ordered_reasons,
            source_primitive_ids=ordered_source,
            ports=ordered_ports,
            frame_bounds_pt=bounds,  # type: ignore[arg-type]
            body_crossing_permitted=rule.body_crossing_permitted,
            annotation_expected=rule.annotation_expected,
            cad_block_ref=rule.cad_block_ref,
            display_label=rule.display_label,
            coordinate_space=coordinate_space,
            frontend_kind=frontend_kind,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stable_hypothesis_id": self.stable_hypothesis_id,
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "canonical_domain_identity": self.canonical_domain_identity,
            "inventory_canonical_identity": self.inventory_canonical_identity,
            "state": self.state.value,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "source_primitive_ids": list(self.source_primitive_ids),
            "ports": [port.to_dict() for port in self.ports],
            "frame_bounds_pt": list(self.frame_bounds_pt),
            "body_crossing_permitted": self.body_crossing_permitted,
            "annotation_expected": self.annotation_expected,
            "cad_block_ref": self.cad_block_ref,
            "display_label": self.display_label,
            "coordinate_space": self.coordinate_space,
            "frontend_kind": self.frontend_kind,
        }


@dataclass(frozen=True)
class ElectricalDomainDecisionManifest:
    source_document_id: str
    source_page: int
    evidence_manifest_id: str
    domain_pack_id: str
    hypotheses: tuple[ElectricalSymbolHypothesis, ...]
    schema_version: str = DRAFTSMAN_ELECTRICAL_DECISION_VERSION

    def __post_init__(self) -> None:
        if self.hypotheses != tuple(
            sorted(self.hypotheses, key=lambda item: item.stable_hypothesis_id)
        ):
            raise ValueError("Electrical hypotheses must use canonical ID order")

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "draftsman-electrical-decision-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": self.source_page,
                "evidence_manifest_id": self.evidence_manifest_id,
                "domain_pack_id": self.domain_pack_id,
                "hypothesis_ids": [
                    item.stable_hypothesis_id for item in self.hypotheses
                ],
            },
        )

    @property
    def accepted(self) -> tuple[ElectricalSymbolHypothesis, ...]:
        return tuple(
            item for item in self.hypotheses if item.state is ElectricalDecisionState.ACCEPTED
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "evidence_manifest_id": self.evidence_manifest_id,
            "domain_pack_id": self.domain_pack_id,
            "hypothesis_count": len(self.hypotheses),
            "accepted_count": len(self.accepted),
            "hypotheses": [item.to_dict() for item in self.hypotheses],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _primitive_dimensions(
    primitive: PdfVectorPrimitiveEvidence,
) -> tuple[float, float, float, float, float, float]:
    left, bottom, right, top = primitive.bounds_pt
    return left, bottom, right, top, right - left, top - bottom


def _top_tracks(
    candidate: PdfBoxedSymbolEvidence,
    primitives: dict[str, PdfVectorPrimitiveEvidence],
) -> tuple[tuple[float, float, tuple[str, ...]], ...]:
    left, _, right, top = candidate.frame_bounds_pt
    raw: list[tuple[float, float, str]] = []
    for primitive_id in candidate.nearby_primitive_ids:
        primitive = primitives[primitive_id]
        x1, y1, x2, y2, width, height = _primitive_dimensions(primitive)
        if not primitive.paint.has_fill:
            continue
        if not (0.0 < width <= 1.7 and height >= 4.0):
            continue
        center = (x1 + x2) / 2.0
        if not left <= center <= right:
            continue
        if y1 > top + 0.75 or y2 <= top + 3.0:
            continue
        raw.append((center, y2, primitive_id))
    groups: list[list[tuple[float, float, str]]] = []
    for item in sorted(raw):
        for group in groups:
            if abs(group[0][0] - item[0]) <= 0.8:
                group.append(item)
                break
        else:
            groups.append([item])
    return tuple(
        sorted(
            (
                (
                    _number(sum(item[0] for item in group) / len(group)),
                    _number(max(item[1] for item in group)),
                    tuple(sorted(item[2] for item in group)),
                )
                for group in groups
            ),
            key=lambda item: item[0],
        )
    )


def _bottom_control_tracks(
    candidate: PdfBoxedSymbolEvidence,
    rules: tuple[ElectricalPortRule, ...],
    primitives: dict[str, PdfVectorPrimitiveEvidence],
) -> tuple[tuple[ElectricalPortRule, float, tuple[str, ...]], ...] | None:
    left, bottom, right, _ = candidate.frame_bounds_pt
    width = right - left
    tracks: list[tuple[ElectricalPortRule, float, tuple[str, ...]]] = []
    for rule in sorted(rules, key=lambda item: item.lateral_fraction):
        expected_x = left + width * rule.lateral_fraction
        selected: list[PdfVectorPrimitiveEvidence] = []
        for primitive_id in candidate.nearby_primitive_ids:
            primitive = primitives[primitive_id]
            x1, y1, x2, y2, primitive_width, height = _primitive_dimensions(
                primitive
            )
            if primitive_id in candidate.frame_primitive_ids:
                continue
            if y2 > bottom + 0.5 or y1 < bottom - 16.0:
                continue
            center = (x1 + x2) / 2.0
            if abs(center - expected_x) > 2.6:
                continue
            if primitive_width > 6.0 or height > 8.0:
                continue
            selected.append(primitive)
        if len(selected) < 6:
            return None
        highest = max(item.bounds_pt[3] for item in selected)
        lowest = min(item.bounds_pt[1] for item in selected)
        if highest < bottom - 0.5 or bottom - lowest < 10.0:
            return None
        tracks.append(
            (
                rule,
                _number(lowest),
                tuple(sorted(item.stable_evidence_id for item in selected)),
            )
        )
    return tuple(tracks)


def _port_decisions(
    candidate: PdfBoxedSymbolEvidence,
    rule: ElectricalSymbolRule,
    primitives: dict[str, PdfVectorPrimitiveEvidence],
) -> tuple[ElectricalPortDecision, ...] | None:
    left, bottom, right, top = candidate.frame_bounds_pt
    width = right - left
    tracks = _top_tracks(candidate, primitives)
    top_rules = tuple(port for port in rule.ports if port.side is ElectricalPortSide.TOP)
    bottom_rules = tuple(
        port for port in rule.ports if port.side is ElectricalPortSide.BOTTOM
    )
    if len(tracks) != len(top_rules):
        return None
    decisions: list[ElectricalPortDecision] = []
    unused_tracks = list(tracks)
    for port in sorted(top_rules, key=lambda item: item.lateral_fraction):
        expected_x = left + width * port.lateral_fraction
        selected = min(unused_tracks, key=lambda item: abs(item[0] - expected_x))
        if abs(selected[0] - expected_x) > 2.0:
            return None
        unused_tracks.remove(selected)
        location = (_number(selected[0]), top)
        decisions.append(
            ElectricalPortDecision(
                port_key=port.port_key,
                side=port.side,
                location=location,
                connection_style=port.connection_style,
                direction=port.direction,
                connection_start=location,
                connection_end=(_number(selected[0]), selected[1]),
                source_primitive_ids=selected[2],
            )
        )
    bottom_tracks = _bottom_control_tracks(candidate, bottom_rules, primitives)
    if bottom_tracks is None or len(bottom_tracks) != len(bottom_rules):
        return None
    for port, lowest, source_ids in bottom_tracks:
        x_value = _number(left + width * port.lateral_fraction)
        location = (x_value, bottom)
        decisions.append(
            ElectricalPortDecision(
                port_key=port.port_key,
                side=port.side,
                location=location,
                connection_style=port.connection_style,
                direction=port.direction,
                connection_start=location,
                connection_end=(x_value, lowest),
                source_primitive_ids=source_ids,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.port_key))


def interpret_electrical_symbols(
    evidence: PdfBoxedSymbolEvidenceManifest,
    pack: DomainPack,
) -> ElectricalDomainDecisionManifest:
    """Match declarative symbol signatures and validate port topology."""

    primitives = evidence.primitive_by_id()
    hypotheses: list[ElectricalSymbolHypothesis] = []
    for rule in pack.electrical_symbol_rules:
        signature = rule.recognition_signature
        if signature is None:
            continue
        for candidate in evidence.boxed_candidates:
            left, bottom, right, top = candidate.frame_bounds_pt
            width = right - left
            height = top - bottom
            if not (
                signature.minimum_frame_size_pt <= width <= signature.maximum_frame_size_pt
                and signature.minimum_frame_size_pt
                <= height
                <= signature.maximum_frame_size_pt
            ):
                continue
            counts = tuple(
                sorted(primitives[item].segment_count for item in candidate.interior_primitive_ids)
            )
            if counts != tuple(sorted(signature.interior_segment_count_multiset)):
                continue
            ports = _port_decisions(candidate, rule, primitives)
            accepted = ports is not None
            source_ids = set(candidate.frame_primitive_ids)
            source_ids.update(candidate.interior_primitive_ids)
            if ports is not None:
                for port in ports:
                    source_ids.update(port.source_primitive_ids)
            hypotheses.append(
                ElectricalSymbolHypothesis.create(
                    candidate=candidate,
                    rule=rule,
                    state=(
                        ElectricalDecisionState.ACCEPTED
                        if accepted
                        else ElectricalDecisionState.REJECTED
                    ),
                    confidence=0.99 if accepted else 0.74,
                    reasons=(
                        "DRAWING_LEGEND_GLYPH_SIGNATURE_MATCH",
                        (
                            "PORT_TOPOLOGY_MATCH"
                            if accepted
                            else "NO_OPERATIONAL_PORT_TOPOLOGY"
                        ),
                        "BODY_CROSSING_FORBIDDEN_BY_DOMAIN_RULE",
                    ),
                    source_primitive_ids=source_ids,
                    ports=() if ports is None else ports,
                )
            )
    return ElectricalDomainDecisionManifest(
        source_document_id=evidence.source_document_id,
        source_page=evidence.source_page,
        evidence_manifest_id=evidence.manifest_id,
        domain_pack_id=pack.pack_id,
        hypotheses=tuple(
            sorted(hypotheses, key=lambda item: item.stable_hypothesis_id)
        ),
    )


@dataclass(frozen=True)
class LogicalElectricalConnection:
    logical_line_id: str
    port_key: str
    start: tuple[float, float]
    end: tuple[float, float]
    style_ref: str
    direction: str
    source_primitive_ids: tuple[str, ...]
    provenance_id: str
    meaningful_boundary: str = "SYMBOL_BOUNDARY"
    observed_evidence_coverage: float = 1.0
    inferred_length: float = 0.0
    gap_causes: tuple[str, ...] = ("SYMBOL_BOUNDARY",)
    state: str = "OBSERVED"
    schema_version: str = DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION

    @classmethod
    def create(
        cls,
        *,
        hypothesis: ElectricalSymbolHypothesis,
        port: ElectricalPortDecision,
    ) -> LogicalElectricalConnection:
        provenance = semantic_id(
            "logical-electrical-connection-provenance",
            DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
            {
                "hypothesis_id": hypothesis.stable_hypothesis_id,
                "port": port.to_dict(),
            },
        )
        identity = {
            "hypothesis_id": hypothesis.stable_hypothesis_id,
            "port_key": port.port_key,
            "start": list(port.connection_start),
            "end": list(port.connection_end),
            "style_ref": port.connection_style.value,
            "direction": port.direction,
            "source_primitive_ids": list(port.source_primitive_ids),
            "provenance_id": provenance,
            "meaningful_boundary": "SYMBOL_BOUNDARY",
            "observed_evidence_coverage": 1.0,
            "inferred_length": 0.0,
            "gap_causes": ["SYMBOL_BOUNDARY"],
            "state": "OBSERVED",
        }
        return cls(
            logical_line_id=semantic_id(
                "logical-electrical-connection",
                DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
                identity,
            ),
            port_key=port.port_key,
            start=port.connection_start,
            end=port.connection_end,
            style_ref=port.connection_style.value,
            direction=port.direction,
            source_primitive_ids=port.source_primitive_ids,
            provenance_id=provenance,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_line_id": self.logical_line_id,
            "port_key": self.port_key,
            "start": list(self.start),
            "end": list(self.end),
            "style_ref": self.style_ref,
            "direction": self.direction,
            "source_primitive_ids": list(self.source_primitive_ids),
            "provenance_id": self.provenance_id,
            "meaningful_boundary": self.meaningful_boundary,
            "observed_evidence_coverage": self.observed_evidence_coverage,
            "inferred_length": self.inferred_length,
            "gap_causes": list(self.gap_causes),
            "state": self.state,
        }


@dataclass(frozen=True)
class LogicalElectricalSymbol:
    logical_entity_id: str
    domain_identity: str
    inventory_identity: str
    frame_bounds_pt: tuple[float, float, float, float]
    source_evidence_ids: tuple[str, ...]
    connections: tuple[LogicalElectricalConnection, ...]
    provenance_id: str
    confidence: float
    cad_block_ref: str
    display_label: str
    coordinate_space: str
    state: str = "OBSERVED"
    annotation_relationship: str | None = None
    schema_version: str = DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION

    @classmethod
    def from_hypothesis(
        cls,
        hypothesis: ElectricalSymbolHypothesis,
    ) -> LogicalElectricalSymbol:
        connections = tuple(
            sorted(
                (
                    LogicalElectricalConnection.create(
                        hypothesis=hypothesis,
                        port=port,
                    )
                    for port in hypothesis.ports
                ),
                key=lambda item: item.logical_line_id,
            )
        )
        provenance = semantic_id(
            "logical-electrical-symbol-provenance",
            DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
            {
                "hypothesis_id": hypothesis.stable_hypothesis_id,
                "source_evidence_ids": list(hypothesis.source_primitive_ids),
                "connection_ids": [item.logical_line_id for item in connections],
            },
        )
        identity = {
            "hypothesis_id": hypothesis.stable_hypothesis_id,
            "domain_identity": hypothesis.canonical_domain_identity,
            "frame_bounds_pt": list(hypothesis.frame_bounds_pt),
            "source_evidence_ids": list(hypothesis.source_primitive_ids),
            "connection_ids": [item.logical_line_id for item in connections],
            "provenance_id": provenance,
            "state": "OBSERVED",
            "cad_block_ref": hypothesis.cad_block_ref,
            "display_label": hypothesis.display_label,
            "coordinate_space": hypothesis.coordinate_space,
        }
        return cls(
            logical_entity_id=semantic_id(
                "logical-electrical-symbol",
                DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
                identity,
            ),
            domain_identity=hypothesis.canonical_domain_identity,
            inventory_identity=hypothesis.inventory_canonical_identity,
            frame_bounds_pt=hypothesis.frame_bounds_pt,
            source_evidence_ids=hypothesis.source_primitive_ids,
            connections=connections,
            provenance_id=provenance,
            confidence=hypothesis.confidence,
            cad_block_ref=hypothesis.cad_block_ref,
            display_label=hypothesis.display_label,
            coordinate_space=hypothesis.coordinate_space,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_entity_id": self.logical_entity_id,
            "domain_identity": self.domain_identity,
            "inventory_identity": self.inventory_identity,
            "frame_bounds_pt": list(self.frame_bounds_pt),
            "source_evidence_ids": list(self.source_evidence_ids),
            "connections": [item.to_dict() for item in self.connections],
            "provenance_id": self.provenance_id,
            "confidence": self.confidence,
            "state": self.state,
            "annotation_relationship": self.annotation_relationship,
            "cad_block_ref": self.cad_block_ref,
            "display_label": self.display_label,
            "coordinate_space": self.coordinate_space,
        }


@dataclass(frozen=True)
class LogicalElectricalManifest:
    source_document_id: str
    source_page: int
    decision_manifest_id: str
    coordinate_space: str
    symbols: tuple[LogicalElectricalSymbol, ...]
    schema_version: str = DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION

    @property
    def manifest_id(self) -> str:
        return semantic_id(
            "logical-electrical-manifest",
            self.schema_version,
            {
                "source_document_id": self.source_document_id,
                "source_page": self.source_page,
                "decision_manifest_id": self.decision_manifest_id,
                "coordinate_space": self.coordinate_space,
                "symbol_ids": [item.logical_entity_id for item in self.symbols],
            },
        )

    @property
    def connections(self) -> tuple[LogicalElectricalConnection, ...]:
        by_id: dict[str, LogicalElectricalConnection] = {}
        for symbol in self.symbols:
            for line in symbol.connections:
                existing = by_id.get(line.logical_line_id)
                if existing is not None and existing != line:
                    raise ValueError("Shared logical connection definitions disagree")
                by_id[line.logical_line_id] = line
        return tuple(sorted(by_id.values(), key=lambda item: item.logical_line_id))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "decision_manifest_id": self.decision_manifest_id,
            "coordinate_space": self.coordinate_space,
            "symbol_count": len(self.symbols),
            "connected_line_count": len(self.connections),
            "symbols": [item.to_dict() for item in self.symbols],
            "connections": [item.to_dict() for item in self.connections],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def assemble_logical_electrical_entities(
    decisions: ElectricalDomainDecisionManifest,
) -> LogicalElectricalManifest:
    symbols = tuple(
        sorted(
            (LogicalElectricalSymbol.from_hypothesis(item) for item in decisions.accepted),
            key=lambda item: item.logical_entity_id,
        )
    )
    return LogicalElectricalManifest(
        source_document_id=decisions.source_document_id,
        source_page=decisions.source_page,
        decision_manifest_id=decisions.manifest_id,
        coordinate_space="normalized-page-point",
        symbols=symbols,
    )
