from __future__ import annotations

from collections.abc import Callable, Sequence
from math import atan2, degrees, hypot

from ezdxf.enums import TextEntityAlignment

from .auxiliary_recognition import TextCandidate
from .font_library import (
    character_advance_units,
    contains_cjk,
    ensure_dxf_font_style,
    find_font_face,
    font_metric_ratios,
    install_bundled_fonts_for_cad,
)
from .librecad_lff import (
    ensure_librecad_dxf_style,
    librecad_character_advance_units,
    librecad_metric_ratios,
)


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
        if item.reviewed:
            accepted.append(item)
            continue
        confidence = float(item.confidence)
        required = max(float(minimum_confidence), _automatic_threshold(content))
        if confidence >= required:
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


def _normalised_content(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _font_strategy(doc, candidate: TextCandidate, content: str):
    """Resolve the renderer that the target CAD can actually use.

    Newly recognised CJK text has no selected font and therefore defaults to
    LibreCAD's native wqy-unicode LFF. The LibreCAD review window also writes
    that explicit LFF filename. Explicit legacy TTF/OTF selections are retained
    only for backwards-compatible tests and non-LibreCAD workflows.
    """

    use_librecad_lff = candidate.font_file.casefold().endswith(".lff") or (
        contains_cjk(content) and not candidate.font_file.strip()
    )
    if use_librecad_lff:
        return (
            ensure_librecad_dxf_style(doc),
            [librecad_character_advance_units(character) for character in content],
            librecad_metric_ratios(),
        )

    face = find_font_face(candidate.font_family, candidate.font_file, content)
    return (
        ensure_dxf_font_style(doc, face),
        [character_advance_units(face, character) for character in content],
        font_metric_ratios(face),
    )


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
    """Write one native, editable DXF TEXT entity per approved character.

    Chinese text reviewed by the LibreCAD workflow uses ``wqy-unicode.lff``.
    This is different from installing a Windows OTF font: LibreCAD's own text
    engine resolves LFF files and otherwise displays missing-glyph diamonds.
    No character is converted into an INSERT block or outline polyline.
    """

    del block_prefix
    install_bundled_fonts_for_cad()
    if _XDATA_APP not in doc.appids:
        doc.appids.add(_XDATA_APP)
    doc.header["$DWGCODEPAGE"] = "ANSI_936"

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    approved = accepted_ocr_texts(texts, minimum_confidence=minimum_confidence)

    for line_index, candidate in enumerate(approved, start=1):
        content = _normalised_content(candidate.text)
        if not content:
            continue
        style_name, advance_units, metric_ratios = _font_strategy(
            doc,
            candidate,
            content,
        )

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

        total_units = max(sum(advance_units), 0.01)
        height_from_box = target_height * 0.86
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
        _ascent_ratio, descent_ratio = metric_ratios
        free_height = max(0.0, target_height - character_height)
        baseline_lift = free_height * 0.5 + character_height * descent_ratio
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
                        "style": style_name,
                        "rotation": float(rotation),
                        "width": 1.0,
                        "oblique": 0.0,
                    },
                )
                entity.set_placement(insert, align=TextEntityAlignment.LEFT)
                entity.set_xdata(
                    _XDATA_APP,
                    [
                        (1070, int(line_index)),
                        (1070, int(character_index)),
                        (1000, content),
                        (1040, float(candidate.confidence)),
                        (1070, int(candidate.reviewed)),
                        (1040, float(candidate.font_match_score)),
                    ],
                )
                entities.append(entity)
            cursor += character_height * units

        bounds.extend(transformed)

    return len(entities), entities, bounds
