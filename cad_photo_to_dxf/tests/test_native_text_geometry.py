from __future__ import annotations

from math import ceil, cos, floor, isclose, radians, sin
from pathlib import Path

import ezdxf
import pytest
from PySide6.QtWidgets import QApplication

from app.auxiliary_recognition import TextCandidate
from app.librecad_lff import (
    librecad_text_metrics,
    librecad_text_path,
)
from app.ocr_outline_export import add_ocr_outline_blocks


PAGE_HEIGHT = 360.0


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _source_quad(
    *,
    center: tuple[float, float],
    width: float,
    height: float,
    rotation: float,
) -> tuple[tuple[float, float], ...]:
    angle = radians(rotation)
    axis = (cos(angle), sin(angle))
    upward = (-axis[1], axis[0])
    local_points = (
        (-width * 0.5, height * 0.5),
        (width * 0.5, height * 0.5),
        (width * 0.5, -height * 0.5),
        (-width * 0.5, -height * 0.5),
    )
    dxf_points = tuple(
        (
            center[0] + axis[0] * x + upward[0] * y,
            center[1] + axis[1] * x + upward[1] * y,
        )
        for x, y in local_points
    )
    return tuple(
        (x, PAGE_HEIGHT - y)
        for x, y in dxf_points
    )


def _candidate(
    text: str,
    *,
    width: float,
    height: float,
    rotation: float,
) -> TextCandidate:
    quad = _source_quad(
        center=(180.0, 180.0),
        width=width,
        height=height,
        rotation=rotation,
    )
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    left = floor(min(xs))
    top = floor(min(ys))
    right = ceil(max(xs))
    bottom = ceil(max(ys))
    return TextCandidate(
        text=text,
        bbox=(left, top, right - left, bottom - top),
        confidence=0.99,
        kind="text_candidate",
        quad=quad,
        source="geometry-test",
        approved=True,
        reviewed=True,
        replacement_safe=True,
    )


def _geometry_values(entity) -> tuple[list[str], list[float], list[int]]:
    xdata = entity.get_xdata("OCR_TEXT_GEOMETRY")
    strings = [str(tag.value) for tag in xdata if tag.code == 1000]
    floats = [float(tag.value) for tag in xdata if tag.code == 1040]
    integers = [int(tag.value) for tag in xdata if tag.code == 1070]
    return strings, floats, integers


@pytest.mark.parametrize(
    ("content", "rotation"),
    [
        ("中文", 0.0),
        ("FIRE ALARM", 17.0),
        ("2026-07-30", -28.0),
        ("，。:;!?", 90.0),
        ("中文123ABC", 180.0),
        ("中文123ABC", 270.0),
        ("中文123ABC", 315.0),
    ],
)
def test_lff_native_text_uses_visible_bounds_for_center_width_and_height(
    content: str,
    rotation: float,
) -> None:
    metrics = librecad_text_metrics(content)
    target_height = 30.0
    target_width = target_height * metrics.width / metrics.height
    candidate = _candidate(
        content,
        width=target_width,
        height=target_height,
        rotation=rotation,
    )
    document = ezdxf.new("R2010", setup=True)

    count, entities, _bounds = add_ocr_outline_blocks(
        document,
        document.modelspace(),
        (candidate,),
        transform=lambda x, y: (x, PAGE_HEIGHT - y),
    )

    assert count == 1
    entity = entities[0]
    assert entity.dxftype() == "TEXT"
    assert entity.dxf.text == content
    strings, values, integers = _geometry_values(entity)
    (
        target_center_x,
        target_center_y,
        measured_target_width,
        measured_target_height,
        rendered_width,
        rendered_height,
        center_error,
        raw_width_factor,
        width_factor,
        measured_rotation,
    ) = values
    assert strings == [
        "metric_source=librecad-lff-visible-bounds",
        "metric_fallback=none",
    ]
    assert integers == [1, 0]
    assert isclose(target_center_x, 180.0, abs_tol=1e-9)
    assert isclose(target_center_y, 180.0, abs_tol=1e-9)
    assert isclose(measured_target_width, target_width, rel_tol=1e-9)
    assert isclose(measured_target_height, target_height, rel_tol=1e-9)
    assert isclose(rendered_width, target_width, rel_tol=1e-9)
    assert isclose(rendered_height, target_height, rel_tol=1e-9)
    assert center_error <= 1e-9
    assert isclose(raw_width_factor, 1.0, rel_tol=1e-9)
    assert isclose(width_factor, 1.0, rel_tol=1e-9)
    assert isclose(measured_rotation, rotation % 360.0, abs_tol=1e-9)
    assert isclose(float(entity.dxf.rotation), rotation % 360.0, abs_tol=1e-9)
    assert not document.audit().errors


def test_narrow_ocr_box_uses_true_fit_without_readability_clamp() -> None:
    candidate = _candidate(
        "NORMAL WIDTH TEXT",
        width=25.0,
        height=30.0,
        rotation=0.0,
    )
    document = ezdxf.new("R2010", setup=True)

    _count, entities, _bounds = add_ocr_outline_blocks(
        document,
        document.modelspace(),
        (candidate,),
        transform=lambda x, y: (x, PAGE_HEIGHT - y),
    )

    _strings, values, integers = _geometry_values(entities[0])
    target_width = values[2]
    rendered_width = values[4]
    raw_width_factor = values[7]
    width_factor = values[8]
    assert raw_width_factor < 0.72
    assert isclose(width_factor, raw_width_factor, rel_tol=1e-12)
    assert isclose(rendered_width, target_width, rel_tol=1e-9)
    assert integers[-1] == 0


def test_lff_metric_bounds_match_the_preview_stroke_path() -> None:
    for content in ("ABC", "123", "中文", "A中1，。"):
        metrics = librecad_text_metrics(content)
        bounds = librecad_text_path(content).boundingRect()
        assert isclose(float(bounds.width()), metrics.width, abs_tol=1e-9)
        assert isclose(float(bounds.height()), metrics.height, abs_tol=1e-9)
        assert isclose(float(bounds.left()), metrics.min_x, abs_tol=1e-9)
        assert isclose(float(bounds.top()), -metrics.max_y, abs_tol=1e-9)


def test_native_text_remains_editable_after_read_modify_save_read(
    tmp_path: Path,
) -> None:
    candidate = _candidate(
        "中文 ABC 123，。",
        width=180.0,
        height=30.0,
        rotation=12.0,
    )
    document = ezdxf.new("R2010", setup=True)
    add_ocr_outline_blocks(
        document,
        document.modelspace(),
        (candidate,),
        transform=lambda x, y: (x, PAGE_HEIGHT - y),
    )
    first_path = tmp_path / "native-text.dxf"
    second_path = tmp_path / "native-text-edited.dxf"
    document.saveas(first_path)

    reopened = ezdxf.readfile(first_path)
    entities = list(reopened.modelspace().query("TEXT"))
    assert len(entities) == 1
    entities[0].dxf.text = "已修改 EDITED 42！"
    reopened.saveas(second_path)

    edited = ezdxf.readfile(second_path)
    edited_entities = list(edited.modelspace().query("TEXT"))
    assert len(edited_entities) == 1
    assert edited_entities[0].dxftype() == "TEXT"
    assert edited_entities[0].dxf.text == "已修改 EDITED 42！"
    assert len(edited.modelspace().query("LWPOLYLINE")) == 0
    assert len(edited.modelspace().query("HATCH")) == 0
    assert not edited.audit().errors


def test_metric_fallback_is_explicit_when_lff_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _application()
    import app.ocr_outline_export as exporter

    monkeypatch.setattr(
        exporter,
        "librecad_font_available",
        lambda: False,
    )
    candidate = _candidate(
        "Fallback 123",
        width=140.0,
        height=30.0,
        rotation=0.0,
    )
    document = ezdxf.new("R2010", setup=True)
    _count, entities, _bounds = add_ocr_outline_blocks(
        document,
        document.modelspace(),
        (candidate,),
        transform=lambda x, y: (x, PAGE_HEIGHT - y),
    )

    strings, values, _integers = _geometry_values(entities[0])
    assert strings[0] == "metric_source=qt-tight-bounds"
    assert strings[1] == "metric_fallback=librecad_lff_unavailable"
    assert values[5] == pytest.approx(values[3])
    assert entities[0].dxftype() == "TEXT"
