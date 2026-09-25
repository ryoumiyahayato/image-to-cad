"""Independent, reference-free source-coverage measurement prototype."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
from PIL import Image

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_qa1 import QA1AuditResult
from .draftsman_vs3_u1 import DraftsmanVs3U1Result


QA2_S1_VERSION = "draftsman-qa2-s1-independent-source-coverage-v1"

# Frozen before the first reference evaluation.  These are generic 150-DPI
# drafting/scan structure parameters, not symbol-family features.
SOURCE_INK_THRESHOLD = 180
LONG_RUN_LENGTH_PX = 19
CLUSTER_DILATION_PX = 3
MIN_REGION_SIDE_PX = 8
MAX_REGION_SIDE_PX = 48
MIN_RESIDUAL_INK_PX = 15
MAX_RESIDUAL_INK_PX = 240
MIN_REGION_DENSITY = 0.035
MAX_REGION_DENSITY = 0.68
MIN_LINE_INCIDENCE_PX = 6
MIN_SUPPORTED_QUADRANTS = 3
EXPLAINED_MARGIN_PX = 3.0
NMS_DISTANCE_PX = 12.0


class SourceRegionFamily(str, Enum):
    COMPACT_LINE_INCIDENT_STRUCTURE = "COMPACT_LINE_INCIDENT_STRUCTURE"


@dataclass(frozen=True)
class ExplainedSourceItem:
    explanation_id: str
    candidate_id: str
    source_region: tuple[int, int, int, int]
    disposition: str
    evidence_refs: tuple[str, ...]
    logical_entity_refs: tuple[str, ...]
    cad_entity_refs: tuple[str, ...]
    review_item_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "explanation_id": self.explanation_id,
            "candidate_id": self.candidate_id,
            "source_region": list(self.source_region),
            "disposition": self.disposition,
            "evidence_refs": list(self.evidence_refs),
            "logical_entity_refs": list(self.logical_entity_refs),
            "cad_entity_refs": list(self.cad_entity_refs),
            "review_item_refs": list(self.review_item_refs),
        }


@dataclass(frozen=True)
class SourceCoverageRegion:
    region_id: str
    family: SourceRegionFamily
    source_region: tuple[int, int, int, int]
    center_px: tuple[float, float]
    residual_ink_pixels: int
    region_density: float
    line_incidence_pixels: int
    supported_quadrants: int
    independent_signal_score: float
    seeded_by_existing_candidate: bool
    overlaps_existing_candidate_explanation: bool
    explanation_ids: tuple[str, ...]
    nearby_evidence_refs: tuple[str, ...]
    nearby_cad_refs: tuple[str, ...]
    nearby_review_refs: tuple[str, ...]
    coverage_reason: str
    measurement_only: bool = True

    @property
    def explained(self) -> bool:
        return bool(self.explanation_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "family": self.family.value,
            "source_region": list(self.source_region),
            "center_px": list(self.center_px),
            "supporting_source_observations": {
                "residual_ink_pixels": self.residual_ink_pixels,
                "region_density": self.region_density,
                "line_incidence_pixels": self.line_incidence_pixels,
                "supported_quadrants": self.supported_quadrants,
            },
            "independent_signal_score": self.independent_signal_score,
            "seeded_by_existing_candidate": self.seeded_by_existing_candidate,
            "independent_of_existing_candidate": not self.seeded_by_existing_candidate,
            "overlaps_existing_candidate_explanation": (
                self.overlaps_existing_candidate_explanation
            ),
            "explained": self.explained,
            "explanation_ids": list(self.explanation_ids),
            "nearby_existing_evidence_refs": list(self.nearby_evidence_refs),
            "nearby_cad_refs": list(self.nearby_cad_refs),
            "nearby_review_refs": list(self.nearby_review_refs),
            "coverage_reason": self.coverage_reason,
            "semantic_identity": None,
            "output_mode": "MEASUREMENT_ONLY_SOURCE_FINDING",
            "measurement_only": self.measurement_only,
        }


@dataclass(frozen=True)
class QA2SourceCoverageResult:
    source_sha256: str
    qa1_audit_id: str
    explained_source_map: tuple[ExplainedSourceItem, ...]
    source_regions: tuple[SourceCoverageRegion, ...]
    residual_regions: tuple[SourceCoverageRegion, ...]
    summary: Mapping[str, object]
    schema_version: str = QA2_S1_VERSION

    @property
    def result_id(self) -> str:
        return semantic_id("draftsman-qa2-s1-result", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "runtime_contract": {
                "reference_available": False,
                "electrical_identity_used": False,
                "existing_glyph_candidate_used_as_detection_seed": False,
                "measurement_only": True,
                "qa1_dispositions_modified": False,
                "production_routing_changed": False,
            },
            "source_sha256": self.source_sha256,
            "qa1_audit_id": self.qa1_audit_id,
            "frozen_parameters": {
                "source_ink_threshold": SOURCE_INK_THRESHOLD,
                "long_run_length_px": LONG_RUN_LENGTH_PX,
                "cluster_dilation_px": CLUSTER_DILATION_PX,
                "region_side_px": [MIN_REGION_SIDE_PX, MAX_REGION_SIDE_PX],
                "residual_ink_px": [MIN_RESIDUAL_INK_PX, MAX_RESIDUAL_INK_PX],
                "region_density": [MIN_REGION_DENSITY, MAX_REGION_DENSITY],
                "minimum_line_incidence_px": MIN_LINE_INCIDENCE_PX,
                "minimum_supported_quadrants": MIN_SUPPORTED_QUADRANTS,
                "nms_distance_px": NMS_DISTANCE_PX,
                "frozen_before_first_reference_evaluation": True,
            },
            "summary": dict(self.summary),
            "explained_source_map": [item.to_dict() for item in self.explained_source_map],
            "source_regions": [item.to_dict() for item in self.source_regions],
            "residual_regions": [item.to_dict() for item in self.residual_regions],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _intersects(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int], margin: int = 0
) -> bool:
    return not (
        first[2] + margin < second[0]
        or second[2] + margin < first[0]
        or first[3] + margin < second[1]
        or second[3] + margin < first[1]
    )


def _explained_map(audit: QA1AuditResult) -> tuple[ExplainedSourceItem, ...]:
    items = []
    for entry in audit.ledger:
        payload = {
            "candidate_id": entry.candidate_id,
            "source_region": entry.source_region,
            "disposition": entry.final_disposition.value,
        }
        items.append(
            ExplainedSourceItem(
                semantic_id("draftsman-qa2-explanation", QA2_S1_VERSION, payload),
                entry.candidate_id,
                entry.source_region,
                entry.final_disposition.value,
                entry.source_evidence_ids,
                entry.related_logical_entity_ids,
                entry.related_cad_ir_entity_ids,
                entry.related_review_item_ids,
            )
        )
    return tuple(sorted(items, key=lambda item: item.explanation_id))


def _quadrant_support(mask: np.ndarray) -> int:
    height, width = mask.shape
    middle_y = height // 2
    middle_x = width // 2
    quadrants = (
        mask[:middle_y, :middle_x],
        mask[:middle_y, middle_x:],
        mask[middle_y:, :middle_x],
        mask[middle_y:, middle_x:],
    )
    return sum(bool(np.any(item)) for item in quadrants)


def measure_independent_source_coverage(
    source: str | Path,
    *,
    u1_result: DraftsmanVs3U1Result,
    qa1_audit: QA1AuditResult,
) -> QA2SourceCoverageResult:
    """Find generic line-incident compact source structure without references."""

    before = u1_result.canonical_bytes()
    with Image.open(source) as image:
        gray = np.asarray(image.convert("L"), dtype=np.uint8)
    ink = (gray <= SOURCE_INK_THRESHOLD).astype(np.uint8)
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (LONG_RUN_LENGTH_PX, 1)),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, LONG_RUN_LENGTH_PX)),
    )
    long_runs = cv2.bitwise_or(horizontal, vertical)
    residual = cv2.bitwise_and(ink, cv2.bitwise_not(long_runs))
    clustered = cv2.dilate(
        residual,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (CLUSTER_DILATION_PX, CLUSTER_DILATION_PX)
        ),
    )
    _, labels, stats, _ = cv2.connectedComponentsWithStats(clustered, connectivity=8)
    explained = _explained_map(qa1_audit)
    primitives = u1_result.t1_result.evidence.primitives
    proposed: list[SourceCoverageRegion] = []
    for label in range(1, stats.shape[0]):
        left, top, width, height, _ = (int(value) for value in stats[label])
        if not (
            MIN_REGION_SIDE_PX <= width <= MAX_REGION_SIDE_PX
            and MIN_REGION_SIDE_PX <= height <= MAX_REGION_SIDE_PX
        ):
            continue
        right = left + width - 1
        bottom = top + height - 1
        region = (left, top, right, bottom)
        local_residual = residual[top : bottom + 1, left : right + 1]
        residual_ink = int(np.count_nonzero(local_residual))
        density = residual_ink / float(width * height)
        if not (
            MIN_RESIDUAL_INK_PX <= residual_ink <= MAX_RESIDUAL_INK_PX
            and MIN_REGION_DENSITY <= density <= MAX_REGION_DENSITY
        ):
            continue
        expanded = (
            max(0, left - 3),
            max(0, top - 3),
            min(gray.shape[1] - 1, right + 3),
            min(gray.shape[0] - 1, bottom + 3),
        )
        line_incidence = int(
            np.count_nonzero(
                long_runs[
                    expanded[1] : expanded[3] + 1,
                    expanded[0] : expanded[2] + 1,
                ]
            )
        )
        quadrants = _quadrant_support(local_residual)
        if line_incidence < MIN_LINE_INCIDENCE_PX or quadrants < MIN_SUPPORTED_QUADRANTS:
            continue
        center = ((left + right) / 2.0, (top + bottom) / 2.0)
        explanation_ids = tuple(
            sorted(
                item.explanation_id
                for item in explained
                if item.source_region[0] - EXPLAINED_MARGIN_PX <= center[0]
                <= item.source_region[2] + EXPLAINED_MARGIN_PX
                and item.source_region[1] - EXPLAINED_MARGIN_PX <= center[1]
                <= item.source_region[3] + EXPLAINED_MARGIN_PX
            )
        )
        nearby_evidence = tuple(
            sorted(
                item.stable_evidence_id
                for item in primitives
                if _intersects(region, item.source_bbox_px, margin=8)
            )
        )
        nearby_explanations = [
            item for item in explained if _intersects(region, item.source_region, margin=24)
        ]
        nearby_cad = tuple(
            sorted({ref for item in nearby_explanations for ref in item.cad_entity_refs})
        )
        nearby_review = tuple(
            sorted({ref for item in nearby_explanations for ref in item.review_item_refs})
        )
        score = round(
            min(1.0, residual_ink / 80.0) * 0.45
            + min(1.0, line_incidence / 40.0) * 0.35
            + quadrants / 4.0 * 0.20,
            6,
        )
        payload = {
            "source_sha256": u1_result.t1_result.evidence.source_sha256,
            "family": SourceRegionFamily.COMPACT_LINE_INCIDENT_STRUCTURE.value,
            "source_region": region,
            "residual_ink_pixels": residual_ink,
            "line_incidence_pixels": line_incidence,
            "supported_quadrants": quadrants,
        }
        proposed.append(
            SourceCoverageRegion(
                semantic_id("draftsman-qa2-source-region", QA2_S1_VERSION, payload),
                SourceRegionFamily.COMPACT_LINE_INCIDENT_STRUCTURE,
                region,
                center,
                residual_ink,
                round(density, 6),
                line_incidence,
                quadrants,
                score,
                False,
                bool(explanation_ids),
                explanation_ids,
                nearby_evidence,
                nearby_cad,
                nearby_review,
                (
                    "CENTER_COVERED_BY_EXPLICIT_QA1_CANDIDATE_DISPOSITION"
                    if explanation_ids
                    else "INDEPENDENT_RASTER_STRUCTURE_HAS_NO_CENTERED_QA1_EXPLANATION"
                ),
            )
        )
    selected: list[SourceCoverageRegion] = []
    for item in sorted(
        proposed,
        key=lambda value: (
            -value.independent_signal_score,
            value.source_region,
            value.region_id,
        ),
    ):
        if all(
            (item.center_px[0] - other.center_px[0]) ** 2
            + (item.center_px[1] - other.center_px[1]) ** 2
            > NMS_DISTANCE_PX**2
            for other in selected
        ):
            selected.append(item)
    source_regions = tuple(sorted(selected, key=lambda item: item.region_id))
    residual_regions = tuple(item for item in source_regions if not item.explained)
    if u1_result.canonical_bytes() != before:
        raise RuntimeError("QA2 source measurement mutated U1 reconstruction")
    summary: dict[str, object] = {
        "source_coverage_regions": len(source_regions),
        "regions_seeded_by_existing_evidence": sum(
            item.seeded_by_existing_candidate for item in source_regions
        ),
        "regions_independent_of_existing_evidence": sum(
            not item.seeded_by_existing_candidate for item in source_regions
        ),
        "residual_regions": len(residual_regions),
        "measurement_only_omission_signals": len(residual_regions),
        "actionable_review_findings": 0,
        "qa1_dispositions_modified": False,
    }
    return QA2SourceCoverageResult(
        u1_result.t1_result.evidence.source_sha256,
        qa1_audit.audit_id,
        explained,
        source_regions,
        residual_regions,
        summary,
    )


def write_draftsman_qa2_s1_artifacts(
    output_dir: str | Path,
    *,
    result: QA2SourceCoverageResult,
    replay_result_ids: tuple[str, ...],
    reference_evaluation: Mapping[str, object],
    baseline_comparison: Mapping[str, object],
) -> tuple[Path, ...]:
    """Write runtime and post-hoc evidence as explicitly separated artifacts."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, object] = {
        "qa2-source-regions.json": {
            "schema_version": "draftsman-qa2-source-regions-v1",
            "result_id": result.result_id,
            "runtime_contract": result.to_dict()["runtime_contract"],
            "frozen_parameters": result.to_dict()["frozen_parameters"],
            "summary": dict(result.summary),
            "regions": [item.to_dict() for item in result.source_regions],
            "deterministic_replay": {
                "passed": len(replay_result_ids) >= 2
                and len(set(replay_result_ids)) == 1,
                "runs": len(replay_result_ids),
                "result_ids": list(replay_result_ids),
            },
        },
        "qa2-explained-source-map.json": {
            "schema_version": "draftsman-qa2-explained-source-map-v1",
            "reference_available": False,
            "geometry_contract": (
                "Candidate body support regions only; no page-sized or union candidate masks."
            ),
            "items": [item.to_dict() for item in result.explained_source_map],
        },
        "qa2-residual-regions.json": {
            "schema_version": "draftsman-qa2-residual-regions-v1",
            "reference_available": False,
            "output_mode": "MEASUREMENT_ONLY_SOURCE_FINDING",
            "regions": [item.to_dict() for item in result.residual_regions],
        },
        "qa2-reference-evaluation.json": dict(reference_evaluation),
        "qa2-baseline-comparison.json": dict(baseline_comparison),
    }
    written = []
    for name, payload in payloads.items():
        path = target / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    qa2_metrics = baseline_comparison.get("qa2")
    if not isinstance(qa2_metrics, dict):
        raise TypeError("QA2 baseline comparison must contain QA2 metrics")
    report = target / "QA2_S1_REPORT.md"
    report.write_text(
        "\n".join(
            (
                "# Draftsman QA2-S1 — Independent source-coverage benchmark",
                "",
                "The source detector was frozen and run without Golden reference input.",
                "It uses generic compact residual structure and direct raster line incidence;",
                "it has no electrical identity, glyph template, tag-layout, or fixture rule.",
                "",
                f"- Source-coverage regions: **{result.summary['source_coverage_regions']}**",
                f"- Existing-candidate seeded: **{result.summary['regions_seeded_by_existing_evidence']}**",
                f"- Existing-candidate independent: **{result.summary['regions_independent_of_existing_evidence']}**",
                f"- Residual measurement signals: **{result.summary['residual_regions']}**",
                "- Actionable Review Queue findings: **0**",
                "",
                "## Frozen post-hoc result",
                "",
                f"- Known true omission hits: **{reference_evaluation['known_omission_hits']}/1**",
                f"- Other insufficient-instance hits: **{reference_evaluation['other_insufficient_hits']}/1**",
                f"- Estimated false signals: **{qa2_metrics['false_alerts']}**",
                f"- Signal precision: **{qa2_metrics['precision_percent']}%**",
                "",
                "The independent signal supports the source-coverage approach because it",
                "finds the known no-candidate omission. It is nevertheless noisier than QA0",
                "and remains unsuitable for an actionable queue. No parameters were adjusted",
                "after reference evaluation; a subsequent slice must test a new generic signal",
                "family rather than tune against this page's answer key.",
                "",
            )
        ),
        encoding="utf-8",
    )
    written.append(report)
    return tuple(written)
