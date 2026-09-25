"""Non-destructive DEV representation for source-stroke multiplicity.

This module is deliberately outside production reconstruction and rendering.
It keeps detector observations, source-stroke hypotheses, geometric grouping,
and derived consolidation as separate concepts.  Proximity never proves that
two observations came from the same source stroke.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import statistics
from typing import Iterable, Mapping, Sequence

from .line_detect import LineSegment


class MultiplicityState(str, Enum):
    CONFIRMED = "MULTIPLICITY_CONFIRMED"
    AMBIGUOUS = "MULTIPLICITY_AMBIGUOUS"


class GroupRelationship(str, Enum):
    EXACT_COINCIDENT = "EXACT_COINCIDENT"
    NEAR_COINCIDENT = "NEAR_COINCIDENT"


class PairIdentityStatus(str, Enum):
    SAME_SOURCE_SUPPORTED = "SAME_SOURCE_SUPPORTED"
    DISTINCT_SOURCE_REJECTED = "DISTINCT_SOURCE_REJECTED"
    MULTIPLICITY_AMBIGUOUS = "MULTIPLICITY_AMBIGUOUS"


def _point(value: Sequence[float]) -> tuple[float, float]:
    return float(value[0]), float(value[1])


def _line_payload(line: LineSegment) -> dict[str, object]:
    return {
        "start": [float(line.x1), float(line.y1)],
        "end": [float(line.x2), float(line.y2)],
        "width": float(line.width),
        "confidence": float(line.confidence),
    }


def _stable_id(prefix: str, parts: Iterable[object]) -> str:
    value = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class EndpointEvidence:
    endpoint_id: str
    point: tuple[float, float]
    confidence: float
    junction_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint_id": self.endpoint_id,
            "point": list(self.point),
            "confidence": float(self.confidence),
            "junction_ids": list(self.junction_ids),
            "provenance_ids": list(self.provenance_ids),
        }


@dataclass(frozen=True)
class SourceStrokeObservation:
    observation_id: str
    geometry: LineSegment
    source_instance_id: str | None = None
    endpoint_confidence: tuple[float, float] = (1.0, 1.0)
    start_junction_ids: tuple[str, ...] = ()
    end_junction_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    equivalence_evidence: tuple[str, ...] = ()

    @classmethod
    def from_line(
        cls,
        line: LineSegment,
        *,
        observation_id: str,
        source_instance_id: str | None = None,
        endpoint_confidence: tuple[float, float] = (1.0, 1.0),
        start_junction_ids: Sequence[str] = (),
        end_junction_ids: Sequence[str] = (),
        equivalence_evidence: Sequence[str] = (),
    ) -> "SourceStrokeObservation":
        provenance = tuple(str(value) for value in line.source_ids) or (
            observation_id,
        )
        return cls(
            observation_id=observation_id,
            geometry=line,
            source_instance_id=source_instance_id,
            endpoint_confidence=endpoint_confidence,
            start_junction_ids=tuple(start_junction_ids),
            end_junction_ids=tuple(end_junction_ids),
            provenance_ids=provenance,
            equivalence_evidence=tuple(equivalence_evidence),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "geometry": _line_payload(self.geometry),
            "source_instance_id": self.source_instance_id,
            "endpoint_confidence": list(self.endpoint_confidence),
            "start_junction_ids": list(self.start_junction_ids),
            "end_junction_ids": list(self.end_junction_ids),
            "provenance_ids": list(self.provenance_ids),
            "equivalence_evidence": list(self.equivalence_evidence),
        }


def _derived_equivalent_geometry(
    observations: Sequence[SourceStrokeObservation],
) -> LineSegment:
    """Create geometry only after an explicit instance ID proves equivalence."""

    first = observations[0].geometry
    dx = first.x2 - first.x1
    dy = first.y2 - first.y1
    length = max(math.hypot(dx, dy), 1e-9)
    direction = (dx / length, dy / length)
    normal = (-direction[1], direction[0])
    points = [
        point
        for observation in observations
        for point in (observation.geometry.p1, observation.geometry.p2)
    ]
    projections = [float(point[0] * direction[0] + point[1] * direction[1]) for point in points]
    coordinates = [float(point[0] * normal[0] + point[1] * normal[1]) for point in points]
    coordinate = float(statistics.median(coordinates))
    start = min(projections)
    end = max(projections)
    p1 = (direction[0] * start + normal[0] * coordinate, direction[1] * start + normal[1] * coordinate)
    p2 = (direction[0] * end + normal[0] * coordinate, direction[1] * end + normal[1] * coordinate)
    return first.copy(
        x1=p1[0],
        y1=p1[1],
        x2=p2[0],
        y2=p2[1],
        source_ids=tuple(
            sorted(
                {
                    source_id
                    for observation in observations
                    for source_id in observation.provenance_ids
                }
            )
        ),
        history=tuple(
            dict.fromkeys(
                (*first.history, "derived_after_proven_source_equivalence")
            )
        ),
    )


@dataclass(frozen=True)
class SourceStrokeInstance:
    stroke_id: str
    geometry: LineSegment
    endpoints: tuple[EndpointEvidence, EndpointEvidence]
    observations: tuple[SourceStrokeObservation, ...]
    multiplicity_state: MultiplicityState
    group_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "stroke_id": self.stroke_id,
            "geometry": _line_payload(self.geometry),
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "observation_ids": [item.observation_id for item in self.observations],
            "observations": [item.to_dict() for item in self.observations],
            "multiplicity_state": self.multiplicity_state.value,
            "group_ids": list(self.group_ids),
        }


@dataclass(frozen=True)
class MultiplicityProfileInterval:
    start: float
    end: float
    member_stroke_ids: tuple[str, ...]

    @property
    def multiplicity(self) -> int:
        return len(self.member_stroke_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "multiplicity": self.multiplicity,
            "member_stroke_ids": list(self.member_stroke_ids),
        }


@dataclass(frozen=True)
class CoincidentStrokeGroup:
    group_id: str
    member_stroke_ids: tuple[str, ...]
    relationship: GroupRelationship
    shared_axis: LineSegment
    local_multiplicity_profile: tuple[MultiplicityProfileInterval, ...]
    member_geometry: tuple[tuple[str, dict[str, object]], ...]
    member_endpoint_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "member_stroke_ids": list(self.member_stroke_ids),
            "relationship": self.relationship.value,
            "shared_axis": _line_payload(self.shared_axis),
            "local_multiplicity_profile": [
                item.to_dict() for item in self.local_multiplicity_profile
            ],
            "member_geometry": {
                stroke_id: payload for stroke_id, payload in self.member_geometry
            },
            "member_endpoint_ids": list(self.member_endpoint_ids),
            "destructive": False,
            "member_provenance_preserved": True,
        }


@dataclass(frozen=True)
class DerivedConsolidatedHypothesis:
    hypothesis_id: str
    geometry: LineSegment
    member_stroke_ids: tuple[str, ...]
    member_geometry: tuple[tuple[str, dict[str, object]], ...]
    member_endpoint_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "geometry": _line_payload(self.geometry),
            "member_stroke_ids": list(self.member_stroke_ids),
            "member_geometry": {
                stroke_id: payload for stroke_id, payload in self.member_geometry
            },
            "member_endpoint_ids": list(self.member_endpoint_ids),
            "derived_only": True,
            "replaces_members": False,
        }


@dataclass(frozen=True)
class PairIdentityDecision:
    status: PairIdentityStatus
    admitted: bool
    reason: str
    left_stroke_ids: tuple[str, ...]
    right_stroke_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "admitted": self.admitted,
            "reason": self.reason,
            "left_stroke_ids": list(self.left_stroke_ids),
            "right_stroke_ids": list(self.right_stroke_ids),
        }


class SourceStrokeRegistry:
    """Immutable-member registry; grouping never deletes source instances."""

    def __init__(self, strokes: Sequence[SourceStrokeInstance]) -> None:
        identifiers = [stroke.stroke_id for stroke in strokes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("stroke_id must be unique")
        self._strokes = tuple(strokes)

    @classmethod
    def from_observations(
        cls, observations: Sequence[SourceStrokeObservation]
    ) -> "SourceStrokeRegistry":
        grouped: dict[str, list[SourceStrokeObservation]] = {}
        states: dict[str, MultiplicityState] = {}
        for observation in observations:
            if observation.source_instance_id:
                key = observation.source_instance_id
                states[key] = MultiplicityState.CONFIRMED
            else:
                key = f"HYPOTHESIS:{observation.observation_id}"
                states[key] = MultiplicityState.AMBIGUOUS
            grouped.setdefault(key, []).append(observation)

        strokes: list[SourceStrokeInstance] = []
        for stroke_id in sorted(grouped):
            members = tuple(grouped[stroke_id])
            if len(members) > 1 and not all(
                member.equivalence_evidence for member in members
            ):
                raise ValueError(
                    "shared source_instance_id requires independent equivalence evidence"
                )
            geometry = (
                members[0].geometry
                if len(members) == 1
                else _derived_equivalent_geometry(members)
            )
            provenance = tuple(
                sorted(
                    {
                        source_id
                        for member in members
                        for source_id in member.provenance_ids
                    }
                )
            )
            start_confidence = min(item.endpoint_confidence[0] for item in members)
            end_confidence = min(item.endpoint_confidence[1] for item in members)
            starts = tuple(
                sorted({value for item in members for value in item.start_junction_ids})
            )
            ends = tuple(
                sorted({value for item in members for value in item.end_junction_ids})
            )
            endpoints = (
                EndpointEvidence(
                    f"{stroke_id}:START",
                    _point((geometry.x1, geometry.y1)),
                    start_confidence,
                    starts,
                    provenance,
                ),
                EndpointEvidence(
                    f"{stroke_id}:END",
                    _point((geometry.x2, geometry.y2)),
                    end_confidence,
                    ends,
                    provenance,
                ),
            )
            strokes.append(
                SourceStrokeInstance(
                    stroke_id=stroke_id,
                    geometry=geometry,
                    endpoints=endpoints,
                    observations=members,
                    multiplicity_state=states[stroke_id],
                )
            )
        return cls(strokes)

    @property
    def strokes(self) -> tuple[SourceStrokeInstance, ...]:
        return self._strokes

    def by_id(self, stroke_id: str) -> SourceStrokeInstance:
        return next(stroke for stroke in self._strokes if stroke.stroke_id == stroke_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_stroke_count": len(self._strokes),
            "strokes": [stroke.to_dict() for stroke in self._strokes],
        }


def capture_line_hypotheses(
    lines: Sequence[LineSegment],
    *,
    confirmed_instance_ids: Mapping[str, str] | None = None,
) -> SourceStrokeRegistry:
    """Capture every geometry without resurrecting lost per-ID geometry.

    ``confirmed_instance_ids`` maps observation IDs to independently proven
    source instance IDs.  Aggregated ``LineSegment.source_ids`` are provenance,
    not authority to fabricate one geometry per historic ID.
    """

    confirmed = dict(confirmed_instance_ids or {})
    observations = []
    for index, line in enumerate(lines):
        observation_id = f"line-observation-{index:06d}"
        observations.append(
            SourceStrokeObservation.from_line(
                line,
                observation_id=observation_id,
                source_instance_id=confirmed.get(observation_id),
            )
        )
    return SourceStrokeRegistry.from_observations(observations)


def _basis(line: LineSegment) -> tuple[tuple[float, float], tuple[float, float]]:
    dx = line.x2 - line.x1
    dy = line.y2 - line.y1
    length = max(math.hypot(dx, dy), 1e-9)
    direction = (dx / length, dy / length)
    return direction, (-direction[1], direction[0])


def _projection_interval(
    line: LineSegment, direction: tuple[float, float]
) -> tuple[float, float]:
    values = (
        line.x1 * direction[0] + line.y1 * direction[1],
        line.x2 * direction[0] + line.y2 * direction[1],
    )
    return min(values), max(values)


def _angle_difference(left: LineSegment, right: LineSegment) -> float:
    delta = abs(left.angle - right.angle) % 180.0
    return min(delta, 180.0 - delta)


def _compatible(
    left: SourceStrokeInstance,
    right: SourceStrokeInstance,
    *,
    distance_tolerance: float,
    angle_tolerance: float,
    endpoint_gap_tolerance: float,
) -> bool:
    if _angle_difference(left.geometry, right.geometry) > angle_tolerance:
        return False
    direction, normal = _basis(left.geometry)
    left_coordinate = (
        left.geometry.midpoint[0] * normal[0]
        + left.geometry.midpoint[1] * normal[1]
    )
    right_coordinate = (
        right.geometry.midpoint[0] * normal[0]
        + right.geometry.midpoint[1] * normal[1]
    )
    if abs(float(left_coordinate - right_coordinate)) > distance_tolerance:
        return False
    left_start, left_end = _projection_interval(left.geometry, direction)
    right_start, right_end = _projection_interval(right.geometry, direction)
    gap = max(left_start - right_end, right_start - left_end, 0.0)
    return gap <= endpoint_gap_tolerance


def _derived_group_geometry(members: Sequence[SourceStrokeInstance]) -> LineSegment:
    observations = tuple(
        SourceStrokeObservation.from_line(
            member.geometry,
            observation_id=f"derived:{member.stroke_id}",
            source_instance_id="DERIVED_GROUP",
            equivalence_evidence=("DERIVED_GROUP_ONLY",),
        )
        for member in members
    )
    return _derived_equivalent_geometry(observations)


def _profile(
    members: Sequence[SourceStrokeInstance], shared_axis: LineSegment
) -> tuple[MultiplicityProfileInterval, ...]:
    direction, _normal = _basis(shared_axis)
    intervals = {
        member.stroke_id: _projection_interval(member.geometry, direction)
        for member in members
    }
    boundaries = sorted({value for interval in intervals.values() for value in interval})
    output: list[MultiplicityProfileInterval] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        midpoint = (start + end) * 0.5
        active = tuple(
            sorted(
                stroke_id
                for stroke_id, (low, high) in intervals.items()
                if low <= midpoint <= high
            )
        )
        if active:
            output.append(MultiplicityProfileInterval(start, end, active))
    return tuple(output)


def group_coincident_or_near_coincident(
    registry: SourceStrokeRegistry,
    *,
    distance_tolerance: float = 3.0,
    angle_tolerance: float = 3.0,
    endpoint_gap_tolerance: float = 0.0,
) -> tuple[CoincidentStrokeGroup, ...]:
    """Group compatible strokes without replacing or mutating any member."""

    remaining = set(range(len(registry.strokes)))
    groups: list[CoincidentStrokeGroup] = []
    while remaining:
        seed_index = min(remaining)
        remaining.remove(seed_index)
        member_indices = [seed_index]
        for candidate_index in sorted(tuple(remaining)):
            candidate = registry.strokes[candidate_index]
            if all(
                _compatible(
                    registry.strokes[index],
                    candidate,
                    distance_tolerance=distance_tolerance,
                    angle_tolerance=angle_tolerance,
                    endpoint_gap_tolerance=endpoint_gap_tolerance,
                )
                for index in member_indices
            ):
                member_indices.append(candidate_index)
                remaining.remove(candidate_index)
        if len(member_indices) < 2:
            continue
        members = tuple(registry.strokes[index] for index in member_indices)
        member_ids = tuple(sorted(member.stroke_id for member in members))
        shared_axis = _derived_group_geometry(members)
        base_direction, base_normal = _basis(members[0].geometry)
        del base_direction
        coordinates = [
            float(
                member.geometry.midpoint[0] * base_normal[0]
                + member.geometry.midpoint[1] * base_normal[1]
            )
            for member in members
        ]
        relationship = (
            GroupRelationship.EXACT_COINCIDENT
            if max(coordinates) - min(coordinates) <= 1e-6
            else GroupRelationship.NEAR_COINCIDENT
        )
        group_id = _stable_id("COINCIDENT-GROUP", member_ids)
        groups.append(
            CoincidentStrokeGroup(
                group_id=group_id,
                member_stroke_ids=member_ids,
                relationship=relationship,
                shared_axis=shared_axis,
                local_multiplicity_profile=_profile(members, shared_axis),
                member_geometry=tuple(
                    (member.stroke_id, _line_payload(member.geometry))
                    for member in members
                ),
                member_endpoint_ids=tuple(
                    endpoint.endpoint_id
                    for member in members
                    for endpoint in member.endpoints
                ),
            )
        )
    return tuple(groups)


def derive_consolidated_hypothesis(
    group: CoincidentStrokeGroup,
) -> DerivedConsolidatedHypothesis:
    """Return an optional rendering hypothesis with explicit member references."""

    return DerivedConsolidatedHypothesis(
        hypothesis_id=group.group_id.replace("COINCIDENT-GROUP", "DERIVED-LINE"),
        geometry=group.shared_axis,
        member_stroke_ids=group.member_stroke_ids,
        member_geometry=group.member_geometry,
        member_endpoint_ids=group.member_endpoint_ids,
    )


def assess_pair_identity(
    left: Sequence[SourceStrokeInstance],
    right: Sequence[SourceStrokeInstance],
) -> PairIdentityDecision:
    """Fail closed unless both fragments share positive source identity."""

    left_ids = tuple(sorted(stroke.stroke_id for stroke in left))
    right_ids = tuple(sorted(stroke.stroke_id for stroke in right))
    shared = set(left_ids).intersection(right_ids)
    if shared:
        return PairIdentityDecision(
            PairIdentityStatus.SAME_SOURCE_SUPPORTED,
            True,
            "independent source-stroke identity is shared by both fragments",
            left_ids,
            right_ids,
        )
    confirmed = all(
        stroke.multiplicity_state is MultiplicityState.CONFIRMED
        for stroke in (*left, *right)
    )
    if confirmed and left and right:
        return PairIdentityDecision(
            PairIdentityStatus.DISTINCT_SOURCE_REJECTED,
            False,
            "confirmed source-stroke identities are disjoint",
            left_ids,
            right_ids,
        )
    return PairIdentityDecision(
        PairIdentityStatus.MULTIPLICITY_AMBIGUOUS,
        False,
        "detector geometry does not independently prove shared source identity",
        left_ids,
        right_ids,
    )


__all__ = [
    "CoincidentStrokeGroup",
    "DerivedConsolidatedHypothesis",
    "EndpointEvidence",
    "GroupRelationship",
    "MultiplicityProfileInterval",
    "MultiplicityState",
    "PairIdentityDecision",
    "PairIdentityStatus",
    "SourceStrokeInstance",
    "SourceStrokeObservation",
    "SourceStrokeRegistry",
    "assess_pair_identity",
    "capture_line_hypotheses",
    "derive_consolidated_hypothesis",
    "group_coincident_or_near_coincident",
]
