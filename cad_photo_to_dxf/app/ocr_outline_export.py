from __future__ import annotations

from collections.abc import Callable, Sequence
from math import atan2, degrees, hypot
from unicodedata import east_asian_width

from ezdxf.enums import TextEntityAlignment

from .auxiliary_recognition import TextCandidate
from .font_library import (
    ensure_dxf_font_style,
    find_font_face,
)
from .librecad_lff import (
    ensure_librecad_dxf_style,
    librecad_font_available,
    librecad_character_advance_units,
    librecad_metric_ratios,
)
from .text_output_contract import accepted_ocr_texts


PointTransform = Callable[[float, float], tuple[float, float]]
_XDATA_APP = "OCR_TEXT_LINE"
_CONTRACT_XDATA_APP = "TEXT_OUTPUT_CONTRACT"
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
    if librecad_font_available():
        return (
            ensure_librecad_dxf_style(doc),
            [librecad_character_advance_units(character) for character in content],
            librecad_metric_ratios(),
        )

    face = find_font_face(
        candidate.font_family,
        candidate.font_file,
        content,
    )
    return (
        ensure_dxf_font_style(doc, face),
        [_portable_advance_units(character) for character in content],
        (0.82, 0.18),
    )


def _portable_advance_units(character: str) -> float:
    if character.isspace():
        return 0.35
    if east_asian_width(character) in {"W", "F", "A"}:
        return 1.0
    return 0.62


def _line_placement_from_quad(
    quad: tuple[tuple[float, float], ...],
    *,
    transform: PointTransform,
    units: float,
    metric_ratios: tuple[float, float],
) -> tuple[tuple[float, float], float, float, float, list[tuple[float, float]]] | None:
    transformed = [transform(float(x), float(y)) for x, y in quad]
    top_left, top_right, bottom_right, bottom_left = transformed
    baseline_dx = bottom_right[0] - bottom_left[0]
    baseline_dy = bottom_right[1] - bottom_left[1]
    target_width = hypot(baseline_dx, baseline_dy)
    left_height = hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
    right_height = hypot(top_right[0] - bottom_right[0], top_right[1] - bottom_right[1])
    target_height = (left_height + right_height) * 0.5
    if target_width <= 0.0 or target_height <= 0.0:
        return None

    character_height = max(0.01, target_height * 0.78)
    available_width = max(0.01, target_width * 0.98)
    rendered_width = character_height * max(units, 0.01)
    width_factor = max(0.25, min(4.0, available_width / max(rendered_width, 0.01)))
    horizontal_offset = target_width * 0.01
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
    insert = (
        bottom_left[0] + unit_x * horizontal_offset + up_x * baseline_lift,
        bottom_left[1] + unit_y * horizontal_offset + up_y * baseline_lift,
    )
    rotation = degrees(atan2(baseline_dy, baseline_dx))
    return insert, character_height, rotation, width_factor, transformed


def _add_text_entity(
    layout,
    *,
    text: str,
    insert: tuple[float, float],
    character_height: float,
    rotation: float,
    width_factor: float,
    layer_name: str,
    style_name: str,
    line_index: int,
    candidate: TextCandidate,
):
    entity = layout.add_text(
        text,
        height=character_height,
        dxfattribs={
            "layer": layer_name,
            "color": 6,
            "style": style_name,
            "rotation": float(rotation),
            "width": float(width_factor),
            "oblique": 0.0,
        },
    )
    entity.set_placement(insert, align=TextEntityAlignment.LEFT)
    entity.set_xdata(
        _XDATA_APP,
        [
            (1070, int(line_index)),
            (1000, text),
            (1040, float(candidate.confidence)),
            (1070, int(candidate.reviewed)),
            (1040, float(candidate.font_match_score)),
        ],
    )
    entity.set_xdata(
        _CONTRACT_XDATA_APP,
        [
            (1000, "editable_text"),
            (1000, str(candidate.source)[:250]),
            (1000, str(candidate.font_family)[:250]),
            (1000, str(candidate.font_file)[:250]),
            (1000, str(style_name)[:250]),
            (1040, float(insert[0])),
            (1040, float(insert[1])),
            (1040, float(rotation)),
            (1040, float(candidate.confidence)),
            (1070, int(candidate.replacement_safe)),
        ],
    )
    return entity


def add_ocr_outline_blocks(
    doc,
    layout,
    texts: Sequence[TextCandidate],
    *,
    transform: PointTransform,
    layer_name: str = "OCR_TEXT",
    block_prefix: str = "OCR_LINE",
    minimum_confidence: float = 0.48,
) -> tuple[int, list[object], list[tuple[float, float]]]:
    """Write each recognized source line as one native editable TEXT entity."""

    del block_prefix
    if _XDATA_APP not in doc.appids:
        doc.appids.add(_XDATA_APP)
    if _CONTRACT_XDATA_APP not in doc.appids:
        doc.appids.add(_CONTRACT_XDATA_APP)
    doc.header["$DWGCODEPAGE"] = "ANSI_936"

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    approved = accepted_ocr_texts(texts, minimum_confidence=minimum_confidence)

    for line_index, candidate in enumerate(approved, start=1):
        content = _normalised_content(candidate.text)
        if not content:
            continue
        style_name, advance_units, metric_ratios = _font_strategy(
            doc, candidate, content
        )
        total_units = max(sum(advance_units), 0.01)
        placement = _line_placement_from_quad(
            _candidate_quad(candidate),
            transform=transform,
            units=total_units,
            metric_ratios=metric_ratios,
        )
        if placement is None:
            continue
        insert, character_height, rotation, width_factor, transformed = placement
        entities.append(
            _add_text_entity(
                layout,
                text=content,
                insert=insert,
                character_height=character_height,
                rotation=rotation,
                width_factor=width_factor,
                layer_name=layer_name,
                style_name=style_name,
                line_index=line_index,
                candidate=candidate,
            )
        )
        bounds.extend(transformed)

    return len(entities), entities, bounds
