"""Reference-free risk triage for frozen QA2-S1 residual regions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import json
from math import log1p, sqrt
from pathlib import Path
from statistics import median
from typing import Mapping, Sequence

import cv2
import numpy as np
from PIL import Image

from .draftsman_contract import canonical_json_bytes, semantic_id
from .draftsman_qa1 import CandidateDisposition, QA1AuditResult
from .draftsman_qa2_s1 import (
    QA2SourceCoverageResult,
    SOURCE_INK_THRESHOLD,
    SourceCoverageRegion,
)


QA2_S2_VERSION = "draftsman-qa2-s2-source-risk-triage-v1"
EXPECTED_FROZEN_S1_RESIDUAL_COUNT = 220
CLUSTER_MARGIN_PX = 4
CLUSTER_MAX_CENTER_DISTANCE_PX = 56.0


class ControlPopulation(str, Enum):
    POSITIVE_STRUCTURE = "POSITIVE_STRUCTURE"
    NEGATIVE_LOW_VALUE = "NEGATIVE_LOW_VALUE"
    RESIDUAL = "RESIDUAL"


class RiskTier(str, Enum):
    A = "TIER_A_ACTIONABLE_CANDIDATE"
    B = "TIER_B_MEASUREMENT_ONLY"
    C = "TIER_C_LIKELY_LOW_VALUE"


class ResidualFamily(str, Enum):
    TEXT_LIKE_STRUCTURE = "TEXT_LIKE_STRUCTURE"
    LONG_LINE_RESIDUAL = "LONG_LINE_RESIDUAL"
    TABLE_OR_GRID_JUNCTION = "TABLE_OR_GRID_JUNCTION"
    CLOSED_COMPACT_STRUCTURE = "CLOSED_COMPACT_STRUCTURE"
    COMPLEX_ANNOTATION = "COMPLEX_ANNOTATION"
    ORDINARY_RESIDUAL = "ORDINARY_RESIDUAL"


@dataclass(frozen=True)
class StructuralFeatures:
    region_id: str
    population: ControlPopulation
    width_px: int
    height_px: int
    aspect_symmetry: float
    residual_ink_pixels: int
    density: float
    line_incidence_pixels: int
    connected_components: int
    largest_component_fraction: float
    contour_count: int
    closed_contours: int
    edge_density: float
    endpoint_count: int
    junction_count: int
    orientation_diversity: int
    supported_quadrants: int
    generic_family: ResidualFamily

    def vector(self) -> tuple[float, ...]:
        return (
            log1p(self.residual_ink_pixels),
            self.density,
            log1p(self.line_incidence_pixels),
            self.aspect_symmetry,
            float(self.connected_components),
            self.largest_component_fraction,
            float(self.closed_contours),
            float(self.endpoint_count),
            float(self.junction_count),
            float(self.orientation_diversity),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "population": self.population.value,
            "features": {
                "width_px": self.width_px,
                "height_px": self.height_px,
                "aspect_symmetry": self.aspect_symmetry,
                "residual_ink_pixels": self.residual_ink_pixels,
                "density": self.density,
                "line_incidence_pixels": self.line_incidence_pixels,
                "connected_components": self.connected_components,
                "largest_component_fraction": self.largest_component_fraction,
                "contour_count": self.contour_count,
                "closed_contours": self.closed_contours,
                "edge_density": self.edge_density,
                "endpoint_count": self.endpoint_count,
                "junction_count": self.junction_count,
                "orientation_diversity": self.orientation_diversity,
                "supported_quadrants": self.supported_quadrants,
            },
            "generic_family": self.generic_family.value,
        }


@dataclass(frozen=True)
class FrozenTriageConfig:
    positive_centroid: tuple[float, ...]
    negative_centroid: tuple[float, ...]
    feature_scales: tuple[float, ...]
    tier_a_minimum_supports: int = 4
    tier_a_minimum_control_margin: float = 0.0
    tier_b_minimum_supports: int = 2
    tier_b_minimum_control_margin: float = -0.75
    cluster_margin_px: int = CLUSTER_MARGIN_PX
    cluster_max_center_distance_px: float = CLUSTER_MAX_CENTER_DISTANCE_PX
    schema_version: str = "draftsman-qa2-s2-frozen-config-v1"

    @property
    def config_id(self) -> str:
        return semantic_id("draftsman-qa2-s2-frozen-config", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "selected_features": [
                "residual_ink_pixels",
                "density",
                "line_incidence_pixels",
                "aspect_symmetry",
                "connected_components",
                "largest_component_fraction",
                "closed_contours",
                "endpoint_count",
                "junction_count",
                "orientation_diversity",
            ],
            "positive_centroid": list(self.positive_centroid),
            "negative_centroid": list(self.negative_centroid),
            "feature_scales": list(self.feature_scales),
            "clustering_rules": {
                "bbox_margin_px": self.cluster_margin_px,
                "maximum_center_distance_px": self.cluster_max_center_distance_px,
                "transitive_union": True,
            },
            "tiering_logic": {
                "tier_a": {
                    "minimum_independent_structural_supports": self.tier_a_minimum_supports,
                    "minimum_positive_vs_negative_control_margin": self.tier_a_minimum_control_margin,
                },
                "tier_b": {
                    "minimum_independent_structural_supports": self.tier_b_minimum_supports,
                    "minimum_positive_vs_negative_control_margin": self.tier_b_minimum_control_margin,
                },
                "tier_c": "otherwise",
            },
            "generic_triage_rule_count": 4,
            "drawing_specific_rule_count": 0,
            "fixture_specific_rule_count": 0,
            "frozen_before_golden_evaluation": True,
            "timestamp_used": False,
        }


@dataclass(frozen=True)
class ResidualCluster:
    cluster_id: str
    region_ids: tuple[str, ...]
    source_region: tuple[int, int, int, int]
    representative_region_id: str
    generic_family: ResidualFamily
    structural_supports: tuple[str, ...]
    positive_distance: float
    negative_distance: float
    control_margin: float
    tier: RiskTier
    independent_of_glyph_evidence: bool = True
    measurement_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "region_ids": list(self.region_ids),
            "source_region": list(self.source_region),
            "representative_region_id": self.representative_region_id,
            "generic_family": self.generic_family.value,
            "structural_supports": list(self.structural_supports),
            "positive_control_distance": self.positive_distance,
            "negative_control_distance": self.negative_distance,
            "control_margin": self.control_margin,
            "tier": self.tier.value,
            "seeded_by_existing_glyph_evidence": False,
            "independent_of_glyph_evidence": self.independent_of_glyph_evidence,
            "output_mode": "MEASUREMENT_ONLY_SOURCE_FINDING",
            "measurement_only": self.measurement_only,
        }


@dataclass(frozen=True)
class QA2S2Result:
    s1_result_id: str
    qa1_audit_id: str
    features: tuple[StructuralFeatures, ...]
    config: FrozenTriageConfig
    clusters: tuple[ResidualCluster, ...]
    summary: Mapping[str, object]
    schema_version: str = QA2_S2_VERSION

    @property
    def result_id(self) -> str:
        return semantic_id("draftsman-qa2-s2-result", self.schema_version, self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "runtime_contract": {
                "reference_available": False,
                "electrical_identity_used": False,
                "measurement_only": True,
                "s1_generation_modified": False,
                "qa1_dispositions_modified": False,
                "production_routing_changed": False,
            },
            "s1_result_id": self.s1_result_id,
            "qa1_audit_id": self.qa1_audit_id,
            "frozen_config_id": self.config.config_id,
            "summary": dict(self.summary),
            "features": [item.to_dict() for item in self.features],
            "clusters": [item.to_dict() for item in self.clusters],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _population_by_region(
    s1: QA2SourceCoverageResult, qa1: QA1AuditResult
) -> dict[str, ControlPopulation]:
    disposition = {item.candidate_id: item.final_disposition for item in qa1.ledger}
    explanation_candidate = {
        item.explanation_id: item.candidate_id for item in s1.explained_source_map
    }
    populations = {}
    positives = {
        CandidateDisposition.REPRESENTED_VERIFIED,
        CandidateDisposition.REPRESENTED_UNVERIFIED,
    }
    negatives = {
        CandidateDisposition.LIKELY_NOISE,
        CandidateDisposition.EXPLICIT_REJECTION,
    }
    for region in s1.source_regions:
        states = {
            disposition[explanation_candidate[explanation_id]]
            for explanation_id in region.explanation_ids
        }
        if states & positives:
            populations[region.region_id] = ControlPopulation.POSITIVE_STRUCTURE
        elif states and states <= negatives:
            populations[region.region_id] = ControlPopulation.NEGATIVE_LOW_VALUE
        else:
            populations[region.region_id] = ControlPopulation.RESIDUAL
    return populations


def _skeleton(binary: np.ndarray) -> np.ndarray:
    image = binary.copy()
    result = np.zeros_like(image)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(image):
        opened = cv2.morphologyEx(image, cv2.MORPH_OPEN, element)
        result = cv2.bitwise_or(result, cv2.subtract(image, opened))
        image = cv2.erode(image, element)
    return result


def _classify_family(
    *,
    aspect: float,
    components: int,
    closed: int,
    line_incidence: int,
    ink: int,
    junctions: int,
    orientations: int,
) -> ResidualFamily:
    if (aspect < 0.48 or components >= 6) and closed == 0:
        return ResidualFamily.TEXT_LIKE_STRUCTURE
    if line_incidence > max(80, ink * 2) and orientations <= 1:
        return ResidualFamily.LONG_LINE_RESIDUAL
    if junctions >= 6 and line_incidence >= 80:
        return ResidualFamily.TABLE_OR_GRID_JUNCTION
    if closed > 0 and components <= 5:
        return ResidualFamily.CLOSED_COMPACT_STRUCTURE
    if components >= 4 or junctions >= 4 or orientations >= 3:
        return ResidualFamily.COMPLEX_ANNOTATION
    return ResidualFamily.ORDINARY_RESIDUAL


def _extract_features(
    gray: np.ndarray,
    region: SourceCoverageRegion,
    population: ControlPopulation,
) -> StructuralFeatures:
    left, top, right, bottom = region.source_region
    patch = (gray[top : bottom + 1, left : right + 1] <= SOURCE_INK_THRESHOLD).astype(
        np.uint8
    )
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        patch, connectivity=8
    )
    areas = [int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, component_count)]
    retained_areas = [area for area in areas if area >= 2]
    components = len(retained_areas)
    largest_fraction = 0.0 if not areas else max(areas) / max(1, sum(areas))
    contours, hierarchy = cv2.findContours(
        patch, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    closed = 0
    if hierarchy is not None:
        closed = sum(int(item[3]) >= 0 for item in hierarchy[0])
    edges = cv2.Canny(patch * 255, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / float(patch.size)
    skeleton = _skeleton(patch)
    neighbors = cv2.filter2D(skeleton, cv2.CV_16S, np.ones((3, 3), np.int16))
    occupied = skeleton > 0
    neighbor_count = neighbors - skeleton.astype(np.int16)
    endpoints = int(np.count_nonzero(occupied & (neighbor_count == 1)))
    junctions = int(np.count_nonzero(occupied & (neighbor_count >= 3)))
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=6, minLineLength=5, maxLineGap=2
    )
    orientation_bins: set[int] = set()
    if lines is not None:
        for line in lines[:, 0, :]:
            dx = int(line[2]) - int(line[0])
            dy = int(line[3]) - int(line[1])
            angle = (np.degrees(np.arctan2(dy, dx)) + 180.0) % 180.0
            orientation_bins.add(int((angle + 22.5) // 45.0) % 4)
    width = right - left + 1
    height = bottom - top + 1
    aspect = min(width, height) / max(width, height)
    family = _classify_family(
        aspect=aspect,
        components=components,
        closed=closed,
        line_incidence=region.line_incidence_pixels,
        ink=region.residual_ink_pixels,
        junctions=junctions,
        orientations=len(orientation_bins),
    )
    return StructuralFeatures(
        region.region_id,
        population,
        width,
        height,
        round(aspect, 6),
        region.residual_ink_pixels,
        region.region_density,
        region.line_incidence_pixels,
        components,
        round(largest_fraction, 6),
        len(contours),
        closed,
        round(edge_density, 6),
        endpoints,
        junctions,
        len(orientation_bins),
        region.supported_quadrants,
        family,
    )


def _centroid(vectors: Sequence[tuple[float, ...]]) -> tuple[float, ...]:
    return tuple(round(sum(values) / len(values), 6) for values in zip(*vectors, strict=True))


def calibrate_reference_free(
    features: Sequence[StructuralFeatures],
) -> FrozenTriageConfig:
    """Calibrate only from naturally occurring QA1 positive/negative controls."""

    positives = [
        item.vector()
        for item in features
        if item.population is ControlPopulation.POSITIVE_STRUCTURE
    ]
    negatives = [
        item.vector()
        for item in features
        if item.population is ControlPopulation.NEGATIVE_LOW_VALUE
    ]
    if not positives or not negatives:
        raise ValueError("QA2-S2 calibration requires positive and negative controls")
    combined = [*positives, *negatives]
    scales = []
    for values in zip(*combined, strict=True):
        center = median(values)
        deviations = [abs(value - center) for value in values]
        scales.append(round(max(median(deviations), 0.1), 6))
    return FrozenTriageConfig(_centroid(positives), _centroid(negatives), tuple(scales))


def _distance(vector: tuple[float, ...], centroid: tuple[float, ...], scales: tuple[float, ...]) -> float:
    return round(
        sqrt(
            sum(
                ((value - center) / scale) ** 2
                for value, center, scale in zip(vector, centroid, scales, strict=True)
            )
        ),
        6,
    )


def _supports(item: StructuralFeatures) -> tuple[str, ...]:
    supports = []
    if item.connected_components <= 5 and item.largest_component_fraction >= 0.45:
        supports.append("COHERENT_COMPONENT")
    if item.closed_contours >= 1:
        supports.append("CLOSED_CONTOUR")
    if item.endpoint_count >= 2 and item.junction_count >= 1:
        supports.append("ENDPOINT_JUNCTION_STRUCTURE")
    if item.orientation_diversity >= 2:
        supports.append("ORIENTATION_DIVERSITY")
    if item.supported_quadrants == 4:
        supports.append("MULTI_QUADRANT_STRUCTURE")
    return tuple(supports)


def _overlap_with_margin(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int], margin: int
) -> bool:
    return not (
        first[2] + margin < second[0]
        or second[2] + margin < first[0]
        or first[3] + margin < second[1]
        or second[3] + margin < first[1]
    )


def _clusters(
    residuals: Sequence[SourceCoverageRegion],
) -> tuple[tuple[SourceCoverageRegion, ...], ...]:
    parent = list(range(len(residuals)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[max(first_root, second_root)] = min(first_root, second_root)

    for first_index, first in enumerate(residuals):
        for second_index in range(first_index + 1, len(residuals)):
            second = residuals[second_index]
            distance = sqrt(
                (first.center_px[0] - second.center_px[0]) ** 2
                + (first.center_px[1] - second.center_px[1]) ** 2
            )
            if distance <= CLUSTER_MAX_CENTER_DISTANCE_PX and _overlap_with_margin(
                first.source_region, second.source_region, CLUSTER_MARGIN_PX
            ):
                union(first_index, second_index)
    grouped: dict[int, list[SourceCoverageRegion]] = {}
    for index, item in enumerate(residuals):
        grouped.setdefault(find(index), []).append(item)
    return tuple(
        tuple(sorted(items, key=lambda item: item.region_id))
        for _, items in sorted(grouped.items())
    )


def triage_source_coverage_risk(
    source: str | Path,
    *,
    s1_result: QA2SourceCoverageResult,
    qa1_audit: QA1AuditResult,
) -> QA2S2Result:
    """Feature, cluster, and tier the frozen S1 residual set without references."""

    if len(s1_result.residual_regions) != EXPECTED_FROZEN_S1_RESIDUAL_COUNT:
        raise ValueError("QA2-S1 residual generation changed; S2 calibration refused")
    qa1_before = qa1_audit.canonical_bytes()
    with Image.open(source) as image:
        gray = np.asarray(image.convert("L"), dtype=np.uint8)
    populations = _population_by_region(s1_result, qa1_audit)
    features = tuple(
        sorted(
            (
                _extract_features(gray, region, populations[region.region_id])
                for region in s1_result.source_regions
            ),
            key=lambda item: item.region_id,
        )
    )
    feature_by_id = {item.region_id: item for item in features}
    config = calibrate_reference_free(features)
    clusters = []
    for members in _clusters(s1_result.residual_regions):
        member_features = [feature_by_id[item.region_id] for item in members]
        ranked = []
        for item in member_features:
            positive_distance = _distance(
                item.vector(), config.positive_centroid, config.feature_scales
            )
            negative_distance = _distance(
                item.vector(), config.negative_centroid, config.feature_scales
            )
            supports = _supports(item)
            ranked.append(
                (
                    len(supports),
                    negative_distance - positive_distance,
                    -positive_distance,
                    item.region_id,
                    item,
                    supports,
                    positive_distance,
                    negative_distance,
                )
            )
        representative_data = max(ranked, key=lambda value: value[:4])
        support_count, margin, _, _, representative, supports, pos_distance, neg_distance = (
            representative_data
        )
        if (
            support_count >= config.tier_a_minimum_supports
            and margin >= config.tier_a_minimum_control_margin
        ):
            tier = RiskTier.A
        elif (
            support_count >= config.tier_b_minimum_supports
            and margin >= config.tier_b_minimum_control_margin
        ):
            tier = RiskTier.B
        else:
            tier = RiskTier.C
        region_ids = tuple(item.region_id for item in members)
        bbox = (
            min(item.source_region[0] for item in members),
            min(item.source_region[1] for item in members),
            max(item.source_region[2] for item in members),
            max(item.source_region[3] for item in members),
        )
        payload = {
            "config_id": config.config_id,
            "region_ids": region_ids,
            "source_region": bbox,
            "representative_region_id": representative.region_id,
        }
        clusters.append(
            ResidualCluster(
                semantic_id("draftsman-qa2-s2-cluster", QA2_S2_VERSION, payload),
                region_ids,
                bbox,
                representative.region_id,
                representative.generic_family,
                supports,
                pos_distance,
                neg_distance,
                round(margin, 6),
                tier,
            )
        )
    clusters.sort(key=lambda item: item.cluster_id)
    tiers = Counter(item.tier.value for item in clusters)
    controls = Counter(item.population.value for item in features)
    families = Counter(item.generic_family.value for item in features if item.population is ControlPopulation.RESIDUAL)
    if qa1_audit.canonical_bytes() != qa1_before:
        raise RuntimeError("QA2-S2 modified QA1 dispositions")
    summary: dict[str, object] = {
        "raw_s1_residuals": len(s1_result.residual_regions),
        "residual_clusters": len(clusters),
        "control_populations": dict(sorted(controls.items())),
        "tiers": {item.value: tiers[item.value] for item in RiskTier},
        "residual_family_counts": dict(sorted(families.items())),
        "generic_triage_rules": 4,
        "drawing_specific_rules": 0,
        "fixture_specific_rules": 0,
        "rule_explosion_risk": "MEDIUM",
        "actionable_review_queue_entries": 0,
    }
    return QA2S2Result(
        s1_result.result_id,
        qa1_audit.audit_id,
        features,
        config,
        tuple(clusters),
        summary,
    )


def write_frozen_config(path: str | Path, config: FrozenTriageConfig) -> Path:
    """Persist the deterministic blind config before any reference is loaded."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {**config.to_dict(), "config_id": config.config_id},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def write_draftsman_qa2_s2_artifacts(
    output_dir: str | Path,
    *,
    result: QA2S2Result,
    replay_result_ids: tuple[str, ...],
    reference_evaluation: Mapping[str, object],
    baseline_comparison: Mapping[str, object],
) -> tuple[Path, ...]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    feature_populations: dict[str, list[dict[str, object]]] = {
        item.value: [] for item in ControlPopulation
    }
    for item in result.features:
        feature_populations[item.population.value].append(item.to_dict())
    control_counts = result.summary.get("control_populations")
    tier_counts = result.summary.get("tiers")
    if not isinstance(control_counts, dict) or not isinstance(tier_counts, dict):
        raise TypeError("S2 summary must contain control and tier dictionaries")
    payloads: dict[str, object] = {
        "qa2-s2-feature-audit.json": {
            "schema_version": "draftsman-qa2-s2-feature-audit-v1",
            "selected_features": result.config.to_dict()["selected_features"],
            "feature_records": [item.to_dict() for item in result.features],
            "generic_false_signal_taxonomy": [item.value for item in ResidualFamily],
        },
        "qa2-s2-control-populations.json": {
            "schema_version": "draftsman-qa2-s2-control-populations-v1",
            "reference_available": False,
            "derivation": {
                "positive": "QA1 represented verified or unverified editable dispositions",
                "negative": "QA1 likely-noise or explicit generic low-support rejection",
                "residual": "Frozen QA2-S1 region without centered QA1 explanation",
            },
            "counts": dict(control_counts),
            "populations": feature_populations,
        },
        "qa2-s2-residual-clusters.json": {
            "schema_version": "draftsman-qa2-s2-residual-clusters-v1",
            "raw_s1_residual_count": result.summary["raw_s1_residuals"],
            "cluster_count": len(result.clusters),
            "clustering_rules": result.config.to_dict()["clustering_rules"],
            "clusters": [item.to_dict() for item in result.clusters],
        },
        "qa2-s2-tiered-signals.json": {
            "schema_version": "draftsman-qa2-s2-tiered-signals-v1",
            "runtime_contract": result.to_dict()["runtime_contract"],
            "summary": dict(result.summary),
            "signals": [item.to_dict() for item in result.clusters],
            "deterministic_replay": {
                "passed": len(replay_result_ids) >= 2
                and len(set(replay_result_ids)) == 1,
                "runs": len(replay_result_ids),
                "result_ids": list(replay_result_ids),
            },
        },
        "qa2-s2-reference-evaluation.json": dict(reference_evaluation),
        "qa2-s2-baseline-comparison.json": dict(baseline_comparison),
    }
    written = [target / "qa2-s2-frozen-config.json"]
    for name, payload in payloads.items():
        path = target / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    tier_a = reference_evaluation.get("tier_a")
    if not isinstance(tier_a, dict):
        raise TypeError("S2 reference evaluation requires Tier A metrics")
    report = target / "QA2_S2_REPORT.md"
    report.write_text(
        "\n".join(
            (
                "# Draftsman QA2-S2 — Reference-free source-risk triage",
                "",
                "The S1 extractor and its 220 residuals are unchanged. Calibration uses",
                "only QA1-derived positive/negative controls. The timestamp-free config was",
                "persisted before the post-hoc Golden reference was loaded.",
                "",
                f"- Raw residuals: **{result.summary['raw_s1_residuals']}**",
                f"- Clustered residual objects: **{result.summary['residual_clusters']}**",
                f"- Tier A: **{tier_counts[RiskTier.A.value]}**",
                f"- Tier B: **{tier_counts[RiskTier.B.value]}**",
                f"- Tier C: **{tier_counts[RiskTier.C.value]}**",
                "- Product Review Queue entries: **0**",
                "",
                "## One frozen post-hoc evaluation",
                "",
                f"- Known omission tier: **{reference_evaluation['known_omission_tier']}**",
                f"- Tier A true hits: **{tier_a['true_hits']}**",
                f"- Tier A false alerts: **{tier_a['false_alerts']}**",
                f"- Tier A precision: **{tier_a['precision_percent']}%**",
                "",
                "Tiering reduces 220 raw residuals to a smaller candidate set, but the",
                "measured burden remains too high for product review. No thresholds or rules",
                "were changed after evaluation. All signals remain measurement-only.",
                "",
            )
        ),
        encoding="utf-8",
    )
    written.append(report)
    return tuple(written)
