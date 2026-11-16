from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, cast


MIN_CIRCLE_EXPORT_CONFIDENCE = 0.90


@dataclass(frozen=True)
class CircleCandidate:
    center: tuple[float, float]
    radius: float
    confidence: float


@dataclass(frozen=True)
class TextObservation:
    """A pre-cell observation, never a source-mask or deletion authority."""

    candidate_index: int
    text: str
    bbox: tuple[int, int, int, int]
    quad: tuple[tuple[float, float], ...] | None
    character_boxes: tuple[tuple[int, int, int, int], ...]
    rotation_deg: float
    source: str
    # Read-only actual clip result, not proof that the cell owns this text.
    cell_clip_bbox: tuple[int, int, int, int] | None = None
    cell_clip_quad: tuple[tuple[float, float], ...] | None = None

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "stage": "pre-table-cell-v1", "candidate_index": self.candidate_index,
            "text": self.text, "bbox": list(self.bbox),
            "quad": [list(p) for p in self.quad] if self.quad is not None else None,
            "character_boxes": [list(b) for b in self.character_boxes],
            "rotation_deg": self.rotation_deg, "source": self.source,
        }
        if self.cell_clip_bbox is not None:
            if self.cell_clip_quad is None:
                raise ValueError("Cell clip bbox requires a matching quad")
            result["cell_clip_bbox"] = list(self.cell_clip_bbox)
            result["cell_clip_quad"] = [list(p) for p in self.cell_clip_quad]
        return result

    @classmethod
    def from_payload(cls, value: Any) -> TextObservation | None:
        # Missing/invalid observations are unavailable; never manufacture one
        # from the already constrained candidate or discard that candidate.
        try:
            if value.get("stage") != "pre-table-cell-v1":
                return None
            bbox = tuple(int(v) for v in value["bbox"])
            quad = value["quad"]
            quad = tuple(tuple(float(v) for v in p) for p in quad) if quad is not None else None
            boxes = tuple(tuple(int(v) for v in b) for b in value["character_boxes"])
            if len(bbox) != 4 or any(len(b) != 4 for b in boxes):
                return None
            if quad is not None and (len(quad) != 4 or any(len(p) != 2 for p in quad)):
                return None
            rotation = float(value["rotation_deg"])
            if (not isfinite(rotation)
                    or (quad is not None and not all(isfinite(v) for p in quad for v in p))):
                return None
            clip_bbox, clip_quad = value.get("cell_clip_bbox"), value.get("cell_clip_quad")
            if clip_bbox is not None or clip_quad is not None:
                clip_bbox = tuple(int(v) for v in clip_bbox)
                clip_quad = tuple(tuple(float(v) for v in p) for p in clip_quad)
                if (len(clip_bbox) != 4 or len(clip_quad) != 4
                        or any(len(p) != 2 for p in clip_quad)
                        or not all(isfinite(v) for p in clip_quad for v in p)):
                    return None
            # Lengths were validated above; the cast only communicates the
            # fixed-size tuple contract to the type checker.
            character_boxes = cast(tuple[tuple[int, int, int, int], ...], boxes)
            return cls(int(value["candidate_index"]), str(value["text"]), bbox,
                       quad, character_boxes, rotation, str(value["source"]), clip_bbox, clip_quad)
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def capture(cls, item: TextCandidate, index: int) -> TextObservation | None:
        try:
            return cls.from_payload({
                "stage": "pre-table-cell-v1", "candidate_index": index,
                "text": item.text, "bbox": item.bbox, "quad": item.quad,
                "character_boxes": item.character_boxes,
                "rotation_deg": item.rotation_deg, "source": item.source,
            })
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True)
class TextCandidate:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    kind: str
    rotation_deg: float = 0.0
    quad: tuple[tuple[float, float], ...] | None = None
    source: str = "unknown"
    approved: bool = True
    reviewed: bool = False
    font_family: str = ""
    font_file: str = ""
    font_match_score: float = 0.0
    character_boxes: tuple[tuple[int, int, int, int], ...] = ()
    replacement_safe: bool = True
    review_note: str = ""
    # Display only. Never source ownership, suppression or OCR evidence.
    display_quad: tuple[tuple[float, float], ...] | None = None
    # Metadata travels with its own candidate through replace/dedup/cache.
    # It does not participate in business equality, ranking or geometry IDs.
    pre_cell_observation: TextObservation | None = field(default=None, compare=False)
    # Source row ID, one-based span order, number of spans in the logical row.
    logical_line: tuple[str, int, int] | None = None


@dataclass(frozen=True)
class SymbolCandidate:
    kind: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass
class AuxiliaryRecognitionResult:
    circles: list[CircleCandidate]
    texts: list[TextCandidate]
    dimension_texts: list[TextCandidate]
    symbols: list[SymbolCandidate]
    warnings: list[str]


def confirmable_circles(
    circles: list[CircleCandidate],
    minimum_confidence: float = MIN_CIRCLE_EXPORT_CONFIDENCE,
) -> list[CircleCandidate]:
    """Return circle candidates eligible for explicit human confirmation."""

    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("Circle confidence threshold must be between 0 and 1")
    return [circle for circle in circles if circle.confidence >= minimum_confidence]
