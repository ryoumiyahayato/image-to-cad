from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite
from unicodedata import east_asian_width

from ezdxf.enums import TextEntityAlignment
from PySide6.QtGui import QFontMetricsF

from .auxiliary_recognition import TextCandidate
from .font_library import (
    ensure_dxf_font_style,
    find_font_face,
    qfont_for_face,
)
from .librecad_lff import (
    ensure_librecad_dxf_style,
    librecad_font_available,
    librecad_text_metrics,
)
from .text_output_contract import accepted_ocr_texts


PointTransform = Callable[[float, float], tuple[float, float]]
_XDATA_APP = "OCR_TEXT_LINE"
_CONTRACT_XDATA_APP = "TEXT_OUTPUT_CONTRACT"
_GEOMETRY_XDATA_APP = "OCR_TEXT_GEOMETRY"
# Deprecated audit reference only; canonical export must not clamp to it.
_DEPRECATED_MIN_READABLE_WIDTH_FACTOR = 0.72
_WIDTH_WARNING_NARROW = 0.20
_WIDTH_WARNING_WIDE = 4.0


@dataclass(frozen=True)
class FontExtent:
    style_name: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    em_height: float
    metric_source: str
    fallback_reason: str | None = None

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)


@dataclass(frozen=True)
class NativeTextGeometry:
    insert: tuple[float, float]
    character_height: float
    rotation: float
    width_factor: float
    transformed_quad: tuple[tuple[float, float], ...]
    target_center: tuple[float, float]
    target_width: float
    target_height: float
    rendered_width: float
    rendered_height: float
    center_error: float
    raw_width_factor: float
    width_factor_clamped: bool
    metric_source: str
    metric_fallback_reason: str | None

    def payload(self) -> dict[str, object]:
        return {
            "target_center": [
                float(self.target_center[0]),
                float(self.target_center[1]),
            ],
            "target_width": float(self.target_width),
            "target_height": float(self.target_height),
            "rendered_width": float(self.rendered_width),
            "rendered_height": float(self.rendered_height),
            "center_error": float(self.center_error),
            "rotation": float(self.rotation),
            "character_height": float(self.character_height),
            "raw_width_factor": float(self.raw_width_factor),
            "width_factor": float(self.width_factor),
            "width_factor_clamped": bool(
                self.width_factor_clamped
            ),
            "metric_source": self.metric_source,
            "metric_fallback_reason": self.metric_fallback_reason,
        }


def _candidate_quad(text: TextCandidate) -> tuple[tuple[float, float], ...]:
    if text.quad and len(text.quad) == 4:
        quad = tuple(
            (float(point[0]), float(point[1]))
            for point in text.quad
        )
        if all(
            isfinite(value)
            for point in quad
            for value in point
        ):
            top_left, top_right, bottom_right, bottom_left = quad
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
            if width > 0.0 and height > 0.0:
                return quad
    x, y, width, height = text.bbox
    return (
        (float(x), float(y)),
        (float(x + width), float(y)),
        (float(x + width), float(y + height)),
        (float(x), float(y + height)),
    )


def _normalised_content(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _portable_text_extent(
    doc,
    candidate: TextCandidate,
    content: str,
) -> FontExtent:
    face = find_font_face(
        candidate.font_family,
        candidate.font_file,
        content,
    )
    style_name = ensure_dxf_font_style(doc, face)
    em_height = 1000.0
    metrics = QFontMetricsF(qfont_for_face(face, int(em_height)))
    bounds = metrics.tightBoundingRect(content)
    min_x = float(bounds.left())
    max_x = float(bounds.right())
    min_y = -float(bounds.bottom())
    max_y = -float(bounds.top())
    values = (min_x, min_y, max_x, max_y)
    if (
        all(isfinite(value) for value in values)
        and max_x > min_x
        and max_y > min_y
    ):
        return FontExtent(
            style_name,
            min_x,
            min_y,
            max_x,
            max_y,
            em_height,
            "qt-tight-bounds",
            "librecad_lff_unavailable",
        )

    width_units = max(
        sum(_portable_advance_units(character) for character in content),
        0.01,
    )
    return FontExtent(
        style_name,
        0.0,
        -180.0,
        width_units * em_height,
        820.0,
        em_height,
        "portable-advance-fallback",
        "font_extent_unavailable",
    )


def _font_strategy(
    doc,
    candidate: TextCandidate,
    content: str,
) -> FontExtent:
    if librecad_font_available():
        metrics = librecad_text_metrics(content)
        if metrics.width > 0.0 and metrics.height > 0.0:
            return FontExtent(
                ensure_librecad_dxf_style(doc),
                metrics.min_x,
                metrics.min_y,
                metrics.max_x,
                metrics.max_y,
                metrics.em_height,
                "librecad-lff-visible-bounds",
                (
                    f"missing_lff_glyphs:{metrics.fallback_glyph_count}"
                    if metrics.fallback_glyph_count
                    else None
                ),
            )
        return FontExtent(
            ensure_librecad_dxf_style(doc),
            0.0,
            0.0,
            max(metrics.advance, 1.0),
            metrics.em_height,
            metrics.em_height,
            "librecad-lff-nominal-fallback",
            "font_extent_unavailable",
        )

    return _portable_text_extent(doc, candidate, content)


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
    metrics: FontExtent,
) -> NativeTextGeometry | None:
    transformed = tuple(
        transform(float(x), float(y))
        for x, y in quad
    )
    top_left, top_right, bottom_right, bottom_left = transformed
    top_dx = top_right[0] - top_left[0]
    top_dy = top_right[1] - top_left[1]
    bottom_dx = bottom_right[0] - bottom_left[0]
    bottom_dy = bottom_right[1] - bottom_left[1]
    baseline_dx = (top_dx + bottom_dx) * 0.5
    baseline_dy = (top_dy + bottom_dy) * 0.5
    baseline_length = hypot(baseline_dx, baseline_dy)
    target_width = (
        hypot(top_dx, top_dy)
        + hypot(bottom_dx, bottom_dy)
    ) * 0.5
    left_height = hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
    right_height = hypot(top_right[0] - bottom_right[0], top_right[1] - bottom_right[1])
    target_height = (left_height + right_height) * 0.5
    if (
        not all(
            isfinite(value)
            for point in transformed
            for value in point
        )
        or baseline_length <= 0.0
        or target_width <= 0.0
        or target_height <= 0.0
        or metrics.width <= 0.0
        or metrics.height <= 0.0
        or metrics.em_height <= 0.0
    ):
        return None

    unit_x = baseline_dx / baseline_length
    unit_y = baseline_dy / baseline_length
    up_x = -unit_y
    up_y = unit_x
    target_center = (
        sum(point[0] for point in transformed) * 0.25,
        sum(point[1] for point in transformed) * 0.25,
    )
    character_height = max(
        1e-6,
        target_height * metrics.em_height / metrics.height,
    )
    natural_width = (
        character_height * metrics.width / metrics.em_height
    )
    raw_width_factor = target_width / max(natural_width, 1e-12)
    if not isfinite(raw_width_factor) or raw_width_factor <= 0.0:
        return None
    # Canonical fit-to-quad contract: preserve the actual finite positive fit.
    # Extreme factors are observable geometry facts, not a reason to enlarge,
    # reject, outline, or otherwise change an eligible native TEXT entity.
    width_factor = raw_width_factor
    width_factor_clamped = False
    rendered_width = natural_width * width_factor
    rendered_height = (
        character_height * metrics.height / metrics.em_height
    )
    local_center_x = (
        (metrics.min_x + metrics.max_x)
        * 0.5
        * character_height
        / metrics.em_height
        * width_factor
    )
    local_center_y = (
        (metrics.min_y + metrics.max_y)
        * 0.5
        * character_height
        / metrics.em_height
    )
    insert = (
        target_center[0]
        - unit_x * local_center_x
        - up_x * local_center_y,
        target_center[1]
        - unit_y * local_center_x
        - up_y * local_center_y,
    )
    rotation = degrees(atan2(baseline_dy, baseline_dx)) % 360.0
    rendered_center = (
        insert[0]
        + unit_x * local_center_x
        + up_x * local_center_y,
        insert[1]
        + unit_y * local_center_x
        + up_y * local_center_y,
    )
    center_error = hypot(
        rendered_center[0] - target_center[0],
        rendered_center[1] - target_center[1],
    )
    return NativeTextGeometry(
        insert=insert,
        character_height=character_height,
        rotation=rotation,
        width_factor=width_factor,
        transformed_quad=transformed,
        target_center=target_center,
        target_width=target_width,
        target_height=target_height,
        rendered_width=rendered_width,
        rendered_height=rendered_height,
        center_error=center_error,
        raw_width_factor=raw_width_factor,
        width_factor_clamped=width_factor_clamped,
        metric_source=metrics.metric_source,
        metric_fallback_reason=metrics.fallback_reason,
    )


def _add_text_entity(
    layout,
    *,
    text: str,
    geometry: NativeTextGeometry,
    layer_name: str,
    style_name: str,
    line_index: int,
    candidate: TextCandidate,
):
    entity = layout.add_text(
        text,
        height=geometry.character_height,
        dxfattribs={
            "layer": layer_name,
            "color": 6,
            "style": style_name,
            "rotation": float(geometry.rotation),
            "width": float(geometry.width_factor),
            "oblique": 0.0,
        },
    )
    entity.set_placement(
        geometry.insert,
        align=TextEntityAlignment.LEFT,
    )
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
            (1040, float(geometry.insert[0])),
            (1040, float(geometry.insert[1])),
            (1040, float(geometry.rotation)),
            (1040, float(candidate.confidence)),
            (1070, int(candidate.replacement_safe)),
        ],
    )
    entity.set_xdata(
        _GEOMETRY_XDATA_APP,
        [
            (1070, 1),
            (1000, f"metric_source={geometry.metric_source}"[:250]),
            (
                1000,
                (
                    "metric_fallback="
                    f"{geometry.metric_fallback_reason or 'none'}"
                )[:250],
            ),
            (1040, float(geometry.target_center[0])),
            (1040, float(geometry.target_center[1])),
            (1040, float(geometry.target_width)),
            (1040, float(geometry.target_height)),
            (1040, float(geometry.rendered_width)),
            (1040, float(geometry.rendered_height)),
            (1040, float(geometry.center_error)),
            (1040, float(geometry.raw_width_factor)),
            (1040, float(geometry.width_factor)),
            (1040, float(geometry.rotation)),
            (1070, int(geometry.width_factor_clamped)),
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
    if _GEOMETRY_XDATA_APP not in doc.appids:
        doc.appids.add(_GEOMETRY_XDATA_APP)
    doc.header["$DWGCODEPAGE"] = "ANSI_936"

    entities: list[object] = []
    bounds: list[tuple[float, float]] = []
    approved = accepted_ocr_texts(texts, minimum_confidence=minimum_confidence)

    for line_index, candidate in enumerate(approved, start=1):
        content = _normalised_content(candidate.text)
        if not content:
            continue
        metrics = _font_strategy(
            doc, candidate, content
        )
        geometry = _line_placement_from_quad(
            _candidate_quad(candidate),
            transform=transform,
            metrics=metrics,
        )
        if geometry is None:
            raise ValueError(
                "Eligible OCR candidate has no finite DXF placement: "
                f"{candidate.bbox!r}"
            )
        entities.append(
            _add_text_entity(
                layout,
                text=content,
                geometry=geometry,
                layer_name=layer_name,
                style_name=metrics.style_name,
                line_index=line_index,
                candidate=candidate,
            )
        )
        bounds.extend(geometry.transformed_quad)

    if len(entities) != len(approved):
        raise AssertionError(
            "Native TEXT count differs from text_emit_eligible count"
        )
    return len(entities), entities, bounds
