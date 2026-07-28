from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

from .auxiliary_recognition import TextCandidate
from .line_detect import LineSegment
from .logo_detection import LogoRegion
from .ocr_outline_export import accepted_ocr_texts
from .resolution import image_resolution_scale
from .signature_overlay import SignatureRegion
from .structural_roi import verified_structural_rule_masks


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


def _preliminary_rule_mask(binary: np.ndarray) -> np.ndarray:
    """Find long source-supported rules used only to protect them from logos."""

    foreground = _source_foreground(binary)
    horizontal, vertical = verified_structural_rule_masks(foreground)
    return cv2.max(horizontal, vertical)


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
    if not cv2.countNonZero(owned):
        return owned
    rules = _preliminary_rule_mask(binary)
    return np.where(
        (owned > 0) & (source > 0) & (rules == 0),
        255,
        0,
    ).astype(np.uint8)


def protected_object_regions(
    binary: np.ndarray,
    *,
    texts: Sequence[TextCandidate],
    logos: Sequence[LogoRegion],
    signatures: Sequence[SignatureRegion],
) -> np.ndarray:
    """Return classification-neutral regions that structural bridges cannot cross."""

    protected = _mask_like(binary)
    for item in texts:
        protected[_candidate_region_mask(item, binary.shape) > 0] = 255
    for item in (*logos, *signatures):
        clipped = _clip_box(item.bbox, binary.shape)
        if clipped is None:
            continue
        left, top, right, bottom = clipped
        protected[top:bottom, left:right] = 255
    return protected


def line_source_mask(
    binary: np.ndarray,
    lines: Sequence[LineSegment],
) -> np.ndarray:
    """Claim only ink actually present underneath reconstructed centerlines."""

    source = _source_foreground(binary)
    band = _mask_like(binary)
    scale = image_resolution_scale(binary.shape)
    maximum_thickness = max(5, int(round(16.0 * scale)))
    for line in lines:
        thickness = max(
            2,
            min(
                maximum_thickness,
                int(round(max(1.0, float(line.width)) * 1.20)) + 2,
            ),
        )
        cv2.line(
            band,
            (int(round(line.x1)), int(round(line.y1))),
            (int(round(line.x2)), int(round(line.y2))),
            255,
            thickness,
            cv2.LINE_8,
        )
    return np.where((band > 0) & (source > 0), 255, 0).astype(np.uint8)


def editable_text_source_mask(
    binary: np.ndarray,
    texts: Sequence[TextCandidate],
    *,
    excluded: np.ndarray,
) -> np.ndarray:
    """Claim source glyph pixels for accepted OCR without blanking whole boxes."""

    source = _source_foreground(binary)
    owned = _mask_like(binary)
    for item in accepted_ocr_texts(texts):
        region = _candidate_region_mask(item, binary.shape)
        owned[(region > 0) & (source > 0) & (excluded == 0)] = 255
    return owned


@dataclass(frozen=True)
class ContentOwnership:
    """One exclusive owner for every retained source foreground pixel."""

    source: np.ndarray
    line: np.ndarray
    text: np.ndarray
    graphic: np.ndarray
    signature: np.ndarray
    residual: np.ndarray
    ambiguous: np.ndarray

    def assert_valid(self) -> None:
        masks = (self.line, self.text, self.graphic, self.signature, self.residual)
        if any(mask.shape != self.source.shape for mask in masks):
            raise AssertionError("Ownership masks must have identical shapes")
        accumulated = np.zeros(self.source.shape, dtype=np.uint8)
        for mask in masks:
            if np.any((mask > 0) & (accumulated > 0)):
                raise AssertionError("A source pixel cannot have multiple owners")
            accumulated[mask > 0] = 255
        if np.any((accumulated > 0) & (self.source == 0)):
            raise AssertionError("Ownership cannot invent foreground pixels")
        if np.any((self.source > 0) & (accumulated == 0)):
            raise AssertionError("Every source foreground pixel needs an owner")

    @property
    def contour(self) -> np.ndarray:
        return cv2.max(self.graphic, self.residual)


def partition_content(
    binary: np.ndarray,
    *,
    lines: Sequence[LineSegment],
    texts: Sequence[TextCandidate],
    signatures: Sequence[SignatureRegion],
    logos: Sequence[LogoRegion] = (),
    graphic_mask: np.ndarray | None = None,
    signature_mask: np.ndarray | None = None,
) -> ContentOwnership:
    """Partition original source ink after semantic decisions are complete."""

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

    line_owned = line_source_mask(binary, lines)
    text_owned = editable_text_source_mask(
        binary,
        texts,
        excluded=np.zeros_like(binary),
    )
    raw_masks = (line_owned, text_owned, graphic_owned, signature_owned)
    claim_count = np.zeros(binary.shape, dtype=np.uint8)
    for mask in raw_masks:
        claim_count += np.where(mask > 0, 1, 0).astype(np.uint8)
    ambiguous = np.where(
        (source > 0) & (claim_count > 1),
        255,
        0,
    ).astype(np.uint8)
    line_owned, text_owned, graphic_owned, signature_owned = tuple(
        np.where((mask > 0) & (ambiguous == 0), 255, 0).astype(np.uint8)
        for mask in raw_masks
    )
    claimed = cv2.max(
        cv2.max(line_owned, text_owned),
        cv2.max(graphic_owned, signature_owned),
    )
    residual = np.where(
        (source > 0) & (claimed == 0),
        255,
        0,
    ).astype(np.uint8)
    ownership = ContentOwnership(
        source=source,
        line=line_owned,
        text=text_owned,
        graphic=graphic_owned,
        signature=signature_owned,
        residual=residual,
        ambiguous=ambiguous,
    )
    ownership.assert_valid()
    return ownership
