from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .auxiliary_recognition import TextCandidate
from .ocr_overlap import collapse_overlapping_candidates


_AUTO_APPROVE_CONFIDENCE = 0.50
_SINGLE_CHARACTER_CONFIDENCE = 0.55
_SHORT_ASCII_CONFIDENCE = 0.52
DEFAULT_MINIMUM_TEXT_CONFIDENCE = 0.48


class TextOutputState(str, Enum):
    EDITABLE_TEXT = "editable_text"
    TEXT_FALLBACK_OUTLINE = "text_fallback_outline"
    RESIDUAL_GRAPHIC = "residual_graphic"


@dataclass(frozen=True)
class TextOutputDecision:
    candidate: TextCandidate
    state: TextOutputState
    output_layer: str
    editable: bool
    downgrade_reason: str | None

    def payload(self) -> dict[str, object]:
        return {
            "text": str(self.candidate.text),
            "bbox": [int(value) for value in self.candidate.bbox],
            "confidence": float(self.candidate.confidence),
            "kind": str(self.candidate.kind),
            "source": str(self.candidate.source),
            "approved": bool(self.candidate.approved),
            "reviewed": bool(self.candidate.reviewed),
            "replacement_safe": bool(self.candidate.replacement_safe),
            "font_family": str(self.candidate.font_family),
            "font_file": str(self.candidate.font_file),
            "font_match_score": float(self.candidate.font_match_score),
            "rotation_deg": float(self.candidate.rotation_deg),
            "state": self.state.value,
            "output_layer": self.output_layer,
            "editable": bool(self.editable),
            "downgrade_reason": self.downgrade_reason,
        }


@dataclass(frozen=True)
class TextOutputSummary:
    ocr_candidate_count: int
    editable_text_count: int
    fallback_outline_count: int
    residual_graphic_count: int
    downgrade_reasons: tuple[tuple[str, int], ...]

    def payload(self) -> dict[str, object]:
        return {
            "ocr_candidate_count": int(self.ocr_candidate_count),
            "text_count": int(self.editable_text_count),
            "fallback_count": int(self.fallback_outline_count),
            "residual_count": int(self.residual_graphic_count),
            "downgrade_reasons": {
                reason: int(count)
                for reason, count in self.downgrade_reasons
            },
        }


def _automatic_threshold(text: str) -> float:
    compact = "".join(text.split())
    if len(compact) <= 1:
        return _SINGLE_CHARACTER_CONFIDENCE
    if len(compact) <= 3 and compact.isascii():
        return _SHORT_ASCII_CONFIDENCE
    return _AUTO_APPROVE_CONFIDENCE


def decide_text_output(
    candidate: TextCandidate,
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> TextOutputDecision:
    """Resolve one OCR candidate without using font choice as object evidence."""

    content = candidate.text.strip()
    if candidate.kind not in {
        "text_candidate",
        "dimension_text_candidate",
    }:
        return TextOutputDecision(
            candidate,
            TextOutputState.RESIDUAL_GRAPHIC,
            "RESIDUAL_GRAPHIC",
            False,
            "unsupported_candidate_kind",
        )
    if not content:
        return TextOutputDecision(
            candidate,
            TextOutputState.RESIDUAL_GRAPHIC,
            "RESIDUAL_GRAPHIC",
            False,
            "empty_ocr_content",
        )
    if not candidate.approved:
        return TextOutputDecision(
            candidate,
            TextOutputState.RESIDUAL_GRAPHIC,
            "RESIDUAL_GRAPHIC",
            False,
            "candidate_not_approved",
        )
    required = max(
        float(minimum_confidence),
        _automatic_threshold(content),
    )
    if not candidate.reviewed and float(candidate.confidence) < required:
        return TextOutputDecision(
            candidate,
            TextOutputState.RESIDUAL_GRAPHIC,
            "RESIDUAL_GRAPHIC",
            False,
            "confidence_below_contract",
        )
    if not candidate.replacement_safe:
        return TextOutputDecision(
            candidate,
            TextOutputState.TEXT_FALLBACK_OUTLINE,
            "TEXT_FALLBACK_OUTLINE",
            False,
            "replacement_unsafe",
        )
    return TextOutputDecision(
        candidate,
        TextOutputState.EDITABLE_TEXT,
        "OCR_TEXT",
        True,
        None,
    )


def text_output_decisions(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> tuple[TextOutputDecision, ...]:
    return tuple(
        decide_text_output(
            candidate,
            minimum_confidence=minimum_confidence,
        )
        for candidate in texts
    )


def accepted_ocr_texts(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> tuple[TextCandidate, ...]:
    """Return native-TEXT candidates that satisfy every contract condition."""

    accepted = [
        decision.candidate
        for decision in text_output_decisions(
            texts,
            minimum_confidence=minimum_confidence,
        )
        if decision.state is TextOutputState.EDITABLE_TEXT
    ]
    return collapse_overlapping_candidates(accepted)


def text_output_summary(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> TextOutputSummary:
    decisions = text_output_decisions(
        texts,
        minimum_confidence=minimum_confidence,
    )
    counts = Counter(decision.state for decision in decisions)
    reasons = Counter(
        decision.downgrade_reason
        for decision in decisions
        if decision.downgrade_reason is not None
    )
    return TextOutputSummary(
        ocr_candidate_count=len(decisions),
        editable_text_count=int(
            counts[TextOutputState.EDITABLE_TEXT]
        ),
        fallback_outline_count=int(
            counts[TextOutputState.TEXT_FALLBACK_OUTLINE]
        ),
        residual_graphic_count=int(
            counts[TextOutputState.RESIDUAL_GRAPHIC]
        ),
        downgrade_reasons=tuple(
            (str(reason), int(count))
            for reason, count in sorted(reasons.items())
        ),
    )
