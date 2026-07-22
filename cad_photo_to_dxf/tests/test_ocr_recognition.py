from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from app import ocr_recognition


class _FallbackWordRapidOcr:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            word_results=[
                [
                    "火",
                    0.96,
                    [[10.0, 10.0], [60.0, 10.0], [60.0, 40.0], [10.0, 40.0]],
                ]
            ],
            boxes=None,
            txts=(),
            scores=(),
        )


class _LineAndCharacterRapidOcr:
    def __call__(self, _image, **_kwargs):
        return SimpleNamespace(
            boxes=[[[10.0, 10.0], [180.0, 10.0], [180.0, 40.0], [10.0, 40.0]]],
            txts=["火灾自动报警及联动系统图"],
            scores=[0.97],
            word_results=[
                ["火", 0.99, [[10.0, 10.0], [24.0, 10.0], [24.0, 40.0], [10.0, 40.0]]],
                ["灾", 0.99, [[25.0, 10.0], [39.0, 10.0], [39.0, 40.0], [25.0, 40.0]]],
            ],
        )


def test_word_boxes_remain_a_fallback_and_normal_flow_runs_once(monkeypatch) -> None:
    engine = _FallbackWordRapidOcr()
    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", engine)
    image = np.full((400, 1000, 3), 255, dtype=np.uint8)

    candidates, warnings = ocr_recognition.recognize_text_candidates(image)

    assert not warnings
    assert candidates
    assert engine.calls == 1
    assert all(candidate.text == "火" for candidate in candidates)
    assert all(candidate.confidence == 0.96 for candidate in candidates)
    assert all(candidate.source == "rapidocr-word-fallback" for candidate in candidates)
    assert all(candidate.quad is not None for candidate in candidates)
    overlay = ocr_recognition.render_ocr_overlay(image, candidates)
    assert overlay.shape == image.shape
    assert not np.array_equal(overlay, image)


def test_complete_line_boxes_are_preferred_over_character_boxes(monkeypatch) -> None:
    monkeypatch.setattr(
        ocr_recognition,
        "_RAPID_OCR_ENGINE",
        _LineAndCharacterRapidOcr(),
    )
    image = np.full((400, 1000, 3), 255, dtype=np.uint8)

    candidates = ocr_recognition._recognize_rapidocr_pass(image, rotation=0)

    assert len(candidates) == 1
    assert candidates[0].text == "火灾自动报警及联动系统图"
    assert candidates[0].source == "rapidocr-line"


def test_oversized_false_text_box_is_rejected(monkeypatch) -> None:
    class Oversized:
        def __call__(self, _image, **_kwargs):
            return SimpleNamespace(
                boxes=[[[5.0, 5.0], [995.0, 5.0], [995.0, 350.0], [5.0, 350.0]]],
                txts=["错误的大范围识别结果"],
                scores=[0.99],
                word_results=(),
            )

    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", Oversized())
    candidates, warnings = ocr_recognition.recognize_text_candidates(
        np.full((400, 1000, 3), 255, dtype=np.uint8)
    )

    assert candidates == ()
    assert warnings


def test_low_confidence_ocr_is_not_exported(monkeypatch) -> None:
    class LowConfidence:
        def __call__(self, _image, **_kwargs):
            return SimpleNamespace(
                word_results=[
                    [
                        "错误",
                        0.2,
                        [[1.0, 1.0], [20.0, 1.0], [20.0, 10.0], [1.0, 10.0]],
                    ]
                ],
                boxes=None,
                txts=(),
                scores=(),
            )

    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", LowConfidence())
    candidates, warnings = ocr_recognition.recognize_text_candidates(
        np.full((200, 300, 3), 255, dtype=np.uint8)
    )

    assert candidates == ()
    assert warnings


def test_installed_rapidocr_runtime_accepts_line_level_call(monkeypatch) -> None:
    monkeypatch.setattr(ocr_recognition, "_RAPID_OCR_ENGINE", None)
    image = np.full((120, 260, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "A1",
        (55, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )

    candidates = ocr_recognition._recognize_rapidocr_pass(image, rotation=0)

    assert isinstance(candidates, list)
    assert ocr_recognition._RAPID_OCR_ENGINE is not None
