from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterable, Mapping, Sequence

import cv2
import numpy as np

from .line_detect import LineSegment
from .raster_trace import TracePath


TERMINAL_REASONS = frozenset(
    {
        "NO_RAW_EVIDENCE",
        "DETECTION_FRAGMENTED",
        "CANDIDATE_INELIGIBLE",
        "OWNERSHIP_SUPPRESSED",
        "REROUTED_TO_GRAPHIC_FALLBACK",
        "FILTERED",
        "FALLBACK_EXECUTED",
        "ARTIFACT_SUPPRESSION_REJECTED",
        "DAMAGE_CLUSTER_PROPAGATION_REJECTED",
        "NEAR_DAMAGE_FRAGMENT_REJECTED",
        "FALLBACK_RESCUED",
        "GEOMETRY_DROPPED",
        "PROMOTION_REJECTED",
        "ASSEMBLY_DROPPED",
        "PRESERVED",
        "UNKNOWN_SILENT_DROP",
    }
)


ARTIFACT_DECISIONS = frozenset(
    {
        "ACCEPTED",
        "REJECTED_DIRECT_DAMAGE_ROOT",
        "REJECTED_DAMAGE_CLUSTER_PROPAGATION",
        "REJECTED_NEAR_DAMAGE_FRAGMENT",
        "OTHER_REJECTION",
    }
)


def _line_id(line: LineSegment, index: int, prefix: str) -> str:
    if line.source_ids:
        return "+".join(str(value) for value in line.source_ids)
    return f"{prefix}-{index:06d}"


def _indices(mask: np.ndarray) -> np.ndarray:
    return np.flatnonzero(mask.reshape(-1) > 0).astype(np.int64, copy=False)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    points = cv2.findNonZero(np.ascontiguousarray(mask, dtype=np.uint8))
    return None if points is None else tuple(int(value) for value in cv2.boundingRect(points))


@dataclass
class _SupportState:
    source_support_id: str
    indices: np.ndarray
    evidence_types: set[str]
    observation_metadata: dict[str, object]
    detection_evidence_ids: dict[str, list[str]] = field(default_factory=dict)
    candidate_ids: list[str] = field(default_factory=list)
    candidate_types: set[str] = field(default_factory=set)
    candidate_branches: set[str] = field(default_factory=set)
    eligibility_decisions: list[dict[str, object]] = field(default_factory=list)
    ownership_claims: dict[str, int] = field(default_factory=dict)
    final_owner: str | None = None
    ownership_history: list[dict[str, object]] = field(default_factory=list)
    filter_decisions: list[dict[str, object]] = field(default_factory=list)
    fallback_eligibility: str | None = None
    fallback_execution: str | None = None
    fallback_root_ids: list[str] = field(default_factory=list)
    artifact_suppression_decisions: list[dict[str, object]] = field(default_factory=list)
    fallback_result: str | None = None
    geometry_ids: list[str] = field(default_factory=list)
    promoted_ids: list[str] = field(default_factory=list)
    final_structure_ids: list[str] = field(default_factory=list)
    terminal_reason: str | None = None
    coverage_gaps: list[str] = field(default_factory=list)
    raw_fraction: float = 0.0
    candidate_fraction: float = 0.0


class SourceSupportLifecycle:
    """Read-only provenance ledger for source-backed production evidence.

    The ledger observes masks and immutable production objects. It never returns a
    decision to the pipeline and therefore has no semantic or geometry authority.
    Coordinates are retained only in ``observation_metadata``; callers provide the
    stable semantic identity used as ``source_support_id``.
    """

    def __init__(
        self,
        shape: tuple[int, int],
        *,
        auto_register_fallback: bool = True,
    ) -> None:
        self.shape = (int(shape[0]), int(shape[1]))
        self.auto_register_fallback = bool(auto_register_fallback)
        self._supports: dict[str, _SupportState] = {}
        self._stage_lines: dict[str, tuple[LineSegment, ...]] = {}
        self._stage_line_labels: dict[str, np.ndarray] = {}
        self._fallback_support_labels = np.zeros(self.shape, dtype=np.int32)
        self._fallback_support_ids: dict[int, str] = {}
        self._fallback_source: np.ndarray | None = None
        self._final_structure_id: str | None = None

    def register(
        self,
        source_support_id: str,
        support_mask: np.ndarray,
        *,
        evidence_types: Iterable[str] = ("anonymous_raster_support",),
        observation_metadata: Mapping[str, object] | None = None,
    ) -> str:
        if not source_support_id or source_support_id in self._supports:
            raise ValueError("source_support_id must be non-empty and unique")
        if support_mask.shape != self.shape:
            raise ValueError("Source support mask must use pipeline source coordinates")
        normalized = np.where(support_mask > 0, 255, 0).astype(np.uint8)
        support_indices = _indices(normalized)
        if not support_indices.size:
            raise ValueError("Source support must contain at least one pixel")
        metadata = dict(observation_metadata or {})
        box = _bbox(normalized)
        if box is not None:
            metadata.setdefault("bbox", [int(value) for value in box])
        metadata.setdefault("source_pixel_count", int(support_indices.size))
        self._supports[source_support_id] = _SupportState(
            source_support_id=source_support_id,
            indices=support_indices,
            evidence_types={str(value) for value in evidence_types},
            observation_metadata=metadata,
        )
        self._backfill(source_support_id)
        return source_support_id

    def register_fallback_roots(
        self,
        binary: np.ndarray,
        paths: Sequence[TracePath],
        *,
        prefix: str = "fallback-support",
    ) -> tuple[str, ...]:
        """Register anonymous fallback roots without coordinate-derived identity."""

        del paths
        foreground = np.where(binary < 128, 1, 0).astype(np.uint8)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            foreground,
            connectivity=8,
        )
        flat_labels = labels.reshape(-1)
        foreground_indices = np.flatnonzero(flat_labels > 0)
        order = np.argsort(flat_labels[foreground_indices], kind="stable")
        ordered_indices = foreground_indices[order]
        ordered_labels = flat_labels[ordered_indices]
        boundaries = np.flatnonzero(np.diff(ordered_labels)) + 1
        groups = np.split(ordered_indices, boundaries)
        created: list[str] = []
        for component_indices in groups:
            if not component_indices.size:
                continue
            label_value = int(flat_labels[int(component_indices[0])])
            x, y, width, height, _area = (
                int(value) for value in stats[label_value]
            )
            crop = labels[y : y + height, x : x + width] == label_value
            digest = sha256(np.packbits(crop).tobytes()).hexdigest()[:12]
            support_id = f"{prefix}-{digest}-{label_value:06d}"
            state = _SupportState(
                source_support_id=support_id,
                indices=component_indices.astype(np.int64, copy=False),
                evidence_types={"anonymous_raster_support"},
                observation_metadata={
                    "fallback_registration": True,
                    "bbox": [x, y, width, height],
                    "source_pixel_count": int(component_indices.size),
                },
            )
            self._supports[support_id] = state
            self._fallback_support_labels.reshape(-1)[component_indices] = label_value
            self._fallback_support_ids[label_value] = support_id
            self._backfill(support_id)
            created.append(support_id)
        return tuple(created)

    def observe_detection(
        self,
        stage: str,
        lines: Sequence[LineSegment],
        *,
        eligible: bool | None = None,
    ) -> None:
        normalized_stage = str(stage).upper()
        frozen = tuple(lines)
        self._stage_lines[normalized_stage] = frozen
        label_map = np.zeros(self.shape, dtype=np.uint16)
        for index, line in enumerate(frozen, start=1):
            thickness = max(1, int(round(max(1.0, float(line.width)))))
            cv2.line(
                label_map,
                (int(round(line.x1)), int(round(line.y1))),
                (int(round(line.x2)), int(round(line.y2))),
                index,
                thickness,
                cv2.LINE_8,
            )
        if self.auto_register_fallback:
            self._stage_line_labels[normalized_stage] = label_map
        for support in self._supports.values():
            ids, covered = self._matching_lines(
                support,
                frozen,
                normalized_stage,
                label_map,
            )
            support.detection_evidence_ids[normalized_stage] = ids
            fraction = covered / max(1, int(support.indices.size))
            if normalized_stage == "RAW":
                support.raw_fraction = fraction
            else:
                support.candidate_fraction = fraction
                support.candidate_ids = list(
                    dict.fromkeys((*support.candidate_ids, *ids))
                )
                if ids:
                    support.candidate_types.add("LINE")
                    support.candidate_branches.add("native_line_reconstruction")
            if eligible is not None:
                support.eligibility_decisions.append(
                    {
                        "stage": normalized_stage,
                        "decision": "ELIGIBLE" if eligible and ids else "INELIGIBLE",
                        "covered_fraction": round(fraction, 6),
                    }
                )
        if normalized_stage != "RAW":
            raw_ids = {
                item.source_support_id: set(item.detection_evidence_ids.get("RAW", ()))
                for item in self._supports.values()
            }
            for support in self._supports.values():
                stage_ids = set(support.detection_evidence_ids.get(normalized_stage, ()))
                removed = sorted(raw_ids[support.source_support_id] - stage_ids)
                if removed:
                    support.filter_decisions.append(
                        {
                            "stage": normalized_stage,
                            "decision": "FILTERED",
                            "evidence_ids": removed,
                        }
                    )

    def observe_ownership(
        self,
        *,
        owner_masks: Mapping[str, np.ndarray],
        downgrades: Sequence[Mapping[str, object]] = (),
        text_adjacent_mask: np.ndarray | None = None,
        symbol_adjacent_mask: np.ndarray | None = None,
    ) -> None:
        del downgrades
        for support in self._supports.values():
            counts = {
                str(owner): int(np.count_nonzero(mask.reshape(-1)[support.indices] > 0))
                for owner, mask in owner_masks.items()
            }
            support.ownership_claims = counts
            support.final_owner = max(counts, key=counts.get) if any(counts.values()) else None
            support.ownership_history.append(
                {"stage": "FINAL_OWNERSHIP", "claims": counts, "final_owner": support.final_owner}
            )
            if counts.get("LINE", 0):
                support.evidence_types.add("native_LINE_evidence")
            elif support.candidate_ids:
                support.evidence_types.add("native_LINE_evidence")
            else:
                support.evidence_types.add("contour-only_evidence")
            if text_adjacent_mask is not None and self._has_overlap(support, text_adjacent_mask):
                support.evidence_types.add("TEXT-adjacent_structural_evidence")
            if symbol_adjacent_mask is not None and self._has_overlap(support, symbol_adjacent_mask):
                support.evidence_types.add("SYMBOL-adjacent_structural_evidence")
            if support.candidate_ids and counts.get("GRAPHIC_FALLBACK", 0):
                support.ownership_history.append(
                    {
                        "stage": "REROUTE",
                        "to": "GRAPHIC_FALLBACK",
                        "reason": "source_pixels_not_finally_owned_by_LINE",
                    }
                )

    def observe_fallback_start(
        self,
        binary: np.ndarray,
        paths: Sequence[TracePath],
        *,
        executed: bool = True,
    ) -> None:
        self._fallback_source = np.ascontiguousarray(binary.copy())
        for support in self._supports.values():
            eligible_pixels = int(np.count_nonzero(binary.reshape(-1)[support.indices] < 128))
            support.fallback_eligibility = "ELIGIBLE" if eligible_pixels else "INELIGIBLE"
            support.fallback_execution = (
                "EXECUTED" if executed and paths and eligible_pixels else "NOT_EXECUTED"
            )
            support.eligibility_decisions.append(
                {
                    "stage": "GRAPHIC_FALLBACK",
                    "decision": support.fallback_eligibility,
                    "eligible_pixels": eligible_pixels,
                }
            )

    def observe_artifact_root(
        self,
        *,
        root_id: str,
        root_mask: np.ndarray,
        decision: str,
        reason: str,
        metrics: Mapping[str, object] | None = None,
    ) -> None:
        if decision not in ARTIFACT_DECISIONS:
            raise ValueError(f"Unknown artifact decision: {decision}")
        root_indices = _indices(root_mask)
        self._observe_artifact_indices(
            root_id=root_id,
            root_indices=root_indices,
            decision=decision,
            reason=reason,
            metrics=metrics,
        )

    def observe_artifact_path(
        self,
        *,
        root_id: str,
        path: TracePath,
        binary: np.ndarray,
        decision: str,
        reason: str,
        metrics: Mapping[str, object] | None = None,
        component_labels: np.ndarray | None = None,
    ) -> None:
        if decision not in ARTIFACT_DECISIONS:
            raise ValueError(f"Unknown artifact decision: {decision}")
        points = np.rint(np.asarray(path.points, dtype=np.float32)).astype(np.int32)
        if len(points) < 3:
            return
        x, y, width, height = cv2.boundingRect(points)
        local_points = points - np.array([x, y], dtype=np.int32)
        local = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(local, [local_points], 255)
        local[binary[y : y + height, x : x + width] >= 128] = 0
        if component_labels is not None:
            clipped_x = np.clip(points[:, 0], 0, self.shape[1] - 1)
            clipped_y = np.clip(points[:, 1], 0, self.shape[0] - 1)
            path_labels = component_labels[clipped_y, clipped_x]
            positive = path_labels[path_labels > 0]
            if positive.size:
                values, counts = np.unique(positive, return_counts=True)
                component = int(values[int(np.argmax(counts))])
                local &= np.where(
                    component_labels[y : y + height, x : x + width] == component,
                    255,
                    0,
                ).astype(np.uint8)
        local_y, local_x = np.nonzero(local)
        root_indices = (
            (local_y.astype(np.int64) + y) * self.shape[1]
            + local_x.astype(np.int64)
            + x
        )
        self._observe_artifact_indices(
            root_id=root_id,
            root_indices=root_indices,
            decision=decision,
            reason=reason,
            metrics=metrics,
        )

    def _observe_artifact_indices(
        self,
        *,
        root_id: str,
        root_indices: np.ndarray,
        decision: str,
        reason: str,
        metrics: Mapping[str, object] | None,
    ) -> None:
        if not root_indices.size:
            return
        auto_labels, auto_counts = np.unique(
            self._fallback_support_labels.reshape(-1)[root_indices],
            return_counts=True,
        )
        for label_value, overlap in zip(auto_labels, auto_counts, strict=True):
            support_id = self._fallback_support_ids.get(int(label_value))
            if support_id is not None:
                self._append_artifact_decision(
                    self._supports[support_id], root_id, decision, reason, int(overlap), metrics
                )
        for support in self._supports.values():
            if support.observation_metadata.get("fallback_registration"):
                continue
            overlap = int(np.intersect1d(root_indices, support.indices).size)
            if overlap:
                self._append_artifact_decision(
                    support, root_id, decision, reason, overlap, metrics
                )

    def observe_fallback_result(self, binary: np.ndarray) -> None:
        for support in self._supports.values():
            retained = int(np.count_nonzero(binary.reshape(-1)[support.indices] < 128))
            if support.fallback_execution == "EXECUTED":
                support.fallback_result = "RESCUED" if retained else "REJECTED"

    def observe_final(
        self,
        *,
        contours: Sequence[TracePath],
        straight_lines: Sequence[LineSegment],
        contour_binary: np.ndarray,
        final_structure_id: str,
    ) -> None:
        self._final_structure_id = str(final_structure_id)
        del contours
        final_foreground = np.where(contour_binary < 128, 1, 0).astype(np.uint8)
        _count, contour_labels = cv2.connectedComponents(final_foreground, connectivity=8)
        line_labels = np.zeros(self.shape, dtype=np.uint16)
        for index, line in enumerate(straight_lines, start=1):
            thickness = max(1, int(round(max(1.0, float(line.width)))))
            cv2.line(
                line_labels,
                (int(round(line.x1)), int(round(line.y1))),
                (int(round(line.x2)), int(round(line.y2))),
                index,
                thickness,
                cv2.LINE_8,
            )
        for support in self._supports.values():
            contour_values = np.unique(contour_labels.reshape(-1)[support.indices])
            line_values = np.unique(line_labels.reshape(-1)[support.indices])
            geometry = [
                f"contour-component-{int(value):06d}"
                for value in contour_values
                if int(value) > 0
            ] + [
                f"line-{int(value) - 1:06d}"
                for value in line_values
                if int(value) > 0
            ]
            support.geometry_ids = geometry
            support.promoted_ids = list(geometry)
            if geometry:
                support.final_structure_ids = [str(final_structure_id)]
            self._resolve_terminal(support)

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": "source-support-lifecycle-v1",
            "semantic_authority": "NONE",
            "source_coordinate_identity": False,
            "registered_source_supports": len(self._supports),
            "supports": [self._payload(item) for item in self._supports.values()],
            "census": self.census(),
        }

    def census(self) -> dict[str, object]:
        supports = list(self._supports.values())
        gaps: dict[str, int] = {}
        for item in supports:
            for stage in item.coverage_gaps:
                gaps[stage] = gaps.get(stage, 0) + 1
        return {
            "registered_source_supports": len(supports),
            "supports_with_complete_lineage": sum(not item.coverage_gaps for item in supports),
            "supports_with_terminal_reason": sum(item.terminal_reason is not None for item in supports),
            "supports_preserved": sum(item.terminal_reason == "PRESERVED" for item in supports),
            "supports_rejected_in_artifact_suppression": sum(
                any(str(decision["decision"]).startswith("REJECTED_") for decision in item.artifact_suppression_decisions)
                for item in supports
            ),
            "supports_lost_before_fallback": sum(
                item.terminal_reason in {"NO_RAW_EVIDENCE", "DETECTION_FRAGMENTED", "CANDIDATE_INELIGIBLE", "FILTERED", "OWNERSHIP_SUPPRESSED"}
                and item.fallback_execution != "EXECUTED"
                for item in supports
            ),
            "supports_with_instrumentation_gap": sum(bool(item.coverage_gaps) for item in supports),
            "instrumentation_gaps_by_stage": gaps,
        }

    def _matching_lines(
        self,
        support: _SupportState,
        lines: Sequence[LineSegment],
        prefix: str,
        label_map: np.ndarray | None = None,
    ) -> tuple[list[str], int]:
        labels = (
            self._stage_line_labels.get(prefix)
            if label_map is None
            else label_map
        )
        if labels is None:
            return [], 0
        values = labels.reshape(-1)[support.indices]
        ids = [
            _line_id(lines[int(value) - 1], int(value) - 1, prefix)
            for value in np.unique(values)
            if int(value) > 0
        ]
        return list(dict.fromkeys(ids)), int(np.count_nonzero(values))

    def _has_overlap(self, support: _SupportState, mask: np.ndarray) -> bool:
        return bool(np.any(mask.reshape(-1)[support.indices] > 0))

    def _backfill(self, support_id: str) -> None:
        support = self._supports[support_id]
        for stage, lines in self._stage_lines.items():
            ids, covered = self._matching_lines(
                support,
                lines,
                stage,
                self._stage_line_labels.get(stage),
            )
            support.detection_evidence_ids[stage] = ids
            fraction = covered / max(1, int(support.indices.size))
            if stage == "RAW":
                support.raw_fraction = fraction
            else:
                support.candidate_fraction = fraction
                support.candidate_ids = list(
                    dict.fromkeys((*support.candidate_ids, *ids))
                )
                if ids:
                    support.candidate_types.add("LINE")
                    support.candidate_branches.add("native_line_reconstruction")

    @staticmethod
    def _append_artifact_decision(
        support: _SupportState,
        root_id: str,
        decision: str,
        reason: str,
        overlap: int,
        metrics: Mapping[str, object] | None,
    ) -> None:
        support.fallback_root_ids.append(root_id)
        support.artifact_suppression_decisions.append(
            {
                "root_id": root_id,
                "decision": decision,
                "reason": str(reason),
                "overlap_pixels": int(overlap),
                "metrics": dict(metrics or {}),
            }
        )

    def _resolve_terminal(self, support: _SupportState) -> None:
        support.coverage_gaps.clear()
        if support.geometry_ids:
            support.terminal_reason = "PRESERVED"
        elif 0.0 < support.raw_fraction < 0.95:
            support.terminal_reason = "DETECTION_FRAGMENTED"
        elif support.raw_fraction == 0.0 and support.fallback_execution != "EXECUTED":
            support.terminal_reason = "NO_RAW_EVIDENCE"
        elif any(
            item["decision"] == "REJECTED_DAMAGE_CLUSTER_PROPAGATION"
            for item in support.artifact_suppression_decisions
        ):
            support.terminal_reason = "DAMAGE_CLUSTER_PROPAGATION_REJECTED"
        elif any(
            item["decision"] == "REJECTED_NEAR_DAMAGE_FRAGMENT"
            for item in support.artifact_suppression_decisions
        ):
            support.terminal_reason = "NEAR_DAMAGE_FRAGMENT_REJECTED"
        elif any(
            str(item["decision"]).startswith("REJECTED_")
            for item in support.artifact_suppression_decisions
        ):
            support.terminal_reason = "ARTIFACT_SUPPRESSION_REJECTED"
        elif support.fallback_result == "REJECTED":
            support.terminal_reason = "ARTIFACT_SUPPRESSION_REJECTED"
        elif support.candidate_ids and not support.geometry_ids:
            support.terminal_reason = "GEOMETRY_DROPPED"
        else:
            support.terminal_reason = "UNKNOWN_SILENT_DROP"
            support.coverage_gaps.append("TERMINAL_FATE")
        if not support.detection_evidence_ids:
            support.coverage_gaps.append("DETECTION")
        if support.fallback_execution == "EXECUTED" and not support.artifact_suppression_decisions:
            support.coverage_gaps.append("ARTIFACT_SUPPRESSION")

    @staticmethod
    def _payload(item: _SupportState) -> dict[str, object]:
        evidence_types = sorted(item.evidence_types)
        if len(evidence_types) > 1:
            evidence_types.append("multiple_upstream_evidence_sources")
        return {
            "source_support_id": item.source_support_id,
            "observation_metadata": dict(item.observation_metadata),
            "upstream_evidence_types": evidence_types,
            "detection_evidence_ids": {key: list(value) for key, value in item.detection_evidence_ids.items()},
            "candidate_ids": list(item.candidate_ids),
            "candidate_types": sorted(item.candidate_types),
            "candidate_branches": sorted(item.candidate_branches),
            "ever_had_candidate_id": bool(item.candidate_ids),
            "ever_had_line_ownership_claim": bool(item.ownership_claims.get("LINE", 0)),
            "eligibility_decisions": list(item.eligibility_decisions),
            "ownership_claims": dict(item.ownership_claims),
            "final_owner": item.final_owner,
            "ownership_history": list(item.ownership_history),
            "filter_decisions": list(item.filter_decisions),
            "fallback_eligibility": item.fallback_eligibility,
            "fallback_execution": item.fallback_execution,
            "fallback_root_ids": list(dict.fromkeys(item.fallback_root_ids)),
            "artifact_suppression_decisions": list(item.artifact_suppression_decisions),
            "fallback_result": item.fallback_result,
            "geometry_ids": list(item.geometry_ids),
            "promoted_ids": list(item.promoted_ids),
            "final_structure_ids": list(item.final_structure_ids),
            "terminal_reason": item.terminal_reason,
            "coverage_gaps": list(item.coverage_gaps),
        }
