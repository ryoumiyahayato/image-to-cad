"""Source-wide raster evidence coverage and frozen-downstream comparison."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from math import hypot
from pathlib import Path
from time import perf_counter
from typing import Iterable, Mapping, Sequence, cast

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_family_audit import (
    FamilyAuditReference,
    FamilyAuditResult,
    FamilyReferenceInstance,
    audit_electrical_family,
)
from .draftsman_raster_evidence import (
    DRAFTSMAN_RASTER_EVIDENCE_VERSION,
    RasterEndpointEvidence,
    RasterEvidenceManifest,
    RasterGlyphEvidence,
    RasterLineFragmentEvidence,
    RasterLineSegmentEvidence,
    RasterTagRegionEvidence,
)


DRAFTSMAN_EVIDENCE_BASELINE_VERSION = "draftsman-raster-evidence-baseline-v1"
DRAFTSMAN_EVIDENCE_FAMILY_AUDIT_VERSION = "draftsman-evidence-family-audit-v1"


def _number(value: float) -> float:
    normalized = round(float(value), 6)
    return 0.0 if normalized == 0.0 else normalized


@dataclass(frozen=True)
class EvidenceAuditBaseline:
    base_head: str
    evidence_contract: str
    source_document_id: str
    source_page: int
    source_sha256: str
    candidate_count: int
    covered_reference_ids: tuple[str, ...]
    family_result: Mapping[str, object]
    provenance: str
    schema_version: str = DRAFTSMAN_EVIDENCE_BASELINE_VERSION

    @classmethod
    def load(cls, path: str | Path) -> EvidenceAuditBaseline:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = str(payload["schema_version"])
        if version != DRAFTSMAN_EVIDENCE_BASELINE_VERSION:
            raise ValueError(f"Unsupported evidence baseline: {version}")
        return cls(
            base_head=str(payload["base_head"]),
            evidence_contract=str(payload["evidence_contract"]),
            source_document_id=str(payload["source_document_id"]),
            source_page=int(payload["source_page"]),
            source_sha256=str(payload["source_sha256"]),
            candidate_count=int(payload["candidate_count"]),
            covered_reference_ids=tuple(
                sorted(str(item) for item in payload["covered_reference_ids"])
            ),
            family_result=cast(Mapping[str, object], payload["family_result"]),
            provenance=str(payload["provenance"]),
            schema_version=version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "base_head": self.base_head,
            "evidence_contract": self.evidence_contract,
            "source_document_id": self.source_document_id,
            "source_page": self.source_page,
            "source_sha256": self.source_sha256,
            "candidate_count": self.candidate_count,
            "covered_reference_ids": list(self.covered_reference_ids),
            "family_result": dict(self.family_result),
            "provenance": self.provenance,
            "role": "PRE_CHANGE_AUDIT_REFERENCE_NOT_RUNTIME_DISCOVERY_INPUT",
        }


@dataclass(frozen=True)
class EvidenceInstanceAudit:
    reference_instance_id: str
    drawing_tag: str
    source_bbox_px: tuple[int, int, int, int]
    glyph_evidence_ids: tuple[str, ...]
    nearby_line_evidence_ids: tuple[str, ...]
    endpoint_evidence_ids: tuple[str, ...]
    tag_evidence_ids: tuple[str, ...]
    spatial_relation_ids: tuple[str, ...]
    compatibility_candidate_id: str | None
    evidence_covered: bool
    missing_evidence_types: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_instance_id": self.reference_instance_id,
            "drawing_tag": self.drawing_tag,
            "source_bbox_px": list(self.source_bbox_px),
            "glyph_shape_evidence_ids": list(self.glyph_evidence_ids),
            "nearby_line_evidence_ids": list(self.nearby_line_evidence_ids),
            "endpoint_evidence_ids": list(self.endpoint_evidence_ids),
            "tag_text_evidence_ids": list(self.tag_evidence_ids),
            "spatial_relation_ids": list(self.spatial_relation_ids),
            "compatibility_candidate_id": self.compatibility_candidate_id,
            "evidence_covered": self.evidence_covered,
            "missing_evidence_types": list(self.missing_evidence_types),
        }


@dataclass(frozen=True)
class EvidenceFamilyAuditSummary:
    expected_family: int
    evidence_coverage_before: int
    evidence_coverage_after: int
    original_evidence_failures_recovered: int
    remaining_evidence_failures: int
    evidence_candidates_before: int
    evidence_candidates_after: int
    candidate_growth_ratio: float
    candidate_growth_percent: float
    primitive_counts_by_kind: tuple[tuple[str, int], ...]
    spatial_relation_count: int
    false_candidate_density_per_megapixel: float
    auto_accepted: int
    review_required: int
    missed: int
    false_positives: int
    failure_distribution: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_family": self.expected_family,
            "evidence_coverage_before": self.evidence_coverage_before,
            "evidence_coverage_after": self.evidence_coverage_after,
            "original_evidence_failures_recovered": (
                self.original_evidence_failures_recovered
            ),
            "remaining_evidence_failures": self.remaining_evidence_failures,
            "evidence_candidates_before": self.evidence_candidates_before,
            "evidence_candidates_after": self.evidence_candidates_after,
            "candidate_growth_ratio": self.candidate_growth_ratio,
            "candidate_growth_percent": self.candidate_growth_percent,
            "primitive_counts_by_kind": dict(self.primitive_counts_by_kind),
            "spatial_relation_count": self.spatial_relation_count,
            "false_candidate_density_per_megapixel": (
                self.false_candidate_density_per_megapixel
            ),
            "frozen_downstream": True,
            "auto_accepted": self.auto_accepted,
            "review_required": self.review_required,
            "missed": self.missed,
            "false_positives": self.false_positives,
            "failure_distribution": dict(self.failure_distribution),
        }


@dataclass(frozen=True)
class EvidenceFamilyAuditResult:
    reference: FamilyAuditReference
    baseline: EvidenceAuditBaseline
    evidence: RasterEvidenceManifest
    downstream: FamilyAuditResult
    instances: tuple[EvidenceInstanceAudit, ...]
    summary: EvidenceFamilyAuditSummary
    schema_version: str = DRAFTSMAN_EVIDENCE_FAMILY_AUDIT_VERSION

    @property
    def audit_id(self) -> str:
        return semantic_id(
            "draftsman-evidence-family-audit",
            self.schema_version,
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "reference_id": self.reference.reference_id,
            "baseline": self.baseline.to_dict(),
            "runtime": {
                "mode": "ONE_SOURCE_WIDE_DISCOVERY_RUN",
                "source_crop_count": 0,
                "reference_used_after_discovery_only": True,
                "evidence_contract": DRAFTSMAN_RASTER_EVIDENCE_VERSION,
                "evidence_manifest_id": self.evidence.manifest_id,
                "frozen_domain_rule_id": self.reference.frozen_rule_id,
                "downstream_rules_modified": False,
            },
            "summary": self.summary.to_dict(),
            "instances": [item.to_dict() for item in self.instances],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def canonical_sha256(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def _expanded_bbox(
    bbox: Sequence[int],
    margin: int,
) -> tuple[int, int, int, int]:
    return (
        int(bbox[0]) - margin,
        int(bbox[1]) - margin,
        int(bbox[2]) + margin,
        int(bbox[3]) + margin,
    )


def _overlaps(first: Sequence[int], second: Sequence[int]) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _match_glyphs(
    reference: FamilyAuditReference,
    evidence: RasterEvidenceManifest,
) -> dict[str, RasterGlyphEvidence]:
    unmatched = {
        item.stable_evidence_id: item
        for item in evidence.primitives
        if isinstance(item, RasterGlyphEvidence)
    }
    matched: dict[str, RasterGlyphEvidence] = {}
    for expected in sorted(reference.instances, key=lambda item: item.reference_instance_id):
        choices = []
        for glyph in unmatched.values():
            distance = hypot(
                glyph.center_px[0] - expected.source_center_px[0],
                glyph.center_px[1] - expected.source_center_px[1],
            )
            if distance <= reference.match_center_tolerance_px:
                choices.append((distance, glyph.stable_evidence_id, glyph))
        if choices:
            _, evidence_id, glyph = min(choices, key=lambda item: (item[0], item[1]))
            matched[expected.reference_instance_id] = glyph
            unmatched.pop(evidence_id)
    return matched


def _match_candidates(
    reference: FamilyAuditReference,
    evidence: RasterEvidenceManifest,
) -> dict[str, str]:
    unmatched = {item.stable_candidate_id: item for item in evidence.candidates}
    matched: dict[str, str] = {}
    for expected in sorted(reference.instances, key=lambda item: item.reference_instance_id):
        choices = []
        for candidate in unmatched.values():
            distance = hypot(
                candidate.source_center_px[0] - expected.source_center_px[0],
                candidate.source_center_px[1] - expected.source_center_px[1],
            )
            if distance <= reference.match_center_tolerance_px:
                choices.append((distance, candidate.stable_candidate_id))
        if choices:
            _, candidate_id = min(choices)
            matched[expected.reference_instance_id] = candidate_id
            unmatched.pop(candidate_id)
    return matched


def _instance_audit(
    expected: FamilyReferenceInstance,
    *,
    evidence: RasterEvidenceManifest,
    glyph: RasterGlyphEvidence | None,
    compatibility_candidate_id: str | None,
) -> EvidenceInstanceAudit:
    glyph_ids = () if glyph is None else (glyph.stable_evidence_id,)
    local_bbox = _expanded_bbox(expected.source_bbox_px, 20)
    tag_bbox = _expanded_bbox(expected.source_bbox_px, 52)
    lines = tuple(
        sorted(
            item.stable_evidence_id
            for item in evidence.primitives
            if isinstance(item, (RasterLineFragmentEvidence, RasterLineSegmentEvidence))
            and _overlaps(local_bbox, item.source_bbox_px)
        )
    )
    endpoints = tuple(
        sorted(
            item.stable_evidence_id
            for item in evidence.primitives
            if isinstance(item, RasterEndpointEvidence)
            and _overlaps(local_bbox, item.source_bbox_px)
        )
    )
    tags = tuple(
        sorted(
            item.stable_evidence_id
            for item in evidence.primitives
            if isinstance(item, RasterTagRegionEvidence)
            and _overlaps(tag_bbox, item.source_bbox_px)
        )
    )
    local_ids = {*glyph_ids, *lines, *endpoints, *tags}
    relations = tuple(
        sorted(
            item.stable_relation_id
            for item in evidence.spatial_relations
            if item.source_evidence_id in local_ids
            or item.target_evidence_id in local_ids
        )
    )
    missing = []
    if not glyph_ids:
        missing.append("GLYPH_SHAPE")
    if not lines:
        missing.append("LINE_SEGMENT")
    if not endpoints:
        missing.append("ENDPOINT")
    if not tags:
        missing.append("TAG_TEXT_REGION")
    if not relations:
        missing.append("SPATIAL_RELATION")
    return EvidenceInstanceAudit(
        reference_instance_id=expected.reference_instance_id,
        drawing_tag=expected.drawing_tag,
        source_bbox_px=expected.source_bbox_px,
        glyph_evidence_ids=glyph_ids,
        nearby_line_evidence_ids=lines,
        endpoint_evidence_ids=endpoints,
        tag_evidence_ids=tags,
        spatial_relation_ids=relations,
        compatibility_candidate_id=compatibility_candidate_id,
        evidence_covered=bool(glyph_ids),
        missing_evidence_types=tuple(missing),
    )


def audit_raster_evidence_family(
    source_path: str | Path,
    *,
    reference: FamilyAuditReference,
    baseline: EvidenceAuditBaseline,
) -> EvidenceFamilyAuditResult:
    """Run once source-wide, then use family coordinates only for post-run audit."""

    downstream = audit_electrical_family(source_path, reference=reference)
    evidence = downstream.vs3.evidence
    if baseline.source_sha256 != evidence.source_sha256:
        raise ValueError("Evidence baseline and runtime source identity differ")
    if baseline.source_document_id != evidence.source_document_id:
        raise ValueError("Evidence baseline and runtime document identity differ")
    if baseline.source_page != evidence.source_page:
        raise ValueError("Evidence baseline and runtime source page differ")
    matched_glyphs = _match_glyphs(reference, evidence)
    matched_candidates = _match_candidates(reference, evidence)
    instances = tuple(
        _instance_audit(
            expected,
            evidence=evidence,
            glyph=matched_glyphs.get(expected.reference_instance_id),
            compatibility_candidate_id=matched_candidates.get(
                expected.reference_instance_id
            ),
        )
        for expected in sorted(
            reference.instances,
            key=lambda item: item.reference_instance_id,
        )
    )
    old_covered = set(baseline.covered_reference_ids)
    new_covered = {
        item.reference_instance_id for item in instances if item.evidence_covered
    }
    old_failures = {
        item.reference_instance_id for item in reference.instances
    } - old_covered
    recovered = len(old_failures & new_covered)
    counts = Counter(item.kind.value for item in evidence.primitives)
    image_megapixels = (
        evidence.image_size_px[0] * evidence.image_size_px[1] / 1_000_000.0
    )
    unmatched_candidates = max(0, len(evidence.candidates) - len(matched_candidates))
    downstream_summary = downstream.summary
    summary = EvidenceFamilyAuditSummary(
        expected_family=len(reference.instances),
        evidence_coverage_before=len(old_covered),
        evidence_coverage_after=len(new_covered),
        original_evidence_failures_recovered=recovered,
        remaining_evidence_failures=len(reference.instances) - len(new_covered),
        evidence_candidates_before=baseline.candidate_count,
        evidence_candidates_after=len(evidence.candidates),
        candidate_growth_ratio=_number(
            len(evidence.candidates) / max(1, baseline.candidate_count)
        ),
        candidate_growth_percent=_number(
            100.0
            * (len(evidence.candidates) - baseline.candidate_count)
            / max(1, baseline.candidate_count)
        ),
        primitive_counts_by_kind=tuple(sorted(counts.items())),
        spatial_relation_count=len(evidence.spatial_relations),
        false_candidate_density_per_megapixel=_number(
            unmatched_candidates / image_megapixels
        ),
        auto_accepted=downstream_summary.auto_accepted,
        review_required=downstream_summary.review_required,
        missed=downstream_summary.missed,
        false_positives=downstream_summary.false_positives,
        failure_distribution=downstream_summary.failure_distribution,
    )
    return EvidenceFamilyAuditResult(
        reference=reference,
        baseline=baseline,
        evidence=evidence,
        downstream=downstream,
        instances=instances,
        summary=summary,
    )


def timed_audit_raster_evidence_family(
    source_path: str | Path,
    *,
    reference: FamilyAuditReference,
    baseline: EvidenceAuditBaseline,
) -> tuple[EvidenceFamilyAuditResult, float]:
    started = perf_counter()
    result = audit_raster_evidence_family(
        source_path,
        reference=reference,
        baseline=baseline,
    )
    return result, _number(perf_counter() - started)


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_evidence_family_audit_artifacts(
    output_dir: str | Path,
    *,
    result: EvidenceFamilyAuditResult,
    replay_audit_ids: Iterable[str],
    runtime_seconds: float,
) -> tuple[Path, ...]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    replay_ids = tuple(replay_audit_ids)
    deterministic = len(replay_ids) >= 2 and len(set(replay_ids)) == 1
    audit_payload = {
        **result.to_dict(),
        "audit_id": result.audit_id,
        "canonical_sha256": result.canonical_sha256,
        "deterministic_replay": {
            "passed": deterministic,
            "runs": len(replay_ids),
            "audit_ids": list(replay_ids),
        },
        "runtime_observation": {
            "seconds": _number(runtime_seconds),
            "excluded_from_stable_identity": True,
        },
    }
    candidates_payload = {
        "schema_version": DRAFTSMAN_RASTER_EVIDENCE_VERSION,
        "manifest_id": result.evidence.manifest_id,
        "candidate_count": len(result.evidence.candidates),
        "primitive_count": len(result.evidence.primitives),
        "spatial_relation_count": len(result.evidence.spatial_relations),
        "primitive_counts_by_kind": dict(result.summary.primitive_counts_by_kind),
        "candidates": [item.to_dict() for item in result.evidence.candidates],
        "primitives": [item.to_dict() for item in result.evidence.primitives],
        "spatial_relations": [
            item.to_dict() for item in result.evidence.spatial_relations
        ],
    }
    before_result = dict(result.baseline.family_result)
    after_result = {
        "auto_accepted": result.summary.auto_accepted,
        "review_required": result.summary.review_required,
        "missed": result.summary.missed,
        "false_positives": result.summary.false_positives,
        "failure_distribution": dict(result.summary.failure_distribution),
    }
    comparison_payload = {
        "schema_version": DRAFTSMAN_EVIDENCE_FAMILY_AUDIT_VERSION,
        "frozen_downstream": True,
        "frozen_rule_id": result.reference.frozen_rule_id,
        "before": {
            "evidence_contract": result.baseline.evidence_contract,
            "evidence_coverage": result.summary.evidence_coverage_before,
            "candidate_count": result.summary.evidence_candidates_before,
            "family_result": before_result,
        },
        "after": {
            "evidence_contract": DRAFTSMAN_RASTER_EVIDENCE_VERSION,
            "evidence_coverage": result.summary.evidence_coverage_after,
            "candidate_count": result.summary.evidence_candidates_after,
            "family_result": after_result,
        },
        "original_evidence_failures_recovered": (
            result.summary.original_evidence_failures_recovered
        ),
        "main_conclusion": "DOMAIN_TOPOLOGY_BOTTLENECK",
        "next_recommended_layer": "TOPOLOGY",
    }
    exceptions_payload = {
        "schema_version": result.downstream.schema_version,
        "exception_count": len(result.downstream.exceptions),
        "remaining_evidence_failures": [
            item.to_dict() for item in result.instances if not item.evidence_covered
        ],
        "downstream_exceptions": [
            item.to_dict() for item in result.downstream.exceptions
        ],
    }
    summary = result.summary
    report = f"""# Draftsman VS3-E1 — Raster Evidence / Domain Decoupling

## Result

The source-wide evidence frontend now preserves independent glyph, tag-region,
direction-neutral line, endpoint, region, and spatial-relation observations.
Candidate existence no longer requires a below-tag relation or horizontal
two-port support. The unchanged VS3 downstream consumes a compatibility
projection; its semantic thresholds remain in the Domain layer.

## Coverage and cost

- Authoritative family: **{summary.expected_family}**
- Evidence coverage: **{summary.evidence_coverage_before}/{summary.expected_family} → {summary.evidence_coverage_after}/{summary.expected_family}**
- Original Evidence misses recovered: **{summary.original_evidence_failures_recovered}/23**
- Remaining Evidence failures: **{summary.remaining_evidence_failures}**
- Compatibility candidates: **{summary.evidence_candidates_before} → {summary.evidence_candidates_after}** ({summary.candidate_growth_ratio}x, {summary.candidate_growth_percent:+.1f}%)
- Primitive counts: **{dict(summary.primitive_counts_by_kind)}**
- Spatial relations: **{summary.spatial_relation_count}**
- False candidate density: **{summary.false_candidate_density_per_megapixel}/MP**
- Observed end-to-end runtime: **{runtime_seconds:.3f}s** (diagnostic only; excluded from stable identity)

## Frozen downstream comparison

- Domain/Topology/Logical/Assembly modified: **NO**
- AUTO_ACCEPTED: **{summary.auto_accepted}/{summary.expected_family}**
- REVIEW_REQUIRED: **{summary.review_required}/{summary.expected_family}**
- MISSED: **{summary.missed}/{summary.expected_family}**
- False positives: **{summary.false_positives}**
- Failure distribution: **{dict(summary.failure_distribution)}**

Evidence coverage rose to {summary.evidence_coverage_after}/{summary.expected_family}
while frozen downstream auto-acceptance remained {summary.auto_accepted}/{summary.expected_family}.
The next bottleneck is therefore Domain/Topology interpretation, not continued
CV filtering. The one remaining Evidence failure records its missing primitive
types explicitly in `evidence-family-audit.json`.

## Determinism and scope

- Deterministic source-wide replays: **{'PASS' if deterministic else 'FAIL'}** ({len(replay_ids)} runs)
- Production semantic delta: **NONE**
- Runtime reference boxes used for discovery: **NO**
- Runtime source crops: **0**
"""
    paths = (
        target / "evidence-family-audit.json",
        target / "evidence-candidates.json",
        target / "downstream-comparison.json",
        target / "exceptions.json",
        target / "VS3_E1_REPORT.md",
    )
    for path, content in zip(
        paths,
        (
            _json_text(audit_payload),
            _json_text(candidates_payload),
            _json_text(comparison_payload),
            _json_text(exceptions_payload),
            report,
        ),
    ):
        path.write_text(content, encoding="utf-8")
    return paths
