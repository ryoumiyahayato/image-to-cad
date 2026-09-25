"""Electrical Domain Pack interpretation of domain-neutral raster evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .draftsman_contract import semantic_id
from .draftsman_domain_pack import (
    DomainPack,
    ElectricalConnectionStyle,
    ElectricalPortSide,
    ElectricalSymbolRule,
)
from .draftsman_electrical import (
    DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
    ElectricalDecisionState,
    ElectricalDomainDecisionManifest,
    ElectricalPortDecision,
    ElectricalSymbolHypothesis,
    LogicalElectricalConnection,
    LogicalElectricalManifest,
    LogicalElectricalSymbol,
)
from .draftsman_raster_evidence import (
    RasterElectricalCandidateEvidence,
    RasterEvidenceManifest,
    RasterGlyphEvidence,
    RasterLineFragmentEvidence,
)


DRAFTSMAN_RASTER_DOMAIN_VERSION = "draftsman-raster-electrical-domain-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


def _template_score(rows: tuple[str, ...], template: tuple[str, ...]) -> float:
    observed = {
        (row_index, column_index)
        for row_index, row in enumerate(rows)
        for column_index, value in enumerate(row)
        if value == "#"
    }
    expected = {
        (row_index, column_index)
        for row_index, row in enumerate(template)
        for column_index, value in enumerate(row)
        if value == "#"
    }
    intersection = len(observed & expected)
    return _number(2.0 * intersection / max(1, len(observed) + len(expected)))


@dataclass(frozen=True)
class RasterDomainMatch:
    candidate_id: str
    rule_id: str
    template_score: float
    aligned_repetition: int
    accepted: bool
    reasons: tuple[str, ...]
    schema_version: str = DRAFTSMAN_RASTER_DOMAIN_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "template_score": self.template_score,
            "aligned_repetition": self.aligned_repetition,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RasterElectricalInterpretation:
    decisions: ElectricalDomainDecisionManifest
    matches: tuple[RasterDomainMatch, ...]
    schema_version: str = DRAFTSMAN_RASTER_DOMAIN_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decisions": self.decisions.to_dict(),
            "matches": [item.to_dict() for item in self.matches],
        }


def _aligned_groups(
    candidates: Iterable[RasterElectricalCandidateEvidence],
    *,
    tolerance_px: float,
) -> tuple[tuple[RasterElectricalCandidateEvidence, ...], ...]:
    groups: list[list[RasterElectricalCandidateEvidence]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.source_center_px[1], item.source_center_px[0]),
    ):
        for group in groups:
            mean_y = sum(item.source_center_px[1] for item in group) / len(group)
            if abs(candidate.source_center_px[1] - mean_y) <= tolerance_px:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    return tuple(
        tuple(sorted(group, key=lambda item: item.source_center_px[0]))
        for group in groups
    )


def _raster_ports(
    candidate: RasterElectricalCandidateEvidence,
    rule: ElectricalSymbolRule,
    *,
    image_height: int,
) -> tuple[ElectricalPortDecision, ...]:
    x_value, source_y = candidate.source_center_px
    cad_y = _number(image_height - source_y)
    radius = candidate.radius_px
    source_ids = tuple(
        sorted(
            {
                candidate.glyph_evidence_id,
                *candidate.nearby_line_evidence_ids,
            }
        )
    )
    decisions: list[ElectricalPortDecision] = []
    for port in rule.ports:
        if port.side is ElectricalPortSide.LEFT:
            location = (_number(x_value - radius), cad_y)
            end = (_number(x_value - radius - 24), cad_y)
        elif port.side is ElectricalPortSide.RIGHT:
            location = (_number(x_value + radius), cad_y)
            end = (_number(x_value + radius + 24), cad_y)
        else:
            continue
        decisions.append(
            ElectricalPortDecision(
                port_key=port.port_key,
                side=port.side,
                location=location,
                connection_style=port.connection_style,
                direction=port.direction,
                connection_start=location,
                connection_end=end,
                source_primitive_ids=source_ids,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.port_key))


def interpret_raster_electrical_symbols(
    evidence: RasterEvidenceManifest,
    pack: DomainPack,
) -> RasterElectricalInterpretation:
    """Apply the same ElectricalSymbolRule contract to raster evidence."""

    primitives = evidence.primitive_by_id()
    hypotheses: list[ElectricalSymbolHypothesis] = []
    matches: list[RasterDomainMatch] = []
    for rule in pack.electrical_symbol_rules:
        signature = rule.raster_recognition_signature
        if signature is None:
            continue
        qualified: list[RasterElectricalCandidateEvidence] = []
        scores: dict[str, float] = {}
        for candidate in evidence.candidates:
            glyph = primitives[candidate.glyph_evidence_id]
            if not isinstance(glyph, RasterGlyphEvidence):
                continue
            score = _template_score(
                glyph.normalized_patch_rows,
                signature.normalized_template_rows,
            )
            scores[candidate.stable_candidate_id] = score
            if (
                score >= signature.minimum_template_score
                and glyph.ring_coverage >= signature.minimum_ring_coverage
                and candidate.left_line_support >= signature.minimum_port_support
                and candidate.right_line_support >= signature.minimum_port_support
            ):
                qualified.append(candidate)
        groups = _aligned_groups(
            qualified,
            tolerance_px=signature.alignment_tolerance_px,
        )
        repetition_by_id = {
            candidate.stable_candidate_id: len(group)
            for group in groups
            for candidate in group
        }
        for candidate in qualified:
            repetition = repetition_by_id[candidate.stable_candidate_id]
            accepted = repetition >= signature.minimum_aligned_repetition
            reasons = tuple(
                sorted(
                    {
                        "RASTER_GLYPH_SIGNATURE_MATCH",
                        "DRAWING_SPECIFIC_TAG_RANGE_AUTHORITY",
                        "TWO_PORT_INLINE_TOPOLOGY_MATCH",
                        (
                            "REPEATED_ALIGNED_FAMILY_MATCH"
                            if accepted
                            else "INSUFFICIENT_REPEATED_CONTEXT"
                        ),
                        "BODY_CROSSING_FORBIDDEN_BY_DOMAIN_RULE",
                    }
                )
            )
            ports = (
                _raster_ports(
                    candidate,
                    rule,
                    image_height=evidence.image_size_px[1],
                )
                if accepted
                else ()
            )
            source_ids = {
                candidate.glyph_evidence_id,
                candidate.tag_evidence_id,
                *candidate.nearby_line_evidence_ids,
            }
            hypotheses.append(
                ElectricalSymbolHypothesis.from_normalized_evidence(
                    candidate_id=candidate.stable_candidate_id,
                    rule=rule,
                    state=(
                        ElectricalDecisionState.ACCEPTED
                        if accepted
                        else ElectricalDecisionState.REJECTED
                    ),
                    confidence=(
                        min(0.99, 0.55 + scores[candidate.stable_candidate_id] * 0.45)
                        if accepted
                        else min(0.79, scores[candidate.stable_candidate_id])
                    ),
                    reasons=reasons,
                    source_primitive_ids=source_ids,
                    ports=ports,
                    frame_bounds=candidate.normalized_frame_bounds,
                    coordinate_space="normalized-image-pixel-y-up",
                    frontend_kind="RASTER_IMAGE",
                )
            )
            matches.append(
                RasterDomainMatch(
                    candidate_id=candidate.stable_candidate_id,
                    rule_id=rule.rule_id,
                    template_score=scores[candidate.stable_candidate_id],
                    aligned_repetition=repetition,
                    accepted=accepted,
                    reasons=reasons,
                )
            )
    decisions = ElectricalDomainDecisionManifest(
        source_document_id=evidence.source_document_id,
        source_page=evidence.source_page,
        evidence_manifest_id=evidence.manifest_id,
        domain_pack_id=pack.pack_id,
        hypotheses=tuple(
            sorted(hypotheses, key=lambda item: item.stable_hypothesis_id)
        ),
    )
    return RasterElectricalInterpretation(
        decisions=decisions,
        matches=tuple(sorted(matches, key=lambda item: item.candidate_id)),
    )


def _coverage(
    start_x: float,
    end_x: float,
    fragments: Iterable[RasterLineFragmentEvidence],
) -> tuple[float, float, tuple[str, ...]]:
    intervals = sorted(
        (
            max(start_x, item.start[0]),
            min(end_x, item.end[0]),
            item.stable_evidence_id,
        )
        for item in fragments
        if item.end[0] > start_x and item.start[0] < end_x
    )
    source_ids = tuple(sorted({item[2] for item in intervals if item[1] > item[0]}))
    merged: list[tuple[float, float]] = []
    for left, right, _ in intervals:
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    total = max(0.0, end_x - start_x)
    observed = sum(right - left for left, right in merged)
    ratio = 0.0 if total <= 0.0 else min(1.0, observed / total)
    return _number(ratio), _number(max(0.0, total - observed)), source_ids


def _logical_connection(
    *,
    index: int,
    start: tuple[float, float],
    end: tuple[float, float],
    source_ids: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    coverage: float,
    inferred_length: float,
) -> LogicalElectricalConnection:
    gap_causes = (
        ("DETECTION_BREAK", "SYMBOL_BOUNDARY")
        if inferred_length > 0.5
        else ("SYMBOL_BOUNDARY",)
    )
    state = "RECONSTRUCTED" if inferred_length > 0.5 else "OBSERVED"
    provenance_payload = {
        "candidate_ids": list(candidate_ids),
        "source_primitive_ids": list(source_ids),
        "start": list(start),
        "end": list(end),
        "observed_evidence_coverage": coverage,
        "inferred_length": inferred_length,
        "gap_causes": list(gap_causes),
        "rule": "INLINE_BUS_SEGMENT_BETWEEN_SYMBOL_BOUNDARIES",
    }
    provenance = semantic_id(
        "logical-raster-electrical-connection-provenance",
        DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
        provenance_payload,
    )
    identity = {
        **provenance_payload,
        "port_key": f"ALARM_BUS_SEGMENT_{index:02d}",
        "style_ref": ElectricalConnectionStyle.CONTINUOUS_SIGNAL.value,
        "direction": "BIDIRECTIONAL",
        "provenance_id": provenance,
        "meaningful_boundary": "SYMBOL_BOUNDARY",
        "state": state,
    }
    return LogicalElectricalConnection(
        logical_line_id=semantic_id(
            "logical-electrical-connection",
            DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
            identity,
        ),
        port_key=f"ALARM_BUS_SEGMENT_{index:02d}",
        start=start,
        end=end,
        style_ref=ElectricalConnectionStyle.CONTINUOUS_SIGNAL.value,
        direction="BIDIRECTIONAL",
        source_primitive_ids=source_ids,
        provenance_id=provenance,
        observed_evidence_coverage=coverage,
        inferred_length=inferred_length,
        gap_causes=gap_causes,
        state=state,
    )


def assemble_raster_logical_electrical_entities(
    evidence: RasterEvidenceManifest,
    interpretation: RasterElectricalInterpretation,
    pack: DomainPack,
) -> LogicalElectricalManifest:
    """Build shared complete bus segments, never a line through a symbol body."""

    accepted = sorted(
        interpretation.decisions.accepted,
        key=lambda item: item.frame_bounds_pt[0],
    )
    if not accepted:
        return LogicalElectricalManifest(
            source_document_id=evidence.source_document_id,
            source_page=evidence.source_page,
            decision_manifest_id=interpretation.decisions.manifest_id,
            coordinate_space="normalized-image-pixel-y-up",
            symbols=(),
        )
    raster_rule = next(
        rule for rule in pack.electrical_symbol_rules if rule.raster_recognition_signature
    )
    signature = raster_rule.raster_recognition_signature
    if signature is None:  # pragma: no cover - narrowed by generator above
        raise ValueError("Raster rule lost its recognition signature")
    line_fragments = evidence.line_fragments
    common_y = _number(
        sum((item.frame_bounds_pt[1] + item.frame_bounds_pt[3]) / 2.0 for item in accepted)
        / len(accepted)
    )
    source_y = evidence.image_size_px[1] - common_y
    aligned_lines = tuple(
        item
        for item in line_fragments
        if abs(
            ((item.source_bbox_px[1] + item.source_bbox_px[3]) / 2.0)
            - source_y
        )
        <= signature.alignment_tolerance_px
    )
    intervals: list[
        tuple[float, float, tuple[str, ...], tuple[str, ...]]
    ] = []
    first = accepted[0]
    first_left = first.frame_bounds_pt[0]
    left_sources = [
        item
        for item in aligned_lines
        if first_left - 10 <= item.end[0] <= first_left + 10
        and item.start[0] < first_left
    ]
    if left_sources:
        selected = max(left_sources, key=lambda item: item.end[0] - item.start[0])
        intervals.append(
            (
                selected.start[0],
                first_left,
                (first.candidate_id,),
                (selected.stable_evidence_id,),
            )
        )
    for left_symbol, right_symbol in zip(accepted, accepted[1:]):
        intervals.append(
            (
                left_symbol.frame_bounds_pt[2],
                right_symbol.frame_bounds_pt[0],
                (left_symbol.candidate_id, right_symbol.candidate_id),
                (),
            )
        )
    last = accepted[-1]
    last_right = last.frame_bounds_pt[2]
    right_sources = [
        item
        for item in aligned_lines
        if last_right - 10 <= item.start[0] <= last_right + 10
        and item.end[0] > last_right
    ]
    if right_sources:
        selected = max(right_sources, key=lambda item: item.end[0] - item.start[0])
        intervals.append(
            (
                last_right,
                selected.end[0],
                (last.candidate_id,),
                (selected.stable_evidence_id,),
            )
        )
    connections: list[LogicalElectricalConnection] = []
    connection_members: dict[str, set[str]] = {
        item.candidate_id: set() for item in accepted
    }
    for index, (start_x, end_x, candidate_ids, explicit_ids) in enumerate(intervals):
        coverage, inferred_length, source_ids = _coverage(
            start_x,
            end_x,
            aligned_lines,
        )
        source_ids = tuple(sorted({*source_ids, *explicit_ids}))
        if coverage < signature.minimum_connection_evidence_coverage:
            continue
        connection = _logical_connection(
            index=index,
            start=(_number(start_x), common_y),
            end=(_number(end_x), common_y),
            source_ids=source_ids,
            candidate_ids=candidate_ids,
            coverage=coverage,
            inferred_length=inferred_length,
        )
        connections.append(connection)
        for candidate_id in candidate_ids:
            connection_members[candidate_id].add(connection.logical_line_id)
    connection_by_id = {item.logical_line_id: item for item in connections}
    symbols: list[LogicalElectricalSymbol] = []
    for hypothesis in accepted:
        related = tuple(
            sorted(
                (
                    connection_by_id[item]
                    for item in connection_members[hypothesis.candidate_id]
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
                "connection_ids": [item.logical_line_id for item in related],
                "frontend_kind": "RASTER_IMAGE",
            },
        )
        identity = {
            "hypothesis_id": hypothesis.stable_hypothesis_id,
            "domain_identity": hypothesis.canonical_domain_identity,
            "frame_bounds_pt": list(hypothesis.frame_bounds_pt),
            "source_evidence_ids": list(hypothesis.source_primitive_ids),
            "connection_ids": [item.logical_line_id for item in related],
            "provenance_id": provenance,
            "state": "OBSERVED",
            "cad_block_ref": hypothesis.cad_block_ref,
            "display_label": hypothesis.display_label,
            "coordinate_space": hypothesis.coordinate_space,
        }
        symbols.append(
            LogicalElectricalSymbol(
                logical_entity_id=semantic_id(
                    "logical-electrical-symbol",
                    DRAFTSMAN_LOGICAL_ELECTRICAL_VERSION,
                    identity,
                ),
                domain_identity=hypothesis.canonical_domain_identity,
                inventory_identity=hypothesis.inventory_canonical_identity,
                frame_bounds_pt=hypothesis.frame_bounds_pt,
                source_evidence_ids=hypothesis.source_primitive_ids,
                connections=related,
                provenance_id=provenance,
                confidence=hypothesis.confidence,
                cad_block_ref=hypothesis.cad_block_ref,
                display_label=hypothesis.display_label,
                coordinate_space=hypothesis.coordinate_space,
                annotation_relationship="ASSOCIATED_TAG_REGION_CONTENT_UNDECODED",
            )
        )
    return LogicalElectricalManifest(
        source_document_id=evidence.source_document_id,
        source_page=evidence.source_page,
        decision_manifest_id=interpretation.decisions.manifest_id,
        coordinate_space="normalized-image-pixel-y-up",
        symbols=tuple(sorted(symbols, key=lambda item: item.logical_entity_id)),
    )
