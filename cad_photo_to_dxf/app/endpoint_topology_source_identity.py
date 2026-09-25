"""DEV-only endpoint/topology evidence for source-stroke pair identity.

The contract in this module is deliberately evidence preserving.  It consumes
``SourceStrokeInstance`` and ``CoincidentStrokeGroup`` records without changing
them, and it never treats collinearity, proximity, or a small gap as proof that
two fragments share a source identity.

Raster topology is local evidence, not a semantic classifier.  A crossing is
distinguished from a termination by testing whether the axial ridge continues
through the endpoint.  Missing evidence remains ambiguous.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import cv2
import numpy as np

from .source_stroke_multiplicity import (
    CoincidentStrokeGroup,
    MultiplicityState,
    SourceStrokeInstance,
)


class SourceIdentityStatus(str, Enum):
    SUPPORTED = "SOURCE_IDENTITY_SUPPORTED"
    REJECTED = "SOURCE_IDENTITY_REJECTED"
    AMBIGUOUS = "SOURCE_IDENTITY_AMBIGUOUS"


class PositiveIdentityEvidence(str, Enum):
    SHARED_CONFIRMED_SOURCE_STROKE = "SHARED_CONFIRMED_SOURCE_STROKE"
    CONTINUATION_TOPOLOGY_SUPPORTED = "CONTINUATION_TOPOLOGY_SUPPORTED"
    CROSSING_WITH_AXIAL_CONTINUATION = "CROSSING_WITH_AXIAL_CONTINUATION"


class NegativeIdentityEvidence(str, Enum):
    DISTINCT_CONFIRMED_SOURCE_INSTANCES = "DISTINCT_CONFIRMED_SOURCE_INSTANCES"
    INDEPENDENT_ENDPOINT_TERMINATION = "INDEPENDENT_ENDPOINT_TERMINATION"
    CORNER_TERMINATION = "CORNER_TERMINATION"
    JUNCTION_TERMINATION = "JUNCTION_TERMINATION"
    COMPETING_SOURCE_STROKE_IDENTITY = "COMPETING_SOURCE_STROKE_IDENTITY"
    MULTIPLICITY_CHANGE_ACROSS_GAP = "MULTIPLICITY_CHANGE_ACROSS_GAP"


class IdentityAmbiguityReason(str, Enum):
    NO_POSITIVE_SOURCE_IDENTITY = "NO_POSITIVE_SOURCE_IDENTITY"
    RASTER_TOPOLOGY_INCONCLUSIVE = "RASTER_TOPOLOGY_INCONCLUSIVE"
    SOURCE_MULTIPLICITY_AMBIGUOUS = "SOURCE_MULTIPLICITY_AMBIGUOUS"
    ENDPOINT_EVIDENCE_WEAK = "ENDPOINT_EVIDENCE_WEAK"


@dataclass(frozen=True)
class EndpointTopologyProfile:
    endpoint_id: str
    source_stroke_id: str
    position: tuple[float, float]
    local_tangent: tuple[float, float]
    termination_strength: float
    corner_evidence: float
    t_junction_evidence: float
    crossing_evidence: float
    continuing_ridge_evidence: float
    competing_stroke_ids: tuple[str, ...]
    local_multiplicity: int
    endpoint_component_id: int | None
    topology_confidence: float
    incoming_ridge_evidence: float
    transverse_negative_evidence: float
    transverse_positive_evidence: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["position"] = list(self.position)
        payload["local_tangent"] = list(self.local_tangent)
        payload["competing_stroke_ids"] = list(self.competing_stroke_ids)
        return payload


@dataclass(frozen=True)
class SourcePairIdentityEvidence:
    pair_id: str
    stroke_a_id: str
    stroke_b_id: str
    positive_evidence: tuple[str, ...]
    negative_evidence: tuple[str, ...]
    ambiguity_reasons: tuple[str, ...]
    identity_status: SourceIdentityStatus
    confidence: float
    endpoint_a: EndpointTopologyProfile | None
    endpoint_b: EndpointTopologyProfile | None
    gap_ridge_evidence: float | None
    tangent_delta_degrees: float
    lateral_offset_px: float
    pair_admission_action: str
    semantic_evidence_used: bool = False
    geometry_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["identity_status"] = self.identity_status.value
        payload["endpoint_a"] = self.endpoint_a.to_dict() if self.endpoint_a else None
        payload["endpoint_b"] = self.endpoint_b.to_dict() if self.endpoint_b else None
        return payload


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    if gray.ndim != 2:
        raise ValueError("endpoint topology requires one grayscale source image")
    source = gray.astype(np.uint8)
    blurred = cv2.GaussianBlur(source, (3, 3), 0)
    return (
        cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1] > 0
    )


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*vector)
    if length <= 1e-9:
        raise ValueError("source stroke geometry must have non-zero length")
    return vector[0] / length, vector[1] / length


def _sample_ray(
    ink: np.ndarray,
    origin: tuple[float, float],
    direction: tuple[float, float],
    *,
    distance: int,
    half_width: int = 1,
) -> float:
    normal = (-direction[1], direction[0])
    supported = 0
    total = 0
    for step in range(2, distance + 1):
        hit = False
        for offset in range(-half_width, half_width + 1):
            x = round(origin[0] + direction[0] * step + normal[0] * offset)
            y = round(origin[1] + direction[1] * step + normal[1] * offset)
            if 0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x]:
                hit = True
        supported += int(hit)
        total += 1
    return supported / max(1, total)


def _component_id(ink: np.ndarray, point: tuple[float, float]) -> int | None:
    count, labels = cv2.connectedComponents(ink.astype(np.uint8), 8)
    x, y = round(point[0]), round(point[1])
    if not (0 <= y < labels.shape[0] and 0 <= x < labels.shape[1]):
        return None
    label = int(labels[y, x])
    if label == 0:
        for radius in (1, 2):
            y0, y1 = max(0, y - radius), min(labels.shape[0], y + radius + 1)
            x0, x1 = max(0, x - radius), min(labels.shape[1], x + radius + 1)
            nearby = labels[y0:y1, x0:x1]
            nonzero = nearby[nearby > 0]
            if nonzero.size:
                label = int(np.bincount(nonzero).argmax())
                break
    return label if 0 < label < count else None


def _group_context(
    stroke: SourceStrokeInstance,
    point: tuple[float, float],
    groups: Sequence[CoincidentStrokeGroup],
) -> tuple[tuple[str, ...], int]:
    competitors: set[str] = set()
    multiplicity = 1
    for group in groups:
        if stroke.stroke_id not in group.member_stroke_ids:
            continue
        competitors.update(group.member_stroke_ids)
        dx = group.shared_axis.x2 - group.shared_axis.x1
        dy = group.shared_axis.y2 - group.shared_axis.y1
        length = max(math.hypot(dx, dy), 1e-9)
        direction = (dx / length, dy / length)
        coordinate = point[0] * direction[0] + point[1] * direction[1]
        local = [
            interval.multiplicity
            for interval in group.local_multiplicity_profile
            if interval.start - 1e-6 <= coordinate <= interval.end + 1e-6
        ]
        if local:
            multiplicity = max(multiplicity, max(local))
    competitors.discard(stroke.stroke_id)
    return tuple(sorted(competitors)), multiplicity


def profile_endpoint_topology(
    gray: np.ndarray,
    stroke: SourceStrokeInstance,
    endpoint_index: int,
    *,
    groups: Sequence[CoincidentStrokeGroup] = (),
    lookahead_px: int = 8,
) -> EndpointTopologyProfile:
    """Measure axial and transverse ink around one preserved endpoint.

    ``endpoint_index`` is 0 for the geometry start and 1 for its end.  The
    interior tangent always points from the endpoint into the source stroke.
    """

    if endpoint_index not in (0, 1):
        raise ValueError("endpoint_index must be 0 or 1")
    ink = _ink_mask(gray)
    geometry = stroke.geometry
    if endpoint_index == 0:
        point = (float(geometry.x1), float(geometry.y1))
        interior = _unit((geometry.x2 - geometry.x1, geometry.y2 - geometry.y1))
    else:
        point = (float(geometry.x2), float(geometry.y2))
        interior = _unit((geometry.x1 - geometry.x2, geometry.y1 - geometry.y2))
    outward = (-interior[0], -interior[1])
    normal = (-interior[1], interior[0])
    incoming = _sample_ray(ink, point, interior, distance=lookahead_px)
    continuing = _sample_ray(ink, point, outward, distance=lookahead_px)
    transverse_negative = _sample_ray(
        ink, point, (-normal[0], -normal[1]), distance=lookahead_px
    )
    transverse_positive = _sample_ray(ink, point, normal, distance=lookahead_px)

    both_transverse = min(transverse_negative, transverse_positive)
    one_transverse = max(transverse_negative, transverse_positive)
    termination = incoming * max(0.0, 1.0 - continuing)
    crossing = min(incoming, continuing, both_transverse)
    t_junction = min(incoming, both_transverse) * max(0.0, 1.0 - continuing)
    corner = (
        min(incoming, one_transverse)
        * max(0.0, 1.0 - continuing)
        * max(0.0, 1.0 - both_transverse)
    )
    competitors, multiplicity = _group_context(stroke, point, groups)
    signal = max(incoming, continuing, one_transverse)
    confidence = min(1.0, 0.5 * incoming + 0.5 * signal)
    endpoint = stroke.endpoints[endpoint_index]
    return EndpointTopologyProfile(
        endpoint_id=endpoint.endpoint_id,
        source_stroke_id=stroke.stroke_id,
        position=point,
        local_tangent=outward,
        termination_strength=round(termination, 6),
        corner_evidence=round(corner, 6),
        t_junction_evidence=round(t_junction, 6),
        crossing_evidence=round(crossing, 6),
        continuing_ridge_evidence=round(continuing, 6),
        competing_stroke_ids=competitors,
        local_multiplicity=multiplicity,
        endpoint_component_id=_component_id(ink, point),
        topology_confidence=round(confidence, 6),
        incoming_ridge_evidence=round(incoming, 6),
        transverse_negative_evidence=round(transverse_negative, 6),
        transverse_positive_evidence=round(transverse_positive, 6),
    )


def _direction(stroke: SourceStrokeInstance) -> tuple[float, float]:
    return _unit(
        (
            stroke.geometry.x2 - stroke.geometry.x1,
            stroke.geometry.y2 - stroke.geometry.y1,
        )
    )


def _tangent_delta(a: SourceStrokeInstance, b: SourceStrokeInstance) -> float:
    da, db = _direction(a), _direction(b)
    cosine = min(1.0, max(-1.0, abs(da[0] * db[0] + da[1] * db[1])))
    return math.degrees(math.acos(cosine))


def _lateral_offset(a: SourceStrokeInstance, b: SourceStrokeInstance) -> float:
    direction = _direction(a)
    normal = (-direction[1], direction[0])
    a_mid = ((a.geometry.x1 + a.geometry.x2) / 2, (a.geometry.y1 + a.geometry.y2) / 2)
    b_mid = ((b.geometry.x1 + b.geometry.x2) / 2, (b.geometry.y1 + b.geometry.y2) / 2)
    return abs((a_mid[0] - b_mid[0]) * normal[0] + (a_mid[1] - b_mid[1]) * normal[1])


def gap_ridge_evidence(
    gray: np.ndarray,
    endpoint_a: EndpointTopologyProfile,
    endpoint_b: EndpointTopologyProfile,
) -> float:
    """Return fraction of the endpoint-to-endpoint path supported by ink."""

    ink = _ink_mask(gray)
    ax, ay = endpoint_a.position
    bx, by = endpoint_b.position
    raw_length = math.hypot(bx - ax, by - ay)
    if raw_length <= 1e-9:
        x, y = round(ax), round(ay)
        return float(0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x])
    length = max(1, round(raw_length))
    direction = _unit((bx - ax, by - ay))
    normal = (-direction[1], direction[0])
    supported = 0
    total = 0
    for step in range(1, length):
        hit = False
        for offset in (-1, 0, 1):
            x = round(ax + direction[0] * step + normal[0] * offset)
            y = round(ay + direction[1] * step + normal[1] * offset)
            if 0 <= y < ink.shape[0] and 0 <= x < ink.shape[1] and ink[y, x]:
                hit = True
        supported += int(hit)
        total += 1
    return round(supported / max(1, total), 6)


def assess_source_pair_identity(
    pair_id: str,
    stroke_a: SourceStrokeInstance,
    stroke_b: SourceStrokeInstance,
    *,
    endpoint_a: EndpointTopologyProfile | None = None,
    endpoint_b: EndpointTopologyProfile | None = None,
    gap_support: float | None = None,
) -> SourcePairIdentityEvidence:
    """Classify pair identity without changing pair admission or geometry.

    Rejection requires confirmed disjoint identity or strong termination
    topology.  Ambiguity is intentionally retained when raster evidence cannot
    identify the physical source stroke.
    """

    positive: list[str] = []
    negative: list[str] = []
    ambiguity: list[str] = []
    tangent_delta = _tangent_delta(stroke_a, stroke_b)
    lateral_offset = _lateral_offset(stroke_a, stroke_b)

    same_id = stroke_a.stroke_id == stroke_b.stroke_id
    both_confirmed = (
        stroke_a.multiplicity_state is MultiplicityState.CONFIRMED
        and stroke_b.multiplicity_state is MultiplicityState.CONFIRMED
    )
    if same_id and both_confirmed:
        positive.append(PositiveIdentityEvidence.SHARED_CONFIRMED_SOURCE_STROKE.value)
    elif both_confirmed:
        negative.append(
            NegativeIdentityEvidence.DISTINCT_CONFIRMED_SOURCE_INSTANCES.value
        )

    profiles = tuple(profile for profile in (endpoint_a, endpoint_b) if profile)
    if any(profile.t_junction_evidence >= 0.6 for profile in profiles):
        negative.append(NegativeIdentityEvidence.JUNCTION_TERMINATION.value)
    if any(profile.corner_evidence >= 0.6 for profile in profiles):
        negative.append(NegativeIdentityEvidence.CORNER_TERMINATION.value)
    explicit_endpoint_structures = bool(stroke_a.endpoints[1].junction_ids) and bool(
        stroke_b.endpoints[0].junction_ids
    )
    if (
        len(profiles) == 2
        and (both_confirmed or explicit_endpoint_structures)
        and all(
            profile.termination_strength >= 0.65 and profile.topology_confidence >= 0.6
            for profile in profiles
        )
    ):
        negative.append(NegativeIdentityEvidence.INDEPENDENT_ENDPOINT_TERMINATION.value)
    competitors = {
        item for profile in profiles for item in profile.competing_stroke_ids
    }
    if competitors and both_confirmed:
        negative.append(NegativeIdentityEvidence.COMPETING_SOURCE_STROKE_IDENTITY.value)
    if (
        len(profiles) == 2
        and profiles[0].local_multiplicity != profiles[1].local_multiplicity
    ):
        negative.append(NegativeIdentityEvidence.MULTIPLICITY_CHANGE_ACROSS_GAP.value)

    crossing = any(profile.crossing_evidence >= 0.6 for profile in profiles)
    no_strong_termination = not any(
        reason in negative
        for reason in (
            NegativeIdentityEvidence.JUNCTION_TERMINATION.value,
            NegativeIdentityEvidence.CORNER_TERMINATION.value,
            NegativeIdentityEvidence.INDEPENDENT_ENDPOINT_TERMINATION.value,
        )
    )
    if crossing and gap_support is not None and gap_support >= 0.65:
        positive.append(PositiveIdentityEvidence.CROSSING_WITH_AXIAL_CONTINUATION.value)
    if (
        gap_support is not None
        and gap_support >= 0.7
        and tangent_delta <= 3.0
        and lateral_offset <= 2.0
        and no_strong_termination
        and not competitors
    ):
        positive.append(PositiveIdentityEvidence.CONTINUATION_TOPOLOGY_SUPPORTED.value)

    positive = list(dict.fromkeys(positive))
    negative = list(dict.fromkeys(negative))
    if same_id and both_confirmed:
        status = SourceIdentityStatus.SUPPORTED
        confidence = 1.0
    elif NegativeIdentityEvidence.DISTINCT_CONFIRMED_SOURCE_INSTANCES.value in negative:
        status = SourceIdentityStatus.REJECTED
        confidence = 1.0
    elif any(
        reason in negative
        for reason in (
            NegativeIdentityEvidence.JUNCTION_TERMINATION.value,
            NegativeIdentityEvidence.CORNER_TERMINATION.value,
            NegativeIdentityEvidence.INDEPENDENT_ENDPOINT_TERMINATION.value,
        )
    ):
        status = SourceIdentityStatus.REJECTED
        confidence = max(
            (
                max(
                    profile.t_junction_evidence,
                    profile.corner_evidence,
                    profile.termination_strength,
                )
                for profile in profiles
            ),
            default=0.6,
        )
    elif positive:
        status = SourceIdentityStatus.SUPPORTED
        confidence = max(0.7, gap_support or 0.0)
    else:
        status = SourceIdentityStatus.AMBIGUOUS
        confidence = 0.0
        ambiguity.extend(
            (
                IdentityAmbiguityReason.NO_POSITIVE_SOURCE_IDENTITY.value,
                IdentityAmbiguityReason.RASTER_TOPOLOGY_INCONCLUSIVE.value,
            )
        )
        if not both_confirmed:
            ambiguity.append(
                IdentityAmbiguityReason.SOURCE_MULTIPLICITY_AMBIGUOUS.value
            )
        if not profiles or any(
            profile.topology_confidence < 0.6 for profile in profiles
        ):
            ambiguity.append(IdentityAmbiguityReason.ENDPOINT_EVIDENCE_WEAK.value)

    action = (
        "REJECT_IN_DEV_ADMISSION"
        if status is SourceIdentityStatus.REJECTED
        else "CONTINUE_EXISTING_POLICY"
    )
    return SourcePairIdentityEvidence(
        pair_id=pair_id,
        stroke_a_id=stroke_a.stroke_id,
        stroke_b_id=stroke_b.stroke_id,
        positive_evidence=tuple(positive),
        negative_evidence=tuple(negative),
        ambiguity_reasons=tuple(dict.fromkeys(ambiguity)),
        identity_status=status,
        confidence=round(float(confidence), 6),
        endpoint_a=endpoint_a,
        endpoint_b=endpoint_b,
        gap_ridge_evidence=gap_support,
        tangent_delta_degrees=round(tangent_delta, 6),
        lateral_offset_px=round(lateral_offset, 6),
        pair_admission_action=action,
    )


__all__ = [
    "EndpointTopologyProfile",
    "IdentityAmbiguityReason",
    "NegativeIdentityEvidence",
    "PositiveIdentityEvidence",
    "SourceIdentityStatus",
    "SourcePairIdentityEvidence",
    "assess_source_pair_identity",
    "gap_ridge_evidence",
    "profile_endpoint_topology",
]
