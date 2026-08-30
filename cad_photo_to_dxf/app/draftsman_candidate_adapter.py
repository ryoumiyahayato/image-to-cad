"""Read-only adapters from existing detector outputs to typed candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, Sequence

import numpy as np

from .draftsman_candidate import (
    CandidateEvidenceRef,
    CandidateKind,
    CandidatePayloadValue,
    CandidateProducerIdentity,
    CandidateRelationship,
    CandidateRelationshipKind,
    CircleCandidatePayload,
    DraftsmanCandidateManifest,
    DraftsmanCandidateRecord,
    LineCandidatePayload,
    LogoCandidatePayload,
    SignatureCandidatePayload,
    StructuralRoiCandidatePayload,
    SymbolCandidatePayload,
    TextCandidatePayload,
)
from .draftsman_contract import (
    SourcePageRef,
    SourceRegionRef,
    TransformRef,
    canonical_json_bytes,
)


LINE_PRODUCER_VERSION = "line-detect-current-v1"
TEXT_PRODUCER_VERSION = "ocr-pipeline-current-v1"
LOGO_PRODUCER_VERSION = "logo-detection-current-v1"
SIGNATURE_PRODUCER_VERSION = "signature-detection-current-v1"
STRUCTURAL_ROI_PRODUCER_VERSION = "structural-roi-current-v1"
AUXILIARY_PRODUCER_VERSION = "legacy-auxiliary-current-v1"


class LineCandidateView(Protocol):
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    confidence: float
    layer: str
    source_ids: Sequence[str]
    history: Sequence[str]
    classification_confidence: float
    classification_reasons: Sequence[str]


class TextCandidateView(Protocol):
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    kind: str
    rotation_deg: float
    quad: tuple[tuple[float, float], ...] | None
    source: str
    character_boxes: Sequence[tuple[int, int, int, int]]
    replacement_safe: bool
    review_note: str


class LogoCandidateView(Protocol):
    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    structural_score: float
    hole_count: int
    contour_count: int
    visual_kind: str
    density: float
    closed_complexity: int
    reflection_similarity: float


class SignatureVisualEvidenceView(Protocol):
    source_component_count: int
    source_pixel_count: int
    density: float
    continuity: float
    directional_complexity: int
    positive_diagonal_span: float
    negative_diagonal_span: float
    bidirectional_diagonal_support: bool
    perimeter_per_pixel: float
    convex_solidity: float
    confidence: float


class SignatureCandidateView(Protocol):
    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    visual_evidence: SignatureVisualEvidenceView | None


class StructuralRoiView(Protocol):
    purpose: str
    bbox: tuple[int, int, int, int]
    line_indices: Sequence[int]
    evidence_intersections: Sequence[tuple[float, float]]
    confidence: float
    expansion_distance: float
    source_types: Sequence[str]


class CircleCandidateView(Protocol):
    center: tuple[float, float]
    radius: float
    confidence: float


class SymbolCandidateView(Protocol):
    kind: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class CandidateAdapterProducers:
    line: CandidateProducerIdentity
    text: CandidateProducerIdentity
    logo: CandidateProducerIdentity
    signature: CandidateProducerIdentity
    structural_roi: CandidateProducerIdentity
    circle: CandidateProducerIdentity | None = None
    symbol: CandidateProducerIdentity | None = None

    def active(self) -> tuple[CandidateProducerIdentity, ...]:
        values = (
            self.line,
            self.text,
            self.logo,
            self.signature,
            self.structural_roi,
            self.circle,
            self.symbol,
        )
        unique = {
            item.producer_config_id: item
            for item in values
            if item is not None
        }
        return tuple(unique[key] for key in sorted(unique))


def _bbox4(values: Sequence[int]) -> tuple[int, int, int, int]:
    if len(values) != 4:
        raise ValueError("Candidate bbox must contain x, y, width and height")
    return (int(values[0]), int(values[1]), int(values[2]), int(values[3]))


def current_candidate_producers(
    *,
    line_config: object,
    text_config: object,
    logo_config: object | None = None,
    signature_config: object | None = None,
    structural_roi_config: object,
    include_legacy_auxiliary: bool = False,
    diagnostic_metadata: object | None = None,
) -> CandidateAdapterProducers:
    """Bind detector/config identity without importing or changing detectors."""

    line = CandidateProducerIdentity.create(
        producer="app.line_detect.detect_lines",
        producer_version=LINE_PRODUCER_VERSION,
        producer_config=line_config,
        diagnostic_metadata=diagnostic_metadata,
    )
    text = CandidateProducerIdentity.create(
        producer="app.ocr_pipeline.recognize_text_candidates_optimized",
        producer_version=TEXT_PRODUCER_VERSION,
        producer_config=text_config,
        diagnostic_metadata=diagnostic_metadata,
    )
    logo = CandidateProducerIdentity.create(
        producer="app.logo_detection.detect_logo_regions",
        producer_version=LOGO_PRODUCER_VERSION,
        producer_config=logo_config or {"configuration": "module-defaults"},
        diagnostic_metadata=diagnostic_metadata,
    )
    signature = CandidateProducerIdentity.create(
        producer="app.signature_overlay.detect_signature_regions",
        producer_version=SIGNATURE_PRODUCER_VERSION,
        producer_config=signature_config or {"configuration": "module-defaults"},
        diagnostic_metadata=diagnostic_metadata,
    )
    structural_roi = CandidateProducerIdentity.create(
        producer="app.structural_roi.detect_structural_rois",
        producer_version=STRUCTURAL_ROI_PRODUCER_VERSION,
        producer_config=structural_roi_config,
        diagnostic_metadata=diagnostic_metadata,
    )
    auxiliary = (
        CandidateProducerIdentity.create(
            producer="app.auxiliary_recognition.recognize_auxiliary",
            producer_version=AUXILIARY_PRODUCER_VERSION,
            producer_config={"configuration": "module-defaults"},
            diagnostic_metadata=diagnostic_metadata,
        )
        if include_legacy_auxiliary
        else None
    )
    return CandidateAdapterProducers(
        line=line,
        text=text,
        logo=logo,
        signature=signature,
        structural_roi=structural_roi,
        circle=auxiliary,
        symbol=auxiliary,
    )


@dataclass(frozen=True)
class _CandidateSeed:
    candidate_kind: CandidateKind
    source_region: SourceRegionRef
    payload: CandidatePayloadValue
    confidence: float
    producer: CandidateProducerIdentity
    evidence_refs: tuple[CandidateEvidenceRef, ...] = ()
    diagnostic_metadata: object | None = None

    def occurrence_key(self) -> bytes:
        return canonical_json_bytes(
            {
                "candidate_kind": self.candidate_kind.value,
                "source_region": self.source_region.identity_payload(),
                "payload": self.payload.to_dict(),
                "confidence": self.confidence,
                "producer_config_id": self.producer.producer_config_id,
                "identity_evidence": [
                    item.identity_payload()
                    for item in self.evidence_refs
                    if item.identity_participates
                ],
            }
        )


def _materialize(
    seeds: Sequence[_CandidateSeed],
    *,
    source_page: SourcePageRef,
    transform: TransformRef,
) -> tuple[
    tuple[DraftsmanCandidateRecord, ...],
    tuple[tuple[str, ...], ...],
]:
    grouped_indices: dict[bytes, list[int]] = {}
    for index, seed in enumerate(seeds):
        grouped_indices.setdefault(seed.occurrence_key(), []).append(index)
    records: list[DraftsmanCandidateRecord] = []
    record_ids_by_key: dict[bytes, list[str]] = {}
    for key in sorted(grouped_indices):
        first_seed = seeds[grouped_indices[key][0]]
        for occurrence in range(1, len(grouped_indices[key]) + 1):
            record = DraftsmanCandidateRecord.create(
                source_page=source_page,
                source_region=first_seed.source_region,
                transform=transform,
                candidate_kind=first_seed.candidate_kind,
                payload=first_seed.payload,
                confidence=first_seed.confidence,
                producer=first_seed.producer,
                evidence_refs=first_seed.evidence_refs,
                occurrence=occurrence,
                diagnostic_metadata=first_seed.diagnostic_metadata,
            )
            records.append(record)
            record_ids_by_key.setdefault(key, []).append(
                record.stable_candidate_id
            )
    source_groups = tuple(
        tuple(record_ids_by_key[seed.occurrence_key()])
        for seed in seeds
    )
    return (
        tuple(sorted(records, key=lambda item: item.stable_candidate_id)),
        source_groups,
    )


def _line_seed(
    line: LineCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    start = (float(line.x1), float(line.y1))
    end = (float(line.x2), float(line.y2))
    region = SourceRegionRef(
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )
    source_evidence = tuple(
        CandidateEvidenceRef.create(
            evidence_kind="legacy-line-source-id",
            evidence_id=str(source_id),
            evidence_payload={"source_id": str(source_id)},
            # HOUGH/LSD ordinals follow detector enumeration and are retained
            # as evidence, but cannot make semantic identity order-dependent.
            identity_participates=False,
        )
        for source_id in sorted({str(item) for item in line.source_ids})
    )
    return _CandidateSeed(
        candidate_kind=CandidateKind.LINE_SEGMENT,
        source_region=region,
        payload=LineCandidatePayload(
            start=start,
            end=end,
            width=float(line.width),
            detector_history=tuple(str(item) for item in line.history),
            proposed_layer=str(line.layer),
            classification_confidence=float(line.classification_confidence),
            classification_reasons=tuple(
                str(item) for item in line.classification_reasons
            ),
        ),
        confidence=float(line.confidence),
        producer=producer,
        evidence_refs=source_evidence,
    )


def _text_seed(
    text: TextCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    bbox = _bbox4(text.bbox)
    quad = (
        None
        if text.quad is None
        else tuple(
            (float(point[0]), float(point[1]))
            for point in text.quad
        )
    )
    return _CandidateSeed(
        candidate_kind=CandidateKind.OCR_TEXT,
        source_region=SourceRegionRef.from_xywh(bbox),
        payload=TextCandidatePayload(
            raw_recognized_text=str(text.text),
            source_bbox=bbox,
            source_quad=quad,
            rotation_degrees=float(text.rotation_deg),
            orientation_evidence=(
                "source-quad-and-rotation"
                if quad is not None
                else "rotation-only-no-source-quad"
            ),
            detector_text_kind=str(text.kind),
            detector_source=str(text.source),
            character_boxes=tuple(_bbox4(box) for box in text.character_boxes),
            replacement_safe=bool(text.replacement_safe),
            review_note=str(text.review_note),
        ),
        confidence=float(text.confidence),
        producer=producer,
    )


def _logo_seed(
    logo: LogoCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    bbox = _bbox4(logo.bbox)
    mask = np.ascontiguousarray(logo.mask, dtype=np.uint8)
    return _CandidateSeed(
        candidate_kind=CandidateKind.LOGO,
        source_region=SourceRegionRef.from_xywh(bbox),
        payload=LogoCandidatePayload(
            source_bbox=bbox,
            source_mask_sha256=sha256(mask.tobytes()).hexdigest(),
            source_foreground_pixels=int(np.count_nonzero(mask)),
            visual_kind=str(logo.visual_kind),
            structural_score=float(logo.structural_score),
            hole_count=int(logo.hole_count),
            contour_count=int(logo.contour_count),
            density=float(logo.density),
            closed_complexity=int(logo.closed_complexity),
            reflection_similarity=float(logo.reflection_similarity),
        ),
        confidence=float(logo.structural_score),
        producer=producer,
    )


def _signature_seed(
    signature: SignatureCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    bbox = _bbox4(signature.bbox)
    mask = np.ascontiguousarray(signature.mask, dtype=np.uint8)
    visual = signature.visual_evidence
    confidence = 0.0 if visual is None else float(visual.confidence)
    return _CandidateSeed(
        candidate_kind=CandidateKind.SIGNATURE,
        source_region=SourceRegionRef.from_xywh(bbox),
        payload=SignatureCandidatePayload(
            source_bbox=bbox,
            source_mask_sha256=sha256(mask.tobytes()).hexdigest(),
            source_foreground_pixels=int(np.count_nonzero(mask)),
            source_component_count=(
                0 if visual is None else int(visual.source_component_count)
            ),
            density=0.0 if visual is None else float(visual.density),
            continuity=0.0 if visual is None else float(visual.continuity),
            directional_complexity=(
                0 if visual is None else int(visual.directional_complexity)
            ),
            positive_diagonal_span=(
                0.0 if visual is None else float(visual.positive_diagonal_span)
            ),
            negative_diagonal_span=(
                0.0 if visual is None else float(visual.negative_diagonal_span)
            ),
            bidirectional_diagonal_support=(
                False
                if visual is None
                else bool(visual.bidirectional_diagonal_support)
            ),
            perimeter_per_pixel=(
                0.0 if visual is None else float(visual.perimeter_per_pixel)
            ),
            convex_solidity=(
                0.0 if visual is None else float(visual.convex_solidity)
            ),
        ),
        confidence=max(0.0, min(1.0, confidence)),
        producer=producer,
    )


def _roi_seed(
    roi: StructuralRoiView,
    producer: CandidateProducerIdentity,
    related_line_ids: Sequence[str],
) -> _CandidateSeed:
    bbox = _bbox4(roi.bbox)
    purpose = str(roi.purpose)
    return _CandidateSeed(
        candidate_kind=(
            CandidateKind.TABLE_REGION
            if purpose == "table"
            else CandidateKind.STRUCTURAL_ROI
        ),
        source_region=SourceRegionRef.from_xywh(bbox),
        payload=StructuralRoiCandidatePayload(
            purpose=purpose,
            source_bbox=bbox,
            related_line_candidate_ids=tuple(sorted(set(related_line_ids))),
            evidence_intersections=tuple(
                (float(point[0]), float(point[1]))
                for point in roi.evidence_intersections
            ),
            expansion_distance=float(roi.expansion_distance),
            source_types=tuple(str(item) for item in roi.source_types),
        ),
        confidence=float(roi.confidence),
        producer=producer,
    )


def _circle_seed(
    circle: CircleCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    center = (float(circle.center[0]), float(circle.center[1]))
    radius = float(circle.radius)
    return _CandidateSeed(
        candidate_kind=CandidateKind.CIRCLE,
        source_region=SourceRegionRef(
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
        ),
        payload=CircleCandidatePayload(center=center, radius=radius),
        confidence=float(circle.confidence),
        producer=producer,
    )


def _symbol_seed(
    symbol: SymbolCandidateView,
    producer: CandidateProducerIdentity,
) -> _CandidateSeed:
    bbox = _bbox4(symbol.bbox)
    return _CandidateSeed(
        candidate_kind=CandidateKind.SYMBOL,
        source_region=SourceRegionRef.from_xywh(bbox),
        payload=SymbolCandidatePayload(
            detector_symbol_kind=str(symbol.kind),
            source_bbox=bbox,
        ),
        confidence=float(symbol.confidence),
        producer=producer,
    )


def adapt_line_candidates(
    lines: Sequence[LineCandidateView],
    *,
    source_page: SourcePageRef,
    transform: TransformRef,
    producer: CandidateProducerIdentity,
) -> tuple[DraftsmanCandidateRecord, ...]:
    records, _groups = _materialize(
        tuple(_line_seed(line, producer) for line in lines),
        source_page=source_page,
        transform=transform,
    )
    return records


def adapt_text_candidates(
    texts: Sequence[TextCandidateView],
    *,
    source_page: SourcePageRef,
    transform: TransformRef,
    producer: CandidateProducerIdentity,
) -> tuple[DraftsmanCandidateRecord, ...]:
    records, _groups = _materialize(
        tuple(_text_seed(text, producer) for text in texts),
        source_page=source_page,
        transform=transform,
    )
    return records


def _closed_regions_overlap(
    left: SourceRegionRef,
    right: SourceRegionRef,
) -> bool:
    return not (
        left.x_max < right.x_min
        or right.x_max < left.x_min
        or left.y_max < right.y_min
        or right.y_max < left.y_min
    )


def _region_contains(
    outer: SourceRegionRef,
    inner: SourceRegionRef,
) -> bool:
    return bool(
        outer.x_min <= inner.x_min
        and outer.y_min <= inner.y_min
        and outer.x_max >= inner.x_max
        and outer.y_max >= inner.y_max
    )


def infer_basic_spatial_relationships(
    candidates: Sequence[DraftsmanCandidateRecord],
    *,
    maximum_pairs: int = 10_000,
) -> tuple[CandidateRelationship, ...]:
    """Describe bbox overlap/containment only; never select or remove candidates."""

    if maximum_pairs < 0:
        raise ValueError("maximum_pairs must not be negative")
    relationships: list[CandidateRelationship] = []
    pair_count = 0
    ordered = sorted(candidates, key=lambda item: item.stable_candidate_id)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            pair_count += 1
            if pair_count > maximum_pairs:
                return tuple(
                    sorted(
                        relationships,
                        key=lambda item: item.stable_relationship_id,
                    )
                )
            if not _closed_regions_overlap(left.source_region, right.source_region):
                continue
            relationships.append(
                CandidateRelationship.create(
                    relationship_kind=CandidateRelationshipKind.OVERLAPS,
                    source_candidate_id=left.stable_candidate_id,
                    target_candidate_id=right.stable_candidate_id,
                    evidence={
                        "method": "closed-source-bbox-intersection",
                        "left_region": left.source_region.identity_payload(),
                        "right_region": right.source_region.identity_payload(),
                    },
                )
            )
            if _region_contains(left.source_region, right.source_region):
                relationships.append(
                    CandidateRelationship.create(
                        relationship_kind=CandidateRelationshipKind.CONTAINS,
                        source_candidate_id=left.stable_candidate_id,
                        target_candidate_id=right.stable_candidate_id,
                        evidence={"method": "source-bbox-containment"},
                    )
                )
            elif _region_contains(right.source_region, left.source_region):
                relationships.append(
                    CandidateRelationship.create(
                        relationship_kind=CandidateRelationshipKind.CONTAINS,
                        source_candidate_id=right.stable_candidate_id,
                        target_candidate_id=left.stable_candidate_id,
                        evidence={"method": "source-bbox-containment"},
                    )
                )
    return tuple(
        sorted(
            relationships,
            key=lambda item: item.stable_relationship_id,
        )
    )


def adapt_candidate_outputs(
    *,
    source_page: SourcePageRef,
    transform: TransformRef,
    producers: CandidateAdapterProducers,
    line_candidates: Sequence[LineCandidateView] = (),
    text_candidates: Sequence[TextCandidateView] = (),
    logo_candidates: Sequence[LogoCandidateView] = (),
    signature_candidates: Sequence[SignatureCandidateView] = (),
    structural_rois: Sequence[StructuralRoiView] = (),
    circle_candidates: Sequence[CircleCandidateView] = (),
    symbol_candidates: Sequence[SymbolCandidateView] = (),
    include_spatial_relationships: bool = False,
) -> DraftsmanCandidateManifest:
    """Preserve every supplied detector output in one deterministic manifest."""

    line_seeds = tuple(
        _line_seed(line, producers.line) for line in line_candidates
    )
    line_records, line_id_groups = _materialize(
        line_seeds,
        source_page=source_page,
        transform=transform,
    )
    other_seeds: list[_CandidateSeed] = []
    other_seeds.extend(
        _text_seed(text, producers.text) for text in text_candidates
    )
    other_seeds.extend(
        _logo_seed(logo, producers.logo) for logo in logo_candidates
    )
    other_seeds.extend(
        _signature_seed(signature, producers.signature)
        for signature in signature_candidates
    )
    for roi in structural_rois:
        related_ids = {
            candidate_id
            for raw_index in roi.line_indices
            if 0 <= int(raw_index) < len(line_id_groups)
            for candidate_id in line_id_groups[int(raw_index)]
        }
        other_seeds.append(
            _roi_seed(
                roi,
                producers.structural_roi,
                sorted(related_ids),
            )
        )
    if circle_candidates:
        if producers.circle is None:
            raise ValueError("Circle outputs require a circle producer identity")
        other_seeds.extend(
            _circle_seed(circle, producers.circle)
            for circle in circle_candidates
        )
    if symbol_candidates:
        if producers.symbol is None:
            raise ValueError("Symbol outputs require a symbol producer identity")
        other_seeds.extend(
            _symbol_seed(symbol, producers.symbol)
            for symbol in symbol_candidates
        )
    other_records, _other_groups = _materialize(
        other_seeds,
        source_page=source_page,
        transform=transform,
    )
    candidates = tuple(
        sorted(
            (*line_records, *other_records),
            key=lambda item: item.stable_candidate_id,
        )
    )
    relationships: list[CandidateRelationship] = []
    roi_records = {
        item.candidate_payload_id: item
        for item in other_records
        if isinstance(item.payload, StructuralRoiCandidatePayload)
    }
    for roi_record in roi_records.values():
        payload = roi_record.payload
        if not isinstance(payload, StructuralRoiCandidatePayload):
            continue
        for line_id in payload.related_line_candidate_ids:
            relationships.append(
                CandidateRelationship.create(
                    relationship_kind=CandidateRelationshipKind.BELONGS_TO_REGION,
                    source_candidate_id=line_id,
                    target_candidate_id=roi_record.stable_candidate_id,
                    evidence={"method": "legacy-structural-roi-line-index"},
                )
            )
    if include_spatial_relationships:
        relationships.extend(infer_basic_spatial_relationships(candidates))
    return DraftsmanCandidateManifest(
        source_page=source_page,
        transform=transform,
        candidates=candidates,
        producers=producers.active(),
        relationships=tuple(
            sorted(
                {
                    item.stable_relationship_id: item
                    for item in relationships
                }.values(),
                key=lambda item: item.stable_relationship_id,
            )
        ),
    )
