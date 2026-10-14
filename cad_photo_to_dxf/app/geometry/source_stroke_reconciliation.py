"""Bounded, source-pixel-backed reconciliation of LINE representations.

This module does not decide semantic ownership and it does not build output
structures.  It records immutable detector/route evidence, certifies local
relations on the original (unclosed) source raster, and returns exact
subsegments for the existing FinalStructure path to consume.

The implementation deliberately has no global "near line" merge.  Geometry is
only a retrieval gate.  A destructive action additionally requires both
trajectories to bind to the same source run in every certified local cell and
requires the removed observation's endpoint obligations to remain represented.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
from enum import Enum
import hashlib
import json
import math
from typing import Mapping, Sequence

import cv2
import numpy as np

from app.geometry.line_detect import LineSegment
from app.geometry.reconciliation_geometry import _production_claim_thickness
from app.geometry.reconciliation_geometry import ParameterInterval, _bresenham_pixels, _child_interval_on_parent, _clipped_child_interval_on_parent, _exact_subsegment, _geometry_key, _geometry_payload, _geometry_payload_matches_line, _intersect_interval_sets, _line_claim_mask, _line_from_geometry_payload, _line_from_payload, _line_identity_key, _line_payload, _local_claim_footprint_pixels, _local_mask_state, _merge_intervals, _parameter_at_axis_coordinate, _pixel_is_source, _subtract_intervals, _trajectory_basis_payload, _trajectory_evidence_key


SCHEMA_VERSION = "source-visible-reconciliation-v1"
POLICY_VERSION = "bounded-source-stroke-reconciliation-v1"
GAP_EXTENT_SCHEMA_VERSION = "source-stroke-gap-extent-v2"
GAP_EXTENT_POLICY_VERSION = "source-faithful-gap-accounting-v2"
GAP_EXTENT_MEASUREMENT_SLOT = "source_stroke_gap_extent_v2"
LEGACY_ACCEPTED_HISTORY = "source_stroke_legacy_accepted"
PIECE_HISTORY = "source_stroke_reconciliation_piece"
DXF_MIN_LINE_LENGTH_PX = 1e-6
SOURCE_SNAPSHOT_VERSION = "source-authority-snapshot-v1"
SOURCE_FRAME_ID = "ORIGINAL_SOURCE_PIXELS"
SCOPED_ACCEPTANCE_VERSION = "scoped-restoration-acceptance-v1"


class Relation(str, Enum):
    SAME_VISIBLE_STROKE_SUPPORTED = "SAME_VISIBLE_STROKE_SUPPORTED"
    DISTINCT_VISIBLE_STROKES_SUPPORTED = "DISTINCT_VISIBLE_STROKES_SUPPORTED"
    RELATION_UNRESOLVED = "RELATION_UNRESOLVED"


class Operation(str, Enum):
    KEEP_BOTH = "KEEP_BOTH"
    KEEP_ONE_EQUIVALENT_REPRESENTATION = "KEEP_ONE_EQUIVALENT_REPRESENTATION"
    KEEP_NOVEL_INTERVAL_ONLY = "KEEP_NOVEL_INTERVAL_ONLY"
    BLOCK_AND_REVIEW = "BLOCK_AND_REVIEW"


class RouteOrigin(str, Enum):
    MAIN = "MAIN"
    RESTORATION = "RESTORATION"


class LineageOperation(str, Enum):
    ORIGINAL_OBSERVATION = "ORIGINAL_OBSERVATION"
    TRIM_TO_SOURCE_SUPPORT = "TRIM_TO_SOURCE_SUPPORT"
    COVERAGE_SPLIT = "COVERAGE_SPLIT"
    ROUTE_DIVERSION = "ROUTE_DIVERSION"
    INTERSECTION_EXTENSION = "INTERSECTION_EXTENSION"
    ROUTE_TRANSFORM = "ROUTE_TRANSFORM"
    CONSOLIDATION = "CONSOLIDATION"


class TerminalDisposition(str, Enum):
    RETAINED = "RETAINED"
    REJECTED_OWNERSHIP = "REJECTED_OWNERSHIP"
    REJECTED_PROTECTION = "REJECTED_PROTECTION"
    SUPERSEDED_EQUIVALENT = "SUPERSEDED_EQUIVALENT"
    ROUTE_DIVERTED = "ROUTE_DIVERTED"
    TRANSFORMED_CHILD = "TRANSFORMED_CHILD"
    SPLIT = "SPLIT"
    BLOCKED = "BLOCKED"




@dataclass(frozen=True)
class RelationCell:
    left_id: str
    right_id: str
    left_interval: ParameterInterval
    right_interval: ParameterInterval
    relation: Relation
    endpoint_obligations_clear: bool
    evidence_id: str
    measurements: tuple[tuple[str, object], ...]
    reason: str
    protection_state: str = "UNPROTECTED"
    semantic_owner_state: str = "LINE_OR_UNOWNED"
    ownership_state: str = "ACCEPTED"
    ancestry_state: str = "CLEAR"

    def payload(self, index: int) -> dict[str, object]:
        operation = (
            Operation.KEEP_ONE_EQUIVALENT_REPRESENTATION
            if self.relation is Relation.SAME_VISIBLE_STROKE_SUPPORTED
            and self.endpoint_obligations_clear
            else Operation.KEEP_BOTH
        )
        return {
            "cell_id": f"cell-{index:06d}",
            "members": [self.left_id, self.right_id],
            "interval": self.right_interval.payload((self.evidence_id,)),
            "relation": self.relation.value,
            "positive_evidence_refs": (
                [self.evidence_id]
                if self.relation
                in {
                    Relation.SAME_VISIBLE_STROKE_SUPPORTED,
                    Relation.DISTINCT_VISIBLE_STROKES_SUPPORTED,
                }
                else []
            ),
            "negative_evidence_refs": (
                [self.evidence_id]
                if self.relation is Relation.RELATION_UNRESOLVED
                else []
            ),
            "endpoint_obligations_clear": self.endpoint_obligations_clear,
            "operation": operation.value,
            "retained_ids": [self.left_id],
            "novel_intervals": [],
            "reason": self.reason,
            "member_intervals": {
                self.left_id: self.left_interval.payload((self.evidence_id,)),
                self.right_id: self.right_interval.payload((self.evidence_id,)),
            },
            "local_obligations": {
                "trajectory_evidence": (
                    "POSITIVE"
                    if self.relation is not Relation.RELATION_UNRESOLVED
                    else "UNKNOWN"
                ),
                "endpoint_attachment_status": (
                    "CLEAR_WITH_EVIDENCE"
                    if self.endpoint_obligations_clear
                    else "PRESERVE"
                ),
                "protection_state": self.protection_state,
                "semantic_owner_state": self.semantic_owner_state,
                "ownership_state": self.ownership_state,
                "ancestry_tombstone_state": self.ancestry_state,
            },
        }


@dataclass(frozen=True)
class _ReconciliationEvidenceCache:
    """Transaction-scoped reuse of exact immutable evidence computations."""

    snapshot_key: tuple[str, ...]
    pair_results: dict[tuple[object, ...], tuple[RelationCell, ...]]
    claim_masks: dict[tuple[tuple[str, ...], tuple[int, int]], np.ndarray]
    footprints: dict[tuple[str, ...], tuple[dict[str, object], ...]]
    support_segments: dict[tuple[str, ...], tuple[dict[str, object], ...]]
    counters: dict[str, int]

    @classmethod
    def create(cls, *snapshot_key: str) -> _ReconciliationEvidenceCache:
        return cls(tuple(snapshot_key), {}, {}, {}, {}, {})

    def count(self, name: str) -> None:
        self.counters[name] = self.counters.get(name, 0) + 1


@dataclass(frozen=True)
class _ImmutableRasterSnapshot:
    """Private immutable authority for one canonical C-order raster."""

    data: bytes
    shape: tuple[int, int]
    dtype: str
    layout: str
    source_frame_id: str
    version: str
    sha256: str
    digest: str

    @classmethod
    def seal(cls, value: np.ndarray, *, source_frame_id: str) -> _ImmutableRasterSnapshot:
        canonical = np.ascontiguousarray(value, dtype=np.uint8)
        data = canonical.tobytes(order="C")
        metadata = {
            "shape": list(canonical.shape),
            "dtype": canonical.dtype.str,
            "layout": "C_ORDER_EXACT_BYTES",
            "source_frame_id": source_frame_id,
            "version": SOURCE_SNAPSHOT_VERSION,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return cls(
            data=data,
            shape=tuple(int(item) for item in canonical.shape),
            dtype=canonical.dtype.str,
            layout="C_ORDER_EXACT_BYTES",
            source_frame_id=source_frame_id,
            version=SOURCE_SNAPSHOT_VERSION,
            sha256=str(metadata["sha256"]),
            digest=hashlib.sha256(
                json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )

    def working_array(self) -> np.ndarray:
        return np.frombuffer(self.data, dtype=np.dtype(self.dtype)).reshape(self.shape)


@dataclass(frozen=True)
class ScopedRestorationAcceptance:
    """Explicit trusted authorization for exact intervals of one restoration."""

    stable_identity: str
    intervals: tuple[tuple[float, float], ...]
    source_scope_digest: str
    authority_source: str
    version: str
    digest: str


@dataclass(frozen=True)
class _ValidationContext:
    input_lines: tuple[LineSegment, ...]
    main_candidates: tuple[LineSegment, ...]
    restoration_candidates: tuple[LineSegment, ...]
    accepted_main: tuple[LineSegment, ...]
    accepted_restorations: tuple[LineSegment, ...]
    source_gray: np.ndarray
    source_binary: np.ndarray
    protected_mask: np.ndarray
    ownership_masks: Mapping[str, np.ndarray]
    route_ledger_json: str
    authority_snapshot_digest: str
    accepted_snapshot_digest: str
    source_gray_sha256: str
    source_binary_sha256: str
    source_gray_authority: _ImmutableRasterSnapshot
    source_binary_authority: _ImmutableRasterSnapshot
    source_scope_digest: str
    scale: float
    evidence_cache: _ReconciliationEvidenceCache
    validated_ledger_digest: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    """Committed line tuple plus an immutable serialized evidence ledger."""

    lines: tuple[LineSegment, ...]
    ledger_json: str
    ledger_digest: str
    input_set_digest: str
    final_set_digest: str
    terminal_representation_ids: tuple[str, ...]
    final_piece_ids: tuple[str, ...]
    _validation_context: _ValidationContext

    def ledger_payload(self) -> dict[str, object]:
        return json.loads(self.ledger_json)

    def commit(self) -> tuple[LineSegment, ...]:
        """Return the exact immutable tuple authorized for FinalStructure."""

        self.assert_complete()
        return self.lines

    def assert_complete(
        self,
        actual_final_lines: Sequence[LineSegment] | None = None,
    ) -> None:
        """Validate the immutable transaction against the lines actually consumed.

        ``actual_final_lines`` is mandatory at the FinalStructure boundary.  The
        optional default exists for callers validating the result immediately
        after :meth:`ReconciliationLedger.reconcile`.
        """

        if type(self.lines) is not tuple or any(
            type(line) is not LineSegment for line in self.lines
        ):
            raise TypeError(
                "Committed reconciliation geometry must be an exact immutable tuple of frozen LineSegment values"
            )
        if type(self._validation_context) is not _ValidationContext:
            raise TypeError("Reconciliation validation context was substituted")
        if actual_final_lines is not None and type(actual_final_lines) is not tuple:
            raise TypeError(
                "FinalStructure must consume the exact committed immutable tuple"
            )
        payload = self.ledger_payload()
        representations = payload.get("representations", [])
        supersession = payload.get("supersession_ledger", [])
        represented = {
            str(item["representation_id"])
            for item in representations
            if isinstance(item, dict) and "representation_id" in item
        }
        terminal = {
            str(item["representation_id"])
            for item in supersession
            if isinstance(item, dict) and "representation_id" in item
        }
        if represented != terminal:
            raise AssertionError(
                "Every reconciliation representation must have a terminal disposition"
            )
        if tuple(sorted(terminal)) != tuple(sorted(self.terminal_representation_ids)):
            raise AssertionError("Terminal reconciliation ledger changed after commit")
        if _digest_payload(payload) != self.ledger_digest:
            raise AssertionError("Reconciliation ledger digest is incomplete")
        if self.ledger_digest != self._validation_context.validated_ledger_digest:
            raise AssertionError(
                "Submitted ledger differs from the independently sealed validated transaction"
            )
        committed_lines = self.lines
        consumed_lines = (
            committed_lines
            if actual_final_lines is None
            else actual_final_lines
        )
        if consumed_lines is not committed_lines:
            raise AssertionError(
                "Actual FinalStructure line set must be the exact tuple object validated by commit"
            )
        if _lines_digest(committed_lines) != self.final_set_digest:
            raise AssertionError("Reconciled final line set changed after commit")
        emitted_piece_ids = tuple(
            str(item["piece_id"])
            for item in payload.get("pieces", ())
            if isinstance(item, dict) and item.get("action") == "EMIT"
        )
        if emitted_piece_ids != self.final_piece_ids:
            raise AssertionError("Committed reconciliation piece set changed")
        snapshot = next(
            (
                item
                for item in payload.get("evidence", ())
                if isinstance(item, dict)
                and item.get("artifact") == "runtime-route-ledger-snapshot"
            ),
            None,
        )
        measurements = snapshot.get("measurements") if isinstance(snapshot, dict) else None
        route_ledger = (
            measurements.get("route_ledger")
            if isinstance(measurements, dict)
            else None
        )
        if not isinstance(route_ledger, dict):
            raise AssertionError("Reconciliation route ledger is missing")
        if _digest_payload(route_ledger) != payload.get("route_ledger_digest"):
            raise AssertionError("Reconciliation route-ledger digest is incomplete")
        input_lines = (
            measurements.get("input_lines")
            if isinstance(measurements, dict)
            else None
        )
        if not isinstance(input_lines, list):
            raise AssertionError("Reconciliation input evidence is missing")
        if _digest_payload(input_lines) != self.input_set_digest:
            raise AssertionError("Reconciliation input-set digest is incomplete")
        transaction = payload.get("transaction")
        if not isinstance(transaction, dict) or transaction.get("state") != "VALIDATED":
            raise AssertionError("Reconciliation transaction was not validated")
        if not transaction.get("final_set_digest_validated"):
            raise AssertionError("Reconciliation final-set digest was not validated")
        # Commit-time authority never trusts retained memoized results.  A fresh
        # cache may reuse exact computations within this validation pass, but it
        # begins empty so mutable diagnostic cache state cannot become evidence.
        commit_context = replace(
            self._validation_context,
            evidence_cache=_ReconciliationEvidenceCache.create(
                *self._validation_context.evidence_cache.snapshot_key
            ),
        )
        _validate_transaction_semantics(
            payload,
            final_lines=consumed_lines,
            final_piece_ids=self.final_piece_ids,
            context=commit_context,
        )


class ReconciliationLedger:
    """Mutable collection phase; :meth:`reconcile` freezes the final record."""

    def __init__(
        self,
        *,
        source_gray: np.ndarray,
        source_binary: np.ndarray,
        protected_mask: np.ndarray | None,
        scale: float,
    ) -> None:
        if source_gray.ndim != 2 or source_binary.ndim != 2:
            raise ValueError("Reconciliation source rasters must be 2D")
        if source_gray.shape != source_binary.shape:
            raise ValueError("Reconciliation source rasters must have equal shape")
        if protected_mask is not None and protected_mask.shape != source_gray.shape:
            raise ValueError("Protected mask must match reconciliation source")
        self._source_gray_authority = _ImmutableRasterSnapshot.seal(
            source_gray, source_frame_id=SOURCE_FRAME_ID
        )
        self._source_binary_authority = _ImmutableRasterSnapshot.seal(
            source_binary, source_frame_id=SOURCE_FRAME_ID
        )
        self.source_gray = self._source_gray_authority.working_array()
        self.source_binary = self._source_binary_authority.working_array()
        self.protected_mask = (
            np.zeros_like(self.source_binary)
            if protected_mask is None
            else np.ascontiguousarray(protected_mask, dtype=np.uint8)
        )
        self.scale = float(scale)
        self._observed: list[dict[str, object]] = []
        self._transformations: list[dict[str, object]] = []
        self._consolidations: list[dict[str, object]] = []
        self._early_proposals: list[dict[str, object]] = []
        self._prefilter_terminal: dict[str, tuple[str, str]] = {}

    def authorize_restoration(
        self,
        line: LineSegment,
        *,
        intervals: Sequence[tuple[float, float]] | None = None,
        authority_source: str = "EXPLICIT_TRUSTED_CALLER_SNAPSHOT",
    ) -> ScopedRestorationAcceptance:
        """Create a source-bound authorization at the trusted ledger boundary."""

        requested = (
            ((0.0, float(line.length)),)
            if intervals is None
            else tuple((float(start), float(end)) for start, end in intervals)
        )
        normalized = tuple(
            (float(item.start), float(item.end))
            for item in _merge_intervals(
                tuple(ParameterInterval(start, end) for start, end in requested)
            )
        )
        if not normalized or any(
            start < 0.0 or end > line.length or end <= start
            for start, end in normalized
        ):
            raise ValueError("Acceptance intervals must be non-empty and within the candidate")
        source_scope_digest = _source_scope_digest(
            self._source_gray_authority, self._source_binary_authority
        )
        payload = {
            "stable_identity": _acceptance_identity_key(line),
            "intervals": [list(item) for item in normalized],
            "source_scope_digest": source_scope_digest,
            "authority_source": str(authority_source),
            "version": SCOPED_ACCEPTANCE_VERSION,
        }
        return ScopedRestorationAcceptance(
            stable_identity=str(payload["stable_identity"]),
            intervals=normalized,
            source_scope_digest=source_scope_digest,
            authority_source=str(authority_source),
            version=SCOPED_ACCEPTANCE_VERSION,
            digest=_digest_payload(payload),
        )

    def observe_route(
        self,
        lines: Sequence[LineSegment],
        *,
        route: RouteOrigin,
        producer: str,
    ) -> None:
        """Retain original geometry/provenance before a lossy route decision."""

        known = {str(item["observation_key"]) for item in self._observed}
        route_index = sum(1 for item in self._observed if item["route"] == route.value)
        for offset, line in enumerate(lines):
            key = _observation_key(route, line)
            if key in known:
                continue
            self._observed.append(
                {
                    "observation_id": (
                        "observation-"
                        f"{hashlib.sha256(key.encode()).hexdigest()[:20]}"
                    ),
                    "observation_key": key,
                    "source_claim_id": _source_claim_id(line),
                    "route": route.value,
                    "producer": producer,
                    "route_index": route_index + offset,
                    "line": _line_payload(line),
                }
            )
            known.add(key)

    def observe_transformation(
        self,
        parent: LineSegment,
        child: LineSegment,
        *,
        parent_route: RouteOrigin,
        child_route: RouteOrigin,
        producer: str,
        operation: LineageOperation,
        parent_parameter_interval: tuple[float, float] | None = None,
        child_parameter_interval: tuple[float, float] | None = None,
    ) -> None:
        """Record one explicit immutable parent/child transformation edge.

        The caller supplies the actual objects at the transformation site.  No
        geometry equality, source-ID overlap, or history similarity is used to
        invent ancestry later.
        """

        self.observe_route((parent,), route=parent_route, producer=f"{producer}:parent")
        self.observe_route((child,), route=child_route, producer=f"{producer}:child")
        parent_observation_id = self._observation_id(parent_route, parent)
        child_observation_id = self._observation_id(child_route, child)
        if parent_parameter_interval is None:
            parent_parameter_interval = _child_interval_on_parent(parent, child)
        if child_parameter_interval is None:
            child_parameter_interval = (0.0, float(child.length))
        parent_start, parent_end = map(float, parent_parameter_interval)
        child_start, child_end = map(float, child_parameter_interval)
        if parent_end < parent_start or child_end < child_start:
            raise ValueError("Transformation intervals must be ordered")
        edge = {
            "transformation_id": (
                f"transform-{len(self._transformations):06d}-"
                f"{hashlib.sha256((parent_observation_id + '|' + child_observation_id + '|' + operation.value).encode()).hexdigest()[:12]}"
            ),
            "parent_observation_id": parent_observation_id,
            "child_observation_id": child_observation_id,
            "operation": operation.value,
            "parent_parameter_interval": [parent_start, parent_end],
            "child_parameter_interval": [child_start, child_end],
            "parent_trajectory_basis": _trajectory_basis_payload(parent),
            "child_geometry_px": _geometry_payload(child),
            "child_endpoint_types": [
                (
                    "ORIGINAL_OBSERVED_ENDPOINT"
                    if np.array_equal(child.p1, parent.p1)
                    else "DERIVED_TRANSFORM_ENDPOINT"
                ),
                (
                    "ORIGINAL_OBSERVED_ENDPOINT"
                    if np.array_equal(child.p2, parent.p2)
                    else "DERIVED_TRANSFORM_ENDPOINT"
                ),
            ],
            "actual_derived_cut_coordinates": [
                [float(child.x1), float(child.y1)],
                [float(child.x2), float(child.y2)],
            ],
            "route_transition": f"{parent_route.value}->{child_route.value}",
            "source_ids": list(child.source_ids),
            "history": list(child.history),
            "producer": producer,
        }
        existing = {
            (
                str(item["parent_observation_id"]),
                str(item["child_observation_id"]),
                str(item["operation"]),
            )
            for item in self._transformations
        }
        identity = (parent_observation_id, child_observation_id, operation.value)
        if identity not in existing:
            self._transformations.append(edge)

    def observe_consolidation(
        self,
        parents: Sequence[LineSegment],
        child: LineSegment,
        *,
        route: RouteOrigin,
        producer: str,
    ) -> None:
        """Record a real many-to-one preparation operation before parents vanish."""

        if len(parents) < 2:
            raise ValueError("Consolidation lineage requires at least two parents")
        self.observe_route(parents, route=route, producer=f"{producer}:original")
        self.observe_route((child,), route=route, producer=f"{producer}:result")
        parent_ids = [self._observation_id(route, line) for line in parents]
        child_id = self._observation_id(route, child)
        identity = (tuple(parent_ids), child_id, producer)
        existing = {
            (
                tuple(str(value) for value in item["parent_observation_ids"]),
                str(item["result_observation_id"]),
                str(item["producer"]),
            )
            for item in self._consolidations
        }
        if identity in existing:
            return
        self._consolidations.append(
            {
                "consolidation_id": (
                    f"consolidation-{len(self._consolidations):06d}-"
                    f"{hashlib.sha256(('|'.join(parent_ids) + '|' + child_id).encode()).hexdigest()[:12]}"
                ),
                "operation": LineageOperation.CONSOLIDATION.value,
                "parent_observation_ids": parent_ids,
                "result_observation_id": child_id,
                "parent_interval_mappings": [
                    {
                        "parent_observation_id": parent_id,
                        "parent_parameter_interval": [0.0, float(parent.length)],
                        "result_parameter_interval": list(
                            _clipped_child_interval_on_parent(child, parent)
                        ),
                        "parent_geometry_px": _geometry_payload(parent),
                    }
                    for parent_id, parent in zip(parent_ids, parents, strict=True)
                ],
                "result_geometry_px": _geometry_payload(child),
                "route": route.value,
                "producer": producer,
            }
        )

    def consolidate_detector_aliases(
        self, lines: Sequence[LineSegment]
    ) -> list[LineSegment]:
        """Bind whole edge observations before center-trajectory reconciliation.

        A white edge trajectory is not source-absence evidence. Only raster
        aliases with one continuous source band and complete claim containment
        qualify here. Keep an existing geometry; never bridge or extend it.
        """
        def order(line: LineSegment) -> tuple[object, ...]:
            span = max(abs(round(line.x2) - round(line.x1)),
                       abs(round(line.y2) - round(line.y1)))
            return (-span, -line.confidence, _stable_line_key(line))

        def eligible(line: LineSegment) -> bool:
            x1, y1, x2, y2 = (round(value) for value in
                (line.x1, line.y1, line.x2, line.y2))
            return ((x1 == x2) != (y1 == y2)
                and _RetainedCandidateIndex._orientation(line) is not None) and any(
                h.startswith("detected:") for h in line.history)

        output: list[LineSegment] = []
        output_positions: list[int] = []
        index = _RetainedCandidateIndex(scale=self.scale)
        endpoint_users: dict[tuple[float, float], list[LineSegment]] = {}
        for line in lines:
            for point in ((line.x1, line.y1), (line.x2, line.y2)):
                endpoint_users.setdefault(point, []).append(line)
        for input_position, line in sorted(enumerate(lines), key=lambda item: order(item[1])):
            matched = False
            for slot, keeper in index.query(line, include_non_axis=False) if eligible(line) else ():
                # The index retains the old geometry for retrieval only. The
                # current value contains all accumulated observation lineage.
                keeper = output[int(slot)]
                if any(
                    point not in ((keeper.x1, keeper.y1), (keeper.x2, keeper.y2))
                    and any(peer is not line and not set(peer.source_ids).issubset(
                        keeper.source_ids) for peer in endpoint_users[point])
                    for point in ((line.x1, line.y1), (line.x2, line.y2))
                ):
                    # A source cap does not authorize losing an independently
                    # represented exact CAD junction carried by this endpoint.
                    continue
                if not _source_bound_raster_alias(
                    keeper, line, gray=self.source_gray, binary=self.source_binary,
                    protected_mask=self.protected_mask,
                ):
                    continue
                child = keeper.copy(
                    source_ids=tuple(sorted(set(keeper.source_ids + line.source_ids))),
                    history=tuple(dict.fromkeys(keeper.history + line.history))
                    + ("source_bound_raster_alias",),
                )
                self.observe_consolidation(
                    (keeper, line), child, route=RouteOrigin.MAIN,
                    producer="source-bound-raster-alias-consolidation",
                )
                output[int(slot)] = child
                output_positions[int(slot)] = min(output_positions[int(slot)], input_position)
                matched = True
                break
            if not matched:
                if eligible(line):
                    index.add(str(len(output)), line)
                output.append(line)
                output_positions.append(input_position)
        # Preserve detector input order for observations that did not change.
        return [line for _, line in sorted(zip(output_positions, output), key=lambda item: item[0])]

    def record_suppression_group(
        self,
        *,
        route: RouteOrigin,
        base: LineSegment,
        members: Sequence[LineSegment],
    ) -> None:
        if len(members) < 2:
            return
        self._early_proposals.append(
            {
                "proposal_id": f"proposal-{len(self._early_proposals):06d}",
                "route": route.value,
                "base_observation_id": self._observation_id(route, base),
                "member_observation_ids": [
                    self._observation_id(route, line) for line in members
                ],
                "state": "PROPOSED_ONLY",
                "authority": "NONE_UNTIL_FINAL_RECONCILIATION",
            }
        )

    def record_prefilter_rejection(
        self,
        line: LineSegment,
        *,
        route: RouteOrigin,
        reason: str,
        disposition: TerminalDisposition = TerminalDisposition.BLOCKED,
    ) -> None:
        if disposition not in {
            TerminalDisposition.BLOCKED,
            TerminalDisposition.REJECTED_PROTECTION,
        }:
            raise ValueError("Prefilter rejection must be BLOCKED or REJECTED_PROTECTION")
        self._prefilter_terminal[_observation_key(route, line)] = (
            disposition.value,
            reason,
        )

    def _observation_id(self, route: RouteOrigin, line: LineSegment) -> str:
        key = _observation_key(route, line)
        for item in self._observed:
            if str(item["observation_key"]) == key:
                return str(item["observation_id"])
        raise AssertionError("Route decision references an unobserved representation")

    def reconcile(
        self,
        *,
        main_candidates: Sequence[LineSegment],
        accepted_main: Sequence[LineSegment],
        restoration_candidates: Sequence[LineSegment],
        ownership_masks: Mapping[str, np.ndarray],
        ownership_downgrades: Sequence[Mapping[str, object]] = (),
        accepted_restorations: Sequence[LineSegment] = (),
        accepted_restoration_authorizations: Sequence[
            ScopedRestorationAcceptance
        ] = (),
    ) -> ReconciliationResult:
        """Reconcile accepted MAIN and eligible restorations exactly once."""

        # Authority-bearing evidence is constructed only from fresh views over
        # the sealed raster bytes.  The public working arrays are intentionally
        # not an authority: callers may replace them for non-authoritative work,
        # but that replacement must never affect reconciliation evidence.
        self.source_gray = self._source_gray_authority.working_array()
        self.source_binary = self._source_binary_authority.working_array()

        original_restoration_candidates = tuple(restoration_candidates)
        original_restoration_counts = Counter(
            _acceptance_identity_key(line)
            for line in original_restoration_candidates
        )
        explicit_restoration_counts = Counter(
            _acceptance_identity_key(line) for line in accepted_restorations
        )
        if any(
            count != 1 or original_restoration_counts.get(identity) != 1
            for identity, count in explicit_restoration_counts.items()
        ):
            raise AssertionError(
                "Accepted-restoration snapshot must correspond one-to-one with the input candidate population"
            )
        authorizations = [
            self.authorize_restoration(line) for line in accepted_restorations
        ]
        authorizations.extend(accepted_restoration_authorizations)
        source_scope_digest = _source_scope_digest(
            self._source_gray_authority, self._source_binary_authority
        )
        authorization_by_identity: dict[str, ScopedRestorationAcceptance] = {}
        for authorization in authorizations:
            payload = {
                "stable_identity": authorization.stable_identity,
                "intervals": [list(item) for item in authorization.intervals],
                "source_scope_digest": authorization.source_scope_digest,
                "authority_source": authorization.authority_source,
                "version": authorization.version,
            }
            if (
                authorization.version != SCOPED_ACCEPTANCE_VERSION
                or authorization.source_scope_digest != source_scope_digest
                or authorization.digest != _digest_payload(payload)
                or original_restoration_counts.get(authorization.stable_identity) != 1
                or authorization.stable_identity in authorization_by_identity
            ):
                raise AssertionError(
                    "Restoration acceptance authorization is invalid or outside the sealed source scope"
                )
            authorization_by_identity[authorization.stable_identity] = authorization

        scoped_restoration_candidates: list[LineSegment] = []
        accepted_restoration_lines: list[LineSegment] = []
        acceptance_by_key: dict[str, ScopedRestorationAcceptance] = {}
        for line in original_restoration_candidates:
            authorization = authorization_by_identity.get(
                _acceptance_identity_key(line)
            )
            if authorization is None:
                scoped_restoration_candidates.append(line)
                continue
            boundaries = sorted(
                {
                    0.0,
                    float(line.length),
                    *(value for interval in authorization.intervals for value in interval),
                }
            )
            for start, end in zip(boundaries, boundaries[1:]):
                if end <= start:
                    continue
                piece = _exact_subsegment(line, ParameterInterval(start, end))
                scoped_restoration_candidates.append(piece)
                if any(
                    accepted_start <= start and end <= accepted_end
                    for accepted_start, accepted_end in authorization.intervals
                ):
                    accepted_restoration_lines.append(piece)
                    acceptance_by_key[_line_identity_key(piece)] = authorization
        restoration_candidates = tuple(scoped_restoration_candidates)

        self.observe_route(
            main_candidates,
            route=RouteOrigin.MAIN,
            producer="post-filter-main-candidate",
        )
        self.observe_route(
            restoration_candidates,
            route=RouteOrigin.RESTORATION,
            producer="late-text-mask-restoration",
        )
        masks = _validated_ownership_masks(
            ownership_masks,
            shape=self.source_binary.shape,
        )
        main_identity_counts = Counter(
            _line_identity_key(line) for line in main_candidates
        )
        accepted_identity_counts = Counter(
            _line_identity_key(line) for line in accepted_main
        )
        invalid_accepted_members = [
            identity
            for identity, count in accepted_identity_counts.items()
            if count != 1 or main_identity_counts.get(identity) != 1
        ]
        if invalid_accepted_members:
            raise AssertionError(
                "Accepted-main snapshot must correspond one-to-one with the input candidate population"
            )
        accepted_restoration_lines = tuple(accepted_restoration_lines)
        accepted_restoration_keys = {
            _line_identity_key(line) for line in accepted_restoration_lines
        }
        accepted_main_keys = {_line_identity_key(line) for line in accepted_main}
        main_key_by_index = {
            index: _geometry_key(line) for index, line in enumerate(main_candidates)
        }
        downgrade_by_key: dict[str, list[dict[str, object]]] = {}
        for downgrade in ownership_downgrades:
            if downgrade.get("candidate_category") != "structural_line":
                continue
            candidate_index = int(downgrade.get("candidate_index", -1))
            key = main_key_by_index.get(candidate_index)
            if key is not None:
                downgrade_by_key.setdefault(key, []).append(dict(downgrade))

        # Freeze every authority-bearing input before any representation,
        # relation, gap, piece, or transaction ledger record is produced.
        route_ledger = {
            "observed": json.loads(json.dumps(self._observed)),
            "transformations": json.loads(json.dumps(self._transformations)),
            "consolidations": json.loads(json.dumps(self._consolidations)),
            "early_proposals": json.loads(json.dumps(self._early_proposals)),
            "prefilter_terminal": [
                {
                    "observation_key": key,
                    "disposition": value[0],
                    "reason": value[1],
                }
                for key, value in sorted(self._prefilter_terminal.items())
            ],
        }
        route_ledger_digest = _digest_payload(route_ledger)
        input_lines = [
            _line_payload(line)
            for line in tuple(main_candidates) + tuple(restoration_candidates)
        ]
        source_gray_snapshot = self._source_gray_authority.working_array()
        source_binary_snapshot = self._source_binary_authority.working_array()
        protected_snapshot = self.protected_mask.copy()
        protected_snapshot.setflags(write=False)
        ownership_snapshots: dict[str, np.ndarray] = {}
        for key, value in masks.items():
            snapshot_value = value.copy()
            snapshot_value.setflags(write=False)
            ownership_snapshots[key] = snapshot_value
        accepted_snapshot = [
            {
                "stable_identity": _line_identity_key(line),
                "line": _line_payload(line),
                "route": RouteOrigin.MAIN.value,
            }
            for line in accepted_main
        ]
        accepted_snapshot.extend(
            {
                "stable_identity": _line_identity_key(line),
                "line": _line_payload(line),
                "route": RouteOrigin.RESTORATION.value,
                "compatibility_source": acceptance_by_key[
                    _line_identity_key(line)
                ].authority_source,
                "reason_version": acceptance_by_key[
                    _line_identity_key(line)
                ].version,
                "authorization_digest": acceptance_by_key[
                    _line_identity_key(line)
                ].digest,
                "source_scope_digest": acceptance_by_key[
                    _line_identity_key(line)
                ].source_scope_digest,
            }
            for line in accepted_restoration_lines
        )
        route_ledger_json = json.dumps(
            route_ledger,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        authority_snapshot = {
            "source_gray_sha256": self._source_gray_authority.sha256,
            "source_binary_sha256": self._source_binary_authority.sha256,
            "source_shape": list(source_gray_snapshot.shape),
            "source_gray_snapshot_digest": self._source_gray_authority.digest,
            "source_binary_snapshot_digest": self._source_binary_authority.digest,
            "source_frame_id": SOURCE_FRAME_ID,
            "source_snapshot_version": SOURCE_SNAPSHOT_VERSION,
            "source_scope_digest": source_scope_digest,
            "raw_route_preparation_snapshot": json.loads(route_ledger_json),
            "input_candidates": input_lines,
            "accepted_members": accepted_snapshot,
            "ownership_masks": {
                key: hashlib.sha256(value.tobytes()).hexdigest()
                for key, value in sorted(ownership_snapshots.items())
            },
            "protection_sha256": hashlib.sha256(
                protected_snapshot.tobytes()
            ).hexdigest(),
            "ownership_downgrades": [dict(value) for value in ownership_downgrades],
        }
        evidence_cache = _ReconciliationEvidenceCache.create(
            _digest_payload(authority_snapshot),
            _digest_payload(accepted_snapshot),
            POLICY_VERSION,
            GAP_EXTENT_POLICY_VERSION,
        )
        validation_context = _ValidationContext(
            input_lines=tuple(main_candidates) + tuple(restoration_candidates),
            main_candidates=tuple(main_candidates),
            restoration_candidates=tuple(restoration_candidates),
            accepted_main=tuple(accepted_main),
            accepted_restorations=accepted_restoration_lines,
            source_gray=source_gray_snapshot,
            source_binary=source_binary_snapshot,
            protected_mask=protected_snapshot,
            ownership_masks=ownership_snapshots,
            route_ledger_json=route_ledger_json,
            authority_snapshot_digest=_digest_payload(authority_snapshot),
            accepted_snapshot_digest=_digest_payload(accepted_snapshot),
            source_gray_sha256=str(authority_snapshot["source_gray_sha256"]),
            source_binary_sha256=str(authority_snapshot["source_binary_sha256"]),
            source_gray_authority=self._source_gray_authority,
            source_binary_authority=self._source_binary_authority,
            source_scope_digest=source_scope_digest,
            scale=self.scale,
            evidence_cache=evidence_cache,
        )

        representations: list[dict[str, object]] = []
        dispositions: dict[str, dict[str, object]] = {}
        evidence: list[dict[str, object]] = []
        cells: list[dict[str, object]] = []
        endpoints: list[dict[str, object]] = []
        pieces: list[dict[str, object]] = []
        relation_cells: list[RelationCell] = []
        gap_certificates: dict[str, tuple[dict[str, object], ...]] = {}
        final_lines: list[LineSegment] = []
        final_piece_ids: list[str] = []

        ordered: list[tuple[RouteOrigin, LineSegment, str]] = []
        for line in sorted(main_candidates, key=_stable_line_key):
            state = (
                "MAIN_ACCEPTED"
                if _line_identity_key(line) in accepted_main_keys
                else "MAIN_REJECTED"
            )
            ordered.append((RouteOrigin.MAIN, line, state))
        for line in sorted(restoration_candidates, key=_stable_line_key):
            state = (
                "LEGACY_RESTORATION_ACCEPTED"
                if _line_identity_key(line) in accepted_restoration_keys
                else "RESTORATION_PROPOSED"
            )
            ordered.append((RouteOrigin.RESTORATION, line, state))

        observation_representation_ids: dict[str, str] = {}
        for observation_index, observation in enumerate(self._observed):
            observation_line = _line_from_payload(observation["line"])
            observation_route = RouteOrigin(str(observation["route"]))
            observation_representation_ids[str(observation["observation_id"])] = (
                _representation_id(
                    observation_route,
                    str(observation["observation_id"]),
                    observation_index,
                    observation_line.source_ids,
                )
            )

        transformation_by_child = {
            str(item["child_observation_id"]): item
            for item in self._transformations
        }

        def lineage_observation_ids(observation_id: str) -> tuple[str, ...]:
            output: list[str] = []
            cursor = observation_id
            seen: set[str] = set()
            while cursor in transformation_by_child:
                if cursor in seen:
                    raise AssertionError("Transformation lineage contains a cycle")
                seen.add(cursor)
                parent_id = str(
                    transformation_by_child[cursor]["parent_observation_id"]
                )
                output.append(parent_id)
                cursor = parent_id
            return tuple(output)

        active: list[
            tuple[
                RouteOrigin,
                LineSegment,
                str,
                str,
                str,
                tuple[str, ...],
            ]
        ] = []
        for route, line, state in ordered:
            observation_key = _observation_key(route, line)
            observation = next(
                item
                for item in self._observed
                if str(item["observation_key"]) == observation_key
            )
            observation_id = str(observation["observation_id"])
            representation_id = observation_representation_ids[observation_id]
            lineage_ids = lineage_observation_ids(observation_id)
            parent_observation_ids = lineage_ids[:1]
            active.append(
                (
                    route,
                    line,
                    state,
                    representation_id,
                    observation_id,
                    parent_observation_ids,
                )
            )
            support = _source_support_intervals(
                line,
                gray=self.source_gray,
                binary=self.source_binary,
            )
            gap_certificates[representation_id] = _source_visible_gap_certificates(
                line,
                representation_id=representation_id,
                gray=self.source_gray,
                binary=self.source_binary,
                protected_mask=self.protected_mask,
                ownership_masks=masks,
                evidence_cache=evidence_cache,
            )
            endpoint_records = _endpoint_records(representation_id, line)
            endpoints.extend(endpoint_records)
            transform = transformation_by_child.get(observation_id)
            root_observation_id = (
                lineage_ids[-1] if lineage_ids else observation_id
            )
            representations.append(
                {
                    "representation_id": representation_id,
                    "observation_id": observation_id,
                    "parent_representation_id": (
                        observation_representation_ids[parent_observation_ids[0]]
                        if parent_observation_ids
                        else None
                    ),
                    "root_observation_id": root_observation_id,
                    "operation": (
                        str(transform["operation"])
                        if transform is not None
                        else LineageOperation.ORIGINAL_OBSERVATION.value
                    ),
                    "parent_parameter_interval": (
                        list(transform["parent_parameter_interval"])
                        if transform is not None
                        else [0.0, float(line.length)]
                    ),
                    "child_parameter_interval": (
                        list(transform["child_parameter_interval"])
                        if transform is not None
                        else [0.0, float(line.length)]
                    ),
                    "parent_trajectory_basis": (
                        dict(transform["parent_trajectory_basis"])
                        if transform is not None
                        else _trajectory_basis_payload(line)
                    ),
                    "route_transition": (
                        str(transform["route_transition"])
                        if transform is not None
                        else f"{route.value}->{route.value}"
                    ),
                    "transformation_id": (
                        str(transform["transformation_id"])
                        if transform is not None
                        else None
                    ),
                    "route_origin": route.value,
                    "route_producer": (
                        "structural-main"
                        if route is RouteOrigin.MAIN
                        else "text-mask-restoration"
                    ),
                    "parent_ids": [
                        observation_representation_ids[parent_id]
                        for parent_id in parent_observation_ids
                    ],
                    "source_ids": list(line.source_ids),
                    "history": list(line.history),
                    "geometry_px": _geometry_payload(line),
                    "observation_interval": ParameterInterval(
                        0.0, line.length
                    ).payload(),
                    "source_support_intervals": [
                        interval.payload((f"support:{representation_id}",))
                        for interval in support
                    ],
                    "trajectory_evidence_refs": [f"support:{representation_id}"],
                    "endpoint_ids": [
                        str(item["endpoint_id"]) for item in endpoint_records
                    ],
                    "structural_obligation_ids": [],
                    "ownership_state": state,
                    "ownership_evidence_refs": [f"ownership:{representation_id}"],
                    "terminal_reason": "PENDING_FINAL_RECONCILIATION",
                }
            )
            evidence.append(
                _support_evidence_payload(
                    representation_id,
                    line,
                    support,
                    self.source_gray,
                )
            )
            evidence.append(
                _ownership_evidence_payload(
                    representation_id,
                    line,
                    state=state,
                    downgrades=downgrade_by_key.get(_geometry_key(line), ()),
                )
            )

        rejected_observation_ids = {
            observation_id
            for _route, _line, state, _rid, observation_id, _parents in active
            if state == "MAIN_REJECTED"
        }
        protection_rejected_observation_ids = {
            str(item["observation_id"])
            for item in self._observed
            if self._prefilter_terminal.get(str(item["observation_key"]), (None,))[0]
            == TerminalDisposition.REJECTED_PROTECTION.value
        }
        direct_rejection_by_observation = {
            observation_id: TerminalDisposition.REJECTED_OWNERSHIP.value
            for observation_id in rejected_observation_ids
        }
        direct_rejection_by_observation.update(
            {
                observation_id: TerminalDisposition.REJECTED_PROTECTION.value
                for observation_id in protection_rejected_observation_ids
            }
        )
        observed_line_by_id = {
            str(item["observation_id"]): _line_from_payload(item["line"])
            for item in self._observed
            if isinstance(item.get("line"), Mapping)
        }
        consolidation_by_result = {
            str(item["result_observation_id"]): item
            for item in self._consolidations
        }

        def map_scope(
            scope: ParameterInterval,
            source_interval: ParameterInterval,
            target_interval: ParameterInterval,
        ) -> ParameterInterval | None:
            overlap_start = max(scope.start, source_interval.start)
            overlap_end = min(scope.end, source_interval.end)
            if overlap_end <= overlap_start or source_interval.length <= 0.0:
                return None
            ratio = target_interval.length / source_interval.length
            return ParameterInterval(
                target_interval.start
                + (overlap_start - source_interval.start) * ratio,
                target_interval.start
                + (overlap_end - source_interval.start) * ratio,
            )

        def inherited_rejection_scopes(
            observation_id: str,
            active_path: frozenset[str] = frozenset(),
        ) -> tuple[tuple[ParameterInterval, str, str], ...]:
            if observation_id in active_path:
                raise AssertionError("Unified ancestry graph contains a cycle")
            line = observed_line_by_id.get(observation_id)
            if line is None:
                return ()
            direct = direct_rejection_by_observation.get(observation_id)
            if direct is not None:
                return ((ParameterInterval(0.0, line.length), direct, observation_id),)
            next_path = active_path | {observation_id}
            output: list[tuple[ParameterInterval, str, str]] = []
            transform = transformation_by_child.get(observation_id)
            if transform is not None:
                parent_id = str(transform["parent_observation_id"])
                parent_values = transform["parent_parameter_interval"]
                child_values = transform["child_parameter_interval"]
                parent_interval = ParameterInterval(
                    float(parent_values[0]), float(parent_values[1])
                )
                child_interval = ParameterInterval(
                    float(child_values[0]), float(child_values[1])
                )
                for scope, disposition, root_id in inherited_rejection_scopes(
                    parent_id, next_path
                ):
                    mapped = map_scope(scope, parent_interval, child_interval)
                    if mapped is not None:
                        output.append((mapped, disposition, root_id))
            consolidation = consolidation_by_result.get(observation_id)
            if consolidation is not None:
                for mapping in consolidation.get("parent_interval_mappings", ()):
                    if not isinstance(mapping, Mapping):
                        continue
                    parent_id = str(mapping["parent_observation_id"])
                    parent_values = mapping["parent_parameter_interval"]
                    result_values = mapping["result_parameter_interval"]
                    parent_interval = ParameterInterval(
                        float(parent_values[0]), float(parent_values[1])
                    )
                    result_interval = ParameterInterval(
                        float(result_values[0]), float(result_values[1])
                    )
                    for scope, disposition, root_id in inherited_rejection_scopes(
                        parent_id, next_path
                    ):
                        mapped = map_scope(scope, parent_interval, result_interval)
                        if mapped is not None:
                            output.append((mapped, disposition, root_id))
            return tuple(output)

        retained: list[tuple[str, LineSegment]] = []
        retained_index = _RetainedCandidateIndex(scale=self.scale)
        for (
            route,
            line,
            ownership_state,
            representation_id,
            _observation_id_value,
            parent_observation_ids,
        ) in active:
            if ownership_state == "MAIN_REJECTED":
                dispositions[representation_id] = _disposition(
                    representation_id,
                    TerminalDisposition.REJECTED_OWNERSHIP.value,
                    (),
                    (),
                    "Explicit main ownership/arbitration rejection",
                )
                continue
            rejection_scopes = inherited_rejection_scopes(_observation_id_value)
            rejected_intervals = _merge_intervals(
                tuple(scope for scope, _disposition_value, _root_id in rejection_scopes)
            )

            supported = _source_support_intervals(
                line,
                gray=self.source_gray,
                binary=self.source_binary,
            )
            if not supported:
                disposition = (
                    TerminalDisposition.RETAINED.value
                    if ownership_state != "RESTORATION_PROPOSED"
                    else TerminalDisposition.BLOCKED.value
                )
                reason = (
                    "Accepted input retained because source relation is unresolved"
                    if disposition == TerminalDisposition.RETAINED.value
                    else "Fresh restoration has no original-source support interval"
                )
                if disposition == TerminalDisposition.RETAINED.value:
                    piece_id = _piece_id(representation_id, 0, 0.0, line.length)
                    final_lines.append(line)
                    retained.append((piece_id, line))
                    retained_index.add(piece_id, line)
                    final_piece_ids.append(piece_id)
                    pieces.append(
                        _piece_payload(
                            piece_id,
                            representation_id,
                            line,
                            ParameterInterval(0.0, line.length),
                            parent_line=line,
                            action="EMIT",
                            claim_mode="UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT",
                            masks=masks,
                            protected_mask=self.protected_mask,
                            source_binary=self.source_binary,
                        )
                    )
                    replacement_ids = (piece_id,)
                else:
                    replacement_ids = ()
                dispositions[representation_id] = _disposition(
                    representation_id,
                    disposition,
                    replacement_ids,
                    (),
                    reason,
                )
                continue

            removable: list[ParameterInterval] = []
            removal_keeper_ids: set[str] = set()
            keeper_candidates = (
                ()
                if _has_structural_endpoint_obligation(
                    line,
                    gray=self.source_gray,
                    binary=self.source_binary,
                )
                or not _has_direct_trajectory_source(
                    line,
                    gray=self.source_gray,
                    binary=self.source_binary,
                )
                else retained_index.query(line)
            )
            for retained_id, keeper in keeper_candidates:
                certified = _certify_pair_cells(
                    keeper,
                    line,
                    left_id=retained_id,
                    right_id=representation_id,
                    gray=self.source_gray,
                    binary=self.source_binary,
                    scale=self.scale,
                    protected_mask=self.protected_mask,
                    ownership_masks=masks,
                    right_ownership_state=ownership_state,
                    evidence_cache=evidence_cache,
                )
                for cell in certified:
                    relation_cells.append(cell)
                    cells.append(cell.payload(len(cells)))
                    evidence.append(_relation_evidence_payload(cell, len(evidence)))
                    if (
                        cell.relation is Relation.SAME_VISIBLE_STROKE_SUPPORTED
                        and cell.endpoint_obligations_clear
                    ):
                        removable.append(cell.right_interval)
                        removal_keeper_ids.add(cell.left_id)

            removed = _intersect_interval_sets(supported, removable)
            accepted_original = ownership_state != "RESTORATION_PROPOSED"
            authorized_absent = (
                [
                    _interval_from_v2_payload(item["certified_absent_interval"])
                    for item in gap_certificates.get(representation_id, ())
                ]
                if ownership_state == "LEGACY_RESTORATION_ACCEPTED"
                else []
            )
            # Source sampling authorizes removal; it never limits the extent of
            # an already accepted representation.  Preserve every unsampled or
            # UNKNOWN portion unless a certified SAME cell removes it or the
            # reviewed V2 source-gap policy explicitly accounts it as absent.
            if accepted_original:
                novel = _subtract_intervals(
                    (ParameterInterval(0.0, line.length),),
                    (*removed, *authorized_absent, *rejected_intervals),
                )
            else:
                novel = _subtract_intervals(supported, (*removed, *rejected_intervals))
            if not removed:
                if ownership_state == "RESTORATION_PROPOSED":
                    # A fresh restoration must independently establish both a
                    # source-supported trajectory and an undisputed ownership
                    # claim.  Geometry or the old scalar coverage helper is not
                    # admission authority.
                    novel = _subtract_intervals(supported, rejected_intervals)
                else:
                    novel = _subtract_intervals(
                        (ParameterInterval(0.0, line.length),),
                        (*authorized_absent, *rejected_intervals),
                    )

            legacy = ownership_state == "LEGACY_RESTORATION_ACCEPTED"
            fresh = ownership_state == "RESTORATION_PROPOSED"
            accepted_parent = route is RouteOrigin.MAIN or legacy
            rollback_reason: str | None = None
            if accepted_parent and (removed or authorized_absent or rejected_intervals):
                for interval in novel:
                    piece_line = _exact_subsegment(line, interval)
                    delta = _claim_delta_measurements(
                        line,
                        piece_line,
                        protected_mask=self.protected_mask,
                        source_binary=self.source_binary,
                    )
                    if (
                        delta["new_source_pixels"] > 0
                        or delta["new_protected_source_pixels"] > 0
                    ):
                        rollback_reason = (
                            "Accepted-parent reduction changed the exact raster claim"
                        )
                        break
                    if piece_line.length <= DXF_MIN_LINE_LENGTH_PX:
                        rollback_reason = (
                            "Required accepted-parent tail cannot survive DXF export"
                        )
                        break
            if rollback_reason is not None:
                if authorized_absent or rejected_intervals:
                    raise AssertionError(
                        "BLOCK_AND_REVIEW: a certified source-visible gap or explicit "
                        "rejection cannot be bridged by accepted-parent rollback"
                    )
                # Atomic failure action: no partial reduction of an accepted
                # transaction is committed.
                novel = [ParameterInterval(0.0, line.length)]
                removed = []

            emitted_ids: list[str] = []
            blocked_intervals: list[ParameterInterval] = []
            emitted_intervals: list[ParameterInterval] = []
            for piece_index, interval in enumerate(novel):
                piece_line = _exact_subsegment(line, interval)
                claim = _claim_measurements(
                    piece_line,
                    masks=masks,
                    protected_mask=self.protected_mask,
                    source_binary=self.source_binary,
                )
                unrepresentable = piece_line.length <= DXF_MIN_LINE_LENGTH_PX
                disputed = (
                    claim["protected_source_pixels"] > 0
                    or claim["semantic_conflict_source_pixels"] > 0
                    or claim["residual_source_pixels"] > 0
                    or unrepresentable
                )
                if fresh and disputed:
                    blocked_intervals.append(interval)
                    piece_id = _piece_id(
                        representation_id,
                        piece_index,
                        interval.start,
                        interval.end,
                    )
                    pieces.append(
                        _piece_payload(
                            piece_id,
                            representation_id,
                            piece_line,
                            interval,
                            parent_line=line,
                            action="BLOCK_AND_REVIEW",
                            claim_mode="NEW_RESTORATION_ADMISSION",
                            masks=masks,
                            protected_mask=self.protected_mask,
                            source_binary=self.source_binary,
                        )
                    )
                    continue
                piece_id = _piece_id(
                    representation_id,
                    piece_index,
                    interval.start,
                    interval.end,
                )
                output_line = piece_line.copy(
                    history=tuple(
                        dict.fromkeys(
                            (
                                *piece_line.history,
                                f"source_stroke_piece:{piece_id}",
                                PIECE_HISTORY,
                            )
                        )
                    )
                )
                final_lines.append(output_line)
                retained.append((piece_id, output_line))
                retained_index.add(piece_id, output_line)
                final_piece_ids.append(piece_id)
                emitted_ids.append(piece_id)
                emitted_intervals.append(interval)
                pieces.append(
                    _piece_payload(
                        piece_id,
                        representation_id,
                        output_line,
                        interval,
                        parent_line=line,
                        action="EMIT",
                        claim_mode=(
                            "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
                            if legacy or route is RouteOrigin.MAIN
                            else "NEW_RESTORATION_ADMISSION"
                        ),
                        masks=masks,
                        protected_mask=self.protected_mask,
                        source_binary=self.source_binary,
                    )
                )

            for rejected_index, interval in enumerate(rejected_intervals):
                rejected_line = _exact_subsegment(line, interval)
                piece_id = _piece_id(
                    representation_id,
                    len(novel) + rejected_index,
                    interval.start,
                    interval.end,
                )
                pieces.append(
                    _piece_payload(
                        piece_id,
                        representation_id,
                        rejected_line,
                        interval,
                        parent_line=line,
                        action="BLOCK_AND_REVIEW",
                        claim_mode=(
                            "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
                            if accepted_parent
                            else "NEW_RESTORATION_ADMISSION"
                        ),
                        masks=masks,
                        protected_mask=self.protected_mask,
                        source_binary=self.source_binary,
                    )
                )

            if rejected_intervals and not emitted_ids and not removed and not authorized_absent:
                rejection_kinds = {value for _scope, value, _root in rejection_scopes}
                terminal = (
                    TerminalDisposition.REJECTED_PROTECTION.value
                    if TerminalDisposition.REJECTED_PROTECTION.value in rejection_kinds
                    else TerminalDisposition.REJECTED_OWNERSHIP.value
                )
                reason = "Explicit ancestry-mapped rejection covers the descendant claim"
            elif blocked_intervals and not emitted_ids:
                terminal = TerminalDisposition.BLOCKED.value
                reason = "Fresh disputed restoration admission blocked for review"
            elif blocked_intervals:
                terminal = TerminalDisposition.SPLIT.value
                reason = "Safe source-supported pieces emitted; disputed pieces blocked"
            elif removed and not emitted_ids:
                terminal = TerminalDisposition.SUPERSEDED_EQUIVALENT.value
                reason = "Every removed supported cell has an accepted keeper"
            elif removed or authorized_absent or rejected_intervals:
                terminal = TerminalDisposition.SPLIT.value
                reason = (
                    "Certified equivalent coverage and/or source-visible absence "
                    "accounted; all remaining accepted extent retained"
                )
            else:
                terminal = TerminalDisposition.RETAINED.value
                reason = (
                    rollback_reason
                    or "Distinct or unresolved relation preserved"
                )
            dispositions[representation_id] = _disposition(
                representation_id,
                terminal,
                tuple(emitted_ids),
                tuple(emitted_intervals or blocked_intervals),
                reason,
                removed_intervals=tuple(removed),
                retained_keeper_piece_ids=tuple(sorted(removal_keeper_ids)),
                rejected_intervals=tuple(rejected_intervals),
                rejected_root_observation_ids=tuple(
                    sorted({root for _scope, _value, root in rejection_scopes})
                ),
                rejected_scope_dispositions=tuple(
                    sorted({value for _scope, value, _root in rejection_scopes})
                ),
            )

        # Observations made before suppression can be filtered later.  They are
        # still terminal and auditable; they are never silently resurrected.
        all_observation_keys = {str(item["observation_key"]) for item in self._observed}
        represented_observation_ids = {
            observation_id
            for _route, _line, _state, _rid, observation_id, _parents in active
        }
        active_representations = tuple(representations)
        for observation in self._observed:
            key = str(observation["observation_key"])
            observation_id = str(observation["observation_id"])
            if observation_id in represented_observation_ids:
                continue
            route = RouteOrigin(str(observation["route"]))
            line_payload = observation["line"]
            if not isinstance(line_payload, dict):
                continue
            line = _line_from_payload(line_payload)
            representation_id = observation_representation_ids[observation_id]
            support = _source_support_intervals(
                line,
                gray=self.source_gray,
                binary=self.source_binary,
            )
            endpoint_records = _endpoint_records(representation_id, line)
            endpoints.extend(endpoint_records)
            representations.append(
                {
                    "representation_id": representation_id,
                    "observation_id": observation_id,
                    "parent_representation_id": (
                        observation_representation_ids[
                            str(transformation_by_child[observation_id]["parent_observation_id"])
                        ]
                        if observation_id in transformation_by_child
                        else None
                    ),
                    "root_observation_id": (
                        lineage_observation_ids(observation_id)[-1]
                        if lineage_observation_ids(observation_id)
                        else observation_id
                    ),
                    "operation": (
                        str(transformation_by_child[observation_id]["operation"])
                        if observation_id in transformation_by_child
                        else LineageOperation.ORIGINAL_OBSERVATION.value
                    ),
                    "parent_parameter_interval": (
                        list(
                            transformation_by_child[observation_id][
                                "parent_parameter_interval"
                            ]
                        )
                        if observation_id in transformation_by_child
                        else [0.0, float(line.length)]
                    ),
                    "child_parameter_interval": (
                        list(
                            transformation_by_child[observation_id][
                                "child_parameter_interval"
                            ]
                        )
                        if observation_id in transformation_by_child
                        else [0.0, float(line.length)]
                    ),
                    "parent_trajectory_basis": (
                        dict(
                            transformation_by_child[observation_id][
                                "parent_trajectory_basis"
                            ]
                        )
                        if observation_id in transformation_by_child
                        else _trajectory_basis_payload(line)
                    ),
                    "route_transition": (
                        str(transformation_by_child[observation_id]["route_transition"])
                        if observation_id in transformation_by_child
                        else f"{route.value}->{route.value}"
                    ),
                    "transformation_id": (
                        str(transformation_by_child[observation_id]["transformation_id"])
                        if observation_id in transformation_by_child
                        else None
                    ),
                    "route_origin": route.value,
                    "route_producer": str(observation["producer"]),
                    "parent_ids": (
                        [
                            observation_representation_ids[
                                str(
                                    transformation_by_child[observation_id][
                                        "parent_observation_id"
                                    ]
                                )
                            ]
                        ]
                        if observation_id in transformation_by_child
                        else []
                    ),
                    "source_ids": list(line.source_ids),
                    "history": list(line.history),
                    "geometry_px": _geometry_payload(line),
                    "observation_interval": ParameterInterval(
                        0.0, line.length
                    ).payload(),
                    "source_support_intervals": [
                        interval.payload((f"support:{representation_id}",))
                        for interval in support
                    ],
                    "trajectory_evidence_refs": [f"support:{representation_id}"],
                    "endpoint_ids": [
                        str(item["endpoint_id"]) for item in endpoint_records
                    ],
                    "structural_obligation_ids": [],
                    "ownership_state": "NOT_AT_FINAL_RECONCILIATION_BOUNDARY",
                    "ownership_evidence_refs": [],
                    "terminal_reason": "FILTERED_BEFORE_FINAL_RECONCILIATION",
                }
            )
            evidence.append(
                _support_evidence_payload(
                    representation_id,
                    line,
                    support,
                    self.source_gray,
                )
            )
            prefiltered = self._prefilter_terminal.get(key)
            consolidation_results = {
                str(item["result_observation_id"])
                for item in self._consolidations
                if observation_id
                in {
                    str(value)
                    for value in item["parent_observation_ids"]
                }
            }
            descendants = [
                item
                for item in active_representations
                if observation_id
                in lineage_observation_ids(str(item["observation_id"]))
                or str(item["observation_id"]) in consolidation_results
            ]
            replacement_ids = tuple(
                replacement_id
                for descendant in descendants
                for replacement_id in dispositions[
                    str(descendant["representation_id"])
                ]["replacement_piece_ids"]
            )
            dispositions[representation_id] = _disposition(
                representation_id,
                (
                    prefiltered[0]
                    if prefiltered
                    else (
                        TerminalDisposition.TRANSFORMED_CHILD.value
                        if descendants
                        else TerminalDisposition.ROUTE_DIVERTED.value
                    )
                ),
                replacement_ids,
                (),
                (
                    prefiltered[1]
                    if prefiltered
                    else (
                        "Lineage continued through a transformed final-boundary representation"
                        if descendants
                        else "Not eligible at mandatory final reconciliation boundary"
                    )
                ),
            )

        if all_observation_keys != {
            str(item["observation_key"]) for item in self._observed
        }:
            raise AssertionError("Observation ledger changed during reconciliation")

        for representation in representations:
            rid = str(representation["representation_id"])
            terminal = dispositions[rid]
            representation["terminal_reason"] = str(terminal["reason"])

        representation_by_id = {
            str(item["representation_id"]): item for item in representations
        }
        for piece in pieces:
            parent_id = str(piece["parent_id"])
            parent = representation_by_id[parent_id]
            interval = piece["parent_parameter_interval"]
            geometry = piece["geometry_px"]
            piece["representation_id"] = str(piece["piece_id"])
            piece["parent_representation_id"] = parent_id
            piece["root_observation_id"] = str(parent["root_observation_id"])
            piece["operation"] = LineageOperation.COVERAGE_SPLIT.value
            piece["parent_t0_t1"] = list(interval)
            piece["child_t0_t1"] = [
                0.0,
                float(
                    math.hypot(
                        float(geometry["end"][0]) - float(geometry["start"][0]),
                        float(geometry["end"][1]) - float(geometry["start"][1]),
                    )
                ),
            ]
            piece["parent_trajectory_basis"] = dict(
                parent["parent_trajectory_basis"]
            )
            piece["route_transition"] = (
                f"{parent['route_origin']}->{parent['route_origin']}"
            )
            piece["child_endpoint_types"] = [
                (
                    "ORIGINAL_OBSERVED_ENDPOINT"
                    if str(piece["start_endpoint_id"]).endswith(":start")
                    else "DERIVED_COVERAGE_CUT"
                ),
                (
                    "ORIGINAL_OBSERVED_ENDPOINT"
                    if str(piece["end_endpoint_id"]).endswith(":end")
                    else "DERIVED_COVERAGE_CUT"
                ),
            ]
            piece["actual_derived_cut_coordinates"] = [
                list(geometry["start"]),
                list(geometry["end"]),
            ]

        endpoint_ids = {str(item["endpoint_id"]) for item in endpoints}
        for piece in pieces:
            geometry = piece["geometry_px"]
            interval = piece["interval"]
            if not isinstance(geometry, Mapping) or not isinstance(interval, Mapping):
                raise AssertionError("Invalid reconciliation piece payload")
            for side, point, parameter in (
                ("start", geometry["start"], interval["start"]),
                ("end", geometry["end"], interval["end"]),
            ):
                endpoint_id = str(piece[f"{side}_endpoint_id"])
                if endpoint_id in endpoint_ids:
                    continue
                endpoints.append(
                    {
                        "endpoint_id": endpoint_id,
                        "representation_id": str(piece["parent_id"]),
                        "point_px": [float(point[0]), float(point[1])],
                        "parameter": float(parameter),
                        "kind": "DERIVED_COVERAGE_CUT",
                        "independent_editable_obligation": "NO_WITH_EVIDENCE",
                        "evidence_refs": list(piece["support_evidence_refs"]),
                        "disposition": "RETAIN_AS_GEOMETRY",
                    }
                )
                endpoint_ids.add(endpoint_id)

        for proposal in self._early_proposals:
            evidence.append(
                {
                    "evidence_id": str(proposal["proposal_id"]),
                    "kind": "ROUTE_DECISION",
                    "artifact": "runtime-main-suppression-proposal",
                    "sha256": hashlib.sha256(
                        json.dumps(proposal, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    "roi_px": [0, 0, 0, 0],
                    "producer_version": POLICY_VERSION,
                    "intervals": [],
                    "result": "UNKNOWN",
                    "measurements": proposal,
                    "limitations": [
                        "Proposal has no destructive authority before final reconciliation"
                    ],
                }
            )
        for piece in pieces:
            inherited_pixels = int(piece["inherited_protected_source_claim_pixels"])
            if inherited_pixels <= 0:
                continue
            evidence_id = f"protected-contact:{piece['piece_id']}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "kind": "INHERITED_SOURCE_CLAIM",
                    "artifact": "runtime-connection-protection-mask",
                    "sha256": hashlib.sha256(self.protected_mask.tobytes()).hexdigest(),
                    "roi_px": [
                        0,
                        0,
                        int(self.protected_mask.shape[1]),
                        int(self.protected_mask.shape[0]),
                    ],
                    "producer_version": POLICY_VERSION,
                    "intervals": [piece["interval"]],
                    "result": "SUPPORTED",
                    "measurements": {
                        "inherited_protected_source_claim_pixels": inherited_pixels,
                        "new_protected_source_claim_pixels": 0,
                    },
                    "limitations": [
                        "Inherited accepted contact does not authorize a fresh source claim"
                    ],
                }
            )

        input_digest = _lines_digest(
            tuple(main_candidates) + tuple(restoration_candidates)
        )
        final_tuple = tuple(final_lines)
        final_digest = _lines_digest(final_tuple)
        supersession = [
            dispositions[str(item["representation_id"])] for item in representations
        ]
        operation = _transaction_operation(supersession)
        source_hash = hashlib.sha256(self.source_gray.tobytes()).hexdigest()
        evidence.append(
            {
                "evidence_id": f"route-ledger:{route_ledger_digest[:20]}",
                "kind": "ROUTE_DECISION",
                "artifact": "runtime-route-ledger-snapshot",
                "sha256": _digest_payload(
                    {"route_ledger": route_ledger, "input_lines": input_lines}
                ),
                "roi_px": [0, 0, 0, 0],
                "producer_version": POLICY_VERSION,
                "intervals": [],
                "result": "SUPPORTED",
                "measurements": {
                    "route_ledger": route_ledger,
                    "input_lines": input_lines,
                    "committed_final_set_digest": final_digest,
                    "committed_final_lines": [
                        _line_payload(line) for line in final_tuple
                    ],
                },
                "limitations": [
                    "Immutable route/input evidence; not relation authority"
                ],
            }
        )
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "record_id": f"reconciliation-{input_digest[:16]}",
            "source_image_sha256": source_hash,
            "producer_head": "runtime",
            "policy_version": POLICY_VERSION,
            "input_set_digest": input_digest,
            "final_main_set_digest": _lines_digest(tuple(accepted_main)),
            "route_ledger_digest": route_ledger_digest,
            "physical_instance_assertion": False,
            "basis": _ledger_basis(representations),
            "representations": representations,
            "evidence": evidence,
            "cells": cells,
            "endpoints": endpoints,
            "pieces": pieces,
            "supersession_ledger": supersession,
            "transaction": {
                "state": "PROPOSED",
                "operation": operation.value,
                "lossless_supported_extent": False,
                "lossless_endpoint_obligations": False,
                "no_new_protected_source_claim": False,
                "final_set_digest_validated": False,
                "reason": (
                    "Interval-local source certificates consumed after MAIN "
                    "ownership; only exact parent subsegments were committed"
                ),
                "failure_action": (
                    "RETAIN_ACCEPTED_INPUTS_AND_BLOCK_NEW_DISPUTED_ADMISSIONS"
                ),
            },
        }
        provisional_extension = _build_gap_extent_v2_record(
            payload,
            base_ledger_digest="0" * 64,
            final_lines=final_tuple,
            final_piece_ids=tuple(final_piece_ids),
            gap_certificates=gap_certificates,
            context=validation_context,
        )
        _set_gap_extent_extension(payload, provisional_extension)
        preliminary_errors = _semantic_transaction_errors(
            payload,
            final_lines=final_tuple,
            final_piece_ids=tuple(final_piece_ids),
            expected_final_digest=final_digest,
            context=validation_context,
            check_v2_digest=False,
        )
        if preliminary_errors:
            raise AssertionError(
                "Reconciliation transaction failed semantic validation: "
                + "; ".join(preliminary_errors)
            )
        transaction = payload["transaction"]
        if not isinstance(transaction, dict):
            raise AssertionError("Invalid reconciliation transaction")
        transaction.update(
            {
                "lossless_supported_extent": True,
                "lossless_endpoint_obligations": True,
                "no_new_protected_source_claim": True,
                "final_set_digest_validated": True,
                "state": "VALIDATED",
            }
        )
        base_ledger_digest = _digest_payload(_payload_without_gap_extent(payload))
        extension = _build_gap_extent_v2_record(
            payload,
            base_ledger_digest=base_ledger_digest,
            final_lines=final_tuple,
            final_piece_ids=tuple(final_piece_ids),
            gap_certificates=gap_certificates,
            context=validation_context,
        )
        _set_gap_extent_extension(payload, extension)
        checks = _transaction_invariant_checks(
            payload,
            final_lines=final_tuple,
            final_piece_ids=tuple(final_piece_ids),
            expected_final_digest=final_digest,
            context=validation_context,
        )
        if not all(checks.values()):
            validation_errors = _semantic_transaction_errors(
                payload,
                final_lines=final_tuple,
                final_piece_ids=tuple(final_piece_ids),
                expected_final_digest=final_digest,
                context=validation_context,
            )
            raise AssertionError(
                "Reconciliation transaction failed semantic validation: "
                + "; ".join(validation_errors)
            )
        transaction.update(checks)
        internal_payload = payload
        payload = _closed_v1_payload(internal_payload)
        closed_base_ledger_digest = _digest_payload(
            _payload_without_gap_extent(payload)
        )
        closed_extension = _build_gap_extent_v2_record(
            internal_payload,
            base_ledger_digest=closed_base_ledger_digest,
            final_lines=final_tuple,
            final_piece_ids=tuple(final_piece_ids),
            gap_certificates=gap_certificates,
            context=validation_context,
        )
        _set_gap_extent_extension(payload, closed_extension)
        ledger_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        ledger_digest = hashlib.sha256(ledger_json.encode("utf-8")).hexdigest()
        sealed_validation_context = replace(
            validation_context,
            validated_ledger_digest=ledger_digest,
        )
        result = ReconciliationResult(
            lines=final_tuple,
            ledger_json=ledger_json,
            ledger_digest=ledger_digest,
            input_set_digest=input_digest,
            final_set_digest=final_digest,
            terminal_representation_ids=tuple(
                str(item["representation_id"])
                for item in payload["representations"]
            ),
            final_piece_ids=tuple(final_piece_ids),
            _validation_context=sealed_validation_context,
        )
        return result


class _RetainedCandidateIndex:
    """Conservative orientation/normal-band retrieval for expensive evidence."""

    def __init__(self, *, scale: float) -> None:
        self._limit = max(4.5, 4.5 * float(scale))
        self._bucket_size = self._limit
        self._entries: list[tuple[str, LineSegment]] = []
        self._buckets: dict[tuple[str, int], list[int]] = {}

    @staticmethod
    def _orientation(line: LineSegment) -> str | None:
        if line.length <= 1e-9:
            return None
        tangent = (line.p2 - line.p1) / line.length
        if abs(float(tangent[0])) >= math.cos(math.radians(4.0)):
            return "H"
        if abs(float(tangent[1])) >= math.cos(math.radians(4.0)):
            return "V"
        return None

    def _normal_bounds(self, line: LineSegment, orientation: str) -> tuple[float, float]:
        values = (
            (float(line.y1), float(line.y2))
            if orientation == "H"
            else (float(line.x1), float(line.x2))
        )
        return min(values), max(values)

    def _bucket_range(
        self,
        line: LineSegment,
        orientation: str,
        *,
        expansion: float,
    ) -> range:
        low, high = self._normal_bounds(line, orientation)
        first = int(math.floor((low - expansion) / self._bucket_size))
        last = int(math.floor((high + expansion) / self._bucket_size))
        return range(first, last + 1)

    def add(self, piece_id: str, line: LineSegment) -> None:
        index = len(self._entries)
        self._entries.append((piece_id, line))
        orientation = self._orientation(line)
        if orientation is None:
            return
        for bucket in self._bucket_range(line, orientation, expansion=0.0):
            self._buckets.setdefault((orientation, bucket), []).append(index)

    def query(
        self, line: LineSegment, *, include_non_axis: bool = True
    ) -> tuple[tuple[str, LineSegment], ...]:
        orientation = self._orientation(line)
        if orientation is None:
            return tuple(self._entries) if include_non_axis else ()
        indices: set[int] = set()
        for bucket in self._bucket_range(
            line,
            orientation,
            expansion=self._limit,
        ):
            indices.update(self._buckets.get((orientation, bucket), ()))
        # Non-axis observations are rare at this production boundary but are
        # always included so the index cannot turn a possible relation into a
        # false negative.
        if include_non_axis:
            indices.update(
                index
                for index, (_piece_id_value, candidate) in enumerate(self._entries)
                if self._orientation(candidate) is None
            )
        output: list[tuple[str, LineSegment]] = []
        for index in sorted(indices):
            piece_id, candidate = self._entries[index]
            axis = 0 if orientation == "H" else 1
            left = sorted((float(candidate.p1[axis]), float(candidate.p2[axis])))
            right = sorted((float(line.p1[axis]), float(line.p2[axis])))
            if min(left[1], right[1]) <= max(left[0], right[0]) + 1e-9:
                continue
            output.append((piece_id, candidate))
        return tuple(output)




def _payload_without_gap_extent(
    payload: Mapping[str, object],
) -> dict[str, object]:
    copied = json.loads(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )
    for item in copied.get("evidence", ()):
        if not isinstance(item, dict) or item.get("artifact") != "runtime-route-ledger-snapshot":
            continue
        measurements = item.get("measurements")
        if isinstance(measurements, dict):
            measurements.pop(GAP_EXTENT_MEASUREMENT_SLOT, None)
    return copied


def _set_gap_extent_extension(
    payload: Mapping[str, object],
    extension: Mapping[str, object],
) -> None:
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise AssertionError("Reconciliation evidence collection is missing")
    snapshot = next(
        (
            item
            for item in evidence
            if isinstance(item, dict)
            and item.get("artifact") == "runtime-route-ledger-snapshot"
        ),
        None,
    )
    measurements = snapshot.get("measurements") if isinstance(snapshot, dict) else None
    if not isinstance(measurements, dict):
        raise AssertionError("Reconciliation route snapshot measurements are missing")
    measurements[GAP_EXTENT_MEASUREMENT_SLOT] = dict(extension)


def _gap_extent_extension(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    evidence = payload.get("evidence")
    if not isinstance(evidence, Sequence):
        return None
    snapshot = next(
        (
            item
            for item in evidence
            if isinstance(item, Mapping)
            and item.get("artifact") == "runtime-route-ledger-snapshot"
        ),
        None,
    )
    measurements = snapshot.get("measurements") if isinstance(snapshot, Mapping) else None
    value = (
        measurements.get(GAP_EXTENT_MEASUREMENT_SLOT)
        if isinstance(measurements, Mapping)
        else None
    )
    return value if isinstance(value, Mapping) else None


def _closed_v1_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Project the internal transaction onto the authoritative closed V1 shape.

    Fine-grained V2 accounting remains in the approved measurement slot.  The
    internal producer model is deliberately not serialized as an unversioned
    extension of V1 representation, cell, piece, evidence, or supersession
    objects.
    """

    output = json.loads(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )
    representation_fields = {
        "representation_id",
        "route_origin",
        "route_producer",
        "parent_ids",
        "source_ids",
        "history",
        "geometry_px",
        "observation_interval",
        "source_support_intervals",
        "trajectory_evidence_refs",
        "endpoint_ids",
        "structural_obligation_ids",
        "ownership_state",
        "ownership_evidence_refs",
        "terminal_reason",
    }
    active_states = {
        "MAIN_ACCEPTED",
        "MAIN_REJECTED",
        "RESTORATION_PROPOSED",
        "LEGACY_RESTORATION_ACCEPTED",
    }
    active_representations = [
        item
        for item in output.get("representations", ())
        if isinstance(item, dict) and item.get("ownership_state") in active_states
    ]
    active_ids = {str(item["representation_id"]) for item in active_representations}
    output["representations"] = [
        {
            key: (
                [value for value in item[key] if str(value) in active_ids]
                if key == "parent_ids"
                else item[key]
            )
            for key in representation_fields
        }
        for item in active_representations
    ]

    allowed_evidence_kinds = {
        "RAW_SOURCE_CROP",
        "SOURCE_BAND_RUNS",
        "TRAJECTORY_BINDING",
        "LIGHT_GAP",
        "INDEPENDENT_TERMINATION",
        "STRUCTURAL_ATTACHMENT",
        "PROTECTED_SOURCE",
        "OWNERSHIP_DECISION",
        "ROUTE_DECISION",
        "INHERITED_SOURCE_CLAIM",
        "OBSERVATION_FRONTIER",
        "UNCERTAINTY",
    }
    output["evidence"] = [
        item
        for item in output.get("evidence", ())
        if isinstance(item, dict) and item.get("kind") in allowed_evidence_kinds
    ]

    cell_fields = {
        "cell_id",
        "members",
        "interval",
        "relation",
        "positive_evidence_refs",
        "negative_evidence_refs",
        "endpoint_obligations_clear",
        "operation",
        "retained_ids",
        "novel_intervals",
        "reason",
    }
    output["cells"] = [
        {key: item[key] for key in cell_fields}
        for item in output.get("cells", ())
        if isinstance(item, dict)
        and any(str(value) in active_ids for value in item.get("members", ()))
    ]

    piece_fields = {
        "piece_id",
        "parent_id",
        "parent_parameter_interval",
        "interval",
        "geometry_px",
        "source_ids",
        "history",
        "start_endpoint_id",
        "end_endpoint_id",
        "support_evidence_refs",
        "claim_mode",
        "new_source_claim_pixels",
        "new_protected_source_claim_pixels",
        "inherited_protected_source_claim_pixels",
        "inherited_contact_evidence_refs",
        "action",
    }
    output["pieces"] = [
        {key: item[key] for key in piece_fields}
        for item in output.get("pieces", ())
        if isinstance(item, dict) and str(item.get("parent_id")) in active_ids
    ]
    piece_ids = {str(item["piece_id"]) for item in output["pieces"]}
    output["endpoints"] = [
        item
        for item in output.get("endpoints", ())
        if isinstance(item, dict)
        and str(item.get("representation_id")) in active_ids
    ]

    disposition_map = {
        TerminalDisposition.RETAINED.value: "RETAINED",
        TerminalDisposition.SUPERSEDED_EQUIVALENT.value: "EQUIVALENT_INTERVAL_SUPERSEDED",
        TerminalDisposition.SPLIT.value: "SPLIT",
        TerminalDisposition.BLOCKED.value: "BLOCKED",
        TerminalDisposition.REJECTED_OWNERSHIP.value: "OWNERSHIP_REJECTED",
        TerminalDisposition.REJECTED_PROTECTION.value: "BLOCKED",
        TerminalDisposition.ROUTE_DIVERTED.value: "BLOCKED",
        TerminalDisposition.TRANSFORMED_CHILD.value: "BLOCKED",
    }
    output["supersession_ledger"] = [
        {
            "representation_id": str(item["representation_id"]),
            "disposition": disposition_map[str(item["disposition"])],
            "replacement_piece_ids": [
                str(value)
                for value in item.get("replacement_piece_ids", ())
                if str(value) in piece_ids
            ],
            "intervals": list(item.get("intervals", ())),
            "reason": str(item.get("reason", "")),
        }
        for item in output.get("supersession_ledger", ())
        if isinstance(item, dict) and str(item.get("representation_id")) in active_ids
    ]
    return output


def _interval_covers(
    outer: ParameterInterval,
    inner: ParameterInterval,
    *,
    tolerance: float = 1e-9,
) -> bool:
    return outer.start <= inner.start + tolerance and outer.end >= inner.end - tolerance


def _equivalent_cover_for_interval(
    parent_id: str,
    interval: ParameterInterval,
    cells: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    for cell in cells:
        if (
            parent_id not in cell.get("members", ())
            or cell.get("relation") != Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
            or not cell.get("endpoint_obligations_clear")
            or not isinstance(cell.get("interval"), Mapping)
            or not _interval_covers(_interval_from_v2_payload(cell["interval"]), interval)
        ):
            continue
        keeper_id = str(next(iter(cell.get("retained_ids", ())), ""))
        member_intervals = cell.get("member_intervals")
        if not keeper_id or not isinstance(member_intervals, Mapping):
            continue
        keeper_payload = member_intervals.get(keeper_id)
        parent_payload = member_intervals.get(parent_id)
        if not isinstance(keeper_payload, Mapping) or not isinstance(parent_payload, Mapping):
            continue
        keeper_base = _interval_from_v2_payload(keeper_payload)
        parent_base = _interval_from_v2_payload(parent_payload)
        if parent_base.length <= 0.0:
            continue
        ratio = keeper_base.length / parent_base.length
        mapped = ParameterInterval(
            keeper_base.start + (interval.start - parent_base.start) * ratio,
            keeper_base.start + (interval.end - parent_base.start) * ratio,
        )
        return {
            "keeper_piece_id": keeper_id,
            "parent_interval": _v2_interval_payload(interval),
            "keeper_interval": _v2_interval_payload(mapped),
            "certificate_ref": str(
                next(iter(cell.get("positive_evidence_refs", ())), "")
            ),
        }
    return None


def _build_gap_extent_v2_record(
    payload: Mapping[str, object],
    *,
    base_ledger_digest: str,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    gap_certificates: Mapping[str, Sequence[Mapping[str, object]]],
    context: _ValidationContext,
) -> dict[str, object]:
    representations = [
        item
        for item in payload.get("representations", ())
        if isinstance(item, Mapping)
        and item.get("ownership_state")
        in {
            "MAIN_ACCEPTED",
            "MAIN_REJECTED",
            "LEGACY_RESTORATION_ACCEPTED",
            "RESTORATION_PROPOSED",
        }
    ]
    v1_pieces = [item for item in payload.get("pieces", ()) if isinstance(item, Mapping)]
    emitted_by_parent: dict[str, list[Mapping[str, object]]] = {}
    for piece in v1_pieces:
        if piece.get("action") == "EMIT":
            emitted_by_parent.setdefault(str(piece.get("parent_id")), []).append(piece)
    terminal_by_id = {
        str(item.get("representation_id")): item
        for item in payload.get("supersession_ledger", ())
        if isinstance(item, Mapping)
    }
    v1_cells = [item for item in payload.get("cells", ()) if isinstance(item, Mapping)]
    source_hash = str(payload["source_image_sha256"])
    source_artifact = {'uri': 'runtime://original-unclosed-source-gray', 'sha256': source_hash, 'role': 'ORIGINAL_UNCLOSED_SOURCE_EVIDENCE'}
    policy_sha = hashlib.sha256(GAP_EXTENT_POLICY_VERSION.encode()).hexdigest()
    provenance = {'uri': 'runtime://source-faithful-gap-policy-v2', 'sha256': policy_sha, 'role': 'POLICY_PROVENANCE'}
    v2_evidence: list[dict[str, object]] = []
    authorizations: list[dict[str, object]] = []
    parents: list[dict[str, object]] = []
    endpoint_obligations: list[dict[str, object]] = []
    gap_observations: list[dict[str, object]] = []
    extension_pieces: list[dict[str, object]] = []
    evidence_collection = payload.get("evidence")
    if not isinstance(evidence_collection, list):
        raise AssertionError("V1 evidence collection is missing")

    # One immutable route snapshot serves every parent in this record. Keep
    # the decoded data private to this call; no page/configuration cache or
    # caller-owned mutable mapping is shared between record builds.
    route_snapshot = json.loads(context.route_ledger_json) if representations else {}
    for representation in representations:
        parent_id = str(representation["representation_id"])
        accepted = representation.get("ownership_state") in {
            "MAIN_ACCEPTED",
            "LEGACY_RESTORATION_ACCEPTED",
        }
        compatibility_acceptance = (
            representation.get("ownership_state")
            == "LEGACY_RESTORATION_ACCEPTED"
        )
        evidence_id = f"v2-source:{hashlib.sha256(parent_id.encode()).hexdigest()[:20]}"
        v2_evidence.append(
            {
                "evidence_id": evidence_id,
                "source_id": "source-image",
                "kind": "ACTUAL_TRAJECTORY_AND_PRODUCTION_CLAIM_FOOTPRINT",
                "result": "SUPPORTED",
                "role": "OBSERVATION",
                "artifacts": [source_artifact],
                "producer_version": GAP_EXTENT_POLICY_VERSION,
                "limitations": [
                    "Clear bounded absence only; ambiguous stations remain UNKNOWN"
                ],
            }
        )
        acceptance_auth = f"v2-acceptance:{hashlib.sha256(parent_id.encode()).hexdigest()[:20]}"
        authorizations.append(
            {
                "authorization_id": acceptance_auth,
                "kind": "ACCEPTANCE_SNAPSHOT" if accepted else "VALIDATED_SCOPED_POLICY",
                "policy_id": (
                    "legacy-acceptance-adapter-v1"
                    if compatibility_acceptance
                    else "source-stroke-gap-extent-v2"
                ),
                "policy_version": GAP_EXTENT_POLICY_VERSION,
                "policy_sha256": policy_sha,
                "source_id": "source-image",
                "target_ids": [parent_id],
                "permitted_actions": [
                    "RETAIN_ACCEPTED_EXTENT"
                    if accepted
                    else "BLOCK_UNRESOLVED_FRESH_ADMISSION"
                ],
                "evidence_refs": [evidence_id],
                "decision_provenance": (
                    {'uri': 'runtime://sealed-legacy-compatibility-acceptance-snapshot', 'sha256': context.accepted_snapshot_digest, 'role': 'TRUSTED_SCOPED_COMPATIBILITY_SOURCE'}
                    if compatibility_acceptance
                    else provenance
                ),
                "validity": "ACTIVE",
                "limitations": [
                    (
                        "Legacy compatibility is adapted into this sealed acceptance snapshot; history text is not authority"
                        if compatibility_acceptance
                        else "No damage repair, Junction mutation, or semantic reclassification"
                    )
                ],
            }
        )

        parent_line = _line_from_geometry_payload(
            representation["geometry_px"],
            source_ids=tuple(str(value) for value in representation.get("source_ids", ())),
            history=tuple(str(value) for value in representation.get("history", ())),
        )
        original = ParameterInterval(0.0, parent_line.length)
        direct_pieces = emitted_by_parent.get(parent_id, [])
        direct_intervals = [
            ParameterInterval(
                float(piece["parent_parameter_interval"][0]),
                float(piece["parent_parameter_interval"][1]),
            )
            for piece in direct_pieces
        ]
        terminal = terminal_by_id.get(parent_id, {})
        rejection_disposition = (
            str(terminal.get("disposition"))
            if terminal.get("disposition")
            in {
                TerminalDisposition.REJECTED_OWNERSHIP.value,
                TerminalDisposition.REJECTED_PROTECTION.value,
            }
            else None
        )
        rejected_scope_dispositions = {
            str(value)
            for value in terminal.get("rejected_scope_dispositions", ())
        }
        rejected_intervals = [
            _interval_from_v2_payload(item)
            for item in terminal.get("rejected_intervals", ())
        ]
        if rejection_disposition is None and rejected_intervals:
            rejection_disposition = (
                TerminalDisposition.REJECTED_PROTECTION.value
                if TerminalDisposition.REJECTED_PROTECTION.value
                in rejected_scope_dispositions
                else TerminalDisposition.REJECTED_OWNERSHIP.value
            )
        rejection_auth: str | None = None
        if rejection_disposition is not None:
            rejection_auth = f"v2-rejection:{hashlib.sha256(parent_id.encode()).hexdigest()[:20]}"
            authorizations.append(
                {
                    "authorization_id": rejection_auth,
                    "kind": (
                        "OWNERSHIP_DECISION"
                        if rejection_disposition == TerminalDisposition.REJECTED_OWNERSHIP.value
                        else "PROTECTION_DECISION"
                    ),
                    "policy_id": "inherited-reconciliation-rejection",
                    "policy_version": GAP_EXTENT_POLICY_VERSION,
                    "policy_sha256": policy_sha,
                    "source_id": "source-image",
                    "target_ids": [parent_id],
                    "permitted_actions": [rejection_disposition],
                    "evidence_refs": [evidence_id],
                    "decision_provenance": provenance,
                    "validity": "ACTIVE",
                    "limitations": ["Preserved inherited tombstone; not a new category decision"],
                }
            )
        equivalent_intervals = [
            _interval_from_v2_payload(item)
            for item in terminal.get("removed_intervals", ())
        ]
        parent_gaps = (
            list(gap_certificates.get(parent_id, ()))
            if representation.get("ownership_state")
            == "LEGACY_RESTORATION_ACCEPTED"
            else []
        )
        gap_intervals = [
            _interval_from_v2_payload(item["certified_absent_interval"])
            for item in parent_gaps
        ]
        support_intervals = [
            ParameterInterval(float(item["start"]), float(item["end"]))
            for item in representation.get("source_support_intervals", ())
            if isinstance(item, Mapping)
        ]
        boundaries = {original.start, original.end}
        for interval in (
            *direct_intervals,
            *equivalent_intervals,
            *gap_intervals,
            *rejected_intervals,
            *support_intervals,
        ):
            boundaries.add(max(original.start, interval.start))
            boundaries.add(min(original.end, interval.end))
        for relation in v1_cells:
            if (
                parent_id in relation.get("members", ())
                and relation.get("relation")
                == Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
                and isinstance(relation.get("interval"), Mapping)
            ):
                relation_interval = _interval_from_v2_payload(relation["interval"])
                boundaries.add(max(original.start, relation_interval.start))
                boundaries.add(min(original.end, relation_interval.end))
        ordered_boundaries = sorted(boundaries)
        partition: list[dict[str, object]] = []

        for gap in parent_gaps:
            gap_id = str(gap["gap_id"])
            gap_evidence_id = f"v2-gap-evidence:{gap_id}"
            gap_auth = f"v2-gap-authorization:{gap_id}"
            measurement_sha = str(gap["measurement_sha256"])
            measurement_artifact = {'uri': f'runtime://v2-gap-measurement/{gap_evidence_id}', 'sha256': measurement_sha, 'role': 'ACTUAL_TRAJECTORY_AND_FOOTPRINT_MEASUREMENT'}
            v2_evidence.append(
                {
                    "evidence_id": gap_evidence_id,
                    "source_id": "source-image",
                    "kind": "SOURCE_VISIBLE_GAP_OBSERVATION",
                    "result": "SUPPORTED",
                    "role": "MUTATION_SUPPORT",
                    "artifacts": [measurement_artifact],
                    "producer_version": GAP_EXTENT_POLICY_VERSION,
                    "limitations": ["Source-visible absence only; cause remains unknown"],
                }
            )
            authorizations.append(
                {
                    "authorization_id": gap_auth,
                    "kind": "SOURCE_FAITHFUL_GAP_POLICY",
                    "policy_id": "source-visible-gap-exclusion",
                    "policy_version": GAP_EXTENT_POLICY_VERSION,
                    "policy_sha256": policy_sha,
                    "source_id": "source-image",
                    "target_ids": [parent_id, gap_id],
                    "permitted_actions": ["PRESERVE_SOURCE_VISIBLE_GAP"],
                    "evidence_refs": [gap_evidence_id],
                    "decision_provenance": provenance,
                    "validity": "ACTIVE",
                    "limitations": ["NO_FILL_WITHOUT_SEPARATE_REPAIR_AUTHORITY"],
                }
            )
            gap_observations.append(
                {
                    "gap_id": gap_id,
                    "parent_id": parent_id,
                    "certified_absent_interval": dict(gap["certified_absent_interval"]),
                    "left_boundary_uncertainty_px": float(gap["left_boundary_uncertainty_px"]),
                    "right_boundary_uncertainty_px": float(gap["right_boundary_uncertainty_px"]),
                    "measurement_convention": str(gap["measurement_convention"]),
                    "observation": "SOURCE_VISIBLE_GAP",
                    "cause_hypothesis": "UNKNOWN_GAP",
                    "actual_trajectory_and_footprint_measurement": measurement_artifact,
                    "source_evidence_refs": [gap_evidence_id],
                    "authorization_ref": gap_auth,
                    "continuation_repair_refs": [],
                    "downstream_behavior": "NO_FILL_WITHOUT_SEPARATE_REPAIR_AUTHORITY",
                }
            )

        for cell_index, (start, end) in enumerate(
            zip(ordered_boundaries, ordered_boundaries[1:])
        ):
            if end <= start:
                continue
            interval = ParameterInterval(float(start), float(end))
            direct = [
                piece
                for piece, piece_interval in zip(direct_pieces, direct_intervals, strict=True)
                if _interval_covers(piece_interval, interval)
            ]
            equivalent = any(
                _interval_covers(value, interval) for value in equivalent_intervals
            )
            rejected = any(
                _interval_covers(value, interval) for value in rejected_intervals
            )
            gap_match = next(
                (
                    gap
                    for gap, gap_interval in zip(parent_gaps, gap_intervals, strict=True)
                    if _interval_covers(gap_interval, interval)
                ),
                None,
            )
            equivalent_cover: list[dict[str, object]] = []
            if equivalent:
                cover = _equivalent_cover_for_interval(parent_id, interval, v1_cells)
                if cover is not None:
                    equivalent_cover.append(cover)
                disposition = "SUPERSEDED_EQUIVALENT_REPRESENTATION"
                source_observation = "SOURCE_PRESENT"
                behavior = "USE_SURVIVING_EQUIVALENT"
                direct_ids: list[str] = []
                gap_id_value: str | None = None
                auth_ref = acceptance_auth
            elif rejected and rejection_disposition is not None and rejection_auth is not None:
                source_observation = (
                    "SOURCE_PRESENT"
                    if any(_interval_covers(value, interval) for value in support_intervals)
                    else "UNKNOWN"
                )
                disposition = rejection_disposition
                behavior = "PRESERVE_SOURCE_FALLBACK"
                direct_ids = []
                gap_id_value = None
                auth_ref = rejection_auth
            elif gap_match is not None:
                gap_id_value = str(gap_match["gap_id"])
                disposition = "SOURCE_VISIBLE_GAP"
                source_observation = "SOURCE_VISIBLE_GAP"
                behavior = "PRESERVE_GAP"
                direct_ids = []
                auth_ref = f"v2-gap-authorization:{gap_id_value}"
            elif direct:
                source_observation = (
                    "SOURCE_PRESENT"
                    if any(_interval_covers(value, interval) for value in support_intervals)
                    else "UNKNOWN"
                )
                disposition = (
                    "RETAINED_SOURCE_SUPPORTED_EXTENT"
                    if source_observation == "SOURCE_PRESENT"
                    else "RETAINED_ACCEPTED_UNRESOLVED_EXTENT"
                )
                behavior = "EMIT_EDITABLE"
                direct_ids = [str(piece["piece_id"]) for piece in direct]
                gap_id_value = None
                auth_ref = acceptance_auth
            elif rejection_disposition is not None and rejection_auth is not None:
                source_observation = (
                    "SOURCE_PRESENT"
                    if any(_interval_covers(value, interval) for value in support_intervals)
                    else "UNKNOWN"
                )
                disposition = rejection_disposition
                behavior = "PRESERVE_SOURCE_FALLBACK"
                direct_ids = []
                gap_id_value = None
                auth_ref = rejection_auth
            else:
                source_observation = "UNKNOWN"
                disposition = "BLOCKED_UNRESOLVED"
                behavior = "BLOCK_NEW_ADMISSION"
                direct_ids = []
                gap_id_value = None
                auth_ref = acceptance_auth
            partition.append(
                {
                    "cell_id": f"{parent_id}:v2-cell-{cell_index:04d}",
                    "parent_interval": _v2_interval_payload(interval),
                    "source_observation": source_observation,
                    "disposition": disposition,
                    "evidence_refs": [evidence_id],
                    "authorization_refs": [auth_ref],
                    "direct_piece_ids": direct_ids,
                    "equivalent_cover": equivalent_cover,
                    "gap_id": gap_id_value,
                    "uncertainty": {
                        "status": "UNKNOWN" if source_observation == "UNKNOWN" else "SUPPORTED",
                        "confidence": None,
                        "calibration": "NOT_APPLICABLE",
                        "limits": ["Accepted uncertainty retained exactly"] if source_observation == "UNKNOWN" else [],
                        "review_required": source_observation == "UNKNOWN",
                    },
                    "downstream_behavior": behavior,
                }
            )

        basis = _trajectory_basis_payload(parent_line)
        transform_records: list[dict[str, object]] = []
        if representation.get("transformation_id"):
            transform_records.append(
                {'uri': f"ledger://transformation/{representation['transformation_id']}", 'sha256': _digest_payload({'id': representation['transformation_id'], 'parent': representation.get('parent_representation_id'), 'interval': representation.get('parent_parameter_interval')}), 'role': 'EXPLICIT_TRANSFORMATION_ANCESTRY'}
            )
        consolidation_parent_ids: list[str] = []
        for consolidation in route_snapshot.get("consolidations", ()):
            if not isinstance(consolidation, Mapping) or str(
                consolidation.get("result_observation_id")
            ) != str(representation.get("observation_id")):
                continue
            consolidation_parent_ids.extend(
                str(value)
                for value in consolidation.get("parent_observation_ids", ())
            )
            transform_records.append(
                {'uri': f"ledger://consolidation/{consolidation.get('consolidation_id')}", 'sha256': _digest_payload(consolidation), 'role': 'EXPLICIT_MANY_TO_ONE_INTERVAL_MAPPED_ANCESTRY'}
            )
        endpoint_ids: list[str] = []
        for name, parameter, point in (
            ("start", 0.0, [float(parent_line.x1), float(parent_line.y1)]),
            ("end", parent_line.length, [float(parent_line.x2), float(parent_line.y2)]),
        ):
            obligation_id = f"{parent_id}:v2-endpoint-{name}"
            endpoint_ids.append(obligation_id)
            touching = [
                str(piece["piece_id"])
                for piece, piece_interval in zip(direct_pieces, direct_intervals, strict=True)
                if abs(piece_interval.start - parameter) <= 1e-9
                or abs(piece_interval.end - parameter) <= 1e-9
            ]
            equivalent_touch = next(
                (
                    cover["keeper_piece_id"]
                    for cell in partition
                    for cover in cell["equivalent_cover"]
                    if abs(float(cell["parent_interval"]["start"]) - parameter) <= 1e-9
                    or abs(float(cell["parent_interval"]["end"]) - parameter) <= 1e-9
                ),
                None,
            )
            if not touching and equivalent_touch:
                touching = [str(equivalent_touch)]
            endpoint_obligations.append(
                {
                    "obligation_id": obligation_id,
                    "parent_id": parent_id,
                    "point_px": point,
                    "kind": "ORIGINAL_ENDPOINT",
                    "disposition": (
                        "EDITABLE_PRESERVED"
                        if touching and not equivalent_touch
                        else (
                            "EQUIVALENT_EDITABLE_PRESERVED"
                            if touching
                            else "REVIEW_REQUIRED"
                        )
                    ),
                    "evidence_refs": [evidence_id],
                    "authorization_refs": [acceptance_auth],
                    "output_member_ids": touching,
                }
            )
        parents.append(
            {
                "parent_id": parent_id,
                "acceptance_status": "ALREADY_ACCEPTED" if accepted else "FRESH_PROPOSAL",
                "acceptance_authorization_ref": acceptance_auth if accepted else None,
                "original_geometry": {
                    "start_px": [float(parent_line.x1), float(parent_line.y1)],
                    "end_px": [float(parent_line.x2), float(parent_line.y2)],
                    "width_px": float(parent_line.width),
                },
                "original_domain": _v2_interval_payload(original),
                "immutable_observation": {'uri': f'ledger://representation/{parent_id}', 'sha256': _digest_payload(representation), 'role': 'IMMUTABLE_ORIGINAL_OBSERVATION'},
                "lineage": {
                    "parent_ids": list(
                        dict.fromkeys(
                            [
                                str(value)
                                for value in representation.get("parent_ids", ())
                            ]
                            + consolidation_parent_ids
                        )
                    ),
                    "primitive_member_ids": [str(value) for value in representation.get("source_ids", ())],
                    "transform_records": transform_records,
                    "producer_head": hashlib.sha1(POLICY_VERSION.encode()).hexdigest(),
                    "producer_version": POLICY_VERSION,
                    "run_id": str(payload["record_id"]),
                },
                "partition": partition,
                "endpoint_obligation_ids": endpoint_ids,
                "parameterization": {
                    "origin_px": list(basis["origin_px"]),
                    "unit_tangent": list(basis["unit_tangent"]),
                    "parameter_units": "SOURCE_PIXELS_ALONG_ORIGINAL_PARENT",
                    "geometry_mapping": "POINT_EQUALS_ORIGIN_PLUS_PARAMETER_TIMES_TANGENT",
                },
            }
        )

    emitted_piece_lookup = {
        str(piece["piece_id"]): piece
        for piece in v1_pieces
        if piece.get("action") == "EMIT"
    }
    for piece_id in final_piece_ids:
        piece = emitted_piece_lookup[str(piece_id)]
        interval = ParameterInterval(
            float(piece["parent_parameter_interval"][0]),
            float(piece["parent_parameter_interval"][1]),
        )
        geometry = piece["geometry_px"]
        extension_pieces.append(
            {
                "piece_id": str(piece_id),
                "parent_id": str(piece["parent_id"]),
                "parent_interval": _v2_interval_payload(interval),
                "geometry": {
                    "start_px": list(geometry["start"]),
                    "end_px": list(geometry["end"]),
                    "width_px": float(geometry["width"]),
                },
                "output_member_id": str(piece_id),
                "claim_measurement": {'uri': f'ledger://piece/{piece_id}/claim', 'sha256': _digest_payload({'new_source': piece['new_source_claim_pixels'], 'new_protected': piece['new_protected_source_claim_pixels'], 'inherited': piece['inherited_protected_source_claim_pixels']}), 'role': 'EXACT_PRODUCTION_RASTER_CLAIM_DELTA'},
                "new_source_claim_pixels": int(piece["new_source_claim_pixels"]),
                "new_protected_claim_pixels": int(piece["new_protected_source_claim_pixels"]),
                "inherited_contact_refs": (
                    [f"protected-contact:{piece_id}"]
                    if int(piece["inherited_protected_source_claim_pixels"]) > 0
                    else []
                ),
            }
        )

    ownership_digest = _digest_payload(
        {
            key: hashlib.sha256(value.tobytes()).hexdigest()
            for key, value in sorted(context.ownership_masks.items())
        }
    )
    protection_digest = hashlib.sha256(context.protected_mask.tobytes()).hexdigest()
    transform_sha = _digest_payload(
        {"coordinate_frame": "ORIGINAL_SOURCE_PIXELS", "mapping": "IDENTITY", "shape": list(context.source_gray.shape)}
    )
    return {
        "schema_version": GAP_EXTENT_SCHEMA_VERSION,
        "record_id": f"gap-extent-{str(payload['input_set_digest'])[:16]}",
        "source": {
            "source_id": "source-image",
            "page_id": str(payload["record_id"]),
            "source_sha256": source_hash,
            "coordinate_frame": "ORIGINAL_SOURCE_PIXELS",
            "region_px": [0, 0, int(context.source_gray.shape[1]), int(context.source_gray.shape[0])],
            "support_artifacts": [source_artifact],
            "source_transform": {'uri': 'runtime://identity-source-transform', 'sha256': transform_sha, 'role': 'SOURCE_TO_RECONCILIATION_IDENTITY_TRANSFORM'},
        },
        "input_snapshot_digest": str(payload["input_set_digest"]),
        "accepted_set_digest": context.accepted_snapshot_digest,
        "route_ledger_digest": str(payload["route_ledger_digest"]),
        "ownership_snapshot_digest": ownership_digest,
        "protection_snapshot_digest": protection_digest,
        "base_ledger_digest": base_ledger_digest,
        "parents": parents,
        "evidence": v2_evidence,
        "authorizations": authorizations,
        "pieces": extension_pieces,
        "endpoint_obligations": endpoint_obligations,
        "transaction": {
            "state": "VALIDATED",
            "consumed_payload_digest": _lines_digest(final_lines),
            "validation_evidence": {'uri': 'runtime://semantic-transaction-validation', 'sha256': _lines_digest(final_lines), 'role': 'RECOMPUTED_TRANSACTION_VALIDATION'},
            "failure_action": "RETAIN_PRIOR_VERSION_AND_BLOCK_INVALID_MUTATION",
            "final_structure_schema": 3,
            "trace_cache_version": 10,
        },
        "gap_observations": gap_observations,
    }


def _gap_extent_semantic_errors(
    payload: Mapping[str, object],
    *,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    context: _ValidationContext,
    check_digest: bool,
) -> list[str]:
    extension = _gap_extent_extension(payload)
    if extension is None:
        return [
            "AUDIT_UNAVAILABLE: source-stroke gap/extent V2 evidence is missing"
        ]
    representations = [
        item
        for item in payload.get("representations", ())
        if isinstance(item, Mapping)
        and item.get("ownership_state")
        in {
            "MAIN_ACCEPTED",
            "MAIN_REJECTED",
            "LEGACY_RESTORATION_ACCEPTED",
            "RESTORATION_PROPOSED",
        }
    ]
    recomputed_gaps: dict[str, tuple[dict[str, object], ...]] = {}
    try:
        for representation in representations:
            parent_id = str(representation["representation_id"])
            line = _line_from_geometry_payload(
                representation["geometry_px"],
                source_ids=tuple(
                    str(value) for value in representation.get("source_ids", ())
                ),
                history=tuple(
                    str(value) for value in representation.get("history", ())
                ),
            )
            recomputed_gaps[parent_id] = _source_visible_gap_certificates(
                line,
                representation_id=parent_id,
                gray=context.source_gray,
                binary=context.source_binary,
                protected_mask=context.protected_mask,
                ownership_masks=context.ownership_masks,
                evidence_cache=context.evidence_cache,
            )
        base_digest = (
            _digest_payload(_payload_without_gap_extent(payload))
            if check_digest
            else str(extension.get("base_ledger_digest", ""))
        )
        expected_payload = _payload_without_gap_extent(payload)
        expected = _build_gap_extent_v2_record(
            expected_payload,
            base_ledger_digest=base_digest,
            final_lines=final_lines,
            final_piece_ids=final_piece_ids,
            gap_certificates=recomputed_gaps,
            context=context,
        )
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        return [f"source-stroke gap/extent V2 evidence is invalid: {exc}"]
    if dict(extension) != expected:
        return [
            "source-stroke gap/extent V2 evidence is missing, stale, forged, or semantically inconsistent"
        ]
    for parent in extension.get("parents", ()):
        if not isinstance(parent, Mapping):
            return ["source-stroke gap/extent V2 parent is invalid"]
        if parent.get("acceptance_status") != "ALREADY_ACCEPTED":
            continue
        if any(
            isinstance(cell, Mapping)
            and cell.get("disposition") == "BLOCKED_UNRESOLVED"
            for cell in parent.get("partition", ())
        ):
            return ["accepted positive extent cannot be BLOCKED_UNRESOLVED"]
    return []


def _transaction_invariant_checks(
    payload: Mapping[str, object],
    *,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    expected_final_digest: str,
    context: _ValidationContext,
) -> dict[str, bool]:
    errors = _semantic_transaction_errors(
        payload,
        final_lines=final_lines,
        final_piece_ids=final_piece_ids,
        expected_final_digest=expected_final_digest,
        context=context,
    )
    valid = not errors
    return {
        "lossless_supported_extent": valid,
        "lossless_endpoint_obligations": valid,
        "no_new_protected_source_claim": valid,
        "final_set_digest_validated": valid,
    }


def _source_scope_digest(
    gray: _ImmutableRasterSnapshot,
    binary: _ImmutableRasterSnapshot,
) -> str:
    return _digest_payload(
        {
            "gray_snapshot_digest": gray.digest,
            "binary_snapshot_digest": binary.digest,
            "shape": list(gray.shape),
            "source_frame_id": gray.source_frame_id,
            "snapshot_version": gray.version,
        }
    )


def _raster_snapshot_is_valid(snapshot: _ImmutableRasterSnapshot) -> bool:
    metadata = {
        "shape": list(snapshot.shape),
        "dtype": snapshot.dtype,
        "layout": snapshot.layout,
        "source_frame_id": snapshot.source_frame_id,
        "version": snapshot.version,
        "sha256": snapshot.sha256,
    }
    return (
        snapshot.version == SOURCE_SNAPSHOT_VERSION
        and snapshot.source_frame_id == SOURCE_FRAME_ID
        and snapshot.layout == "C_ORDER_EXACT_BYTES"
        and len(snapshot.shape) == 2
        and snapshot.dtype == np.dtype(np.uint8).str
        and len(snapshot.data) == math.prod(snapshot.shape) * np.dtype(snapshot.dtype).itemsize
        and hashlib.sha256(snapshot.data).hexdigest() == snapshot.sha256
        and _digest_payload(metadata) == snapshot.digest
    )


def _validate_source_authority(context: _ValidationContext) -> None:
    gray = context.source_gray_authority
    binary = context.source_binary_authority
    if not _raster_snapshot_is_valid(gray) or not _raster_snapshot_is_valid(binary):
        raise AssertionError("Immutable source authority snapshot is invalid")
    if gray.shape != binary.shape or gray.source_frame_id != binary.source_frame_id:
        raise AssertionError("Immutable source authority scopes disagree")
    if (
        context.source_gray_sha256 != gray.sha256
        or context.source_binary_sha256 != binary.sha256
        or context.source_scope_digest != _source_scope_digest(gray, binary)
    ):
        raise AssertionError("Source authority metadata differs from the trusted snapshot")
    for name, working, snapshot in (
        ("gray", context.source_gray, gray),
        ("binary", context.source_binary, binary),
    ):
        if (
            not isinstance(working, np.ndarray)
            or tuple(working.shape) != snapshot.shape
            or working.dtype.str != snapshot.dtype
            or not working.flags.c_contiguous
            or working.tobytes(order="C") != snapshot.data
        ):
            raise AssertionError(f"Sealed {name} source snapshot changed")


def _semantic_transaction_errors(
    payload: Mapping[str, object],
    *,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    expected_final_digest: str,
    context: _ValidationContext,
    check_v2_digest: bool = True,
) -> list[str]:
    errors: list[str] = []
    expected_top_level = {
        "schema_version",
        "record_id",
        "source_image_sha256",
        "producer_head",
        "policy_version",
        "input_set_digest",
        "final_main_set_digest",
        "route_ledger_digest",
        "physical_instance_assertion",
        "basis",
        "representations",
        "evidence",
        "cells",
        "endpoints",
        "pieces",
        "supersession_ledger",
        "transaction",
    }
    if set(payload) != expected_top_level:
        errors.append("closed v1 transaction shape has unknown or missing fields")
    try:
        _validate_source_authority(context)
    except AssertionError as error:
        errors.append(str(error))
    if payload.get("source_image_sha256") != context.source_gray_sha256:
        errors.append("source image identity differs from the sealed source snapshot")
    names = (
        "representations",
        "supersession_ledger",
        "pieces",
        "endpoints",
        "evidence",
        "cells",
    )
    values = [payload.get(name) for name in names]
    if not all(isinstance(value, list) for value in values):
        return ["transaction collections are missing"]
    representations, supersession, pieces, endpoints, evidence, cells = values
    representation_items = [item for item in representations if isinstance(item, Mapping)]
    representation_ids = [str(item.get("representation_id")) for item in representation_items]
    if len(representation_items) != len(representations) or len(set(representation_ids)) != len(representation_ids):
        errors.append("representation identities are not unique")
    representation_by_id = {
        str(item["representation_id"]): item for item in representation_items
    }
    observation_ids = {str(item.get("observation_id")) for item in representation_items}

    terminal_items = [item for item in supersession if isinstance(item, Mapping)]
    terminal_ids = [str(item.get("representation_id")) for item in terminal_items]
    terminal_counts = Counter(terminal_ids)
    if set(terminal_ids) != set(representation_ids) or any(
        terminal_counts[representation_id] != 1 for representation_id in representation_ids
    ):
        errors.append("exactly one terminal disposition is required")
    terminal_by_id = {
        str(item["representation_id"]): item for item in terminal_items
    }

    snapshot = next(
        (
            item
            for item in evidence
            if isinstance(item, Mapping)
            and item.get("artifact") == "runtime-route-ledger-snapshot"
        ),
        None,
    )
    measurements = snapshot.get("measurements") if isinstance(snapshot, Mapping) else None
    route_ledger = measurements.get("route_ledger") if isinstance(measurements, Mapping) else None
    snapshot_inputs = measurements.get("input_lines") if isinstance(measurements, Mapping) else None
    if not isinstance(route_ledger, Mapping) or not isinstance(snapshot_inputs, list):
        errors.append("route/input snapshot is missing")
        route_ledger = {}
        snapshot_inputs = []
    else:
        if _digest_payload(route_ledger) != payload.get("route_ledger_digest"):
            errors.append("route ledger digest is stale")
        if dict(route_ledger) != json.loads(context.route_ledger_json):
            errors.append("route ledger differs from the sealed raw/route snapshot")
        actual_inputs = [_line_payload(line) for line in context.input_lines]
        if snapshot_inputs != actual_inputs:
            errors.append("input snapshot differs from live reconciliation inputs")
    if _lines_digest(context.input_lines) != payload.get("input_set_digest"):
        errors.append("input set digest is false")
    if _lines_digest(context.accepted_main) != payload.get("final_main_set_digest"):
        errors.append("final main digest is false")
    actual_final_digest = _lines_digest(final_lines)
    snapshot_final_digest = (
        measurements.get("committed_final_set_digest")
        if isinstance(measurements, Mapping)
        else None
    )
    snapshot_final_lines = (
        measurements.get("committed_final_lines")
        if isinstance(measurements, Mapping)
        else None
    )
    if (
        actual_final_digest != expected_final_digest
        or snapshot_final_digest != actual_final_digest
        or snapshot_final_lines != [_line_payload(line) for line in final_lines]
    ):
        errors.append("final set digest is false")

    observed = (
        route_ledger.get("observed", ())
        if isinstance(route_ledger, Mapping)
        else ()
    )
    observed_by_id = {
        str(item.get("observation_id")): item
        for item in observed
        if isinstance(item, Mapping)
    }
    transformations = (
        route_ledger.get("transformations", ())
        if isinstance(route_ledger, Mapping)
        else ()
    )
    transform_by_id = {
        str(item.get("transformation_id")): item
        for item in transformations
        if isinstance(item, Mapping)
    }
    consolidations = (
        route_ledger.get("consolidations", ())
        if isinstance(route_ledger, Mapping)
        else ()
    )
    for consolidation in consolidations:
        if not isinstance(consolidation, Mapping):
            errors.append("invalid consolidation record")
            continue
        parent_observation_ids = consolidation.get("parent_observation_ids")
        result_observation_id = str(consolidation.get("result_observation_id"))
        if (
            consolidation.get("operation") != LineageOperation.CONSOLIDATION.value
            or not isinstance(parent_observation_ids, list)
            or len(parent_observation_ids) < 2
            or any(str(value) not in observed_by_id for value in parent_observation_ids)
            or result_observation_id not in observed_by_id
        ):
            errors.append("consolidation ancestry is incomplete")
            continue
        result_observation = observed_by_id[result_observation_id]
        result_line = result_observation.get("line")
        if (
            not isinstance(result_line, Mapping)
            or consolidation.get("result_geometry_px")
            != {
                "start": [float(result_line.get("x1")), float(result_line.get("y1"))],
                "end": [float(result_line.get("x2")), float(result_line.get("y2"))],
                "width": float(result_line.get("width")),
            }
        ):
            errors.append("consolidation result geometry is false")

    accepted_main_keys = {_line_identity_key(line) for line in context.accepted_main}
    accepted_restoration_keys = {
        _line_identity_key(line) for line in context.accepted_restorations
    }
    live_state_by_observation: dict[str, tuple[str, str]] = {}
    for route, lines in (
        (RouteOrigin.MAIN, context.main_candidates),
        (RouteOrigin.RESTORATION, context.restoration_candidates),
    ):
        for line in lines:
            observation_key = _observation_key(route, line)
            observation = next(
                (
                    item
                    for item in observed
                    if isinstance(item, Mapping)
                    and str(item.get("observation_key")) == observation_key
                ),
                None,
            )
            if not isinstance(observation, Mapping):
                errors.append("live input has no original observation")
                continue
            expected_state = (
                (
                    "MAIN_ACCEPTED"
                    if _line_identity_key(line) in accepted_main_keys
                    else "MAIN_REJECTED"
                )
                if route is RouteOrigin.MAIN
                else (
                    "LEGACY_RESTORATION_ACCEPTED"
                    if _line_identity_key(line) in accepted_restoration_keys
                    else "RESTORATION_PROPOSED"
                )
            )
            live_state_by_observation[str(observation["observation_id"])] = (
                route.value,
                expected_state,
            )
    for representation in representation_items:
        representation_id = str(representation["representation_id"])
        observation_id = str(representation.get("observation_id"))
        observation = observed_by_id.get(observation_id)
        if not isinstance(observation, Mapping):
            errors.append(f"{representation_id}: missing original observation")
        else:
            observed_line = observation.get("line")
            if not isinstance(observed_line, Mapping) or (
                representation.get("geometry_px")
                != {
                    "start": [
                        float(observed_line.get("x1")),
                        float(observed_line.get("y1")),
                    ],
                    "end": [
                        float(observed_line.get("x2")),
                        float(observed_line.get("y2")),
                    ],
                    "width": float(observed_line.get("width")),
                }
                or list(representation.get("source_ids", ()))
                != list(observed_line.get("source_ids", ()))
                or list(representation.get("history", ()))
                != list(observed_line.get("history", ()))
            ):
                errors.append(f"{representation_id}: representation differs from original observation")
        live_state = live_state_by_observation.get(observation_id)
        if live_state is not None and (
            representation.get("route_origin") != live_state[0]
            or representation.get("ownership_state") != live_state[1]
        ):
            errors.append(f"{representation_id}: live route/ownership state is false")
        try:
            child_interval_values = representation.get("child_parameter_interval")
            if not isinstance(child_interval_values, list) or len(child_interval_values) != 2:
                raise ValueError
            geometry = representation.get("geometry_px")
            if not isinstance(geometry, Mapping):
                raise ValueError
            child_length = math.hypot(
                float(geometry["end"][0]) - float(geometry["start"][0]),
                float(geometry["end"][1]) - float(geometry["start"][1]),
            )
            if [float(value) for value in child_interval_values] != [0.0, child_length]:
                errors.append(f"{representation_id}: child parameter interval is false")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{representation_id}: invalid child interval")
        parent_id = representation.get("parent_representation_id")
        parent_ids = representation.get("parent_ids")
        expected_parents = [] if parent_id is None else [str(parent_id)]
        if not isinstance(parent_ids, list) or [str(value) for value in parent_ids] != expected_parents:
            errors.append(f"{representation_id}: ancestry references disagree")
        if parent_id is None:
            if representation.get("operation") != LineageOperation.ORIGINAL_OBSERVATION.value:
                errors.append(f"{representation_id}: non-original has no parent")
            if str(representation.get("root_observation_id")) != str(
                representation.get("observation_id")
            ):
                errors.append(f"{representation_id}: original root identity is inconsistent")
        else:
            parent = representation_by_id.get(str(parent_id))
            if parent is None:
                errors.append(f"{representation_id}: unknown parent")
                continue
            if str(representation.get("root_observation_id")) != str(
                parent.get("root_observation_id")
            ):
                errors.append(f"{representation_id}: root ancestry is inconsistent")
            if representation.get("route_transition") != (
                f"{parent.get('route_origin')}->{representation.get('route_origin')}"
            ):
                errors.append(f"{representation_id}: route transition is inconsistent")
            transform = transform_by_id.get(str(representation.get("transformation_id")))
            if transform is None:
                errors.append(f"{representation_id}: missing transformation record")
            elif (
                str(transform.get("parent_observation_id")) != str(parent.get("observation_id"))
                or str(transform.get("child_observation_id")) != str(representation.get("observation_id"))
                or str(transform.get("operation")) != str(representation.get("operation"))
            ):
                errors.append(f"{representation_id}: transformation edge is inconsistent")
            elif (
                list(transform.get("parent_parameter_interval", ()))
                != list(representation.get("parent_parameter_interval", ()))
                or list(transform.get("child_parameter_interval", ()))
                != list(representation.get("child_parameter_interval", ()))
                or transform.get("child_geometry_px")
                != representation.get("geometry_px")
            ):
                errors.append(f"{representation_id}: transformation facts are false")
            if representation.get("operation") in {
                LineageOperation.TRIM_TO_SOURCE_SUPPORT.value,
                LineageOperation.COVERAGE_SPLIT.value,
                LineageOperation.ROUTE_DIVERSION.value,
                LineageOperation.ROUTE_TRANSFORM.value,
            }:
                try:
                    interval_values = representation["parent_parameter_interval"]
                    if not isinstance(interval_values, list) or len(interval_values) != 2:
                        raise ValueError
                    interval = ParameterInterval(float(interval_values[0]), float(interval_values[1]))
                    parent_line = _line_from_geometry_payload(
                        parent["geometry_px"],
                        source_ids=tuple(str(value) for value in parent.get("source_ids", ())),
                        history=tuple(str(value) for value in parent.get("history", ())),
                    )
                    expected_child = _exact_subsegment(parent_line, interval)
                    child_geometry = representation.get("geometry_px")
                    if not _geometry_payload_matches_line(
                        child_geometry,
                        expected_child,
                    ):
                        errors.append(f"{representation_id}: parent/child interval is geometrically inconsistent")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{representation_id}: invalid parent interval")
        if str(representation.get("root_observation_id")) not in observation_ids:
            errors.append(f"{representation_id}: missing root observation")

    piece_items = [item for item in pieces if isinstance(item, Mapping)]
    piece_ids = [str(item.get("piece_id")) for item in piece_items]
    if len(piece_items) != len(pieces) or len(set(piece_ids)) != len(piece_ids):
        errors.append("piece identities are not unique")
    piece_by_id = {str(item["piece_id"]): item for item in piece_items}
    emitted = [item for item in piece_items if item.get("action") == "EMIT"]
    emitted_ids = tuple(str(item["piece_id"]) for item in emitted)
    if emitted_ids != tuple(final_piece_ids):
        errors.append("emitted piece order differs from committed piece IDs")
    if len(emitted) != len(final_lines):
        errors.append("emitted piece count differs from final line count")
    else:
        for piece, line in zip(emitted, final_lines, strict=True):
            if piece.get("line_payload") != _line_payload(line):
                errors.append(f"{piece.get('piece_id')}: final line differs from ledger piece")

    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence
        if isinstance(item, Mapping)
    }
    if len(evidence_by_id) != len(evidence):
        errors.append("evidence identities are missing or duplicated")
    for cell in cells:
        if not isinstance(cell, Mapping):
            errors.append("relation cell is invalid")
            continue
        references = [
            str(value)
            for key in ("positive_evidence_refs", "negative_evidence_refs")
            for value in cell.get(key, ())
        ]
        if not references or any(value not in evidence_by_id for value in references):
            errors.append(f"{cell.get('cell_id')}: relation evidence is missing")
            continue
        members = [str(value) for value in cell.get("members", ())]
        if len(members) != 2:
            errors.append(f"{cell.get('cell_id')}: relation members are invalid")
            continue
        left_piece = piece_by_id.get(members[0])
        right_representation = representation_by_id.get(members[1])
        if left_piece is None or right_representation is None:
            errors.append(f"{cell.get('cell_id')}: relation member does not resolve")
            continue
        try:
            left_line = _line_from_geometry_payload(
                left_piece["geometry_px"],
                source_ids=tuple(str(value) for value in left_piece.get("source_ids", ())),
                history=tuple(str(value) for value in left_piece.get("history", ())),
            )
            right_line = _line_from_geometry_payload(
                right_representation["geometry_px"],
                source_ids=tuple(
                    str(value) for value in right_representation.get("source_ids", ())
                ),
                history=tuple(
                    str(value) for value in right_representation.get("history", ())
                ),
            )
            expected_cells = _certify_pair_cells(
                left_line,
                right_line,
                left_id=members[0],
                right_id=members[1],
                gray=context.source_gray,
                binary=context.source_binary,
                scale=context.scale,
                protected_mask=context.protected_mask,
                ownership_masks=context.ownership_masks,
                right_ownership_state=str(
                    right_representation.get("ownership_state", "ACCEPTED")
                ),
                evidence_cache=context.evidence_cache,
            )
            interval_payload = cell.get("interval")
            if not isinstance(interval_payload, Mapping):
                raise ValueError
            interval = ParameterInterval(
                float(interval_payload["start"]), float(interval_payload["end"])
            )
            matched = next(
                (
                    value
                    for value in expected_cells
                    if abs(value.right_interval.start - interval.start) <= 1e-9
                    and abs(value.right_interval.end - interval.end) <= 1e-9
                ),
                None,
            )
            if matched is None or (
                matched.relation.value != cell.get("relation")
                or matched.endpoint_obligations_clear
                != bool(cell.get("endpoint_obligations_clear"))
            ):
                errors.append(
                    f"{cell.get('cell_id')}: relation certificate is not independently reproducible"
                )
        except (AssertionError, KeyError, TypeError, ValueError):
            errors.append(f"{cell.get('cell_id')}: relation certificate is invalid")

    endpoint_by_id = {
        str(item.get("endpoint_id")): item
        for item in endpoints
        if isinstance(item, Mapping)
    }
    for piece in piece_items:
        piece_id = str(piece.get("piece_id"))
        parent_id = str(piece.get("parent_id"))
        parent = representation_by_id.get(parent_id)
        if parent is None:
            errors.append(f"{piece_id}: unknown piece parent")
            continue
        try:
            interval_values = piece.get("parent_parameter_interval")
            interval_payload = piece.get("interval")
            if not isinstance(interval_values, list) or not isinstance(interval_payload, Mapping):
                raise ValueError
            interval = ParameterInterval(float(interval_values[0]), float(interval_values[1]))
            if [interval.start, interval.end] != [
                float(interval_payload.get("start")),
                float(interval_payload.get("end")),
            ]:
                errors.append(f"{piece_id}: interval records disagree")
            parent_line = _line_from_geometry_payload(
                parent["geometry_px"],
                source_ids=tuple(str(value) for value in parent.get("source_ids", ())),
                history=tuple(str(value) for value in parent.get("history", ())),
            )
            expected_piece = _exact_subsegment(parent_line, interval)
            geometry = piece.get("geometry_px")
            if _geometry_payload(expected_piece) != geometry:
                errors.append(f"{piece_id}: piece geometry is inconsistent with parent interval")
            line_payload = piece.get("line_payload")
            if not isinstance(line_payload, Mapping) or {
                "start": [float(line_payload.get("x1")), float(line_payload.get("y1"))],
                "end": [float(line_payload.get("x2")), float(line_payload.get("y2"))],
                "width": float(line_payload.get("width")),
            } != geometry:
                errors.append(f"{piece_id}: line payload and geometry disagree")
            piece_line = _line_from_payload(line_payload)
            claim = _claim_measurements(
                piece_line,
                masks=context.ownership_masks,
                protected_mask=context.protected_mask,
                source_binary=context.source_binary,
            )
            delta = _claim_delta_measurements(
                parent_line,
                piece_line,
                protected_mask=context.protected_mask,
                source_binary=context.source_binary,
            )
            unchanged = piece.get("claim_mode") == "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
            expected_new_source = delta["new_source_pixels"] if unchanged else claim["new_source_pixels"]
            expected_new_protected = (
                delta["new_protected_source_pixels"]
                if unchanged
                else (0 if piece.get("action") == "BLOCK_AND_REVIEW" else claim["protected_source_pixels"])
            )
            expected_inherited = delta["inherited_protected_source_pixels"] if unchanged else 0
            if int(piece.get("new_source_claim_pixels", -1)) != expected_new_source:
                errors.append(f"{piece_id}: source claim counter is false")
            if int(piece.get("new_protected_source_claim_pixels", -1)) != expected_new_protected:
                errors.append(f"{piece_id}: protected claim counter is false")
            if int(piece.get("inherited_protected_source_claim_pixels", -1)) != expected_inherited:
                errors.append(f"{piece_id}: inherited claim counter is false")
            if piece.get("action") == "EMIT" and unchanged and (
                delta["new_source_pixels"] > 0
                or delta["new_protected_source_pixels"] > 0
            ):
                errors.append(
                    f"{piece_id}: accepted-parent reduction creates an unauthorized exact raster claim"
                )
            if piece.get("action") == "EMIT" and not unchanged and (
                claim["protected_source_pixels"]
                or claim["semantic_conflict_source_pixels"]
                or claim["residual_source_pixels"]
            ):
                errors.append(f"{piece_id}: disputed fresh claim was emitted")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{piece_id}: invalid piece transaction")
        geometry = piece.get("geometry_px")
        if isinstance(geometry, Mapping):
            for side in ("start", "end"):
                endpoint = endpoint_by_id.get(str(piece.get(f"{side}_endpoint_id")))
                if not isinstance(endpoint, Mapping) or endpoint.get("point_px") != geometry.get(side):
                    errors.append(f"{piece_id}: endpoint geometry is inconsistent")

    rejected_states = {
        TerminalDisposition.REJECTED_OWNERSHIP.value,
        TerminalDisposition.REJECTED_PROTECTION.value,
        TerminalDisposition.BLOCKED.value,
    }
    extension = _gap_extent_extension(payload)
    v2_parent_by_id = {
        str(item.get("parent_id")): item
        for item in (
            extension.get("parents", ()) if isinstance(extension, Mapping) else ()
        )
        if isinstance(item, Mapping)
    }
    prefilter_by_key = {
        str(item.get("observation_key")): str(item.get("disposition"))
        for item in route_ledger.get("prefilter_terminal", ())
        if isinstance(item, Mapping)
    }
    authorized_rejection_roots: set[str] = set()
    for observation_id, observation in observed_by_id.items():
        observed_line = observation.get("line")
        if not isinstance(observed_line, Mapping):
            continue
        main_rejected = (
            observation.get("route") == RouteOrigin.MAIN.value
            and _line_identity_key(_line_from_payload(observed_line))
            not in accepted_main_keys
        )
        protection_rejected = (
            prefilter_by_key.get(str(observation.get("observation_key")))
            == TerminalDisposition.REJECTED_PROTECTION.value
        )
        if main_rejected or protection_rejected:
            authorized_rejection_roots.add(observation_id)
    for representation_id, terminal in terminal_by_id.items():
        disposition = terminal.get("disposition")
        if disposition not in {
            item.value for item in TerminalDisposition
        }:
            errors.append(f"{representation_id}: terminal disposition is outside the closed vocabulary")
        replacements = [str(value) for value in terminal.get("replacement_piece_ids", ())]
        if any(value not in piece_by_id for value in replacements):
            errors.append(f"{representation_id}: replacement piece does not exist")
        emitted_children = [
            piece
            for piece in emitted
            if str(piece.get("parent_id")) == representation_id
        ]
        if disposition in rejected_states and emitted_children:
            errors.append(f"{representation_id}: rejected/blocked representation was emitted")
        representation = representation_by_id.get(representation_id, {})
        if representation.get("ownership_state") == "MAIN_REJECTED" and emitted_children:
            errors.append(f"{representation_id}: ownership-rejected representation was emitted")
        removed_payloads = terminal.get("removed_intervals", ())
        removed_intervals: list[ParameterInterval] = []
        rejected_interval_payloads = terminal.get("rejected_intervals", ())
        rejected_intervals: list[ParameterInterval] = []
        try:
            for item in removed_payloads:
                removed_intervals.append(ParameterInterval(float(item["start"]), float(item["end"])))
            for item in rejected_interval_payloads:
                rejected_intervals.append(
                    ParameterInterval(float(item["start"]), float(item["end"]))
                )
        except (KeyError, TypeError, ValueError):
            errors.append(f"{representation_id}: invalid removed/rejected interval")
        if rejected_intervals and not terminal.get("rejected_root_observation_ids"):
            errors.append(f"{representation_id}: rejection has no explicit ancestry root")
        rejection_roots = {
            str(value) for value in terminal.get("rejected_root_observation_ids", ())
        }
        if rejection_roots and not rejection_roots.issubset(authorized_rejection_roots):
            errors.append(f"{representation_id}: rejection root lacks sealed authority")
        if disposition in {
            TerminalDisposition.REJECTED_OWNERSHIP.value,
            TerminalDisposition.REJECTED_PROTECTION.value,
        } and representation.get("ownership_state") != "MAIN_REJECTED" and not rejection_roots and str(
            representation.get("observation_id")
        ) not in authorized_rejection_roots:
            errors.append(f"{representation_id}: rejection lacks an explicit sealed decision")
        if removed_intervals:
            keepers = {str(value) for value in terminal.get("retained_keeper_piece_ids", ())}
            if not keepers or any(
                keeper not in piece_by_id or piece_by_id[keeper].get("action") != "EMIT"
                for keeper in keepers
            ):
                errors.append(f"{representation_id}: removed support lacks retained keeper")
            certified: list[ParameterInterval] = []
            for cell in cells:
                if not isinstance(cell, Mapping) or representation_id not in cell.get("members", ()):
                    continue
                if (
                    cell.get("relation") != Relation.SAME_VISIBLE_STROKE_SUPPORTED.value
                    or not cell.get("endpoint_obligations_clear")
                    or not keepers.intersection(str(value) for value in cell.get("retained_ids", ()))
                ):
                    continue
                obligations = cell.get("local_obligations")
                if not isinstance(obligations, Mapping) or (
                    obligations.get("protection_state") != "UNPROTECTED"
                    or obligations.get("semantic_owner_state") != "LINE_OR_UNOWNED"
                    or obligations.get("trajectory_evidence") != "POSITIVE"
                ):
                    continue
                interval_payload = cell.get("interval")
                if isinstance(interval_payload, Mapping):
                    certified.append(ParameterInterval(float(interval_payload["start"]), float(interval_payload["end"])))
            for removed in removed_intervals:
                if _subtract_intervals((removed,), certified):
                    errors.append(f"{representation_id}: removed support is not keeper-covered")

        if disposition == TerminalDisposition.SUPERSEDED_EQUIVALENT.value and (
            not removed_intervals
            or not terminal.get("retained_keeper_piece_ids")
            or emitted_children
        ):
            errors.append(f"{representation_id}: supersession is not explicitly closed")
        if disposition == TerminalDisposition.RETAINED.value and not emitted_children:
            errors.append(f"{representation_id}: retained representation has no final output")
        if disposition == TerminalDisposition.SPLIT.value and not (
            emitted_children or removed_intervals or rejected_intervals
        ):
            errors.append(f"{representation_id}: split disposition has no partition")
        if disposition == TerminalDisposition.TRANSFORMED_CHILD.value:
            transformed_representation = representation_by_id.get(
                representation_id, {}
            )
            transformed_observation_id = str(
                transformed_representation.get("observation_id", "")
            )
            explicit_transform_child = any(
                representation_id
                in {str(value) for value in item.get("parent_ids", ())}
                for item in representation_items
            )
            consolidation_child_observation_ids = {
                str(item.get("result_observation_id"))
                for item in consolidations
                if isinstance(item, Mapping)
                and transformed_observation_id
                in {
                    str(value)
                    for value in item.get("parent_observation_ids", ())
                }
            }
            explicit_consolidation_child = any(
                str(item.get("observation_id"))
                in consolidation_child_observation_ids
                for item in representation_items
            )
            if not explicit_transform_child and not explicit_consolidation_child:
                errors.append(
                    f"{representation_id}: transformed observation has no child representation"
                )

        representation = representation_by_id.get(representation_id, {})
        if representation.get("ownership_state") in {
            "MAIN_ACCEPTED",
            "LEGACY_RESTORATION_ACCEPTED",
        } and disposition not in rejected_states:
            try:
                observation_interval = representation.get("observation_interval")
                if not isinstance(observation_interval, Mapping):
                    raise ValueError
                original = ParameterInterval(
                    float(observation_interval["start"]),
                    float(observation_interval["end"]),
                )
                retained_intervals = [
                    ParameterInterval(
                        float(piece["parent_parameter_interval"][0]),
                        float(piece["parent_parameter_interval"][1]),
                    )
                    for piece in emitted_children
                ]
                for first_index, first in enumerate(retained_intervals):
                    for second in retained_intervals[first_index + 1 :]:
                        if _intersect_interval_sets((first,), (second,)):
                            errors.append(
                                f"{representation_id}: direct output coverage is duplicated"
                            )
                v2_parent = v2_parent_by_id.get(representation_id, {})
                absent_intervals = [
                    _interval_from_v2_payload(cell["parent_interval"])
                    for cell in v2_parent.get("partition", ())
                    if isinstance(cell, Mapping)
                    and cell.get("disposition") == "SOURCE_VISIBLE_GAP"
                ]
                if (
                    _intersect_interval_sets(retained_intervals, removed_intervals)
                    or _intersect_interval_sets(retained_intervals, rejected_intervals)
                    or _intersect_interval_sets(retained_intervals, absent_intervals)
                    or _intersect_interval_sets(removed_intervals, rejected_intervals)
                    or _intersect_interval_sets(removed_intervals, absent_intervals)
                    or _intersect_interval_sets(rejected_intervals, absent_intervals)
                ):
                    errors.append(
                        f"{representation_id}: accepted extent dispositions overlap"
                    )
                partition = _merge_intervals(
                    (
                        *retained_intervals,
                        *removed_intervals,
                        *rejected_intervals,
                        *absent_intervals,
                    )
                )
                if (
                    _subtract_intervals((original,), partition)
                    or _subtract_intervals(partition, (original,))
                ):
                    errors.append(
                        f"{representation_id}: accepted original extent partition is open"
                    )
            except (KeyError, TypeError, ValueError):
                errors.append(f"{representation_id}: invalid accepted extent partition")

    if any(line.length <= DXF_MIN_LINE_LENGTH_PX for line in final_lines):
        errors.append("unexportable final line was committed")
    errors.extend(
        _gap_extent_semantic_errors(
            payload,
            final_lines=final_lines,
            final_piece_ids=final_piece_ids,
            context=context,
            check_digest=check_v2_digest,
        )
    )
    return errors


def _validate_transaction_semantics(
    payload: Mapping[str, object],
    *,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    context: _ValidationContext,
) -> None:
    representations = payload.get("representations", ())
    if isinstance(representations, Sequence) and all(
        isinstance(item, Mapping) and "observation_id" not in item
        for item in representations
    ):
        _validate_closed_transaction_semantics(
            payload,
            final_lines=final_lines,
            final_piece_ids=final_piece_ids,
            context=context,
        )
        return
    checks = _transaction_invariant_checks(
        payload,
        final_lines=final_lines,
        final_piece_ids=final_piece_ids,
        expected_final_digest=_lines_digest(final_lines),
        context=context,
    )
    transaction = payload.get("transaction")
    if not isinstance(transaction, Mapping):
        raise AssertionError("Reconciliation transaction is missing")
    if not all(checks.values()):
        raise AssertionError("Reconciliation semantic invariants do not hold")
    for key, value in checks.items():
        if bool(transaction.get(key)) != value:
            raise AssertionError(f"Reconciliation transaction invariant changed: {key}")


def _validate_closed_transaction_semantics(
    payload: Mapping[str, object],
    *,
    final_lines: Sequence[LineSegment],
    final_piece_ids: Sequence[str],
    context: _ValidationContext,
) -> None:
    """Validate the real closed V1 envelope against the sealed authority input."""

    _validate_source_authority(context)
    expected_top_level = {
        "schema_version",
        "record_id",
        "source_image_sha256",
        "producer_head",
        "policy_version",
        "input_set_digest",
        "final_main_set_digest",
        "route_ledger_digest",
        "physical_instance_assertion",
        "basis",
        "representations",
        "evidence",
        "cells",
        "endpoints",
        "pieces",
        "supersession_ledger",
        "transaction",
    }
    if set(payload) != expected_top_level:
        raise AssertionError("Closed V1 transaction shape changed")
    if payload.get("source_image_sha256") != context.source_gray_sha256:
        raise AssertionError("Closed transaction source identity is not sealed")
    if payload.get("input_set_digest") != _lines_digest(context.input_lines):
        raise AssertionError("Closed transaction input identity is false")
    if payload.get("final_main_set_digest") != _lines_digest(context.accepted_main):
        raise AssertionError("Closed transaction accepted-main identity is false")

    evidence = payload.get("evidence")
    representations = payload.get("representations")
    supersession = payload.get("supersession_ledger")
    pieces = payload.get("pieces")
    if not all(
        isinstance(value, list)
        for value in (evidence, representations, supersession, pieces)
    ):
        raise AssertionError("Closed V1 transaction collections are missing")
    snapshot = next(
        (
            item
            for item in evidence
            if isinstance(item, Mapping)
            and item.get("artifact") == "runtime-route-ledger-snapshot"
        ),
        None,
    )
    measurements = snapshot.get("measurements") if isinstance(snapshot, Mapping) else None
    if not isinstance(measurements, Mapping):
        raise AssertionError("Sealed route snapshot is missing")
    route_ledger = measurements.get("route_ledger")
    if (
        not isinstance(route_ledger, Mapping)
        or dict(route_ledger) != json.loads(context.route_ledger_json)
        or _digest_payload(route_ledger) != payload.get("route_ledger_digest")
    ):
        raise AssertionError("Closed transaction route authority is not sealed")
    if measurements.get("input_lines") != [
        _line_payload(line) for line in context.input_lines
    ]:
        raise AssertionError("Closed transaction input snapshot is false")
    if measurements.get("committed_final_lines") != [
        _line_payload(line) for line in final_lines
    ] or measurements.get("committed_final_set_digest") != _lines_digest(final_lines):
        raise AssertionError("Closed transaction final payload is false")

    representation_ids = [
        str(item.get("representation_id"))
        for item in representations
        if isinstance(item, Mapping)
    ]
    terminal_ids = [
        str(item.get("representation_id"))
        for item in supersession
        if isinstance(item, Mapping)
    ]
    if (
        len(representation_ids) != len(representations)
        or len(set(representation_ids)) != len(representation_ids)
        or Counter(terminal_ids) != Counter(representation_ids)
    ):
        raise AssertionError("Closed transaction terminal accounting is incomplete")

    emitted = [
        item
        for item in pieces
        if isinstance(item, Mapping) and item.get("action") == "EMIT"
    ]
    if tuple(str(item.get("piece_id")) for item in emitted) != tuple(final_piece_ids):
        raise AssertionError("Closed transaction emitted piece identity changed")
    if len(emitted) != len(final_lines):
        raise AssertionError("Closed transaction final membership is incomplete")
    for piece, line in zip(emitted, final_lines, strict=True):
        geometry = piece.get("geometry_px")
        if not isinstance(geometry, Mapping) or geometry != _geometry_payload(line):
            raise AssertionError("Closed transaction piece geometry changed")
        if list(piece.get("source_ids", ())) != list(line.source_ids) or list(
            piece.get("history", ())
        ) != list(line.history):
            raise AssertionError("Closed transaction piece provenance changed")

    extension = _gap_extent_extension(payload)
    if extension is None:
        raise AssertionError("AUDIT_UNAVAILABLE: V2 extent accounting is missing")
    expected_ownership_digest = _digest_payload(
        {
            key: hashlib.sha256(value.tobytes()).hexdigest()
            for key, value in sorted(context.ownership_masks.items())
        }
    )
    expected_protection_digest = hashlib.sha256(
        context.protected_mask.tobytes()
    ).hexdigest()
    if (
        extension.get("input_snapshot_digest") != _lines_digest(context.input_lines)
        or extension.get("accepted_set_digest") != context.accepted_snapshot_digest
        or extension.get("route_ledger_digest") != payload.get("route_ledger_digest")
        or extension.get("ownership_snapshot_digest") != expected_ownership_digest
        or extension.get("protection_snapshot_digest") != expected_protection_digest
        or extension.get("base_ledger_digest")
        != _digest_payload(_payload_without_gap_extent(payload))
    ):
        raise AssertionError("V2 accounting is not bound to the sealed authority snapshot")
    transaction = extension.get("transaction")
    if not isinstance(transaction, Mapping) or (
        transaction.get("state") != "VALIDATED"
        or transaction.get("consumed_payload_digest") != _lines_digest(final_lines)
    ):
        raise AssertionError("V2 consumed payload identity is false")

    parents = extension.get("parents")
    if not isinstance(parents, list):
        raise AssertionError("V2 accepted-parent accounting is missing")
    accepted_geometry_keys = {
        _geometry_key(line) for line in (*context.accepted_main, *context.accepted_restorations)
    }
    accounted_accepted_keys: set[str] = set()
    for parent in parents:
        if not isinstance(parent, Mapping):
            raise AssertionError("V2 parent accounting is invalid")
        geometry = parent.get("original_geometry")
        if not isinstance(geometry, Mapping):
            raise AssertionError("V2 parent geometry is missing")
        line = LineSegment(
            float(geometry["start_px"][0]),
            float(geometry["start_px"][1]),
            float(geometry["end_px"][0]),
            float(geometry["end_px"][1]),
            width=float(geometry["width_px"]),
            source_ids=tuple(
                str(value)
                for value in parent.get("lineage", {}).get("primitive_member_ids", ())
            ),
        )
        if parent.get("acceptance_status") == "ALREADY_ACCEPTED":
            accounted_accepted_keys.add(_geometry_key(line))
        partition = parent.get("partition")
        if not isinstance(partition, list) or not partition:
            raise AssertionError("V2 parent partition is missing")
        cursor = 0.0
        for cell in partition:
            if not isinstance(cell, Mapping):
                raise AssertionError("V2 partition cell is invalid")
            interval = _interval_from_v2_payload(cell.get("parent_interval"))
            if abs(interval.start - cursor) > 1e-9:
                raise AssertionError("V2 partition is overlapping, unordered, or open")
            cursor = interval.end
            direct_ids = [str(value) for value in cell.get("direct_piece_ids", ())]
            if len(direct_ids) > 1 or len(direct_ids) != len(set(direct_ids)):
                raise AssertionError("V2 direct coverage multiplicity is invalid")
        if abs(cursor - line.length) > 1e-9:
            raise AssertionError("V2 partition does not close the original domain")
    if accounted_accepted_keys != accepted_geometry_keys:
        raise AssertionError("V2 accepted snapshot membership is incomplete")

    outer = payload.get("transaction")
    required_checks = (
        "lossless_supported_extent",
        "lossless_endpoint_obligations",
        "no_new_protected_source_claim",
        "final_set_digest_validated",
    )
    if not isinstance(outer, Mapping) or outer.get("state") != "VALIDATED" or any(
        outer.get(key) is not True for key in required_checks
    ):
        raise AssertionError("Closed V1 transaction is not validated")


def _validated_ownership_masks(
    masks: Mapping[str, np.ndarray],
    *,
    shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    output: dict[str, np.ndarray] = {}
    for key in ("line", "text", "logo", "signature", "graphic", "residual"):
        mask = masks.get(key)
        if mask is None:
            output[key] = np.zeros(shape, dtype=np.uint8)
            continue
        if mask.shape != shape:
            raise ValueError(f"Ownership mask {key!r} has the wrong shape")
        output[key] = np.ascontiguousarray(mask, dtype=np.uint8)
    return output


def _source_visible_gap_certificates(
    line: LineSegment,
    *,
    representation_id: str,
    gray: np.ndarray,
    binary: np.ndarray,
    protected_mask: np.ndarray,
    ownership_masks: Mapping[str, np.ndarray],
    evidence_cache: _ReconciliationEvidenceCache | None = None,
) -> tuple[dict[str, object], ...]:
    """Certify only bounded, clearly observable blank source intervals.

    Samples follow the actual floating-point parent trajectory.  Each station
    inspects the production raster claim footprint, not a shared rounded
    surrogate point.  Unknown, covered, clipped, or threshold-sensitive
    stations split a run and can never become gap authority.
    """

    if line.length <= 1e-9:
        return ()
    trajectory_key = _trajectory_evidence_key(line)
    footprint = (
        None
        if evidence_cache is None
        else evidence_cache.footprints.get(trajectory_key)
    )
    if footprint is None:
        if evidence_cache is not None:
            evidence_cache.count("footprint_misses")
        footprint = _complete_claim_footprint_records(
            line,
            gray=gray,
            binary=binary,
            protected_mask=protected_mask,
            ownership_masks=ownership_masks,
        )
        if evidence_cache is not None:
            evidence_cache.footprints[trajectory_key] = footprint
    elif evidence_cache is not None:
        evidence_cache.count("footprint_hits")
    cached_segments = (
        None
        if evidence_cache is None
        else evidence_cache.support_segments.get(trajectory_key)
    )
    if cached_segments is None:
        if evidence_cache is not None:
            evidence_cache.count("support_segment_misses")
        segments = tuple(_continuous_footprint_segments(line, footprint))
        if evidence_cache is not None:
            evidence_cache.support_segments[trajectory_key] = segments
    else:
        if evidence_cache is not None:
            evidence_cache.count("support_segment_hits")
        segments = cached_segments
    uncertainty = _raster_cell_parameter_half_width(line)
    output: list[dict[str, object]] = []
    for index, segment in enumerate(segments):
        if segment["observation"] != "SOURCE_VISIBLE_GAP":
            continue
        if (
            index == 0
            or index == len(segments) - 1
            or segments[index - 1]["observation"] != "SOURCE_PRESENT"
            or segments[index + 1]["observation"] != "SOURCE_PRESENT"
        ):
            continue
        # The footprint-to-parameter projection includes the exact square-cell
        # intersection band.  Retain one further square-cell projection band
        # at each transition; this is uncertainty preservation, not epsilon
        # shrinking.
        start = float(segment["start"]) + uncertainty
        end = float(segment["end"]) - uncertainty
        if end <= start:
            continue
        interval = ParameterInterval(start, end)
        sampled = segments[max(0, index - 1) : min(len(segments), index + 2)]
        measurement = {
            "representation_id": representation_id,
            "trajectory_basis": _trajectory_basis_payload(line),
            "source_shape": [int(gray.shape[0]), int(gray.shape[1])],
            "sampling_resolution_px": 0.0,
            "raster_cell_parameter_half_width_px": uncertainty,
            "complete_production_claim_cell_count": len(footprint),
            "samples": sampled,
            "observability": "OBSERVABLE_ORIGINAL_UNCLOSED_SOURCE",
            "boundary_rule": "RETAIN_ONE_RASTER_CELL_PROJECTION_BAND",
        }
        measurement_sha = _digest_payload(measurement)
        gap_id = (
            "gap-"
            + hashlib.sha256(
                f"{representation_id}|{interval.start:.12f}|{interval.end:.12f}|{measurement_sha}".encode()
            ).hexdigest()[:20]
        )
        output.append(
            {
                "gap_id": gap_id,
                "parent_id": representation_id,
                "certified_absent_interval": _v2_interval_payload(interval),
                "left_boundary_uncertainty_px": uncertainty,
                "right_boundary_uncertainty_px": uncertainty,
                "measurement_convention": (
                    "COMPLETE_PRODUCTION_RASTER_CLAIM_FOOTPRINT_TO_CONTINUOUS_"
                    "PARENT_INTERVAL_RETAIN_ONE_CELL_BOUNDARY_BAND"
                ),
                "observation": "SOURCE_VISIBLE_GAP",
                "cause_hypothesis": "UNKNOWN_GAP",
                "measurement": measurement,
                "measurement_sha256": measurement_sha,
            }
        )
    return tuple(output)


def _raster_cell_parameter_half_width(line: LineSegment) -> float:
    if line.length <= 0.0:
        return 0.0
    tangent = (line.p2 - line.p1) / line.length
    return 0.5 * (abs(float(tangent[0])) + abs(float(tangent[1])))


def _complete_claim_footprint_records(
    line: LineSegment,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
    protected_mask: np.ndarray,
    ownership_masks: Mapping[str, np.ndarray],
) -> tuple[dict[str, object], ...]:
    """Map every production-claim raster cell to its continuous parent band."""

    if line.length <= 0.0:
        return ()
    tangent = (line.p2 - line.p1) / line.length
    half_width = _raster_cell_parameter_half_width(line)
    claim = _line_claim_mask(line, shape=binary.shape)
    records: list[dict[str, object]] = []
    for y_value, x_value in np.argwhere(claim > 0):
        x, y = int(x_value), int(y_value)
        parameter = float(
            np.dot(np.array([float(x), float(y)]) - line.p1, tangent)
        )
        raw_start = parameter - half_width
        raw_end = parameter + half_width
        endpoint_cap = raw_end <= 0.0 or raw_start >= float(line.length)
        start = max(0.0, raw_start)
        end = min(float(line.length), raw_end)
        # OpenCV's production LINE_8 stroke includes round endpoint caps.  Cap
        # pixels can project wholly before 0 or after ``line.length`` even
        # though they are real members of the production claim footprint.
        # Bind those pixels conservatively to a one-cell boundary band rather
        # than dropping them from continuous accounting.
        if end <= start and raw_end <= 0.0:
            start = 0.0
            end = min(float(line.length), max(half_width, 1e-9))
        elif end <= start and raw_start >= float(line.length):
            end = float(line.length)
            start = max(0.0, end - max(half_width, 1e-9))
        if end <= start:
            continue
        non_line_owners = tuple(
            key
            for key in ("text", "logo", "signature", "graphic", "residual")
            if ownership_masks[key][y, x] > 0
        )
        source = _pixel_is_source(x, y, gray=gray, binary=binary)
        ambiguous = (not source) and (
            int(gray[y, x]) < 245 or int(binary[y, x]) < 245
        )
        records.append(
            {
                "pixel": [x, y],
                "start": start,
                "end": end,
                "source": source,
                "ambiguous": ambiguous,
                "protected": bool(protected_mask[y, x] > 0),
                "non_line_owners": list(non_line_owners),
                "endpoint_cap": endpoint_cap,
                "clipped": bool(
                    x == 0
                    or y == 0
                    or x == binary.shape[1] - 1
                    or y == binary.shape[0] - 1
                ),
            }
        )
    return tuple(records)


def _continuous_footprint_segments(
    line: LineSegment,
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Sweep mapped raster cells into conservative continuous observations."""

    starts: dict[float, list[int]] = {}
    ends: dict[float, list[int]] = {}
    boundaries = {0.0, float(line.length)}
    for record_index, record in enumerate(records):
        start = float(record["start"])
        end = float(record["end"])
        boundaries.update((start, end))
        starts.setdefault(start, []).append(record_index)
        ends.setdefault(end, []).append(record_index)
    ordered = sorted(boundaries)
    active: set[int] = set()
    raw: list[dict[str, object]] = []
    raw_pixel_sets: list[set[tuple[int, int]]] = []
    for index, start in enumerate(ordered[:-1]):
        for record_index in ends.get(start, ()):
            active.discard(record_index)
        active.update(starts.get(start, ()))
        end = ordered[index + 1]
        if end <= start:
            continue
        local = [records[value] for value in sorted(active)]
        if not local or any(bool(item["clipped"]) for item in local):
            observation = "UNOBSERVABLE"
        elif any(
            bool(item["protected"]) or bool(item["non_line_owners"])
            for item in local
        ):
            observation = "UNKNOWN"
        elif any(bool(item["source"]) for item in local):
            observation = "SOURCE_PRESENT"
        elif any(bool(item["ambiguous"]) for item in local):
            observation = "UNKNOWN"
        else:
            observation = "SOURCE_VISIBLE_GAP"
        pixels = {
            (int(item["pixel"][0]), int(item["pixel"][1]))
            for item in local
        }
        if raw and raw[-1]["observation"] == observation:
            raw[-1]["end"] = end
            raw_pixel_sets[-1].update(pixels)
            continue
        raw_pixel_sets.append(set(pixels))
        raw.append(
            {
                "start": start,
                "end": end,
                "claim_footprint_pixels": [],
                "observation": observation,
                "observable": observation not in {"UNOBSERVABLE", "UNKNOWN"},
            }
        )
    for segment, pixel_set in zip(raw, raw_pixel_sets, strict=True):
        segment["claim_footprint_pixels"] = [
            [x, y] for x, y in sorted(pixel_set)
        ]
    return raw


def _v2_interval_payload(interval: ParameterInterval) -> dict[str, object]:
    return {
        "start": float(interval.start),
        "end": float(interval.end),
        "convention": "HALF_OPEN_INTERIOR_SEPARATE_ENDPOINTS",
    }


def _interval_from_v2_payload(payload: object) -> ParameterInterval:
    if not isinstance(payload, Mapping):
        raise ValueError("Invalid V2 interval")
    return ParameterInterval(float(payload["start"]), float(payload["end"]))


def _source_support_intervals(
    line: LineSegment,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> list[ParameterInterval]:
    if line.length <= 1e-9:
        return []
    tangent = (line.p2 - line.p1) / line.length
    samples = np.linspace(0.0, line.length, max(2, int(math.ceil(line.length)) + 1))
    supported: list[bool] = []
    for distance in samples:
        point = line.p1 + tangent * distance
        supported.append(
            _pixel_is_source(
                int(round(float(point[0]))),
                int(round(float(point[1]))),
                gray=gray,
                binary=binary,
            )
        )
    intervals: list[ParameterInterval] = []
    run_start: int | None = None
    for index, value in enumerate((*supported, False)):
        if value and run_start is None:
            run_start = index
            continue
        if value or run_start is None:
            continue
        run_end = index - 1
        start = (
            0.0
            if run_start == 0
            else float((samples[run_start - 1] + samples[run_start]) / 2.0)
        )
        end = (
            line.length
            if run_end == len(samples) - 1
            else float((samples[run_end] + samples[run_end + 1]) / 2.0)
        )
        if end > start:
            intervals.append(ParameterInterval(start, end))
        run_start = None
    return intervals


def _has_direct_trajectory_source(
    line: LineSegment,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> bool:
    """Conservative retrieval gate; false can only suppress destructive work."""

    if line.length <= 0.0:
        return False
    sample_count = max(2, int(math.ceil(line.length)) + 1)
    for distance in np.linspace(0.0, line.length, sample_count):
        point = line.p1 + (line.p2 - line.p1) * (float(distance) / line.length)
        if _pixel_is_source(
            int(round(float(point[0]))),
            int(round(float(point[1]))),
            gray=gray,
            binary=binary,
        ):
            return True
    return False


def _has_full_direct_trajectory_source(
    line: LineSegment,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> bool:
    if line.length <= 0.0:
        return False
    sample_count = max(2, int(math.ceil(line.length)) + 1)
    return all(
        _pixel_is_source(
            int(round(float(point[0]))),
            int(round(float(point[1]))),
            gray=gray,
            binary=binary,
        )
        for point in (
            line.p1
            + (line.p2 - line.p1) * (float(distance) / line.length)
            for distance in np.linspace(0.0, line.length, sample_count)
        )
    )


def _certify_pair_cells(
    left: LineSegment,
    right: LineSegment,
    *,
    left_id: str,
    right_id: str,
    gray: np.ndarray,
    binary: np.ndarray,
    scale: float,
    protected_mask: np.ndarray | None = None,
    ownership_masks: Mapping[str, np.ndarray] | None = None,
    right_ownership_state: str = "ACCEPTED",
    evidence_cache: _ReconciliationEvidenceCache | None = None,
) -> tuple[RelationCell, ...]:
    if evidence_cache is None:
        return _certify_pair_cells_uncached(
            left,
            right,
            left_id=left_id,
            right_id=right_id,
            gray=gray,
            binary=binary,
            scale=scale,
            protected_mask=protected_mask,
            ownership_masks=ownership_masks,
            right_ownership_state=right_ownership_state,
        )
    key = (
        evidence_cache.snapshot_key,
        left_id,
        right_id,
        _line_identity_key(left),
        _line_identity_key(right),
        float(scale).hex(),
        right_ownership_state,
    )
    cached = evidence_cache.pair_results.get(key)
    if cached is not None:
        evidence_cache.count("pair_hits")
        return cached
    evidence_cache.count("pair_misses")
    result = _certify_pair_cells_uncached(
        left,
        right,
        left_id=left_id,
        right_id=right_id,
        gray=gray,
        binary=binary,
        scale=scale,
        protected_mask=protected_mask,
        ownership_masks=ownership_masks,
        right_ownership_state=right_ownership_state,
        evidence_cache=evidence_cache,
    )
    evidence_cache.pair_results[key] = result
    return result


def _certify_pair_cells_uncached(
    left: LineSegment,
    right: LineSegment,
    *,
    left_id: str,
    right_id: str,
    gray: np.ndarray,
    binary: np.ndarray,
    scale: float,
    protected_mask: np.ndarray | None = None,
    ownership_masks: Mapping[str, np.ndarray] | None = None,
    right_ownership_state: str = "ACCEPTED",
    evidence_cache: _ReconciliationEvidenceCache | None = None,
) -> tuple[RelationCell, ...]:
    if left.length <= 1e-9 or right.length <= 1e-9:
        return ()
    left_tangent = (left.p2 - left.p1) / left.length
    right_tangent = (right.p2 - right.p1) / right.length
    alignment = abs(float(np.dot(left_tangent, right_tangent)))
    if alignment < math.cos(math.radians(4.0)):
        return ()
    right_forward = float(np.dot(left_tangent, right_tangent)) >= 0.0
    if not right_forward:
        right_tangent = -right_tangent
    right_origin = right.p1 if right_forward else right.p2
    left_normal = np.array([-left_tangent[1], left_tangent[0]], dtype=float)
    axis = 0 if abs(float(left_tangent[0])) >= abs(float(left_tangent[1])) else 1
    left_coordinates = sorted((float(left.p1[axis]), float(left.p2[axis])))
    right_coordinates = sorted((float(right.p1[axis]), float(right.p2[axis])))
    overlap_coordinate_start = max(left_coordinates[0], right_coordinates[0])
    overlap_coordinate_end = min(left_coordinates[1], right_coordinates[1])
    if overlap_coordinate_end <= overlap_coordinate_start:
        return ()
    left_parameters = sorted(
        (
            _parameter_at_axis_coordinate(left, axis, overlap_coordinate_start),
            _parameter_at_axis_coordinate(left, axis, overlap_coordinate_end),
        )
    )
    overlap_start, overlap_end = left_parameters
    midpoint = left.p1 + left_tangent * ((overlap_start + overlap_end) / 2.0)
    right_mid_parameter = float(np.dot(midpoint - right_origin, right_tangent))
    right_mid = right_origin + right_tangent * right_mid_parameter
    separation = abs(float(np.dot(right_mid - midpoint, left_normal)))
    retrieval_limit = max(4.5, 4.5 * scale)
    if separation > retrieval_limit:
        return ()

    sample_count = max(2, int(math.ceil(overlap_end - overlap_start)) + 1)
    distances = np.linspace(overlap_start, overlap_end, sample_count)
    states: list[Relation] = []
    authority_states: list[tuple[str, ...]] = []
    cross_sections: list[dict[str, object]] = []
    original_right_tangent = (right.p2 - right.p1) / right.length
    def claim_mask(line: LineSegment) -> np.ndarray:
        if evidence_cache is None:
            return _line_claim_mask(line, shape=binary.shape)
        key = (_trajectory_evidence_key(line), tuple(binary.shape))
        cached = evidence_cache.claim_masks.get(key)
        if cached is not None:
            evidence_cache.count("claim_mask_hits")
            return cached
        evidence_cache.count("claim_mask_misses")
        value = _line_claim_mask(line, shape=binary.shape)
        value.setflags(write=False)
        evidence_cache.claim_masks[key] = value
        return value

    left_claim = claim_mask(left)
    right_claim = claim_mask(right)
    authority_masks = {
        key: (
            np.zeros(binary.shape, dtype=np.uint8)
            if ownership_masks is None or ownership_masks.get(key) is None
            else ownership_masks[key]
        )
        for key in ("line", "text", "logo", "signature", "graphic", "residual")
    }
    authority_protection = (
        np.zeros(binary.shape, dtype=np.uint8)
        if protected_mask is None
        else protected_mask
    )
    def footprint(line: LineSegment) -> tuple[dict[str, object], ...]:
        if evidence_cache is None:
            return _complete_claim_footprint_records(
                line,
                gray=gray,
                binary=binary,
                protected_mask=authority_protection,
                ownership_masks=authority_masks,
            )
        key = _trajectory_evidence_key(line)
        cached = evidence_cache.footprints.get(key)
        if cached is not None:
            evidence_cache.count("footprint_hits")
            return cached
        evidence_cache.count("footprint_misses")
        value = _complete_claim_footprint_records(
            line,
            gray=gray,
            binary=binary,
            protected_mask=authority_protection,
            ownership_masks=authority_masks,
        )
        evidence_cache.footprints[key] = value
        return value

    complete_left_footprint = footprint(left)
    complete_right_footprint = footprint(right)
    for distance in distances:
        left_point = left.p1 + left_tangent * distance
        right_parameter = float(np.dot(left_point - right_origin, right_tangent))
        right_parameter = min(right.length, max(0.0, right_parameter))
        right_point = right_origin + right_tangent * right_parameter
        offset = float(np.dot(right_point - left_point, left_normal))
        state, cross_section = _cross_section_relation(
            left_point,
            right_point,
            left_normal,
            gray=gray,
            binary=binary,
            radius=max(
                6, int(math.ceil(abs(offset) + max(left.width, right.width) + 3))
            ),
        )
        states.append(state)
        claim_footprint_pixels = _local_claim_footprint_pixels(
            (
                (left, left_point, left_claim),
                (right, right_point, right_claim),
            ),
            shape=binary.shape,
        )
        cross_section["claim_footprint_pixels"] = [
            [int(x), int(y)] for x, y in claim_footprint_pixels
        ]
        cross_sections.append(cross_section)
        protection_state = _local_mask_state(
            protected_mask,
            claim_footprint_pixels,
            active="PROTECTED",
            inactive="UNPROTECTED",
        )
        semantic_owner_state = "LINE_OR_UNOWNED"
        if ownership_masks is not None:
            owners = tuple(
                key
                for key in ("text", "logo", "signature", "graphic", "residual")
                if _local_mask_state(
                    ownership_masks.get(key),
                    claim_footprint_pixels,
                    active=key.upper(),
                    inactive="",
                )
            )
            if owners:
                semantic_owner_state = "+".join(owners)
        line_owner_state = (
            _local_mask_state(
                None if ownership_masks is None else ownership_masks.get("line"),
                claim_footprint_pixels,
                active="LINE_OWNED",
                inactive="LINE_UNOWNED",
            )
        )
        source_footprint_state = (
            "SOURCE_PRESENT"
            if any(
                _pixel_is_source(x, y, gray=gray, binary=binary)
                for x, y in claim_footprint_pixels
            )
            else "SOURCE_ABSENT"
        )
        ownership_conflict_state = (
            "OWNERSHIP_CONFLICT"
            if line_owner_state == "LINE_OWNED"
            and semantic_owner_state != "LINE_OR_UNOWNED"
            else "NO_OWNERSHIP_CONFLICT"
        )
        endpoint_attachment_state = "NO_ENDPOINT_TRANSITION"
        if (
            distance == distances[0]
            or distance == distances[-1]
        ):
            endpoint_attachment_state = "ENDPOINT_BOUNDARY"
        authority_states.append(
            (
                protection_state,
                semantic_owner_state,
                right_ownership_state,
                endpoint_attachment_state,
                source_footprint_state,
                line_owner_state,
                ownership_conflict_state,
            )
        )

    # Each sample state remains local.  Boundaries are placed halfway between
    # adjacent samples so an UNKNOWN or light-gap transition can never be
    # absorbed into a neighboring SAME certificate.
    left_boundaries = [float(overlap_start)]
    left_boundaries.extend(
        float((distances[index] + distances[index + 1]) / 2.0)
        for index in range(sample_count - 1)
    )
    left_boundaries.append(float(overlap_end))

    cells: list[RelationCell] = []
    run_start = 0
    for index in range(1, sample_count + 1):
        if (
            index < sample_count
            and states[index] is states[run_start]
            and authority_states[index] == authority_states[run_start]
        ):
            continue
        left_interval = ParameterInterval(
            left_boundaries[run_start],
            left_boundaries[index],
        )
        start_point = left.p1 + left_tangent * left_interval.start
        end_point = left.p1 + left_tangent * left_interval.end
        right_bounds = sorted(
            (
                min(
                    right.length,
                    max(
                        0.0,
                        float(
                            np.dot(
                                start_point - right.p1,
                                original_right_tangent,
                            )
                        ),
                    ),
                ),
                min(
                    right.length,
                    max(
                        0.0,
                        float(
                            np.dot(
                                end_point - right.p1,
                                original_right_tangent,
                            )
                        ),
                    ),
                ),
            )
        )
        if right_bounds[1] <= right_bounds[0]:
            run_start = index
            continue
        right_interval = ParameterInterval(*right_bounds)
        right_clear, right_endpoint_reason = _endpoint_obligations_clear(
            keeper=left,
            candidate=right,
            candidate_interval=right_interval,
            gray=gray,
            binary=binary,
        )
        left_clear, left_endpoint_reason = _endpoint_obligations_clear(
            keeper=right,
            candidate=left,
            candidate_interval=left_interval,
            gray=gray,
            binary=binary,
        )
        clear = right_clear and left_clear
        relation = states[run_start]
        (
            protection_state,
            semantic_owner_state,
            local_ownership_state,
            _,
            _source_footprint_state,
            _line_owner_state,
            _ownership_conflict_state,
        ) = authority_states[run_start]
        sampled_pixels = {
            (int(pixel[0]), int(pixel[1]))
            for section in cross_sections[run_start:index]
            for pixel in section.get("claim_footprint_pixels", ())
        }
        interval_footprint = [
            record
            for record in complete_left_footprint
            if float(record["start"]) < left_interval.end
            and float(record["end"]) > left_interval.start
        ] + [
            record
            for record in complete_right_footprint
            if float(record["start"]) < right_interval.end
            and float(record["end"]) > right_interval.start
        ]
        full_protected = any(bool(record["protected"]) for record in interval_footprint)
        full_semantic_owners = sorted(
            {
                str(owner)
                for record in interval_footprint
                for owner in record["non_line_owners"]
            }
        )
        ambiguous_cells = [
            record for record in interval_footprint if bool(record["ambiguous"])
        ]
        unobserved_source_cells = [
            record
            for record in interval_footprint
            if bool(record["source"])
            and not bool(record.get("endpoint_cap"))
            and (int(record["pixel"][0]), int(record["pixel"][1]))
            not in sampled_pixels
        ]
        complete_interval_pixels = sorted(
            {
                (int(record["pixel"][0]), int(record["pixel"][1]))
                for record in interval_footprint
            }
        )
        relation_sections = [
            dict(section) for section in cross_sections[run_start:index]
        ]
        if relation_sections:
            relation_sections[0]["claim_footprint_pixels"] = [
                [x, y] for x, y in complete_interval_pixels
            ]
            relation_sections[0][
                "claim_footprint_accounting"
            ] = "COMPLETE_CONTINUOUS_INTERVAL_PRODUCTION_RASTER_FOOTPRINT"
        if full_protected:
            protection_state = "PROTECTED"
        if full_semantic_owners:
            semantic_owner_state = "+".join(owner.upper() for owner in full_semantic_owners)
        if (
            protection_state == "PROTECTED"
            or semantic_owner_state != "LINE_OR_UNOWNED"
            or local_ownership_state in {"MAIN_REJECTED", "REJECTED_OWNERSHIP"}
            or ambiguous_cells
            or unobserved_source_cells
        ):
            relation = Relation.RELATION_UNRESOLVED
            clear = False
        if relation is Relation.SAME_VISIBLE_STROKE_SUPPORTED and not clear:
            relation = Relation.RELATION_UNRESOLVED
        local_count = index - run_start
        same_samples = (
            local_count
            if relation is Relation.SAME_VISIBLE_STROKE_SUPPORTED
            else 0
        )
        distinct_samples = (
            local_count
            if relation is Relation.DISTINCT_VISIBLE_STROKES_SUPPORTED
            else 0
        )
        unknown_samples = (
            local_count if relation is Relation.RELATION_UNRESOLVED else 0
        )
        endpoint_reason = (
            f"left={left_endpoint_reason};right={right_endpoint_reason}"
        )
        evidence_id = (
            "relation:"
            + hashlib.sha256(
                (
                    f"{left_id}|{right_id}|{left_interval.start:.9f}|"
                    f"{left_interval.end:.9f}|{relation.value}"
                ).encode()
            ).hexdigest()[:20]
        )
        cells.append(
            RelationCell(
                left_id=left_id,
                right_id=right_id,
                left_interval=left_interval,
                right_interval=right_interval,
                relation=relation,
                endpoint_obligations_clear=clear,
                evidence_id=evidence_id,
                measurements=(
                    ("lateral_separation_px", separation),
                    ("same_samples", same_samples),
                    ("distinct_samples", distinct_samples),
                    ("unknown_samples", unknown_samples),
                    ("same_ratio", same_samples / local_count),
                    ("distinct_ratio", distinct_samples / local_count),
                    (
                        "left_trajectory_binding_ratio",
                        0.0 if unknown_samples else 1.0,
                    ),
                    (
                        "right_trajectory_binding_ratio",
                        0.0 if unknown_samples else 1.0,
                    ),
                    ("sample_count", local_count),
                    ("sample_start_index", run_start),
                    ("sample_end_index", index - 1),
                    (
                        "cross_sections",
                        tuple(relation_sections),
                    ),
                    ("complete_claim_cell_count", len(interval_footprint)),
                    ("complete_claim_protected", full_protected),
                    ("complete_claim_semantic_owners", tuple(full_semantic_owners)),
                    ("complete_claim_ambiguous_cell_count", len(ambiguous_cells)),
                    ("unobserved_source_claim_cell_count", len(unobserved_source_cells)),
                    ("endpoint_reason", endpoint_reason),
                ),
                reason=(
                    "Both trajectories directly bind to one original-source run"
                    if relation is Relation.SAME_VISIBLE_STROKE_SUPPORTED
                    else (
                        "Original source contains trajectory-bound separate runs"
                        if relation is Relation.DISTINCT_VISIBLE_STROKES_SUPPORTED
                        else "Source or endpoint evidence is incomplete/conflicting"
                    )
                ),
                protection_state=protection_state,
                semantic_owner_state=semantic_owner_state,
                ownership_state=local_ownership_state,
                ancestry_state="CLEAR",
            )
        )
        run_start = index
    return tuple(cells)


def _cross_section_relation(
    point: np.ndarray,
    right_point: np.ndarray,
    normal: np.ndarray,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
    radius: int,
) -> tuple[Relation, dict[str, object]]:
    connector = np.asarray(right_point, dtype=float) - np.asarray(point, dtype=float)
    connector_length = float(np.linalg.norm(connector))
    connector_unit = normal if connector_length <= 1e-12 else connector / connector_length
    left_pixel_xy = tuple(int(round(float(value))) for value in point)
    right_pixel_xy = tuple(int(round(float(value))) for value in right_point)
    start_pixel = tuple(
        int(round(float(value)))
        for value in point - connector_unit * float(radius)
    )
    end_pixel = tuple(
        int(round(float(value)))
        for value in right_point + connector_unit * float(radius)
    )
    pixels = _bresenham_pixels(start_pixel, left_pixel_xy)
    pixels.extend(_bresenham_pixels(left_pixel_xy, right_pixel_xy)[1:])
    pixels.extend(_bresenham_pixels(right_pixel_xy, end_pixel)[1:])
    dark = [
        _pixel_is_source(x, y, gray=gray, binary=binary)
        for x, y in pixels
    ]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate((*dark, False)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None

    def containing(pixel: tuple[int, int]) -> int | None:
        try:
            pixel_index = pixels.index(pixel)
        except ValueError:
            return None
        for run_index, (run_start, run_end) in enumerate(runs):
            if run_start <= pixel_index <= run_end:
                return run_index
        return None

    left_run = containing(left_pixel_xy)
    right_run = containing(right_pixel_xy)
    run_offsets = [
        [
            float(
                np.dot(
                    np.asarray(pixels[run_start], dtype=float) - point,
                    connector_unit,
                )
            ),
            float(
                np.dot(
                    np.asarray(pixels[run_end], dtype=float) - point,
                    connector_unit,
                )
            ),
        ]
        for run_start, run_end in runs
    ]
    measurement: dict[str, object] = {
        "left_trajectory_point_px": [float(point[0]), float(point[1])],
        "right_trajectory_point_px": [
            float(right_point[0]),
            float(right_point[1]),
        ],
        "right_trajectory_offset_px": float(
            np.dot(right_point - point, normal)
        ),
        "left_trajectory_pixel": list(left_pixel_xy),
        "right_trajectory_pixel": list(right_pixel_xy),
        "left_trajectory_source_bound": bool(
            _pixel_is_source(*left_pixel_xy, gray=gray, binary=binary)
        ),
        "right_trajectory_source_bound": bool(
            _pixel_is_source(*right_pixel_xy, gray=gray, binary=binary)
        ),
        "source_runs": run_offsets,
        "source_run_pixels": [
            [list(pixels[pixel_index]) for pixel_index in range(run_start, run_end + 1)]
            for run_start, run_end in runs
        ],
        "left_run_index": left_run,
        "right_run_index": right_run,
        "authority": "INDEPENDENT_ACTUAL_TRAJECTORY_ORIGINAL_PIXEL_BINDING",
    }
    if left_run is None or right_run is None:
        relation = Relation.RELATION_UNRESOLVED
        measurement["relation"] = relation.value
        return relation, measurement
    if left_run == right_run:
        relation = Relation.SAME_VISIBLE_STROKE_SUPPORTED
        measurement["relation"] = relation.value
        return relation, measurement
    first = runs[min(left_run, right_run)]
    second = runs[max(left_run, right_run)]
    if second[0] - first[1] >= 2:
        relation = Relation.DISTINCT_VISIBLE_STROKES_SUPPORTED
        measurement["relation"] = relation.value
        return relation, measurement
    relation = Relation.RELATION_UNRESOLVED
    measurement["relation"] = relation.value
    return relation, measurement


def _endpoint_obligations_clear(
    *,
    keeper: LineSegment,
    candidate: LineSegment,
    candidate_interval: ParameterInterval,
    gray: np.ndarray,
    binary: np.ndarray,
) -> tuple[bool, str]:
    statuses: list[str] = []
    for parameter, point, outward_sign in (
        (0.0, candidate.p1, -1.0),
        (candidate.length, candidate.p2, 1.0),
    ):
        if (
            parameter < candidate_interval.start
            or parameter > candidate_interval.end
        ):
            continue
        tangent = (candidate.p2 - candidate.p1) / candidate.length
        normal = np.array([-tangent[1], tangent[0]], dtype=float)
        continuation = 0
        checked = 0
        for distance in (1.0, 2.0, 3.0, 4.0):
            sample_point = point + tangent * outward_sign * distance
            checked += 1
            if _point_has_source(
                sample_point,
                normal,
                gray=gray,
                binary=binary,
                normal_radius=max(2, int(math.ceil(candidate.width / 2.0))),
            ):
                continuation += 1
        attachment_status = _endpoint_attachment_status(
            point,
            tangent=tangent,
            normal=normal,
            inward_sign=-outward_sign,
            gray=gray,
            binary=binary,
        )
        if attachment_status == "ATTACHMENT_SUPPORTED":
            return False, "INDEPENDENT_STRUCTURAL_ATTACHMENT_AT_ENDPOINT"
        exact_keeper_endpoint = bool(
            np.array_equal(point, keeper.p1)
            or np.array_equal(point, keeper.p2)
        )
        if exact_keeper_endpoint:
            statuses.append("EXACT_SOURCE_ENDPOINT_RETAINED_BY_KEEPER")
            continue
        if attachment_status == "ATTACHMENT_UNRESOLVED":
            return False, "ENDPOINT_ATTACHMENT_UNRESOLVED"
        if continuation >= 3 and attachment_status == "NO_ATTACHMENT_WITH_EVIDENCE":
            statuses.append("OBSERVATION_FRONTIER_SOURCE_CONTINUES")
            continue
        if continuation == 0:
            return False, "SOURCE_TERMINATION_AT_ENDPOINT"
        return False, "ENDPOINT_RELATION_UNRESOLVED"
    return True, ";".join(statuses) if statuses else "NO_REMOVED_ORIGINAL_ENDPOINT"


def _has_structural_endpoint_obligation(
    line: LineSegment,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> bool:
    """Return true when either original endpoint carries a visible attachment."""

    if line.length <= 1e-9:
        return True
    if not _has_full_direct_trajectory_source(
        line,
        gray=gray,
        binary=binary,
    ):
        # Source transitions require cell-level evidence; they are not an
        # endpoint-only retrieval shortcut.
        return False
    tangent = (line.p2 - line.p1) / line.length
    normal = np.array([-tangent[1], tangent[0]], dtype=float)
    interior_profiles = [
        _normal_source_profile(
            line.p1 + tangent * line.length * fraction,
            normal=normal,
            gray=gray,
            binary=binary,
        )
        for fraction in (0.05, 0.25, 0.5, 0.75, 0.95)
    ]
    narrowest_profile = min(interior_profiles, key=len)
    for point, inward_sign in ((line.p1, 1.0), (line.p2, -1.0)):
        endpoint_profile = _normal_source_profile(
            point,
            normal=normal,
            gray=gray,
            binary=binary,
        )
        if (set(endpoint_profile) - set(narrowest_profile)) - {0}:
            return True
        status = _endpoint_attachment_status(
            point,
            tangent=tangent,
            normal=normal,
            inward_sign=inward_sign,
            gray=gray,
            binary=binary,
        )
        if status == "ATTACHMENT_SUPPORTED":
            return True
    return False


def _endpoint_attachment_status(
    point: np.ndarray,
    *,
    tangent: np.ndarray,
    normal: np.ndarray,
    inward_sign: float,
    gray: np.ndarray,
    binary: np.ndarray,
) -> str:
    """Classify a local endpoint without an absence-by-width threshold.

    A perpendicular attachment is positive when an exact original-pixel normal
    sample exists at the endpoint but at none of three inward cross-sections.
    A clear frontier requires the inverse positive pattern: stable inward band,
    no endpoint-only normal sample, and source continuation beyond the detector
    endpoint.  Any incomplete pattern remains unresolved.
    """

    endpoint_profile = _normal_source_profile(
        point,
        normal=normal,
        gray=gray,
        binary=binary,
    )
    inward_profiles = [
        _normal_source_profile(
            point + tangent * inward_sign * distance,
            normal=normal,
            gray=gray,
            binary=binary,
        )
        for distance in (2.0, 3.0, 4.0)
    ]
    if not endpoint_profile or any(not profile for profile in inward_profiles):
        return "ATTACHMENT_UNRESOLVED"
    stable_interior = set.intersection(*(set(profile) for profile in inward_profiles))
    endpoint_only = set(endpoint_profile) - set.union(
        *(set(profile) for profile in inward_profiles)
    )
    endpoint_only.discard(0)
    if endpoint_only:
        return "ATTACHMENT_SUPPORTED"
    # A no-attachment result is a positive frontier certificate, not the
    # absence of a hit on a few normal profiles.  Inspect every original-source
    # pixel in the already bounded four-pixel neighborhood and require it to be
    # explained by the stable interior stroke band.  Short diagonal/T branches
    # that fall between the profiles therefore remain unresolved and editable.
    frontier_radius = 4
    center_x = int(round(float(point[0])))
    center_y = int(round(float(point[1])))
    if (
        center_x - frontier_radius < 0
        or center_y - frontier_radius < 0
        or center_x + frontier_radius >= gray.shape[1]
        or center_y + frontier_radius >= gray.shape[0]
    ):
        return "ATTACHMENT_UNRESOLVED"
    plausible_off_band_source: list[tuple[int, int]] = []
    for y in range(center_y - frontier_radius, center_y + frontier_radius + 1):
        for x in range(center_x - frontier_radius, center_x + frontier_radius + 1):
            strong_source = _pixel_is_source(x, y, gray=gray, binary=binary)
            plausible_source = strong_source or (
                int(gray[y, x]) < 245 or int(binary[y, x]) < 245
            )
            if not plausible_source:
                continue
            delta = np.array([float(x), float(y)], dtype=float) - point
            longitudinal = float(np.dot(delta, tangent)) * inward_sign
            if abs(longitudinal) > float(frontier_radius) + 0.5:
                continue
            normal_offset = int(round(float(np.dot(delta, normal))))
            # A threshold disagreement or faint original-gray mark is
            # ambiguous evidence, never positive evidence that the frontier is
            # empty.  Only pixels already explained by the stable inward band
            # can be ignored here.
            if normal_offset not in stable_interior:
                plausible_off_band_source.append((x, y))
    if plausible_off_band_source:
        return "ATTACHMENT_UNRESOLVED"
    outward_sign = -inward_sign
    continuation = sum(
        _pixel_is_source(
            int(round(float((point + tangent * outward_sign * distance)[0]))),
            int(round(float((point + tangent * outward_sign * distance)[1]))),
            gray=gray,
            binary=binary,
        )
        for distance in (1.0, 2.0, 3.0, 4.0)
    )
    if stable_interior and continuation >= 3:
        return "NO_ATTACHMENT_WITH_EVIDENCE"
    return "ATTACHMENT_UNRESOLVED"


def _normal_source_profile(
    point: np.ndarray,
    *,
    normal: np.ndarray,
    gray: np.ndarray,
    binary: np.ndarray,
) -> frozenset[int]:
    return frozenset(
        offset
        for offset in range(-8, 9)
        if _pixel_is_source(
            int(round(float((point + normal * float(offset))[0]))),
            int(round(float((point + normal * float(offset))[1]))),
            gray=gray,
            binary=binary,
        )
    )


def _point_has_source(
    point: np.ndarray,
    normal: np.ndarray,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
    normal_radius: int,
) -> bool:
    for offset in range(-normal_radius, normal_radius + 1):
        sample = point + normal * float(offset)
        x = int(round(float(sample[0])))
        y = int(round(float(sample[1])))
        if (
            0 <= y < gray.shape[0]
            and 0 <= x < gray.shape[1]
            and int(gray[y, x]) <= 150
            and int(binary[y, x]) < 128
        ):
            return True
    return False


def _cross_section_width(
    point: np.ndarray,
    normal: np.ndarray,
    *,
    gray: np.ndarray,
    binary: np.ndarray,
) -> int:
    width = 0
    for offset in range(-8, 9):
        sample = point + normal * float(offset)
        x = int(round(float(sample[0])))
        y = int(round(float(sample[1])))
        if (
            0 <= y < gray.shape[0]
            and 0 <= x < gray.shape[1]
            and int(gray[y, x]) <= 150
            and int(binary[y, x]) < 128
        ):
            width += 1
    return width




























def _measurement_claim_window(
    lines: Sequence[LineSegment], *, shape: tuple[int, int]
) -> tuple[tuple[slice, slice], tuple[np.ndarray, ...]]:
    """Draw unchanged production footprints without allocating a whole page.

    Include every endpoint and stroke cap, use the full-page thickness, and
    translate already rounded endpoints. Rounding after translation would
    change half-pixel endpoints. Only the original page edges clip a stroke.
    """
    endpoints = [((int(round(line.x1)), int(round(line.y1))),
                  (int(round(line.x2)), int(round(line.y2)))) for line in lines]
    thicknesses = [_production_claim_thickness(line, shape=shape) for line in lines]
    padding = max(thicknesses) + 2
    left = max(0, min(p[0] for pair in endpoints for p in pair) - padding)
    top = max(0, min(p[1] for pair in endpoints for p in pair) - padding)
    right = min(shape[1], max(p[0] for pair in endpoints for p in pair) + padding + 1)
    bottom = min(shape[0], max(p[1] for pair in endpoints for p in pair) + padding + 1)
    if right <= left or bottom <= top:
        empty = np.zeros((0, 0), np.uint8)
        return (slice(0, 0), slice(0, 0)), tuple(empty for _ in lines)
    claims = []
    for (start, end), thickness in zip(endpoints, thicknesses, strict=True):
        claim = np.zeros((bottom - top, right - left), np.uint8)
        cv2.line(claim, (start[0] - left, start[1] - top),
                 (end[0] - left, end[1] - top), 255, thickness, cv2.LINE_8)
        claims.append(claim)
    return (slice(top, bottom), slice(left, right)), tuple(claims)


def _source_bound_raster_alias(
    keeper: LineSegment, candidate: LineSegment, *, gray: np.ndarray,
    binary: np.ndarray, protected_mask: np.ndarray,
) -> bool:
    """Certify an entire contained observation, including its source end caps.

    Pixel-track agreement is only retrieval. Independent source runs, blank
    stations, protected ink, or endpoints outside the keeper's original caps
    prevent consolidation, even when the production footprints overlap.
    """
    origins = [set(h for h in line.history if h.startswith("detected:"))
               for line in (keeper, candidate)]
    if not all(origins) or origins[0] == origins[1]:
        return False
    ends = [tuple((round(x), round(y)) for x, y in
                  ((line.x1, line.y1), (line.x2, line.y2)))
            for line in (keeper, candidate)]
    axis = 0 if ends[0][0][1] == ends[0][1][1] else 1
    normal = 1 - axis
    if any(pair[0][normal] != pair[1][normal] for pair in ends):
        return False
    if ends[0][0][normal] != ends[1][0][normal]:
        return False
    bounds = [sorted((pair[0][axis], pair[1][axis])) for pair in ends]
    cap = _production_claim_thickness(keeper, shape=binary.shape) // 2
    if (bounds[1][0] < bounds[0][0] or bounds[1][1] > bounds[0][1]
            or bounds[1][0] - bounds[0][0] > cap
            or bounds[0][1] - bounds[1][1] > cap
            or bounds[1][1] - bounds[1][0] <= 2 * cap):
        return False
    window, (left, right) = _measurement_claim_window(
        (keeper, candidate), shape=binary.shape)
    if not left.size or np.any((right > 0) & (left == 0)):
        return False
    union = left > 0
    if np.any(union & (protected_mask[window] > 0)):
        return False
    # Scan every axial station of both observations, excluding only their
    # already-contained original end caps. Use the gray raster as well as the
    # binary raster so a faint separate stroke cannot be assumed absent.
    plausible = (gray[window] < 245) | (binary[window] < 245)
    strong = (gray[window] <= 150) & (binary[window] < 128)
    if axis == 1:
        plausible, strong, left, right = (
            value.T for value in (plausible, strong, left, right))
    offset = window[1].start if axis == 0 else window[0].start
    for coordinate in range(bounds[0][0] + cap, bounds[0][1] - cap + 1):
        column = coordinate - offset
        band = np.flatnonzero(plausible[:, column])
        if (not band.size or np.any(np.diff(band) != 1)
                or band[0] == 0 or band[-1] == plausible.shape[0] - 1
                or not np.any(strong[band, column])):
            return False
        # Both footprints must independently bind to the complete unique band.
        if np.any(left[band, column] == 0) or np.any(right[band, column] == 0):
            return False
    return True


def _claim_measurements(
    line: LineSegment,
    *,
    masks: Mapping[str, np.ndarray],
    protected_mask: np.ndarray,
    source_binary: np.ndarray,
) -> dict[str, int]:
    window, (claim,) = _measurement_claim_window((line,), shape=source_binary.shape)
    if not claim.size:
        return dict.fromkeys(("source_pixels", "new_source_pixels",
            "protected_source_pixels", "semantic_conflict_source_pixels",
            "residual_source_pixels"), 0)
    source = source_binary[window] < 128
    claimed_source = (claim > 0) & source
    semantic_conflict = cv2.max(
        cv2.max(masks["text"][window], masks["graphic"][window]),
        cv2.max(masks["logo"][window], masks["signature"][window]),
    )
    return {
        "source_pixels": int(np.count_nonzero(claimed_source)),
        "new_source_pixels": int(
            np.count_nonzero(claimed_source & (masks["line"][window] == 0))
        ),
        "protected_source_pixels": int(
            np.count_nonzero(claimed_source & (protected_mask[window] > 0))
        ),
        "semantic_conflict_source_pixels": int(
            np.count_nonzero(claimed_source & (semantic_conflict > 0))
        ),
        "residual_source_pixels": int(
            np.count_nonzero(claimed_source & (masks["residual"][window] > 0))
        ),
    }




def _claim_delta_measurements(
    parent: LineSegment,
    piece: LineSegment,
    *,
    protected_mask: np.ndarray,
    source_binary: np.ndarray,
) -> dict[str, int]:
    window, (parent_claim, piece_claim) = _measurement_claim_window(
        (parent, piece), shape=source_binary.shape)
    if not piece_claim.size:
        return dict.fromkeys(("new_source_pixels", "new_protected_source_pixels",
                              "inherited_protected_source_pixels"), 0)
    source = source_binary[window] < 128
    delta = (piece_claim > 0) & (parent_claim == 0)
    inherited = (piece_claim > 0) & (parent_claim > 0) & source
    return {
        "new_source_pixels": int(np.count_nonzero(delta & source)),
        "new_protected_source_pixels": int(
            np.count_nonzero(delta & source & (protected_mask[window] > 0))
        ),
        "inherited_protected_source_pixels": int(
            np.count_nonzero(inherited & (protected_mask[window] > 0))
        ),
    }


def _piece_payload(
    piece_id: str,
    parent_id: str,
    line: LineSegment,
    interval: ParameterInterval,
    *,
    parent_line: LineSegment,
    action: str,
    claim_mode: str,
    masks: Mapping[str, np.ndarray],
    protected_mask: np.ndarray,
    source_binary: np.ndarray,
) -> dict[str, object]:
    claim = _claim_measurements(
        line,
        masks=masks,
        protected_mask=protected_mask,
        source_binary=source_binary,
    )
    delta = _claim_delta_measurements(
        parent_line,
        line,
        protected_mask=protected_mask,
        source_binary=source_binary,
    )
    inherited = (
        delta["inherited_protected_source_pixels"]
        if claim_mode == "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
        else 0
    )
    return {
        "piece_id": piece_id,
        "parent_id": parent_id,
        "parent_parameter_interval": [float(interval.start), float(interval.end)],
        "interval": interval.payload((f"support:{parent_id}",)),
        "geometry_px": _geometry_payload(line),
        "line_payload": _line_payload(line),
        "source_ids": list(line.source_ids),
        "history": list(line.history),
        "start_endpoint_id": (
            f"{parent_id}:start"
            if interval.start <= 0.0
            else f"{piece_id}:start:DERIVED_COVERAGE_CUT"
        ),
        "end_endpoint_id": (
            f"{parent_id}:end"
            if interval.end >= parent_line.length
            else f"{piece_id}:end:DERIVED_COVERAGE_CUT"
        ),
        "support_evidence_refs": [f"support:{parent_id}"],
        "claim_mode": claim_mode,
        "new_source_claim_pixels": (
            delta["new_source_pixels"]
            if claim_mode == "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
            else claim["new_source_pixels"]
        ),
        "new_protected_source_claim_pixels": (
            delta["new_protected_source_pixels"]
            if claim_mode == "UNCHANGED_ALREADY_ACCEPTED_SUBSEGMENT"
            else (
                0
                if action == "BLOCK_AND_REVIEW"
                else claim["protected_source_pixels"]
            )
        ),
        "inherited_protected_source_claim_pixels": inherited,
        "inherited_contact_evidence_refs": (
            [f"protected-contact:{piece_id}"] if inherited else []
        ),
        "action": action,
    }


def _support_evidence_payload(
    representation_id: str,
    line: LineSegment,
    intervals: Sequence[ParameterInterval],
    gray: np.ndarray,
) -> dict[str, object]:
    left = max(0, int(math.floor(min(line.x1, line.x2))) - 2)
    top = max(0, int(math.floor(min(line.y1, line.y2))) - 2)
    right = min(gray.shape[1], int(math.ceil(max(line.x1, line.x2))) + 3)
    bottom = min(gray.shape[0], int(math.ceil(max(line.y1, line.y2))) + 3)
    return {
        "evidence_id": f"support:{representation_id}",
        "kind": "TRAJECTORY_BINDING",
        "artifact": "runtime-original-unclosed-source",
        "sha256": hashlib.sha256(gray[top:bottom, left:right].tobytes()).hexdigest(),
        "roi_px": [left, top, right, bottom],
        "producer_version": POLICY_VERSION,
        "intervals": [item.payload() for item in intervals],
        "result": "SUPPORTED" if intervals else "UNKNOWN",
        "measurements": {
            "supported_length_px": float(sum(item.length for item in intervals)),
            "observed_length_px": float(line.length),
            "gray_cutoff": 150,
            "binary_required": True,
        },
        "limitations": [
            "Detector IDs are observations, not physical stroke identities",
            "Support intervals do not make detector frontiers physical terminations",
        ],
    }


def _ownership_evidence_payload(
    representation_id: str,
    line: LineSegment,
    *,
    state: str,
    downgrades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if state == "MAIN_REJECTED":
        result = "CONTRADICTED"
    elif state in {"MAIN_ACCEPTED", "LEGACY_RESTORATION_ACCEPTED"}:
        result = "SUPPORTED"
    else:
        result = "UNKNOWN"
    digest_source = {
        "representation_id": representation_id,
        "state": state,
        "downgrades": [dict(item) for item in downgrades],
    }
    return {
        "evidence_id": f"ownership:{representation_id}",
        "kind": "OWNERSHIP_DECISION",
        "artifact": "runtime-content-ownership",
        "sha256": _digest_payload(digest_source),
        "roi_px": [
            float(min(line.x1, line.x2)),
            float(min(line.y1, line.y2)),
            float(max(line.x1, line.x2)),
            float(max(line.y1, line.y2)),
        ],
        "producer_version": POLICY_VERSION,
        "intervals": [ParameterInterval(0.0, line.length).payload()],
        "result": result,
        "measurements": {
            "ownership_state": state,
            "downgrades": [dict(item) for item in downgrades],
        },
        "limitations": [
            "Ownership decides semantic eligibility, not same-stroke relation"
        ],
    }


def _relation_evidence_payload(
    cell: RelationCell,
    index: int,
) -> dict[str, object]:
    return {
        "evidence_id": cell.evidence_id,
        "kind": (
            "SOURCE_BAND_RUNS"
            if cell.relation is not Relation.RELATION_UNRESOLVED
            else "UNCERTAINTY"
        ),
        "artifact": "runtime-original-unclosed-source",
        "sha256": hashlib.sha256(
            f"{cell.left_id}|{cell.right_id}|{cell.measurements}".encode()
        ).hexdigest(),
        "roi_px": [0, 0, 0, 0],
        "producer_version": POLICY_VERSION,
        "intervals": [cell.right_interval.payload()],
        "result": (
            "UNKNOWN" if cell.relation is Relation.RELATION_UNRESOLVED else "SUPPORTED"
        ),
        "measurements": dict(cell.measurements),
        "limitations": [
            "Certificate is interval-local and non-transitive",
            "No physical pen/stroke-instance identity is asserted",
            f"evidence-sequence={index}",
        ],
    }


def _endpoint_records(
    representation_id: str,
    line: LineSegment,
) -> list[dict[str, object]]:
    return [
        {
            "endpoint_id": f"{representation_id}:start",
            "representation_id": representation_id,
            "point_px": [float(line.x1), float(line.y1)],
            "parameter": 0.0,
            "kind": "OBSERVED_DETECTOR_ENDPOINT",
            "independent_editable_obligation": "UNKNOWN",
            "evidence_refs": [],
            "disposition": "RETAIN_AS_OBSERVATION_EVIDENCE",
        },
        {
            "endpoint_id": f"{representation_id}:end",
            "representation_id": representation_id,
            "point_px": [float(line.x2), float(line.y2)],
            "parameter": float(line.length),
            "kind": "OBSERVED_DETECTOR_ENDPOINT",
            "independent_editable_obligation": "UNKNOWN",
            "evidence_refs": [],
            "disposition": "RETAIN_AS_OBSERVATION_EVIDENCE",
        },
    ]


def _disposition(
    representation_id: str,
    disposition: str,
    replacement_piece_ids: Sequence[str],
    intervals: Sequence[ParameterInterval],
    reason: str,
    *,
    removed_intervals: Sequence[ParameterInterval] = (),
    retained_keeper_piece_ids: Sequence[str] = (),
    rejected_intervals: Sequence[ParameterInterval] = (),
    rejected_root_observation_ids: Sequence[str] = (),
    rejected_scope_dispositions: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "representation_id": representation_id,
        "disposition": disposition,
        "replacement_piece_ids": list(replacement_piece_ids),
        "intervals": [item.payload() for item in intervals],
        "removed_intervals": [item.payload() for item in removed_intervals],
        "retained_keeper_piece_ids": list(retained_keeper_piece_ids),
        "rejected_intervals": [item.payload() for item in rejected_intervals],
        "rejected_root_observation_ids": list(rejected_root_observation_ids),
        "rejected_scope_dispositions": list(rejected_scope_dispositions),
        "reason": reason,
    }


def _transaction_operation(
    supersession: Sequence[Mapping[str, object]],
) -> Operation:
    dispositions = {str(item["disposition"]) for item in supersession}
    if TerminalDisposition.BLOCKED.value in dispositions:
        return Operation.BLOCK_AND_REVIEW
    if TerminalDisposition.SPLIT.value in dispositions:
        return Operation.KEEP_NOVEL_INTERVAL_ONLY
    if TerminalDisposition.SUPERSEDED_EQUIVALENT.value in dispositions:
        return Operation.KEEP_ONE_EQUIVALENT_REPRESENTATION
    return Operation.KEEP_BOTH


def _ledger_basis(representations: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not representations:
        return {
            "origin_px": [0.0, 0.0],
            "unit_tangent": [1.0, 0.0],
            "unit_normal": [0.0, 1.0],
            "basis_source_representation_id": "EMPTY_INPUT",
            "units": "source_pixels",
        }
    first = representations[0]
    geometry = first["geometry_px"]
    if not isinstance(geometry, Mapping):
        raise AssertionError("Invalid reconciliation basis geometry")
    start = np.asarray(geometry["start"], dtype=float)
    end = np.asarray(geometry["end"], dtype=float)
    vector = end - start
    norm = float(np.linalg.norm(vector))
    tangent = np.array([1.0, 0.0]) if norm <= 1e-9 else vector / norm
    normal = np.array([-tangent[1], tangent[0]])
    return {
        "origin_px": [float(start[0]), float(start[1])],
        "unit_tangent": [float(tangent[0]), float(tangent[1])],
        "unit_normal": [float(normal[0]), float(normal[1])],
        "basis_source_representation_id": str(first["representation_id"]),
        "units": "source_pixels",
    }


def _representation_id(
    route: RouteOrigin,
    observation_id: str,
    stable_index: int,
    source_ids: Sequence[str] = (),
) -> str:
    del stable_index
    source = "+".join(source_ids) if source_ids else "ANONYMOUS"
    return f"{route.value}:{source}:REP:{observation_id}"


def _stable_line_key(line: LineSegment) -> tuple[object, ...]:
    return (
        tuple(line.source_ids),
        round(float(line.x1), 9),
        round(float(line.y1), 9),
        round(float(line.x2), 9),
        round(float(line.y2), 9),
        round(float(line.width), 9),
        tuple(line.history),
    )


def _piece_id(
    parent_id: str,
    piece_index: int,
    start: float,
    end: float,
) -> str:
    return f"{parent_id}:piece-{piece_index:03d}:{start:.9f}-{end:.9f}"


def _observation_key(route: RouteOrigin, line: LineSegment) -> str:
    return f"{route.value}:{_line_identity_key(line)}"




def _acceptance_identity_key(line: LineSegment) -> str:
    """Exact semantic member identity for scoped restoration acceptance.

    Source scope and acceptance version are bound by the surrounding record.
    This key binds exact oriented geometry, member identity, representation
    role, and behavior-bearing confidences.  Audit history and diagnostic
    reasons are deliberately excluded: they neither grant nor revoke authority.
    """

    return json.dumps(
        {
            "geometry": {
                "x1": float(line.x1).hex(),
                "y1": float(line.y1).hex(),
                "x2": float(line.x2).hex(),
                "y2": float(line.y2).hex(),
                "width": float(line.width).hex(),
            },
            "source_ids": list(line.source_ids),
            "layer": line.layer,
            "confidence": float(line.confidence).hex(),
            "classification_confidence": float(
                line.classification_confidence
            ).hex(),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )




def _source_claim_id(line: LineSegment) -> str:
    return hashlib.sha256(_geometry_key(line).encode()).hexdigest()
















def _lines_digest(lines: Sequence[LineSegment]) -> str:
    payload = [_line_payload(line) for line in lines]
    return _digest_payload(payload)


def _digest_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
