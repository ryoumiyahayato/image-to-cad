from __future__ import annotations

from dataclasses import dataclass




MIN_CIRCLE_EXPORT_CONFIDENCE = 0.90


@dataclass(frozen=True)
class CircleCandidate:
    center: tuple[float, float]
    radius: float
    confidence: float


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
