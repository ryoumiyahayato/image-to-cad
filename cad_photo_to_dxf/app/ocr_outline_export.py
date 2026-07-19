from __future__ import annotations

from collections.abc import Callable, Sequence
from math import atan2, degrees, hypot
from unicodedata import east_asian_width

from .auxiliary_recognition import TextCandidate


PointTransform = Callable[[float, float], tuple[float, float]]
_XDATA_APP = "OCR_CHARACTER"
_AUTO_APPROVE_CONFIDENCE = 0.90
_SINGLE_CHARACTER_CONFIDENCE = 0.97
_SHORT_ASCII_CONFIDENCE = 0.94


def _automatic_threshold(text: str) -> float:
    compact = "".join(text.split())
    if len(compact) <= 1:
        return _SINGLE_CHARACTER_CONFIDENCE
    if len(compact) <= 3 and compact.isascii():
        return _SHORT_ASCII_CONFIDENCE
    return _AUTO_APPROVE_CONFIDENCE


def accepted_ocr_texts(
    texts: Sequence[TextCandidate],
    *,
    minimum_confidence: float = 0.58,
) -> tuple[TextCandidate, ...]:
    """Return OCR candidates approved manually or safe for automatic export."""

    accepted: list[TextCandidate] = []
    for item in texts:
        content = item.text.strip()
        if not content or not item.approved:
            continue
        confidence = float(item.confidence)
        if confidence < minimum_confidence:
            continue
        if item.reviewed or confidence >= _automatic_threshold(content):
            accepted.append(item)
    return tuple(accepted)


def _candidate_quad(text: TextCandidate) -> tuple[tuple[float, float], ...]:
    if text.quad and len(text.quad) == 4:
        return text.quad
    x, y, width, height = text.bbox
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )


def _character_advance_units(character: str) -> float:
    if character.isspace():
        return 0.35
    if east_asian_width(character) in {"W", "F", "A"}:
        return 1.0
    if character in "ilI1.,:;|!'`":
        return 0.38
    if character in "MW@#%&":
        return 0.90
    return 0.62


def _normalised_content(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def add_ocr_outline_blocks(
    doc,
    layout,
    texts: Sequence[TextCandidate],
    *,
    transform: PointTransform,
    layer_name: str = "OCR_TEXT",
    block_prefix: str = "OCR_LINE",
    minimum_confidence: float = 0.58,
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Write one native DXF TEXT entity for every approved OCR character.

    The historical function name is retained for call-site compatibility. It no
    longer creates outline blocks. Every Chinese character, Latin letter and digit
    becomes an independent editable TEXT entity. Glyphs are never converted to
    polylines and are never stretched with a DXF width factor. A line is fitted
    into its OCR box only by reducing one uniform text height.

    ``block_prefix`` is intentionally ignored because no INSERT blocks are made.
    The DXF stores no absolute font path from the exporting computer; the receiving
    CAD application chooses its available Unicode font or fallback.
    """

    del block_prefix
    if _XDATA_APP not in doc.appids:
        doc.appids.add(_XDATA_APP)

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    approved = accepted_ocr_texts(texts, minimum_confidence=minimum_confidence)

    for line_index, candidate in enumerate(approved, start=1):
        content = _normalised_content(candidate.text)
        if not content:
            continue

        transformed = [
            transform(float(x), float(y)) for x, y in _candidate_quad(candidate)
        ]
        top_left, top_right, bottom_right, bottom_left = transformed
        baseline_dx = bottom_right[0] - bottom_left[0]
        baseline_dy = bottom_right[1] - bottom_left[1]
        target_width = hypot(baseline_dx, baseline_dy)
        left_height = hypot(
            top_left[0] - bottom_left[0], top_left[1] - bottom_left[1]
        )
        right_height = hypot(
            top_right[0] - bottom_right[0], top_right[1] - bottom_right[1]
        )
        target_height = (left_height + right_height) * 0.5
        if target_width <= 0.0 or target_height <= 0.0:
            continue

        advance_units = [_character_advance_units(character) for character in content]
        total_units = max(sum(advance_units), 0.01)
        height_from_box = target_height * 0.82
        height_from_width = target_width * 0.96 / total_units
        character_height = max(0.01, min(height_from_box, height_from_width))
        rendered_width = character_height * total_units
        horizontal_offset = max(0.0, (target_width - rendered_width) * 0.5)

        unit_x = baseline_dx / max(target_width, 1e-9)
        unit_y = baseline_dy / max(target_width, 1e-9)
        upward_dx = top_left[0] - bottom_left[0]
        upward_dy = top_left[1] - bottom_left[1]
        upward_length = max(hypot(upward_dx, upward_dy), 1e-9)
        up_x = upward_dx / upward_length
        up_y = upward_dy / upward_length
        baseline_lift = max(0.0, (target_height - character_height) * 0.12)
        rotation = degrees(atan2(baseline_dy, baseline_dx))

        cursor = horizontal_offset
        for character_index, (character, units) in enumerate(
            zip(content, advance_units, strict=True),
            start=1,
        ):
            if not character.isspace():
                insert = (
                    bottom_left[0] + unit_x * cursor + up_x * baseline_lift,
                    bottom_left[1] + unit_y * cursor + up_y * baseline_lift,
                )
                entity = layout.add_text(
                    character,
                    height=character_height,
                    dxfattribs={
                        "layer": layer_name,
                        "color": 6,
                        "style": "Standard",
                        "rotation": float(rotation),
                    },
                )
                entity.set_placement(insert)
                entity.set_xdata(
                    _XDATA_APP,
                    [
                        (1070, int(line_index)),
                        (1070, int(character_index)),
                        (1000, content),
                    ],
                )
                entities.append(entity)
            cursor += character_height * units

        bounds.extend(transformed)

    return len(entities), entities, bounds
