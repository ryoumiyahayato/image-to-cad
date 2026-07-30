from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .line_detect import LineSegment
from .logo_detection import LogoRegion
from .resolution import image_resolution_scale
from .signature_overlay import SignatureRegion
from .text_output_contract import (
    accepted_ocr_texts,
    suppressible_ocr_texts,
)


def _mask_like(binary: np.ndarray) -> np.ndarray:
    return np.zeros(binary.shape, dtype=np.uint8)


def _source_foreground(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0 or binary.ndim != 2:
        raise ValueError("Content ownership requires a non-empty binary page")
    if binary.dtype != np.uint8:
        raise ValueError("Content ownership requires an 8-bit binary page")
    return np.where(binary < 128, 255, 0).astype(np.uint8)


def binary_from_foreground(mask: np.ndarray) -> np.ndarray:
    """Convert a 0/255 foreground ownership mask to a trace binary image."""

    if mask.ndim != 2 or mask.dtype != np.uint8:
        raise ValueError("Foreground ownership mask must be an 8-bit 2D image")
    return np.where(mask > 0, 0, 255).astype(np.uint8)


def without_owned_pixels(binary: np.ndarray, *masks: np.ndarray) -> np.ndarray:
    """Return source ink with only the explicitly owned source pixels removed."""

    result = np.ascontiguousarray(binary.copy(), dtype=np.uint8)
    for mask in masks:
        if mask.shape != binary.shape:
            raise ValueError("Ownership masks must match the source page")
        result[mask > 0] = 255
    return result


def _clip_box(
    bbox: tuple[int, int, int, int],
    shape: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    x, y, width, height = (int(value) for value in bbox)
    page_height, page_width = shape
    left = max(0, x)
    top = max(0, y)
    right = min(page_width, x + width)
    bottom = min(page_height, y + height)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _candidate_region_mask(
    candidate: TextCandidate,
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize the OCR footprint, never its enclosing table cell."""

    mask = np.zeros(shape, dtype=np.uint8)
    if candidate.character_boxes:
        for box in candidate.character_boxes:
            clipped = _clip_box(box, shape)
            if clipped is None:
                continue
            left, top, right, bottom = clipped
            pad = max(1, int(round((bottom - top) * 0.05)))
            left = max(0, left - pad)
            top = max(0, top - pad)
            right = min(shape[1], right + pad)
            bottom = min(shape[0], bottom + pad)
            mask[top:bottom, left:right] = 255
        if cv2.countNonZero(mask):
            return mask

    if candidate.quad and len(candidate.quad) == 4:
        polygon = np.asarray(candidate.quad, dtype=np.float32)
        polygon[:, 0] = np.clip(polygon[:, 0], 0, shape[1] - 1)
        polygon[:, 1] = np.clip(polygon[:, 1], 0, shape[0] - 1)
        cv2.fillConvexPoly(mask, np.rint(polygon).astype(np.int32), 255)
        return mask

    clipped = _clip_box(candidate.bbox, shape)
    if clipped is not None:
        left, top, right, bottom = clipped
        mask[top:bottom, left:right] = 255
    return mask


def signature_source_mask(
    binary: np.ndarray,
    regions: Sequence[SignatureRegion],
) -> np.ndarray:
    """Return only source pixels belonging to validated signature masks."""

    source = _source_foreground(binary)
    owned = _mask_like(binary)
    for region in regions:
        clipped = _clip_box(region.bbox, binary.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        if region.mask.shape != (bottom - top, right - left):
            continue
        local = (region.mask > 0) & (source[top:bottom, left:right] > 0)
        owned[top:bottom, left:right][local] = 255
    return owned


def graphic_source_mask(
    binary: np.ndarray,
    logos: Sequence[LogoRegion],
) -> np.ndarray:
    """Return exact source ink for independently detected Logo objects."""

    source = _source_foreground(binary)
    owned = _mask_like(binary)
    for item in logos:
        clipped = _clip_box(item.bbox, binary.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        if item.mask.shape != (bottom - top, right - left):
            continue
        local = (item.mask > 0) & (source[top:bottom, left:right] > 0)
        owned[top:bottom, left:right][local] = 255
    return owned


@dataclass(frozen=True)
class ConnectionProtection:
    """Classification-neutral masks and guards used only for bridge safety."""

    mask: np.ndarray
    category_pixels: tuple[tuple[str, int], ...]
    guards: tuple[tuple[str, str], ...]

    def payload(self) -> dict[str, object]:
        return {
            "protected_categories": [
                category for category, _mechanism in self.guards
            ],
            "protection_guards": {
                category: mechanism
                for category, mechanism in self.guards
            },
            "category_pixels": {
                category: int(pixel_count)
                for category, pixel_count in self.category_pixels
            },
            "protected_pixels": int(cv2.countNonZero(self.mask)),
        }


def build_connection_protection(
    binary: np.ndarray,
    *,
    texts: Sequence[TextCandidate],
    logos: Sequence[LogoRegion],
    signatures: Sequence[SignatureRegion],
) -> ConnectionProtection:
    """Build explicit semantic guards without assigning source ownership."""

    protected = _mask_like(binary)
    text_mask = _mask_like(binary)
    high_confidence_text_mask = _mask_like(binary)
    dimension_number_mask = _mask_like(binary)
    accepted_text_ids = {
        id(item) for item in accepted_ocr_texts(texts)
    }
    for item in texts:
        candidate_mask = _candidate_region_mask(item, binary.shape)
        text_mask[candidate_mask > 0] = 255
        if id(item) in accepted_text_ids:
            high_confidence_text_mask[candidate_mask > 0] = 255
        if item.kind == "dimension_text_candidate":
            dimension_number_mask[candidate_mask > 0] = 255

    logo_mask = _mask_like(binary)
    for item in logos:
        clipped = _clip_box(item.bbox, binary.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        logo_mask[top:bottom, left:right] = 255
    signature_mask = _mask_like(binary)
    for item in signatures:
        clipped = _clip_box(item.bbox, binary.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        signature_mask[top:bottom, left:right] = 255

    for mask in (text_mask, logo_mask, signature_mask):
        protected[mask > 0] = 255
    category_pixels = (
        (
            "high_confidence_text",
            int(cv2.countNonZero(high_confidence_text_mask)),
        ),
        ("logo", int(cv2.countNonZero(logo_mask))),
        ("signature", int(cv2.countNonZero(signature_mask))),
        (
            "dimension_number",
            int(cv2.countNonZero(dimension_number_mask)),
        ),
    )
    guards = (
        ("high_confidence_text", "accepted_ocr_source_footprint"),
        ("logo", "independent_logo_bbox"),
        ("signature", "independent_signature_bbox"),
        (
            "engineering_symbol",
            "non_structural_source_ink_inside_structural_roi",
        ),
        ("arrow", "non_structural_source_ink_inside_structural_roi"),
        (
            "dimension_number",
            "ocr_footprint_or_non_structural_source_ink",
        ),
        (
            "leader_annotation",
            "ocr_footprint_or_non_structural_source_ink",
        ),
    )
    return ConnectionProtection(
        mask=protected,
        category_pixels=category_pixels,
        guards=guards,
    )


def protected_object_regions(
    binary: np.ndarray,
    *,
    texts: Sequence[TextCandidate],
    logos: Sequence[LogoRegion],
    signatures: Sequence[SignatureRegion],
) -> np.ndarray:
    """Return semantic regions that structural bridges cannot cross."""

    return build_connection_protection(
        binary,
        texts=texts,
        logos=logos,
        signatures=signatures,
    ).mask


def _line_claim_thickness(
    line: LineSegment,
    *,
    scale: float,
) -> int:
    maximum_thickness = max(5, int(round(16.0 * scale)))
    return max(
        2,
        min(
            maximum_thickness,
            int(round(max(1.0, float(line.width)) * 1.20)) + 2,
        ),
    )


def _rasterize_line_claims(
    lines: Sequence[LineSegment],
    *,
    shape: tuple[int, int],
) -> np.ndarray:
    band = np.zeros(shape, dtype=np.uint8)
    scale = image_resolution_scale(shape)
    for line in lines:
        cv2.line(
            band,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            _line_claim_thickness(line, scale=scale),
            cv2.LINE_8,
        )
    return band


def line_source_mask(
    binary: np.ndarray,
    lines: Sequence[LineSegment],
) -> np.ndarray:
    """Claim only source ink underneath independent line candidates."""

    source = _source_foreground(binary)
    band = _rasterize_line_claims(lines, shape=binary.shape)
    return np.where((band > 0) & (source > 0), 255, 0).astype(np.uint8)


def editable_text_source_mask(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
    *,
    excluded: np.ndarray,
) -> np.ndarray:
    """Claim only safely suppressible source glyph pixels."""

    source = _source_foreground(binary)
    owned = _mask_like(binary)
    for item in suppressible_ocr_texts(texts):
        region = _candidate_region_mask(item, binary.shape)
        owned[(region > 0) & (source > 0) & (excluded == 0)] = 255
    return owned


def text_candidate_source_mask(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
) -> np.ndarray:
    """Return source ink under every OCR candidate, without approving it."""

    source = _source_foreground(binary)
    candidates = _mask_like(binary)
    for item in texts:
        region = _candidate_region_mask(item, binary.shape)
        candidates[(region > 0) & (source > 0)] = 255
    return candidates


@dataclass(frozen=True)
class CandidateClassEvidence:
    category: str
    source: str
    candidate_count: int
    claimed_pixels: int
    confidence_minimum: float
    confidence_mean: float
    confidence_maximum: float

    def payload(self) -> dict[str, object]:
        return {
            "category": self.category,
            "source": self.source,
            "candidate_count": int(self.candidate_count),
            "claimed_pixels": int(self.claimed_pixels),
            "confidence": {
                "minimum": float(self.confidence_minimum),
                "mean": float(self.confidence_mean),
                "maximum": float(self.confidence_maximum),
            },
        }


@dataclass(frozen=True)
class OwnershipConflict:
    conflict_id: str
    bbox: tuple[int, int, int, int]
    candidate_categories: tuple[str, ...]
    candidate_confidences: tuple[tuple[str, float], ...]
    overlap_pixels: tuple[tuple[str, int], ...]
    conflict_reason: str
    arbitration_rule: str
    final_category: str
    residual_pixels: int
    downgrade_reason: str

    def payload(self) -> dict[str, object]:
        return {
            "conflict_id": self.conflict_id,
            "bbox": [int(value) for value in self.bbox],
            "candidate_categories": list(self.candidate_categories),
            "candidate_confidences": {
                category: float(confidence)
                for category, confidence in self.candidate_confidences
            },
            "overlap_pixels": {
                category: int(pixel_count)
                for category, pixel_count in self.overlap_pixels
            },
            "conflict_reason": self.conflict_reason,
            "arbitration_rule": self.arbitration_rule,
            "final_category": self.final_category,
            "residual_pixels": int(self.residual_pixels),
            "downgrade_reason": self.downgrade_reason,
        }


@dataclass(frozen=True)
class ContentOwnership:
    """One explainable final owner for every retained source foreground pixel."""

    source: np.ndarray
    line: np.ndarray
    text: np.ndarray
    logo: np.ndarray
    signature: np.ndarray
    graphic: np.ndarray
    residual: np.ndarray
    ambiguous: np.ndarray
    candidate_classes: tuple[CandidateClassEvidence, ...] = ()
    conflicts: tuple[OwnershipConflict, ...] = ()
    downgrades: tuple[dict[str, object], ...] = ()
    arbitration_rule: str = "independent_evidence_then_explicit_conflict_rules"

    def assert_valid(self) -> None:
        masks = (
            self.line,
            self.text,
            self.logo,
            self.signature,
            self.graphic,
            self.residual,
        )
        if any(mask.shape != self.source.shape for mask in masks):
            raise AssertionError("Ownership masks must have identical shapes")
        if self.ambiguous.shape != self.source.shape:
            raise AssertionError("Conflict mask must use source coordinates")
        accumulated = np.zeros(self.source.shape, dtype=np.uint8)
        for mask in masks:
            if np.any((mask > 0) & (accumulated > 0)):
                raise AssertionError("A source pixel cannot have multiple owners")
            accumulated[mask > 0] = 255
        if np.any((accumulated > 0) & (self.source == 0)):
            raise AssertionError("Ownership cannot invent foreground pixels")
        if np.any((self.source > 0) & (accumulated == 0)):
            raise AssertionError("Every source foreground pixel needs an owner")
        if np.any((self.ambiguous > 0) & (self.source == 0)):
            raise AssertionError("Conflicts cannot include background pixels")
        if np.any((self.residual > 0) & (self.ambiguous == 0)):
            raise AssertionError(
                "Residual is reserved for unresolved candidate conflicts"
            )

    @property
    def contour(self) -> np.ndarray:
        return cv2.max(
            self.logo,
            cv2.max(self.graphic, self.residual),
        )

    def payload(self) -> dict[str, object]:
        return {
            "role": "ownership-arbitration",
            "arbitration_rule": self.arbitration_rule,
            "candidate_classes": [
                candidate.payload() for candidate in self.candidate_classes
            ],
            "conflict_pixels": int(cv2.countNonZero(self.ambiguous)),
            "conflict_object_count": len(self.conflicts),
            "conflicts": [conflict.payload() for conflict in self.conflicts],
            "unresolved_conflict_pixels": int(
                cv2.countNonZero(self.residual)
            ),
            "graphic_fallback_pixels": int(
                cv2.countNonZero(self.graphic)
            ),
            "final_owner_pixels": {
                "structural_line": int(cv2.countNonZero(self.line)),
                "text": int(cv2.countNonZero(self.text)),
                "logo": int(cv2.countNonZero(self.logo)),
                "signature": int(cv2.countNonZero(self.signature)),
                "graphic": int(cv2.countNonZero(self.graphic)),
                "residual": int(cv2.countNonZero(self.residual)),
            },
            "downgrades": [dict(item) for item in self.downgrades],
        }


@dataclass(frozen=True)
class ArbitratedContent:
    lines: tuple[LineSegment, ...]
    texts: tuple[TextCandidate, ...]
    logos: tuple[LogoRegion, ...]
    signatures: tuple[SignatureRegion, ...]
    downgrades: tuple[dict[str, object], ...]


def _confidence_evidence(
    *,
    category: str,
    source: str,
    candidate_count: int,
    claimed_pixels: int,
    values: Sequence[float],
) -> CandidateClassEvidence:
    normalized = [max(0.0, min(1.0, float(value))) for value in values]
    if not normalized:
        normalized = [0.0]
    return CandidateClassEvidence(
        category=category,
        source=source,
        candidate_count=int(candidate_count),
        claimed_pixels=int(claimed_pixels),
        confidence_minimum=float(min(normalized)),
        confidence_mean=float(np.mean(normalized)),
        confidence_maximum=float(max(normalized)),
    )


def _point_has_claim(
    mask: np.ndarray,
    point: tuple[float, float],
    *,
    radius: int,
) -> bool:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    left = max(0, x - radius)
    top = max(0, y - radius)
    right = min(mask.shape[1], x + radius + 1)
    bottom = min(mask.shape[0], y + radius + 1)
    return bool(
        right > left
        and bottom > top
        and np.any(mask[top:bottom, left:right] > 0)
    )


def _strong_structural_line_mask(
    binary: np.ndarray,
    lines: Sequence[LineSegment],
    *,
    other_semantic_claims: np.ndarray,
) -> np.ndarray:
    source = _source_foreground(binary)
    band = _mask_like(binary)
    scale = image_resolution_scale(binary.shape)
    for line in lines:
        thickness = _line_claim_thickness(line, scale=scale)
        radius = max(1, (thickness + 1) // 2)
        if _point_has_claim(
            other_semantic_claims,
            (line.x1, line.y1),
            radius=radius,
        ) or _point_has_claim(
            other_semantic_claims,
            (line.x2, line.y2),
            radius=radius,
        ):
            continue
        cv2.line(
            band,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            thickness,
            cv2.LINE_8,
        )
    return np.where((band > 0) & (source > 0), 255, 0).astype(np.uint8)


def _conflict_records(
    *,
    ambiguous: np.ndarray,
    candidate_masks: dict[str, np.ndarray],
    candidate_confidences: dict[str, float],
    line_resolved: np.ndarray,
    text_resolved: np.ndarray,
    unresolved: np.ndarray,
) -> tuple[OwnershipConflict, ...]:
    records: list[OwnershipConflict] = []
    resolution_groups = (
        (
            "structural_line",
            line_resolved,
            "line_text_overlap_with_independent_line_endpoints",
            "structural_endpoints_outside_other_semantic_claims",
            "",
        ),
        (
            "text",
            text_resolved,
            "line_text_overlap_without_independent_line_endpoints",
            "accepted_text_footprint_overrides_weak_line_candidate",
            "weak_line_candidate",
        ),
        (
            "residual",
            unresolved,
            "overlapping_semantic_source_claims",
            "preserve_source_without_type_priority",
            "semantic_evidence_conflict",
        ),
    )
    conflict_index = 0
    for (
        final_category,
        decision_mask,
        conflict_reason,
        arbitration_rule,
        downgrade_reason,
    ) in resolution_groups:
        component_source = np.where(
            (ambiguous > 0) & (decision_mask > 0),
            255,
            0,
        ).astype(np.uint8)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            component_source,
            connectivity=8,
        )
        for label in range(1, count):
            x, y, width, height, area = (
                int(value) for value in stats[label]
            )
            if area <= 0:
                continue
            component = labels == label
            categories = tuple(
                category
                for category, mask in candidate_masks.items()
                if np.any(component & (mask > 0))
            )
            conflict_index += 1
            records.append(
                OwnershipConflict(
                    conflict_id=f"conflict-{conflict_index:05d}",
                    bbox=(x, y, width, height),
                    candidate_categories=categories,
                    candidate_confidences=tuple(
                        (
                            category,
                            float(candidate_confidences.get(category, 0.0)),
                        )
                        for category in categories
                    ),
                    overlap_pixels=tuple(
                        (
                            category,
                            int(np.count_nonzero(component & (mask > 0))),
                        )
                        for category, mask in candidate_masks.items()
                        if category in categories
                    ),
                    conflict_reason=conflict_reason,
                    arbitration_rule=arbitration_rule,
                    final_category=final_category,
                    residual_pixels=(
                        area if final_category == "residual" else 0
                    ),
                    downgrade_reason=downgrade_reason,
                )
            )
    return tuple(records)


def partition_content(
    binary: np.ndarray,
    *,
    lines: Sequence[LineSegment],
    texts: Sequence[TextCandidate],
    signatures: Sequence[SignatureRegion],
    logos: Sequence[LogoRegion] = (),
    graphic_mask: np.ndarray | None = None,
    signature_mask: np.ndarray | None = None,
    forced_residual: np.ndarray | None = None,
) -> ContentOwnership:
    """Arbitrate independent semantic candidates without mutating their inputs."""

    source = _source_foreground(binary)
    signature_owned = (
        signature_source_mask(binary, signatures)
        if signature_mask is None
        else np.ascontiguousarray(signature_mask, dtype=np.uint8)
    )
    graphic_owned = (
        graphic_source_mask(binary, logos)
        if graphic_mask is None
        else np.ascontiguousarray(graphic_mask, dtype=np.uint8)
    )

    line_candidate = line_source_mask(binary, lines)
    text_candidate = editable_text_source_mask(
        binary,
        texts,
        excluded=np.zeros_like(binary),
    )
    text_evidence = text_candidate_source_mask(binary, texts)
    logo_candidate = np.where(
        (graphic_owned > 0) & (source > 0),
        255,
        0,
    ).astype(np.uint8)
    signature_candidate = np.where(
        (signature_owned > 0) & (source > 0),
        255,
        0,
    ).astype(np.uint8)
    forced = (
        np.zeros_like(binary)
        if forced_residual is None
        else np.ascontiguousarray(forced_residual, dtype=np.uint8)
    )
    if forced.shape != binary.shape:
        raise ValueError("Forced residual mask must match the source page")
    forced = np.where(
        (forced > 0) & (source > 0),
        255,
        0,
    ).astype(np.uint8)
    semantic_masks = (
        line_candidate,
        text_candidate,
        logo_candidate,
        signature_candidate,
    )
    claim_count = np.zeros(binary.shape, dtype=np.uint8)
    for mask in semantic_masks:
        claim_count += np.where(mask > 0, 1, 0).astype(np.uint8)
    ambiguous = np.where(
        (source > 0) & ((claim_count > 1) | (forced > 0)),
        255,
        0,
    ).astype(np.uint8)
    other_semantic = cv2.max(
        text_candidate,
        cv2.max(logo_candidate, signature_candidate),
    )
    strong_line = _strong_structural_line_mask(
        binary,
        lines,
        other_semantic_claims=other_semantic,
    )
    line_text_only = (
        (line_candidate > 0)
        & (text_candidate > 0)
        & (logo_candidate == 0)
        & (signature_candidate == 0)
        & (forced == 0)
        & (claim_count == 2)
    )
    line_resolved = np.where(
        line_text_only & (strong_line > 0),
        255,
        0,
    ).astype(np.uint8)
    text_resolved = np.where(
        line_text_only & (strong_line == 0),
        255,
        0,
    ).astype(np.uint8)
    unresolved = np.where(
        (source > 0)
        & (
            (forced > 0)
            | (
                (claim_count > 1)
                & (line_resolved == 0)
                & (text_resolved == 0)
            )
        ),
        255,
        0,
    ).astype(np.uint8)
    exclusive = (claim_count == 1) & (forced == 0)
    line_owned = np.where(
        ((line_candidate > 0) & exclusive) | (line_resolved > 0),
        255,
        0,
    ).astype(np.uint8)
    text_owned = np.where(
        ((text_candidate > 0) & exclusive) | (text_resolved > 0),
        255,
        0,
    ).astype(np.uint8)
    logo_owned = np.where(
        (logo_candidate > 0) & exclusive,
        255,
        0,
    ).astype(np.uint8)
    signature_owned = np.where(
        (signature_candidate > 0) & exclusive,
        255,
        0,
    ).astype(np.uint8)
    graphic_fallback = np.where(
        (source > 0) & (claim_count == 0) & (forced == 0),
        255,
        0,
    ).astype(np.uint8)
    residual = unresolved

    candidate_classes = (
        _confidence_evidence(
            category="structural_line",
            source="source_supported_line_candidates",
            candidate_count=len(lines),
            claimed_pixels=int(cv2.countNonZero(line_candidate)),
            values=[
                min(
                    float(line.confidence),
                    float(line.classification_confidence),
                )
                for line in lines
            ],
        ),
        _confidence_evidence(
            category="text",
            source="ocr_text_candidate_source_footprints",
            candidate_count=len(texts),
            claimed_pixels=int(cv2.countNonZero(text_evidence)),
            values=[float(item.confidence) for item in texts],
        ),
        _confidence_evidence(
            category="logo",
            source="independent_logo_visual_masks",
            candidate_count=len(logos),
            claimed_pixels=int(cv2.countNonZero(logo_candidate)),
            values=[float(item.structural_score) for item in logos],
        ),
        _confidence_evidence(
            category="signature",
            source="independent_signature_visual_masks",
            candidate_count=len(signatures),
            claimed_pixels=int(cv2.countNonZero(signature_candidate)),
            values=[
                (
                    1.0
                    if item.visual_evidence is None
                    else float(item.visual_evidence.confidence)
                )
                for item in signatures
            ],
        ),
        _confidence_evidence(
            category="graphic",
            source="unclaimed_source_contour_fallback",
            candidate_count=1,
            claimed_pixels=int(cv2.countNonZero(graphic_fallback)),
            values=[1.0],
        ),
    )
    candidate_masks = {
        "structural_line": line_candidate,
        "text": text_candidate,
        "logo": logo_candidate,
        "signature": signature_candidate,
    }
    confidence_by_category = {
        item.category: item.confidence_maximum for item in candidate_classes
    }
    conflicts = _conflict_records(
        ambiguous=np.where(claim_count > 1, 255, 0).astype(np.uint8),
        candidate_masks=candidate_masks,
        candidate_confidences=confidence_by_category,
        line_resolved=line_resolved,
        text_resolved=text_resolved,
        unresolved=unresolved,
    )
    ownership = ContentOwnership(
        source=source,
        line=line_owned,
        text=text_owned,
        logo=logo_owned,
        signature=signature_owned,
        graphic=graphic_fallback,
        residual=residual,
        ambiguous=ambiguous,
        candidate_classes=candidate_classes,
        conflicts=conflicts,
    )
    ownership.assert_valid()
    return ownership


def _arbitrate_lines(
    lines: Sequence[LineSegment],
    *,
    ownership: ContentOwnership,
) -> tuple[tuple[LineSegment, ...], tuple[dict[str, object], ...]]:
    kept: list[LineSegment] = []
    downgrades: list[dict[str, object]] = []
    scale = image_resolution_scale(ownership.source.shape)
    for index, line in enumerate(lines):
        thickness = _line_claim_thickness(line, scale=scale)
        padding = max(1, (thickness + 1) // 2 + 1)
        left = max(
            0,
            int(np.floor(min(line.x1, line.x2))) - padding,
        )
        top = max(
            0,
            int(np.floor(min(line.y1, line.y2))) - padding,
        )
        right = min(
            ownership.source.shape[1],
            int(np.ceil(max(line.x1, line.x2))) + padding + 1,
        )
        bottom = min(
            ownership.source.shape[0],
            int(np.ceil(max(line.y1, line.y2))) + padding + 1,
        )
        local_claim = np.zeros(
            (bottom - top, right - left),
            dtype=np.uint8,
        )
        cv2.line(
            local_claim,
            (
                int(round(line.x1)) - left,
                int(round(line.y1)) - top,
            ),
            (
                int(round(line.x2)) - left,
                int(round(line.y2)) - top,
            ),
            255,
            thickness,
            cv2.LINE_8,
        )
        source_crop = ownership.source[top:bottom, left:right]
        owned_crop = ownership.line[top:bottom, left:right]
        conflicting_source_pixels = int(
            np.count_nonzero(
                (local_claim > 0)
                & (source_crop > 0)
                & (owned_crop == 0)
            )
        )
        if conflicting_source_pixels == 0:
            kept.append(line)
            continue
        downgrades.append(
            {
                "candidate_category": "structural_line",
                "candidate_index": index,
                "overlap_pixels": conflicting_source_pixels,
                "conflict_reason": "line_source_not_exclusively_owned",
                "arbitration_rule": "exported_line_requires_complete_source_ownership",
                "final_category": "graphic",
                "downgrade_reason": "weak_or_conflicting_line_candidate",
            }
        )
    return tuple(kept), tuple(downgrades)


def _arbitrate_texts(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
    *,
    ownership: ContentOwnership,
) -> tuple[tuple[TextCandidate, ...], tuple[dict[str, object], ...]]:
    source = _source_foreground(binary)
    accepted_ids = {id(item) for item in accepted_ocr_texts(texts)}
    output: list[TextCandidate] = []
    downgrades: list[dict[str, object]] = []
    for index, item in enumerate(texts):
        if id(item) not in accepted_ids:
            output.append(item)
            continue
        region = _candidate_region_mask(item, binary.shape)
        claim = (region > 0) & (source > 0)
        conflicting_pixels = int(
            np.count_nonzero(claim & (ownership.text == 0))
        )
        if conflicting_pixels == 0:
            output.append(item)
            continue
        note = item.review_note.strip()
        explanation = (
            "Unified ownership arbitration retained conflicting source "
            "pixels as structural or outline geometry."
        )
        output.append(
            replace(
                item,
                replacement_safe=False,
                review_note=(
                    explanation if not note else f"{note}; {explanation}"
                ),
            )
        )
        downgrades.append(
            {
                "candidate_category": "text",
                "candidate_index": index,
                "bbox": [int(value) for value in item.bbox],
                "overlap_pixels": conflicting_pixels,
                "conflict_reason": "text_source_not_exclusively_owned",
                "arbitration_rule": "editable_text_requires_complete_source_ownership",
                "final_category": "graphic",
                "downgrade_reason": "preserve_original_outline",
            }
        )
    return tuple(output), tuple(downgrades)


def _arbitrate_masked_regions(
    regions: Sequence[Any],
    *,
    owned: np.ndarray,
    category: str,
) -> tuple[tuple[Any, ...], tuple[dict[str, object], ...]]:
    output: list[Any] = []
    downgrades: list[dict[str, object]] = []
    for index, item in enumerate(regions):
        clipped = _clip_box(item.bbox, owned.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        local_owned = owned[top:bottom, left:right]
        original = np.ascontiguousarray(item.mask, dtype=np.uint8)
        if original.shape != local_owned.shape:
            continue
        final_mask = np.where(
            (original > 0) & (local_owned > 0),
            255,
            0,
        ).astype(np.uint8)
        removed_pixels = int(
            np.count_nonzero((original > 0) & (final_mask == 0))
        )
        if cv2.countNonZero(final_mask):
            output.append(replace(item, mask=final_mask))
        if removed_pixels:
            downgrades.append(
                {
                    "candidate_category": category,
                    "candidate_index": index,
                    "bbox": [int(value) for value in item.bbox],
                    "overlap_pixels": removed_pixels,
                    "conflict_reason": "masked_object_source_not_exclusively_owned",
                    "arbitration_rule": "retain_only_exact_exclusive_source_mask",
                    "final_category": (
                        category
                        if cv2.countNonZero(final_mask)
                        else "graphic"
                    ),
                    "downgrade_reason": "conflicting_pixels_preserved_as_outline",
                }
            )
    return tuple(output), tuple(downgrades)


def arbitrate_content_candidates(
    binary: np.ndarray,
    *,
    lines: Sequence[LineSegment],
    texts: Sequence[TextCandidate],
    logos: Sequence[LogoRegion],
    signatures: Sequence[SignatureRegion],
    ownership: ContentOwnership,
) -> ArbitratedContent:
    """Apply the unified pixel decision to exported candidate objects."""

    final_lines, line_downgrades = _arbitrate_lines(
        lines,
        ownership=ownership,
    )
    final_texts, text_downgrades = _arbitrate_texts(
        binary,
        texts,
        ownership=ownership,
    )
    final_logos, logo_downgrades = _arbitrate_masked_regions(
        logos,
        owned=ownership.logo,
        category="logo",
    )
    final_signatures, signature_downgrades = _arbitrate_masked_regions(
        signatures,
        owned=ownership.signature,
        category="signature",
    )
    return ArbitratedContent(
        lines=final_lines,
        texts=final_texts,
        logos=tuple(final_logos),
        signatures=tuple(final_signatures),
        downgrades=(
            line_downgrades
            + text_downgrades
            + logo_downgrades
            + signature_downgrades
        ),
    )


def finalize_content_ownership(
    binary: np.ndarray,
    *,
    candidates: ContentOwnership,
    arbitrated: ArbitratedContent,
) -> ContentOwnership:
    """Repartition final objects while retaining unresolved conflict pixels."""

    final = partition_content(
        binary,
        lines=arbitrated.lines,
        texts=arbitrated.texts,
        logos=arbitrated.logos,
        signatures=arbitrated.signatures,
        forced_residual=candidates.residual,
    )
    final = replace(
        final,
        ambiguous=candidates.ambiguous,
        candidate_classes=candidates.candidate_classes,
        conflicts=candidates.conflicts,
        downgrades=arbitrated.downgrades,
    )
    final.assert_valid()
    return final
