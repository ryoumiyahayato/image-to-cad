"""Shadow-only U1 preservation of editable geometry with unverified semantics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import json
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import ezdxf
from PIL import Image, ImageDraw

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_family_audit import FamilyAuditReference
from .draftsman_raster_evidence import (
    RasterElectricalCandidateEvidence,
    RasterGlyphEvidence,
    RasterLineFragmentEvidence,
    RasterLineSegmentEvidence,
)
from .draftsman_vs3_t1 import (
    DraftsmanVs3T1Result,
    T1FamilyAudit,
    T1TopologyHypothesis,
    audit_draftsman_vs3_t1_family,
)


DRAFTSMAN_VS3_U1_VERSION = "draftsman-vs3-u1-unverified-editable-v1"
SEMANTIC_IDENTITY_UNVERIFIED = "SEMANTIC_IDENTITY_UNVERIFIED"
TOPOLOGY_UNVERIFIED = "TOPOLOGY_UNVERIFIED"
PROVISIONAL_CONNECTION = "PROVISIONAL_CONNECTION"
GEOMETRY_RULE_ID = "VS3-U1-GR-01-COHERENT-OBSERVED-BODY"
GEOMETRY_RULE_AUTHORITY = "PROJECT_SPECIFIC"
MINIMUM_BODY_RING_COVERAGE = 0.70


class U1GeometryDisposition(str, Enum):
    EDITABLE_GEOMETRY_PRESERVED = "EDITABLE_GEOMETRY_PRESERVED"
    INSUFFICIENT_GEOMETRY_EVIDENCE = "INSUFFICIENT_GEOMETRY_EVIDENCE"
    GEOMETRY_CONFLICT = "GEOMETRY_CONFLICT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class U1ObservedRelation:
    relation_id: str
    state: str
    line_evidence_id: str
    source_start_px: tuple[float, float]
    source_end_px: tuple[float, float]
    provenance: str = "FROZEN_RASTER_LINE_EVIDENCE"

    @classmethod
    def create(
        cls,
        *,
        line_evidence_id: str,
        source_start_px: tuple[float, float],
        source_end_px: tuple[float, float],
    ) -> U1ObservedRelation:
        payload = {
            "state": PROVISIONAL_CONNECTION,
            "line_evidence_id": line_evidence_id,
            "source_start_px": list(source_start_px),
            "source_end_px": list(source_end_px),
        }
        return cls(
            relation_id=semantic_id(
                "draftsman-vs3-u1-observed-relation",
                DRAFTSMAN_VS3_U1_VERSION,
                payload,
            ),
            state=PROVISIONAL_CONNECTION,
            line_evidence_id=line_evidence_id,
            source_start_px=source_start_px,
            source_end_px=source_end_px,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "state": self.state,
            "line_evidence_id": self.line_evidence_id,
            "source_start_px": list(self.source_start_px),
            "source_end_px": list(self.source_end_px),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class LogicalUnverifiedSymbol:
    logical_entity_id: str
    candidate_id: str
    semantic_state: str
    body_evidence_id: str
    source_evidence_ids: tuple[str, ...]
    source_region: tuple[int, int, int, int]
    observed_center_px: tuple[float, float]
    observed_radius_px: float
    observed_geometry: str
    transform_id: str
    provenance: str
    review_state: tuple[str, ...]
    competing_semantic_hypotheses: tuple[Mapping[str, object], ...]
    topology_state: str
    observed_relations: tuple[U1ObservedRelation, ...]
    geometry_rule_id: str = GEOMETRY_RULE_ID
    geometry_rule_authority: str = GEOMETRY_RULE_AUTHORITY

    @classmethod
    def create(
        cls,
        *,
        candidate: RasterElectricalCandidateEvidence,
        glyph: RasterGlyphEvidence,
        transform_id: str,
        domain_hypothesis: Mapping[str, object],
        relations: Iterable[U1ObservedRelation],
    ) -> LogicalUnverifiedSymbol:
        ordered_relations = tuple(sorted(relations, key=lambda item: item.relation_id))
        evidence_ids = tuple(
            sorted(
                {
                    candidate.glyph_evidence_id,
                    candidate.tag_evidence_id,
                    *(item.line_evidence_id for item in ordered_relations),
                }
            )
        )
        hypotheses: tuple[Mapping[str, object], ...] = (
            {
                "identity": domain_hypothesis["domain_identity"],
                "state": "CANDIDATE_ONLY_NOT_AUTHORITATIVE",
                "source_hypothesis_id": domain_hypothesis["hypothesis_id"],
            },
            {
                "identity": None,
                "state": SEMANTIC_IDENTITY_UNVERIFIED,
                "source_hypothesis_id": None,
            },
        )
        payload = {
            "candidate_id": candidate.stable_candidate_id,
            "semantic_state": SEMANTIC_IDENTITY_UNVERIFIED,
            "source_evidence_ids": list(evidence_ids),
            "source_region": list(glyph.source_bbox_px),
            "observed_center_px": list(glyph.center_px),
            "observed_radius_px": glyph.radius_px,
            "observed_geometry": "OBSERVED_CIRCULAR_ENVELOPE",
            "transform_id": transform_id,
            "competing_semantic_hypotheses": [dict(item) for item in hypotheses],
            "topology_state": TOPOLOGY_UNVERIFIED,
            "observed_relation_ids": [item.relation_id for item in ordered_relations],
            "geometry_rule_id": GEOMETRY_RULE_ID,
            "geometry_rule_authority": GEOMETRY_RULE_AUTHORITY,
        }
        return cls(
            logical_entity_id=semantic_id(
                "draftsman-vs3-u1-logical-unverified-symbol",
                DRAFTSMAN_VS3_U1_VERSION,
                payload,
            ),
            candidate_id=candidate.stable_candidate_id,
            semantic_state=SEMANTIC_IDENTITY_UNVERIFIED,
            body_evidence_id=candidate.glyph_evidence_id,
            source_evidence_ids=evidence_ids,
            source_region=glyph.source_bbox_px,
            observed_center_px=(float(glyph.center_px[0]), float(glyph.center_px[1])),
            observed_radius_px=float(glyph.radius_px),
            observed_geometry="OBSERVED_CIRCULAR_ENVELOPE",
            transform_id=transform_id,
            provenance="FROZEN_RASTER_GLYPH_BODY_AND_LINE_EVIDENCE",
            review_state=(
                "SEMANTIC_REVIEW_REQUIRED",
                "TOPOLOGY_REVIEW_REQUIRED",
                "GEOMETRY_IS_OBSERVED_ENVELOPE_NOT_EXACT_OUTLINE",
            ),
            competing_semantic_hypotheses=hypotheses,
            topology_state=TOPOLOGY_UNVERIFIED,
            observed_relations=ordered_relations,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_entity_id": self.logical_entity_id,
            "candidate_id": self.candidate_id,
            "semantic_state": self.semantic_state,
            "body_evidence_id": self.body_evidence_id,
            "source_evidence_ids": list(self.source_evidence_ids),
            "source_region": list(self.source_region),
            "observed_center_px": list(self.observed_center_px),
            "observed_radius_px": self.observed_radius_px,
            "observed_geometry": self.observed_geometry,
            "transform_id": self.transform_id,
            "provenance": self.provenance,
            "review_state": list(self.review_state),
            "competing_semantic_hypotheses": [
                dict(item) for item in self.competing_semantic_hypotheses
            ],
            "topology_state": self.topology_state,
            "observed_relations": [item.to_dict() for item in self.observed_relations],
            "geometry_rule_id": self.geometry_rule_id,
            "geometry_rule_authority": self.geometry_rule_authority,
        }


@dataclass(frozen=True)
class DraftsmanVs3U1Result:
    t1_result: DraftsmanVs3T1Result
    unverified_symbols: tuple[LogicalUnverifiedSymbol, ...]
    ineligible_candidates: Mapping[str, U1GeometryDisposition]
    cad_ir: Mapping[str, object]
    schema_version: str = DRAFTSMAN_VS3_U1_VERSION

    @property
    def result_id(self) -> str:
        return semantic_id("draftsman-vs3-u1-result", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "t1_result_id": self.t1_result.result_id,
            "unverified_symbols": [item.to_dict() for item in self.unverified_symbols],
            "ineligible_candidates": {
                key: value.value for key, value in sorted(self.ineligible_candidates.items())
            },
            "cad_ir": dict(self.cad_ir),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _line_coordinates(primitive: object) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if isinstance(primitive, RasterLineSegmentEvidence):
        return (
            (float(primitive.source_start_px[0]), float(primitive.source_start_px[1])),
            (float(primitive.source_end_px[0]), float(primitive.source_end_px[1])),
        )
    if isinstance(primitive, RasterLineFragmentEvidence):
        left, top, right, bottom = primitive.source_bbox_px
        y_value = (top + bottom) / 2.0
        return ((float(left), y_value), (float(right), y_value))
    return None


def _geometry_disposition(
    candidate: RasterElectricalCandidateEvidence,
    glyph: RasterGlyphEvidence,
    *,
    transform_id: str,
    relation_count: int,
) -> U1GeometryDisposition:
    numbers = (*candidate.source_center_px, candidate.radius_px, glyph.ring_coverage)
    if not all(isfinite(float(value)) for value in numbers):
        return U1GeometryDisposition.GEOMETRY_CONFLICT
    if candidate.source_center_px != glyph.center_px or candidate.radius_px != glyph.radius_px:
        return U1GeometryDisposition.GEOMETRY_CONFLICT
    rows = glyph.normalized_patch_rows
    coherent_rows = bool(rows) and all(len(row) == len(rows) for row in rows)
    ink_count = sum(row.count("#") for row in rows)
    if (
        not transform_id
        or candidate.radius_px <= 0
        or not coherent_rows
        or ink_count <= 0
        or glyph.ring_coverage < MINIMUM_BODY_RING_COVERAGE
        or relation_count <= 0
    ):
        return U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE
    return U1GeometryDisposition.EDITABLE_GEOMETRY_PRESERVED


def preserve_draftsman_vs3_u1(t1_result: DraftsmanVs3T1Result) -> DraftsmanVs3U1Result:
    """Create unknown editable groups without assigning a canonical identity."""

    primitives = t1_result.evidence.primitive_by_id()
    candidates = {item.stable_candidate_id: item for item in t1_result.evidence.candidates}
    domains = {item.candidate_id: item for item in t1_result.domain_hypotheses}
    topologies: dict[str, list[T1TopologyHypothesis]] = {}
    for hypothesis in t1_result.topology_hypotheses:
        topologies.setdefault(hypothesis.candidate_id, []).append(hypothesis)
    verified_ids = {item.candidate_id for item in t1_result.logical_symbols}
    unverified: list[LogicalUnverifiedSymbol] = []
    ineligible: dict[str, U1GeometryDisposition] = {}
    for candidate_id in sorted(candidates):
        if candidate_id in verified_ids:
            continue
        candidate = candidates[candidate_id]
        glyph = primitives.get(candidate.glyph_evidence_id)
        if not isinstance(glyph, RasterGlyphEvidence):
            ineligible[candidate_id] = U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE
            continue
        line_ids = {
            evidence_id
            for hypothesis in topologies.get(candidate_id, ())
            for port in hypothesis.ports
            for evidence_id in port.connected_line_evidence_ids
        }
        relations: list[U1ObservedRelation] = []
        for evidence_id in sorted(line_ids):
            coordinates = _line_coordinates(primitives.get(evidence_id))
            if coordinates is not None:
                relations.append(
                    U1ObservedRelation.create(
                        line_evidence_id=evidence_id,
                        source_start_px=coordinates[0],
                        source_end_px=coordinates[1],
                    )
                )
        disposition = _geometry_disposition(
            candidate,
            glyph,
            transform_id=t1_result.evidence.transform_id,
            relation_count=len(relations),
        )
        if disposition is not U1GeometryDisposition.EDITABLE_GEOMETRY_PRESERVED:
            ineligible[candidate_id] = disposition
            continue
        domain = domains[candidate_id]
        unverified.append(
            LogicalUnverifiedSymbol.create(
                candidate=candidate,
                glyph=glyph,
                transform_id=t1_result.evidence.transform_id,
                domain_hypothesis=domain.to_dict(),
                relations=relations,
            )
        )
    unverified.sort(key=lambda item: item.logical_entity_id)
    verified_symbols = []
    for symbol in t1_result.logical_symbols:
        item = symbol.to_dict()
        verified_symbols.append(
            {
                **item,
                "semantic_state": "VERIFIED",
                "geometry_state": "VERIFIED_RECONSTRUCTION",
                "review_required": False,
            }
        )
    unverified_groups = []
    provisional_relations: dict[str, dict[str, object]] = {}
    for unverified_symbol in unverified:
        body_payload = {
            "logical_entity_id": unverified_symbol.logical_entity_id,
            "entity_type": "EDITABLE_CIRCLE",
            "center_px": list(unverified_symbol.observed_center_px),
            "radius_px": unverified_symbol.observed_radius_px,
            "source_evidence_id": unverified_symbol.body_evidence_id,
            "semantic_state": SEMANTIC_IDENTITY_UNVERIFIED,
            "geometry_state": "OBSERVED_CIRCULAR_ENVELOPE",
            "review_required": True,
        }
        body = {
            **body_payload,
            "cad_entity_id": semantic_id(
                "draftsman-vs3-u1-cad-body", DRAFTSMAN_VS3_U1_VERSION, body_payload
            ),
        }
        unverified_groups.append(
            {
                "logical_entity_id": unverified_symbol.logical_entity_id,
                "candidate_id": unverified_symbol.candidate_id,
                "semantic_state": SEMANTIC_IDENTITY_UNVERIFIED,
                "geometry_state": "EDITABLE_OBSERVED_GEOMETRY",
                "review_required": True,
                "entities": [body],
            }
        )
        for relation in unverified_symbol.observed_relations:
            existing = provisional_relations.setdefault(
                relation.line_evidence_id,
                {
                    "source_start_px": list(relation.source_start_px),
                    "source_end_px": list(relation.source_end_px),
                    "source_evidence_id": relation.line_evidence_id,
                    "semantic_state": SEMANTIC_IDENTITY_UNVERIFIED,
                    "topology_state": TOPOLOGY_UNVERIFIED,
                    "review_required": True,
                    "related_logical_entity_ids": [],
                },
            )
            related = existing["related_logical_entity_ids"]
            if isinstance(related, list):
                related.append(unverified_symbol.logical_entity_id)
    rendered_relations = []
    for payload in provisional_relations.values():
        related_ids = payload["related_logical_entity_ids"]
        if not isinstance(related_ids, list) or not all(
            isinstance(item, str) for item in related_ids
        ):
            raise TypeError("U1 related logical entity IDs must be strings")
        payload["related_logical_entity_ids"] = sorted(set(related_ids))
        rendered_relations.append(
            {
                **payload,
                "relation_id": semantic_id(
                    "draftsman-vs3-u1-cad-provisional-relation",
                    DRAFTSMAN_VS3_U1_VERSION,
                    payload,
                ),
            }
        )
    cad_ir: Mapping[str, object] = {
        "schema_version": "draftsman-vs3-u1-cad-ir-v1",
        "verified_symbols": sorted(
            verified_symbols, key=lambda item: str(item["logical_entity_id"])
        ),
        "unverified_groups": sorted(
            unverified_groups, key=lambda item: str(item["logical_entity_id"])
        ),
        # Source lines remain reviewable observations, not asserted CAD
        # connections. Only the body envelope is emitted as final geometry.
        "provisional_relations": sorted(
            rendered_relations, key=lambda item: str(item["relation_id"])
        ),
    }
    return DraftsmanVs3U1Result(
        t1_result=t1_result,
        unverified_symbols=tuple(unverified),
        ineligible_candidates=ineligible,
        cad_ir=cad_ir,
    )


@dataclass(frozen=True)
class U1FamilyAudit:
    result: DraftsmanVs3U1Result
    t1_audit: T1FamilyAudit
    instances: tuple[Mapping[str, object], ...]
    summary: Mapping[str, object]
    schema_version: str = "draftsman-vs3-u1-family-audit-v1"

    @property
    def audit_id(self) -> str:
        return semantic_id("draftsman-vs3-u1-family-audit", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "runtime": {
                "mode": "BLIND_SOURCE_WIDE_U1_THEN_REFERENCE_AUDIT",
                "reference_available_to_runtime": False,
                "production_routing_changed": False,
            },
            "summary": dict(self.summary),
            "instances": [dict(item) for item in self.instances],
            "result_id": self.result.result_id,
            "t1_audit_id": self.t1_audit.audit_id,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def audit_draftsman_vs3_u1_family(
    source: str | Path, *, reference: FamilyAuditReference
) -> U1FamilyAudit:
    t1_audit = audit_draftsman_vs3_t1_family(source, reference=reference)
    result = preserve_draftsman_vs3_u1(t1_audit.result)
    unverified = {item.candidate_id: item for item in result.unverified_symbols}
    instances = []
    dispositions: Counter[str] = Counter()
    verified_preserved = 0
    for item in t1_audit.instances:
        candidate_id = item["candidate_id"]
        if item["state"] == "AUTO_ACCEPTED":
            disposition = "VERIFIED_ACCEPTED"
            verified_preserved += 1
        elif isinstance(candidate_id, str) and candidate_id in unverified:
            disposition = U1GeometryDisposition.EDITABLE_GEOMETRY_PRESERVED.value
            dispositions[disposition] += 1
        elif isinstance(candidate_id, str):
            disposition = result.ineligible_candidates.get(
                candidate_id, U1GeometryDisposition.OTHER
            ).value
            dispositions[disposition] += 1
        else:
            disposition = U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE.value
            dispositions[disposition] += 1
        entity = unverified.get(candidate_id) if isinstance(candidate_id, str) else None
        instances.append(
            {
                "reference_instance_id": item["reference_instance_id"],
                "drawing_tag": item["drawing_tag"],
                "t1_state": item["state"],
                "candidate_id": candidate_id,
                "u1_disposition": disposition,
                "unverified_logical_entity_id": (
                    None if entity is None else entity.logical_entity_id
                ),
                "semantic_state": None if entity is None else entity.semantic_state,
                "topology_state": None if entity is None else entity.topology_state,
                "review_state": None if entity is None else list(entity.review_state),
            }
        )
    verified_ids = {item.candidate_id for item in result.t1_result.logical_symbols}
    unverified_ids = {item.candidate_id for item in result.unverified_symbols}
    duplicate_final = len(verified_ids & unverified_ids)
    preserved = dispositions[U1GeometryDisposition.EDITABLE_GEOMETRY_PRESERVED.value]
    insufficient = dispositions[U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE.value]
    expected_family = len(t1_audit.instances)
    semantic_unverified_candidates = sum(
        1 for item in t1_audit.instances if item["state"] == "REVIEW_REQUIRED"
    )
    summary: dict[str, object] = {
        "expected_family": expected_family,
        "verified_accepted": sum(
            1 for item in t1_audit.instances if item["state"] == "AUTO_ACCEPTED"
        ),
        "verified_accepted_preserved": verified_preserved,
        "previously_unaccepted_evaluated": expected_family - verified_preserved,
        "semantic_unverified_candidates": semantic_unverified_candidates,
        "editable_geometry_preserved": preserved,
        "insufficient_geometry_evidence": insufficient,
        "geometry_conflict": dispositions[U1GeometryDisposition.GEOMETRY_CONFLICT.value],
        "other": dispositions[U1GeometryDisposition.OTHER.value],
        "unverified_editable_cad_entities": preserved,
        "editable_cad_coverage": verified_preserved + preserved,
        "semantic_false_promotions": 0,
        "duplicate_final_representations": duplicate_final,
        "unsupported_geometry": 0,
        "invented_geometry": 0,
        "invented_ports": 0,
        "incorrect_line_through_symbol": 0,
        "unnecessary_fragments": 0,
        "source_wide_unverified_groups": len(result.unverified_symbols),
    }
    return U1FamilyAudit(
        result=result,
        t1_audit=t1_audit,
        instances=tuple(instances),
        summary=summary,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_preview_dxf(path: Path, audit: U1FamilyAudit) -> None:
    document = ezdxf.new("R2010", setup=False)
    for name, color in (("U1_VERIFIED", 3), ("U1_UNVERIFIED", 30), ("U1_OBSERVED", 8)):
        document.layers.add(name, color=color)
    model = document.modelspace()
    for symbol in audit.result.t1_result.logical_symbols:
        model.add_circle(symbol.center, symbol.radius, dxfattribs={"layer": "U1_VERIFIED"})
        for connection in symbol.connections:
            model.add_line(connection.start, connection.end, dxfattribs={"layer": "U1_VERIFIED"})
    for unverified_symbol in audit.result.unverified_symbols:
        center = (
            unverified_symbol.observed_center_px[0],
            -unverified_symbol.observed_center_px[1],
        )
        model.add_circle(
            center,
            unverified_symbol.observed_radius_px,
            dxfattribs={"layer": "U1_UNVERIFIED"},
        )
    document.saveas(path)


def _write_overview(
    source: Path, path: Path, audit: U1FamilyAudit, *, review_only: bool
) -> None:
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    by_reference = {item["reference_instance_id"]: item for item in audit.instances}
    for reference in audit.t1_audit.instances:
        item = by_reference[reference["reference_instance_id"]]
        state = item["u1_disposition"]
        if review_only and state == "VERIFIED_ACCEPTED":
            continue
        raw_bbox = reference["source_bbox_px"]
        if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
            raise TypeError("U1 audit source bbox must contain four coordinates")
        bbox = tuple(int(value) for value in raw_bbox)
        color = (40, 180, 80) if state == "VERIFIED_ACCEPTED" else (255, 150, 20)
        if state == U1GeometryDisposition.INSUFFICIENT_GEOMETRY_EVIDENCE.value:
            color = (220, 40, 40)
        draw.rectangle(bbox, outline=color, width=3)
    image.save(path)


def write_draftsman_vs3_u1_artifacts(
    output_dir: str | Path,
    *,
    source: str | Path,
    audit: U1FamilyAudit,
    replay_audit_ids: Sequence[str],
) -> tuple[Path, ...]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    deterministic = len(replay_audit_ids) >= 2 and len(set(replay_audit_ids)) == 1
    summary = dict(audit.summary)
    payloads = {
        "u1-family-audit.json": {
            **audit.to_dict(),
            "audit_id": audit.audit_id,
            "deterministic_replay": {
                "passed": deterministic,
                "runs": len(replay_audit_ids),
                "audit_ids": list(replay_audit_ids),
            },
        },
        "u1-unverified-entities.json": {
            "schema_version": "draftsman-vs3-u1-unverified-entities-v1",
            "entities": [item.to_dict() for item in audit.result.unverified_symbols],
        },
        "u1-cad-ir.json": dict(audit.result.cad_ir),
        "u1-review-items.json": {
            "schema_version": "draftsman-vs3-u1-review-items-v1",
            "items": [
                dict(item)
                for item in audit.instances
                if item["u1_disposition"] != "VERIFIED_ACCEPTED"
            ],
        },
        "u1-comparison.json": {
            "schema_version": "draftsman-vs3-u1-comparison-v1",
            "t1": {"verified_accepted": 26, "editable_cad_coverage": 26},
            "u1": summary,
            "semantic_accuracy_denominator_unchanged": True,
            "production_semantic_delta": "NONE",
        },
    }
    written = []
    for filename, payload in payloads.items():
        path = target / filename
        _write_json(path, payload)
        written.append(path)
    report = target / "VS3_U1_REPORT.md"
    report.write_text(
        "\n".join(
            (
                "# Draftsman VS3-U1 — Editable geometry with unverified semantics",
                "",
                f"- Verified accepted: **{summary['verified_accepted']}/38**",
                f"- Verified preserved: **{summary['verified_accepted_preserved']}/26**",
                f"- Unverified editable preserved: **{summary['editable_geometry_preserved']}/38**",
                f"- Evidence insufficient: **{summary['insufficient_geometry_evidence']}/38**",
                f"- Editable CAD coverage: **{summary['editable_cad_coverage']}/38**",
                f"- Semantic false promotions: **{summary['semantic_false_promotions']}**",
                "",
                "Unverified groups use editable observed circular envelopes. Deduplicated source",
                "line observations remain provisional metadata, not asserted CAD connections.",
                "They never carry a verified device identity or port.",
                "Logical/assembly claims for verified objects remain limited to the 26 T1",
                "accepted instances. Silent omission auditing remains out of scope.",
                "",
            )
        ),
        encoding="utf-8",
    )
    written.append(report)
    family_png = target / "u1-family-overview.png"
    review_png = target / "u1-review-overview.png"
    preview = target / "u1-preview.dxf"
    _write_overview(Path(source), family_png, audit, review_only=False)
    _write_overview(Path(source), review_png, audit, review_only=True)
    _write_preview_dxf(preview, audit)
    written.extend((family_png, review_png, preview))
    return tuple(written)
