from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from math import hypot, isfinite

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
    text_emit_eligible: bool
    source_outline_suppressible: bool
    hard_reject_reason: str | None
    primary_semantic: str

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
            "text_emit_eligible": bool(self.text_emit_eligible),
            "source_outline_suppressible": bool(
                self.source_outline_suppressible
            ),
            "hard_reject_reason": self.hard_reject_reason,
            "primary_semantic": self.primary_semantic,
        }


@dataclass(frozen=True)
class TextOutputSummary:
    ocr_candidate_count: int
    editable_text_count: int
    fallback_outline_count: int
    residual_graphic_count: int
    text_emit_eligible_count: int
    source_outline_suppressible_count: int
    source_outline_backup_count: int
    confidence_hard_reject_count: int
    invalid_geometry_count: int
    downgrade_reasons: tuple[tuple[str, int], ...]

    def payload(self) -> dict[str, object]:
        return {
            "ocr_candidate_count": int(self.ocr_candidate_count),
            "text_count": int(self.editable_text_count),
            "fallback_count": int(self.fallback_outline_count),
            "residual_count": int(self.residual_graphic_count),
            "text_emit_eligible_count": int(
                self.text_emit_eligible_count
            ),
            "source_outline_suppressible_count": int(
                self.source_outline_suppressible_count
            ),
            "source_outline_backup_count": int(
                self.source_outline_backup_count
            ),
            "confidence_hard_reject_count": int(
                self.confidence_hard_reject_count
            ),
            "invalid_geometry_count": int(
                self.invalid_geometry_count
            ),
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


def _valid_bbox(candidate: TextCandidate) -> bool:
    try:
        x, y, width, height = (
            float(value) for value in candidate.bbox
        )
    except (TypeError, ValueError):
        return False
    return bool(
        all(isfinite(value) for value in (x, y, width, height))
        and x >= 0.0
        and y >= 0.0
        and width > 0.0
        and height > 0.0
    )


def _valid_quad(candidate: TextCandidate) -> bool:
    quad = candidate.quad
    if quad is None or len(quad) != 4:
        return False
    try:
        points = tuple(
            (float(point[0]), float(point[1])) for point in quad
        )
    except (IndexError, TypeError, ValueError):
        return False
    if not all(
        isfinite(value)
        for point in points
        for value in point
    ):
        return False
    top_left, top_right, bottom_right, bottom_left = points
    width = (
        hypot(
            top_right[0] - top_left[0],
            top_right[1] - top_left[1],
        )
        + hypot(
            bottom_right[0] - bottom_left[0],
            bottom_right[1] - bottom_left[1],
        )
    ) * 0.5
    height = (
        hypot(
            bottom_left[0] - top_left[0],
            bottom_left[1] - top_left[1],
        )
        + hypot(
            bottom_right[0] - top_right[0],
            bottom_right[1] - top_right[1],
        )
    ) * 0.5
    return width > 0.0 and height > 0.0


def _dxf_encodable(content: str) -> bool:
    try:
        content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return "\x00" not in content


def _decision(
    candidate: TextCandidate,
    *,
    state: TextOutputState,
    output_layer: str,
    text_emit_eligible: bool,
    hard_reject_reason: str | None,
) -> TextOutputDecision:
    primary_semantic = (
        "editable_text"
        if text_emit_eligible
        else (
            "uncertain_text"
            if state is TextOutputState.TEXT_FALLBACK_OUTLINE
            else "residual_non_text"
        )
    )
    return TextOutputDecision(
        candidate=candidate,
        state=state,
        output_layer=output_layer,
        editable=text_emit_eligible,
        downgrade_reason=hard_reject_reason,
        text_emit_eligible=text_emit_eligible,
        source_outline_suppressible=bool(
            candidate.replacement_safe
        ),
        hard_reject_reason=hard_reject_reason,
        primary_semantic=primary_semantic,
    )


def decide_text_output(
    candidate: TextCandidate,
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> TextOutputDecision:
    """Resolve editable emission independently from source-outline safety."""

    content = candidate.text.strip()
    if candidate.kind not in {
        "text_candidate",
        "dimension_text_candidate",
    }:
        return _decision(
            candidate,
            state=TextOutputState.RESIDUAL_GRAPHIC,
            output_layer="RESIDUAL_GRAPHIC",
            text_emit_eligible=False,
            hard_reject_reason="unsupported_candidate_kind",
        )
    if not content:
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="empty_ocr_content",
        )
    if not _dxf_encodable(content):
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="content_not_dxf_encodable",
        )
    if not candidate.approved:
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="candidate_not_approved",
        )
    if not isfinite(float(candidate.confidence)):
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="invalid_confidence",
        )
    required = max(
        float(minimum_confidence),
        _automatic_threshold(content),
    )
    if not candidate.reviewed and float(candidate.confidence) < required:
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="confidence_below_contract",
        )
    if not (_valid_bbox(candidate) or _valid_quad(candidate)):
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="invalid_text_geometry",
        )
    if not isfinite(float(candidate.rotation_deg)):
        return _decision(
            candidate,
            state=TextOutputState.TEXT_FALLBACK_OUTLINE,
            output_layer="TEXT_FALLBACK_OUTLINE",
            text_emit_eligible=False,
            hard_reject_reason="invalid_text_geometry",
        )
    return _decision(
        candidate,
        state=TextOutputState.EDITABLE_TEXT,
        output_layer="OCR_TEXT",
        text_emit_eligible=True,
        hard_reject_reason=None,
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
        for candidate in collapse_overlapping_candidates(texts)
    )


def accepted_ocr_texts(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> tuple[TextCandidate, ...]:
    """Return every candidate eligible for one native editable TEXT."""

    return tuple(
        decision.candidate
        for decision in text_output_decisions(
            texts,
            minimum_confidence=minimum_confidence,
        )
        if decision.text_emit_eligible
    )


def suppressible_ocr_texts(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = DEFAULT_MINIMUM_TEXT_CONFIDENCE,
) -> tuple[TextCandidate, ...]:
    """Return emitted candidates whose source glyph may be suppressed."""

    return tuple(
        decision.candidate
        for decision in text_output_decisions(
            texts,
            minimum_confidence=minimum_confidence,
        )
        if (
            decision.text_emit_eligible
            and decision.source_outline_suppressible
        )
    )


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
        text_emit_eligible_count=sum(
            decision.text_emit_eligible
            for decision in decisions
        ),
        source_outline_suppressible_count=sum(
            decision.text_emit_eligible
            and decision.source_outline_suppressible
            for decision in decisions
        ),
        source_outline_backup_count=sum(
            decision.text_emit_eligible
            and not decision.source_outline_suppressible
            for decision in decisions
        ),
        confidence_hard_reject_count=sum(
            decision.hard_reject_reason
            == "confidence_below_contract"
            for decision in decisions
        ),
        invalid_geometry_count=sum(
            decision.hard_reject_reason
            == "invalid_text_geometry"
            for decision in decisions
        ),
        downgrade_reasons=tuple(
            (str(reason), int(count))
            for reason, count in sorted(reasons.items())
        ),
    )
