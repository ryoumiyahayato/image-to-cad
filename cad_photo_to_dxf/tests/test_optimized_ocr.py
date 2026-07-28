from __future__ import annotations

import cv2
import numpy as np

import app.ocr_pipeline as ocr_pipeline
from app.auxiliary_recognition import TextCandidate
from app.ocr_fast import (
    TILE_OVERLAP,
    TILE_SIZE,
    deduplicate_candidates,
    prepare_safe_candidate,
)
from app.ocr_layout import tile_regions
from app.ocr_tile_filter import tile_has_probable_text
from app.ocr_pipeline import (
    _recognize_tiles,
    recognize_text_candidates_optimized,
)
from app.optimized_trace import trace_image_optimized


def _candidate(text: str, bbox, confidence: float, source: str) -> TextCandidate:
    x, y, width, height = bbox
    return TextCandidate(
        text=text,
        bbox=bbox,
        confidence=confidence,
        kind="text_candidate",
        quad=(
            (float(x), float(y)),
            (float(x + width), float(y)),
            (float(x + width), float(y + height)),
            (float(x), float(y + height)),
        ),
        source=source,
    )


def test_overview_and_tile_candidates_for_same_line_are_deduplicated() -> None:
    candidates = (
        _candidate("自动喷水灭火系统", (100, 100, 420, 52), 0.96, "rapidocr-overview"),
        _candidate("自动喷水灭火系统", (108, 102, 405, 49), 0.95, "rapidocr-tile"),
    )

    resolved = deduplicate_candidates(candidates)

    assert len(resolved) == 1
    assert resolved[0].text == "自动喷水灭火系统"


def test_adjacent_lines_are_not_collapsed_as_duplicates() -> None:
    candidates = (
        _candidate("第一行", (100, 100, 200, 40), 0.97, "rapidocr-tile"),
        _candidate("第二行", (100, 155, 200, 40), 0.97, "rapidocr-tile"),
    )

    assert len(deduplicate_candidates(candidates)) == 2


def test_large_page_uses_six_tiles_instead_of_twelve_for_common_a1_render() -> None:
    regions = tile_regions(
        (10513, 7442),
        tile_size=TILE_SIZE,
        overlap=TILE_OVERLAP,
    )

    assert len(regions) == 6


def test_blank_rule_only_tile_is_skipped_but_text_tile_is_kept() -> None:
    blank = np.full((1200, 1200), 255, dtype=np.uint8)
    for y in range(100, 1100, 100):
        cv2.line(blank, (20, y), (1180, y), 0, 2)
    for x in range(100, 1100, 200):
        cv2.line(blank, (x, 20), (x, 1180), 0, 2)

    text = blank.copy()
    cv2.putText(
        text,
        "A12",
        (350, 620),
        cv2.FONT_HERSHEY_SIMPLEX,
        3.0,
        0,
        7,
        cv2.LINE_AA,
    )

    assert not tile_has_probable_text(blank)
    assert tile_has_probable_text(text)


def test_partial_connected_stroke_is_not_automatically_replaced() -> None:
    image = np.full((220, 420), 255, dtype=np.uint8)
    points = np.asarray(
        [[40, 115], [100, 70], [155, 145], [215, 65], [285, 150], [370, 95]],
        dtype=np.int32,
    )
    cv2.polylines(image, [points], False, 0, 5, cv2.LINE_AA)
    candidate = _candidate("签名", (150, 80, 120, 55), 0.98, "rapidocr-tile")

    resolved = prepare_safe_candidate(image, candidate)

    assert not resolved.replacement_safe
    assert "连通笔画" in resolved.review_note


def test_bounded_pdf_page_skips_expensive_native_tiles(monkeypatch) -> None:
    image = np.full((600, 4800), 255, dtype=np.uint8)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("bounded pages must not invoke native OCR tiles")

    monkeypatch.setattr("app.ocr_pipeline._recognize_rapidocr_pass", fail_if_called)
    assert _recognize_tiles(image) == []


def test_large_page_uses_cleaned_native_tiles_without_repeating_overview(
    monkeypatch,
) -> None:
    image = np.full((3200, 4800), 255, dtype=np.uint8)
    calls = {"native": 0}

    def native_page(*_args, **_kwargs):
        calls["native"] += 1
        return [_candidate("图纸目录", (100, 100, 240, 48), 0.98, "rapidocr-tile")]

    def unexpected_overview(*_args, **_kwargs):
        raise AssertionError("large page must not repeat a resized overview pass")

    monkeypatch.setattr("app.ocr_pipeline._recognize_tiles", native_page)
    monkeypatch.setattr("app.ocr_pipeline._recognize_overview", unexpected_overview)
    monkeypatch.setattr(
        "app.ocr_pipeline.prepare_safe_candidate",
        lambda _image, candidate: candidate,
    )

    resolved, warnings = recognize_text_candidates_optimized(image)

    assert not warnings
    assert calls["native"] == 1
    assert [item.text for item in resolved] == ["图纸目录"]


def test_ocr_pipeline_has_no_position_or_fixed_field_template_pass() -> None:
    source = ocr_pipeline.__file__
    assert source is not None
    assert not hasattr(ocr_pipeline, "_recognize_right_title_block")
    assert not hasattr(ocr_pipeline, "_infer_ruled_title_block_labels")


def test_optimized_result_keeps_complete_preview_separate_from_residual(
    monkeypatch,
) -> None:
    image = np.full((140, 240), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "A",
        (50, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.8,
        0,
        4,
        cv2.LINE_8,
    )
    candidate = TextCandidate(
        text="A",
        bbox=(45, 45, 55, 55),
        confidence=0.99,
        kind="text_candidate",
        source="test",
        replacement_safe=True,
    )
    monkeypatch.setattr(
        "app.optimized_trace.recognize_text_candidates_optimized",
        lambda *_args, **_kwargs: ((candidate,), ()),
    )

    result = trace_image_optimized(image, enable_ocr=True)

    assert result.preview_binary is not None
    assert np.count_nonzero(result.preview_binary == 0) > 0
    assert np.count_nonzero(result.preview_binary == 0) > np.count_nonzero(
        result.binary == 0
    )
